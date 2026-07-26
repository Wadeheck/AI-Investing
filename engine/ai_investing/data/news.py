"""News ingestion + LLM-powered sentiment, hype detection, and global briefing.

Everything here is best-effort and degrades gracefully: no network or no API key
just yields an empty/neutral context, and the engine keeps running on price signals.

Provider priority (cost-first): LOCAL open-source model via Ollama (FREE — e.g.
qwen3.6:27b, preferred whenever the server is up and LLM_PREFER_LOCAL=true) >
Anthropic Claude > BytePlus ModelArk > DeepSeek > none. A failed local call falls
through to the cloud chain transparently. All APIs are called directly over
urllib so no SDK install is required.

Feed fetching uses conditional GET (ETag / If-Modified-Since) with a small disk
cache, so polling every 5 minutes costs ~zero bandwidth when nothing changed.
"""
from __future__ import annotations

import json
import re as _re
import time
import urllib.error
import urllib.request
from typing import Optional
from xml.etree import ElementTree

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
BYTEPLUS_URL = "https://ark.ap-southeast.bytepluses.com/api/v3/chat/completions"

# local server availability is probed at most once per this many seconds
_LOCAL_PROBE_TTL = 600.0
_local_probe: dict = {"ts": 0.0, "ok": False}


def _call_claude(prompt: str, settings, max_tokens: int = 1500) -> Optional[str]:
    body = json.dumps({
        "model": settings.anthropic_model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(ANTHROPIC_URL, data=body, method="POST", headers={
        "content-type": "application/json",
        "x-api-key": settings.anthropic_api_key,
        "anthropic-version": "2023-06-01",
    })
    with urllib.request.urlopen(req, timeout=60) as resp:
        payload = json.loads(resp.read().decode())
    parts = [b.get("text", "") for b in payload.get("content", []) if b.get("type") == "text"]
    return "".join(parts).strip()


def _call_deepseek(prompt: str, settings, max_tokens: int = 1500) -> Optional[str]:
    body = json.dumps({
        "model": settings.deepseek_model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(DEEPSEEK_URL, data=body, method="POST", headers={
        "content-type": "application/json",
        "authorization": f"Bearer {settings.deepseek_api_key}",
    })
    with urllib.request.urlopen(req, timeout=60) as resp:
        payload = json.loads(resp.read().decode())
    choices = payload.get("choices") or [{}]
    return (choices[0].get("message") or {}).get("content", "").strip()


def _call_byteplus(prompt: str, settings, model: str, max_tokens: int = 1500) -> Optional[str]:
    body = json.dumps({
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(BYTEPLUS_URL, data=body, method="POST", headers={
        "content-type": "application/json",
        "authorization": f"Bearer {settings.byteplus_api_key}",
    })
    with urllib.request.urlopen(req, timeout=60) as resp:
        payload = json.loads(resp.read().decode())
    choices = payload.get("choices") or [{}]
    return (choices[0].get("message") or {}).get("content", "").strip()


def local_llm_available(settings) -> bool:
    """Is the local Ollama server up? Cheap probe, cached for 10 minutes."""
    if not settings.local_llm_url:
        return False
    now = time.time()
    if now - _local_probe["ts"] < _LOCAL_PROBE_TTL:
        return _local_probe["ok"]
    ok = False
    try:
        req = urllib.request.Request(settings.local_llm_url.rstrip("/") + "/api/tags")
        with urllib.request.urlopen(req, timeout=3) as resp:
            names = [m.get("name", "") for m in json.loads(resp.read().decode()).get("models", [])]
        ok = settings.local_llm_model in names or bool(names)
    except Exception:
        ok = False
    _local_probe.update(ts=now, ok=ok)
    return ok


def _call_local(prompt: str, settings, max_tokens: int = 1500, tier: str = "fast",
                json_mode: bool = False) -> Optional[str]:
    """Ollama /api/chat. The fast tier (per-cycle digestion volume) runs the small
    model; the smart tier (daily briefing) runs the big one. think=False
    suppresses qwen3's reasoning stream; json_mode forces a valid JSON object
    (small models like to drop the outer braces otherwise)."""
    payload: dict = {
        "model": settings.local_llm_model if tier == "smart" else settings.local_llm_model_fast,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "think": False,
        "options": {"num_predict": max_tokens, "temperature": 0.2},
    }
    if json_mode:
        payload["format"] = "json"
    body = json.dumps(payload).encode()
    req = urllib.request.Request(settings.local_llm_url.rstrip("/") + "/api/chat",
                                 data=body, method="POST",
                                 headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as resp:
        payload = json.loads(resp.read().decode())
    return ((payload.get("message") or {}).get("content") or "").strip()


def llm_ready(settings) -> bool:
    """Any brain-capable model reachable — a cloud key OR the free local server."""
    return settings.llm_available or local_llm_available(settings)


def _call_llm(prompt: str, settings, max_tokens: int = 1500, tier: str = "fast",
              json_mode: bool = False) -> Optional[str]:
    """Cost-first routing: FREE local model whenever it's up (both tiers), then
    Anthropic > BytePlus > DeepSeek. `tier` ('fast'|'smart') picks the BytePlus
    model on the cloud path. A local failure falls through to the cloud chain."""
    if settings.llm_prefer_local and local_llm_available(settings):
        try:
            out = _call_local(prompt, settings, max_tokens, tier, json_mode)
            if out:
                return out
        except Exception:
            _local_probe.update(ts=time.time(), ok=False)   # re-probe later
    try:
        if settings.anthropic_api_key:
            return _call_claude(prompt, settings, max_tokens)
        if settings.byteplus_api_key:
            model = settings.byteplus_model_smart if tier == "smart" else settings.byteplus_model_fast
            return _call_byteplus(prompt, settings, model, max_tokens)
        if settings.deepseek_api_key:
            return _call_deepseek(prompt, settings, max_tokens)
    except Exception:
        return None
    return None


def _extract_json(text: str) -> Optional[dict]:
    """Pull the first JSON object out of a model response."""
    if not text:
        return None
    # local reasoning models may leak <think> blocks (which can contain braces)
    text = _re.sub(r"<think>.*?</think>", "", text, flags=_re.S)
    start, depth = text.find("{"), 0
    if start < 0:
        return None
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _load_feed_cache(settings) -> dict:
    try:
        with open(settings.brain.feed_cache_path) as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError, AttributeError):
        return {}


def _save_feed_cache(settings, cache: dict) -> None:
    import os
    try:
        path = settings.brain.feed_cache_path
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w") as fh:
            json.dump(cache, fh)
    except (OSError, AttributeError):
        pass


def _parse_feed(data: bytes, source: str, limit: int) -> list[dict]:
    root = ElementTree.fromstring(data)
    items, taken = [], 0
    # RSS <item> and Atom <entry>
    ns_entry = "{http://www.w3.org/2005/Atom}entry"
    ns_title = "{http://www.w3.org/2005/Atom}title"
    for item in list(root.iter("item")) + list(root.iter(ns_entry)):
        title = (item.findtext("title") or item.findtext(ns_title) or "").strip()
        if not title:
            continue
        items.append({
            "title": title,
            "summary": (item.findtext("description") or "").strip()[:300],
            "published": (item.findtext("pubDate") or "").strip(),
            "source": source,
        })
        taken += 1
        if taken >= limit:
            break
    return items


def fetch_headlines(settings, limit_per_feed: int = 15) -> list[dict]:
    """Poll all feeds with conditional GET: unchanged feeds answer 304 and cost
    nothing; their last parsed items are replayed from the disk cache (the brain's
    article store dedupes them anyway, so nothing is re-digested)."""
    cache = _load_feed_cache(settings)
    headlines: list[dict] = []
    dirty = False
    for feed in settings.news_rss:
        source = feed.split("//")[-1].split("/")[0].replace("www.", "")
        entry = cache.get(feed, {})
        headers = {"user-agent": "ai-investing/0.1 (rss reader)"}
        if entry.get("etag"):
            headers["if-none-match"] = entry["etag"]
        if entry.get("last_modified"):
            headers["if-modified-since"] = entry["last_modified"]
        try:
            req = urllib.request.Request(feed, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                items = _parse_feed(resp.read(), source, limit_per_feed)
                cache[feed] = {"etag": resp.headers.get("ETag", ""),
                               "last_modified": resp.headers.get("Last-Modified", ""),
                               "items": items, "fetched": time.time(), "status": 200}
                dirty = True
        except urllib.error.HTTPError as exc:
            if exc.code == 304 and entry.get("items"):
                items = entry["items"]          # unchanged — replay cached parse
            else:
                cache.setdefault(feed, {})["status"] = exc.code
                dirty = True
                continue
        except Exception:
            items = entry.get("items") or []    # network blip — stale beats nothing
            if not items:
                continue
        headlines.extend(items)
    if dirty:
        _save_feed_cache(settings, cache)
    return headlines


def analyze_with_claude(headlines: list[dict], symbols: list[str], settings) -> Optional[dict]:
    if not headlines or not llm_ready(settings):
        return None
    lines = "\n".join(f"- {h['title']}" for h in headlines[:60])
    prompt = f"""You are a markets analyst screening news for an automated trading system.

WATCHED TICKERS: {", ".join(symbols)}

HEADLINES:
{lines}

Return ONLY a JSON object, no prose, with this exact shape:
{{
  "briefing": "<=120 words on the most important global market-moving developments right now",
  "assets": {{
    "<TICKER>": {{
      "score": <number -1..1, net news sentiment>,
      "confidence": <number 0..1>,
      "summary": "<one short sentence>",
      "promotional": <true if news is someone talking the asset UP / hype / pump>,
      "political": <true if a politician/president/official is driving the move>,
      "intensity": <number 0..1, how loud/manipulative the hype is>
    }}
  }}
}}
Only include tickers that actually appear in the news. Flag pump-and-dump / meme /
political-hype dynamics aggressively -- the system uses these to FADE hype."""
    return _extract_json(_call_llm(prompt, settings, max_tokens=1800, tier="fast",
                                   json_mode=True) or "")


def _load_sentiment_cache(settings) -> dict:
    try:
        with open(settings.brain.sentiment_cache_path) as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_sentiment_cache(settings, cache: dict) -> None:
    import os
    try:
        path = settings.brain.sentiment_cache_path
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w") as fh:
            json.dump(cache, fh)
    except OSError:
        pass


def build_market_context(settings, assets) -> dict:
    """Compute the per-cycle shared context: sentiment scores, hype flags, briefing.

    Cost design: the brain runs FIRST and dedupes headlines against brain.db, so
    the per-ticker sentiment LLM call only sees NEVER-SEEN headlines. When nothing
    new happened, no LLM is called at all — scores replay from a 24h disk cache."""
    symbols = [a.symbol for a in assets]
    ctx: dict = {"sentiment_scores": {}, "hype_flags": {}, "briefing": "", "headlines": []}
    headlines = fetch_headlines(settings)
    ctx["headlines"] = headlines

    brain = None
    if settings.brain.enabled:
        try:
            from ai_investing.brain import Brain
            from ai_investing.data import macro as macro_mod
            brain = Brain(settings)
            ctx["brain"] = brain.think(headlines, macro=macro_mod.get_snapshot(settings))
        except Exception as exc:   # the brain is additive; never take the engine down
            print(f"  [brain] skipped this cycle: {type(exc).__name__}: {exc}")
            brain = None

    to_score = brain.last_new_headlines if brain is not None else headlines
    cache = _load_sentiment_cache(settings)
    if to_score:
        analysis = analyze_with_claude(to_score, symbols, settings)
        if analysis:
            now = time.time()
            cache["_briefing"] = {"text": analysis.get("briefing", ""), "ts": now}
            for sym, a in (analysis.get("assets") or {}).items():
                cache[sym] = {
                    "score": a.get("score", 0.0),
                    "confidence": a.get("confidence", 0.0),
                    "summary": a.get("summary", ""),
                    "promotional": bool(a.get("promotional")),
                    "political": bool(a.get("political")),
                    "intensity": a.get("intensity", 0.0),
                    "ts": now,
                }
            _save_sentiment_cache(settings, cache)

    # serve from cache (fresh <24h), whether or not the LLM ran this cycle
    horizon = time.time() - 24 * 3600
    brief = cache.get("_briefing") or {}
    if brief.get("ts", 0) > horizon:
        ctx["briefing"] = brief.get("text", "")
    for sym, a in cache.items():
        if sym.startswith("_") or a.get("ts", 0) <= horizon:
            continue
        age_h = (time.time() - a["ts"]) / 3600.0
        fade = max(0.3, 1.0 - age_h / 24.0)     # old news matters less
        ctx["sentiment_scores"][sym] = {
            "score": a.get("score", 0.0) * fade,
            "confidence": a.get("confidence", 0.0) * fade,
            "summary": a.get("summary", ""),
        }
        ctx["hype_flags"][sym] = {
            "promotional": bool(a.get("promotional")),
            "political": bool(a.get("political")),
            "intensity": a.get("intensity", 0.0) * fade,
        }

    if settings.altdata.enabled:
        _merge_altdata(settings, assets, ctx)
    return ctx


def _merge_altdata(settings, assets, ctx: dict) -> None:
    """Fold live alt-data (options flow / crypto hype / social velocity) into the hype
    flags and sentiment so the PoliticalHypeSignal reacts to real manipulation signals."""
    from ai_investing.data import altdata
    for a in assets:
        try:
            agg = altdata.aggregate(altdata.collect(settings, a.symbol, a.asset_class.value))
        except Exception:
            continue
        if not agg["available"]:
            continue
        hf = ctx["hype_flags"].get(a.symbol, {"promotional": False, "political": False, "intensity": 0.0})
        hf["intensity"] = max(float(hf.get("intensity", 0.0)), agg["intensity"])
        if agg["intensity"] >= 0.5:
            hf["promotional"] = True
        hf["altdata"] = agg["detail"]
        ctx["hype_flags"][a.symbol] = hf

        ss = ctx["sentiment_scores"].get(a.symbol, {"score": 0.0, "confidence": 0.0, "summary": ""})
        ss["score"] = max(-1.0, min(1.0, 0.6 * float(ss.get("score", 0.0)) + 0.4 * agg["bullish"]))
        ss["confidence"] = max(float(ss.get("confidence", 0.0)), min(1.0, agg["intensity"]))
        ss["summary"] = (ss.get("summary", "") + " | alt: " + agg["detail"])[:200]
        ctx["sentiment_scores"][a.symbol] = ss


def global_briefing(settings) -> str:
    """Standalone world briefing for the `--briefing` command."""
    headlines = fetch_headlines(settings)
    if not headlines:
        return "No headlines fetched (check NEWS_RSS / connectivity)."
    if not llm_ready(settings):
        return "No LLM reachable (start Ollama, or set an API key) for an AI briefing. Latest headlines:\n" + \
            "\n".join(f"  • {h['title']}" for h in headlines[:15])
    lines = "\n".join(f"- {h['title']}" for h in headlines[:60])
    prompt = ("Give me a concise, decision-useful global briefing (<=250 words) for an "
              "investor covering stocks and crypto. Group into: Macro/Rates, Geopolitics, "
              "Crypto, and Risks/Manipulation to watch. Headlines:\n" + lines)
    return _call_llm(prompt, settings, max_tokens=1200, tier="smart") or "Briefing unavailable."
