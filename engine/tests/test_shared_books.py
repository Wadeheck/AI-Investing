"""The sleeve and the investing book, wired to a shared account end to end.

`test_shared_account.py` proves `BookBroker` obeys its rules. This proves the two
strategies actually go THROUGH it — that state round-trips to disk, that a real
order reaches the venue, and that an exit the venue has not filled does not make
the book forget a position it still owns.
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai_investing.brokers.base import BrokerAdapter                    # noqa: E402
from ai_investing.config import Settings                               # noqa: E402
from ai_investing.models import Order, OrderStatus, Position, Side     # noqa: E402
from ai_investing.strategy import event_sleeve as es                   # noqa: E402
from ai_investing.strategy.investor import Investor                    # noqa: E402


class FakeStock(BrokerAdapter):
    name, live = "fake", True

    def __init__(self, cash=1_000_000.0, mode="fill"):
        self.cash, self.mode = float(cash), mode
        self.positions, self.sent, self._n = {}, [], 0

    def get_cash(self):
        return self.cash

    def get_positions(self):
        return dict(self.positions)

    def submit(self, order, price):
        self.sent.append((order.asset.symbol, order.side.value, order.qty))
        self._n += 1
        order.id = f"ord{self._n}"
        if self.mode == "pend":
            order.status = OrderStatus.PENDING
            return order
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
        return order

    def fetch_fill(self, order_id):
        return None


class Quiet:
    """A notifier that records instead of sending."""
    enabled = True

    def __init__(self):
        self.msgs = []

    def send(self, text, buttons=None):
        self.msgs.append(text)


def _settings(tmp, shared=True):
    s = Settings()
    s.state_path = os.path.join(tmp, "state.json")
    s.shared_stock_account = shared
    s.trade_approval = False
    return s


def _state(tmp, name):
    with open(os.path.join(tmp, name)) as fh:
        return json.load(fh)


# ------------------------------------------------------------- event sleeve --
def test_sleeve_sends_whole_shares_to_the_venue_and_records_the_claim():
    with tempfile.TemporaryDirectory() as tmp:
        st, venue = _settings(tmp), FakeStock()
        sl = es.EventSleeve(st, venue)
        sl.cycle({"AAA": {"impact": 0.3, "node": "semis"}}, {"AAA": 137.0})

        assert len(venue.sent) == 1, "the entry must reach the shared account"
        sym, side, qty = venue.sent[0]
        assert (sym, side) == ("AAA", "buy")
        assert qty == float(int(qty)) and qty >= 1, f"fractional qty sent: {qty}"

        saved = _state(tmp, "event_state.json")
        assert saved["stock_ledger"]["ledger"]["marks"]["stock:AAA"]["qty"] == qty
        assert saved["broker"]["positions"][0]["symbol"] == "AAA", \
            "the reader-facing view must still be there for the dashboard"


def test_sleeve_book_survives_a_restart_through_the_ledger():
    with tempfile.TemporaryDirectory() as tmp:
        st, venue = _settings(tmp), FakeStock()
        es.EventSleeve(st, venue).cycle({"AAA": {"impact": 0.3}}, {"AAA": 100.0})
        held = venue.get_positions()["stock:AAA"].qty

        again = es.EventSleeve(st, venue)
        assert again.broker.get_positions()["stock:AAA"].qty == held
        assert abs(again.broker.get_cash() - (es.START_CASH - held * 100.0
                                              - again.broker.ledger.fees)) < 1e-6


def test_sleeve_does_not_forget_a_position_whose_exit_did_not_fill():
    """The old code dropped `held[sym]`, settled the learning spine and announced
    a close on the strength of having ASKED. A real venue acknowledges without
    filling, and a forgotten position has no stop and no clock."""
    with tempfile.TemporaryDirectory() as tmp:
        st, venue = _settings(tmp), FakeStock()
        es.EventSleeve(st, venue).cycle({"AAA": {"impact": 0.3}}, {"AAA": 100.0})

        venue.mode = "pend"                      # the venue stops filling
        note = Quiet()
        r = es.EventSleeve(st, venue).cycle({}, {"AAA": 80.0}, note)   # -20%: hard stop
        assert r["closed"] == [], "an unfilled exit is not a close"
        assert not any("closed" in m for m in note.msgs), \
            "announcing a close that did not happen loses the position"

        after = es.EventSleeve(st, venue)
        assert after.broker.get_positions()["stock:AAA"].qty > 0, "still held"
        events = [json.loads(l)["event"]
                  for l in open(os.path.join(tmp, "event_journal.jsonl"))]
        assert "exit_unfilled" in events, "the miss must be on the record"


def test_sleeve_refuses_an_entry_that_floors_to_zero_shares_and_says_why():
    with tempfile.TemporaryDirectory() as tmp:
        st, venue = _settings(tmp), FakeStock()
        # One share costs more than the whole sleeve's per-name slice.
        es.EventSleeve(st, venue).cycle({"AAA": {"impact": 0.3}}, {"AAA": 900_000.0})
        assert venue.sent == [], "a doomed order must not reach the venue"
        rows = [json.loads(l) for l in open(os.path.join(tmp, "event_journal.jsonl"))]
        rej = [r for r in rows if r["event"] == "rejected"]
        assert rej and "floors to 0 whole shares" in rej[0]["reason"]


def test_sleeve_stops_calling_real_orders_pretend_money():
    with tempfile.TemporaryDirectory() as tmp:
        note = Quiet()
        es.EventSleeve(_settings(tmp), FakeStock()).cycle(
            {"AAA": {"impact": 0.3}}, {"AAA": 100.0}, note)
        assert note.msgs and "pretend money" not in note.msgs[0]
        assert "real orders" in note.msgs[0]


def test_sleeve_with_the_flag_off_is_unchanged():
    with tempfile.TemporaryDirectory() as tmp:
        st = _settings(tmp, shared=False)
        note = Quiet()
        sl = es.EventSleeve(st)
        sl.cycle({"AAA": {"impact": 0.3}}, {"AAA": 137.0}, note)
        assert sl.broker.name == "paper"
        saved = _state(tmp, "event_state.json")
        assert "stock_ledger" not in saved, "no new state key appears while off"
        assert "pretend money" in note.msgs[0]
        # The whole-share floor ships regardless of the flag — it is a fix, not a
        # feature of sharing.
        assert saved["broker"]["positions"][0]["qty"] == float(
            int(saved["broker"]["positions"][0]["qty"]))


def test_the_books_competing_for_cash_leaves_a_trace():
    """An order trimmed from 50 shares to 25 by the shared account's cash still
    returns FILLED, and the journal records 25 as though 25 were wanted. The
    difference is the only evidence the books are competing for one pot."""
    with tempfile.TemporaryDirectory() as tmp:
        st, venue = _settings(tmp), FakeStock(cash=900.0)   # account nearly empty
        es.EventSleeve(st, venue).cycle({"AAA": {"impact": 0.3}}, {"AAA": 100.0})
        rows = [json.loads(l) for l in open(os.path.join(tmp, "event_journal.jsonl"))]
        notes = [r for r in rows if r["event"] == "shared_account"]
        assert notes and "shared-account cash" in notes[0]["note"]


# ---------------------------------------------------------- investing book --
def _strategy(sym="AAA"):
    return {"theses": [{"stance": "long", "symbols": [sym], "title": "t",
                        "thesis": "why", "assumptions": "a"}]}


def test_investor_buys_whole_shares_through_the_shared_account():
    with tempfile.TemporaryDirectory() as tmp:
        st, venue = _settings(tmp), FakeStock()
        inv = Investor(st, venue)
        inv.daily_manage({"AAA": 333.0}, _strategy(), Quiet(), {})
        assert len(venue.sent) == 1
        _, side, qty = venue.sent[0]
        assert side == "buy" and qty == float(int(qty)) and qty >= 1
        assert _state(tmp, "invest_state.json")["stock_ledger"]["ledger"]["marks"]


def test_investor_cannot_open_a_stock_short_on_a_shared_account():
    """This book expresses an "overvalued" thesis as a short, and that stops
    working for stocks — a short is indistinguishable from selling the trading
    book's shares. The refusal must be recorded, not silent."""
    with tempfile.TemporaryDirectory() as tmp:
        st, venue = _settings(tmp), FakeStock()
        strat = {"theses": [{"stance": "short", "symbols": ["AAA"], "title": "bubble",
                             "thesis": "why", "assumptions": "a"}]}
        Investor(st, venue).daily_manage({"AAA": 100.0}, strat, Quiet(), {})
        assert venue.sent == [], "no short may reach the shared account"
        rows = [json.loads(l) for l in open(os.path.join(tmp, "invest_journal.jsonl"))]
        rej = [r for r in rows if r["event"] == "rejected"]
        assert rej and "stock shorts are disabled" in rej[0]["reason"]


def test_investor_keeps_a_position_whose_exit_did_not_fill():
    with tempfile.TemporaryDirectory() as tmp:
        st, venue = _settings(tmp), FakeStock()
        Investor(st, venue).daily_manage({"AAA": 100.0}, _strategy(), Quiet(), {})
        held = venue.get_positions()["stock:AAA"].qty

        venue.mode = "pend"
        inv = Investor(st, venue)
        inv._state["last_managed"] = None                # let it run again today
        note = Quiet()
        inv.daily_manage({"AAA": 100.0}, {"theses": []}, note, {})   # thesis dropped
        assert any("could NOT close" in m for m in note.msgs)
        assert Investor(st, venue).broker.get_positions()["stock:AAA"].qty == held


def test_investor_with_the_flag_off_is_unchanged():
    with tempfile.TemporaryDirectory() as tmp:
        st = _settings(tmp, shared=False)
        inv = Investor(st)
        inv.daily_manage({"AAA": 333.0}, _strategy(), Quiet(), {})
        assert inv.broker.name == "paper" and inv.broker.allow_short
        assert "stock_ledger" not in _state(tmp, "invest_state.json")


# ---------------------------------------------------- the books coexist ------
def test_two_books_on_one_account_do_not_take_each_others_shares():
    """The whole point, exercised through the real strategy code paths."""
    from ai_investing.brokers.shared import reconcile_claims
    with tempfile.TemporaryDirectory() as tmp:
        st, venue = _settings(tmp), FakeStock()
        es.EventSleeve(st, venue).cycle({"AAA": {"impact": 0.3}}, {"AAA": 100.0})
        Investor(st, venue).daily_manage({"AAA": 100.0}, _strategy(), Quiet(), {})

        sleeve_qty = es.EventSleeve(st, venue).broker.get_positions()["stock:AAA"].qty
        inv_qty = Investor(st, venue).broker.get_positions()["stock:AAA"].qty
        account = venue.get_positions()["stock:AAA"].qty
        assert abs(sleeve_qty + inv_qty - account) < 1e-9, "claims must sum to the account"

        claims = {"event": es.EventSleeve(st, venue).broker.working_positions(),
                  "investor": Investor(st, venue).broker.working_positions()}
        assert reconcile_claims(claims, venue.get_positions()) == []

        # The sleeve exits. The investing book's shares must survive.
        venue_before = account
        es.EventSleeve(st, venue).cycle({}, {"AAA": 80.0})           # hard stop
        assert venue.get_positions()["stock:AAA"].qty == venue_before - sleeve_qty
        assert Investor(st, venue).broker.get_positions()["stock:AAA"].qty == inv_qty


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"test_shared_books: all {len(fns)} passed")
