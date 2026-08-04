"""No adapter may report a fill it has not confirmed.

STATE §4.15 found LongbridgeBroker.submit() reporting every accepted order as fully
filled at the price it had merely hoped for. Fixing that one adapter was NOT a root
fix: reviewing the other two afterwards showed MoomooBroker doing exactly the same
thing, and CcxtBroker falling back to `filled or order.qty` / `average or price` —
inventing a full fill and the caller's mark whenever the exchange did not report.

Three adapters, three different degrees of the same assumption, because each wrote
its own ending to submit(). The confirmation now lives once, in
BrokerAdapter.confirm_or_pend, and these tests hold the contract for all of them.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_investing.brokers.base import BrokerAdapter
from ai_investing.models import Asset, AssetClass, Order, OrderStatus, Side

A = Asset("AAA", AssetClass.STOCK)


class _Fake(BrokerAdapter):
    """Adapter whose venue answers however a test needs it to."""
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = 0

    def get_cash(self): return 0.0
    def get_positions(self): return {}
    def submit(self, order, price): return order

    def fetch_fill(self, order_id):
        self.calls += 1
        return self.answers.pop(0) if self.answers else self.answers_default

    answers_default = None


def _order(qty=10.0, oid="1"):
    o = Order(A, Side.BUY, qty, reason="test")
    o.id = oid
    return o


def test_a_confirmed_fill_is_recorded_from_the_venue_not_the_caller():
    b = _Fake([("Filled", 10.0, 13.99)])
    o = b.confirm_or_pend(_order(), attempts=1)
    assert o.status is OrderStatus.FILLED
    assert o.filled_qty == 10.0 and o.filled_price == 13.99, \
        "the price must be the VENUE's, which is the whole point"


def test_an_unanswerable_venue_yields_pending_never_filled():
    """The default fetch_fill returns None — an adapter that has not implemented the
    query must report PENDING. The engine copes with pending; it cannot cope with a
    fabricated fill, because the ledger and the breaker read the price as fact."""
    b = _Fake([None])
    o = b.confirm_or_pend(_order(), attempts=1)
    assert o.status is OrderStatus.PENDING
    assert (o.filled_qty or 0) == 0
    assert "unconfirmed" in (o.reason or "")


def test_a_rejected_or_cancelled_order_is_never_a_fill():
    for venue_status, expected in (("Rejected", OrderStatus.REJECTED),
                                   ("Canceled", OrderStatus.CANCELLED),
                                   ("Expired", OrderStatus.CANCELLED)):
        b = _Fake([(venue_status, 0.0, 0.0)])
        o = b.confirm_or_pend(_order(), attempts=1)
        assert o.status is expected, f"{venue_status} became {o.status}"
        assert (o.filled_qty or 0) == 0


def test_an_unknown_status_is_not_optimistically_booked():
    b = _Fake([("SomeNewVenueState", 0.0, 0.0)])
    o = b.confirm_or_pend(_order(), attempts=1)
    assert o.status is OrderStatus.PENDING, \
        "an unrecognised state must never be treated as filled"


def test_a_partial_keeps_the_quantity_that_actually_executed():
    b = _Fake([("PartialFilled", 4.0, 13.50)])
    o = b.confirm_or_pend(_order(qty=10.0), attempts=1)
    assert o.filled_qty == 4.0, "downstream reads filled_qty, so it must be true"
    assert "partial" in (o.reason or "").lower()


def test_no_order_id_means_pending():
    b = _Fake([("Filled", 10.0, 13.99)])
    o = _order(oid="")
    b.confirm_or_pend(o, attempts=1)
    assert o.status is OrderStatus.PENDING and b.calls == 0, \
        "without an id there is nothing to confirm, so nothing may be claimed"


def test_no_live_adapter_declares_a_fill_by_itself():
    """The structural guarantee. If a future adapter writes its own ending to
    submit() again, this fails — which is the only reason it will not happen."""
    import inspect
    from ai_investing.brokers import live

    for name in ("CcxtBroker", "LongbridgeBroker", "MoomooBroker"):
        cls = getattr(live, name)
        src = "\n".join(l for l in inspect.getsource(cls.submit).splitlines()
                        if not l.strip().startswith("#"))
        assert "confirm_or_pend" in src or "OrderStatus.FILLED" not in src, (
            f"{name}.submit sets FILLED without going through confirm_or_pend — "
            f"this is §4.15 returning")
        assert "filled_qty = float(qty)" not in src, (
            f"{name}.submit assumes the submitted quantity was filled")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\nAll {len(tests)} fill-contract tests passed.")
