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


def test_proposal_book_lifecycle():
    import tempfile, os
    from ai_investing.execution.approvals import ProposalBook
    path = os.path.join(tempfile.mkdtemp(), "proposals.json")
    book = ProposalBook(path, ttl_hours=12)
    # propose is idempotent per symbol+side while fresh
    p1 = book.propose("NVDA", "buy", 3.0, 180.0, "momentum+field")
    p2 = book.propose("NVDA", "buy", 4.0, 181.0, "different sizing, same idea")
    assert p1["id"] == p2["id"] and p1["status"] == "pending"
    assert [q["id"] for q in book.pending()] == [p1["id"]]
    # a pending proposal blocks execution; approval enables exactly one entry
    assert book.get("NVDA", "buy")["status"] == "pending"
    assert book.decide("nope1234", True) is None          # unknown id
    assert book.decide(p1["id"], True)["status"] == "approved"
    assert book.decide(p1["id"], True) is None            # can't re-decide
    assert book.get("NVDA", "buy")["status"] == "approved"
    book.consume(p1["id"])
    assert book.get("NVDA", "buy") is None                # consumed -> can re-propose
    # rejection sticks (no nagging) until expiry
    p3 = book.propose("TSLA", "sell", 1.0, 300.0)
    book.decide(p3["id"], False)
    assert book.get("TSLA", "sell")["status"] == "rejected"
    assert book.pending() == []
    # expired proposals vanish
    expired = ProposalBook(path, ttl_hours=-1)
    expired.propose("AAPL", "buy", 1.0, 200.0)
    expired.prune()
    assert expired.get("AAPL", "buy") is None


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\nAll {len(tests)} execution tests passed.")
