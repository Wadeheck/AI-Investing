"""Whole-share quantisation at the sizer (regression for the USO re-entry loop).

Until 2026-08-12 the only place shares were rounded was the broker adapter:

    qty = int(order.qty)
    if qty <= 0: reject "qty < 1 share"

That truncation is correct — Longbridge cannot take 0.71 shares — but it ran
AFTER sizing, so the sizer emitted the same sub-share order every cycle and
collected the same reject forever. Two gates contradicted each other: minimum
trade is 0.5% of equity ($50 on a $10k book), while ONE share of a $70 stock
costs $70. Anything priced above the minimum-trade notional could size to
"0.71 shares", pass the notional gate, and truncate to zero.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_investing.config import RiskConfig
from ai_investing.models import Asset, AssetClass, Order, Portfolio, Side
from ai_investing.strategy.risk import RiskManager


def _rm():
    return RiskManager(RiskConfig())


def _stock(sym="USO"):
    return Asset(sym, AssetClass.STOCK)


def test_sub_share_buy_becomes_one_share_not_a_reject():
    """The exact USO case: $50 of a $70 stock is 0.71 shares -> must become 1."""
    rm = _rm()
    o = Order(_stock(), Side.BUY, 50.0 / 70.0, reason="re-entry")
    out = rm._quantize_whole_shares([o], {"stock:USO": 70.0}, equity=10_000)
    assert len(out) == 1, "an affordable sub-share buy must survive, not vanish"
    assert out[0].qty == 1.0, f"expected 1 whole share, got {out[0].qty}"
    assert "1-share min" in out[0].reason


def test_fractional_buy_floors_to_whole_shares():
    rm = _rm()
    o = Order(_stock(), Side.BUY, 3.9, reason="add")
    out = rm._quantize_whole_shares([o], {"stock:USO": 70.0}, equity=10_000)
    assert out[0].qty == 3.0, "3.9 shares must floor to 3, never round up to 4"


def test_one_share_over_the_position_cap_is_dropped_not_retried():
    """A $9,000 share on a $10k book breaches max_position_weight (15%).
    The old path shipped it to the broker and ate a reject every cycle."""
    rm = _rm()
    o = Order(_stock("BRK-A"), Side.BUY, 0.4, reason="expensive")
    out = rm._quantize_whole_shares([o], {"stock:BRK-A": 9_000.0}, equity=10_000)
    assert out == [], "an unaffordable single share must be dropped at the sizer"


def test_sells_are_never_bumped_or_blocked():
    """Protection must not depend on affordability. A stock position is already
    integral, so flooring an exit is a no-op — but it must never become a BUY
    of one share, and a genuine exit must always pass through."""
    rm = _rm()
    sell = Order(_stock(), Side.SELL, 7.0, reason="stop")
    out = rm._quantize_whole_shares([sell], {"stock:USO": 70.0}, equity=10_000)
    assert len(out) == 1 and out[0].qty == 7.0 and out[0].side is Side.SELL


def test_crypto_stays_fractional():
    rm = _rm()
    o = Order(Asset("BTC/USD", AssetClass.CRYPTO), Side.BUY, 0.0031, reason="dca")
    out = rm._quantize_whole_shares([o], {"crypto:BTC/USD": 60_000.0}, equity=10_000)
    assert len(out) == 1 and abs(out[0].qty - 0.0031) < 1e-12, \
        "crypto is genuinely fractional and must not be rounded"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"test_whole_shares: all {len(fns)} passed")
