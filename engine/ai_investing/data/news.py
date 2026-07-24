"""News ingestion + LLM-powered sentiment, hype detection, and global briefing.

Everything here is best-effort and degrades gracefully: no network or no API key
just yields an empty/neutral context, and the engine keeps running on price signals.
Provider priority: Anthropic Claude (if ANTHROPIC_API_KEY set) > BytePlus ModelArk
(if BYTEPLUS_API_KEY set) > DeepSeek (if DEEPSEEK_API_KEY set) > none. BytePlus
uses its FAST model for high-volume per-cycle sentiment scoring and its SMART
model for the on-demand global briefing. All APIs are called directly over
urllib so no SDK install is required.
"""
from __future__ import annotations

import json
import urllib.request
from typing import Optional
from xml.etree import ElementTree

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
BYTEPLUS_URL = "https://ark.ap-southeast.bytepluses.com/api/v3/chat/completions"


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


def _call_llm(prompt: str, settings, max_tokens: int = 1500, tier: str = "fast") -> Optional[str]:
    """Anthropic > BytePlus > DeepSeek. `tier` ('fast'|'smart') picks the BytePlus model."""
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


def fetch_headlines(settings, limit_per_feed: int = 15) -> list[dict]:
    headlines: list[dict] = []
    for feed in settings.news_rss:
        try:
            with urllib.request.urlopen(feed, timeout=15) as resp:
                root = ElementTree.fromstring(resp.read())
        except Exception:
            continue
        taken = 0
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            if not title:
                continue
            headlines.append({
                "title": title,
                "summary": (item.findtext("description") or "").strip()[:300],
                "published": (item.findtext("pubDate") or "").strip(),
            })
            taken += 1
            if taken >= limit_per_feed:
                break
    return headlines


def analyze_with_claude(headlines: list[dict], symbols: list[str], settings) -> Optional[dict]:
    if not headlines or not settings.llm_available:
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
    return _extract_json(_call_llm(prompt, settings, max_tokens=1800, tier="fast") or "")


def build_market_context(settings, assets) -> dict:
    """Compute the per-cycle shared context: sentiment scores, hype flags, briefing.
    `assets` is a list of Asset (symbol + asset_class) so alt-data can route correctly."""
    symbols = [a.symbol for a in assets]
    ctx: dict = {"sentiment_scores": {}, "hype_flags": {}, "briefing": "", "headlines": []}
    headlines = fetch_headlines(settings)
    ctx["headlines"] = headlines

    analysis = analyze_with_claude(headlines, symbols, settings)
    if analysis:
        ctx["briefing"] = analysis.get("briefing", "")
        for sym, a in (analysis.get("assets") or {}).items():
            ctx["sentiment_scores"][sym] = {
                "score": a.get("score", 0.0),
                "confidence": a.get("confidence", 0.0),
                "summary": a.get("summary", ""),
            }
            ctx["hype_flags"][sym] = {
                "promotional": bool(a.get("promotional")),
                "political": bool(a.get("political")),
                "intensity": a.get("intensity", 0.0),
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
    if not settings.llm_available:
        return "Set DEEPSEEK_API_KEY, BYTEPLUS_API_KEY, or ANTHROPIC_API_KEY for an AI briefing. Latest headlines:\n" + \
            "\n".join(f"  • {h['title']}" for h in headlines[:15])
    lines = "\n".join(f"- {h['title']}" for h in headlines[:60])
    prompt = ("Give me a concise, decision-useful global briefing (<=250 words) for an "
              "investor covering stocks and crypto. Group into: Macro/Rates, Geopolitics, "
              "Crypto, and Risks/Manipulation to watch. Headlines:\n" + lines)
    return _call_llm(prompt, settings, max_tokens=1200, tier="smart") or "Briefing unavailable."
