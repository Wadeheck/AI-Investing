"""Event sleeve (third policy): entry floor, hold clock, hard stop, persistence."""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai_investing.config import Settings  # noqa: E402
from ai_investing.strategy import event_sleeve as es  # noqa: E402


def _settings(tmp):
    s = Settings()
    s.state_path = os.path.join(tmp, "state.json")
    return s


def test_enters_only_above_the_shock_floor():
    with tempfile.TemporaryDirectory() as tmp:
        sl = es.EventSleeve(_settings(tmp))
        shocks = {"AAA": {"impact": es.EVENT_MIN + 0.02, "node": "semis"},
                  "BBB": {"impact": es.EVENT_MIN - 0.02, "node": "semis"}}
        r = sl.cycle(shocks, {"AAA": 100.0, "BBB": 100.0})
        syms = [o[0] for o in r["opened"]]
        assert "AAA" in syms, "shock above the floor must open"
        assert "BBB" not in syms, "shock below the floor must be ignored"


def test_never_shorts_a_negative_shock():
    with tempfile.TemporaryDirectory() as tmp:
        sl = es.EventSleeve(_settings(tmp))
        r = sl.cycle({"AAA": {"impact": -0.9, "node": "semis"}}, {"AAA": 100.0})
        assert not r["opened"], "R37 rejected shorts — the sleeve is long-only"


def test_respects_max_concurrent_positions():
    with tempfile.TemporaryDirectory() as tmp:
        sl = es.EventSleeve(_settings(tmp))
        shocks = {f"S{i}": {"impact": 0.2, "node": "semis"} for i in range(es.EVENT_N + 3)}
        prices = {f"S{i}": 100.0 for i in range(es.EVENT_N + 3)}
        r = sl.cycle(shocks, prices)
        assert len(r["opened"]) <= es.EVENT_N


def test_hard_stop_closes_the_position():
    with tempfile.TemporaryDirectory() as tmp:
        st = _settings(tmp)
        sl = es.EventSleeve(st)
        sl.cycle({"AAA": {"impact": 0.3, "node": "semis"}}, {"AAA": 100.0})
        assert sl.broker.get_positions(), "position should be open"
        sl2 = es.EventSleeve(st)                      # reload: persistence check
        assert sl2.broker.get_positions(), "book must survive a restart"
        r = sl2.cycle({}, {"AAA": 100.0 * (1 - es.HARD_STOP - 0.01)})
        assert r["closed"], "a >10% loss must trigger the user's hard stop"
        assert not sl2.broker.get_positions()


def test_clock_exit_after_hold_days():
    with tempfile.TemporaryDirectory() as tmp:
        st = _settings(tmp)
        sl = es.EventSleeve(st)
        sl.cycle({"AAA": {"impact": 0.3, "node": "semis"}}, {"AAA": 100.0})
        # fake the calendar forward past the hold window
        sl._state["seen_days"] = ["2000-01-0%d" % d for d in range(1, es.EVENT_HOLD_DAYS + 3)]
        sl._state["held"]["AAA"]["opened_day"] = "2000-01-01"
        r = sl.cycle({}, {"AAA": 101.0})
        assert r["closed"], "the hold clock must force an exit"


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
    print("All event-sleeve tests passed." if not fails else f"{fails} failed")
    sys.exit(1 if fails else 0)
