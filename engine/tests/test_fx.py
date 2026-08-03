"""Currency contract: one book, one unit.

Written after the engine spent weeks summing HKD, KRW and USD as if they were
the same currency. SK Hynix at 1,591,000 KRW was read as $1,591,000 a share, so
the sizer bought a thousandth of a share and booked it as a $1,588 position
worth $1.15. Across the trading book that misstated $9,038 of $16,027 net
exposure, and the event sleeve believed it had $3,333 left when it held
$87,671 -- it had stopped trading for lack of money it actually had.

These tests are pure: no network, no live rates.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai_investing.data import fx  # noqa: E402


class _S:
    state_path = "/tmp/ai-investing-fxtest/state.json"


def _with_rates(rates):
    fx._mem.update(ts=float("inf"), rates=rates)
    return _S()


def test_currency_is_derived_from_the_exchange_suffix():
    assert fx.currency_of("0700.HK") == "HKD"
    assert fx.currency_of("000660.KS") == "KRW"
    assert fx.currency_of("7203.T") == "JPY"
    assert fx.currency_of("PRX.AS") == "EUR"
    assert fx.currency_of("MSFT") == "USD"


def test_crypto_is_already_usd_and_must_not_be_converted():
    """Crypto pairs are USD-quoted; converting them would corrupt the one book
    that was never broken."""
    assert fx.currency_of("BTC/USD", "crypto") == "USD"
    s = _with_rates({"HKD": 7.84})
    assert fx.to_usd(63000.0, "BTC/USD", s, "crypto") == 63000.0


def test_the_bug_that_started_this():
    s = _with_rates({"KRW": 1429.0})
    usd = fx.to_usd(1_591_000.0, "000660.KS", s)
    assert 1000 < usd < 1300, f"SK Hynix is ~$1,100 a share, not ${usd:,.0f}"


def test_conversion_direction_holds_for_currencies_stronger_than_the_dollar():
    """EUR trades below 1 per USD, so the same divide must make the price
    LARGER. A sign or inversion error would only show up here."""
    s = _with_rates({"EUR": 0.87})
    assert fx.to_usd(39.97, "PRX.AS", s) > 39.97


def test_us_symbols_are_untouched():
    s = _with_rates({"HKD": 7.84})
    assert fx.to_usd(464.53, "MSFT", s) == 464.53
    assert fx.rate_for("MSFT", s) is None


def test_a_missing_rate_leaves_the_price_alone_rather_than_zeroing_it():
    """Unknown rate must degrade to 'unconverted', never to 0 or a crash: a
    zero price would trip stops and liquidate a position on a data gap.

    The cache is populated but lacks HKD -- an empty cache would (correctly)
    trigger a refetch, which is not what this test is about.
    """
    s = _with_rates({"KRW": 1429.0})
    assert fx.rate_for("2097.HK", s) is None
    assert fx.to_usd(226.03, "2097.HK", s) == 226.03


def test_zero_and_negative_rates_are_refused():
    s = _with_rates({"HKD": 0.0})
    assert fx.to_usd(226.03, "2097.HK", s) == 226.03


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok  {name}")
            except AssertionError as exc:
                fails += 1
                print(f"  FAIL {name}: {exc}")
    print("All FX tests passed." if not fails else f"{fails} failed")
    sys.exit(1 if fails else 0)
