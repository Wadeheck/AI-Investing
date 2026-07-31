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
    # official / central banks: primary sources, near-total trust
    "federalreserve": 0.95, "boj.or.jp": 0.95, "ecb.europa.eu": 0.95,
    "reuters": 0.95, "wsj": 0.9, "dowjones": 0.9, "dj.com": 0.9, "bloomberg": 0.9,
    "ft.com": 0.9, "theguardian": 0.85, "bbc": 0.85, "cnbc": 0.75, "nikkei": 0.85,
    "scmp": 0.75,
    "caixin": 0.8, "straitstimes": 0.8, "businesstimes": 0.8,
    "japantimes": 0.8, "koreaherald": 0.75, "channelnewsasia": 0.8,
    "economictimes": 0.65, "mining.com": 0.6,
    # state media: useful policy signal, but reads like advocacy
    "globaltimes": 0.45,
    "coindesk": 0.6, "theblock": 0.65, "decrypt": 0.5, "panewslab": 0.5,
    "wublockchain": 0.6,
    # curated X handles (news_archive_x.jsonl capture) — listed BEFORE the
    # generic x.com fallback because first substring match wins
    "x.com/farsideuk": 0.8, "x.com/glassnode": 0.7, "x.com/zachxbt": 0.7,
    "x.com/eleanorterrett": 0.7, "x.com/theblockco": 0.65,
    "x.com/blockworks": 0.6, "x.com/messaricrypto": 0.6,
    "x.com/coinbureau": 0.5, "x.com/watcherguru": 0.35,
    "cointelegraph": 0.45, "reddit": 0.25, "twitter": 0.25, "x.com": 0.25,
    "substack": 0.35, "seekingalpha": 0.45, "zerohedge": 0.3, "benzinga": 0.45,
}
DEFAULT_TRUST = 0.5

_HYPE_WORDS = re.compile(
    r"\b(to the moon|skyrocket|explode|guaranteed|can't lose|100x|10x|massive gains|"
    r"next nvidia|next bitcoin|get in now|don't miss|insider says|sources say|"
    r"could soar|set to surge|unstoppable)\b", re.I)


def source_trust(source: str, settings=None) -> float:
    """Static prior, blended 50/50 with LEARNED per-source precision once a
    source has enough scored outcomes (brain/source_learning.py). Feeds that
    keep pointing the right way earn weight; wolf-criers lose it."""
    s = (source or "").lower()
    static = DEFAULT_TRUST
    for key, val in SOURCE_TRUST.items():
        if key in s:
            static = val
            break
    if settings is not None:
        try:
            from ai_investing.brain.source_learning import MIN_N, learned_map
            for src, entry in learned_map(settings).items():
                if src and src.lower() in s and entry.get("n", 0) >= MIN_N:
                    return round(0.5 * static + 0.5 * entry["trust"], 3)
        except Exception:
            pass
    return static


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{4,}", text.lower())
            if w not in ("this", "that", "with", "from", "after", "amid", "over", "says")}


def corroboration(headline: str, source: str, all_headlines: list[dict],
                  min_trust: float = 0.55, settings=None) -> int:
    """How many other TRUSTED sources carry a substantially similar story.
    Independence-weighted on purpose: a chorus of low-trust feeds echoing one
    another is how pump campaigns look, so only sources at or above `min_trust`
    count as confirmation (pass min_trust=0 to count everyone). With `settings`,
    trust is the LEARNED blend — a no-name feed that has earned precision can
    confirm; a big name that keeps crying wolf loses the privilege."""
    t = _tokens(headline)
    if not t:
        return 0
    others = 0
    for h in all_headlines:
        if h.get("title") == headline or h.get("source", "") == source:
            continue
        if source_trust(h.get("source", ""), settings) < min_trust:
            continue
        overlap = len(t & _tokens(h.get("title", "")))
        # rephrased duplicates share the facts, not the words: 2+ meaty tokens
        # covering a quarter of the headline is enough to count as corroboration
        if overlap >= max(2, len(t) // 4):
            others += 1
    return others


def low_trust_echoes(headline: str, source: str, all_headlines: list[dict],
                     settings=None) -> int:
    """The campaign signature: similar stories carried ONLY by low-trust feeds."""
    return (corroboration(headline, source, all_headlines, min_trust=0.0)
            - corroboration(headline, source, all_headlines, settings=settings))


def credibility(event: dict, all_headlines: list[dict], settings=None) -> float:
    """Blend source trust, trusted corroboration, manipulation likelihood, hype
    language, and the low-trust-chorus signature into one credibility score.
    This is the noise filter."""
    src = event.get("source", "")
    headline = event.get("headline", event.get("summary", ""))
    trust = source_trust(src, settings)
    corr = min(2, corroboration(headline, src, all_headlines, settings=settings))
    echoes = low_trust_echoes(headline, src, all_headlines, settings=settings)
    manip = max(0.0, min(1.0, float(event.get("manipulation_likelihood", 0.0))))
    hype_pen = 0.15 if _HYPE_WORDS.search(headline or "") else 0.0
    # many low-trust feeds, zero trusted ones: coordination, not confirmation
    chorus_pen = 0.15 if (echoes >= 3 and corr == 0) else 0.0
    official = 0.1 if event.get("type") in ("monetary_policy", "fiscal_policy",
                                            "trade_policy", "regulation") else 0.0
    score = (0.15 + 0.45 * trust + 0.15 * (corr / 2) + official
             - 0.5 * manip - hype_pen - chorus_pen)
    return max(0.0, min(1.0, score))


def _prompt(headlines: list[dict], node_ids: list[str]) -> str:
    def _line(h: dict) -> str:
        s = f"- [{h.get('source', '?')}] {h['title']}"
        extra = (h.get("body") or h.get("summary") or "").strip()
        if extra:                     # body/summary carries the WHO/HOW the
            s += f" — {extra[:400]}"  # deals & integrity extraction feed on
        return s
    lines = "\n".join(_line(h) for h in headlines[:100])
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
      ],
      "integrity": [  // OPTIONAL but CRITICAL: any story casting doubt on whether an
                      // entity's reported numbers, assets, returns, or collateral are
                      // REAL — by ANY mechanism, including ones you've never seen named
                      // before. History: auditors resigning, withdrawal halts,
                      // short-seller exposés, "guaranteed returns", repackaged risk sold
                      // as safe, self-dealing collateral. Judge the MECHANISM freshly:
                      // if the honest version of this story requires trusting numbers
                      // someone has an incentive and opportunity to fake, flag it.
        {{"company": "<entity name as stated>", "severity": <0..1, how load-bearing the
          doubt is: auditor walking ~0.9, anonymous allegation ~0.3>,
          "mechanism": "<one line: HOW the dishonesty works, in your own words>"}}
      ],
      "deals": [  // OPTIONAL: any MATERIAL corporate transaction the headline states,
                  // BOTH parties named as plain company names (not node ids — private
                  // companies count and matter most): equity investments, multi-year
                  // supply/compute contracts, vendor financing, acquisitions.
        {{"party_a": "<company doing the investing/supplying/acquiring>",
          "party_b": "<the counterparty>",
          "kind": "invests_in|supplies|acquires",
          "value_usd_bn": <stated deal size in $B, or null>,
          "why": "<short>"}}
      ]
    }}
  ]
}}
Merge duplicate headlines into ONE event. Skip celebrity/sports/fluff. Be aggressive
flagging manipulation_likelihood on single-source hype, anonymous "sources", and
promotional language.

CIRCULAR-FINANCING RADAR: when a company INVESTS IN or LENDS TO its own customer
(who then buys its products), or two firms announce mutual investment + purchase
agreements, that revenue is partly the same dollar counted twice. Tag such events
with node "ai_circularity" (polarity +1 = more round-tripping revealed), type
"market_flow", and set manipulation_likelihood >= 0.4 — the deal is real but the
implied growth is inflated.

DEALS: separately from event tagging, ALWAYS record material corporate
transactions in the `deals` field — one record per investment/supply/acquisition
with both parties' plain names and the stated size. You do NOT need to judge
circularity there: the relationship graph accumulates every deal leg and detects
money circles structurally, including multi-party circles no single headline
reveals. Missing a deal record is losing a leg of a future circle."""


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
        ev["credibility"] = round(credibility(ev, headlines, settings), 3)
        ev["is_noise"] = ev["credibility"] < threshold or ev.get("type") == "rumor_hype"
        ev["emotion"] = ev.get("emotion") if ev.get("emotion") in EMOTIONS else "neutral"
        ev["emotion_intensity"] = max(0.0, min(1.0, float(ev.get("emotion_intensity", 0.0) or 0.0)))
        ev["ts"] = now
        # effective impulse the graph will feel: direction x size x trust x certainty
        ev["impulse"] = round(ev["polarity"] * ev["magnitude"] * ev["credibility"]
                              * ev["confidence"], 4)
        # fear-monger discount: a source whose doom stories measurably never move
        # markets gets its fear-event impulses damped (learned, per source)
        if ev["emotion"] in ("fear", "panic") and ev["polarity"] < 0:
            try:
                from ai_investing.brain.source_learning import learned_map
                s = (ev.get("source") or "").lower()
                for src, entry in learned_map(settings).items():
                    dd = entry.get("doom_discount")
                    if dd is not None and src and src.lower() in s:
                        ev["impulse"] = round(ev["impulse"] * dd, 4)
                        ev["doom_discount"] = dd
                        break
            except Exception:
                pass
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
