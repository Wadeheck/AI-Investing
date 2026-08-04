"""Trading a bounded slice of a much larger live account.

WHY THIS EXISTS
---------------
Every risk limit in this engine is a fraction of equity: `max_position_weight`,
`max_gross_exposure`, and all three breaker thresholds (daily, trailing,
inception). While the book was a `PaperBroker` seeded with `STARTING_CASH`, that
denominator was the money at risk and the percentages meant what they said.

A live adapter breaks that silently. The Longbridge paper account this was built
for reports USD 1,000,000; the intent was to risk USD 10,000. Attached directly,
`RISK_MAX_POSITION_WEIGHT=0.15` authorises a $150,000 position — fifteen times
the entire stake — and `RISK_MAX_DAILY_DRAWDOWN=0.05` puts the halt at −$50,000,
so the stake could be lost in full, five times over, without a single breaker
firing. Nothing errors. The safety layer simply measures a book nobody is
trading.

WHAT IT DOES
------------
Keeps a ledger over the slice and hands the rest of the engine a `Portfolio`
describing *only* that slice:

    equity = base + realized + Σ qty·(price − avg)

Returning a real `Portfolio` is the whole design. Sizing, exposure, stop losses
and the circuit breaker are unchanged and unaware — they receive a book whose
equity is $10,000 and size against it correctly. One boundary, converted once,
rather than a cap threaded through every consumer. (The same reasoning as fixing
FX at the data layer in §4.2 rather than at each display site.)

WHAT IT DELIBERATELY DOES NOT DO
--------------------------------
It does not measure the account. An obvious-looking alternative — track the
account's own net assets and take the delta since the epoch began — is wrong
here: the account also holds 1M SGD and 1M HKD idle, whose USD value drifts by
thousands a day. That FX noise would swamp a $10,000 book and trip breakers on
days the strategy did nothing. Only positions the engine opened are counted.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from ai_investing.models import Portfolio, Position


@dataclass
class BookLedger:
    """Shadow accounting for the slice. `realized` accumulates closed P&L."""

    base: float
    realized: float = 0.0
    # {position key: {"qty": float, "avg": float}} as of the last observation —
    # needed because realized P&L can only be computed against the cost basis a
    # position had BEFORE it was reduced, and the broker stops reporting it after.
    marks: dict = field(default_factory=dict)

    # -- serialisation ------------------------------------------------------
    def to_dict(self) -> dict:
        return {"base": self.base, "realized": self.realized, "marks": self.marks}

    @classmethod
    def from_dict(cls, d: dict, base: float) -> "BookLedger":
        """`base` comes from config and always wins: changing LIVE_CAPITAL_BASE
        must take effect, and a stale base persisted from an earlier run would
        silently override the setting the operator just edited."""
        return cls(base=base,
                   realized=float(d.get("realized", 0.0) or 0.0),
                   marks=dict(d.get("marks") or {}))

    # -- accounting ---------------------------------------------------------
    def observe(self, positions: dict[str, Position], prices: dict[str, float]) -> float:
        """Fold any reduction since the last observation into `realized`.

        Called once per cycle AFTER fills. Returns the P&L booked this cycle.

        Reduction rather than "sell" on purpose: a short is closed by a BUY, and a
        position can be trimmed without being closed. What matters is that |qty|
        fell — and a flip (long to short in one fill) closes the whole old side.
        """
        booked = 0.0
        for key, prev in list(self.marks.items()):
            prev_qty = float(prev.get("qty", 0.0) or 0.0)
            avg = float(prev.get("avg", 0.0) or 0.0)
            now = positions.get(key)
            now_qty = float(now.qty) if now else 0.0

            # closed quantity, signed with the OLD side; a flip closes all of it
            if prev_qty > 0:
                closed = prev_qty - max(now_qty, 0.0)
            elif prev_qty < 0:
                closed = prev_qty - min(now_qty, 0.0)
            else:
                closed = 0.0
            if abs(closed) < 1e-9 or avg <= 0:
                continue

            px = prices.get(key)
            try:
                px = float(px)
            except (TypeError, ValueError):
                px = None
            # No usable exit price means no bookable P&L. Do NOT fall back to the
            # cost basis and call it flat: that would quietly record a real gain
            # or loss as zero and the ledger would drift from the account forever.
            # Keep the mark and try again next cycle. (§4.10's lesson: a missing
            # price is not a valuation.)
            if px is None or not math.isfinite(px) or px <= 0:
                continue

            booked += (px - avg) * closed

        self.realized += booked
        # re-baseline to what the account holds now
        self.marks = {k: {"qty": float(p.qty), "avg": float(p.avg_price)}
                      for k, p in positions.items() if abs(float(p.qty)) > 1e-9}
        return booked

    def book_portfolio(self, positions: dict[str, Position]) -> Portfolio:
        """The slice, as a Portfolio the rest of the engine can use unchanged.

        `cost` is signed, which is what makes shorts work: a short's cost is
        negative, so the sale proceeds raise cash exactly as they do in the paper
        broker — the same accounting whose absence caused §4.7.
        """
        cost = sum(float(p.avg_price) * float(p.qty) for p in positions.values())
        return Portfolio(cash=self.base + self.realized - cost, positions=dict(positions))


def own_positions(positions: dict[str, Position], universe) -> dict[str, Position]:
    """Positions inside the engine's mandate. See runner.foreign_positions()."""
    return {k: p for k, p in positions.items() if k in universe}
