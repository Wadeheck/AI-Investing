"""Versioned, point-in-time outcome ledgers for model improvement.

The live decision journals remain the source of truth. This module only adds
settled labels; it never changes a model, the live book, or the linear learner.
Version 2 makes the prediction contract explicit so settlement cannot silently
grade whichever nested model key happens to sort first.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import datetime, timedelta, timezone


SCHEMA_VERSION = 2


def artifact_model_id(path: str, model_type: str) -> str:
    """Return an immutable id for the exact artifact used for inference."""
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return f"{model_type}:missing"
    return f"{model_type}:{digest.hexdigest()[:20]}"


class OutcomeLedger:
    def __init__(self, root: str, lane: str, horizon_days: int = 5):
        self.root = root
        self.lane = lane
        self.horizon_days = horizon_days
        os.makedirs(root, exist_ok=True)
        self.path = os.path.join(root, "outcomes.jsonl")
        self.incomplete_path = os.path.join(root, "incomplete_outcomes.jsonl")

    def _done(self) -> set[tuple[str, str]]:
        out = set()
        try:
            with open(self.path, errors="replace") as fh:
                for line in fh:
                    try:
                        row = json.loads(line)
                        if int(row.get("schema_version", 0)) < SCHEMA_VERSION:
                            continue
                        out.add((row.get("model_id"), row.get("prediction_id")))
                    except (json.JSONDecodeError, TypeError, ValueError):
                        continue
        except OSError:
            pass
        return out

    def append_decisions(self, path: str, rows: list[dict]) -> None:
        """Append decisions after validating the versioned prediction contract."""
        if not rows:
            return
        seen = set()
        try:
            with open(path, errors="replace") as fh:
                for line in fh:
                    try:
                        old = json.loads(line)
                        seen.add((old.get("model_id"), old.get("prediction_id")))
                    except (json.JSONDecodeError, TypeError):
                        continue
        except OSError:
            pass
        with open(path, "a") as fh:
            for row in rows:
                model_id = row.get("model_id")
                prediction_id = row.get("prediction_id")
                prediction = row.get("prediction")
                if not model_id or not prediction_id or not isinstance(prediction, dict):
                    raise ValueError(
                        "outcome decision requires model_id, prediction_id, and prediction")
                key = (model_id, prediction_id)
                if key in seen:
                    continue
                payload = dict(row)
                payload["schema_version"] = SCHEMA_VERSION
                payload.setdefault("feature_schema", sorted(
                    (payload.get("features") or {}).keys()))
                payload.setdefault("decision_ts", payload.get("ts"))
                payload.setdefault(
                    "scheduled_exit_ts",
                    self._scheduled_exit(payload.get("decision_ts"), self.horizon_days))
                fh.write(json.dumps(payload, allow_nan=False) + "\n")
                seen.add(key)

    @staticmethod
    def _scheduled_exit(ts, horizon_days: int) -> str | None:
        try:
            value = datetime.fromisoformat(str(ts))
        except (TypeError, ValueError):
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return (value + timedelta(days=horizon_days)).isoformat()

    @staticmethod
    def _finite(x):
        try:
            x = float(x)
            return x if math.isfinite(x) else None
        except (TypeError, ValueError):
            return None

    def _record_incomplete(self, row: dict, reason: str) -> None:
        try:
            with open(self.incomplete_path, "a") as fh:
                fh.write(json.dumps({"schema_version": SCHEMA_VERSION,
                                     "lane": self.lane,
                                     "prediction_id": row.get("prediction_id"),
                                     "symbol": row.get("symbol"),
                                     "reason": reason,
                                     "recorded_at": datetime.now(timezone.utc).isoformat()},
                                    allow_nan=False) + "\n")
        except OSError:
            pass

    def settle(self, journal_path: str, prices: dict[str, float], assets: list,
               now: datetime | None = None) -> int:
        """Settle due versioned predictions once; preserve legacy rows untouched."""
        now = now or datetime.now(timezone.utc)
        done = self._done(); rows = []
        try:
            with open(journal_path, errors="replace") as fh:
                source = [json.loads(line) for line in fh if line.strip()]
        except (OSError, json.JSONDecodeError):
            return 0

        peer_returns = {}
        for candidate in source:
            if int(candidate.get("schema_version", 0)) < SCHEMA_VERSION or not candidate.get("is_primary"):
                continue
            px0 = self._finite(candidate.get("price"))
            px1 = self._finite(prices.get(candidate.get("asset_key")))
            if px0 and px1 and px0 > 0:
                peer_returns.setdefault(candidate.get("day"), []).append(px1 / px0 - 1.0)

        for row in source:
            if int(row.get("schema_version", 0)) < SCHEMA_VERSION or not row.get("is_primary"):
                continue
            model_id = row.get("model_id")
            prediction_id = row.get("prediction_id")
            key = (model_id, prediction_id)
            if key in done:
                continue
            if not model_id or not prediction_id or not isinstance(row.get("prediction"), dict):
                raise ValueError("versioned outcome row is missing its explicit prediction payload")
            try:
                due = datetime.fromisoformat(str(row.get("scheduled_exit_ts")))
                if due.tzinfo is None:
                    due = due.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                due = None
            if due and now < due:
                continue
            asset_key = row.get("asset_key")
            entry = self._finite(row.get("price"))
            exit_px = self._finite(prices.get(asset_key))
            if not asset_key or entry is None or exit_px is None or entry <= 0:
                self._record_incomplete(row, "missing_entry_or_exit_price")
                continue

            prediction = row["prediction"]
            realized = exit_px / entry - 1.0
            expected = self._finite(prediction.get("expected_return"))
            weight = self._finite(prediction.get("target_weight")) or 0.0
            direction = prediction.get("direction")
            benchmark_return = None
            bench_key = row.get("benchmark_key")
            bench_entry = self._finite(row.get("benchmark_price"))
            bench_exit = self._finite(prices.get(bench_key)) if bench_key else None
            if bench_entry and bench_exit and bench_entry > 0:
                benchmark_return = bench_exit / bench_entry - 1.0
            if benchmark_return is None and peer_returns.get(row.get("day")):
                values = sorted(peer_returns[row["day"]])
                benchmark_return = values[len(values) // 2]
            excess = realized - benchmark_return if benchmark_return is not None else realized
            hit = None if direction in (None, "FLAT") else (
                excess > 0 if direction == "LONG" else excess < 0)
            rows.append({
                "schema_version": SCHEMA_VERSION,
                "lane": self.lane,
                "model_id": model_id,
                "prediction_id": prediction_id,
                "symbol": row.get("symbol"),
                "day": row.get("day"),
                "decision_ts": row.get("decision_ts") or row.get("ts"),
                "feature_cutoff_ts": row.get("feature_cutoff_ts") or row.get("decision_ts"),
                "scheduled_exit_ts": row.get("scheduled_exit_ts"),
                "exit_price_ts": now.isoformat(),
                "settled_ts": now.isoformat(),
                "entry_price": entry,
                "exit_price": exit_px,
                "realized_return": realized,
                "benchmark_return": benchmark_return,
                "benchmark_id": row.get("benchmark_id") or "cross_sectional_median:v1",
                "excess_return": excess,
                "direction_hit": hit,
                "expected_return": expected,
                "target_weight": weight,
                "features": row.get("features") or {},
                "feature_schema": row.get("feature_schema") or sorted((row.get("features") or {}).keys()),
                "ood_multiplier": self._finite(prediction.get("ood_multiplier")),
                "model_version": row.get("model_version"),
                "eligible": row.get("eligible", True),
            })
            done.add(key)
        if rows:
            with open(self.path, "a") as fh:
                for row in rows:
                    fh.write(json.dumps(row, allow_nan=False) + "\n")
        return len(rows)
