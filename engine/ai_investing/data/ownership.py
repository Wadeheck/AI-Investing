"""Ownership & flow signals: who is on the other side of the trade.

  insiders      : net open-market insider activity, last ~6 months. A CLUSTER
                  of buys (2+ distinct purchases) is one of the few free,
                  evidence-backed bullish signals — insiders sell for many
                  reasons but buy for one. Sales are only mildly informative.
  short interest: % of float sold short. >15% = crowded short — treated as a
                  CAUTION both ways (squeeze fuel on longs' side, but the
                  crowd is sometimes right — see the integrity layer), never
                  as a naive contrarian buy signal.
  buybacks      : net share-count change already lives in the fundamentals
                  history (dilution_rate) — shrinking count = standing bid.

Cached 7 days, budget-capped. Output: one ownership tilt per symbol plus the
raw facts for the report.
"""
from __future__ import annotations

import json
import os
import time

CACHE_AGE = 7 * 86400
FETCH_BUDGET = 30


def _cache_path(settings=None) -> str:
    from ai_investing.data.paths import data_path
    return data_path("ownership.json", settings)


def _load(settings=None) -> dict:
    try:
        with open(_cache_path(settings)) as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}


def fetch_one(symbol: str) -> dict:
    import warnings
    warnings.filterwarnings("ignore")
    import yfinance as yf
    t = yf.Ticker(symbol)
    out: dict = {}
    try:
        # transaction-level truth: only "Purchase at price" is an open-market
        # buy. The summary table counts grants/awards as "purchases", which
        # made every mega-cap look insider-supported — it isn't.
        it = t.insider_transactions
        if it is not None and not it.empty and "Text" in it.columns:
            import pandas as pd
            cutoff = pd.Timestamp.now() - pd.Timedelta(days=180)
            if "Start Date" in it.columns:
                it = it[pd.to_datetime(it["Start Date"], errors="coerce") >= cutoff]
            txt = it["Text"].astype(str).str.lower()
            buys_df = it[txt.str.contains("purchase at price")]
            sells_df = it[txt.str.contains("sale at price")]
            out["insider_buys"] = int(len(buys_df))
            out["insider_buyers"] = int(buys_df["Insider"].nunique()) if len(buys_df) else 0
            out["insider_buy_value"] = float(buys_df["Value"].fillna(0).sum()) if len(buys_df) else 0.0
            out["insider_sells"] = int(len(sells_df))
    except Exception:
        pass
    try:
        info = t.info or {}
        spf = info.get("shortPercentOfFloat")
        if spf is not None:
            out["short_pct_float"] = round(float(spf) * (0.01 if spf > 1 else 1.0), 4)
        if info.get("heldPercentInsiders") is not None:
            out["insider_held_pct"] = round(float(info["heldPercentInsiders"]), 4)
    except Exception:
        pass
    return out


def score(rec: dict) -> float:
    """Ownership tilt in [-0.5, 0.5]: insider buy clusters dominate."""
    if not rec:
        return 0.0
    s = 0.0
    buys = rec.get("insider_buys", 0)
    buyers = rec.get("insider_buyers", buys)
    sells = rec.get("insider_sells", 0)
    # true open-market purchases only (transaction-text filtered): a CLUSTER
    # means 2+ DISTINCT insiders buying with their own money
    if buys >= 2 and buyers >= 2:
        s += 0.35                                   # the cluster-buy signal
    elif buys >= 1:
        s += 0.15
    elif sells >= 5 and buys == 0:
        s -= 0.10                                   # exodus with zero buying
    spf = rec.get("short_pct_float")
    if spf is not None and spf >= 0.15:
        s -= 0.10                                   # crowded — caution, not contrarian
    return round(max(-0.5, min(0.5, s)), 3)


def refresh(symbols: list[str], settings=None, budget: int = FETCH_BUDGET) -> dict:
    cache = _load(settings)
    now = time.time()
    todo = [s for s in symbols
            if now - cache.get(s, {}).get("asof", 0) >= CACHE_AGE]
    for sym in todo[:budget]:
        try:
            rec = fetch_one(sym)
        except Exception:
            rec = {}
        cache[sym] = {"asof": now, **rec, "score": score(rec)}
        time.sleep(0.3)
    try:
        os.makedirs(os.path.dirname(_cache_path(settings)), exist_ok=True)
        with open(_cache_path(settings), "w") as fh:
            json.dump(cache, fh)
    except OSError:
        pass
    return cache


def ownership_scores(settings=None) -> dict[str, float]:
    return {sym: rec.get("score", 0.0) for sym, rec in _load(settings).items()
            if rec.get("score")}


def crowded_shorts(settings=None, threshold: float = 0.15) -> dict[str, float]:
    """symbol -> short % of float, where it exceeds the crowding threshold."""
    return {sym: rec["short_pct_float"] for sym, rec in _load(settings).items()
            if rec.get("short_pct_float", 0) >= threshold}


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    from ai_investing.data.fundamentals_history import graph_stock_symbols
    c = refresh(graph_stock_symbols(), budget=int(sys.argv[sys.argv.index("--limit") + 1])
                if "--limit" in sys.argv else FETCH_BUDGET)
    pos = sorted(((s, r) for s, r in c.items() if r.get("score", 0) > 0),
                 key=lambda kv: -kv[1]["score"])
    print("insider-supported names:")
    for s, r in pos[:12]:
        print(f"  {s:10s} {r['score']:+.2f}  buys {r.get('insider_buys')} "
              f"sells {r.get('insider_sells')}  short% {r.get('short_pct_float')}")
    cs = {s: r.get("short_pct_float") for s, r in c.items()
          if r.get("short_pct_float", 0) >= 0.15}
    print("crowded shorts (>=15% float):", cs or "none")
