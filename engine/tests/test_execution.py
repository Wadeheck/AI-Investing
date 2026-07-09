"""Tests for limit-order price protection and the native-stop hook."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_investing.brokers.paper import PaperBroker
from ai_investing.models import Asset, AssetClass, Order, OrderType, Side


def _asset():
    return Asset("X", AssetClass.STOCK)


def test_limit_buy_fills_within_limit():
    b = PaperBroker(10_000)
    o = Order(_asset(), Side.BUY, 10, order_type=OrderType.LIMIT, limit_price=105.0)
    b.submit(o, 104.0)                 # market within the limit
    assert o.status.value == "filled" and o.filled_price == 104.0
    assert b.get_cash() == 10_000 - 1040


def test_limit_buy_rejects_above_limit():
    b = PaperBroker(10_000)
    o = Order(_asset(), Side.BUY, 10, order_type=OrderType.LIMIT, limit_price=105.0)
    b.submit(o, 106.0)                 # market above the limit -> no fill (price protection)
    assert o.status.value == "rejected" and not b.get_positions()
    assert b.get_cash() == 10_000


def test_limit_sell_rejects_below_fills_above():
    b = PaperBroker(10_000)
    b.submit(Order(_asset(), Side.BUY, 10), 100.0)     # open a long (market)
    low = Order(_asset(), Side.SELL, 10, order_type=OrderType.LIMIT, limit_price=110.0)
    b.submit(low, 109.0)              # below limit -> no fill, still holding
    assert low.status.value == "rejected" and b.get_positions()
    high = Order(_asset(), Side.SELL, 10, order_type=OrderType.LIMIT, limit_price=110.0)
    b.submit(high, 111.0)             # above limit -> fill
    assert high.status.value == "filled" and not b.get_positions()


def test_market_order_unaffected():
    b = PaperBroker(10_000)
    o = Order(_asset(), Side.BUY, 5)  # default market order
    b.submit(o, 200.0)
    assert o.status.value == "filled"


def test_place_stop_default_none():
    assert PaperBroker(10_000).place_stop(_asset(), Side.SELL, 5, 90.0) is None


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\nAll {len(tests)} execution tests passed.")
