"""TIGHT confluence version of the Empower entry, per user direction.

Entry (both conditions, in order):
  SETUP:   close pierces BELOW the lower Bollinger band (20-SMA - 2 std)
           -> the name is "armed" for the next 5 trading days
  TRIGGER: MACD (12/26/9) bullish crossover (line crosses above signal)
           while armed -> buy at next day's open
Exit (either):
  - price pierces outside the UPPER Bollinger band (reversion completed)
  - MACD bearish crossover
Variants: with and without the 3% hard stop (resting intraday, gaps fill at open).

Physics unchanged: long/flat, next-open fills, 5 bps/side, 10-slot equal
weight, no leverage. Windows: 3y and 10y.
"""
import math
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
import pandas as pd
import yfinance as yf

from ai_investing.brain.graph import KnowledgeGraph

GRAPH_PATH = str(Path(__file__).resolve().parents[3] / "data" / "knowledge_graph.json")
COST_SIDE = 0.0005
START_CASH = 100_000.0
SLOTS = 10
ARM_DAYS = 5

g = KnowledgeGraph.load(GRAPH_PATH)
SYMS = sorted(getattr(n, "symbol") for n in g.nodes.values()
              if getattr(n, "symbol", None) and "/" not in getattr(n, "symbol"))

def load(period):
    data = yf.download([s.replace("/", "-") for s in SYMS], period=period,
                       interval="1d", auto_adjust=True, progress=False)
    ohlc = {}
    for f in ("Open", "High", "Low", "Close"):
        ohlc[f] = data[f].rename(columns={s.replace("/", "-"): s for s in SYMS})
    mask = ohlc["Close"].notna().mean(axis=1) > 0.5
    for f in ohlc:
        ohlc[f] = ohlc[f][mask].ffill(limit=5)
    keep = [s for s in SYMS if ohlc["Close"][s].notna().mean() > 0.8]
    for f in ohlc:
        ohlc[f] = ohlc[f][keep]
    return ohlc, keep

def cross_up(a, b):
    return (a > b) & (a.shift(1) <= b.shift(1))

def cross_dn(a, b):
    return (a < b) & (a.shift(1) >= b.shift(1))

def signals(O, H, L, C):
    ema12 = C.ewm(span=12, adjust=False).mean()
    ema26 = C.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    sig = macd.ewm(span=9, adjust=False).mean()
    mid = C.rolling(20).mean()
    std = C.rolling(20).std()
    below = C < (mid - 2 * std)
    armed = below.rolling(ARM_DAYS, min_periods=1).max().astype(bool)
    buy = (armed & cross_up(macd, sig)).fillna(False)
    sell = ((C > mid + 2 * std) | cross_dn(macd, sig)).fillna(False)
    return buy, sell

def run(O, L, C, symbols, buy_sig, sell_sig, stop_pct):
    cash, pos = START_CASH, {}
    curve, dates = [], []
    trades = wins = 0
    for i in range(30, len(C)):
        op, lo, cl = O.iloc[i], L.iloc[i], C.iloc[i]
        b, s = buy_sig.iloc[i - 1], sell_sig.iloc[i - 1]
        for sym in list(pos):
            v = op[sym]
            if np.isnan(v):
                continue
            p = pos[sym]
            fill = None
            if stop_pct:
                stop = p["entry"] * (1 - stop_pct)
                if v <= stop:
                    fill = v
                elif not np.isnan(lo[sym]) and lo[sym] <= stop:
                    fill = stop
            if fill is None and s.get(sym, False):
                fill = v
            if fill is None:
                continue
            pos.pop(sym)
            cash += p["qty"] * fill * (1 - COST_SIDE)
            trades += 1
            wins += 1 if fill > p["entry"] else 0
        eq = cash + sum(p["qty"] * cl[sym] for sym, p in pos.items()
                        if not np.isnan(cl[sym]))
        for sym in symbols:
            if len(pos) >= SLOTS:
                break
            if not b.get(sym, False) or sym in pos or np.isnan(op[sym]):
                continue
            notional = min(eq / SLOTS, cash)
            if notional < 1000:
                continue
            qty = notional / op[sym]
            cash -= qty * op[sym] * (1 + COST_SIDE)
            pos[sym] = {"qty": qty, "entry": op[sym]}
        dates.append(C.index[i])
        curve.append(cash + sum(p["qty"] * cl[sym] for sym, p in pos.items()
                                if not np.isnan(cl[sym])))
    return pd.Series(curve, index=dates), trades, wins

def stats(c):
    r = c.pct_change().dropna()
    years = len(c) / 252
    cagr = (c.iloc[-1] / c.iloc[0]) ** (1 / years) - 1
    sharpe = r.mean() / (r.std() + 1e-12) * math.sqrt(252)
    dd = ((c / c.cummax()) - 1).min()
    return cagr, sharpe, dd

for period in ("3y", "10y"):
    ohlc, symbols = load(period)
    O, H, L, C = ohlc["Open"], ohlc["High"], ohlc["Low"], ohlc["Close"]
    buy, sell = signals(O, H, L, C)
    print(f"\n=== TIGHT ENTRY (BB pierce armed {ARM_DAYS}d + MACD cross) — {period} "
          f"({C.index[0].date()} -> {C.index[-1].date()}, {len(symbols)} names) ===")
    for label, sp in (("no stop", None), ("3% stop", 0.03)):
        c, tr, wn = run(O, L, C, symbols, buy, sell, sp)
        cagr, sh, dd = stats(c)
        yrs = "  ".join(f"{y}:{c[c.index.year == y].iloc[-1] / c[c.index.year == y].iloc[0] - 1:+.0%}"
                        for y in sorted({d.year for d in c.index})
                        if len(c[c.index.year == y]) > 20)
        print(f"  [{label}]  CAGR {cagr:+.1%}  Sharpe {sh:.2f}  maxDD {dd:.1%}  "
              f"trades {tr}  win {wn / max(1, tr):.0%}")
        print(f"     {yrs}")
    bench = (C / C.iloc[0]).mean(axis=1).iloc[30:] * START_CASH
    spy = yf.download("SPY", period=period, interval="1d", auto_adjust=True,
                      progress=False)["Close"].squeeze().reindex(C.index).ffill().iloc[30:]
    spy = spy / spy.iloc[0] * START_CASH
    for name, bc in (("equal-weight universe B&H", bench), ("SPY B&H", spy)):
        bcagr, bsh, bdd = stats(bc)
        print(f"  BENCH {name}: CAGR {bcagr:+.1%}  Sharpe {bsh:.2f}  maxDD {bdd:.1%}")
