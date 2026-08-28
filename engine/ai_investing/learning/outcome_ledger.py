"""Append-only, point-in-time outcome ledgers for model improvement.

The live decision journals remain the source of truth.  This module only adds
settled labels; it never changes a model, the live book, or the linear RLS
learner.  A primary observation is (symbol, SGT day), and settlement is
idempotent.
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timedelta, timezone


class OutcomeLedger:
    def __init__(self, root: str, lane: str, horizon_days: int = 5):
        self.root = root
        self.lane = lane
        self.horizon_days = horizon_days
        os.makedirs(root, exist_ok=True)
        self.path = os.path.join(root, "outcomes.jsonl")

    def _done(self) -> set[tuple[str, str]]:
        out = set()
        try:
            with open(self.path, errors="replace") as fh:
                for line in fh:
                    try:
                        row = json.loads(line)
                        out.add((row.get("symbol"), row.get("day")))
                    except (json.JSONDecodeError, TypeError):
                        continue
        except OSError:
            pass
        return out

    def append_decisions(self, path: str, rows: list[dict]) -> None:
        """Write a separate decision stream for a non-NN consumer."""
        if not rows:
            return
        seen = set()
        try:
            with open(path, errors="replace") as fh:
                for line in fh:
                    try:
                        old = json.loads(line)
                        seen.add((old.get("symbol"), old.get("day")))
                    except (json.JSONDecodeError, TypeError):
                        continue
        except OSError:
            pass
        with open(path, "a") as fh:
            for row in rows:
                key = (row.get("symbol"), row.get("day"))
                if key in seen:
                    continue
                fh.write(json.dumps(row, allow_nan=False) + "\n")
                seen.add(key)

    @staticmethod
    def _finite(x):
        try:
            x = float(x)
            return x if math.isfinite(x) else None
        except (TypeError, ValueError):
            return None

    def settle(self, journal_path: str, prices: dict[str, float], assets: list,
               now: datetime | None = None) -> int:
        """Settle mature primary rows against current prices, once only."""
        now = now or datetime.now(timezone.utc)
        cutoff = (now + timedelta(hours=8) - timedelta(days=self.horizon_days)).date()
        done = self._done(); rows = []
        try:
            with open(journal_path, errors="replace") as fh:
                source = [json.loads(line) for line in fh if line.strip()]
        except (OSError, json.JSONDecodeError):
            return 0
        # Equal-weight cross-sectional benchmark.  This is deliberately built
        # from the same primary rows and the same valuation timestamp, so a
        # missing SPY/BTC feed cannot silently turn a stock pick into a market
        # bet.  Explicit benchmark fields, when present, still take priority.
        peer_returns = {}
        for candidate in source:
            if not candidate.get("is_primary"):
                continue
            px0 = self._finite(candidate.get("price")); px1 = self._finite(prices.get(candidate.get("asset_key")))
            if px0 and px1 and px0 > 0:
                peer_returns.setdefault(candidate.get("day"), []).append(px1 / px0 - 1.0)
        for row in source:
            key = (row.get("symbol"), row.get("day"))
            if not row.get("is_primary") or key in done or not row.get("day"):
                continue
            try:
                if datetime.strptime(row["day"], "%Y-%m-%d").date() > cutoff:
                    continue
            except (TypeError, ValueError):
                continue
            asset_key = row.get("asset_key")
            entry = self._finite(row.get("price")); exit_px = self._finite(prices.get(asset_key))
            if not asset_key or entry is None or exit_px is None or entry <= 0:
                continue
            realized = exit_px / entry - 1.0
            pred = row.get("nn3") or row.get("nn4") or row.get("brain") or {}
            expected = self._finite(pred.get("expected_return"))
            weight = self._finite(pred.get("target_weight")) or 0.0
            direction = pred.get("direction")
            benchmark_return = None
            bench_key = row.get("benchmark_key")
            bench_entry = self._finite(row.get("benchmark_price"))
            bench_exit = self._finite(prices.get(bench_key)) if bench_key else None
            if bench_entry and bench_exit and bench_entry > 0:
                benchmark_return = bench_exit / bench_entry - 1.0
            if benchmark_return is None and peer_returns.get(row.get("day")):
                values = sorted(peer_returns[row["day"]]); benchmark_return = values[len(values) // 2]
            excess = realized - benchmark_return if benchmark_return is not None else realized
            hit = None if direction in (None, "FLAT") else (
                (excess > 0) if direction == "LONG" else (excess < 0))
            out = {"lane": self.lane, "symbol": row.get("symbol"), "day": row.get("day"),
                   "settled_ts": now.isoformat(), "entry_price": entry,
                   "exit_price": exit_px, "realized_return": realized,
                   "benchmark_return": benchmark_return, "excess_return": excess,
                   "direction_hit": hit, "expected_return": expected,
                   "target_weight": weight, "features": row.get("features") or {},
                   "ood_multiplier": self._finite(pred.get("ood_multiplier")),
                   "model_version": row.get("model_version")}
            rows.append(out); done.add(key)
        if rows:
            with open(self.path, "a") as fh:
                for row in rows:
                    fh.write(json.dumps(row, allow_nan=False) + "\n")
        return len(rows)
