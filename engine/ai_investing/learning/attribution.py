"""Credit assignment: turn realized position outcomes into learning samples.

Tracks each position from open to close and, when it closes, emits the feature
vector φ that opened it paired with the realized signed return y. Those (φ, y) pairs
are what the online RLS learner consumes — the engine literally learns from P&L.

THE PAIRING IS THE WHOLE POINT, AND IT HAS TO SURVIVE A RESTART (2026-08-17).
This tracker was memory-only: `_open` was rebuilt empty in every `Runner`
constructor and never written anywhere. The engine restarts at least daily — the
ProDesk powers down 05:00–07:30 SGT — while the trading book holds positions for
days to weeks. So a position was re-registered after every restart with THAT
MORNING's feature vector, and when it finally closed the learner was handed
(today's φ, a two-week return).

That is not a lost sample, which would merely be slow. It is a WRONG sample:
the model would be taught that whatever the features happened to look like this
morning caused a move that was decided on a fortnight ago. Every sample the
live engine could ever have produced would have carried that defect, and the
only reason none did is that the book has closed nothing since going live —
`outcomes` held zero rows after sixteen days and thirty-one fills.

So `_open` is persisted, and φ is the φ that actually opened the position.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from ai_investing.models import Position


@dataclass
class Sample:
    symbol: str
    features: dict
    realized_return: float


class OutcomeTracker:
    def __init__(self) -> None:
        # key -> {features, entry_price, direction, symbol, opened_ts}
        self._open: dict[str, dict] = {}

    # -- persistence --------------------------------------------------------
    def state(self) -> dict:
        return {"open": self._open}

    @classmethod
    def from_state(cls, d: dict) -> "OutcomeTracker":
        t = cls()
        for key, rec in ((d or {}).get("open") or {}).items():
            # A malformed record is dropped rather than raised on: a corrupt
            # claims file must cost one sample, never the engine's start-up.
            if isinstance(rec, dict) and isinstance(rec.get("features"), dict):
                t._open[key] = rec
        return t

    def pending_ages(self, now=None) -> dict[str, float]:
        """Days each tracked claim has been open. For reporting how starved the
        learner is — "zero samples" and "nothing has closed yet" look identical
        from the outside and mean very different things."""
        now = now or datetime.now(timezone.utc)
        out = {}
        for key, rec in self._open.items():
            try:
                t0 = datetime.fromisoformat(str(rec.get("opened_ts")))
                if t0.tzinfo is None:
                    t0 = t0.replace(tzinfo=timezone.utc)
                out[key] = (now - t0).total_seconds() / 86400.0
            except (TypeError, ValueError):
                continue
        return out

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
                "opened_ts": datetime.now(timezone.utc).isoformat(),
            }
        return samples

    @property
    def open_count(self) -> int:
        return len(self._open)
