#!/usr/bin/env python3
"""Foresight check: names the news keeps mentioning that the graph doesn't know.

WHY THIS EXISTS.

The graph grows two ways, and both are blind to "a promising company is all
over the headlines": brain/seed.py is hand-curated (only knows what a human
remembered to type in), and brain/deals.py only auto-creates a node when an
UNKNOWN party shows up in a >=$1B bilateral deal (invests_in/supplies/
acquires). An IPO isn't a bilateral deal, a hot startup's early funding rounds
are rarely >=$1B each, and neither path has any notion of "mentioned a lot
this week" — so a headline-making company can sit outside the graph
indefinitely with nothing ever flagging the gap. Unitree Robotics' STAR
Market IPO (2026-08) was a real miss of exactly this kind.

This script is the missing check: it mines the news archives/caches already
being collected, extracts candidate company/entity names, counts how often
and how widely (across distinct sources) each one is mentioned, and reports
whichever ones the graph's alias index cannot resolve. It does not touch the
LLM digester or auto-create anything — it is a human-facing gap report, same
spirit as needs_you.py, meant to be skimmed and acted on (usually: add the
name to brain/seed.py).

Precision over recall: a frequency-only heuristic on scraped headlines is
noisy (nav-menu boilerplate, sentence-initial capitalization, source names).
Two independent thresholds cut most of that: a candidate must appear in
several DISTINCT headlines from MULTIPLE DISTINCT source domains before it's
worth a human's time.

  python3 scripts/graph_gap_scan.py                  # last 30 days, top 25
  python3 scripts/graph_gap_scan.py --days 90 --top 50
  python3 scripts/graph_gap_scan.py --min-mentions 2 --min-sources 2
"""
from __future__ import annotations

import argparse
import glob
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))

DATA_DIR = ROOT / "data"

# Multi-word Title Case runs (1-4 words). Deliberately greedy — the stoplist
# and frequency/source thresholds below do the real filtering, not this regex.
_PHRASE_RE = re.compile(r"\b(?:[A-Z][a-zA-Z&\.]{1,}\s){0,3}[A-Z][a-zA-Z&\.]{1,}\b")
_TICKER_RE = re.compile(r"\$([A-Z]{1,5})\b")

_SUFFIXES = re.compile(
    r"\b(Inc|Corp|Corporation|Co|Ltd|Plc|Holdings?|Group|Technologies|"
    r"Technology|Labs|LLC)\b\.?", re.I)

# Sentence-initial capitals, calendar words, and scraped nav-menu junk (seen
# verbatim in the wild, e.g. an Antofagasta press item whose "summary" field
# was actually page chrome: "Latest Headlines / Top Stories / Stock Alerts /
# Wallstreet Events / Industry News / Corp. Calendars / Stock Splits").
_STOPWORDS = {
    "the", "this", "that", "these", "those", "a", "an", "and", "or", "but",
    "in", "on", "at", "to", "for", "of", "with", "by", "from", "as", "is",
    "are", "was", "were", "be", "been", "it", "its", "here", "here is",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday",
    "sunday", "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
    "latest headlines", "top stories", "breaking news", "stock alerts",
    "wallstreet events", "industry news", "corp. calendars", "stock splits",
    "new", "us", "u.s.", "eu", "uk", "ai", "ipo", "ceo", "cfo", "q1", "q2",
    "q3", "q4", "fy26", "fy27", "read more", "click here", "learn more",
    # countries / regions / generic geography — real signal is the COMPANY
    # named alongside these, not the place itself
    "china", "chinese", "hong kong", "japan", "japanese", "singapore",
    "asia", "asian", "europe", "european", "america", "american",
    "malaysia", "kuala lumpur", "bursa malaysia", "india", "indian",
    "korea", "korean", "south korea", "north korea", "taiwan", "vietnam",
    "indonesia", "shanghai", "beijing", "guangzhou", "shenzhen",
    # generic finance/news boilerplate that scrapes as Title Case noise
    "conference calls", "earnings calendar", "calendars", "index", "market",
    "total", "strategy", "doubling", "in focus", "key takeaways",
    "key insights", "buy now", "furthermore", "crucial support",
    "weekly scam alert", "scammers", "million", "billion", "three", "two",
    "four", "strait", "self reported market cap",
    # the macro/geopolitics archives (Guardian/GDELT/Wikipedia backfills) feed
    # regime factors, not company discovery — countries, nationalities, and
    # named conflict actors dominate there and are never a graph GAP, just
    # noise for THIS tool's purpose (a factor node like geopolitical_tension
    # already covers the macro signal these stories carry)
    "pakistan", "france", "french", "syria", "syrian", "ukraine",
    "ukrainian", "russia", "russian", "israel", "israeli", "palestinian",
    "gaza strip", "gaza", "lebanon", "lebanese", "iran", "iranian", "iraq",
    "iraqi", "saudi arabia", "saudi", "yemen", "afghanistan", "sudan",
    "somalia", "venezuela", "mexico", "mexican", "canada", "canadian",
    "germany", "german", "italy", "italian", "spain", "spanish", "poland",
    "polish", "turkey", "turkish", "egypt", "egyptian", "nigeria",
    "nigerian", "brazil", "brazilian", "argentina", "australia",
    "australian", "united kingdom", "britain", "british", "scotland",
    "wales", "ireland", "irish", "hezbollah", "hamas", "taliban", "isis",
    "al qaeda", "houthi", "kashmir", "donald trump", "trump",
    "united states", "united kingdom", "european union", "the united states",
    # wire agencies / news orgs — near-universal false positives in any
    # news corpus, never a graph gap
    "reuters", "afp", "al jazeera", "bloomberg", "associated press", "ap",
    "cnn", "bbc", "xinhua", "cna", "agence france-presse", "getty images",
}
# Candidate phrases ending in one of these read as sentence fragments, not
# entity names ("...Are Trying", "...Is Lacking As") — drop them.
_BAD_TRAILING_WORDS = {
    "is", "are", "as", "near", "after", "before", "into", "onto", "upon",
    "trying", "lacking", "posing", "announces", "says", "said", "was",
    "were", "has", "have", "had", "will", "would", "could", "should",
    "total", "key", "insights", "takeaways", "of", "for", "the", "and",
}


def _norm(name: str) -> str:
    return re.sub(r"\s+", " ", _SUFFIXES.sub("", name or "")).strip()


def _iter_headline_texts():
    """Yield (title, summary, source_domain, url) across every collected feed —
    news_archive_*.jsonl (append-only, {"headlines": [...]} per line) and the
    rolling *_cache.json snapshots ({"items": [...]})."""
    for path in sorted(glob.glob(str(DATA_DIR / "news_archive_*.jsonl"))):
        try:
            with open(path) as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    for h in rec.get("headlines", []) or []:
                        yield _row(h)
        except OSError:
            continue
    for path in sorted(glob.glob(str(DATA_DIR / "*_cache.json"))):
        try:
            d = json.loads(Path(path).read_text())
        except (OSError, json.JSONDecodeError):
            continue
        items = d.get("items") if isinstance(d, dict) else None
        if not isinstance(items, list):
            continue
        for h in items:
            if isinstance(h, dict):
                yield _row(h)


def _row(h: dict):
    title = str(h.get("title") or "")
    summary = str(h.get("summary") or h.get("body") or "")
    url = str(h.get("url") or "")
    domain = urlparse(url).netloc or str(h.get("source") or "?")
    published = h.get("published") or h.get("ts") or ""
    return title, summary, domain, published, url


def _candidates(text: str) -> set[str]:
    out = set()
    for m in _TICKER_RE.finditer(text):
        out.add(f"${m.group(1)}")
    for m in _PHRASE_RE.finditer(text):
        cand = _norm(m.group(0))
        low = cand.lower()
        if low in _STOPWORDS or len(cand) < 3:
            continue
        # ALL-CAPS single tokens are almost always wire-story datelines
        # ("SEOUL, Aug 13 (Reuters) —"), not entity names
        if cand.isupper() and " " not in cand:
            continue
        # single-word candidates are the noisiest (sentence-initial capitals);
        # require a bit more length to keep them
        if " " not in cand and len(cand) < 5:
            continue
        if cand.split()[-1].lower() in _BAD_TRAILING_WORDS:
            continue
        if cand.lower().endswith((".com", ".net", ".org", ".co")):
            continue
        out.add(cand)
    return out


def scan(days: int, min_mentions: int, min_sources: int) -> list[dict]:
    from ai_investing.brain.graph import KnowledgeGraph
    from ai_investing.config import Settings

    settings = Settings()
    graph_path = settings.brain.graph_path
    graph = KnowledgeGraph.load(graph_path) if Path(graph_path).exists() \
        else KnowledgeGraph.seeded()
    idx = graph.alias_index()

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    mentions: dict[str, int] = defaultdict(int)
    sources: dict[str, set[str]] = defaultdict(set)
    examples: dict[str, str] = {}

    seen_rows = 0
    for title, summary, domain, published, url in _iter_headline_texts():
        if published:
            try:
                ts = datetime.fromisoformat(str(published).replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    # some feeds publish naive timestamps — assume UTC rather
                    # than crash the comparison below
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts < cutoff:
                    continue
            except (ValueError, TypeError):
                pass
        seen_rows += 1
        cands = _candidates(title) | _candidates(summary[:400])
        for c in cands:
            mentions[c] += 1
            sources[c].add(domain)
            examples.setdefault(c, title)

    out = []
    for cand, n in mentions.items():
        if n < min_mentions or len(sources[cand]) < min_sources:
            continue
        low = cand.lstrip("$").lower()
        if low in idx or cand.lower() in idx:
            continue  # already resolvable — not a gap
        out.append({
            "candidate": cand,
            "mentions": n,
            "sources": sorted(sources[cand]),
            "example_headline": examples[cand],
        })
    out.sort(key=lambda r: (-r["mentions"], -len(r["sources"])))
    return out, seen_rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30, help="lookback window")
    ap.add_argument("--min-mentions", type=int, default=3,
                     help="minimum distinct headline mentions")
    ap.add_argument("--min-sources", type=int, default=2,
                     help="minimum distinct source domains")
    ap.add_argument("--top", type=int, default=25)
    args = ap.parse_args()

    results, seen_rows = scan(args.days, args.min_mentions, args.min_sources)

    if seen_rows == 0:
        print("no headlines found in the lookback window — nothing to scan yet "
              "(the news archives are still thin; re-run once more cycles have "
              "accumulated)")
        return 0

    if not results:
        print(f"scanned {seen_rows} headlines over the last {args.days}d — "
              f"nothing cleared the mentions>={args.min_mentions}/"
              f"sources>={args.min_sources} bar. Either the graph has "
              f"real coverage right now, or the archives are still too thin "
              f"for frequency to be a signal yet.")
        return 0

    print(f"scanned {seen_rows} headlines over the last {args.days}d — "
          f"{len(results)} candidate name(s) not resolvable in the graph:\n")
    for r in results[:args.top]:
        srcs = ", ".join(r["sources"][:4])
        print(f"  {r['mentions']:>3}x  [{len(r['sources'])} sources: {srcs}]  "
              f"{r['candidate']}")
        print(f"        e.g. \"{r['example_headline'][:100]}\"")
    print(f"\n({len(results)} total, showing top {min(args.top, len(results))}. "
          f"If one of these is real, add it to brain/seed.py.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
