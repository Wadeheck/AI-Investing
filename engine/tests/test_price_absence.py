"""A missing price is an ABSENT KEY, not a zero. §4.7's root cause, removed.

The runner used to build prices as `b[-1].close if b else 0.0`. That sentinel
means "absent" and reads as "free", and 0.0 is a perfectly good number to
multiply by a quantity:

  - 2026-08-03: a yfinance rate-limit returned "possibly delisted" for EVERY
    symbol, the whole book valued at zero, and equity read $116,027 against a
    real ~$129k.
  - 2026-08-04: the same shape faked a 13.8% crash and flattened a healthy book.

Since then it was CONTAINED by `mark_price()` at every consumer — which works
only for as long as every new consumer remembers. §4B's instruction was to
remove it at the source before the non-USD gate lifts, because a new market
multiplies the consumers it can reach.

Two properties, and the second is the one that made this change dangerous to
ship naively: an absent price must not be usable as a number, AND it must still
be loud. Omitting the key gets the first for free and would have silently lost
the second — a feed outage that produces no keys produces no guard messages.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_investing.models import Asset, AssetClass, Portfolio, Position, mark_price
from ai_investing.safety.data_guard import DataGuard

_CFG = SimpleNamespace(max_price_jump=0.5, max_bar_staleness_days=5)


def _bar(close):
    return SimpleNamespace(close=close, volume=1000.0, ts=None)


def _build_prices(bars_by_key):
    """The runner's rule, kept here so the test pins the RULE, not a copy."""
    return {k: b[-1].close for k, b in bars_by_key.items() if b}


def test_a_missing_bar_produces_no_key_at_all():
    bars = {"stock:AAPL": [_bar(190.0)], "stock:MSFT": []}
    prices = _build_prices(bars)
    assert prices == {"stock:AAPL": 190.0}
    assert "stock:MSFT" not in prices, "absent, not zero"
    assert prices.get("stock:MSFT") is None


def test_an_absent_price_cannot_be_multiplied_by_a_quantity():
    """The whole point. 0.0 * 100 shares = a plausible-looking $0; None * 100
    raises. A valuation that cannot be computed must not look computed."""
    prices = _build_prices({"stock:MSFT": []})
    px = prices.get("stock:MSFT")
    try:
        _ = 100 * px
        raise AssertionError("an absent price must not behave like a number")
    except TypeError:
        pass


def test_a_position_with_no_price_is_still_valued_at_cost_not_at_zero():
    """§4.10's shared valuation rule still applies — the book keeps the position
    at the last price anyone actually paid, so an outage reads as 'no change'
    rather than as a collapse."""
    pos = {"stock:MSFT": Position(Asset("MSFT", AssetClass.STOCK), 10, 480.0)}
    prices = _build_prices({"stock:MSFT": []})
    assert Portfolio(1000.0, pos).equity(prices) == 1000.0 + 10 * 480.0
    assert mark_price(prices.get("stock:MSFT"), 480.0) == 480.0


def test_a_total_feed_outage_is_still_LOUD():
    """The regression this change could easily have shipped: no keys, no
    iteration, no messages — a blanket outage passing silently, which is the
    same failure §4.7 was, with the opposite sign."""
    bars = {"stock:AAPL": [], "stock:MSFT": [], "crypto:BTC/USD": []}
    prices = _build_prices(bars)
    assert prices == {}
    bad, messages = DataGuard(_CFG).check(prices, bars)
    assert bad == set(bars), "every expected symbol must be flagged"
    assert all("no price this cycle" in m for m in messages)


def test_a_partial_outage_flags_only_the_missing_ones():
    bars = {"stock:AAPL": [_bar(190.0)], "stock:MSFT": []}
    bad, messages = DataGuard(_CFG).check(_build_prices(bars), bars)
    assert bad == {"stock:MSFT"}
    assert len(messages) == 1


def test_a_zero_that_does_arrive_is_still_caught():
    """Belt and braces: a provider that hands back a genuine 0.0 close (rather
    than no bar) must still be refused by the non-positive check."""
    bad, messages = DataGuard(_CFG).check({"stock:AAPL": 0.0},
                                          {"stock:AAPL": [_bar(0.0)]})
    assert bad == {"stock:AAPL"}
    assert any("non-positive" in m for m in messages)


def test_decision_guards_still_skip_an_absent_price():
    """`if not px: continue` is the correct way to refuse to ACT on a bad price,
    and it must keep working — None is falsy exactly as 0.0 was."""
    prices = _build_prices({"stock:AAPL": [_bar(190.0)], "stock:MSFT": []})
    acted = [k for k in ("stock:AAPL", "stock:MSFT") if prices.get(k)]
    assert acted == ["stock:AAPL"]


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\nAll {len(tests)} price-absence tests passed.")
