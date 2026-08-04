"""Longbridge symbol and currency mapping — the boundary where the engine's world
meets the broker's.

Every bug in this file's history has been a string or a unit: a symbol that looked
equal to a human and wasn't, or a price in the wrong currency. Nothing here needs
a network, so it is cheap to keep honest.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_investing.brokers.live import LongbridgeBroker


def test_symbols_round_trip_to_the_form_the_watchlist_uses():
    w = LongbridgeBroker.watchlist_symbol

    # US: the watchlist says AAPL, the broker says AAPL.US
    assert w("AAPL.US") == "AAPL"
    assert w("BRK-B.US") == "BRK-B"

    # HK: the broker says 700.HK, the watchlist says 0700.HK. A dict lookup does
    # not care that a human can see these are the same instrument — before this,
    # the engine classed its own HK holdings as another account's and would never
    # have exited them.
    assert w("700.HK") == "0700.HK"
    assert w("9988.HK") == "9988.HK"
    assert w("0700.HK") == "0700.HK", "already-padded must be left alone"
    assert w("3690.HK") == "3690.HK"

    # the original bug: split(".")[0] destroyed every non-US symbol
    assert w("700.HK") != "700"

    # markets with no rule stay untouched rather than being mangled
    for s in ("D05.SI", "600519.SS", "9984.T", "005930.KS", "MC.PA"):
        assert w(s) == s
    assert w("") == "" and w(None) == ""


def test_a_position_cost_is_converted_out_of_the_listing_currency():
    """§4.2's third appearance. cost_price arrives in the listing currency while
    every price here is USD-normalised, so an HK basis compared against a USD mark
    is the error that once read SK Hynix at $1.59M a share."""
    from ai_investing.config import Settings
    from ai_investing.data import fx

    s = Settings()
    rates = fx.rates(s) or {}
    hkd = rates.get("HKD")
    if not hkd:
        return                      # no cached rates in this environment

    # a HK$390 basis is not $390
    usd = fx.to_usd(390.0, "0700.HK", s)
    assert usd < 390.0 and abs(usd - 390.0 / hkd) < 1e-6
    # a US listing must not be touched
    assert fx.to_usd(390.0, "AAPL", s) == 390.0
    # an unknown rate returns the amount unchanged, never zero (§4.10)
    assert fx.to_usd(390.0, "XYZ.ZZ", s) == 390.0


def test_fill_confirmation_never_invents_a_price():
    """submit() once set filled_price to the mark it was handed and marked the order
    FILLED without asking the broker. Proven live on 2026-08-04: passing price=0.0
    produced 'status filled, 1 share @ $0.00' while the real fill was $13.99."""
    import inspect

    def code_only(fn):
        """Comments quote the OLD buggy lines on purpose, so strip them before
        asserting on what the function actually executes."""
        return "\n".join(l for l in inspect.getsource(fn).splitlines()
                          if not l.strip().startswith("#"))

    src = code_only(LongbridgeBroker.submit)
    assert "self._confirm(" in src, "submit must confirm against the broker"
    assert "order.status = OrderStatus.FILLED" not in src, \
        "submit must not declare a fill itself — _confirm decides from order_detail"
    assert "order.filled_qty = float(qty)" not in src, \
        "submit must not assume the submitted quantity was the filled quantity"

    csrc = code_only(LongbridgeBroker._confirm)
    assert "order_detail" in csrc, "the fill must come from the broker, not the caller"
    # terminal states live on the class, so assert on them there rather than by
    # grepping a function body
    assert LongbridgeBroker._TERMINAL_FILLED == {"Filled"}
    assert {"Rejected", "Canceled", "Expired"} <= LongbridgeBroker._TERMINAL_DEAD, \
        "a dead order must never be booked as a fill"
    assert "Filled" not in LongbridgeBroker._TERMINAL_DEAD


def test_the_venue_exits_use_the_right_order_types():
    """MIT for the stop, LIT for the take-profit. A limit-if-touched stop can be
    skipped straight through in the fast move a stop exists for; an un-executed
    stop is not a stop. Verified against the live paper account 2026-08-04."""
    import inspect
    def body(fn):
        """Docstrings name the rejected alternatives deliberately; assert on code."""
        src = inspect.getsource(fn)
        # drop the docstring block
        parts = src.split('"""')
        return parts[0] + ("".join(parts[2:]) if len(parts) > 2 else "")

    stop = body(LongbridgeBroker.place_stop)
    tp = body(LongbridgeBroker.place_take_profit)
    assert "OrderType.MIT" in stop and "trigger_price" in stop
    assert "OrderType.LIT" in tp and "submitted_price" in tp
    assert "TSLP" not in stop, \
        "a trailing stop would move the exit away from the level the position was " \
        "sized against and from the claim the learning ledger recorded"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\nAll {len(tests)} live-broker mapping tests passed.")
