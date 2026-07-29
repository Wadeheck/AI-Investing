"""Backtest of the Empower Advisory Stock Investment Programme rules, verbatim.

Source: user-provided course pages (photos, 2026-07-29). Every formula and
parameter below is taken from the book AS PRINTED — nothing tuned, nothing
"fixed":

  MACD:        12/26-day EMA difference, 9-day EMA signal line.
               - Crossover: bullish when MACD crosses above signal from below,
                 bearish when it crosses below from above.
               - Centreline: positive range = bullish trend, negative = bearish.
  Stochastic:  %D with a 5-period smoothed %D.
               - Buy when %D crosses UP through smoothed %D, sell when %D
                 crosses DOWN through smoothed %D.
               - "Important! Do not take mid-level crossovers as entry signals
                 ... wait for the higher probability signal to set up at the
                 above 80 level and below 20 level."
  Bollinger:   20-period SMA +/- 2 standard deviations.
               - Buy when price has fallen below the lower band; sell/exit
                 when the stock pierces outside the upper band.
  Candles:     reversal patterns requiring a PRIOR TREND ("A prior trend must
               be seen ... determined using trend lines and moving averages")
               and confirmation where the book demands it:
               bullish (after downtrend): hammer, inverted hammer, bullish
               engulfing, piercing line, morning star, dragonfly doji;
               bearish (after uptrend): hanging man, shooting star, bearish
               engulfing, dark cloud cover, evening star, gravestone doji.
               Shadow rule from the book: "lower shadow at least twice as big
               as real body"; dark cloud/piercing use the printed 50%
               retracement rule; stars use the printed gap rules.
  Combo:       the book teaches MACD as the TREND indicator and stochastic as
               the timing signal -> take stochastic buys only while MACD is in
               positive range (bullish trend), exit on stochastic sell or MACD
               turning negative.

Test physics (project house rules, matching the mechanical replay baseline):
next-day-OPEN fills after a signal (no same-bar fills), 5 bps per side, no
leverage, no shorts (long/flat), equal-weight 10-slot portfolio. Universe =
the project's 85 stock/ETF symbols; crypto excluded (stock programme).

Portfolio sizing is NOT specified by the book; the 10-slot equal-weight model
is the neutral default and is identical across all strategy variants so the
comparison is signal-vs-signal.
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
COST_SIDE = 0.0005        # 5 bps per side, same as replay3y mechanical baseline
START_CASH = 100_000.0
SLOTS = 10                # equal-weight portfolio slots (house default, not book)

g = KnowledgeGraph.load(GRAPH_PATH)
symbols = sorted(getattr(n, "symbol") for n in g.nodes.values()
                 if getattr(n, "symbol", None) and "/" not in getattr(n, "symbol"))

def yf_sym(s):
    return s.replace("/", "-")

data = yf.download([yf_sym(s) for s in symbols], period="3y", interval="1d",
                   auto_adjust=True, progress=False)
ohlc = {}
for f in ("Open", "High", "Low", "Close"):
    df = data[f].rename(columns={yf_sym(s): s for s in symbols})
    ohlc[f] = df
# align to rows where most stocks printed, forward-fill small gaps
mask = ohlc["Close"].notna().mean(axis=1) > 0.5
for f in ohlc:
    ohlc[f] = ohlc[f][mask].ffill(limit=5)
keep = [s for s in symbols if ohlc["Close"][s].notna().mean() > 0.8]
for f in ohlc:
    ohlc[f] = ohlc[f][keep]
symbols = keep
O, H, L, C = ohlc["Open"], ohlc["High"], ohlc["Low"], ohlc["Close"]
print(f"universe: {len(symbols)} stock/ETF symbols, {len(C)} days "
      f"({C.index[0].date()} -> {C.index[-1].date()})", flush=True)

# ---------------- indicators, exactly as printed ----------------
ema12 = C.ewm(span=12, adjust=False).mean()
ema26 = C.ewm(span=26, adjust=False).mean()
macd = ema12 - ema26
macd_sig = macd.ewm(span=9, adjust=False).mean()

# Stochastic: fast %K over 14, %D = 3-SMA of %K, smoothed %D = 5-SMA of %D.
# (The book page shows "%D" vs a "5-period smoothed %D"; 14/3 are the
# standard construction the course charts display.)
l14 = L.rolling(14).min()
h14 = H.rolling(14).max()
pk = 100 * (C - l14) / (h14 - l14 + 1e-12)
pd_ = pk.rolling(3).mean()          # %D
pds = pd_.rolling(5).mean()         # smoothed %D

bb_mid = C.rolling(20).mean()
bb_std = C.rolling(20).std()
bb_up = bb_mid + 2 * bb_std
bb_lo = bb_mid - 2 * bb_std

# prior trend via moving average (book: "trend lines and moving averages")
sma20 = C.rolling(20).mean()
uptrend = (C > sma20) & (sma20 > sma20.shift(3))
downtrend = (C < sma20) & (sma20 < sma20.shift(3))

# ---------------- candlestick patterns, book definitions ----------------
body = (C - O).abs()
upsh = H - C.where(C > O, O)           # upper shadow
losh = C.where(C < O, O) - L           # lower shadow
bull = C > O
bear = C < O
rng = (H - L) + 1e-12
avg_body = body.rolling(20).mean()
long_body = body > avg_body            # "long" candle vs recent context
small_body = body < 0.5 * avg_body
doji = body <= 0.1 * rng               # open ~= close

hammer = (losh >= 2 * body) & (upsh <= 0.2 * rng) & (body > 0)
inv_hammer = (upsh >= 2 * body) & (losh <= 0.2 * rng) & (body > 0)
dragonfly = doji & (losh >= 2 * upsh + 0.3 * rng)
gravestone = doji & (upsh >= 2 * losh + 0.3 * rng)

o1, c1 = O.shift(1), C.shift(1)
bull1, bear1 = bull.shift(1).fillna(False), bear.shift(1).fillna(False)
body1 = body.shift(1)
mid1 = (O.shift(1) + C.shift(1)) / 2

# engulfing: smaller day-1 candle, opposite larger day-2 that gaps beyond and
# closes past day-1's open (book: gap down/up rejected, close beyond open)
bull_engulf = bear1 & bull & (O < c1) & (C > o1) & (body > body1)
bear_engulf = bull1 & bear & (O > c1) & (C < o1) & (body > body1)

# piercing: gap down open below day-1 low? book: gaps down, closes above 50%
# of day-1 bearish body
piercing = bear1 & bull & (O < c1) & (C > mid1) & (C < o1)
# dark cloud: gap up, close below 50% of day-1 bullish body
dark_cloud = bull1 & bear & (O > c1) & (C < mid1) & (C > o1)

o2, c2 = O.shift(2), C.shift(2)
bull2, bear2 = bull.shift(2).fillna(False), bear.shift(2).fillna(False)
long2 = long_body.shift(2).fillna(False)
small1 = small_body.shift(1).fillna(False)
mid2 = (O.shift(2) + C.shift(2)) / 2

# morning star: large bearish, gap-down small candle (any colour / doji),
# large bullish closing well into day-1 body
morning_star = (bear2 & long2 & small1
                & (C.shift(1).combine(O.shift(1), np.minimum) < c2)
                & bull & long_body & (C > mid2))
# evening star: mirror at the top
evening_star = (bull2 & long2 & small1
                & (C.shift(1).combine(O.shift(1), np.maximum) > c2)
                & bear & long_body & (C < mid2))

bull_candle_raw = (hammer | inv_hammer | dragonfly | bull_engulf
                   | piercing | morning_star) & downtrend
bear_candle_raw = ((hammer & uptrend)          # hanging man = hammer shape in uptrend
                   | (inv_hammer & uptrend)    # shooting star shape in uptrend
                   | gravestone & uptrend
                   | (bear_engulf | dark_cloud | evening_star) & uptrend)

# book: confirmation candle required (next day closes in the signal direction)
bull_candle = bull_candle_raw.shift(1).fillna(False) & bull
bear_candle = bear_candle_raw.shift(1).fillna(False) & bear

def cross_up(a, b):
    return (a > b) & (a.shift(1) <= b.shift(1))

def cross_dn(a, b):
    return (a < b) & (a.shift(1) >= b.shift(1))

# ---------------- strategy signal tables (True on signal DAY; fill next open)
strategies = {}

# 1. MACD crossover
strategies["MACD crossover"] = (cross_up(macd, macd_sig), cross_dn(macd, macd_sig))

# 2. MACD centreline (trend indicator)
strategies["MACD centreline"] = (cross_up(macd, macd * 0), cross_dn(macd, macd * 0))

# 3. Stochastic with the 20/80 discipline rule
sto_buy = cross_up(pd_, pds) & (pd_.shift(1) < 20)
sto_sell = cross_dn(pd_, pds) & (pd_.shift(1) > 80)
strategies["Stochastic 20/80"] = (sto_buy, sto_sell)

# 4. Bollinger band mean-reversion
strategies["Bollinger 20/2"] = (C < bb_lo, C > bb_up)

# 5. Candlestick reversals (confirmed, with prior trend)
strategies["Candle reversals"] = (bull_candle, bear_candle)

# 6. Combo: MACD positive range = trend filter, stochastic buy = timing
combo_buy = sto_buy & (macd > 0)
combo_sell = sto_sell | cross_dn(macd, macd * 0)
strategies["Combo MACD+Stoch"] = (combo_buy, combo_sell)

# ---------------- portfolio simulation ----------------
def run(buy_sig, sell_sig):
    cash = START_CASH
    pos = {}                      # sym -> {qty, entry}
    curve, dates = [], []
    trades = wins = 0
    n = len(C)
    for i in range(30, n):
        day = C.index[i]
        op, cl = O.iloc[i], C.iloc[i]
        # signals from YESTERDAY's completed bar -> act at TODAY's open
        b, s = buy_sig.iloc[i - 1], sell_sig.iloc[i - 1]
        # exits first
        for sym in list(pos):
            v = op[sym]
            if np.isnan(v):
                continue
            if s.get(sym, False):
                p = pos.pop(sym)
                cash += p["qty"] * v * (1 - COST_SIDE)
                trades += 1
                wins += 1 if v > p["entry"] else 0
        # entries
        eq = cash + sum(p["qty"] * cl[sym] for sym, p in pos.items()
                        if not np.isnan(cl[sym]))
        cands = [sym for sym in symbols
                 if b.get(sym, False) and sym not in pos and not np.isnan(op[sym])]
        for sym in cands:
            if len(pos) >= SLOTS:
                break
            notional = min(eq / SLOTS, cash)
            if notional < 1000:
                continue
            qty = notional / op[sym]
            cash -= qty * op[sym] * (1 + COST_SIDE)
            pos[sym] = {"qty": qty, "entry": op[sym]}
        dates.append(day)
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

print("\n=== EMPOWER ADVISORY RULES — VERBATIM BACKTEST (long/flat, "
      f"{SLOTS}-slot equal weight, next-open fills, {COST_SIDE*1e4:.0f}bps/side) ===")
results = {}
for name, (bs, ss) in strategies.items():
    c, tr, wn = run(bs.fillna(False), ss.fillna(False))
    cagr, sh, dd = stats(c)
    results[name] = c
    # house-protocol segment view: first 55% / next 25% / last 20%
    n = len(c)
    seg = [c.iloc[: int(n * .55)], c.iloc[int(n * .55): int(n * .80)], c.iloc[int(n * .80):]]
    segtxt = " | ".join(f"{s.iloc[-1] / s.iloc[0] - 1:+.1%}" for s in seg if len(s) > 1)
    print(f"\n  {name}")
    print(f"    CAGR {cagr:+.1%}  Sharpe {sh:.2f}  maxDD {dd:.1%}  "
          f"trades {tr}  win rate {wn / max(1, tr):.0%}")
    print(f"    segments (55/25/20): {segtxt}")

bench_ew = (C / C.iloc[0]).mean(axis=1).iloc[30:] * START_CASH
spy = yf.download("SPY", period="3y", interval="1d", auto_adjust=True,
                  progress=False)["Close"].squeeze().reindex(C.index).ffill().iloc[30:]
spy = spy / spy.iloc[0] * START_CASH
print("\n  --- benchmarks ---")
for name, c in (("equal-weight universe B&H", bench_ew), ("SPY B&H", spy)):
    cagr, sh, dd = stats(c)
    print(f"  {name}: CAGR {cagr:+.1%}  Sharpe {sh:.2f}  maxDD {dd:.1%}")
