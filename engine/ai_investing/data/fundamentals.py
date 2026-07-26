"""Free weekly fundamentals snapshot (yfinance .info, cached on disk).

Gives the strategist a valuation/health picture — P/E, price-to-book,
debt, margins — so calls like "overvalued" or "financially stressed" are
grounded in numbers, not vibes. Fetches are lazy and budgeted (a few
symbols per call); the cache fills up over the first few cycles and then
refreshes weekly.
"""
from __future__ import annotations

import json
import os
import time

FIELDS = ("trailingPE", "forwardPE", "priceToBook", "debtToEquity",
          "profitMargins", "revenueGrowth", "marketCap")
MAX_AGE_DAYS = 7
FETCH_BUDGET = 15          # per call, keeps a cycle from stalling


def _cache_path(settings) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(settings.state_path)),
                        "fundamentals.json")


def get_fundamentals(settings, symbols: list[str]) -> dict[str, dict]:
    """{symbol: {field: value, "ts": epoch}} for what's cached; refreshes a
    budgeted batch of missing/stale symbols per call."""
    path = _cache_path(settings)
    try:
        with open(path) as fh:
            cache = json.load(fh)
    except (OSError, json.JSONDecodeError):
        cache = {}
    horizon = time.time() - MAX_AGE_DAYS * 86400
    stale = [s for s in symbols if "/" not in s              # crypto has no .info
             and cache.get(s, {}).get("ts", 0) <= horizon]
    if stale:
        try:
            import yfinance
        except ImportError:
            return cache
        for sym in stale[:FETCH_BUDGET]:
            row: dict = {"ts": time.time()}
            try:
                info = yfinance.Ticker(sym).info or {}
                for f in FIELDS:
                    v = info.get(f)
                    if isinstance(v, (int, float)):
                        row[f] = round(float(v), 4)
            except Exception:
                pass                                          # keep the ts: don't re-hammer failures
            cache[sym] = row
        try:
            with open(path, "w") as fh:
                json.dump(cache, fh)
        except OSError:
            pass
    return cache


def notable_extremes(fund: dict[str, dict], labels: dict[str, str]) -> dict[str, list[str]]:
    """Symbols whose valuation/health stands out, phrased for a prompt."""
    rich, cheap, stressed = [], [], []
    for sym, f in fund.items():
        name = labels.get(sym, sym)
        pe, fpe = f.get("trailingPE"), f.get("forwardPE")
        pb, de = f.get("priceToBook"), f.get("debtToEquity")
        margin = f.get("profitMargins")
        if (pe and pe > 45) or (pb and pb > 12):
            rich.append(f"{name} ({sym}): P/E {pe or '?'}, P/B {pb or '?'}")
        elif pe and 0 < pe < 12 and (margin or 0) > 0.05:
            cheap.append(f"{name} ({sym}): P/E {pe}, margins {margin:.0%}")
        if (de and de > 250) or (margin is not None and margin < 0):
            stressed.append(f"{name} ({sym}): debt/equity {de or '?'}, margins "
                            f"{f'{margin:.0%}' if margin is not None else '?'}")
    return {"richly_valued": rich[:8], "cheap": cheap[:8], "financially_stressed": stressed[:8]}
