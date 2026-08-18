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

`driver_persistence_days()` extends this upstream (2026-08-18, widened to 2 hops
the same day): an asset's OWN landed activation is, by the graph's own design, a
damped and faster-decaying echo of whatever factor/theme is driving it (assets
decay at a 24h half-life vs. 96h for factors, and every edge hop costs weight --
see graph.py's propagate() docstring). So an asset can sit well below the
saturation threshold for weeks while the thing actually causing that -- a
factor node like bond_stress or us_gov_debt -- has been pinned at its ceiling
the entire time. Reading only the asset's own streak misses that; reading only
its DIRECT predecessors still misses it when the real cause is one hop further
back (checked against live data 2026-08-18: TLT's strongest direct predecessor
is us_10y_yield, weight 0.9 -- but bond_stress/us_gov_debt, the multi-week
story, sit a second hop behind that). This walks up to `max_hops` upstream,
through non-asset nodes only, and lets a sufficiently strong, sufficiently
persistent origin lend the node some of its persistence -- weight compounding
per hop, with `decay` (the SAME per-hop decay constant `graph.propagate()`
already uses for the real ripple) applied beyond the first hop, so a 2-hop
borrow is honestly discounted for the extra inference, not treated as equally
certain as a direct edge.
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


DEFAULT_HOP_DECAY = 0.6   # matches settings.brain.decay / graph.propagate()'s default


def _upstream_origins(graph, node_id: str, max_hops: int = 2,
                      hop_decay: float = DEFAULT_HOP_DECAY, top_k: int = 6) -> dict[str, float]:
    """Non-asset nodes reachable from `node_id` within `max_hops`, walking
    BACKWARDS along the graph (i.e. nodes that could have caused a shock at
    `node_id`), mapped to a combined path weight.

    A visited set bounds this to a simple BFS over a small, finite frontier
    (at most `top_k` branches per hop) -- no risk of the graph's cycles
    (correlates_with is bidirectional) causing unbounded recursion. Traversal
    only continues THROUGH non-asset nodes: an asset can be a leaf origin's
    victim, never a hop the search passes through on its way to one, which
    keeps this a look-through to CAUSES, not a two-asset feedback loop.
    """
    best: dict[str, float] = {}
    seen = {node_id}
    frontier = [(node_id, 1.0, 0)]
    while frontier:
        cur, path_w, hops = frontier.pop(0)
        if hops >= max_hops:
            continue
        for src, w in graph.predecessors(cur, k=top_k):
            if src in seen:
                continue
            seen.add(src)
            n = graph.nodes.get(src)
            if not n:
                continue
            new_w = path_w * w * (1.0 if hops == 0 else hop_decay)
            if n.type != "asset":
                best[src] = max(best.get(src, 0.0), new_w)
                frontier.append((src, new_w, hops + 1))
    return best


def driver_persistence_days(graph, store, activations: dict[str, float], node: str,
                             now: Optional[datetime] = None,
                             threshold: float = THRESHOLD,
                             lookback_days: int = LOOKBACK_DAYS,
                             max_hops: int = 2,
                             hop_decay: float = DEFAULT_HOP_DECAY,
                             top_k: int = 6) -> float:
    """`persistence_days` for `node` itself, OR-ed with a scaled-down read
    borrowed from its strongest upstream factor/theme drivers (up to
    `max_hops` away), whichever is larger.

    Deliberately additive, never a replacement: a node whose own activation
    IS the sustained story (a single-name grind lower under its own steam)
    keeps full, unscaled credit. A driver's streak is scaled by its combined
    path weight to `node` (edge weights compounded, extra hops discounted by
    `hop_decay`) -- capped at 1.0 -- so a weakly-linked or many-hops-away
    origin can't hand a node full credit for a regime it barely touches.
    Asset-type nodes are excluded from the walk entirely: this is a
    look-through to ORIGIN causes (factor/theme/sector/commodity/actor), not
    a way for assets to inflate each other's streaks.

    Degrades to plain `persistence_days` (returns `own`) if graph traversal
    raises for any reason -- this is an enrichment, never load-bearing.
    """
    current = activations.get(node, 0.0)
    best = persistence_days(store, node, current, now, threshold, lookback_days)
    try:
        origins = _upstream_origins(graph, node, max_hops=max_hops,
                                    hop_decay=hop_decay, top_k=top_k)
        for src, w in origins.items():
            src_days = persistence_days(store, src, activations.get(src, 0.0),
                                        now, threshold, lookback_days)
            best = max(best, src_days * min(1.0, w))
    except Exception:
        pass
    return best
