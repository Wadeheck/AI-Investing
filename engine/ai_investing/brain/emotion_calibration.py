"""Emotion calibration: measure whether panic and euphoria actually overshoot.

"Be greedy when others are fearful" is a hypothesis, not a law — so before the
contrarian composer sizes on it, measure it on THIS system's own history. The
event_outcomes table (brain/source_learning.py) freezes the realized ~5d return
of the assets each event touched. Group by the event's tagged emotion:

    panic/fear group   -> mean forward return AFTER fear events. Positive and
                          significant = the crowd overshoots down = rebound is
                          real = positive contrarian coefficient.
    euphoria/greed group -> mean forward return AFTER greed events. Negative =
                          chasing costs money = fade coefficient.

Until n >= MIN_N per group the composer runs on modest PRIORS (+0.30 buy-panic,
-0.30 fade-euphoria — history's base rates, clearly labeled "prior"). Once
evidence accumulates, the measured coefficient replaces the prior:

    coef = clamp(tstat / 3, -1, 1) x sign-appropriateness

Written to data/emotion_calibration.json alongside the raw stats, so the
dashboard can show WHY the brain believes fear is (or is not) a buy signal.
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
from datetime import datetime, timezone

MIN_N = 20
PRIORS = {"panic_rebound": 0.30, "euphoria_fade": -0.30}
FEAR_EMOTIONS = ("fear", "panic")
GREED_EMOTIONS = ("greed", "euphoria")


def _path(settings) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(settings.brain.db_path)),
                        "emotion_calibration.json")


def _stats(rets: list[float]) -> dict:
    n = len(rets)
    if n == 0:
        return {"n": 0, "mean": None, "tstat": None}
    mean = sum(rets) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in rets) / max(1, n - 1))
    if sd > 1e-12 and n > 1:
        t = mean / (sd / math.sqrt(n))
    else:
        t = math.copysign(99.0, mean) if abs(mean) > 1e-9 else 0.0
    return {"n": n, "mean": round(mean, 5), "tstat": round(max(-99.0, min(99.0, t)), 2)}


def calibrate(settings) -> dict:
    """Aggregate post-emotion forward returns from event_outcomes; persist."""
    fear_rets: list[float] = []
    greed_rets: list[float] = []
    try:
        conn = sqlite3.connect(settings.brain.db_path)
        rows = conn.execute(
            "SELECT emotion, realized_ret, is_noise FROM event_outcomes "
            "WHERE symbol != '_NONE' AND realized_ret IS NOT NULL").fetchall()
        conn.close()
    except sqlite3.Error:
        rows = []
    for emotion, ret, is_noise in rows:
        if is_noise:
            continue                       # manufactured emotion doesn't count
        if emotion in FEAR_EMOTIONS:
            fear_rets.append(ret)
        elif emotion in GREED_EMOTIONS:
            greed_rets.append(ret)
    fear, greed = _stats(fear_rets), _stats(greed_rets)

    # panic rebound: positive mean AFTER fear events = overshoot = buy signal
    if fear["n"] >= MIN_N:
        coef_panic = round(max(-1.0, min(1.0, fear["tstat"] / 3.0)), 3)
        panic_basis = "measured"
    else:
        coef_panic, panic_basis = PRIORS["panic_rebound"], "prior"
    # euphoria fade: negative mean AFTER greed events = chasing costs = fade
    if greed["n"] >= MIN_N:
        coef_euph = round(max(-1.0, min(1.0, greed["tstat"] / 3.0)), 3)
        euph_basis = "measured"
    else:
        coef_euph, euph_basis = PRIORS["euphoria_fade"], "prior"

    report = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "panic_rebound": {"coef": coef_panic, "basis": panic_basis, **fear},
        "euphoria_fade": {"coef": coef_euph, "basis": euph_basis, **greed},
    }
    try:
        with open(_path(settings), "w") as fh:
            json.dump(report, fh, indent=1)
    except OSError:
        pass
    return report


def coefficients(settings) -> dict[str, float]:
    """{panic_rebound, euphoria_fade} for the composer — priors until measured."""
    try:
        with open(_path(settings)) as fh:
            r = json.load(fh)
        return {"panic_rebound": float(r["panic_rebound"]["coef"]),
                "euphoria_fade": float(r["euphoria_fade"]["coef"])}
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return dict(PRIORS)
