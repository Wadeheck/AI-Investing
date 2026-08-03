"""Scalp backtest — 60d of Binance 1m data, train 70% / holdout 30%, real
maker/taker fees. Per docs/research/SCALP_MODEL.md the kill rule is pre-committed:
a family ships only if holdout net > 0 AND daily Sharpe >= 0.5.

Run: .venv/bin/python -m ai_investing.research.scalp_backtest [taker]
  'taker' scenario prices ALL fills at taker+slip (fee-sensitivity check).
Writes data/scalp_backtest.json.
"""
import json
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
import numpy as np

from ai_investing.scalp import engine as eng
from ai_investing.scalp import indicators as ind
from ai_investing.scalp import strategies as st

DATA = Path(__file__).resolve().parents[3] / "data"
HIST = DATA / "scalp_history"
SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

if "taker" in sys.argv:
    eng.MAKER = eng.TAKER          # everything pays taker: worst case


def run_symbol(sym, btc5, i0, i1, enabled):
    df1 = ind.load_1m(HIST / f"{sym}_1m.csv")
    df = ind.enrich(ind.resample(df1, "5min"))
    df1h = ind.resample(df1, "1h")
    df1h["dvol"] = df1h["close"] * df1h["vol"]
    bk = eng.Book()
    lv_cache, va_cache = [], {"in_value": True}
    for i in range(max(i0, 60), min(i1, len(df))):
        if i % 12 == 0:                       # refresh levels/VA hourly
            lv_cache = ind.confirmed_levels(df, i)
            va_cache = ind.value_area(df, i)
        h1 = df1h[df1h.index < df.index[i]]
        intents = st.generate(df, df1, h1, btc5, i, lv_cache, va_cache, enabled)
        eng.on_bar(bk, sym, df.index[i], df.iloc[i], intents)
    return bk, df


def metrics(bk, df, i0, i1):
    eq = [p["equity"] for p in bk.curve]
    if not eq:
        return {}
    days = max((i1 - i0) / 288.0, 1e-9)
    ret = eq[-1] / eq[0] - 1.0
    daily = np.array(eq[::288], dtype=float)
    dr = np.diff(daily) / daily[:-1] if len(daily) > 2 else np.array([0.0])
    sharpe = float(dr.mean() / (dr.std() + 1e-12) * np.sqrt(365))
    dd = 0.0
    peak = eq[0]
    for v in eq:
        peak = max(peak, v)
        dd = min(dd, v / peak - 1.0)
    wins = [t for t in bk.trades if t["pnl"] > 0]
    return {"net": round(ret, 4), "net_per_day": round(ret / days, 5),
            "sharpe_d": round(sharpe, 2), "maxdd": round(dd, 4),
            "trades": len(bk.trades), "trades_day": round(len(bk.trades) / days, 2),
            "win_rate": round(len(wins) / max(1, len(bk.trades)), 3)}


def main():
    scenario = "taker-only" if "taker" in sys.argv else "maker-entry"
    btc1 = ind.load_1m(HIST / "BTCUSDT_1m.csv")
    btc5 = ind.enrich(ind.resample(btc1, "5min"))
    n5 = len(btc5)
    t_end = int(n5 * 0.70)
    print(f"scenario {scenario}: {n5} 5m bars/symbol, train [0,{t_end}) holdout [{t_end},{n5})")
    report = {"scenario": scenario, "families": {}}
    for fam in st.FAMILIES:
        rows = {}
        for wname, (a, b) in (("train", (0, t_end)), ("holdout", (t_end, n5))):
            agg = {"net": 0.0, "trades": 0, "wins": 0}
            per = {}
            for sym in SYMS:
                bk, df = run_symbol(sym, btc5, a, b, (fam,))
                m = metrics(bk, df, a, b)
                per[sym] = m
                agg["net"] += m.get("net", 0.0)
                agg["trades"] += m.get("trades", 0)
                agg["wins"] += round(m.get("win_rate", 0) * m.get("trades", 0))
            rows[wname] = {"per_symbol": per,
                           "net_avg": round(agg["net"] / len(SYMS), 4),
                           "trades": agg["trades"],
                           "win_rate": round(agg["wins"] / max(1, agg["trades"]), 3)}
        ho = rows["holdout"]
        sh = [rows["holdout"]["per_symbol"][s].get("sharpe_d", 0) for s in SYMS]
        ships = ho["net_avg"] > 0 and float(np.mean(sh)) >= 0.5
        report["families"][fam] = {**rows, "holdout_sharpe_avg": round(float(np.mean(sh)), 2),
                                   "ships": bool(ships)}
        print(f"{fam:12s} train net {rows['train']['net_avg']:+.2%} ({rows['train']['trades']}tr, "
              f"wr {rows['train']['win_rate']:.0%}) | holdout net {ho['net_avg']:+.2%} "
              f"({ho['trades']}tr, wr {ho['win_rate']:.0%}, sharpe {np.mean(sh):.2f}) "
              f"-> {'SHIPS' if ships else 'killed'}")
    out = DATA / f"scalp_backtest{'_taker' if 'taker' in sys.argv else ''}.json"
    out.write_text(json.dumps(report, indent=1))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
