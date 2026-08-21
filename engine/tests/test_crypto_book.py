"""₿ crypto book: mandate, bear exit, hard stop, majors-only, persistence."""
import json
import os
import sys
import tempfile
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai_investing.config import Settings  # noqa: E402
from ai_investing.strategy import crypto_book as cb  # noqa: E402


def _bars(prices):
    return [SimpleNamespace(close=p, volume=1000.0) for p in prices]


def _settings(tmp):
    s = Settings()
    s.state_path = os.path.join(tmp, "state.json")
    return s


def _draining_stablecoins(tmp):
    """Write the ONE extra bear signal the exit test needs, as a fixture.

    Before this, the test redirected state_path into a temp dir and then read
    the machine's LIVE crypto history anyway, so whether it passed depended on
    the real stablecoin supply: green on the dev box's stale snapshot, red on
    the ProDesk's live data, and able to flip on either as the market moved
    (§4.21). A test for "two signals fire" must SUPPLY two signals.
    """
    d = os.path.join(tmp, "crypto_history")
    os.makedirs(d, exist_ok=True)
    # 32 rows: supply 2% lower than 30 days ago -> "stablecoin supply draining"
    rows = [{"usd_bn": 100.0}] * 31 + [{"usd_bn": 98.0}]
    with open(os.path.join(d, "stablecoins_daily.json"), "w") as fh:
        json.dump(rows, fh)


CALM = _bars([100.0] * 120 + [110.0])       # well above its 100d mean
PRICES = {"BTC/USD": 110.0, "ETH/USD": 110.0, "SOL/USD": 110.0}
BARS = {s: CALM for s in cb.MAJORS}


def test_builds_the_hodl_core_when_calm():
    with tempfile.TemporaryDirectory() as tmp:
        book = cb.CryptoBook(_settings(tmp))
        r = book.cycle({}, BARS, PRICES)
        kinds = [k for _, k, _ in r["opened"]]
        assert kinds and all(k == "hodl" for k in kinds), "core should be established"
        core = sum(n for _, k, n in r["opened"] if k == "hodl")
        assert abs(core / cb.START_CASH - cb.HODL_FRAC) < 0.05, "core ≈ 20% of the book"


def test_a_smaller_book_can_still_reach_its_own_mandate():
    """The 2026-08-20 freeze, pinned.

    Both trade gates used a hardcoded $500 floor, tuned on a $10,000 book. When
    this book moved to a Binance Futures testnet account holding $5,000, the
    HODL core's per-major target fell to HODL_FRAC/3 = 6.67% = $333 — below the
    floor — so the core became unreachable BY CONSTRUCTION. The book sat 100%
    cash from 2026-08-20 placing zero orders, and said nothing, because a gate
    that never opens logs nothing.

    A book must always be able to buy the thing it is mandated to hold. This is
    checked across the size range rather than at one number, because the defect
    was invisible at the size the constants were written for.
    """
    for cash in (2_000.0, 4_999.89, 5_000.0, 10_000.0, 50_000.0):
        with tempfile.TemporaryDirectory() as tmp:
            book = cb.CryptoBook(_settings(tmp))
            book.broker.cash = cash
            r = book.cycle({}, BARS, PRICES)
            core = sum(n for _, k, n in r["opened"] if k == "hodl")
            assert core > 0, f"a ${cash:,.0f} book could not build its core at all"
            # and it reaches roughly the mandate, not a token position
            assert core / cash > cb.HODL_FRAC * 0.5, (
                f"${cash:,.0f} book only reached ${core:,.0f} of a "
                f"${cb.HODL_FRAC * cash:,.0f} mandate")


def test_the_trade_floor_can_never_exceed_what_it_is_buying():
    """The structural guarantee, independent of any particular book size: a
    rebalance threshold above its own target is a deadlock, always."""
    for equity in (500.0, 1_000.0, 5_000.0, 10_000.0, 100_000.0, 1_000_000.0):
        target = cb.HODL_FRAC * equity / len(cb.MAJORS)
        floor = cb.min_trade_usd(equity, target)
        if target >= cb.MIN_TRADE_USD:
            assert floor < target, (
                f"equity ${equity:,.0f}: floor ${floor:,.2f} >= target "
                f"${target:,.2f} — the core is unreachable")
    # the old behaviour is preserved at the book size it was tuned on
    assert cb.min_trade_usd(10_000.0) == 500.0, "0.05 x equity == the old $500 at $10k"


def test_stale_held_metadata_is_reconciled_against_the_venue():
    """`held` records what KIND of position exists, never that one does. After
    the 2026-08-20 broker migration it claimed three majors the venue did not
    have, so every diagnostic lied about the book while it sat frozen."""
    with tempfile.TemporaryDirectory() as tmp:
        book = cb.CryptoBook(_settings(tmp))
        book._state["held"] = {"BTC/USD": {"kind": "hodl", "day": "2026-08-18"},
                               "ETH/USD": {"kind": "hodl", "day": "2026-08-18"},
                               "SOL/USD": {"kind": "hodl", "day": "2026-08-18"}}
        assert not book.broker.get_positions(), "fixture: venue holds nothing"
        book._reconcile_held(book._state["held"])
        assert book._state["held"] == {}, "metadata for absent positions is dropped"


def test_a_venue_we_cannot_read_changes_nothing():
    """Reconciliation must never act on an unreadable account — that is how you
    delete the record of a position that is actually there (§4.7's family)."""
    with tempfile.TemporaryDirectory() as tmp:
        book = cb.CryptoBook(_settings(tmp))
        held = {"BTC/USD": {"kind": "hodl", "day": "2026-08-18"}}
        book._state["held"] = held

        class _Blind:
            def get_positions(self):
                raise RuntimeError("venue unreachable")

        book.broker = _Blind()
        book._reconcile_held(held)
        assert held == {"BTC/USD": {"kind": "hodl", "day": "2026-08-18"}}


def test_never_buys_an_alt():
    with tempfile.TemporaryDirectory() as tmp:
        book = cb.CryptoBook(_settings(tmp))
        alt_signal = {"DOGE/USD": {"impact": 0.9}, "RENDER/USD": {"impact": 0.9}}
        prices = dict(PRICES, **{"DOGE/USD": 1.0, "RENDER/USD": 1.0})
        bars = dict(BARS, **{"DOGE/USD": CALM, "RENDER/USD": CALM})
        r = book.cycle(alt_signal, bars, prices)
        assert all(sym in cb.MAJORS for sym, _, _ in r["opened"]), "alts are signal-only (R27)"


def test_never_shorts():
    with tempfile.TemporaryDirectory() as tmp:
        book = cb.CryptoBook(_settings(tmp))
        r = book.cycle({s: {"impact": -0.9} for s in cb.MAJORS}, BARS, PRICES)
        assert all(k == "hodl" for _, k, _ in r["opened"]), "no tactical short on bad news"


def test_bear_exit_liquidates_and_holds_cash():
    with tempfile.TemporaryDirectory() as tmp:
        _draining_stablecoins(tmp)          # signal 2 of 2, supplied not borrowed
        st = _settings(tmp)
        book = cb.CryptoBook(st)
        book.cycle({}, BARS, PRICES)                       # build the core
        bear_bars = {s: _bars([200.0] * 120 + [100.0]) for s in cb.MAJORS}  # deep winter
        book2 = cb.CryptoBook(st)                          # reload: persistence
        r = book2.cycle({}, bear_bars, PRICES)
        assert r["bear"], "winter + draining supply must register as a bear"
        assert r["closed"], "bear exit must sell"
        assert r["cash"] > cb.START_CASH * 0.8, "most of the book should be in cash"


def test_hard_stop_fires_on_a_10pct_loss():
    with tempfile.TemporaryDirectory() as tmp:
        st = _settings(tmp)                 # no history: deliberately NOT a bear
        book = cb.CryptoBook(st)
        book.cycle({}, BARS, PRICES)
        crashed = {s: 110.0 * (1 - cb.HARD_STOP - 0.01) for s in cb.MAJORS}
        r = cb.CryptoBook(st).cycle({}, BARS, crashed)
        assert any("hard stop" in why for _, why in r["closed"]), "10% rule must fire"


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
    print("All crypto-book tests passed." if not fails else f"{fails} failed")
    sys.exit(1 if fails else 0)
