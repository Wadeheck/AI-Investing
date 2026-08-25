"""Isolated research foundations for the next NN shadow lane.

Nothing in this module loads, changes, or saves the live decision formula. It
captures point-in-time inputs for future training and provides date-safe helpers
for research jobs which must not use the legacy length-based alignment.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Iterable


V2_DIR = "nn_v2"
SNAPSHOTS = "feature_snapshots.jsonl"


def _json_safe(value):
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


class PointInTimeFeatureStore:
    """Append-only, timestamped inputs available to the NN at decision time."""

    def __init__(self, state_path: str):
        self.dir = os.path.join(os.path.dirname(os.path.abspath(state_path)), V2_DIR)
        self.path = os.path.join(self.dir, SNAPSHOTS)

    def capture(self, *, context: dict, bars_by_key: dict, assets: Iterable,
                prices: dict, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        os.makedirs(self.dir, exist_ok=True)
        rows = []
        for asset in assets:
            bars = bars_by_key.get(asset.key) or []
            if not bars or asset.key not in prices:
                continue
            rows.append({
                "ts": now.isoformat(), "symbol": asset.symbol,
                "asset_class": asset.asset_class.value, "key": asset.key,
                "price": prices[asset.key], "bar_ts": bars[-1].ts.isoformat(),
                "sentiment": (context.get("sentiment_scores") or {}).get(asset.symbol),
                "hype": (context.get("hype_flags") or {}).get(asset.symbol),
                "brain_impact": ((context.get("brain") or {}).get("asset_impacts") or {}).get(asset.symbol),
                "brain_regime": (context.get("brain") or {}).get("regime"),
            })
        with open(self.path, "a") as handle:
            for row in rows:
                handle.write(json.dumps(_json_safe(row), separators=(",", ":")) + "\n")


def align_on_common_dates(bars_by_key: dict) -> tuple[dict, list]:
    """Return bars joined on actual timestamps, never on list position."""
    indexed = {key: {bar.ts.date(): bar for bar in bars}
               for key, bars in bars_by_key.items() if bars}
    if not indexed:
        return {}, []
    dates = sorted(set.intersection(*(set(rows) for rows in indexed.values())))
    return {key: [rows[day] for day in dates] for key, rows in indexed.items()}, dates


def purged_walk_forward_splits(dates: list, horizon: int, folds: int = 3):
    """Pre-register expanding train/validation folds plus an untouched final test.

    The embargo removes labels whose forward horizon touches validation.  The
    final block is never returned as validation and is reserved for one-time
    model assessment after all model choices are frozen.
    """
    if horizon < 1 or folds < 1:
        raise ValueError("horizon and folds must be positive")
    final_size = max(horizon + 10, len(dates) // (folds + 2))
    research_end = len(dates) - final_size
    fold_size = max(horizon + 10, research_end // (folds + 1))
    splits = []
    for fold in range(folds):
        train_end = fold_size * (fold + 1)
        validation_start = train_end + horizon
        validation_end = min(research_end, train_end + fold_size)
        if validation_start >= validation_end:
            break
        splits.append((range(0, train_end), range(validation_start, validation_end)))
    return splits, range(research_end, len(dates))
