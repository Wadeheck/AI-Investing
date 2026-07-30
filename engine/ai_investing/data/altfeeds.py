"""Free structured/alt sources beyond RSS — same headline-dict shape as
data/news.py `fetch_headlines` so everything funnels through the one dedupe
store and, later, the one digester.

Sources (all keyless, all probed reachable 2026-07-30):
  - SEC EDGAR full-text search: fresh 8-K filings — structured, market-grade
    company events (guidance pulls, resignations, material weaknesses).
  - StockTwits per-symbol streams: retail bull/bear sentiment counts (the
    free X-substitute for crowd mood).
  - Hacker News front page: tech/AI narrative velocity.

SEC asks for a descriptive User-Agent with contact info — set SEC_USER_AGENT
in .env; a generic default is used otherwise. All fetchers fail soft: any
error returns [] so one dead source never stalls the accumulation loop.
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone

_UA = os.environ.get("SEC_USER_AGENT", "ai-investing-research (contact: set SEC_USER_AGENT)")


def _get_json(url: str, timeout: int = 20) -> dict | list | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fetch_edgar_8k(limit: int = 20) -> list[dict]:
    """Latest 8-K filings via EDGAR full-text search (efts.sec.gov)."""
    url = ("https://efts.sec.gov/LATEST/search-index?" +
           urllib.parse.urlencode({"q": "\"8-K\"", "forms": "8-K", "hits": str(limit)}))
    d = _get_json(url)
    hits = (d or {}).get("hits", {}).get("hits", [])
    out = []
    for h in hits[:limit]:
        src = h.get("_source", {})
        names = src.get("display_names") or []
        company = names[0].split("(")[0].strip() if names else ""
        if not company:
            continue
        out.append({"title": f"8-K filed: {company}",
                    "summary": f"form {src.get('root_forms', ['8-K'])[0]} filed {src.get('file_date', '')}",
                    "published": src.get("file_date", ""), "source": "sec.gov"})
    return out


def fetch_stocktwits(symbols: list[str], min_msgs: int = 10) -> list[dict]:
    """Per-symbol sentiment gauge from StockTwits' free streams. Emitted as ONE
    synthetic headline per symbol so the digester/emotion factor can read the
    crowd without drowning in individual posts. Crypto uses BTC.X-style ids."""
    out = []
    for sym in symbols:
        d = _get_json(f"https://api.stocktwits.com/api/2/streams/symbol/{sym}.json")
        msgs = (d or {}).get("messages", [])
        if len(msgs) < min_msgs:
            continue
        bull = sum(1 for m in msgs
                   if (m.get("entities", {}).get("sentiment") or {}).get("basic") == "Bullish")
        bear = sum(1 for m in msgs
                   if (m.get("entities", {}).get("sentiment") or {}).get("basic") == "Bearish")
        if bull + bear == 0:
            continue
        tilt = "bullish" if bull > bear * 1.5 else "bearish" if bear > bull * 1.5 else "mixed"
        out.append({"title": f"StockTwits crowd on {sym}: {tilt} ({bull} bull / {bear} bear "
                             f"of {len(msgs)} recent posts)",
                    "summary": "", "published": _now_iso(), "source": "stocktwits.com"})
    return out


def fetch_hn_top(limit: int = 20) -> list[dict]:
    """Hacker News front-page titles — tech/AI narrative pulse."""
    ids = _get_json("https://hacker-news.firebaseio.com/v0/topstories.json") or []
    out = []
    for i in ids[:limit]:
        item = _get_json(f"https://hacker-news.firebaseio.com/v0/item/{i}.json", timeout=10)
        t = (item or {}).get("title", "").strip()
        if t:
            out.append({"title": t[:200], "summary": "", "published": _now_iso(),
                        "source": "news.ycombinator.com"})
    return out


def fetch_all(settings) -> list[dict]:
    st_syms = list(settings.stock_watchlist) + ["BTC.X", "ETH.X"]
    return fetch_edgar_8k() + fetch_stocktwits(st_syms) + fetch_hn_top()
