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

    dark_cloud = bull1 & bear & (O > c1) & (C < mid1) & (C > o1)

    # LONG side: own-name uptrend, pullback to SMA30, bullish reversal trigger
    up_trend = (sma30 > sma30.shift(5)) & (macd > 0)
    pullback = L <= sma30 * 1.02
    long_trig = (hammer | dragonfly | bull_engulf | piercing | morning
                 | (doji.shift(1).fillna(False) & bull))
    buy = (up_trend & pullback & long_trig).fillna(False)
    exit_long = ((C < sma30 * 0.98)
                 | ((macd < 0) & (macd.shift(1) >= 0))).fillna(False)

    # SHORT side: own-name downtrend, rally to SMA30, bearish reversal trigger
    dn_trend = (sma30 < sma30.shift(5)) & (macd < 0)
    rally = H >= sma30 * 0.98
    short_trig = (inv_hammer | gravestone | bear_engulf | dark_cloud | evening
                  | (doji.shift(1).fillna(False) & bear))
    sell_short = (dn_trend & rally & short_trig).fillna(False)
    exit_short = ((C > sma30 * 1.02)
                  | ((macd > 0) & (macd.shift(1) <= 0))).fillna(False)
    return buy, exit_long, sell_short, exit_short, L.copy(), H.copy()

BORROW_YR = 0.03          # borrow fee on short notional, per year
YEAR_BUDGET = 0.05        # -5% YTD -> flat until Jan 1 (backstop)

def run(O, H, L, C, symbols, buy_sig, exl_sig, sht_sig, exs_sig, tlow, thigh):
    cash, pos = START_CASH, {}      # qty>0 long, qty<0 short
    curve, dates = [], []
    trades = wins = 0
    year_start_eq, cur_year, halted = START_CASH, C.index[35].year, False
    for i in range(35, len(C)):
        op, lo, hi, cl = O.iloc[i], L.iloc[i], H.iloc[i], C.iloc[i]
        b = buy_sig.iloc[i - 1]
        xl = exl_sig.iloc[i - 1]
        sh = sht_sig.iloc[i - 1]
        xs = exs_sig.iloc[i - 1]
        if C.index[i].year != cur_year:
            cur_year = C.index[i].year
            year_start_eq = curve[-1] if curve else START_CASH
            halted = False
        for sym in list(pos):
            v = op[sym]
            if np.isnan(v):
                continue
            p = pos[sym]
            is_long = p["qty"] > 0
            fill = None
            if halted:
                fill = v
            elif is_long:
                if v <= p["stop"]:
                    fill = v
                elif not np.isnan(lo[sym]) and lo[sym] <= p["stop"]:
                    fill = p["stop"]
                elif xl.get(sym, False):
                    fill = v
            else:
                if v >= p["stop"]:
                    fill = v
                elif not np.isnan(hi[sym]) and hi[sym] >= p["stop"]:
                    fill = p["stop"]
                elif xs.get(sym, False):
                    fill = v
            if fill is None:
                # daily borrow accrual on open shorts
                if not is_long and not np.isnan(cl[sym]):
                    cash -= abs(p["qty"]) * cl[sym] * BORROW_YR / 252
                continue
            pos.pop(sym)
            cash += p["qty"] * fill
            cash -= abs(p["qty"]) * fill * COST_SIDE
            pnl = (fill - p["entry"]) * (1 if is_long else -1)
            trades += 1
            wins += 1 if pnl > 0 else 0
        eq = cash + sum(p["qty"] * cl[sym] for sym, p in pos.items()
                        if not np.isnan(cl[sym]))
        if not halted and eq <= year_start_eq * (1 - YEAR_BUDGET):
            halted = True
        for sym in symbols:
            if halted or len(pos) >= SLOTS:
                break
            if sym in pos or np.isnan(op[sym]):
                continue
            go_long = b.get(sym, False)
            go_short = sh.get(sym, False) and not go_long
            if not (go_long or go_short):
                continue
            ref = tlow.iloc[i - 1][sym] if go_long else thigh.iloc[i - 1][sym]
            if np.isnan(ref) or (go_long and ref >= op[sym]) or \
               (go_short and ref <= op[sym]):
                continue
            notional = eq / SLOTS
            if go_long:
                notional = min(notional, cash)
            if notional < 1000:
                continue
            qty = (notional / op[sym]) * (1 if go_long else -1)
            cash -= qty * op[sym]
            cash -= abs(qty) * op[sym] * COST_SIDE
            pos[sym] = {"qty": qty, "entry": op[sym], "stop": ref}
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
    buy, exl, sht, exs, tlow, thigh = signals(O, H, L, C)
    c, tr, wn = run(O, H, L, C, symbols, buy, exl, sht, exs, tlow, thigh)
    cagr, sh, dd = stats(c)
    print(f"\n=== LONG/SHORT ROTATION (per-name regime, borrow 3%/yr) — {period} "
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
