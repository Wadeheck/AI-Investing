"""One shared rule for declaring which book an equity mark belongs to.

THE FAILURE THIS PREVENTS. On 2026-08-20 the crypto sleeve moved from an
in-memory PaperBroker seeded at $10,000 to a real Binance Futures testnet
account holding $5,000. `data/crypto_journal.jsonl` recorded:

    2026-08-19  equity 10,052.20
    2026-08-20  equity  4,999.89

Nothing was lost — the book changed. But an equity journal is a CURVE, and
everything that reads it (the circuit breaker, `scripts/watchdog.py`,
`scripts/daily_status.py`) saw -50.3% in a single day on a book that had in
fact been flat.

This is STATE_OF_THE_SYSTEM §4.14 — "a change of book size read as a 90%
crash" — whose fix was recorded as *"declared basis, never inferred"*. The
declaration was built for the main runner's book (`runner._book_basis`, feeding
`CircuitBreaker.ensure_basis`) and the four per-book strategies never got one.
§4.14 was fixed where the bug was observed and nowhere else, the same shape as
§4.23's tick snapping and §4.36's margin equity.

Why a mixin rather than four copies: §4.10's lesson. Four books each carried
their own phantom-valuation bug until one shared valuation rule replaced them.
A rule applied at each call site is a rule you will eventually forget at one
of them.

Declared, never inferred — for the reason `CircuitBreaker.ensure_basis` gives
in its own docstring: *"equity moved a lot, must be a new book" is precisely
how you teach a safety system to explain away a real crash.* The basis string
changes when the VENUE changes and never when the money does.
"""
from __future__ import annotations


class BookBasisMixin:
    """Adds `_basis_fields()` to a strategy that owns a broker and a state dict.

    Requires `self.broker` and `self._state`.
    """

    def book_basis(self) -> str:
        try:
            return self.broker.basis()
        except Exception:
            # A basis we cannot read must not take a cycle down, and must not
            # silently look like a basis that never changed either.
            return "unknown"

    def _basis_fields(self) -> dict:
        """`{"basis": ...}` for a mark line, plus `basis_changed` on the mark
        where it actually moved.

        `basis_changed` is the field a reader needs: it turns a -50% step in the
        curve from something to explain into something already explained, at the
        exact row where it happened.
        """
        basis = self.book_basis()
        prev = self._state.get("basis")
        self._state["basis"] = basis
        if prev is not None and prev != basis:
            return {"basis": basis, "basis_changed": {"from": prev, "to": basis}}
        return {"basis": basis}
