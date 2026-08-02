"""Expectation ledger: claims, settlement, calibration, and bounded reward/penalty."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai_investing.config import Settings  # noqa: E402
from ai_investing.learning.expectations import (ExpectationLedger, MIN_N,  # noqa: E402
                                                TRUST_BOUNDS, GAIN_BOUNDS)


def _led(tmp):
    s = Settings()
    s.state_path = os.path.join(tmp, "state.json")
    return ExpectationLedger(s)


def test_untuned_prior_changes_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        led = _led(tmp)
        assert led.size_multiplier("event") == 1.0, "no evidence => no adjustment"
        assert led.calibration_gain("event") == 1.0


def test_records_and_settles_a_claim():
    with tempfile.TemporaryDirectory() as tmp:
        led = _led(tmp)
        led.record("event", "AAA", 1, signal=0.2, vol_daily=0.02, horizon_days=2)
        out = led.settle("event", "AAA", realized_move=0.01)
        assert out and out["expected_move"] > 0
        assert out["ratio"] > 0 and out["score"] in (-1.0, 0.0, 1.0)


def test_wrong_direction_scores_negative_and_shrinks_size():
    with tempfile.TemporaryDirectory() as tmp:
        led = _led(tmp)
        for i in range(MIN_N + 6):             # a policy that is persistently wrong
            led.record("bad", f"S{i}", 1, signal=0.2, vol_daily=0.02, horizon_days=2)
            led.settle("bad", f"S{i}", realized_move=-0.03)
        m = led.size_multiplier("bad")
        assert m < 1.0, f"a losing policy must trade smaller, got {m}"
        assert m >= TRUST_BOUNDS[0], "penalty must stay bounded"


def test_persistent_winner_earns_size_but_is_capped():
    with tempfile.TemporaryDirectory() as tmp:
        led = _led(tmp)
        for i in range(MIN_N + 6):
            led.record("good", f"S{i}", 1, signal=0.2, vol_daily=0.02, horizon_days=2)
            led.settle("good", f"S{i}", realized_move=0.05)
        m = led.size_multiplier("good")
        assert m > 1.0, "a winning policy earns size"
        assert m <= TRUST_BOUNDS[1], "reward must stay capped — no runaway leverage"


def test_overprediction_is_corrected_not_punished():
    with tempfile.TemporaryDirectory() as tmp:
        led = _led(tmp)
        # right direction every time, but only ever a third of the predicted size
        for i in range(MIN_N + 6):
            led.record("opt", f"S{i}", 1, signal=0.3, vol_daily=0.02, horizon_days=4)
            exp = led.expected_move(0.3, 0.02, 4, led.calibration_gain("opt"))
            led.settle("opt", f"S{i}", realized_move=exp / 3.0)
        g = led.calibration_gain("opt")
        assert g < 1.0, f"expectations should shrink toward reality, got {g}"
        assert g >= GAIN_BOUNDS[0]


def test_a_single_outlier_cannot_rewrite_the_model():
    with tempfile.TemporaryDirectory() as tmp:
        led = _led(tmp)
        for i in range(MIN_N + 2):
            led.record("x", f"S{i}", 1, signal=0.2, vol_daily=0.02, horizon_days=2)
            led.settle("x", f"S{i}", realized_move=0.005)
        before = led.size_multiplier("x")
        led.record("x", "MOON", 1, signal=0.2, vol_daily=0.02, horizon_days=2)
        led.settle("x", "MOON", realized_move=5.0)          # a 500% freak
        after = led.size_multiplier("x")
        assert abs(after - before) < 0.25, "one outlier must not swing sizing"


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
    print("All expectation-ledger tests passed." if not fails else f"{fails} failed")
    sys.exit(1 if fails else 0)
