"""The expectations layer: consensus, revisions, and earnings surprises.

Markets trade the gap between consensus and reality — a model that only
knows actuals is structurally late. Three signals, all free via the provider:

  revisions : direction of consensus EPS changes over the last 30/7 days
              (revision momentum — a documented, durable institutional factor)
  surprise  : average of the last 4 quarters' EPS surprise %, plus the most
              recent one (post-earnings drift rides positive surprises)
  target_gap: consensus price target vs current price (weak signal, wide
              error bars — used only at small weight)

Everything cached 7 days per symbol, budget-capped per refresh call, and
scored into one expectations tilt in [-1, 1].
"""
from __future__ import annotations

import json
import os
import time

CACHE_AGE = 7 * 86400
FETCH_BUDGET = 30


def _cache_path(settings=None) -> str:
    base = (os.path.dirname(os.path.abspath(settings.state_path)) if settings is not None
            else os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.dirname(os.path.abspath(__file__))))), "data"))
    return os.path.join(base, "estimates.json")


def _load(settings=None) -> dict:
    try:
        with open(_cache_path(settings)) as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}


def fetch_one(symbol: str) -> dict:
    """Raw expectations data for one symbol; {} when the provider has none."""
    import warnings
    warnings.filterwarnings("ignore")
    import yfinance as yf
    t = yf.Ticker(symbol)
    out: dict = {}
    try:
        tr = t.eps_trend            # rows: 0q,+1q,0y,+1y | cols incl current, 7daysAgo, 30daysAgo
        if tr is not None and not tr.empty and "0y" in tr.index:
            row = tr.loc["0y"]
            cur, d7, d30 = row.get("current"), row.get("7daysAgo"), row.get("30daysAgo")
            if cur and d30:
                out["rev_30d"] = round(float(cur) / float(d30) - 1, 4)
            if cur and d7:
                out["rev_7d"] = round(float(cur) / float(d7) - 1, 4)
    except Exception:
        pass
    try:
        eh = t.earnings_history     # cols: epsEstimate, epsActual, surprisePercent
        if eh is not None and not eh.empty and "surprisePercent" in eh.columns:
            sp = [float(x) for x in eh["surprisePercent"].dropna().tolist()[-4:]]
            if sp:
                out["surprise_last"] = round(sp[-1], 4)
                out["surprise_avg4"] = round(sum(sp) / len(sp), 4)
    except Exception:
        pass
    try:
        pt = t.analyst_price_targets or {}
        if pt.get("mean") and pt.get("current"):
            out["target_gap"] = round(float(pt["mean"]) / float(pt["current"]) - 1, 4)
            out["n_analysts"] = pt.get("numberOfAnalysts")
    except Exception:
        pass
    return out


def score(rec: dict) -> float:
    """One expectations tilt in [-1, 1]: revisions dominate, surprises second,
    target gap a whisper."""
    if not rec:
        return 0.0
    s = 0.0
    r30 = rec.get("rev_30d")
    if r30 is not None:
        s += max(-0.5, min(0.5, r30 * 10))          # ±5% revision = full ±0.5
    sa = rec.get("surprise_avg4")
    if sa is not None:
        s += max(-0.3, min(0.3, sa * 3))            # ±10% avg surprise = ±0.3
    tg = rec.get("target_gap")
    if tg is not None:
        s += max(-0.15, min(0.15, tg * 0.5))
    return round(max(-1.0, min(1.0, s)), 3)


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


def expectation_scores(settings=None) -> dict[str, float]:
    """symbol -> expectations tilt, from cache only (refresh() to update)."""
    return {sym: rec.get("score", 0.0) for sym, rec in _load(settings).items()
            if rec.get("score")}


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    from ai_investing.data.fundamentals_history import graph_stock_symbols
    c = refresh(graph_stock_symbols(), budget=int(sys.argv[sys.argv.index("--limit") + 1])
                if "--limit" in sys.argv else FETCH_BUDGET)
    ranked = sorted(((s, r) for s, r in c.items() if r.get("score")),
                    key=lambda kv: -kv[1]["score"])
    print("top positive expectations (revisions/surprises):")
    for s, r in ranked[:10]:
        print(f"  {s:10s} {r['score']:+.2f}  rev30d {r.get('rev_30d')}  "
              f"surpAvg {r.get('surprise_avg4')}  targetGap {r.get('target_gap')}")
    print("most negative:")
    for s, r in ranked[-5:]:
        print(f"  {s:10s} {r['score']:+.2f}  rev30d {r.get('rev_30d')}  "
              f"surpAvg {r.get('surprise_avg4')}")
