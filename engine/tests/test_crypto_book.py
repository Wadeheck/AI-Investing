"""₿ crypto book: mandate, bear exit, hard stop, majors-only, persistence."""
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
        st = _settings(tmp)
        book = cb.CryptoBook(st)
        book.cycle({}, BARS, PRICES)                       # build the core
        bear_bars = {s: _bars([200.0] * 120 + [100.0]) for s in cb.MAJORS}  # deep winter
        book2 = cb.CryptoBook(st)                          # reload: persistence
        r = book2.cycle({}, bear_bars, PRICES)
        assert r["bear"], "winter must register as bear evidence"
        assert r["closed"], "bear exit must sell"
        assert r["cash"] > cb.START_CASH * 0.8, "most of the book should be in cash"


def test_hard_stop_fires_on_a_10pct_loss():
    with tempfile.TemporaryDirectory() as tmp:
        st = _settings(tmp)
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
