"""Scalp indicators — everything computable from free Binance 1m klines
(ts, o, h, l, c, vol, taker_buy_vol, n_trades). See docs/research/SCALP_MODEL.md.

delta = taker_buy - taker_sell = 2*taker_buy - vol  (order-flow proxy: who
crossed the spread). CVD is its running sum. These are the free stand-ins
for the paid footprint/tape reads the source docs use.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

PIVOT_K = 3          # fractal order on 5m bars
LEVEL_EPS_ATR = 0.25  # two pivots within this ATR fraction = confirmed level
VA_BARS = 288         # value-area window: 24h of 5m bars
VA_PCT = 0.70


def load_1m(path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.index = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df.drop(columns=["ts"]).astype(float)


def resample(df1: pd.DataFrame, rule: str) -> pd.DataFrame:
    o = df1.resample(rule)
    out = pd.DataFrame({"open": o["open"].first(), "high": o["high"].max(),
                        "low": o["low"].min(), "close": o["close"].last(),
                        "vol": o["vol"].sum(),
                        "taker_buy_vol": o["taker_buy_vol"].sum(),
                        "n_trades": o["n_trades"].sum()})
    return out.dropna(subset=["close"])


def enrich(df: pd.DataFrame) -> pd.DataFrame:
    """Add the indicator columns strategies read. df = 5m bars."""
    out = df.copy()
    c, h, l, v = out["close"], out["high"], out["low"], out["vol"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    out["atr"] = tr.rolling(20, min_periods=10).mean()
    out["ema9"] = c.ewm(span=9, adjust=False).mean()
    out["rvol"] = v / (v.rolling(100, min_periods=30).mean() + 1e-12)
    out["delta"] = 2.0 * out["taker_buy_vol"] - v
    out["cvd"] = out["delta"].cumsum()
    dz = out["delta"] / (out["delta"].rolling(100, min_periods=30).std() + 1e-12)
    out["delta_z"] = dz
    out["ret"] = c.pct_change()
    # rolling 24h anchored VWAP (crypto has no session open — rolling anchor)
    pv = (c * v).rolling(VA_BARS, min_periods=30).sum()
    out["vwap24"] = pv / (v.rolling(VA_BARS, min_periods=30).sum() + 1e-12)
    # dollar volume + green-run escalation counter (Dux, on 5m->1h upsample later)
    out["dvol"] = c * v
    # pivots (confirmed only k bars later — shift so no lookahead)
    ph = (h == h.rolling(2 * PIVOT_K + 1, center=True).max())
    pl_ = (l == l.rolling(2 * PIVOT_K + 1, center=True).min())
    out["pivot_hi"] = ph.shift(PIVOT_K).fillna(False).infer_objects(copy=False)
    out["pivot_lo"] = pl_.shift(PIVOT_K).fillna(False).infer_objects(copy=False)
    return out


def confirmed_levels(df: pd.DataFrame, i: int, lookback: int = 288,
                     max_levels: int = 6) -> list[dict]:
    """Marco/Gala: a level counts only when TWO pivots agree within
    LEVEL_EPS_ATR·ATR. Level price = close of the bar after the later pivot
    (body, not wick). Uses bars [i-lookback, i) only — causal."""
    a, b = max(0, i - lookback), i
    atr = float(df["atr"].iloc[i]) if df["atr"].iloc[i] == df["atr"].iloc[i] else 0.0
    if atr <= 0:
        return []
    eps = LEVEL_EPS_ATR * atr
    out = []
    for kind, col, price_col in (("res", "pivot_hi", "high"), ("sup", "pivot_lo", "low")):
        idx = [j for j in range(a, b) if df[col].iloc[j]]
        pxs = [float(df[price_col].iloc[j - PIVOT_K]) for j in idx]  # pivot bar itself
        for x in range(len(idx) - 1, 0, -1):
            for y in range(x - 1, -1, -1):
                if abs(pxs[x] - pxs[y]) <= eps:
                    j = idx[x]                       # later pivot's following bar
                    lvl = float(df["close"].iloc[min(j - PIVOT_K + 1, b - 1)])
                    out.append({"kind": kind, "price": lvl, "bar": j,
                                "touches": 2})
                    break
            if len([o for o in out if o["kind"] == kind]) >= max_levels // 2:
                break
    return out


def value_area(df: pd.DataFrame, i: int) -> dict:
    """Volume profile over the trailing 24h: POC + 70% value area."""
    a = max(0, i - VA_BARS)
    seg = df.iloc[a:i]
    if len(seg) < 30:
        return {"poc": float("nan"), "va_lo": float("nan"), "va_hi": float("nan"),
                "in_value": True}
    prices, vols = seg["close"].values, seg["vol"].values
    bins = np.linspace(prices.min(), prices.max(), 40)
    which = np.clip(np.digitize(prices, bins) - 1, 0, 38)
    hist = np.bincount(which, weights=vols, minlength=39)
    poc_bin = int(hist.argmax())
    order = np.argsort(hist)[::-1]
    need, got, chosen = hist.sum() * VA_PCT, 0.0, []
    for bidx in order:
        chosen.append(bidx); got += hist[bidx]
        if got >= need:
            break
    lo, hi = bins[min(chosen)], bins[min(max(chosen) + 1, 38)]
    px = float(df["close"].iloc[i - 1])
    return {"poc": float((bins[poc_bin] + bins[min(poc_bin + 1, 38)]) / 2),
            "va_lo": float(lo), "va_hi": float(hi),
            "in_value": bool(lo <= px <= hi)}


def cvd_divergence(df: pd.DataFrame, i: int, look: int = 20) -> str:
    """'bear' if price made a new high but CVD didn't (and mirror). Veto tool."""
    a = max(0, i - look)
    seg = df.iloc[a:i]
    if len(seg) < look // 2:
        return ""
    px, cvd = seg["close"], seg["cvd"]
    if px.iloc[-1] >= px.max() - 1e-12 and cvd.iloc[-1] < cvd.max() - 1e-12:
        return "bear"
    if px.iloc[-1] <= px.min() + 1e-12 and cvd.iloc[-1] > cvd.min() + 1e-12:
        return "bull"
    return ""


def absorption(df: pd.DataFrame, i: int) -> str:
    """Fabio: big aggressive delta with no price follow-through = the passive
    side is stronger. Returns the side being absorbed ('buyers'/'sellers')."""
    if i < 1:
        return ""
    dz = float(df["delta_z"].iloc[i - 1])
    atr = float(df["atr"].iloc[i - 1])
    ret = float(df["close"].iloc[i - 1] - df["open"].iloc[i - 1])
    if atr != atr or atr <= 0 or dz != dz:
        return ""
    if dz > 2.0 and ret < 0.2 * atr:
        return "buyers"      # heavy buying, no lift -> absorbed by sellers
    if dz < -2.0 and ret > -0.2 * atr:
        return "sellers"
    return ""


def green_run(df1h: pd.DataFrame) -> tuple[int, bool]:
    """Dux: consecutive green 1h bars with escalating DOLLAR volume; any red
    bar resets. Returns (run_length, escalating)."""
    n, esc = 0, True
    for j in range(len(df1h) - 1, -1, -1):
        row = df1h.iloc[j]
        if row["close"] <= row["open"]:
            break
        n += 1
        if n > 1 and row["dvol"] > df1h.iloc[j + 1]["dvol"]:
            esc = False
        if n >= 12:
            break
    return n, esc


def btc_aligned(btc5: pd.DataFrame, i: int, side: int) -> bool:
    """Jeff's market-wide-move precondition, crypto analogue: BTC's 15m return
    agrees with the trade direction and is moving (>0.15%)."""
    if i < 3:
        return False
    r = float(btc5["close"].iloc[i - 1] / btc5["close"].iloc[i - 4] - 1.0)
    return r * side > 0.0015
