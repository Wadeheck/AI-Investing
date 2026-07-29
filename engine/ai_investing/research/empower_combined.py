"""ONE combined strategy from the Empower Advisory course pages, tested as a whole.

The book's own structure (stated repeatedly: "other indicators must be used in
conjunction ...") is hierarchical:

  TREND (MACD as Trend Indicator): positive range = bullish trend. Only trade
  long while the trend is bullish. Trend break (MACD crossing below the
  centreline) = clear indication momentum flipped bearish -> exit everything
  in that name.

  TIMING (buy signals, any one, taken only while the trend is bullish):
    - Stochastic: %D crosses UP through the 5-period smoothed %D, set up
      below the 20 level (mid-level crossovers ignored, per the printed rule)
    - Bollinger: price has fallen below the lower 20/2 band (revert to mean)
    - A CONFIRMED bullish candlestick reversal after a downswing (hammer,
      inverted hammer, dragonfly doji, bullish engulfing, piercing line,
      morning star) — confirmation candle required, per the book
    - MACD bullish crossover (line crosses above signal from below)

  SELL signals (any one -> exit):
    - Stochastic: %D crosses DOWN through smoothed %D above the 80 level
    - Price pierces outside the upper Bollinger band
    - A CONFIRMED bearish candlestick reversal after an upswing (hanging man,
      shooting star, gravestone doji, bearish engulfing, dark cloud cover,
      evening star)
    - MACD bearish centreline crossing (trend break)

All formulas/parameters verbatim from the book: MACD 12/26/9, stochastic %D
with 5-period smoothing and the 20/80 discipline, Bollinger 20-period +/-2
standard deviations, "lower shadow at least twice as big as the real body",
50% retracement for piercing/dark-cloud, gap rules inside engulfing/stars.
Nothing tuned.

Physics: long/flat, next-day-OPEN fills, 5 bps/side, 10-slot equal weight,
no leverage. Run on BOTH 3y and 10y windows (regime diversity check).
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
STOP_PCT = 0.03           # user-mandated 3% hard stop below entry

g = KnowledgeGraph.load(GRAPH_PATH)
SYMS = sorted(getattr(n, "symbol") for n in g.nodes.values()
              if getattr(n, "symbol", None) and "/" not in getattr(n, "symbol"))

def yf_sym(s):
    return s.replace("/", "-")

def load(period):
    data = yf.download([yf_sym(s) for s in SYMS], period=period, interval="1d",
                       auto_adjust=True, progress=False)
    ohlc = {}
    for f in ("Open", "High", "Low", "Close"):
        ohlc[f] = data[f].rename(columns={yf_sym(s): s for s in SYMS})
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

    l14, h14 = L.rolling(14).min(), H.rolling(14).max()
    pk = 100 * (C - l14) / (h14 - l14 + 1e-12)
    pd_ = pk.rolling(3).mean()
    pds = pd_.rolling(5).mean()

    mid = C.rolling(20).mean()
    std = C.rolling(20).std()
    bb_up, bb_lo = mid + 2 * std, mid - 2 * std

    sma20 = C.rolling(20).mean()
    up = (C > sma20) & (sma20 > sma20.shift(3))
    dn = (C < sma20) & (sma20 < sma20.shift(3))

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
    dark_cloud = bull1 & bear & (O > c1) & (C < mid1) & (C > o1)

    o2, c2 = O.shift(2), C.shift(2)
    bull2, bear2 = bull.shift(2).fillna(False), bear.shift(2).fillna(False)
    long2 = long_body.shift(2).fillna(False)
    small1 = small_body.shift(1).fillna(False)
    mid2 = (o2 + c2) / 2
    morning = (bear2 & long2 & small1
               & (C.shift(1).combine(O.shift(1), np.minimum) < c2)
               & bull & long_body & (C > mid2))
    evening = (bull2 & long2 & small1
               & (C.shift(1).combine(O.shift(1), np.maximum) > c2)
               & bear & long_body & (C < mid2))

    bull_raw = (hammer | inv_hammer | dragonfly | bull_engulf | piercing | morning) & dn
    bear_raw = (hammer | inv_hammer | gravestone | bear_engulf | dark_cloud | evening) & up
    bull_candle = bull_raw.shift(1).fillna(False) & bull      # confirmation candle
    bear_candle = bear_raw.shift(1).fillna(False) & bear

    sto_buy = cross_up(pd_, pds) & (pd_.shift(1) < 20)
    sto_sell = cross_dn(pd_, pds) & (pd_.shift(1) > 80)
    zero = macd * 0

    regime = macd > 0                                          # bullish trend
    timing = sto_buy | (C < bb_lo) | bull_candle | cross_up(macd, sig)
    buy = (regime & timing).fillna(False)
    sell = (sto_sell | (C > bb_up) | bear_candle | cross_dn(macd, zero)).fillna(False)
    return buy, sell

def run(O, H, L, C, symbols, buy_sig, sell_sig):
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
            stop = p["entry"] * (1 - STOP_PCT)
            if v <= stop:                      # gapped through -> fill at open
                fill = v
            elif not np.isnan(lo[sym]) and lo[sym] <= stop:
                fill = stop                    # resting intraday stop order
            elif s.get(sym, False):
                fill = v                       # signal exit at the open
            else:
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
    c, tr, wn = run(O, H, L, C, symbols, buy, sell)
    cagr, sh, dd = stats(c)
    print(f"\n=== COMBINED EMPOWER STRATEGY — {period} window "
          f"({C.index[0].date()} -> {C.index[-1].date()}, {len(symbols)} names) ===")
    print(f"  CAGR {cagr:+.1%}  Sharpe {sh:.2f}  maxDD {dd:.1%}  "
          f"trades {tr}  win rate {wn / max(1, tr):.0%}")
    for y in sorted({d.year for d in c.index}):
        yc = c[c.index.year == y]
        if len(yc) > 20:
            print(f"    {y}: {yc.iloc[-1] / yc.iloc[0] - 1:+.1%}")
    bench = (C / C.iloc[0]).mean(axis=1).iloc[30:] * START_CASH
    spy = yf.download("SPY", period=period, interval="1d", auto_adjust=True,
                      progress=False)["Close"].squeeze().reindex(C.index).ffill().iloc[30:]
    spy = spy / spy.iloc[0] * START_CASH
    for name, bc in (("equal-weight universe B&H", bench), ("SPY B&H", spy)):
        bcagr, bsh, bdd = stats(bc)
        print(f"  BENCH {name}: CAGR {bcagr:+.1%}  Sharpe {bsh:.2f}  maxDD {bdd:.1%}")
