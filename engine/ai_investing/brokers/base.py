from __future__ import annotations

from abc import ABC, abstractmethod

from ai_investing.models import Order, OrderStatus, Portfolio, Position


class BrokerAdapter(ABC):
    """Uniform interface over paper and live brokers.

    `submit` receives a reference `price` (the engine's current mark). Paper fills
    at that price; live adapters may ignore it and send a real market/limit order.
    """

    name = "broker"
    live = False

    def basis(self) -> str:
        """Identity of the BOOK this adapter backs — not its size or its value.

        WHY A BOOK NEEDS A NAME. On 2026-08-20 the crypto sleeve moved from an
        in-memory PaperBroker seeded at $10,000 to a real Binance Futures testnet
        account holding $5,000. `crypto_journal.jsonl` recorded:

            2026-08-19  10,052.20
            2026-08-20   4,999.89

        Nothing was lost. But the equity journal is a curve, and everything that
        reads it — the circuit breaker, the watchdog, daily_status — saw -50.3%
        in a day. This is §4.14 ("a change of book size read as a 90% crash")
        exactly, whose fix was "declared basis, never inferred"; the declaration
        existed for the main runner's book (`runner._book_basis`) and the sleeves
        never got one.

        Declared, never inferred, for the reason CircuitBreaker.ensure_basis
        gives: "equity moved a lot, must be a new book" is precisely how you
        teach a safety system to explain away a real crash. The default here is
        the adapter's own class and name, which changes exactly when the venue
        does and never when the money does.
        """
        return f"{self.__class__.__name__}:{self.name}"

    @abstractmethod
    def get_cash(self) -> float:
        ...

    @abstractmethod
    def get_positions(self) -> dict[str, Position]:
        ...

    @abstractmethod
    def submit(self, order: Order, price: float) -> Order:
        """Send the order and report WHAT ACTUALLY HAPPENED.

        THE CONTRACT, stated because breaking it silently was the worst bug in this
        project's history (STATE §4.15). A live venue's submit call *acknowledges* an
        order; it does not fill it. An adapter may therefore only set
        `status = FILLED` and a `filled_price` it has **confirmed with the venue**.

        When confirmation is unavailable — unimplemented, timed out, ambiguous — the
        honest answer is `PENDING` with a reason. The engine handles a pending order:
        it holds no position for it, books no P&L, and re-decides next cycle. It
        cannot handle a fabricated fill, because the ledger, the circuit breaker and
        the learning spine all read the fill price as fact.

        Three adapters implemented three different degrees of assumption here, and
        two of them invented both the quantity and the price. `confirm_or_pend()`
        below exists so the safe default costs less effort than the unsafe one.
        """
        ...

    # -- fill confirmation ---------------------------------------------------
    def fetch_fill(self, order_id: str):
        """Ask the venue about an order: `(status, filled_qty, filled_price)`.

        `status` is a venue string; `"filled"`, `"rejected"`, `"canceled"` and
        `"expired"` are recognised case-insensitively, anything else is treated as
        still working. Return None when the venue cannot be asked — the caller then
        reports PENDING rather than guessing.
        """
        return None

    def confirm_or_pend(self, order: Order, attempts: int = 4, pause: float = 0.75) -> Order:
        """Poll `fetch_fill` briefly, then record the truth — never an assumption.

        Shared so every adapter gets the same behaviour: the reason two of three had
        this wrong is that each wrote its own ending to `submit`.
        """
        import time as _time

        if not order.id:
            order.status = OrderStatus.PENDING
            order.reason = f"{order.reason or ''} [no order id returned]".strip()
            return order
        last = None
        for i in range(attempts):
            try:
                got = self.fetch_fill(order.id)
            except Exception as exc:
                last, got = exc, None
            if got is None:
                if i < attempts - 1 and last is not None:
                    _time.sleep(pause)
                    continue
                order.status = OrderStatus.PENDING
                order.reason = (f"{order.reason or ''} [unconfirmed"
                                + (f": {last}" if last else " — venue query "
                                   "unimplemented for this adapter") + "]").strip()
                return order
            status, qty, px = got
            s = str(status or "").split(".")[-1].lower()
            order.filled_qty = float(qty or 0.0)
            if px and float(px) > 0:
                order.filled_price = float(px)
            if s == "filled" and order.filled_qty > 0:
                order.status = OrderStatus.FILLED
                return order
            if s in ("rejected", "canceled", "cancelled", "expired"):
                order.status = (OrderStatus.REJECTED if s == "rejected"
                                else OrderStatus.CANCELLED)
                order.reason = f"{order.reason or ''} [venue: {s}]".strip()
                return order
            if order.filled_qty > 0 and i == attempts - 1:
                # partial still working: filled_qty carries the truth, which is what
                # every downstream calculation actually reads
                order.status = OrderStatus.FILLED
                order.reason = (f"{order.reason or ''} "
                                f"[partial {order.filled_qty:g}/{order.qty:g}]").strip()
                return order
            if i < attempts - 1:
                _time.sleep(pause)
        order.status = OrderStatus.PENDING
        order.reason = f"{order.reason or ''} [unconfirmed after {attempts} checks]".strip()
        return order

    def venue_equity_parts(self) -> tuple[float, dict] | None:
        """`(cash_excluding_those_venues, {AssetClass: venue equity})`, or None.

        Override on an adapter that spans several venues where at least one
        reports its OWN equity — a margined leg, typically. Returning None keeps
        the plain `cash + qty*price` reconstruction, which is right for every
        adapter whose cash is exchanged for positions rather than locked
        against them. See Portfolio.venue_equity and failure register §4.36.
        """
        return None

    def portfolio(self) -> Portfolio:
        parts = self.venue_equity_parts()
        if parts is None:
            return Portfolio(self.get_cash(), self.get_positions())
        cash, venue_equity = parts
        return Portfolio(cash, self.get_positions(), venue_equity=venue_equity)

    # True only for adapters whose get_cash() is a MARGIN balance — i.e. where
    # opening a position locks cash instead of exchanging it for the position's
    # value, so `cash + qty * price` is not this account's equity (§4.36). Such
    # an adapter must override get_equity(); a caller that cannot use
    # get_equity() (RoutingBroker, which has to blend two venues) must refuse
    # any configuration where the reconstruction would be wrong.
    margined = False

    def get_equity(self) -> float | None:
        """Total account equity, read straight from the venue, or None if this
        adapter has no better number than cash + mark-to-market.

        The default reconstruction every caller falls back to (cash + sum of
        qty * price) assumes opening a short CREDITS cash with sale proceeds —
        true for a paper broker or a real spot short-sell, false for a margined
        futures short, which LOCKS margin out of free cash instead. An adapter
        whose "cash" doesn't carry that assumption (see BinanceFuturesBroker)
        must override this so callers can skip the reconstruction entirely.
        """
        return None

    def snapshot(self) -> dict:
        """Read-only view of cash/positions, same shape as PaperBroker.state().

        For live adapters that have no `.state()` of their own (positions live
        at the venue, not here — see crypto_book.py/crypto_event_sleeve.py's
        `_save`). Built fresh from the venue every call, never persisted back
        via `from_state`, so it exists purely so callers that only have a
        saved-state dict (dashboards, equity-marking) still see real numbers
        instead of an empty positions list.
        """
        return {"cash": self.get_cash(), "positions": [
            {"symbol": p.asset.symbol, "qty": p.qty, "avg_price": p.avg_price}
            for p in self.get_positions().values()]}

    def place_stop(self, asset, side, qty: float, stop_price: float):
        """Place a resting protective stop AT THE VENUE, so it survives a crash/hang and
        triggers on an intraday gap between cycles. Default: unsupported (returns None)."""
        return None
