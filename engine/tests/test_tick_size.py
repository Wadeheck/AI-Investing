"""Limit prices must land on a legal tick.

Longbridge rejects an off-tick limit with code 602035, "Wrong bid size, please
change the price". The adapter sent `round(limit_price, 3)`, so a US limit was
legal only when its third decimal happened to be zero — roughly one attempt in
ten, and the live record bears that out exactly: eight rejections and one fill
between 2026-08-05 and 2026-08-10.

Confirmed against the paper account on 2026-08-10 with two orders identical in
symbol, side, quantity and second, differing only in the third decimal:

    AAPL.US BUY 1 @ 275.90   -> ACCEPTED
    AAPL.US BUY 1 @ 275.903  -> REJECTED 602035
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ai_investing.brokers.live import snap_to_tick, tick_size
from ai_investing.models import Side

BUY, SELL = Side.BUY, Side.SELL


def _legal(price, symbol):
    """Is `price` an exact multiple of the symbol's tick at that price?"""
    t = tick_size(symbol, price)
    steps = price / t
    return abs(steps - round(steps)) < 1e-6


def test_the_exact_price_the_venue_rejected_is_now_legal():
    got = snap_to_tick(275.903, "AAPL.US", BUY)
    assert got == 275.90, got
    assert _legal(got, "AAPL.US")


def test_a_price_already_on_tick_is_left_alone():
    """The float boundary matters: 275.90/0.01 is 27589.999... in binary, and a
    naive floor would shift a perfectly legal price down by a whole tick."""
    for px in (275.90, 306.94, 1.00, 71.68, 999.99):
        assert snap_to_tick(px, "AAPL.US", BUY) == px, px
        assert snap_to_tick(px, "AAPL.US", SELL) == px, px


def test_snapping_never_makes_an_order_more_aggressive():
    """A buy must not quietly round UP to a price we did not agree to pay."""
    assert snap_to_tick(275.907, "AAPL.US", BUY) == 275.90
    assert snap_to_tick(275.903, "AAPL.US", SELL) == 275.91
    assert snap_to_tick(275.901, "AAPL.US", BUY) <= 275.901
    assert snap_to_tick(275.909, "AAPL.US", SELL) >= 275.909


def test_us_sub_dollar_names_keep_four_decimals():
    """A penny tick on a $0.40 stock would be a 2.5% jump."""
    assert tick_size("XYZ.US", 0.40) == 0.0001
    assert snap_to_tick(0.40567, "XYZ.US", BUY) == 0.4056


def test_hk_uses_the_exchange_spread_table_not_a_penny():
    """HKEX ticks widen with price; a flat penny is illegal above HK$10."""
    assert tick_size("0700.HK", 5.00) == 0.010
    assert tick_size("0700.HK", 15.00) == 0.020
    assert tick_size("0700.HK", 55.00) == 0.050
    assert tick_size("0700.HK", 350.00) == 0.200
    assert tick_size("0700.HK", 0.30) == 0.005
    # 1.8981 was a real 2331.HK mark; the legal tick there is a cent
    assert snap_to_tick(1.8981, "2331.HK", BUY) == 1.89
    # and a mid-band name snaps to the 0.05 grid, not to a penny
    assert snap_to_tick(55.07, "0700.HK", BUY) == 55.05
    assert snap_to_tick(55.07, "0700.HK", SELL) == 55.10


def test_singapore_and_unknown_markets_are_never_finer_than_a_cent():
    """Too coarse shifts a price by one tick; too fine is what cost eight orders,
    so an unrecognised market defaults to the coarser side."""
    assert tick_size("D05.SI", 35.0) == 0.01
    assert tick_size("D05.SI", 0.5) == 0.001
    assert tick_size("FOO.XYZ", 50.0) == 0.01
    assert snap_to_tick(35.007, "D05.SI", BUY) == 35.00


def test_every_snapped_price_is_legal_across_a_sweep():
    """The property that actually matters, over prices no hand-written case
    would think to include."""
    for sym in ("AAPL.US", "0700.HK", "2331.HK", "D05.SI", "FOO.XYZ"):
        px = 0.13
        while px < 3000:
            for side in (BUY, SELL):
                got = snap_to_tick(px, sym, side)
                assert _legal(got, sym), f"{sym} {px} -> {got} is off-tick"
                assert abs(got - px) <= tick_size(sym, px) + 1e-9
            px *= 1.7


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\nAll {len(tests)} tick-size tests passed.")
