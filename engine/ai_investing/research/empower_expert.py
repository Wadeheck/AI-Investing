"""Expert synthesis: 30-day pullback-reversal system (designed, then tested once).

Ingredients per user request: MACD, daily moving averages (30-day), doji and
candlestick patterns. Structure: trend -> location -> trigger -> invalidation.

LONG-ONLY rules (all evaluated on completed daily bars, acted at next open):
  TREND:    SMA30 rising (above its value 5 days ago) AND MACD(12/26) > 0
  LOCATION: day's low within 2% of SMA30 (pullback to the average)
  TRIGGER:  bullish reversal candle at that location — hammer, dragonfly doji,
            bullish engulfing, piercing, morning star — OR yesterday doji +
            today bullish candle
  STOP:     resting intraday stop at the trigger candle's LOW (pattern
            invalidation; gaps through fill at the open)
  EXITS:    close < 0.98*SMA30 (trend break), MACD crosses below 0,
            or confirmed bearish reversal (shooting star / evening star /
            gravestone / hanging man / bearish engulfing) while close is
            >10% above SMA30 (extended)

Physics: identical to all prior runs — long/flat, next-open fills, 5 bps/side,
10-slot equal weight, no leverage. Windows: 3y and 10y. No parameter search.
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

def signals(O, H, L, C):
    ema12 = C.ewm(span=12, adjust=False).mean()
    ema26 = C.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    sma30 = C.rolling(30).mean()

    body = (C - O).abs()
    upsh = H - C.where(C > O, O)
    losh = C.where(C < O, O) - L
    bull, bear = C > O, C < O
    rng = (H - L) + 1e-12
    avg_body = body.rolling(20).mean()
    long_body = body > avg_body
    small_body = body < 0.5 * avg_body
    doji = body <= 0.1 * rng

    hammer = (losh >= 2 * body) & (upsh <= 0.2 * rng) & (body > 0)
    inv_hammer = (upsh >= 2 * body) & (losh <= 0.2 * rng) & (body > 0)
    dragonfly = doji & (losh >= 2 * upsh + 0.3 * rng)
    gravestone = doji & (upsh >= 2 * losh + 0.3 * rng)

    o1, c1, body1 = O.shift(1), C.shift(1), body.shift(1)
    bull1, bear1 = bull.shift(1).fillna(False), bear.shift(1).fillna(False)
    mid1 = (o1 + c1) / 2
    bull_engulf = bear1 & bull & (O < c1) & (C > o1) & (body > body1)
    bear_engulf = bull1 & bear & (O > c1) & (C < o1) & (body > body1)
    piercing = bear1 & bull & (O < c1) & (C > mid1) & (C < o1)

    o2, c2 = O.shift(2), C.shift(2)
    bear2 = bear.shift(2).fillna(False)
    long2 = long_body.shift(2).fillna(False)
    small1 = small_body.shift(1).fillna(False)
    mid2 = (o2 + c2) / 2
    morning = (bear2 & long2 & small1
               & (C.shift(1).combine(O.shift(1), np.minimum) < c2)
               & bull & long_body & (C > mid2))
    bull2_ = bull.shift(2).fillna(False)
    evening = (bull2_ & long2 & small1
               & (C.shift(1).combine(O.shift(1), np.maximum) > c2)
               & bear & long_body & (C < mid2))

    trend = (sma30 > sma30.shift(5)) & (macd > 0)
    pullback = L <= sma30 * 1.02
    trigger = (hammer | dragonfly | bull_engulf | piercing | morning
               | (doji.shift(1).fillna(False) & bull))
    buy = (trend & pullback & trigger).fillna(False)

    extended = C > sma30 * 1.10
    bear_rev_raw = ((hammer | inv_hammer) & extended) | gravestone | bear_engulf | evening
    bear_rev = bear_rev_raw.shift(1).fillna(False) & bear & extended
    zero = macd * 0
    exit_sig = ((C < sma30 * 0.98)
                | ((macd < 0) & (macd.shift(1) >= 0))
                | bear_rev).fillna(False)
    return buy, exit_sig, L.copy()

def run(O, L, C, symbols, buy_sig, sell_sig, trig_low):
    cash, pos = START_CASH, {}
    curve, dates = [], []
    trades = wins = 0
    for i in range(35, len(C)):
        op, lo, cl = O.iloc[i], L.iloc[i], C.iloc[i]
        b, s = buy_sig.iloc[i - 1], sell_sig.iloc[i - 1]
        for sym in list(pos):
            v = op[sym]
            if np.isnan(v):
                continue
            p = pos[sym]
            fill = None
            if v <= p["stop"]:
                fill = v                              # gapped through
            elif not np.isnan(lo[sym]) and lo[sym] <= p["stop"]:
                fill = p["stop"]                      # resting stop
            elif s.get(sym, False):
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
            stop = trig_low.iloc[i - 1][sym]          # trigger candle's low
            if np.isnan(stop) or stop >= op[sym]:
                continue
            notional = min(eq / SLOTS, cash)
            if notional < 1000:
                continue
            qty = notional / op[sym]
            cash -= qty * op[sym] * (1 + COST_SIDE)
            pos[sym] = {"qty": qty, "entry": op[sym], "stop": stop}
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
    buy, sell, tlow = signals(O, H, L, C)
    c, tr, wn = run(O, L, C, symbols, buy, sell, tlow)
    cagr, sh, dd = stats(c)
    print(f"\n=== EXPERT 30d PULLBACK-REVERSAL — {period} "
          f"({C.index[0].date()} -> {C.index[-1].date()}, {len(symbols)} names) ===")
    print(f"  CAGR {cagr:+.1%}  Sharpe {sh:.2f}  maxDD {dd:.1%}  "
          f"trades {tr}  win {wn / max(1, tr):.0%}")
    yrs = "  ".join(f"{y}:{c[c.index.year == y].iloc[-1] / c[c.index.year == y].iloc[0] - 1:+.0%}"
                    for y in sorted({d.year for d in c.index})
                    if len(c[c.index.year == y]) > 20)
    print(f"    {yrs}")
    bench = (C / C.iloc[0]).mean(axis=1).iloc[35:] * START_CASH
    spy = yf.download("SPY", period=period, interval="1d", auto_adjust=True,
                      progress=False)["Close"].squeeze().reindex(C.index).ffill().iloc[35:]
    spy = spy / spy.iloc[0] * START_CASH
    for name, bc in (("equal-weight universe B&H", bench), ("SPY B&H", spy)):
        bcagr, bsh, bdd = stats(bc)
        print(f"  BENCH {name}: CAGR {bcagr:+.1%}  Sharpe {bsh:.2f}  maxDD {bdd:.1%}")
EOF = None
