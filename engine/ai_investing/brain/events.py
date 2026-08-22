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

# --- the curated tier ------------------------------------------------------
#
# Content the operator hand-picked and submitted. It is NOT a feed and must not
# be scored like one: the credibility formula rewards CORROBORATION, and a
# single in-depth analysis has none by construction — the very thing that makes
# it worth reading is what costs it 0.15 of credibility. Measured before this
# tier existed: a curated submission scored 0.555 against a corroborated wire's
# 0.677, so `impulse = polarity x magnitude x credibility x confidence` pressed
# the operator's own research ~18% SOFTER than a Reuters headline. With the
# extractor reading promotional register into an argumentative piece
# (manipulation_likelihood 0.4) it scored 0.355 — five thousandths above the
# noise line, where it would have stopped propagating entirely.
#
# The judgement was already made by a human with capital at risk. Re-deriving it
# from source statistics can only subtract. Curated events therefore take
# credibility 1.0 and are never marked noise. See DIGESTION_SPEC §A12.
CURATED_SOURCES = ("user_curated",)

# Per-item ceiling on curated body text reaching the extractor. 12k chars is
# ~3k tokens — room for a long-form analysis, while leaving the prompt safe for
# the local qwen3:8b fallback when the cloud key is exhausted. Compare 400 for a
# wire item, whose body is a lede restating its own headline.
CURATED_PROMPT_CHARS = 12000


def is_curated(source: str) -> bool:
    """True for content the operator submitted by hand.

    Substring match on purpose: the drop-directory tags each file
    `user_curated:<filename>` so provenance survives into the graph, and the
    Telegram path writes a bare `user_curated`. Both are the same tier.
    """
    s = (source or "").lower()
    return any(s.startswith(c) for c in CURATED_SOURCES)

# Default per-source trust. Keyed by substring of the feed/source host or name.
SOURCE_TRUST = {
    # Hand-picked by the user via Telegram /submit (data/news.py
    # _user_submitted_headlines) — a human with capital at risk chose to type
    # this in, which is a stronger filter than any wire's editorial process.
    # Trust sits with WSJ/Bloomberg, not at the primary-source 0.95 tier: a
    # curated read can still be one-sided or wrong, so it still needs the same
    # corroboration/manipulation math as everything else, just from a much
    # better prior than the 0.5 default that would otherwise send a single,
    # zero-corroboration submission (credibility ~0.375) right to the noise
    # line at BRAIN_CREDIBILITY_THRESHOLD (0.35).
    "user_curated": 0.9,
    # official / central banks: primary sources, near-total trust
    "federalreserve": 0.95, "boj.or.jp": 0.95, "ecb.europa.eu": 0.95,
    # BoE was the one central bank with no key, so it silently took the 0.5
    # default while its three peers sat at 0.95 — a primary source discounted by
    # oversight rather than by anyone's decision (2026-08-16).
    "bankofengland": 0.95,
    "reuters": 0.95, "wsj": 0.9, "dowjones": 0.9, "dj.com": 0.9, "bloomberg": 0.9,
    "ft.com": 0.9, "theguardian": 0.85, "bbc": 0.85, "cnbc": 0.75, "nikkei": 0.85,
    "scmp": 0.75,
    "caixin": 0.8, "straitstimes": 0.8, "businesstimes": 0.8,
    "japantimes": 0.8, "koreaherald": 0.75, "channelnewsasia": 0.8,
    "economictimes": 0.65, "mining.com": 0.6, "koreatimes": 0.7,
    # --- scored 2026-08-16 -------------------------------------------------
    # 16 configured hosts had no key and were silently taking the 0.5 default —
    # not a judgement anyone made, just an absence. Placed against the tiers
    # already here rather than on a new scale.
    #
    # national wire services: the same role Reuters plays, for their own country
    "yna.co.kr": 0.8,                     # Yonhap — Korea's national wire
    "antaranews": 0.7,                    # Antara — Indonesia's national wire
    "feedburner": 0.75,                   # currently ONLY CNA Taiwan's finance feed;
                                          # revisit if another feedburner feed is added
    # established national dailies / public broadcasters
    "mainichi": 0.75,                     # Mainichi Shimbun (JP)
    "rthk.hk": 0.75,                      # RTHK — HK public broadcaster
    "marketwatch": 0.75,                  # Dow Jones property, below WSJ's own 0.9
    "bangkokpost": 0.7,                   # TH broadsheet of record
    "thehindubusinessline": 0.7,          # IN business daily
    "livemint": 0.7,                      # Mint (IN) business daily
    "ltn.com.tw": 0.65,                   # Liberty Times — TW's largest daily
    "taipeitimes": 0.65,                  # TW English daily
    "technews.tw": 0.65,                  # TW semiconductor trade press — narrow but expert
    "vnexpress": 0.6,                     # VN's largest online paper
    # high volume, thinner editing — the trust number is what stops raw volume
    # from reading as corroboration in credibility()
    "cnyes": 0.55,                        # Anue (TW) financial portal, largely aggregated
    "oilprice": 0.55,                     # commodity commentary, promotional register
    "voi.id": 0.55,                       # ID digital outlet; 143 articles/day, our 2nd
                                          # highest volume source — see note above
    # official primary sources added alongside these
    "rbi.org.in": 0.95,                   # Reserve Bank of India — central bank tier
    "gov.cn": 0.9,                        # PRC State Council publishing its own decisions:
                                          # a primary source, NOT the 0.45 state-media tier
    # credit-rating agencies publishing their own actions: primary source, same
    # class as an SEC 8-K (§2.2 of the digest brief) — added 2026-08-18 after a
    # backfilled S&P action (Oracle downgrade) silently defaulted to 0.5 and
    # fell under the noise threshold despite being the rating agency's own release
    "spglobal.com": 0.95, "moodys.com": 0.95, "fitchratings.com": 0.95,
    "cgtn": 0.45,                         # state media — same tier as globaltimes
    # -----------------------------------------------------------------------
    # replacements wired in 2026-08-16 for feeds that were dead on arrival (see
    # the block comments in config.news_rss). ft.com/dowjones/scmp already scored
    # above; these are the sources that had no entry and would otherwise have
    # fallen to the 0.5 default without anyone choosing it.
    "technode": 0.6,                      # China tech, EN, reported not aggregated
    "northernminer": 0.65, "mining-technology": 0.6,   # specialist trade press
    "cnbeta": 0.45, "ifanr": 0.5,         # zh consumer-tech; ifanr reports, cnbeta aggregates
    # state media: useful policy signal, but reads like advocacy
    "globaltimes": 0.45,
    "coindesk": 0.6, "theblock": 0.65, "decrypt": 0.5, "panewslab": 0.5,
    "wublock": 0.6,                       # matches wublockchain + wublock.substack.com
    # Fast crypto-native tier. Trust is set LOW on purpose: they break stories
    # hours before the wires, but they also carry the pump material. Low trust is
    # not a penalty here, it is the instrument — the chorus signature in
    # credibility() fires precisely when a story runs across many low-trust
    # crypto feeds and NO trusted one, which is what a coordinated pump looks like.
    "protos": 0.6,                        # investigative, skeptical house style
    "dlnews": 0.6,                        # outlet closed 2026-05; key kept for syndication
    "thedefiant": 0.6, "blockworks.co": 0.6,   # replacements; blockworks matches its X handle
    "cointelegraph": 0.45, "bitcoinmagazine": 0.4,
    "cryptobriefing": 0.35, "ambcrypto": 0.3,
    "binance.com": 0.7, "upbit.com": 0.7,  # primary-source exchange announcements
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
            from ai_investing.brain.source_learning import (LAPSE_PENALTY, MIN_N,
                                                            learned_map, rescue_map)
            _, lapsed = rescue_map(settings)
            pen = LAPSE_PENALTY if any(l and l.lower() in s for l in lapsed) else 0.0
            for src, entry in learned_map(settings).items():
                if src and src.lower() in s and entry.get("n", 0) >= MIN_N:
                    return round(0.5 * static + 0.5 * entry["trust"] - pen, 3)
            if pen:      # lapsed rescue with thin recent record: below-neutral, not innocent
                return round(static - pen, 3)
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


def _prompt(headlines: list[dict], node_ids: str, graph=None) -> str:
    def _line(i: int, h: dict) -> str:
        s = f"{i}. [{h.get('source', '?')}] {h['title']}"
        extra = (h.get("body") or h.get("summary") or "").strip()
        # 400 chars is right for a wire item, whose body is a lede restating the
        # headline. It is exactly wrong for hand-picked long-form: a curated
        # submission stores 4000 chars (news.py `_submit`) and the
        # drop-directory stores whole files, so this line was discarding ~90% of
        # the operator's own research BEFORE anything judged it. The depth was
        # never rejected — it was never read. Curated content passes whole.
        if extra:                     # body/summary carries the WHO/HOW the
            if is_curated(h.get("source", "")):
                body = extra[:CURATED_PROMPT_CHARS]
                if len(extra) > CURATED_PROMPT_CHARS:
                    # NOT silent. An unbounded prompt overflows the local
                    # qwen3:8b fallback, the call fails, and extraction drops to
                    # `_fallback_extract` — which would lose the whole piece
                    # instead of its tail. So there is still a ceiling; the
                    # difference is that this one announces itself, in the
                    # prompt and on the headline, where truncation at 400 did
                    # neither.
                    body += (f"\n   [TRUNCATED at {CURATED_PROMPT_CHARS} chars of "
                             f"{len(extra)} — extract what you can from the above]")
                    h["curated_truncated"] = len(extra)
            else:
                body = extra[:400]
            s += f" — {body}"         # deals & integrity extraction feed on
        # Retrieval hint: alias-matching the text narrows 128 nodes to a handful.
        # Picking the origin node out of the full list is the small model's
        # weakest step, and most of its misses are nodes it simply never
        # considered. The hint is a shortlist, NOT an answer — Hormuz never
        # alias-matches oil_supply, so the model must stay free to overrule it.
        if graph is not None:
            try:
                cand = [n for n in graph.match_text(f"{h['title']} {extra}")
                        if graph.nodes[n].type != "asset"][:8]
                if cand:
                    s += f"\n   (mentions: {', '.join(cand)} — verify, may be wrong or incomplete)"
            except Exception:
                pass
        return s
    lines = "\n".join(_line(i, h) for i, h in enumerate(headlines[:100], 1))
    return f"""You are the macro brain of an automated trading system. Extract structured
EVENTS from these headlines. Markets are full of engineered noise — planted stories,
pumps, hype. Judge each event skeptically.

KNOWN GRAPH NODES (tag events ONLY with ids from this list). Each node is a
MEASURABLE QUANTITY; the name in brackets is what it measures:
{node_ids}

HEADLINES (numbered — you must account for EVERY number):
{lines}

Return ONLY JSON:
{{
  "events": [
    {{
      "n": <the HEADLINE NUMBER this event came from>,
      "summary": "<one line, what actually happened>",
      "headline": "<the headline this came from, verbatim>",
      "source": "<the [source] tag of that headline>",
      "type": "<one of: {", ".join(EVENT_TYPES)}>",
      "nodes": ["<1-3 node ids where the shock ORIGINATES — the thing that actually
                 changed (a policy node, a factor, a commodity). Do NOT tag sectors or
                 themes that are merely AFFECTED downstream; the relationship graph
                 propagates those itself>"],
      "direction": "<REQUIRED. Write it as words, not a number: 'more <the quantity
                   the FIRST node measures>' or 'less <that quantity>'. Example for
                   an OPEC output cut tagged oil_supply: 'less oil supply'. Example
                   for a rouble crash tagged currency_stress: 'more currency stress'.
                   Say MORE or LESS of the quantity — never 'good'/'bad'/'up'/'down'>",
      "magnitude_signed": <0.05..1, how big the change in that quantity is. Always
                   POSITIVE — "direction" already carries the sign>,
      "magnitude": <0..1, how big a deal this is if true>,
      "confidence": <0..1, how sure you are of the reading>,
      "assumption": "<one line: the thing that must be TRUE for your reading to hold,
                   stated so a non-expert can disagree with it. Not a hedge and not a
                   restatement of the news — the load-bearing belief. For an OPEC cut
                   read as 'less oil supply': 'that the announced cuts are actually
                   delivered, and demand does not soften to meet them'. This is shown
                   to the user, who judges the LEAP rather than the trade>",
      "manipulation_likelihood": <0..1, odds this is hype/planted/pump material rather
                                  than organic verified news>,
      "emotion": "<dominant crowd emotion: {", ".join(EMOTIONS)}>",
      "emotion_intensity": <0..1>,
      "proposed_edges": [  // OPTIONAL: only when headlines reveal a relationship the node list can't express
        {{"src": "<node id>", "dst": "<node id>", "type": "influences", "sign": <1|-1>,
          "weight": <0..1>, "delay_days": <optional, real-world lag before it lands>,
          "why": "<short>"}}
        // For a [user_curated...] item ONLY, this is the MAIN JOB, not an
        // afterthought. Those are long-form pieces the operator hand-picked
        // precisely because they explain MECHANISM, and the whole point of
        // submitting one is to wire what it explains. Extract every distinct
        // causal claim it actually makes — a dozen is normal for a real
        // analysis — and you may name `src`/`dst` ids that are NOT in the node
        // list above when the piece introduces something genuinely new
        // (a factor, a theme, an actor); those nodes get created. Use snake_case
        // ids that describe a MEASURABLE QUANTITY, same convention as the list.
        // Do NOT invent claims to pad the list: extract what the piece argues,
        // including the lags it asserts. For ordinary feed items the old rule
        // stands — a genuinely new mechanism only, and rarely.
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
      "deals": [  // OPTIONAL: any MATERIAL corporate transaction OR listing event the
                  // headline states, named as plain company names (not node ids —
                  // private companies count and matter most): equity investments,
                  // multi-year supply/compute contracts, vendor financing,
                  // acquisitions, AND a company IPOing / debuting on an exchange.
        {{"party_a": "<company doing the investing/supplying/acquiring, OR the "
                     "company going public for kind=lists_on>",
          "party_b": "<the counterparty; for kind=lists_on, the exchange it listed "
                     "on (e.g. 'STAR Market', 'NYSE', 'HKEX') — best-effort, can be "
                     "null if the headline doesn't say>",
          "kind": "invests_in|supplies|acquires|lists_on",
          "value_usd_bn": <stated deal size in $B, or null. For kind=lists_on this "
                          "is the IPO valuation / market cap at listing, not a "
                          "bilateral deal size — a big debut is material on its own>",
          "symbol": "<ONLY for kind=lists_on, and ONLY if the headline states a "
                    "ticker/stock code — the raw code as printed (e.g. '688825', "
                    "'9888.HK'), do not guess one. Otherwise null>",
          "why": "<short>"}}
      ]
    }}
  ],
  "skipped": [<headline numbers you deliberately produced no event for: fluff,
               sport, celebrity, lifestyle, or nothing that maps to a node>]
}}

COVERAGE — every headline number must appear EXACTLY ONCE, either as an event's
"n" or in "skipped". Do not stop early, do not summarise a few and drop the rest.
If two numbers are the same story, emit one event and put the other number in
"skipped". A dropped number is a story the system never sees.

SIGN CONVENTION — the single most important rule, and the easiest to get wrong.
"direction" describes THE QUANTITY THE NODE MEASURES. It is NOT "is this good or
bad news", and NOT which way prices move. The graph derives market consequences
itself; pre-baking them into the direction makes it apply them twice and invert.

BAD NEWS IS OFTEN "MORE". Most mistakes come from reading a grim headline and
writing "less". Stress, tension, spreads, debt, defaults and controls all go UP
in a crisis. Worked examples, the counter-intuitive ones first:

  "Fitch strips US of AAA rating"           -> us_gov_debt      MORE US debt stress
     NOT less. The rating fell, but the node measures STRESS, and stress rose.
  "High-yield spreads blow past 500bp"      -> credit_spreads   MORE spread
  "Private credit fund gates redemptions"   -> credit_stress    MORE stress
  "Rouble crashes through 150 per dollar"   -> currency_stress  MORE stress
  "SF office tower sells 70% below 2019"    -> cre_stress       MORE stress
  "OPEC+ agrees surprise output CUT"        -> oil_supply       LESS supply
     NOT more, though prices rise. The node measures SUPPLY, and supply fell.
  "Fed cuts rates 25bp"                     -> us_policy_rate   LESS rate
  "Tighter chip export controls announced"  -> export_controls  MORE controls
  "French government loses confidence vote" -> political_stability LESS stability
  "PBoC extends gold buying to 18th month"  -> cb_gold_demand   MORE demand
  "Tankers halted in Strait of Hormuz"      -> oil_supply LESS, geopolitical_tension MORE

Ask literally: "did the thing this node is NAMED AFTER go up or down?" — never
"was this good or bad for markets".

NEGATION AND DENIAL — read what the sentence actually asserts, not the words in
it. "Iran DENIES it agreed to reopen Hormuz" is an ESCALATION (+1 tension), not a
de-escalation, even though it contains "agreed" and "reopen". "Talks collapse",
"deal falls through", "pauses the pause" all invert. A retraction of good news is
bad news of similar size.

ORIGIN NODES — tag where the shock LANDS FIRST, not what it will affect. A Hormuz
blockage originates on oil_supply (and geopolitical_tension); it does NOT originate
on airlines, inflation, or equities, however obviously it will reach them. Tagging
a downstream node double-counts, because the graph will propagate there anyway.

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
reveals. Missing a deal record is losing a leg of a future circle.

IPOs AND NEW LISTINGS (kind=lists_on): a company debuting on an exchange is
just as material as a big bilateral deal, and the graph has NO OTHER way to
learn a brand-new public company exists — record every one you see, even if
the company means nothing to you yet. Large first-day moves, "most valuable
listing", "biggest IPO of the year" language are all strong signals. Missing
an IPO record means that company is invisible to the system until a human
happens to add it by hand."""


# Headlines per LLM call. Measured, not guessed: at 25 the small model answers
# for ~half the batch and drops the rest; at 10 recall is near-total. The live
# loop sees ~40-100 headlines a cycle, so this costs a few extra local calls
# every five minutes and buys back the half of the world that was going missing.
_BATCH = 10

_NEG_WORDS = re.compile(r"\b(cut|cuts|falls?|fell|drops?|plunge[sd]?|slump|sinks?|"
                        r"halts?|halted|bans?|banned|sanction\w*|blocks?|collapse[sd]?|"
                        r"crash\w*|default\w*|shrinks?|contract(?:s|ed|ion)|weaken\w*|"
                        r"loses?|lost|miss(?:es|ed)?|deni\w+|reject\w+|scraps?)\b", re.I)
_POS_WORDS = re.compile(r"\b(hikes?|raise[sd]?|rises?|rose|surge[sd]?|jumps?|rall(?:y|ies|ied)|"
                        r"soars?|climbs?|expand\w*|grow\w*|boost\w*|approve[sd]?|beats?|"
                        r"record|escalat\w*|tighten\w*|strengthen\w*|adds?|wins?)\b", re.I)


def _attach_headline(events: list, chunk: list[dict]) -> list[dict]:
    """Repair the `headline`/`source` fields from the batch index.

    Small models paraphrase the headline they were told to copy verbatim, which
    breaks every downstream join (dedup, corroboration, credibility). The
    numbered index is far more reliable than the echoed text, so it wins.
    """
    out = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        try:
            idx = int(ev.get("n", 0)) - 1
        except (TypeError, ValueError):
            idx = -1
        if 0 <= idx < len(chunk):
            ev["headline"] = chunk[idx].get("title", ev.get("headline", ""))
            ev["source"] = chunk[idx].get("source", ev.get("source", ""))
            for key in ("published", "ts_published"):
                if chunk[idx].get(key):
                    ev.setdefault("published", chunk[idx][key])
        out.append(ev)
    return out


_MORE = re.compile(r"^\s*(more|higher|increase\w*|rise\w*|up)\b", re.I)
_LESS = re.compile(r"^\s*(less|fewer|lower|decrease\w*|fall\w*|down|reduc\w*)\b", re.I)


def _polarity_of(ev: dict) -> float:
    """Prefer the WORDS over the number.

    Asked for a signed number the small model reports sentiment — grim headline,
    negative sign — which inverts every stress-type node (debt, spreads, tension:
    all of which RISE in a crisis). Asked to write "more credit stress" or "less
    oil supply" it gets the frame right far more often, because the sentence has
    to name the quantity. So `direction` wins when present and the numeric field
    only carries size.
    """
    d = str(ev.get("direction", "") or "")
    mag = ev.get("magnitude_signed", ev.get("magnitude", 0.5))
    try:
        mag = abs(float(mag or 0.5))
    except (TypeError, ValueError):
        mag = 0.5
    mag = max(0.05, min(1.0, mag))
    if _MORE.match(d):
        return mag
    if _LESS.match(d):
        return -mag
    return max(-1.0, min(1.0, float(ev.get("polarity", 0.0) or 0.0)))


def _keyword_sign(text: str) -> float:
    """Last-resort direction from the headline's own verbs. Deliberately weak
    (+/-0.4): a guessed sign should move the field less than a read one."""
    neg, pos = bool(_NEG_WORDS.search(text or "")), bool(_POS_WORDS.search(text or ""))
    if neg == pos:
        return 0.0
    return -0.4 if neg else 0.4


def _resolve_unsigned(events: list[dict], graph, settings) -> list[dict]:
    """Rescue events the fast model left directionless.

    A polarity of 0 is not a reading, it is an abstention — and since impulse
    multiplies by polarity, an abstention is indistinguishable from "this never
    happened". So: ask the big model to commit to a sign, fall back to the
    headline's own verbs, and if even that is mute, mark the event `unsigned`
    so the rate is visible in the health check instead of vanishing.
    """
    stuck = [ev for ev in events
             if isinstance(ev, dict)
             and abs(float(ev.get("polarity", 0.0) or 0.0)) < 1e-9
             and (ev.get("nodes") or [])]
    if stuck and llm_ready(settings):
        for i in range(0, len(stuck), _BATCH):
            batch = stuck[i:i + _BATCH]
            def _label(ev):
                nid = (ev.get("nodes") or [""])[0]
                node = graph.nodes.get(nid)
                return getattr(node, "label", "") or nid

            lines = "\n".join(
                f"{j}. {ev.get('headline') or ev.get('summary', '')}\n"
                f"   QUANTITY TO JUDGE: \"{_label(ev)}\" — did it go UP or DOWN?"
                for j, ev in enumerate(batch, 1))
            prompt = f"""For each item, say whether THE NAMED QUANTITY went up or down.
Do NOT judge whether the news is good or bad, and do NOT judge prices.

Bad news usually means MORE of a stress-type quantity:
  "Fitch strips US of AAA" / quantity "US government debt stress"   -> more
  "High-yield spreads blow past 500bp" / "Credit spreads"           -> more
  "OPEC+ cuts output" / "Oil supply"                                -> less
  "Fed cuts rates" / "US policy rate"                               -> less
  "Iran denies it agreed to reopen Hormuz" / "Geopolitical tension" -> more
     (a denial of de-escalation IS escalation)

Answer "more" or "less" for EVERY item — never "unchanged". If the item is
genuinely unrelated to its quantity, still answer, and set "weak": true.

{lines}

Return ONLY JSON: {{"signs": [{{"n": <number>, "direction": "more"|"less", "weak": <bool>}}]}}"""
            raw = _call_llm(prompt, settings, max_tokens=1200, tier="smart",
                            json_mode=True)
            parsed = _extract_json(raw or "") or {}
            for rec in (parsed.get("signs") or []):
                try:
                    ev = batch[int(rec.get("n", 0)) - 1]
                except (TypeError, ValueError, IndexError):
                    continue
                d = str(rec.get("direction", "") or "")
                pol = 1.0 if _MORE.match(d) else (-1.0 if _LESS.match(d) else 0.0)
                if abs(pol) > 1e-9:
                    # a rescued sign is a second opinion, not a first reading:
                    # damp it, and damp it harder when the model called it weak
                    ev["polarity"] = max(-1.0, min(1.0, pol)) * (0.4 if rec.get("weak") else 0.7)
                    ev["sign_source"] = "escalated"

    for ev in events:
        if not isinstance(ev, dict):
            continue
        if abs(float(ev.get("polarity", 0.0) or 0.0)) < 1e-9 and (ev.get("nodes") or []):
            guess = _keyword_sign(ev.get("headline") or ev.get("summary", ""))
            if guess:
                ev["polarity"] = guess
                ev["sign_source"] = "keyword"
            else:
                ev["unsigned"] = True     # counted by scripts/daily_status.py
    return events


def extract_events(headlines: list[dict], graph, settings) -> list[dict]:
    """LLM extraction with a keyword-matching fallback so the brain still works
    offline (lower fidelity, marked as such).

    Two failure modes measured on the golden set (scripts/audit_live_tagger.py)
    shape this function:

      * RECALL — handed 25+ headlines at once the small model answers for about
        half and silently drops the rest, so headlines go out in small batches.
      * UNSIGNED — it returns polarity 0 when unsure, and because
        `impulse = polarity x magnitude x credibility` a 0 deletes the event.
        Anything unsigned is escalated to the big model, then to keyword sign,
        and only then given up on (counted, never silently dropped).
    """
    if not headlines:
        return []
    events: Optional[list[dict]] = None
    if llm_ready(settings):
        node_ids = ", ".join(
            f"{n.id} [{n.label}]" if getattr(n, "label", "") else n.id
            for n in graph.nodes.values() if n.type != "asset")
        events = []
        # fast tier: this is the high-volume per-cycle job — locally that's the
        # small qwen; the big model is reserved for the daily deep briefing
        for i in range(0, len(headlines), _BATCH):
            chunk = headlines[i:i + _BATCH]
            raw = _call_llm(_prompt(chunk, node_ids, graph), settings, max_tokens=6000,
                            tier="fast", json_mode=True)
            parsed = _extract_json(raw or "")
            got = (_attach_headline(parsed["events"], chunk)
                   if parsed and isinstance(parsed.get("events"), list) else [])
            events.extend(got)
            # COVERAGE ENFORCEMENT. The prompt says "account for EVERY number"
            # but nothing verified it, and mark_digested() then buried whatever
            # the model skipped — permanently, thanks to the cost gate. The
            # skipped ones are exactly the boring-looking stories the
            # noise-rescue loop needs scored (source_learning.py): a story can
            # be JUDGED noise, but it must never be silently unjudged.
            covered = set()
            for ev in got:
                try:
                    covered.add(int(ev.get("n", 0)))
                except (TypeError, ValueError):
                    pass
            missing = [h for j, h in enumerate(chunk, 1) if j not in covered]
            if missing:                      # one focused retry on just the misses
                raw = _call_llm(_prompt(missing, node_ids, graph), settings,
                                max_tokens=6000, tier="fast", json_mode=True)
                parsed = _extract_json(raw or "")
                got = (_attach_headline(parsed["events"], missing)
                       if parsed and isinstance(parsed.get("events"), list) else [])
                events.extend(got)
                covered = set()
                for ev in got:
                    try:
                        covered.add(int(ev.get("n", 0)))
                    except (TypeError, ValueError):
                        pass
                still = [h for j, h in enumerate(missing, 1) if j not in covered]
                if still:                    # keyword floor: low fidelity, but graded
                    fb = _fallback_extract(still, graph)
                    for ev in fb:
                        ev["coverage_fallback"] = True
                        events.append(ev)
                    fb_titles = {ev.get("headline", "") for ev in fb}
                    for h in still:          # absolute floor: an unsigned stub that
                        if h.get("title", "") in fb_titles:   # _resolve_unsigned will
                            continue                          # escalate — never silent
                        title = h.get("title", "")
                        events.append({
                            "summary": title, "headline": title,
                            "source": h.get("source", ""), "type": "other",
                            "nodes": [n for n in graph.match_text(
                                f"{title} {h.get('summary', '')}")
                                if graph.nodes[n].type != "asset"][:3],
                            "polarity": 0.0, "magnitude": 0.15, "confidence": 0.2,
                            "manipulation_likelihood": 0.2, "emotion": "neutral",
                            "emotion_intensity": 0.1, "coverage_fallback": True,
                        })
        if not events:
            events = None
    if events is None:
        events = _fallback_extract(headlines, graph)
    else:
        events = _resolve_unsigned(events, graph, settings)

    now = datetime.now(timezone.utc).isoformat()
    threshold = settings.brain.credibility_threshold
    out = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        ev.setdefault("summary", ev.get("headline", ""))
        ev["assumption"] = str(ev.get("assumption") or "")[:400]   # shown to the user in consult asks
        # Unknown origin ids are normally dropped — the extractor hallucinates
        # node names and a shock cannot start somewhere that does not exist.
        # For CURATED items an unknown id is the opposite signal: the operator
        # submitted a piece precisely because it names a mechanism the graph has
        # not heard of. Those ids are kept aside for `core` to create, then used
        # as real origins on the SAME cycle (§A12).
        raw_nodes = [n for n in (ev.get("nodes") or []) if isinstance(n, str) and n]
        ev["nodes"] = [n for n in raw_nodes if n in graph.nodes]
        if is_curated(ev.get("source", "")):
            ev["proposed_nodes"] = [n for n in raw_nodes if n not in graph.nodes]
        ev["polarity"] = _polarity_of(ev)
        ev["magnitude"] = max(0.0, min(1.0, float(ev.get("magnitude", 0.0) or 0.0)))
        ev["confidence"] = max(0.0, min(1.0, float(ev.get("confidence", 0.5) or 0.5)))
        # THE CURATED TIER. A human with capital at risk already made this
        # judgement; the credibility formula can only subtract from it, and it
        # subtracts hardest for depth (no corroboration) and for argumentative
        # prose (manipulation_likelihood). Neither is a defect in hand-picked
        # research. Curated events take full credibility and are never noise —
        # not even on `type == "rumor_hype"`, because the operator submitting a
        # piece ABOUT a rumour is making a deliberate call to track it.
        ev["curated"] = is_curated(ev.get("source", ""))
        if ev["curated"]:
            ev["credibility"] = 1.0
            ev["is_noise"] = False
        else:
            ev["credibility"] = round(credibility(ev, headlines, settings), 3)
            # noise-rescue: a source whose ignored calls keep coming true gets a
            # lower noise bar — its "noise" has measurably been signal
            eff_threshold = threshold
            try:
                from ai_investing.brain.source_learning import rescue_map
                rescued, _ = rescue_map(settings)
                s_low = (ev.get("source") or "").lower()
                if any(r and r.lower() in s_low for r in rescued):
                    eff_threshold = max(0.0, threshold - 0.1)
                    ev["rescued_source"] = True
            except Exception:
                pass
            ev["is_noise"] = (ev["credibility"] < eff_threshold
                              or ev.get("type") == "rumor_hype")
        ev["emotion"] = ev.get("emotion") if ev.get("emotion") in EMOTIONS else "neutral"
        ev["emotion_intensity"] = max(0.0, min(1.0, float(ev.get("emotion_intensity", 0.0) or 0.0)))
        ev["ts"] = now
        # effective impulse the graph will feel: direction x size x trust x certainty
        ev["impulse"] = round(ev["polarity"] * ev["magnitude"] * ev["credibility"]
                              * ev["confidence"], 4)
        # fear-monger discount: a source whose doom stories measurably never move
        # markets gets its fear-event impulses damped (learned, per source)
        if ev["emotion"] in ("fear", "panic") and ev["polarity"] < 0 and not ev["curated"]:
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
