"""Reaching Hong Kong, Singapore and the mainland: symbols, board lots, currency.

For a fortnight the live book traded USD listings only, on two stated grounds
that were both wrong when probed against the account on 2026-08-17:

  - `cost_price` currency was said to be unconverted. It was converted, three
    lines below the docstring that said otherwise.
  - the symbols were said to "only round-trip cleanly for .US". They round-trip
    fine; the WATCHLIST speaks Yahoo (`D05.SI`, `600519.SS`) and Longbridge
    speaks its own dialect (`D05.SG`, `600519.SH`), and an unknown string comes
    back as an empty list rather than an error, so every check answered "no".

116 of the 126 non-USD names resolve once translated, and the account holds
SGD 1,000,000 and HKD 1,000,000 to trade them with. What was actually missing:
the suffix map, board lots, and converting prices back out of USD.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_investing.brokers import symbols as sym
from ai_investing.brokers.live import snap_to_tick, tick_size
from ai_investing.brokers.lots import LotBook
from ai_investing.config import RiskConfig
from ai_investing.models import Asset, AssetClass, Order, Side
from ai_investing.strategy.risk import RiskManager


# ------------------------------------------------------------------ symbols --
def test_the_two_dialects_that_actually_differ():
    assert sym.to_longbridge("D05.SI") == "D05.SG", "Singapore: Yahoo .SI, Longbridge .SG"
    assert sym.to_longbridge("600519.SS") == "600519.SH", "Shanghai: .SS vs .SH"
    assert sym.to_longbridge("AAPL") == "AAPL.US"
    assert sym.to_longbridge("0700.HK") == "0700.HK", "HK already agrees"
    assert sym.to_longbridge("000333.SZ") == "000333.SZ", "so does Shenzhen"


def test_markets_longbridge_does_not_carry_are_unreachable():
    """Probed with every plausible spelling; none resolve."""
    for s in ("005930.KS", "PRX.AS", "6954.T", "2317.TW", "RHM.DE", "AIR.PA"):
        assert sym.to_longbridge(s) is None, f"{s} should be unreachable"
        assert not sym.reachable(s)


def test_crypto_never_goes_to_a_stock_venue():
    assert sym.to_longbridge("BTC/USD") is None


def test_the_map_round_trips_both_ways():
    """A symbol that converts one way but not the other is worse than one that
    never converts: the order goes out fine and the fill comes back under a name
    the engine does not recognise, so it manages a position it believes is
    somebody else's."""
    for w in ("AAPL", "D05.SI", "600519.SS", "0700.HK", "000333.SZ"):
        assert sym.from_longbridge(sym.to_longbridge(w)) == w, w


def test_hk_codes_are_zero_padded_coming_back():
    """Longbridge reports 700.HK; the watchlist holds 0700.HK."""
    assert sym.from_longbridge("700.HK") == "0700.HK"
    assert sym.from_longbridge("2331.HK") == "2331.HK"


def test_non_usd_markets_are_flagged_for_price_conversion():
    assert sym.is_non_usd("0700.HK") and sym.is_non_usd("D05.SI")
    assert not sym.is_non_usd("AAPL")


# --------------------------------------------------------------- board lots --
def _lots(**kw):
    return LotBook("/nonexistent", kw)


def test_us_listings_are_single_shares_without_a_lookup():
    """The US path must not start depending on a cache that might be cold."""
    assert _lots().lot_size("AAPL") == 1
    assert _lots().floor_to_lot("AAPL", 37.9) == 37.0


def test_an_unknown_lot_is_untradable_rather_than_guessed():
    """Guessing 1 sends 37 shares of a 100-lot stock and collects a reject
    forever; guessing 100 multiplies a US order by a hundred."""
    b = _lots()
    assert b.lot_size("0700.HK") is None
    assert b.floor_to_lot("0700.HK", 500.0) == 0.0


def test_orders_floor_to_whole_lots():
    b = _lots(**{"0700.HK": 100, "0669.HK": 500})
    assert b.floor_to_lot("0700.HK", 337.0) == 300.0
    assert b.floor_to_lot("0669.HK", 1499.0) == 1000.0
    assert b.floor_to_lot("0700.HK", 99.0) == 0.0, "under one lot is not tradable"


def test_lots_never_round_up():
    """On a 500-lot stock, rounding up is up to 499 extra shares — not a
    rounding error, and bought with cash no ceiling was checked against."""
    b = _lots(**{"0669.HK": 500})
    assert b.floor_to_lot("0669.HK", 999.9) == 500.0


# ------------------------------------------------- the sizer honours lots ----
def _rm(lots=None):
    return RiskManager(RiskConfig(), lots=lots)


HK = Asset("0700.HK", AssetClass.STOCK)
US = Asset("AAPL", AssetClass.STOCK)


def test_the_sizer_quantises_to_board_lots():
    o = Order(HK, Side.BUY, 337.0, reason="entry")
    out = _rm(_lots(**{"0700.HK": 100}))._quantize_whole_shares(
        [o], {"stock:0700.HK": 57.0}, equity=100_000)
    assert len(out) == 1 and out[0].qty == 300.0, "337 must floor to three lots"


def test_the_sizer_drops_a_buy_whose_one_lot_breaches_the_position_cap():
    """Tencent's 100-share lot is $5,715. On a $10k book at 15% that is 3.8x the
    cap, and the old path shipped it and ate a reject every cycle."""
    o = Order(HK, Side.BUY, 40.0, reason="entry")
    out = _rm(_lots(**{"0700.HK": 100}))._quantize_whole_shares(
        [o], {"stock:0700.HK": 57.0}, equity=10_000)
    assert out == []


def test_the_sizer_bumps_a_sub_lot_buy_when_one_lot_is_affordable():
    """0020.HK's 1000-share lot is $199 — comfortably inside the cap."""
    o = Order(Asset("0020.HK", AssetClass.STOCK), Side.BUY, 300.0, reason="entry")
    out = _rm(_lots(**{"0020.HK": 1000}))._quantize_whole_shares(
        [o], {"stock:0020.HK": 0.2}, equity=10_000)
    assert len(out) == 1 and out[0].qty == 1000.0
    assert "1000-share lot min" in out[0].reason


def test_us_orders_are_unchanged_with_a_lot_book_attached():
    """The book that already works must not move because another one widened."""
    o = Order(US, Side.BUY, 3.9, reason="add")
    out = _rm(_lots())._quantize_whole_shares([o], {"stock:AAPL": 70.0}, equity=10_000)
    assert len(out) == 1 and out[0].qty == 3.0


def test_an_exit_is_never_blocked_by_an_unknown_lot():
    """Protection must never be gated on bookkeeping. An unknown lot excludes a
    name from ENTRY; a position already held still has to be able to get out."""
    o = Order(HK, Side.SELL, 300.0, reason="stop")
    out = _rm(_lots())._quantize_whole_shares(
        [o], {"stock:0700.HK": 57.0}, equity=10_000)
    assert len(out) == 1 and out[0].side is Side.SELL and out[0].qty == 300.0


# ------------------------------------------------------- ticks and currency --
def test_hk_uses_the_hkex_spread_table_not_a_penny():
    assert tick_size("0700.HK", 448.0) == 0.2, "HKD 200-500 band"
    assert tick_size("0020.HK", 1.56) == 0.01, "HKD 0.50-10 band"
    assert tick_size("0020.HK", 0.30) == 0.005, "HKD 0.25-0.50 band"
    assert tick_size("D05.SG", 40.0) == 0.01
    assert tick_size("AAPL.US", 275.9) == 0.01


def test_a_snapped_limit_never_becomes_more_aggressive():
    assert snap_to_tick(448.37, "0700.HK", Side.BUY) <= 448.37
    assert snap_to_tick(448.37, "0700.HK", Side.SELL) >= 448.37


def test_usd_prices_are_converted_back_to_the_listing_currency():
    """THE ONE THAT LOSES MONEY. Bars are USD-normalised on the way in, so a
    limit price sent back out is in the wrong units. A SELL limit priced in USD
    against an HKD listing sits ~7.8x below the market and fills instantly at
    the worst price on the book."""
    from ai_investing.data import fx

    class S:
        state_path = "/nonexistent/state.json"
    fx._mem.update(ts=9e18, rates={"HKD": 7.8, "SGD": 1.28})   # freeze the cache
    try:
        assert abs(fx.from_usd(57.49, "0700.HK", S()) - 448.4) < 0.5
        assert abs(fx.from_usd(31.25, "D05.SI", S()) - 40.0) < 0.5
        assert fx.from_usd(275.9, "AAPL", S()) == 275.9, "USD stays put"
        # and it must be the exact inverse of the way in
        assert abs(fx.from_usd(fx.to_usd(448.4, "0700.HK", S()), "0700.HK", S())
                   - 448.4) < 1e-6
    finally:
        fx._mem.update(ts=0.0, rates={})


# ------------------------------------- a fill price is money crossing in ----
def test_a_foreign_fill_price_is_converted_on_the_way_back_in():
    """THE ONE THAT ACTUALLY HAPPENED. The first Hong Kong order this engine
    placed — 100 shares of 3690.HK for HKD 8,870, about USD 1,129 — was booked
    into a USD ledger at a cost basis of 8,870. Cash fell by seven times what
    was spent, equity read $2,256 against a true $10,000, and the daily notional
    cap, the drawdown breaker and the learning spine all inherited it."""
    from ai_investing.brokers.live import LongbridgeBroker
    from ai_investing.data import fx

    class Detail:
        status, executed_quantity, executed_price, symbol = "Filled", 100, 88.70, "3690.HK"

    class Ctx:
        def order_detail(self, oid):
            return Detail()

    class S:
        state_path = "/nonexistent/state.json"
        base_currency = "USD"

    b = LongbridgeBroker.__new__(LongbridgeBroker)   # no network, no channel check
    b.ctx, b.settings = Ctx(), S()
    fx._mem.update(ts=9e18, rates={"HKD": 7.85})
    try:
        status, qty, px = b.fetch_fill("any")
        assert qty == 100
        assert abs(px - 11.30) < 0.05, f"HKD 88.70 must come back as ~USD 11.30, got {px}"
    finally:
        fx._mem.update(ts=0.0, rates={})


def test_a_us_fill_price_is_untouched():
    from ai_investing.brokers.live import LongbridgeBroker

    class Detail:
        status, executed_quantity, executed_price, symbol = "Filled", 5, 275.90, "AAPL.US"

    class Ctx:
        def order_detail(self, oid):
            return Detail()

    class S:
        state_path = "/nonexistent/state.json"
        base_currency = "USD"

    b = LongbridgeBroker.__new__(LongbridgeBroker)
    b.ctx, b.settings = Ctx(), S()
    assert b.fetch_fill("any")[2] == 275.90


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"test_venue_reach: all {len(fns)} passed")
