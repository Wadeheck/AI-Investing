"""Structured event extraction + credibility scoring (signal vs. noise).

Headlines are full of engineered noise — pumps, planted narratives, single-source
"exclusives", influencer hype. Every extracted event therefore gets a credibility
score in [0,1] built from things manipulation finds hard to fake:

  * source trust     — wire services and papers-of-record > unknown blogs/social
  * corroboration    — the same story appearing across independent feeds
  * manipulation     — the LLM's own read of promotional/planted language
  * verifiability    — official/actor-attributed events beat anonymous "sources say"

Events below the credibility threshold are kept (visible in the dashboard, labeled
noise) but do NOT propagate through the graph and do NOT move positions.

Each event also carries an emotion read (fear/greed/euphoria/panic/anger/hope) —
the crowd's emotional charge is itself information, and it feeds the market-emotion
gauge in the regime state.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from ai_investing.data.news import _call_llm, _extract_json, llm_ready

EVENT_TYPES = ["monetary_policy", "fiscal_policy", "trade_policy", "regulation",
               "geopolitics", "earnings", "supply_chain", "commodity", "technology",
               "market_flow", "rumor_hype", "other"]

EMOTIONS = ["fear", "greed", "euphoria", "panic", "anger", "hope", "complacency", "neutral"]

# Default per-source trust. Keyed by substring of the feed/source host or name.
SOURCE_TRUST = {
    "reuters": 0.95, "wsj": 0.9, "dowjones": 0.9, "dj.com": 0.9, "bloomberg": 0.9,
    "ft.com": 0.9, "bbc": 0.85, "cnbc": 0.75, "nikkei": 0.85, "scmp": 0.75,
    "caixin": 0.8, "straitstimes": 0.8, "businesstimes": 0.8, "coindesk": 0.6,
    "cointelegraph": 0.45, "reddit": 0.25, "twitter": 0.25, "x.com": 0.25,
    "substack": 0.35, "seekingalpha": 0.45, "zerohedge": 0.3, "benzinga": 0.45,
}
DEFAULT_TRUST = 0.5

_HYPE_WORDS = re.compile(
    r"\b(to the moon|skyrocket|explode|guaranteed|can't lose|100x|10x|massive gains|"
    r"next nvidia|next bitcoin|get in now|don't miss|insider says|sources say|"
    r"could soar|set to surge|unstoppable)\b", re.I)


def source_trust(source: str) -> float:
    s = (source or "").lower()
    for key, val in SOURCE_TRUST.items():
        if key in s:
            return val
    return DEFAULT_TRUST


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{4,}", text.lower())
            if w not in ("this", "that", "with", "from", "after", "amid", "over", "says")}


def corroboration(headline: str, source: str, all_headlines: list[dict]) -> int:
    """How many OTHER sources carry a substantially similar story (token overlap)."""
    t = _tokens(headline)
    if not t:
        return 0
    others = 0
    for h in all_headlines:
        if h.get("title") == headline or h.get("source", "") == source:
            continue
        overlap = len(t & _tokens(h.get("title", "")))
        # rephrased duplicates share the facts, not the words: 2+ meaty tokens
        # covering a quarter of the headline is enough to count as corroboration
        if overlap >= max(2, len(t) // 4):
            others += 1
    return others


def credibility(event: dict, all_headlines: list[dict]) -> float:
    """Blend source trust, corroboration, manipulation likelihood, and hype language
    into one credibility score. This is the noise filter."""
    src = event.get("source", "")
    headline = event.get("headline", event.get("summary", ""))
    trust = source_trust(src)
    corr = min(2, corroboration(headline, src, all_headlines))
    manip = max(0.0, min(1.0, float(event.get("manipulation_likelihood", 0.0))))
    hype_pen = 0.15 if _HYPE_WORDS.search(headline or "") else 0.0
    official = 0.1 if event.get("type") in ("monetary_policy", "fiscal_policy",
                                            "trade_policy", "regulation") else 0.0
    score = 0.15 + 0.45 * trust + 0.15 * (corr / 2) + official - 0.5 * manip - hype_pen
    return max(0.0, min(1.0, score))


def _prompt(headlines: list[dict], node_ids: list[str]) -> str:
    lines = "\n".join(f"- [{h.get('source', '?')}] {h['title']}" for h in headlines[:60])
    return f"""You are the macro brain of an automated trading system. Extract structured
EVENTS from these headlines. Markets are full of engineered noise — planted stories,
pumps, hype. Judge each event skeptically.

KNOWN GRAPH NODES (tag events ONLY with ids from this list):
{", ".join(node_ids)}

HEADLINES:
{lines}

Return ONLY JSON:
{{
  "events": [
    {{
      "summary": "<one line, what actually happened>",
      "headline": "<the headline this came from, verbatim>",
      "source": "<the [source] tag of that headline>",
      "type": "<one of: {", ".join(EVENT_TYPES)}>",
      "nodes": ["<1-3 node ids where the shock ORIGINATES — the thing that actually
                 changed (a policy node, a factor, a commodity). Do NOT tag sectors or
                 themes that are merely AFFECTED downstream; the relationship graph
                 propagates those itself>"],
      "polarity": <-1..1, direction of the named quantity on those origin nodes (up=+):
                   a rate CUT is -1 on the rate node; tighter export controls are +1 on
                   the controls node; escalating tension is +1 on the tension node>,
      "magnitude": <0..1, how big a deal this is if true>,
      "confidence": <0..1, how sure you are of the reading>,
      "manipulation_likelihood": <0..1, odds this is hype/planted/pump material rather
                                  than organic verified news>,
      "emotion": "<dominant crowd emotion: {", ".join(EMOTIONS)}>",
      "emotion_intensity": <0..1>,
      "proposed_edges": [  // OPTIONAL: only when headlines reveal a relationship the node list can't express
        {{"src": "<node id>", "dst": "<node id>", "type": "influences", "sign": <1|-1>,
          "weight": <0..1>, "why": "<short>"}}
      ]
    }}
  ]
}}
Merge duplicate headlines into ONE event. Skip celebrity/sports/fluff. Be aggressive
flagging manipulation_likelihood on single-source hype, anonymous "sources", and
promotional language."""


def extract_events(headlines: list[dict], graph, settings) -> list[dict]:
    """LLM extraction with a keyword-matching fallback so the brain still works
    offline (lower fidelity, marked as such)."""
    if not headlines:
        return []
    events: Optional[list[dict]] = None
    if llm_ready(settings):
        node_ids = [n.id for n in graph.nodes.values() if n.type != "asset"]
        # fast tier: this is the high-volume per-cycle job — locally that's the
        # small qwen; the big model is reserved for the daily deep briefing
        raw = _call_llm(_prompt(headlines, node_ids), settings, max_tokens=6000,
                        tier="fast", json_mode=True)
        parsed = _extract_json(raw or "")
        if parsed and isinstance(parsed.get("events"), list):
            events = parsed["events"]
    if events is None:
        events = _fallback_extract(headlines, graph)

    now = datetime.now(timezone.utc).isoformat()
    threshold = settings.brain.credibility_threshold
    out = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        ev.setdefault("summary", ev.get("headline", ""))
        ev["nodes"] = [n for n in (ev.get("nodes") or []) if n in graph.nodes]
        ev["polarity"] = max(-1.0, min(1.0, float(ev.get("polarity", 0.0) or 0.0)))
        ev["magnitude"] = max(0.0, min(1.0, float(ev.get("magnitude", 0.0) or 0.0)))
        ev["confidence"] = max(0.0, min(1.0, float(ev.get("confidence", 0.5) or 0.5)))
        ev["credibility"] = round(credibility(ev, headlines), 3)
        ev["is_noise"] = ev["credibility"] < threshold or ev.get("type") == "rumor_hype"
        ev["emotion"] = ev.get("emotion") if ev.get("emotion") in EMOTIONS else "neutral"
        ev["emotion_intensity"] = max(0.0, min(1.0, float(ev.get("emotion_intensity", 0.0) or 0.0)))
        ev["ts"] = now
        # effective impulse the graph will feel: direction x size x trust x certainty
        ev["impulse"] = round(ev["polarity"] * ev["magnitude"] * ev["credibility"]
                              * ev["confidence"], 4)
        out.append(ev)
    return out


def _fallback_extract(headlines: list[dict], graph) -> list[dict]:
    """No-LLM fallback: match headlines to nodes by alias, infer crude polarity."""
    neg = re.compile(r"\b(cut|falls?|drops?|plunge|sanction|ban|war|crackdown|tariff|"
                     r"escalat|weak|slump|crisis|default|miss)\b", re.I)
    pos = re.compile(r"\b(hike|rises?|rally|surge|stimulus|deal|record|beat|strong|"
                     r"growth|approve|boost)\b", re.I)
    events = []
    for h in headlines:
        title = h.get("title", "")
        nodes = [n for n in graph.match_text(title) if graph.nodes[n].type != "asset"]
        if not nodes:
            continue
        polarity = (-0.5 if neg.search(title) else 0.0) + (0.5 if pos.search(title) else 0.0)
        if polarity == 0.0:
            continue
        events.append({
            "summary": title, "headline": title, "source": h.get("source", ""),
            "type": "other", "nodes": nodes[:3], "polarity": polarity,
            "magnitude": 0.3, "confidence": 0.3, "manipulation_likelihood": 0.2,
            "emotion": "neutral", "emotion_intensity": 0.2, "fallback": True,
        })
    return events
