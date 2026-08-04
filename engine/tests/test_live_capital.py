"""LIVE_CAPITAL_BASE: trading a bounded slice of a much larger live account.

The Longbridge paper account holds USD 1,000,000; the intent is to risk USD
10,000. Attached directly, every percentage limit in the engine is measured
against the wrong denominator — so these tests are about one question: does the
safety layer see the money actually at risk?
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_investing.config import SafetyConfig, Settings
from ai_investing.execution.capital import BookLedger, own_positions
from ai_investing.models import Asset, AssetClass, Position
from ai_investing.safety.circuit_breaker import CircuitBreaker

A = Asset("AAPL", AssetClass.STOCK)
B = Asset("MSFT", AssetClass.STOCK)


def _pos(asset, qty, avg):
    return {asset.key: Position(asset, qty, avg)}


def test_the_slice_is_the_book_not_the_account():
    led = BookLedger(base=10_000.0)
    book = led.book_portfolio({})
    assert book.cash == 10_000.0
    assert book.equity({}) == 10_000.0, \
        "an untouched slice is worth exactly the capital committed to it"

    # buy 50 AAPL at 100 = $5,000 deployed
    led2 = BookLedger(base=10_000.0)
    book = led2.book_portfolio(_pos(A, 50, 100.0))
    assert book.cash == 5_000.0, "cash must fall by cost, not by the account's cash"
    assert book.equity({A.key: 100.0}) == 10_000.0, "flat trade, flat book"
    assert book.equity({A.key: 110.0}) == 10_500.0, "+10% on half the book = +5%"
    assert book.equity({A.key: 90.0}) == 9_500.0


def test_a_short_raises_cash_in_the_slice_too():
    """§4.7 was a short valued at zero collapsing equity to cash. The slice must
    account for shorts the same way the paper broker does, or the bug returns in
    a book where the numbers are 100x smaller and easier to miss."""
    led = BookLedger(base=10_000.0)
    book = led.book_portfolio(_pos(A, -100, 20.0))     # short 100 @ 20 = +$2,000 cash
    assert book.cash == 12_000.0
    assert book.equity({A.key: 20.0}) == 10_000.0
    assert book.equity({A.key: 18.0}) == 10_200.0, "short profits as price falls"
    assert book.equity({A.key: 22.0}) == 9_800.0


def test_the_breaker_measures_the_slice_and_actually_fires():
    """The reason this feature exists.

    On the raw account a $600 loss is 0.06% and nothing happens. On the slice it
    is 6% and the daily breaker halts. Same trade, same account, same limits —
    only the denominator differs, and the denominator is the whole safeguard.
    """
    fd, path = tempfile.mkstemp(suffix=".json"); os.close(fd); os.unlink(path)
    cb = CircuitBreaker(SafetyConfig(), 0.05, path)      # 5% daily

    led = BookLedger(base=10_000.0)
    positions = _pos(A, 100, 50.0)                        # $5,000 deployed

    assert cb.check(led.book_portfolio(positions).equity({A.key: 50.0})).allow_new

    # AAPL 50 -> 44: -$600 on the slice
    hurt = led.book_portfolio(positions).equity({A.key: 44.0})
    assert hurt == 9_400.0
    assert cb.check(hurt).flatten, "-6% on the slice must halt"

    # the same $600 against the whole account would not have registered
    account_equity = 1_000_000.0 - 600.0
    fd, p2 = tempfile.mkstemp(suffix=".json"); os.close(fd); os.unlink(p2)
    cb2 = CircuitBreaker(SafetyConfig(), 0.05, p2)
    cb2.check(1_000_000.0)
    assert not cb2.check(account_equity).flatten, \
        "sanity: this is the blindness the slice exists to remove"


def test_realised_pnl_survives_a_close_and_a_restart():
    """A closed trade's cost basis is only knowable before the position shrinks —
    the broker stops reporting it afterwards. If the ledger misses the cycle, that
    P&L is gone permanently and the book silently reverts toward its base."""
    led = BookLedger(base=10_000.0)
    led.observe(_pos(A, 100, 50.0), {A.key: 50.0})        # opened
    assert led.realized == 0.0

    led.observe({}, {A.key: 60.0})                        # closed at 60
    assert round(led.realized, 2) == 1_000.0, "100 x (60-50)"
    assert led.book_portfolio({}).equity({}) == 11_000.0, \
        "realised gains must persist in equity once the position is gone"

    # restart: base comes from config, realised from disk
    revived = BookLedger.from_dict(led.to_dict(), 10_000.0)
    assert revived.realized == led.realized
    assert revived.book_portfolio({}).equity({}) == 11_000.0

    # and changing the setting must win over the persisted value
    resized = BookLedger.from_dict(led.to_dict(), 25_000.0)
    assert resized.base == 25_000.0, "LIVE_CAPITAL_BASE must not be overridden by state"


def test_partial_exit_and_short_close_book_correctly():
    led = BookLedger(base=10_000.0)
    led.observe(_pos(A, 100, 50.0), {A.key: 50.0})
    led.observe(_pos(A, 40, 50.0), {A.key: 55.0})          # sold 60 @ 55
    assert round(led.realized, 2) == 300.0                 # 60 x 5

    short = BookLedger(base=10_000.0)
    short.observe(_pos(B, -50, 20.0), {B.key: 20.0})
    short.observe({}, {B.key: 18.0})                       # bought back at 18
    assert round(short.realized, 2) == 100.0, "-50 x (18-20) = +100 on a short"


def test_a_missing_exit_price_is_never_booked_as_flat():
    """§4.10's lesson inside the ledger: a price that isn't there is not a
    valuation. Booking a close at cost basis would record a real gain or loss as
    zero and the ledger would drift from the account permanently."""
    for bad in (0.0, None, float("nan"), float("-inf"), "x"):
        led = BookLedger(base=10_000.0)
        led.observe(_pos(A, 100, 50.0), {A.key: 50.0})
        led.observe({}, {A.key: bad})
        assert led.realized == 0.0, f"exit price {bad!r} must not book P&L"


def test_only_positions_in_the_mandate_enter_the_slice():
    """The account may hold anything. §4.13 — the slice counts only what this
    engine has a mandate over, or a foreign holding would inflate its equity and
    loosen every limit derived from it."""
    universe = {A.key}
    account = {**_pos(A, 10, 100.0), **_pos(B, 500, 300.0)}   # MSFT is not ours
    own = own_positions(account, universe)
    assert set(own) == {A.key}

    led = BookLedger(base=10_000.0)
    book = led.book_portfolio(own)
    assert book.cash == 9_000.0, "only AAPL's $1,000 cost may be deducted"
    assert book.equity({A.key: 100.0, B.key: 300.0}) == 10_000.0, \
        "a $150,000 foreign holding must not appear in a $10,000 book"


def test_the_setting_is_off_by_default():
    s = Settings()
    assert s.live_capital_base == 0.0, \
        "capping must be opt-in; existing paper behaviour is unchanged"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\nAll {len(tests)} live-capital tests passed.")
