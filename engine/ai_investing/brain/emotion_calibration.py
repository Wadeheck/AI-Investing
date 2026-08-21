"""Emotion calibration: measure whether panic and euphoria actually overshoot.

"Be greedy when others are fearful" is a hypothesis, not a law — so before the
contrarian composer sizes on it, measure it on THIS system's own history. The
event_outcomes table (brain/source_learning.py) freezes the realized ~5d return
of the assets each event touched. Group by the event's tagged emotion:

    panic/fear group   -> forward EXCESS return after fear events, MINUS the
                          same statistic for every other non-noise event.
                          Positive and significant = the crowd overshoots down
                          = rebound is real = positive contrarian coefficient.
    euphoria/greed group -> the same lift for greed events. Negative = chasing
                          costs money = fade coefficient.

TWO CORRECTIONS, 2026-08-21, after this module returned +1.19% for PANIC and
+1.12% for EUPHORIA — the same answer, within noise, for opposite emotions,
with both coefficients clamped to 1.0:

  1. MARKET-RELATIVE. It read `realized_ret`, an absolute move graded against
     zero, so in a tape with any drift it measured the drift. It now reads
     `excess_ret` (see brain/source_learning.py's `_migrate`), the same
     benchmark discipline brain/scorecard.py adopted on the advice side.
  2. A CONTROL GROUP. Each emotion is t-tested against EVERY OTHER non-noise
     event rather than against zero, with Welch's t for unequal variances. A
     contrarian claim is comparative — "panic overshoots MORE than an ordinary
     event" — so it needs an ordinary event to compare against.

Until n >= MIN_N per group (and in the control) the composer runs on modest
PRIORS (+0.30 buy-panic, -0.30 fade-euphoria — clearly labeled "prior"). Once
evidence accumulates, the measured coefficient replaces the prior:

    coef = clamp(tstat_of_the_lift / 3, -1, 1)

and a lift measured in the direction OPPOSITE the hypothesis yields 0.0
("measured-contradicted") rather than a backwards coefficient — the composer
stops sizing on the claim instead of sizing on its inverse.

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


def _welch(group: list[float], rest: list[float]) -> dict:
    """Group mean MINUS the baseline mean, with Welch's t for unequal variances.

    THE CONTROL GROUP. This used to t-test each emotion group against ZERO, and
    the answer was always "the sample's average forward return" — which is why
    on 2026-08-21 it reported +1.19% after PANIC and +1.12% after EUPHORIA, the
    same number for opposite emotions, and clamped both coefficients to 1.0.
    A contrarian claim is comparative ("panic overshoots MORE than an ordinary
    event"), so it needs the ordinary event to compare against.
    """
    g, r = _stats(group), _stats(rest)
    if not group or not rest or g["mean"] is None or r["mean"] is None:
        return {"n": g["n"], "baseline_n": r["n"], "mean": g["mean"],
                "baseline_mean": r["mean"], "lift": None, "tstat": None}
    lift = g["mean"] - r["mean"]
    def var(xs, m):
        return sum((x - m) ** 2 for x in xs) / max(1, len(xs) - 1)
    se = math.sqrt(var(group, g["mean"]) / len(group) + var(rest, r["mean"]) / len(rest))
    t = lift / se if se > 1e-12 else math.copysign(99.0, lift) if abs(lift) > 1e-9 else 0.0
    return {"n": g["n"], "baseline_n": r["n"], "mean": g["mean"],
            "baseline_mean": r["mean"], "lift": round(lift, 5),
            "tstat": round(max(-99.0, min(99.0, t)), 2)}


def calibrate(settings) -> dict:
    """Aggregate post-emotion forward EXCESS returns against a control group."""
    fear_rets: list[float] = []
    greed_rets: list[float] = []
    other_rets: list[float] = []
    basis_used = "absolute"
    try:
        conn = sqlite3.connect(settings.brain.db_path)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(event_outcomes)")}
        # Market-relative where the column exists (see source_learning._migrate);
        # a name that rose 2% in a tape that rose 6% did not react to the shock.
        if "excess_ret" in cols:
            basis_used = "excess"
            rows = conn.execute(
                "SELECT emotion, COALESCE(excess_ret, realized_ret), is_noise "
                "FROM event_outcomes WHERE symbol != '_NONE' "
                "  AND COALESCE(excess_ret, realized_ret) IS NOT NULL").fetchall()
        else:
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
        else:
            other_rets.append(ret)         # the control group: ordinary events

    # Each emotion is compared against EVERY OTHER non-noise event, so the
    # coefficient measures the emotion, not the window's drift.
    fear = _welch(fear_rets, greed_rets + other_rets)
    greed = _welch(greed_rets, fear_rets + other_rets)

    def _coef(stat, key):
        """A coefficient only where the lift is BOTH large enough to have been
        measured and in the direction the hypothesis predicts. A contradicted
        sign collapses the coefficient to 0 — the composer stops sizing on it
        rather than sizing on it backwards."""
        if stat["n"] < MIN_N or stat["baseline_n"] < MIN_N or stat["tstat"] is None:
            return PRIORS[key], "prior"
        want = 1.0 if key == "panic_rebound" else -1.0
        c = max(-1.0, min(1.0, stat["tstat"] / 3.0))
        if c * want <= 0:                  # measured the opposite of the claim
            return 0.0, "measured-contradicted"
        return round(c, 3), "measured"

    coef_panic, panic_basis = _coef(fear, "panic_rebound")
    coef_euph, euph_basis = _coef(greed, "euphoria_fade")

    report = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "return_basis": basis_used,        # 'excess' once event_outcomes is migrated
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
