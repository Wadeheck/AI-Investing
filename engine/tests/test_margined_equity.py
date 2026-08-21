"""§4.36: `cash + sum(qty * price)` is not equity on a margined account.

The bug that produced this file reported -$4,265 of equity on a crypto book that
was actually flat at $5,014.87, because opening a futures short LOCKS margin out
of free cash instead of crediting sale proceeds into it — so the formula
subtracted the notional twice. It was fixed three times in a row (f00e477,
cadba0d, 562e620) with no test pinning any of it. This is that test.

Nothing here needs a network: the venue is a stub balance blob shaped like the
real ccxt/Binance response the bug was found in.
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai_investing.alerts.chat import ChatBot  # noqa: E402
from ai_investing.brokers.base import BrokerAdapter  # noqa: E402
from ai_investing.brokers.live import BinanceFuturesBroker  # noqa: E402
from ai_investing.brokers.routing import RoutingBroker  # noqa: E402
from ai_investing.models import Asset, AssetClass, Order, Position, Side  # noqa: E402


class _Client:
    """The two calls the reporting path makes, with the real response shape."""

    def __init__(self, balance, positions=()):
        self._balance = balance
        self._positions = list(positions)

    def fetch_balance(self):
        return self._balance

    def fetch_positions(self):
        return self._positions


def _broker(balance, positions=()):
    """A BinanceFuturesBroker with the venue stubbed out.

    Built with __new__ deliberately: __init__ imports ccxt, reads env keys and
    rewrites URLs, none of which this behaviour depends on, and all of which
    would make a pure-arithmetic test refuse to run on a box without ccxt.
    """
    b = BinanceFuturesBroker.__new__(BinanceFuturesBroker)
    b.client = _Client(balance, positions)
    b.settings = type("S", (), {"crypto_exchange": "binance"})()
    b.long_only = False
    b.leverage = 1
    b._prepared = set()
    return b


# The live account at the moment the bug was caught: $4,998.02 of wallet, two
# open shorts holding ~$4,669 of margin, leaving $340 free.
_FLAT_BOOK = {
    "info": {"totalMarginBalance": "5014.87", "totalWalletBalance": "4998.02"},
    "USDT": {"free": 340.0, "used": 4658.02, "total": 5014.87},
}
_SHORTS = [
    {"symbol": "BTC/USDT:USDT", "contracts": 0.0436, "side": "short", "entryPrice": 69529.2},
    {"symbol": "ETH/USDT:USDT", "contracts": 0.719, "side": "short", "entryPrice": 2261.68},
]


def test_equity_is_read_from_the_venue_not_reconstructed_from_cash():
    b = _broker(_FLAT_BOOK, _SHORTS)
    assert b.get_equity() == 5014.87
    assert b.get_cash() == 340.0, "sizing still needs the FREE balance, not wallet"

    # and this is what the reconstruction would have said about the same book —
    # the number that shipped to Telegram. Pinned so nobody 'simplifies'
    # get_equity() back into it.
    naive = b.get_cash() + sum(p.qty * abs(p.avg_price)
                               for p in b.get_positions().values())
    assert naive < -4000, naive
    assert b.get_equity() - naive > 9000, "the gap the user reported was ~$9,280"


def test_cash_reported_for_display_is_wallet_not_margin_balance():
    """562e620: ccxt maps USDT.total to Binance's MARGIN balance for this account
    type — the same number get_equity() returns. Reading it as cash collapsed
    'invested' (equity - cash) to ~$0 and hid two open positions entirely."""
    snap = _broker(_FLAT_BOOK, _SHORTS).snapshot()
    assert snap["cash"] == 4998.02
    assert snap["cash"] != 5014.87, "cash must exclude unrealized P&L"
    assert len(snap["positions"]) == 2
    # the identity the whole /assets view rests on: cash + net == equity, and
    # net is real unrealized P&L rather than zero
    assert abs(5014.87 - snap["cash"] - 16.85) < 0.01


def test_an_unreadable_balance_raises_rather_than_reporting_zero_equity():
    """A zero equity is indistinguishable from an empty account and gets written
    to a state file as fact — §4.7, where an outage priced a book at zero and it
    was flattened against a number that never happened."""
    b = _broker({"info": {}, "USDT": {"free": 340.0}})
    try:
        b.get_equity()
    except RuntimeError as exc:
        assert "unreadable" in str(exc)
    else:
        raise AssertionError("a balance with no equity field must not return 0.0")


def test_a_margined_book_reports_its_exposure_even_with_no_shorts():
    """On a margined book `cash` already contains the margin locked in a
    position, so `equity - cash` is only unrealized P&L. The at-risk clause was
    gated on `shorts > 0`, so a LONG-only futures book (the live ₿ crypto book)
    rendered $4.6k of open position as 'cash $4,998 + $17 invested' — flat."""
    blob = {"equity": 5014.87, "broker": {"cash": 4998.02, "positions": [
        {"symbol": "BTC/USD", "qty": 0.0436, "avg_price": 69529.2, "price": 69915.0}]}}
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "crypto_state.json"), "w") as fh:
            json.dump(blob, fh)
        settings = type("S", (), {})()
        settings.state_path = os.path.join(d, "state.json")
        settings.starting_cash = 10000.0
        settings.invest_starting_cash = 10000.0
        settings.alerts = type("A", (), {"telegram_bot_token": "", "telegram_chat_id": ""})()
        settings.brain = type("B", (), {"state_path": os.path.join(d, "brain.json"),
                                        "advice_path": os.path.join(d, "advice.json")})()
        out = ChatBot(settings)._fmt_assets()
    assert "$3,048 at risk" in out, out          # 0.0436 * 69,915
    assert "$4,998 cash + $17 invested" in out, out   # still reconciles to equity


class _Margined(BrokerAdapter):
    name, live, margined = "fake_futures", True, True

    def __init__(self, long_only=True, leverage=1):
        self.long_only, self.leverage = long_only, leverage

    def get_cash(self):
        return 0.0

    def get_positions(self):
        return {}

    def submit(self, order: Order, price: float) -> Order:
        return order


class _Spot(_Margined):
    margined = False


def test_routing_refuses_a_margined_leg_its_equity_formula_cannot_value():
    """The main trading book values itself through Portfolio.equity(prices) —
    one cash figure across two venues, so it cannot ask get_equity(). The
    reconstruction only survives a margined leg at 1x long-only, and both halves
    of that are one env var away from being false."""
    stock = _Spot()
    RoutingBroker(stock, _Margined(long_only=True, leverage=1))   # today's config: fine
    RoutingBroker(stock, _Spot(long_only=False, leverage=3))      # not margined: not our problem

    for leg, expect in ((_Margined(long_only=False, leverage=1), "can short"),
                        (_Margined(long_only=True, leverage=3), "3x")):
        try:
            RoutingBroker(stock, leg)
        except RuntimeError as exc:
            assert expect in str(exc) and "4.36" in str(exc), str(exc)
        else:
            raise AssertionError(f"expected a refusal for {leg.long_only}/{leg.leverage}x")


def test_the_default_adapter_still_says_it_has_no_venue_equity():
    """get_equity() defaulting to None is what keeps every paper/spot book on the
    reconstruction that is correct for it."""
    assert _Spot().get_equity() is None
    assert RoutingBroker(_Spot(), _Spot()).get_equity() is None, \
        "returning the crypto leg's equity here would drop the stock book"


# ---------------------------------------------------------------------------
# §4.36's REAL fix: Portfolio.equity() blending a venue's own equity with a
# marked stock leg, so leverage and direction stop corrupting the number.
# Until 2026-08-21 this was a startup REFUSAL, not a fix.
# ---------------------------------------------------------------------------
def _blend_case(leverage, wallet, qty, entry, price, stock_cash, stock_qty, stock_px):
    """Build a RoutingBroker-shaped book and value it both ways."""
    from ai_investing.models import Asset, AssetClass, Portfolio, Position

    positions = {
        "crypto:BTC/USD": Position(Asset("BTC/USD", AssetClass.CRYPTO), qty, entry),
        "stock:AAPL": Position(Asset("AAPL", AssetClass.STOCK), stock_qty, 100.0),
    }
    prices = {"crypto:BTC/USD": price, "stock:AAPL": stock_px}

    # what the VENUE says its equity is: wallet + unrealized on the position
    venue_equity = wallet + (price - entry) * qty
    truth = stock_cash + stock_qty * stock_px + venue_equity

    # OLD: one cash figure spanning both venues, everything marked. On a
    # margined venue the initial margin is already locked out of the wallet.
    margin = abs(qty) * entry / leverage
    old = Portfolio(stock_cash + (wallet - margin), positions).equity(prices)
    # NEW: the crypto leg valued by its own venue, its cash excluded from `cash`
    new = Portfolio(stock_cash, positions,
                    venue_equity={AssetClass.CRYPTO: venue_equity}).equity(prices)
    return truth, old, new


def test_the_blend_agrees_where_the_old_formula_happened_to_be_right():
    """1x long-only — the ONE configuration the startup guard permitted. The
    blend must agree with it, or the fix would move a number that was correct."""
    truth, old, new = _blend_case(leverage=1, wallet=5000.0, qty=0.1, entry=60000.0,
                                  price=66000.0, stock_cash=2000.0, stock_qty=10,
                                  stock_px=110.0)
    assert abs(old - truth) < 1e-6, "fixture: the old formula IS right at 1x long"
    assert abs(new - truth) < 1e-6, "and the blend must not move it"


def test_the_blend_is_right_where_leverage_broke_the_old_formula():
    """At 2x, half the notional is added back that was never deducted."""
    truth, old, new = _blend_case(leverage=2, wallet=5000.0, qty=0.1, entry=60000.0,
                                  price=66000.0, stock_cash=2000.0, stock_qty=10,
                                  stock_px=110.0)
    assert abs(new - truth) < 1e-6, "the blend is correct at 2x"
    assert old - truth > 2_900, f"fixture: old overstates by {old - truth:,.0f}"


def test_the_blend_is_right_on_a_short_the_old_formula_double_counted():
    """The -$4,265-on-a-flat-book signature: margin locked (cash down) AND
    qty*price negative, so the notional is subtracted twice."""
    truth, old, new = _blend_case(leverage=1, wallet=5000.0, qty=-0.1, entry=60000.0,
                                  price=57000.0, stock_cash=2000.0, stock_qty=10,
                                  stock_px=110.0)
    assert abs(new - truth) < 1e-6, "the blend is correct on a short"
    assert truth - old > 11_000, f"fixture: old understates by {truth - old:,.0f}"


def test_exposure_is_not_reduced_by_the_override():
    """Equity is what margin distorts; exposure is not. A margined position's
    exposure is its NOTIONAL, which is what the risk layer needs — hiding it is
    §4.36's third defect (`/assets` under-reporting a long-only margined book)."""
    from ai_investing.models import Asset, AssetClass, Portfolio, Position
    pos = {"crypto:BTC/USD": Position(Asset("BTC/USD", AssetClass.CRYPTO), 0.1, 60000.0)}
    p = Portfolio(0.0, pos, venue_equity={AssetClass.CRYPTO: 5000.0})
    assert abs(p.exposure({"crypto:BTC/USD": 66000.0}) - 6600.0) < 1e-6


def test_a_book_with_no_margined_leg_values_exactly_as_before():
    from ai_investing.models import Asset, AssetClass, Portfolio, Position
    pos = {"stock:AAPL": Position(Asset("AAPL", AssetClass.STOCK), 10, 100.0)}
    assert Portfolio(2000.0, pos).equity({"stock:AAPL": 110.0}) == 3100.0


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\nAll {len(tests)} margined-equity tests passed.")
