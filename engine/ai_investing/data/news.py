"""News ingestion + Claude-powered sentiment, hype detection, and global briefing.

Everything here is best-effort and degrades gracefully: no network or no API key
just yields an empty/neutral context, and the engine keeps running on price signals.
The Anthropic API is called directly over urllib so no SDK install is required.
"""
from __future__ import annotations

import json
import urllib.request
from typing import Optional
from xml.etree import ElementTree

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"


def _call_claude(prompt: str, settings, max_tokens: int = 1500) -> Optional[str]:
    if not settings.anthropic_api_key:
        return None
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
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode())
        parts = [b.get("text", "") for b in payload.get("content", []) if b.get("type") == "text"]
        return "".join(parts).strip()
    except Exception:
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
    if not headlines or not settings.anthropic_api_key:
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
    return _extract_json(_call_claude(prompt, settings, max_tokens=1800) or "")


def build_market_context(settings, symbols: list[str]) -> dict:
    """Compute the per-cycle shared context: sentiment scores, hype flags, briefing."""
    ctx: dict = {"sentiment_scores": {}, "hype_flags": {}, "briefing": "", "headlines": []}
    headlines = fetch_headlines(settings)
    ctx["headlines"] = headlines
    analysis = analyze_with_claude(headlines, symbols, settings)
    if not analysis:
        return ctx
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
    return ctx


def global_briefing(settings) -> str:
    """Standalone world briefing for the `--briefing` command."""
    headlines = fetch_headlines(settings)
    if not headlines:
        return "No headlines fetched (check NEWS_RSS / connectivity)."
    if not settings.anthropic_api_key:
        return "Set ANTHROPIC_API_KEY for an AI briefing. Latest headlines:\n" + \
            "\n".join(f"  • {h['title']}" for h in headlines[:15])
    lines = "\n".join(f"- {h['title']}" for h in headlines[:60])
    prompt = ("Give me a concise, decision-useful global briefing (<=250 words) for an "
              "investor covering stocks and crypto. Group into: Macro/Rates, Geopolitics, "
              "Crypto, and Risks/Manipulation to watch. Headlines:\n" + lines)
    return _call_claude(prompt, settings, max_tokens=1200) or "Briefing unavailable."
