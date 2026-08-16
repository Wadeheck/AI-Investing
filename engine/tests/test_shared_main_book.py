"""The TRADING book on a shared account.

Converting the main book is not optional and not cosmetic. Its ledger reads
`broker.get_positions()` — the raw account — as its own holdings. That is exactly
right while it is the account's only user and catastrophic the moment it is not:
the sleeve's NVDA becomes the trading book's NVDA, the sleeve's P&L is booked
here, and `_reconcile` halts the engine on a difference that is not a fault.

A live broker cannot be built in a test (no SDK, no keys), so `get_broker` is
replaced with a routed fake. Everything else is the real `Runner`.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_investing import runner as runner_mod                          # noqa: E402
from ai_investing.brokers.base import BrokerAdapter                    # noqa: E402
from ai_investing.brokers.paper import PaperBroker                     # noqa: E402
from ai_investing.brokers.routing import RoutingBroker                 # noqa: E402
from ai_investing.config import Settings                               # noqa: E402
from ai_investing.models import Asset, AssetClass, Order, OrderStatus, Position, Side  # noqa: E402
from ai_investing.runner import Runner                                 # noqa: E402

AAA = Asset("AAA", AssetClass.STOCK)


class FakeStock(BrokerAdapter):
    name, live = "fake", True

    def __init__(self, cash=1_000_000.0, positions=None):
        self.cash = float(cash)
        self.positions = dict(positions or {})

    def get_cash(self):
        return self.cash

    def get_positions(self):
        return dict(self.positions)

    def submit(self, order, price):
        signed = order.qty if order.side is Side.BUY else -order.qty
        self.cash -= signed * price
        p = self.positions.get(order.asset.key)
        if p is None:
            self.positions[order.asset.key] = Position(order.asset, signed, price)
        elif abs(p.qty + signed) < 1e-9:
            self.positions.pop(order.asset.key)
        else:
            p.qty += signed
        order.filled_qty, order.filled_price = order.qty, price
        order.status = OrderStatus.FILLED
        order.id = "x"
        return order


class Quiet:
    enabled = False

    def send(self, *a, **k):
        pass


def _runner(tmp, shared=True, stock=None, base=10_000.0):
    s = Settings()
    for attr, name in (("state_path", "state.json"), ("db_path", "j.db"),
                       ("params_path", "p.json"), ("breaker_path", "b.json"),
                       ("user_views_path", "v.json"), ("heartbeat_path", "hb.json"),
                       ("proposals_path", "pr.json")):
        setattr(s, attr, os.path.join(tmp, name))
    s.stock_watchlist, s.crypto_watchlist = ["AAA"], []
    s.data_provider = "synthetic"
    s.live, s.live_capital_base, s.shared_stock_account = True, base, shared
    s.stock_broker = "longbridge"

    venue = stock or FakeStock()
    orig = runner_mod.get_broker
    runner_mod.get_broker = lambda _s: RoutingBroker(venue, PaperBroker(0.0))
    try:
        r = Runner(s, use_news=False)
    finally:
        runner_mod.get_broker = orig
    r.notifier = Quiet()
    return r, venue


def test_the_main_book_is_wrapped_when_the_account_is_shared():
    with tempfile.TemporaryDirectory() as tmp:
        r, venue = _runner(tmp)
        assert r.book is not r.broker, "an unwrapped main book claims the account"
        assert r.book.book_id == "main"
        assert r.book.ledger is r._ledger, "it must reuse the ledger, not a copy"


def test_it_is_not_wrapped_when_the_flag_is_off():
    with tempfile.TemporaryDirectory() as tmp:
        r, _ = _runner(tmp, shared=False)
        assert r.book is r.broker, "off must be exactly the old behaviour"


def test_the_main_book_does_not_inherit_another_books_position():
    """The event sleeve bought 40 AAA before the trading book ever ran."""
    with tempfile.TemporaryDirectory() as tmp:
        venue = FakeStock(positions={"stock:AAA": Position(AAA, 40.0, 90.0)})
        r, _ = _runner(tmp, stock=venue)
        book = r._book_portfolio()
        assert book.positions == {}, "the account's shares are not this book's"
        assert abs(book.cash - 10_000.0) < 1e-9, "an untouched slice is its full base"


def test_the_main_book_cannot_sell_a_position_it_did_not_open():
    with tempfile.TemporaryDirectory() as tmp:
        venue = FakeStock(positions={"stock:AAA": Position(AAA, 40.0, 90.0)})
        r, _ = _runner(tmp, stock=venue)
        out = r.book.submit(Order(AAA, Side.SELL, 40.0, reason="stop"), 100.0)
        assert out.status is OrderStatus.REJECTED
        assert venue.get_positions()["stock:AAA"].qty == 40.0, \
            "the sleeve's position must survive the trading book's exit"


def test_the_main_books_own_trades_flow_through_the_ledger_normally():
    with tempfile.TemporaryDirectory() as tmp:
        venue = FakeStock(positions={"stock:AAA": Position(AAA, 40.0, 90.0)})
        r, _ = _runner(tmp, stock=venue)
        r.book.submit(Order(AAA, Side.BUY, 20.0, reason="entry"), 100.0)
        book = r._book_portfolio()
        assert book.positions["stock:AAA"].qty == 20.0
        assert abs(book.cash - (10_000.0 - 2_000.0 - r._ledger.fees)) < 1e-6
        assert abs(book.equity({"stock:AAA": 110.0}) - (10_200.0 - r._ledger.fees)) < 1e-6

        r.book.submit(Order(AAA, Side.SELL, 20.0, reason="exit"), 110.0)
        assert abs(r._ledger.observe(r.book.get_positions(), {"stock:AAA": 110.0})
                   + 0.0) < 1e-9, "the position is gone; P&L books against the marks"


def test_the_ledger_file_carries_pending_orders_and_still_loads_the_old_shape():
    with tempfile.TemporaryDirectory() as tmp:
        r, _ = _runner(tmp)
        state = r.book.ledger_state()
        assert set(state) == {"ledger", "pending"}

        # The flat shape this file held before pending orders existed.
        with open(r._ledger_path, "w") as fh:
            json.dump({"base": 999.0, "realized": 12.5,
                       "marks": {"stock:AAA": {"qty": 3.0, "avg": 90.0}}}, fh)
        r2, _ = _runner(tmp)
        assert r2._ledger.realized == 12.5, "an existing live_book.json must still load"
        assert r2.book.get_positions()["stock:AAA"].qty == 3.0
        assert r2._ledger.base == 10_000.0, "base always comes from config"


def test_a_late_fill_is_not_reported_as_reconciliation_drift():
    """`resolve_pending` legitimately adds shares that were not in last cycle's
    snapshot. Halting on that would halt on the one asynchronous outcome the
    design expects."""
    with tempfile.TemporaryDirectory() as tmp:
        r, _ = _runner(tmp)
        r._last_positions = {}
        r.book._working["stock:AAA"] = Position(AAA, 5.0, 100.0)
        r.book.resolved_keys = {"stock:AAA"}
        assert r._reconcile(r._book_portfolio()) is True
        assert r._last_positions["stock:AAA"] == 5.0

        # A position that appeared with NO late fill behind it is still drift.
        r.book._working["stock:AAA"] = Position(AAA, 9.0, 100.0)
        r.book.resolved_keys = set()
        assert r._reconcile(r._book_portfolio()) is False


def test_aggregate_drift_halts_the_next_cycle_and_stays_latched():
    with tempfile.TemporaryDirectory() as tmp:
        venue = FakeStock(positions={"stock:AAA": Position(AAA, 40.0, 90.0)})
        r, _ = _runner(tmp, stock=venue)
        # Nobody claims the account's 40 shares.
        assert r._reconcile_shared() is False
        assert r._shared_drift and "stock:AAA" in r._shared_drift
        assert r._reconcile(r._book_portfolio()) is False, "the next cycle must not trade"


def test_aggregate_check_is_silent_when_every_book_adds_up():
    with tempfile.TemporaryDirectory() as tmp:
        r, venue = _runner(tmp)
        r.book.submit(Order(AAA, Side.BUY, 20.0, reason="entry"), 100.0)
        assert r._reconcile_shared() is True and r._shared_drift is None


def test_an_unreadable_book_file_does_not_halt_the_engine():
    """Treating a book we cannot read as a book holding nothing would report
    every share it owns as unclaimed drift."""
    with tempfile.TemporaryDirectory() as tmp:
        venue = FakeStock(positions={"stock:AAA": Position(AAA, 40.0, 90.0)})
        r, _ = _runner(tmp, stock=venue)
        with open(os.path.join(tmp, "event_state.json"), "w") as fh:
            fh.write("{ this is not json")
        assert r._reconcile_shared() is True
        assert r._shared_drift is None


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"test_shared_main_book: all {len(fns)} passed")
