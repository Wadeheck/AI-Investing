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
          "profitMargins", "revenueGrowth", "marketCap",
          "returnOnEquity", "operatingMargins", "earningsGrowth")
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


def quality_value(f: dict) -> tuple[float, str]:
    """Buffett-style margin-of-safety score in [0, 1] with a plain reason.

    Quality: does the business earn well (ROE, margins) without leaning on
    debt? Value: are you paying a sane price for those earnings, with growth
    not already priced for perfection? 0.5 = nothing known / neutral."""
    pe = f.get("trailingPE") or f.get("forwardPE")
    roe, margins = f.get("returnOnEquity"), f.get("operatingMargins") or f.get("profitMargins")
    de, growth = f.get("debtToEquity"), f.get("earningsGrowth") or f.get("revenueGrowth")
    known = [v for v in (pe, roe, margins, de) if v is not None]
    if len(known) < 2:
        return 0.5, "limited fundamentals data — sized neutrally"
    q = 0.0
    q += min(1.0, max(0.0, (roe - 0.05) / 0.25)) if roe is not None else 0.5      # ROE 5%→0, 30%→1
    q += min(1.0, max(0.0, (margins - 0.02) / 0.25)) if margins is not None else 0.5
    q += min(1.0, max(0.0, (200.0 - de) / 180.0)) if de is not None else 0.5      # low debt scores
    q /= 3.0
    v = 0.5
    if pe and pe > 0:
        v = min(1.0, max(0.0, (35.0 - pe) / 27.0))                                # PE 8→1, 35→0
        if growth is not None and growth > 0.15 and pe < 40:
            v = min(1.0, v + 0.15)                                                # growth at a fair price
    score = round(0.55 * q + 0.45 * v, 3)
    bits = []
    if roe is not None:
        bits.append(f"ROE {roe:.0%}")
    if margins is not None:
        bits.append(f"margins {margins:.0%}")
    if pe:
        bits.append(f"P/E {pe:.0f}")
    if de is not None:
        bits.append(f"debt/equity {de:.0f}")
    tone = ("wonderful business at a fair price" if score >= 0.65 else
            "decent quality for the price" if score >= 0.45 else
            "quality/value below the bar — sized down")
    return score, f"{tone} ({', '.join(bits)})"


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
