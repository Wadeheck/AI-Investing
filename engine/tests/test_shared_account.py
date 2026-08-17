"""One real account, several books — the rules that keep them from robbing each other.

Every test here runs against a FAKE stock broker, never Longbridge. The point of
`BookBroker` is that a book's own view is local, so it can be verified locally;
if these tests needed a venue the design would already be wrong.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_investing.brokers.base import BrokerAdapter
from ai_investing.brokers.shared import BookBroker, reconcile_claims
from ai_investing.execution import fees as fee_model
from ai_investing.execution.capital import BookLedger
from ai_investing.models import Asset, AssetClass, Order, OrderStatus, Position, Side


# --------------------------------------------------------------------- doubles
class FakeStock(BrokerAdapter):
    """A shared stock account. Fills instantly by default; can be told to
    acknowledge-without-filling, which is what the real adapter usually does."""

    name, live = "fake", True

    def __init__(self, cash=1_000_000.0, positions=None, mode="fill"):
        self.cash = float(cash)
        self.positions = dict(positions or {})
        self.mode = mode                 # "fill" | "pend"
        self.sent: list[Order] = []
        self.details: dict[str, tuple] = {}
        self._n = 0

    def get_cash(self):
        return self.cash

    def get_positions(self):
        return dict(self.positions)

    def submit(self, order, price):
        self.sent.append(order)
        self._n += 1
        order.id = f"ord{self._n}"
        signed = order.qty if order.side is Side.BUY else -order.qty
        if self.mode == "pend":
            order.status = OrderStatus.PENDING
            return order
        self.cash -= signed * price
        self._blend(order.asset, signed, price)
        order.filled_qty, order.filled_price = order.qty, price
        order.status = OrderStatus.FILLED
        return order

    def fetch_fill(self, order_id):
        return self.details.get(order_id)

    def _blend(self, asset, signed, price):
        p = self.positions.get(asset.key)
        if p is None:
            self.positions[asset.key] = Position(asset, signed, price)
            return
        new = p.qty + signed
        if abs(new) < 1e-9:
            self.positions.pop(asset.key, None)
        else:
            p.qty = new

    def settle(self, order_id, qty, price, status="Filled"):
        """Pretend the venue finished an order that had been PENDING."""
        self.details[order_id] = (status, qty, price)
        for o in self.sent:
            if o.id == order_id and status.lower() == "filled":
                self._blend(o.asset, qty if o.side is Side.BUY else -qty, price)
                self.cash -= (qty if o.side is Side.BUY else -qty) * price
        return self


NVDA = Asset("NVDA", AssetClass.STOCK)
BTC = Asset("BTC/USD", AssetClass.CRYPTO, exchange="gemini")


def _book(book_id="event", cash=100_000.0, stock=None, allow_short=False, **kw):
    return BookBroker(book_id, BookLedger(base=cash, **kw),
                      stock_broker=stock, allow_short=allow_short)


def _buy(b, asset, qty, px, **kw):
    return b.submit(Order(asset, Side.BUY, qty, **kw), px)


def _sell(b, asset, qty, px, **kw):
    return b.submit(Order(asset, Side.SELL, qty, **kw), px)


# ------------------------------------------------------------ whole shares --
def test_stock_buy_floors_to_whole_shares():
    shared = FakeStock()
    b = _book(stock=shared)
    o = _buy(b, NVDA, 10.9, 100.0)
    assert o.status is OrderStatus.FILLED
    assert o.filled_qty == 10.0, f"10.9 shares must floor to 10, got {o.filled_qty}"
    assert shared.sent[0].qty == 10.0, "the venue must never see a fractional qty"


def test_sub_share_stock_order_is_rejected_not_truncated_silently():
    """The sleeve's Sunday NVDA buy sized 0.71 shares. The venue would have
    truncated it to 0 and rejected; the book must say so itself, in its own
    words, rather than learn it from a venue error."""
    shared = FakeStock()
    b = _book(stock=shared)
    o = _buy(b, NVDA, 0.71, 100.0)
    assert o.status is OrderStatus.REJECTED
    assert "floors to 0 whole shares" in o.reason
    assert shared.sent == [], "a doomed order must not reach the venue at all"


def test_crypto_stays_fractional():
    b = _book(stock=FakeStock())
    o = _buy(b, BTC, 0.0031, 60_000.0)
    assert o.status is OrderStatus.FILLED
    assert abs(o.filled_qty - 0.0031) < 1e-12, "crypto is genuinely divisible"


# ------------------------------------------------------------ cash ceilings --
def test_buy_is_capped_by_the_books_own_cash_not_the_accounts():
    """The account has $1M. The book has $10k. It may spend $10k."""
    shared = FakeStock(cash=1_000_000.0)
    b = _book(cash=10_000.0, stock=shared)
    o = _buy(b, NVDA, 500.0, 100.0)          # asking for $50,000
    assert o.filled_qty == 100.0, f"expected 100 shares ($10k), got {o.filled_qty}"


def test_buy_is_capped_by_the_real_account_when_it_is_the_tighter_limit():
    """Ceilings can sum to more than the account holds. The last book to trade
    must not be the one that discovers it."""
    shared = FakeStock(cash=2_500.0)
    b = _book(cash=100_000.0, stock=shared)
    o = _buy(b, NVDA, 50.0, 100.0)
    assert o.filled_qty == 25.0, f"expected 25 shares ($2.5k), got {o.filled_qty}"
    assert any("shared-account cash" in n for n in b.notes), \
        "trimming by the shared account must be visible, not silent"


def test_buy_rejected_when_the_shared_account_is_empty():
    b = _book(cash=100_000.0, stock=FakeStock(cash=10.0))
    o = _buy(b, NVDA, 50.0, 100.0)
    assert o.status is OrderStatus.REJECTED and "shared account cash" in o.reason


def test_unreadable_account_cash_rejects_rather_than_guesses():
    class Broken(FakeStock):
        def get_cash(self):
            raise RuntimeError("network")
    o = _buy(_book(stock=Broken()), NVDA, 5.0, 100.0)
    assert o.status is OrderStatus.REJECTED and "cannot read shared account" in o.reason


# --------------------------------------------------- selling only your own --
def test_a_book_cannot_sell_shares_another_book_owns():
    """THE central rule. The account holds 40 NVDA; this book bought 10 of them.
    An exit sized off a blended read would close all 40."""
    shared = FakeStock(positions={"stock:NVDA": Position(NVDA, 40.0, 90.0)})
    b = _book(stock=shared)
    _buy(b, NVDA, 10.0, 100.0)
    assert shared.get_positions()["stock:NVDA"].qty == 50.0
    o = _sell(b, NVDA, 40.0, 110.0)
    assert o.filled_qty == 10.0, f"may only sell its own 10, sold {o.filled_qty}"
    assert shared.get_positions()["stock:NVDA"].qty == 40.0, \
        "the other book's 40 shares must survive this book's exit"
    assert any("capped at its own claim" in n for n in b.notes)


def test_a_book_sees_only_its_own_positions():
    shared = FakeStock(positions={"stock:NVDA": Position(NVDA, 40.0, 90.0)})
    b = _book(stock=shared)
    assert b.get_positions() == {}, "a raw account read is never a book's own view"
    _buy(b, NVDA, 10.0, 100.0)
    assert set(b.get_positions()) == {"stock:NVDA"}
    assert b.get_positions()["stock:NVDA"].qty == 10.0


def test_stock_shorts_are_refused_outright():
    """A short and a raid on another book's position are the same order."""
    shared = FakeStock(positions={"stock:NVDA": Position(NVDA, 40.0, 90.0)})
    b = _book(stock=shared, allow_short=True)
    o = _sell(b, NVDA, 5.0, 100.0)
    assert o.status is OrderStatus.REJECTED
    assert "stock shorts are disabled" in o.reason
    assert shared.sent == []


def test_crypto_shorts_still_work_when_the_book_allows_them():
    """The investing book expresses a bubble thesis as a short. Crypto fills on a
    local pot nobody shares, so the shared-account rule does not apply."""
    b = _book(stock=FakeStock(), allow_short=True)
    o = _sell(b, BTC, 0.5, 60_000.0)
    assert o.status is OrderStatus.FILLED
    assert b.get_positions()["crypto:BTC/USD"].qty == -0.5
    assert b.get_cash() > 100_000.0, "short proceeds raise cash"


def test_crypto_sell_is_capped_at_holdings_for_a_long_only_book():
    b = _book(stock=FakeStock(), allow_short=False)
    _buy(b, BTC, 1.0, 50_000.0)
    o = _sell(b, BTC, 5.0, 60_000.0)
    assert o.filled_qty == 1.0 and b.get_positions() == {}


# ------------------------------------------------------------ one pot only --
def test_stocks_and_crypto_draw_on_the_same_cash():
    """The bug this design avoids: a separate crypto pot and stock pot doubles
    the book's capital, and the sleeve sizes entries off equity."""
    b = _book(cash=100_000.0, stock=FakeStock())
    _buy(b, NVDA, 400.0, 100.0)                     # $40,000
    assert abs(b.get_cash() - (60_000.0 - fee_model.fill_fee(Side.BUY, 400, 100))) < 1e-6
    _buy(b, BTC, 1.0, 50_000.0)                     # $50,000 of the SAME pot
    assert b.get_cash() < 11_000.0, "crypto must spend the book's one pot"
    o = _buy(b, BTC, 1.0, 50_000.0)                 # only ~$10k left
    assert o.filled_qty < 0.25, "a book cannot spend cash it has already spent"


# ------------------------------------------------------------------- fees ----
def test_stock_fills_are_charged_and_crypto_fills_are_not():
    b = _book(stock=FakeStock())
    _buy(b, NVDA, 10.0, 100.0)
    assert abs(b.ledger.fees - fee_model.platform_fee()) < 1e-9
    before = b.ledger.fees
    _buy(b, BTC, 0.1, 50_000.0)
    assert b.ledger.fees == before, "the local crypto sim charges nothing (as before)"


def test_selling_costs_more_than_buying():
    """SEC fee and FINRA TAF are sell-side only; a fee model that misses that
    under-reports the cost of every round trip by half of its variable part."""
    buy = fee_model.fill_fee(Side.BUY, 1000, 100.0)
    sell = fee_model.fill_fee(Side.SELL, 1000, 100.0)
    assert sell > buy
    assert abs(sell - buy - (100_000 * fee_model.SEC_FEE_RATE
                             + fee_model.finra_taf(1000))) < 1e-9


def test_taf_floor_and_cap_both_bind():
    assert fee_model.finra_taf(1) == fee_model.FINRA_TAF_MIN, "the $0.01 floor is real"
    assert fee_model.finra_taf(10_000_000) == fee_model.FINRA_TAF_CAP
    assert fee_model.finra_taf(0) == 0.0, "no trade, no charge"


def test_fees_reduce_cash_but_never_realised_pnl():
    b = _book(stock=FakeStock())
    _buy(b, NVDA, 10.0, 100.0)
    b.settle({"NVDA": 100.0})
    _sell(b, NVDA, 10.0, 110.0)
    booked = b.settle({"NVDA": 110.0})
    assert abs(booked - 100.0) < 1e-6, "realised P&L is the trade, not the bill"
    assert b.ledger.fees > 0
    assert abs(b.get_cash() - (100_000.0 + 100.0 - b.ledger.fees)) < 1e-6


# ------------------------------------------------- realised P&L over cycles --
def test_partial_exit_then_full_close_books_pnl_once_each():
    b = _book(stock=FakeStock())
    _buy(b, NVDA, 100.0, 100.0)
    assert b.settle({"NVDA": 100.0}) == 0.0, "an entry books nothing"

    _sell(b, NVDA, 40.0, 110.0)
    assert abs(b.settle({"NVDA": 110.0}) - 400.0) < 1e-6, "40 × $10"
    assert b.get_positions()["stock:NVDA"].qty == 60.0
    assert abs(b.get_positions()["stock:NVDA"].avg_price - 100.0) < 1e-9, \
        "trimming must not rewrite the cost basis of what is left"

    assert b.settle({"NVDA": 130.0}) == 0.0, "an idle cycle books nothing"

    _sell(b, NVDA, 60.0, 90.0)
    assert abs(b.settle({"NVDA": 90.0}) + 600.0) < 1e-6, "60 × -$10"
    assert b.get_positions() == {}
    assert abs(b.ledger.realized - (400.0 - 600.0)) < 1e-6


def test_averaging_in_blends_the_cost_basis():
    b = _book(stock=FakeStock())
    _buy(b, NVDA, 10.0, 100.0)
    _buy(b, NVDA, 10.0, 120.0)
    p = b.get_positions()["stock:NVDA"]
    assert p.qty == 20.0 and abs(p.avg_price - 110.0) < 1e-9


# ------------------------------------------------- restart / persistence -----
def test_state_round_trips_through_json():
    """These books are rebuilt from disk every cycle — a working set that does
    not survive `json.dumps` is a book that forgets what it owns every 5 minutes."""
    b = _book(stock=FakeStock())
    _buy(b, NVDA, 10.0, 100.0)
    _buy(b, BTC, 0.5, 60_000.0)
    b.settle({"NVDA": 100.0, "BTC/USD": 60_000.0})
    saved = json.loads(json.dumps(b.ledger_state()))

    b2 = BookBroker("event", BookLedger.from_dict(saved["ledger"], base=100_000.0),
                    stock_broker=FakeStock(), pending=saved["pending"])
    assert set(b2.get_positions()) == {"stock:NVDA", "crypto:BTC/USD"}
    assert abs(b2.get_cash() - b.get_cash()) < 1e-6
    btc = b2.get_positions()["crypto:BTC/USD"]
    assert btc.asset.exchange == "gemini", "the exchange must survive the round trip"
    assert btc.asset.asset_class is AssetClass.CRYPTO


def test_legacy_marks_without_identity_fields_still_load():
    """Ledgers written before the identity fields existed must not crash."""
    led = BookLedger.from_dict({"realized": 5.0,
                                "marks": {"stock:NVDA": {"qty": 3.0, "avg": 90.0}}},
                               base=1000.0)
    pos = led.positions()["stock:NVDA"]
    assert pos.asset.symbol == "NVDA" and pos.asset.asset_class is AssetClass.STOCK
    assert pos.qty == 3.0 and pos.avg_price == 90.0


# ----------------------------------------------------------- late fills ------
def test_a_pending_order_is_claimed_when_it_fills_a_cycle_later():
    """`LongbridgeBroker.submit` returns PENDING far more often than FILLED. A
    book that forgets those orders drifts from the account permanently."""
    shared = FakeStock(mode="pend")
    b = _book(stock=shared)
    o = _buy(b, NVDA, 10.0, 100.0)
    assert o.status is OrderStatus.PENDING
    assert b.get_positions() == {}, "an unconfirmed order claims nothing yet"
    assert len(b.pending) == 1

    saved = json.loads(json.dumps(b.ledger_state()))            # engine restarts here
    shared.settle("ord1", 10.0, 101.5)

    b2 = BookBroker("event", BookLedger.from_dict(saved["ledger"], base=100_000.0),
                    stock_broker=shared, pending=saved["pending"])
    notes = b2.resolve_pending()
    assert b2.get_positions()["stock:NVDA"].qty == 10.0
    assert abs(b2.get_positions()["stock:NVDA"].avg_price - 101.5) < 1e-9, \
        "the price the venue actually traded, not the one we hoped for"
    assert b2.pending == []
    assert any("late fill" in n for n in notes)


def test_a_partial_fill_that_completes_later_is_booked_once_not_twice():
    """The venue reports CUMULATIVE executed quantity."""
    shared = FakeStock(mode="pend")
    b = _book(stock=shared)
    _buy(b, NVDA, 10.0, 100.0)

    shared.settle("ord1", 4.0, 100.0, status="PartialFilled")
    b.resolve_pending()
    assert b.get_positions()["stock:NVDA"].qty == 4.0
    assert len(b.pending) == 1, "still working — keep watching it"

    shared.settle("ord1", 10.0, 100.0, status="Filled")
    b.resolve_pending()
    assert b.get_positions()["stock:NVDA"].qty == 10.0, "6 more, not 10 more"
    assert b.pending == []


def test_a_rejected_pending_order_claims_nothing():
    shared = FakeStock(mode="pend")
    b = _book(stock=shared)
    _buy(b, NVDA, 10.0, 100.0)
    shared.settle("ord1", 0.0, 0.0, status="Rejected")
    b.resolve_pending()
    assert b.get_positions() == {} and b.pending == []


def test_an_unresolvable_order_is_kept_not_dropped():
    """Dropping a claim we cannot confirm is exactly the permanent drift this
    machinery exists to prevent. Keep asking."""
    shared = FakeStock(mode="pend")
    b = _book(stock=shared)
    _buy(b, NVDA, 10.0, 100.0)
    b.resolve_pending()                     # no detail recorded -> unknown
    assert len(b.pending) == 1


def test_a_late_fill_lands_in_the_book_that_placed_the_order():
    """Two books, one account, one order id each. Attribution is by id."""
    shared = FakeStock(mode="pend")
    ev, inv = _book("event", stock=shared), _book("investor", stock=shared)
    _buy(ev, NVDA, 10.0, 100.0)
    _buy(inv, NVDA, 25.0, 100.0)
    shared.settle("ord1", 10.0, 100.0).settle("ord2", 25.0, 100.0)
    ev.resolve_pending()
    inv.resolve_pending()
    assert ev.get_positions()["stock:NVDA"].qty == 10.0
    assert inv.get_positions()["stock:NVDA"].qty == 25.0


# ------------------------------------------------------- reconciliation ------
def test_reconcile_is_silent_when_the_books_add_up():
    real = {"stock:NVDA": Position(NVDA, 35.0, 100.0)}
    claims = {"main": {"stock:NVDA": Position(NVDA, 25.0, 99.0)},
              "event": {"stock:NVDA": Position(NVDA, 10.0, 101.0)}}
    assert reconcile_claims(claims, real) == []


def test_reconcile_catches_a_manual_trade_in_the_broker_app():
    real = {"stock:NVDA": Position(NVDA, 5.0, 100.0)}
    claims = {"main": {"stock:NVDA": Position(NVDA, 25.0, 99.0)},
              "event": {"stock:NVDA": Position(NVDA, 10.0, 101.0)}}
    drift = reconcile_claims(claims, real)
    assert len(drift) == 1 and "claim 35.0000" in drift[0] and "holds 5.0000" in drift[0]


def test_reconcile_catches_a_position_no_book_claims():
    drift = reconcile_claims({"main": {}}, {"stock:TSM": Position(Asset("TSM", AssetClass.STOCK), 7.0, 1.0)})
    assert len(drift) == 1 and "stock:TSM" in drift[0]


def test_reconcile_ignores_crypto():
    """Crypto never reaches the shared account, so the account holding none of
    it is not drift — it is the design."""
    claims = {"event": {"crypto:BTC/USD": Position(BTC, 1.0, 60_000.0)}}
    assert reconcile_claims(claims, {}) == []


# --------------------------------------------------- the reader-facing shape --
def test_the_reader_view_shows_money_committed_to_unfilled_orders():
    """It vanished. `get_cash()` reports SPENDABLE cash so a book cannot spend
    the same money twice; handing that to a reader subtracts the commitment
    while no position exists for it yet, so the money appears nowhere.

    On 2026-08-17 Telegram reported the event sleeve at $4,362 when it held
    $11,102, and the four books "down $7,226 since the $40,000 start" when they
    were up $955."""
    shared = FakeStock(mode="pend")
    b = _book(cash=10_000.0, stock=shared)
    _buy(b, NVDA, 30.0, 100.0)                      # $3,000 queued, unfilled

    assert b.get_cash() == 7_000.0, "spendable is still net of the commitment"
    view = b.state()
    assert view["cash"] == 10_000.0, \
        f"a reader must see the whole book, got ${view['cash']:,.2f}"
    assert view["committed"] == 3_000.0, "and be told how much is spoken for"
    assert view["positions"] == [], "an unfilled order is not a position"


def test_the_reader_view_and_the_ledger_agree_once_filled():
    shared = FakeStock(mode="pend")
    b = _book(cash=10_000.0, stock=shared)
    _buy(b, NVDA, 30.0, 100.0)
    shared.settle("ord1", 30.0, 100.0)
    b.resolve_pending()
    view = b.state()
    assert view["committed"] == 0.0
    assert abs(view["cash"] - (7_000.0 - b.ledger.fees)) < 1e-6
    assert view["positions"][0]["qty"] == 30.0
    # equity is unchanged by the fill: cash became stock, less the fee
    assert abs(view["cash"] + 30.0 * 100.0 - (10_000.0 - b.ledger.fees)) < 1e-6


def test_state_keeps_paper_brokers_shape_for_readers():
    """The Telegram portfolio, the dashboard and each book's `_stamp_marks` all
    read `state["broker"]["positions"]`. Changing that shape would make every one
    of them report a book holding nothing — wrong in the most reassuring
    direction."""
    b = _book(stock=FakeStock())
    _buy(b, NVDA, 10.0, 100.0)
    view = b.state()
    assert set(view) == {"cash", "committed", "positions"}
    row = view["positions"][0]
    assert set(row) == {"symbol", "asset_class", "exchange", "quote", "qty", "avg_price"}
    assert row["symbol"] == "NVDA" and row["qty"] == 10.0
    assert abs(view["cash"] - b.get_cash()) < 1e-9


# ------------------------------- orders in flight commit cash and occupy a name --
def test_a_queued_order_commits_its_cash_immediately():
    """THE 4.46x BUG (2026-08-17). Longbridge answers an order placed outside US
    market hours with `NotReported` — queued, not filled. That is honestly
    PENDING, so no position is claimed and the ledger does not move. `get_cash()`
    returned the ledger, so the book reported its full cash again next cycle and
    spent it a second time. The sleeve ended with $33,946 of queued buys against
    a $7,612 book, all waiting to fill at the opening bell."""
    shared = FakeStock(mode="pend")
    b = _book(cash=10_000.0, stock=shared)
    o = _buy(b, NVDA, 30.0, 100.0)
    assert o.status is OrderStatus.PENDING
    assert b.pending_commitment() == 3_000.0
    assert b.get_cash() == 7_000.0, "cash committed to a live order is not cash"


def test_a_book_cannot_spend_the_same_cash_twice_while_orders_queue():
    shared = FakeStock(mode="pend")
    b = _book(cash=10_000.0, stock=shared)
    for _ in range(5):
        _buy(b, NVDA, 40.0, 100.0)      # $4,000 each against a $10,000 book
    committed = b.pending_commitment()
    assert committed <= 10_000.0 + 1e-6, \
        f"the book committed ${committed:,.0f} of a $10,000 pot"
    assert b.get_cash() >= -1e-6, "spendable cash must never go negative"


def test_a_filled_order_stops_committing_and_starts_costing():
    shared = FakeStock(mode="pend")
    b = _book(cash=10_000.0, stock=shared)
    _buy(b, NVDA, 30.0, 100.0)
    shared.settle("ord1", 30.0, 100.0)
    b.resolve_pending()
    assert b.pending_commitment() == 0.0, "no longer in flight"
    assert abs(b.get_cash() - (7_000.0 - b.ledger.fees)) < 1e-6, "now a real cost"


def test_a_rejected_order_gives_its_committed_cash_back():
    shared = FakeStock(mode="pend")
    b = _book(cash=10_000.0, stock=shared)
    _buy(b, NVDA, 30.0, 100.0)
    assert b.get_cash() == 7_000.0
    shared.settle("ord1", 0.0, 0.0, status="Rejected")
    b.resolve_pending()
    assert b.get_cash() == 10_000.0, "a refused order must not hold cash hostage"


def test_a_queued_sell_cannot_be_sent_twice_and_oversell_the_claim():
    """The nastier half of the same bug. A queued SELL does not reduce the
    claim, so an exit that re-fires while its first order sits `NotReported`
    passes the "sell only what you claim" check a second time — ten shares sold
    twice, taking the account short or straight through another book's
    position."""
    shared = FakeStock()
    b = _book(stock=shared)
    _buy(b, NVDA, 10.0, 100.0)
    shared.mode = "pend"

    first = _sell(b, NVDA, 10.0, 110.0)
    assert first.status is OrderStatus.PENDING
    second = _sell(b, NVDA, 10.0, 110.0)          # the exit re-fires next cycle
    assert second.status is OrderStatus.REJECTED
    assert "unpromised" in second.reason
    assert len([s for s in shared.sent if s.side is Side.SELL]) == 1


def test_a_dead_sell_order_frees_the_claim_to_be_exited_again():
    """The cap must not become a trap: if the exit order dies, the position is
    still held and still needs its exit."""
    shared = FakeStock()
    b = _book(stock=shared)
    _buy(b, NVDA, 10.0, 100.0)
    shared.mode = "pend"
    _sell(b, NVDA, 10.0, 110.0)
    assert _sell(b, NVDA, 10.0, 110.0).status is OrderStatus.REJECTED

    shared.settle("ord2", 0.0, 0.0, status="Expired")
    b.resolve_pending()
    shared.mode = "fill"
    again = _sell(b, NVDA, 10.0, 110.0)
    assert again.status is OrderStatus.FILLED and again.filled_qty == 10.0
    assert b.get_positions() == {}


def test_pending_symbols_reports_what_is_in_flight():
    shared = FakeStock(mode="pend")
    b = _book(stock=shared)
    _buy(b, NVDA, 10.0, 100.0)
    assert b.pending_symbols() == {"NVDA"}
    shared.settle("ord1", 10.0, 100.0)
    b.resolve_pending()
    assert b.pending_symbols() == set(), "settled orders are no longer in flight"


def test_the_stuck_order_warning_fires_once_not_every_cycle():
    """209 journal lines about nine orders in one evening. The noise does not
    merely annoy — it is the same alert-fatigue failure that buried the
    crash-loop diagnosis in STATE 4.16."""
    from datetime import datetime, timedelta, timezone
    shared = FakeStock(mode="pend")
    b = _book(stock=shared)
    _buy(b, NVDA, 10.0, 100.0)
    old = (datetime.now(timezone.utc) - timedelta(hours=9)).isoformat()
    b.pending[0]["ts"] = old
    notes = [n for _ in range(6) for n in b.resolve_pending()]
    assert len(notes) == 1, f"expected one warning, got {len(notes)}"
    assert "still unresolved" in notes[0]
    assert len(b.pending) == 1, "and the order is still watched, just not re-announced"


# --------------------------------------------- only USD listings go to Longbridge
HKEX = Asset("2331.HK", AssetClass.STOCK)
AMS = Asset("PRX.AS", AssetClass.STOCK)


def test_non_usd_listings_never_reach_the_shared_account():
    """The investing book holds PRX.AS, 2331.HK and 2097.HK right now. The
    trading book has been fenced off from non-USD listings since
    `_live_universe()` was written — Longbridge symbols only round-trip for
    `.US`, and `cost_price` arrives in the listing currency."""
    shared = FakeStock()
    b = _book(stock=shared)
    for asset in (HKEX, AMS):
        o = _buy(b, asset, 100.0, 10.0)
        assert o.status is OrderStatus.FILLED, "it must still trade, just locally"
    assert shared.sent == [], "no non-USD order may reach the venue"
    assert set(b.get_positions()) == {"stock:2331.HK", "stock:PRX.AS"}


def test_a_locally_simulated_stock_keeps_its_fractional_size():
    """Whole shares are a VENUE constraint. A simulated position has no venue."""
    b = _book(stock=FakeStock())
    o = _buy(b, HKEX, 734.6691, 1.875)
    assert abs(o.filled_qty - 734.6691) < 1e-9


def test_reconcile_ignores_positions_that_cannot_reach_the_account():
    """The account correctly holds no 2331.HK. Calling that drift would halt the
    engine every cycle, forever, on a position working exactly as designed."""
    claims = {"investor": {"stock:2331.HK": Position(HKEX, 734.0, 1.87),
                           "stock:PRX.AS": Position(AMS, 29.0, 47.5)}}
    assert reconcile_claims(claims, {}) == []


def test_reconcile_still_checks_usd_listings_alongside_them():
    claims = {"investor": {"stock:2331.HK": Position(HKEX, 734.0, 1.87),
                           "stock:NVDA": Position(NVDA, 10.0, 100.0)}}
    assert reconcile_claims(claims, {"stock:NVDA": Position(NVDA, 10.0, 100.0)}) == [], \
        "the HK position must not make an otherwise-clean account look wrong"
    drift = reconcile_claims(claims, {"stock:NVDA": Position(NVDA, 4.0, 100.0)})
    assert len(drift) == 1 and "stock:NVDA" in drift[0], \
        "and it must not mask a real disagreement about the USD one"


# ------------------------- simulated holdings are not claims on the account --
def test_a_locally_filled_position_is_not_claimed_against_the_account():
    """A book can hold both kinds at once. `PRX.AS` has no Longbridge symbol and
    never will, so it is simulated forever — counting it as a claim on an
    account that holds none of it is not drift detection, it is a false halt."""
    b = _book(stock=FakeStock())
    _buy(b, HKEX, 100.0, 10.0)                    # no lot table => simulated
    assert b.get_positions()["stock:2331.HK"].qty == 100.0, "the book holds it"
    assert b.working_positions() == {}, "but the ACCOUNT does not"
    assert reconcile_claims({"investor": b.working_positions()}, {}) == []


def test_simulated_ness_survives_a_restart():
    """It is a fact about how the position was FILLED, not about its market
    today. 2331.HK was simulated while Hong Kong was unreachable; the day it
    became reachable, reconciliation halted the engine on 734 shares that were
    never real."""
    b = _book(stock=FakeStock())
    _buy(b, HKEX, 100.0, 10.0)
    b.settle({"2331.HK": 10.0})
    saved = json.loads(json.dumps(b.ledger_state()))
    assert saved["sim_keys"] == ["stock:2331.HK"]

    b2 = BookBroker("investor", BookLedger.from_dict(saved["ledger"], base=100_000.0),
                    stock_broker=FakeStock(), pending=saved["pending"],
                    sim_keys=saved["sim_keys"])
    assert b2.get_positions()["stock:2331.HK"].qty == 100.0
    assert b2.working_positions() == {}


def test_a_venue_fill_clears_the_simulated_flag():
    """Same symbol, both ways round: simulated while unreachable, real once the
    lot table arrives."""
    from ai_investing.brokers.lots import LotBook
    shared = FakeStock()
    b = _book(stock=shared)
    _buy(b, HKEX, 100.0, 10.0)
    assert b.working_positions() == {}

    b.lots = LotBook("/nonexistent", {"2331.HK": 100})   # now reachable
    _buy(b, HKEX, 100.0, 10.0)
    assert shared.sent, "the second order reached the venue"
    assert "stock:2331.HK" in b.working_positions(), "and is claimed against it"


def test_migration_marks_what_it_carried_as_simulated():
    from ai_investing.brokers.shared import build_book_broker

    class S:
        shared_stock_account = True
        base_currency = "USD"
    state = {"broker": _paper(6_913.07, [
        {"symbol": "PDD", "asset_class": "stock", "qty": 16.6, "avg_price": 90.16},
        {"symbol": "2331.HK", "asset_class": "stock", "qty": 734.0, "avg_price": 1.875},
    ])}
    b, note = build_book_broker("investor", S(), state, 10_000.0)
    assert b.sim_keys == {"stock:2331.HK"}
    assert b.working_positions() == {}, "nothing carried over is a claim"


# ---------------------------------------------------------------- migration --
def _paper(cash, positions):
    return {"cash": cash, "positions": positions}


def test_migration_drops_simulated_stock_and_returns_its_cash():
    """The sleeve's NVDA/TSM/AMD were "bought" on a Sunday, fractionally, at
    whatever price a simulator was handed. Making them real retroactively would
    put shares in a real account no real order ever bought."""
    from ai_investing.brokers.shared import migrate_paper_state
    led, note = migrate_paper_state(_paper(20_000.0, [
        {"symbol": "NVDA", "asset_class": "stock", "qty": 0.71, "avg_price": 1000.0},
        {"symbol": "TSM", "asset_class": "stock", "qty": 400.0, "avg_price": 125.0},
    ]), base=100_000.0)
    assert led.marks == {}, "no simulated stock position survives"
    assert led.realized == 0.0, "closing at cost books no fictional P&L"
    # $20,000 cash + $710 + $50,000 released from the two positions
    assert abs(led.book_portfolio({}).cash - 70_710.0) < 1e-6
    assert len(note["closed_simulated_stock"]) == 2
    assert note["cash_after"] == 70_710.0


def test_migration_keeps_positions_that_stay_simulated():
    """PRX.AS and 2331.HK cannot reach the venue, so nothing about them is
    changing. Closing them would destroy live theses to celebrate a bookkeeping
    change."""
    from ai_investing.brokers.shared import migrate_paper_state
    led, note = migrate_paper_state(_paper(6_913.07, [
        {"symbol": "PDD", "asset_class": "stock", "qty": 16.637, "avg_price": 90.16},
        {"symbol": "PRX.AS", "asset_class": "stock", "qty": 29.88, "avg_price": 47.51},
        {"symbol": "2331.HK", "asset_class": "stock", "qty": 734.67, "avg_price": 1.875},
    ]), base=10_000.0)
    assert set(led.marks) == {"stock:PRX.AS", "stock:2331.HK"}
    assert [c["symbol"] for c in note["closed_simulated_stock"]] == ["PDD"]
    # cash rises only by the USD position closed at cost
    assert abs(led.book_portfolio(led.positions()).cash
               - (6_913.07 + 16.637 * 90.16)) < 1e-6


def test_migration_carries_crypto_across_untouched():
    from ai_investing.brokers.shared import migrate_paper_state
    led, _ = migrate_paper_state(_paper(40_000.0, [
        {"symbol": "BTC/USD", "asset_class": "crypto", "qty": 1.0,
         "avg_price": 60_000.0, "exchange": "gemini"},
    ]), base=100_000.0)
    pos = led.positions()["crypto:BTC/USD"]
    assert pos.qty == 1.0 and pos.avg_price == 60_000.0
    assert pos.asset.exchange == "gemini"
    assert abs(led.book_portfolio(led.positions()).cash - 40_000.0) < 1e-6, \
        "cash must be preserved to the cent across the accounting change"


def test_migration_puts_the_correction_in_adjust_not_realised():
    """A book whose track record jumps because its bookkeeping changed has no
    track record."""
    from ai_investing.brokers.shared import migrate_paper_state
    led, _ = migrate_paper_state(_paper(133_500.0, []), base=100_000.0)
    assert led.realized == 0.0
    assert abs(led.adjust - 33_500.0) < 1e-6
    assert abs(led.book_portfolio({}).cash - 133_500.0) < 1e-6


def test_migration_happens_once_and_is_not_repeated():
    """`build_book_broker` runs on every construction — several times a cycle."""
    from ai_investing.brokers.shared import build_book_broker

    class S:
        shared_stock_account = True
    state = {"broker": _paper(50_000.0, [])}
    b1, note1 = build_book_broker("event", S(), state, 100_000.0)
    assert note1 is not None
    state["stock_ledger"] = b1.ledger_state()
    b2, note2 = build_book_broker("event", S(), state, 100_000.0)
    assert note2 is None, "a second migration would re-apply the cash correction"
    assert abs(b2.get_cash() - 50_000.0) < 1e-6


def test_a_fresh_book_starts_with_its_full_pot_and_is_not_migrated():
    """A book with no prior state has nothing to migrate. Running the migration
    on it anyway computed `adjust = 0 - base` and started the book at zero cash —
    it could never open a position and nothing said why."""
    from ai_investing.brokers.shared import build_book_broker

    class S:
        shared_stock_account = True
    b, note = build_book_broker("event", S(), {}, 100_000.0)
    assert note is None
    assert b.get_cash() == 100_000.0
    assert b.ledger.adjust == 0.0


def test_flag_off_still_gives_a_plain_paper_broker():
    """Off must be byte-for-byte the old behaviour, so this can be deployed
    before it is switched on."""
    from ai_investing.brokers.paper import PaperBroker
    from ai_investing.brokers.shared import build_book_broker

    class S:
        shared_stock_account = False
    state = {"broker": _paper(50_000.0, [
        {"symbol": "NVDA", "asset_class": "stock", "qty": 0.71, "avg_price": 1000.0}])}
    b, note = build_book_broker("event", S(), state, 100_000.0)
    assert isinstance(b, PaperBroker) and note is None
    assert b.get_cash() == 50_000.0
    assert b.get_positions()["stock:NVDA"].qty == 0.71, "untouched, fractions and all"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"test_shared_account: all {len(fns)} passed")
