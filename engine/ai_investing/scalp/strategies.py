"""Four scalp strategy families from the six-doc synthesis (docs/SCALP_MODEL.md).

Each returns an order INTENT: dict(side=+1/-1, entry, stop, target, tag, ttl)
or None. Entries are resting LIMITS (maker). Stops are structural but floored
at MIN_STOP_FRAC — the fee-survival rule every digest converged on.

All lookups are causal: a signal computed at bar i uses bars < i and may fill
from bar i onward.
"""
from __future__ import annotations

from . import indicators as ind

MIN_STOP_FRAC = 0.0045     # 45 bps = 5x worst-case round-trip cost
RR_TARGET = 2.0            # Gala: 2R default target
TTL_BARS = 6               # unfilled limit dies after 30m
SECOND_DRIVE_BARS = 48     # Fabio: never the first test — look for a prior touch


def _floor_stop(entry: float, stop: float, side: int) -> float:
    dist = abs(entry - stop)
    mind = entry * MIN_STOP_FRAC
    if dist < mind:
        stop = entry - side * mind
    return stop


_SOFT: dict = {}     # research sweeps patch soft thresholds here


def _had_prior_touch(df, i, price, atr, bars=None) -> bool:
    a = max(0, i - (bars or SECOND_DRIVE_BARS))
    seg = df.iloc[a:i - 1]
    if not len(seg):
        return False
    return bool(((seg["low"] <= price + 0.3 * atr)
                 & (seg["high"] >= price - 0.3 * atr)).any())


def sweep_reversion(df, df1, i, levels, va) -> dict | None:
    """S1 (Marco+Gala): 1m wick sweeps a confirmed 5m support, 5m body closes
    back above it -> resting limit AT the level. Mean-reversion family: only
    inside the value area (Fabio's balance gate). Long-only form."""
    if not va["in_value"]:
        return None
    bar = df.iloc[i - 1]
    atr = float(bar["atr"])
    if atr != atr or atr <= 0:
        return None
    for lv in levels:
        if lv["kind"] != "sup":
            continue
        p = lv["price"]
        pierced = bar["low"] < p and bar["low"] > p - 0.6 * atr
        reclaimed = min(bar["open"], bar["close"]) > p
        if pierced and reclaimed and _had_prior_touch(df, i, p, atr):
            if ind.cvd_divergence(df, i) == "bear" or ind.absorption(df, i) == "buyers":
                return None
            entry = p
            stop = _floor_stop(entry, bar["low"] - 0.1 * atr, +1)
            return {"side": 1, "entry": entry, "stop": stop,
                    "target": entry + RR_TARGET * (entry - stop),
                    "tag": "S1_sweep", "ttl": TTL_BARS}
    return None


def break_retest(df, df1, i, levels, va) -> dict | None:
    """S2 (Gala): 5m body close through a confirmed resistance, then a retest
    bar whose body holds above it -> continuation long. Trend family: only
    OUTSIDE the value area (imbalance). Requires volume expansion (Ted's
    asymmetry: breakouts must bring volume)."""
    if va["in_value"] or i < 3:
        return None
    brk, rt = df.iloc[i - 2], df.iloc[i - 1]
    atr = float(rt["atr"])
    if atr != atr or atr <= 0:
        return None
    for lv in levels:
        if lv["kind"] != "res":
            continue
        p = lv["price"]
        broke = min(brk["open"], brk["close"]) > p and brk["rvol"] > 1.3
        retested = rt["low"] <= p + 0.3 * atr and min(rt["open"], rt["close"]) > p
        if broke and retested:
            if ind.absorption(df, i) == "buyers":
                return None
            entry = p + 0.05 * atr
            stop = _floor_stop(entry, min(rt["low"], brk["low"]) - 0.1 * atr, +1)
            return {"side": 1, "entry": entry, "stop": stop,
                    "target": entry + RR_TARGET * (entry - stop),
                    "tag": "S2_retest", "ttl": TTL_BARS}
    return None


def exhaustion_fade(df, df1h, i, va) -> dict | None:
    """S3 (Dux): >=3 escalating dollar-volume green 1h bars + stretched 24h
    return, first 5m close back below EMA9 -> fade toward VWAP. The
    reset-on-red rule is structural: any red hour resets the count, so
    healthy grind-ups are never faded. Short intent (paper only)."""
    bar = df.iloc[i - 1]
    atr = float(bar["atr"])
    if atr != atr or atr <= 0 or len(df1h) < 30:
        return None
    run, esc = ind.green_run(df1h)
    r24 = float(df["close"].iloc[i - 1] / df["close"].iloc[max(0, i - 288)] - 1.0)
    min_run = int(_SOFT.get("_run", 3))
    min_r24 = float(_SOFT.get("_r24", 0.06))
    if run >= min_run and esc and r24 > min_r24 and bar["close"] < bar["ema9"]:
        if _SOFT.get("_cvd", 1) and ind.cvd_divergence(df, i) != "bear":
            return None
        entry = float(bar["close"]) + 0.1 * atr
        stop = _floor_stop(entry, float(df["high"].iloc[i - 6:i].max()) + 0.1 * atr, -1)
        tgt = max(float(bar["vwap24"]), entry - RR_TARGET * (stop - entry))
        return {"side": -1, "entry": entry, "stop": stop, "target": tgt,
                "tag": "S3_exhaust", "ttl": TTL_BARS}
    return None


def momentum_continuation(df, btc5, i, va) -> dict | None:
    """S4 (Jeff): higher-low then consolidation-range break with volume,
    gated by BTC alignment (market-wide move precondition). Exit handled by
    the engine's EMA9 close-below trail, so target is far (5R cap)."""
    if va["in_value"] or i < 16:
        return None
    seg = df.iloc[i - 13:i - 1]
    bar = df.iloc[i - 1]
    atr = float(bar["atr"])
    if atr != atr or atr <= 0:
        return None
    box_hi, box_lo = float(seg["high"].max()), float(seg["low"].min())
    tight = (box_hi - box_lo) < float(_SOFT.get("_box", 2.0)) * atr
    lows = df["low"].iloc[i - 40:i - 12]
    higher_low = len(lows) and box_lo > float(lows.min())
    broke = bar["close"] > box_hi and bar["rvol"] > float(_SOFT.get("_rvol", 1.5))
    aligned = ind.btc_aligned(btc5, i, +1) if _SOFT.get("_btc", 1) else True
    if tight and higher_low and broke and aligned:
        if ind.absorption(df, i) == "buyers":
            return None
        entry = box_hi + 0.05 * atr
        stop = _floor_stop(entry, box_lo - 0.1 * atr, +1)
        return {"side": 1, "entry": entry, "stop": stop,
                "target": entry + 5.0 * (entry - stop),
                "tag": "S4_momo", "ttl": TTL_BARS, "trail_ema9": True}
    return None


FAMILIES = ("S1_sweep", "S2_retest", "S3_exhaust", "S4_momo")


def generate(df, df1, df1h, btc5, i, levels, va, enabled=FAMILIES) -> list[dict]:
    out = []
    if "S1_sweep" in enabled:
        s = sweep_reversion(df, df1, i, levels, va)
        if s: out.append(s)
    if "S2_retest" in enabled:
        s = break_retest(df, df1, i, levels, va)
        if s: out.append(s)
    if "S3_exhaust" in enabled:
        s = exhaustion_fade(df, df1h, i, va)
        if s: out.append(s)
    if "S4_momo" in enabled:
        s = momentum_continuation(df, btc5, i, va)
        if s: out.append(s)
    return out
