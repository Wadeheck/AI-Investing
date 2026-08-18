"""Regime persistence: how many consecutive days a node's activation has stayed
pinned near its saturation ceiling, sign held constant.

`macro_linkage` (signals/macro_linkage.py) reads the graph's CURRENT impact
level only -- a node that crossed 0.9 yesterday and one that has sat at 0.9 for
six weeks look identical to it, because both are just "near max". Once a
node's activation is itself clamped to [-1, 1] (field.py), the level has no
more room to say "this got worse" -- but duration still can. This module
answers the duration question from the real time series already kept in
brain.db (`BrainStore.node_trend`), so a fresh shock and a proven structural
regime can be told apart downstream (signals/regime_persistence.py).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

THRESHOLD = 0.85       # |activation| at/above this counts as "saturated"
LOOKBACK_DAYS = 60      # how far back to look for the streak


def persistence_days(store, node: str, current: float,
                      now: Optional[datetime] = None,
                      threshold: float = THRESHOLD,
                      lookback_days: int = LOOKBACK_DAYS) -> float:
    """Consecutive days (most recent first) `node` has held |activation| >=
    threshold with the SAME sign as `current`. 0.0 if `current` itself isn't
    saturated, or the streak is broken on the very first day looked at.

    One activation per calendar day: `node_trend` returns one row per cycle
    (many a day), so same-day rows are collapsed to the LAST value of that
    day before walking the streak backwards -- a mid-day dip below threshold
    that closed the day still-elevated shouldn't count as a broken streak.
    """
    if abs(current) < threshold:
        return 0.0
    rows = store.node_trend(node, days=lookback_days)
    if not rows:
        return 0.0
    sign = 1.0 if current > 0 else -1.0
    by_day: dict[str, float] = {}
    for ts, activation in rows:            # ORDER BY ts ascending: last write wins
        by_day[str(ts)[:10]] = float(activation)
    today = (now or datetime.now(timezone.utc)).date().isoformat()
    by_day.setdefault(today, current)      # today's cycle may predate its own history row
    streak = 0.0
    for day in sorted(by_day, reverse=True):
        a = by_day[day]
        if abs(a) >= threshold and (1.0 if a > 0 else -1.0) == sign:
            streak += 1.0
        else:
            break
    return streak
