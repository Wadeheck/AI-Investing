"""Test of the viral 'Claude Fable trading bot' thread (Bruno Souza screenshots).

Claimed system, reconstructed with standard definitions (thread gives none):
  SPY/QQQ 15m:  mean reversion — BB(20,2) on 15m; long < lower band, short >
                upper band, exit at mid-band; correlation filter: SPY and QQQ
                never simultaneously in the same direction.
  BTC 1h:       momentum breakout — close breaks prior 20-bar high/low with
                volume >= 1.5x 20-bar average; exit at opposite 10-bar extreme.
  GLD/USO 4h:   trend following — EMA20/EMA50 cross (resampled 1h -> 4h),
                long/short on fresh cross.
  All trades:   hard 1% stop, no exceptions. Vol sizing: risk 0.25% equity
                per trade -> 25% notional at 1% stop. Costs 2bps/side ETFs,
                10bps BTC. Fills on next bar's open after a signal.

Data windows (yfinance limits): 15m ~3 months; BTC 1h 2y; GLD/USO 1h ~3y.
"""
import math
import warnings

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf

START = 100_000.0
RISK = 0.0025           # risk per trade as fraction of equity
STOP = 0.01             # hard 1% stop
ANN = {"15m": 252 * 26, "1h": 24 * 365, "4h": 6 * 252}

def fetch(sym, iv, per):
    d = yf.download(sym, interval=iv, period=per, progress=False, auto_adjust=True)
    d = d.droplevel(1, axis=1) if isinstance(d.columns, pd.MultiIndex) else d
    return d.dropna()

def to_4h(d):
    o = d.resample("4h").agg({"Open": "first", "High": "max", "Low": "min",
                              "Close": "last", "Volume": "sum"}).dropna()
    return o

def simulate(bars, sig, cost, ann, allow=None):
    """sig: +1 open long, -1 open short, 0 flat/exit, np.nan hold current.
    Evaluated on completed bar i-1, filled at bar i open. 1% stop intraday."""
    cash, qty, entry, stop = START, 0.0, 0.0, 0.0
    curve, times = [], []
    trades = wins = 0
    for i in range(1, len(bars)):
        op, hi, lo, cl = bars["Open"].iloc[i], bars["High"].iloc[i], \
                         bars["Low"].iloc[i], bars["Close"].iloc[i]
        want = sig.iloc[i - 1]
        eq = cash + qty * op
        # stop check first (intraday, resting)
        if qty > 0 and lo <= stop:
            fill = min(op, stop)
            cash += qty * fill * (1 - cost)
            trades += 1; wins += fill > entry
            qty = 0.0
        elif qty < 0 and hi >= stop:
            fill = max(op, stop)
            cash += qty * fill * (1 + cost)
            trades += 1; wins += fill < entry
            qty = 0.0
        # signal exits / flips
        if not np.isnan(want):
            cur = np.sign(qty)
            if want != cur and qty != 0:
                cash += qty * op * (1 - cost * np.sign(qty))
                trades += 1; wins += (op > entry) if qty > 0 else (op < entry)
                qty = 0.0
            if want != 0 and qty == 0 and (allow is None or allow(i, want)):
                eq = cash
                notional = eq * (RISK / STOP)
                q = (notional / op) * want
                cash -= q * op * (1 + cost * want)
                qty, entry = q, op
                stop = op * (1 - STOP) if want > 0 else (op * (1 + STOP))
        curve.append(cash + qty * cl)
        times.append(bars.index[i])
    return pd.Series(curve, index=times), trades, wins

def stats(c, ann):
    r = c.pct_change().dropna()
    years = len(c) / ann
    cagr = (c.iloc[-1] / c.iloc[0]) ** (1 / max(years, 1e-9)) - 1
    sharpe = r.mean() / (r.std() + 1e-12) * math.sqrt(ann)
    dd = ((c / c.cummax()) - 1).min()
    return cagr, sharpe, dd, years

print("=== VIRAL BOT RECONSTRUCTION ===")

# ---- SPY/QQQ 15m mean reversion with correlation filter ----
spy = fetch("SPY", "15m", "60d")
qqq = fetch("QQQ", "15m", "60d")
state = {"SPY": 0, "QQQ": 0}

def mr_signal(d):
    mid = d["Close"].rolling(20).mean()
    sd = d["Close"].rolling(20).std()
    sig = pd.Series(np.nan, index=d.index)
    sig[d["Close"] < mid - 2 * sd] = 1.0
    sig[d["Close"] > mid + 2 * sd] = -1.0
    # exit at mean: crossing the mid-band -> flat
    up_thru = (d["Close"] >= mid) & (d["Close"].shift(1) < mid.shift(1))
    dn_thru = (d["Close"] <= mid) & (d["Close"].shift(1) > mid.shift(1))
    sig[up_thru | dn_thru] = sig[up_thru | dn_thru].where(
        sig[up_thru | dn_thru].notna(), 0.0)
    sig[(up_thru | dn_thru) & sig.isna()] = 0.0
    return sig

curves = {}
for name, d, other in (("SPY", spy, "QQQ"), ("QQQ", qqq, "SPY")):
    sig = mr_signal(d)
    def allow(i, want, _name=name, _other=other):
        if state[_other] == want:      # correlation filter
            return False
        state[_name] = want
        return True
    c, tr, wn = simulate(d, sig, 0.0002, ANN["15m"], allow)
    curves[name] = c
    cagr, sh, dd, yrs = stats(c, ANN["15m"])
    print(f"  {name} 15m mean-rev ({yrs*12:.1f} months): total "
          f"{c.iloc[-1]/START-1:+.1%}  (ann {cagr:+.1%})  Sharpe {sh:.2f}  "
          f"maxDD {dd:.1%}  trades {tr}  win {wn/max(1,tr):.0%}")

# ---- BTC 1h volume breakout ----
btc = fetch("BTC-USD", "1h", "730d")
hh = btc["High"].rolling(20).max().shift(1)
ll = btc["Low"].rolling(20).min().shift(1)
volf = btc["Volume"] >= 1.5 * btc["Volume"].rolling(20).mean()
sig = pd.Series(np.nan, index=btc.index)
sig[(btc["Close"] > hh) & volf] = 1.0
sig[(btc["Close"] < ll) & volf] = -1.0
ex_hi = btc["High"].rolling(10).max().shift(1)
ex_lo = btc["Low"].rolling(10).min().shift(1)
sig[(btc["Close"] < ex_lo)] = sig[(btc["Close"] < ex_lo)].fillna(0.0)
sig[(btc["Close"] > ex_hi) & sig.isna()] = np.nan  # longs exit handled below
# exits: long out on close < 10-bar low, short out on close > 10-bar high
exit_mask_long = btc["Close"] < ex_lo
exit_mask_short = btc["Close"] > ex_hi
sig[exit_mask_long & sig.isna()] = 0.0
sig[exit_mask_short & sig.isna()] = 0.0
c, tr, wn = simulate(btc, sig, 0.0010, ANN["1h"])
cagr, sh, dd, yrs = stats(c, ANN["1h"])
print(f"  BTC 1h breakout ({yrs:.1f}y): total {c.iloc[-1]/START-1:+.1%}  "
      f"(ann {cagr:+.1%})  Sharpe {sh:.2f}  maxDD {dd:.1%}  trades {tr}  "
      f"win {wn/max(1,tr):.0%}")
curves["BTC"] = c

# ---- GLD/USO 4h EMA trend following ----
for name in ("GLD", "USO"):
    d4 = to_4h(fetch(name, "1h", "730d"))
    f = d4["Close"].ewm(span=20, adjust=False).mean()
    s = d4["Close"].ewm(span=50, adjust=False).mean()
    sig = pd.Series(np.nan, index=d4.index)
    sig[(f > s) & (f.shift(1) <= s.shift(1))] = 1.0
    sig[(f < s) & (f.shift(1) >= s.shift(1))] = -1.0
    c, tr, wn = simulate(d4, sig, 0.0002, ANN["4h"])
    cagr, sh, dd, yrs = stats(c, ANN["4h"])
    print(f"  {name} 4h trend ({yrs:.1f}y): total {c.iloc[-1]/START-1:+.1%}  "
          f"(ann {cagr:+.1%})  Sharpe {sh:.2f}  maxDD {dd:.1%}  trades {tr}  "
          f"win {wn/max(1,tr):.0%}")
    curves[name] = c

# benchmarks over matching windows
print("\n  --- buy & hold over the same windows ---")
for name, d in (("SPY (3mo)", spy), ("QQQ (3mo)", qqq), ("BTC (2y)", btc)):
    print(f"  {name}: {d['Close'].iloc[-1]/d['Close'].iloc[0]-1:+.1%}")
for name in ("GLD", "USO"):
    d = fetch(name, "1h", "730d")
    print(f"  {name} (~3y): {d['Close'].iloc[-1]/d['Close'].iloc[0]-1:+.1%}")
