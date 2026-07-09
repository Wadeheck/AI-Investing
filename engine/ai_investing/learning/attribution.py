"""Credit assignment: turn realized position outcomes into learning samples.

Tracks each position from open to close and, when it closes, emits the feature
vector φ that opened it paired with the realized signed return y. Those (φ, y) pairs
are what the online RLS learner consumes — the engine literally learns from P&L.
"""
from __future__ import annotations

from dataclasses import dataclass

from ai_investing.models import Position


@dataclass
class Sample:
    symbol: str
    features: dict
    realized_return: float


class OutcomeTracker:
    def __init__(self) -> None:
        # key -> {features, entry_price, direction, symbol}
        self._open: dict[str, dict] = {}

    def sync(self, positions: dict[str, Position], features_by_key: dict[str, dict],
             prices: dict[str, float]) -> list[Sample]:
        """Call once per cycle AFTER execution. Returns samples for trades that closed.

        Simplification: a position is "closed" when its key goes from held to flat;
        adds and same-cycle sign flips reuse/ignore the original entry φ.
        """
        samples: list[Sample] = []
        current = {k for k, p in positions.items() if abs(p.qty) > 1e-9}
        previous = set(self._open)

        for key in previous - current:  # closed
            rec = self._open.pop(key)
            exit_px = prices.get(key)
            entry = rec["entry_price"]
            if exit_px and entry:
                realized = (exit_px - entry) / entry * rec["direction"]
                samples.append(Sample(rec["symbol"], rec["features"], realized))

        for key in current - previous:  # newly opened
            feats = features_by_key.get(key)
            if feats is None:
                continue  # opened without a tracked decision (e.g. a reversal) -> skip
            pos = positions[key]
            self._open[key] = {
                "features": feats,
                "entry_price": pos.avg_price,
                "direction": 1.0 if pos.qty > 0 else -1.0,
                "symbol": pos.asset.symbol,
            }
        return samples

    @property
    def open_count(self) -> int:
        return len(self._open)
