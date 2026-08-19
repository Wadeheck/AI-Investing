"""Crypto event sleeve: event_sleeve.py's crypto-only twin (split 2026-08-19)."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai_investing.config import Settings  # noqa: E402
from ai_investing.strategy import crypto_event_sleeve as ces  # noqa: E402


def _settings(tmp):
    s = Settings()
    s.state_path = os.path.join(tmp, "state.json")
    return s


def test_enters_only_above_the_shock_floor():
    with tempfile.TemporaryDirectory() as tmp:
        sl = ces.CryptoEventSleeve(_settings(tmp))
        shocks = {"BTC/USD": {"impact": ces.CRYPTO_EVENT_MIN + 0.02, "node": "crypto_flow"},
                  "ETH/USD": {"impact": ces.CRYPTO_EVENT_MIN - 0.02, "node": "crypto_flow"}}
        r = sl.cycle(shocks, {"BTC/USD": 60000.0, "ETH/USD": 3000.0})
        syms = [o[0] for o in r["opened"]]
        assert "BTC/USD" in syms, "shock above the floor must open"
        assert "ETH/USD" not in syms, "shock below the floor must be ignored"


def test_ignores_stock_shocks_entirely():
    """This sleeve's capital and 3 slots are crypto-only — a stock shock, however
    large, belongs to event_sleeve.py, not here."""
    with tempfile.TemporaryDirectory() as tmp:
        sl = ces.CryptoEventSleeve(_settings(tmp))
        shocks = {"AAA": {"impact": 0.9, "node": "semis"},
                  "BTC/USD": {"impact": ces.CRYPTO_EVENT_MIN + 0.02, "node": "crypto_flow"}}
        r = sl.cycle(shocks, {"AAA": 100.0, "BTC/USD": 60000.0})
        syms = [o[0] for o in r["opened"]]
        assert "AAA" not in syms, "stock shocks must never open a position here"
        assert "BTC/USD" in syms


def test_never_shorts_a_negative_shock():
    with tempfile.TemporaryDirectory() as tmp:
        sl = ces.CryptoEventSleeve(_settings(tmp))
        r = sl.cycle({"BTC/USD": {"impact": -0.9, "node": "crypto_flow"}}, {"BTC/USD": 60000.0})
        assert not r["opened"], "long only, v1 — no shorts"


def test_respects_max_concurrent_positions():
    with tempfile.TemporaryDirectory() as tmp:
        sl = ces.CryptoEventSleeve(_settings(tmp))
        shocks = {f"S{i}/USD": {"impact": 0.2, "node": "crypto_flow"}
                  for i in range(ces.CRYPTO_EVENT_N + 3)}
        prices = {f"S{i}/USD": 100.0 for i in range(ces.CRYPTO_EVENT_N + 3)}
        r = sl.cycle(shocks, prices)
        assert len(r["opened"]) <= ces.CRYPTO_EVENT_N


def test_hard_stop_closes_the_position():
    with tempfile.TemporaryDirectory() as tmp:
        st = _settings(tmp)
        sl = ces.CryptoEventSleeve(st)
        sl.cycle({"BTC/USD": {"impact": 0.3, "node": "crypto_flow"}}, {"BTC/USD": 60000.0})
        assert sl.broker.get_positions(), "position should be open"
        sl2 = ces.CryptoEventSleeve(st)                # reload: persistence check
        assert sl2.broker.get_positions(), "book must survive a restart"
        r = sl2.cycle({}, {"BTC/USD": 60000.0 * (1 - ces.HARD_STOP - 0.01)})
        assert r["closed"], "a >10% loss must trigger the user's hard stop"
        assert not sl2.broker.get_positions()


def test_clock_exit_after_hold_days():
    with tempfile.TemporaryDirectory() as tmp:
        st = _settings(tmp)
        sl = ces.CryptoEventSleeve(st)
        sl.cycle({"BTC/USD": {"impact": 0.3, "node": "crypto_flow"}}, {"BTC/USD": 60000.0})
        sl._state["seen_days"] = ["2000-01-0%d" % d for d in range(1, ces.CRYPTO_EVENT_HOLD_DAYS + 3)]
        sl._state["held"]["BTC/USD"]["opened_day"] = "2000-01-01"
        r = sl.cycle({}, {"BTC/USD": 60500.0})
        assert r["closed"], "the hold clock must force an exit"


def test_never_doubles_up_on_a_symbol_it_already_holds():
    with tempfile.TemporaryDirectory() as tmp:
        sl = ces.CryptoEventSleeve(_settings(tmp))
        shock = {"BTC/USD": {"impact": 0.3, "node": "crypto_flow"}}
        prices = {"BTC/USD": 60000.0}

        first = sl.cycle(shock, prices)
        assert [o[0] for o in first["opened"]] == ["BTC/USD"]
        held_qty = sum(p.qty for p in sl.broker.get_positions().values())

        for _ in range(3):
            again = sl.cycle(shock, prices)
            assert not again["opened"], \
                "a symbol already held must never be re-entered"

        assert sum(p.qty for p in sl.broker.get_positions().values()) == held_qty
        assert len(sl.broker.get_positions()) == 1


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
    print("All crypto-event-sleeve tests passed." if not fails else f"{fails} failed")
    sys.exit(1 if fails else 0)
