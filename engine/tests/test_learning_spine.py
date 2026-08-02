"""The learning spine: posteriors, regime conditioning, allocation, self-defence.

These tests encode the DESIGN CONTRACT in docs/LEARNING.md. If one fails, the
learner is either not learning or learning dangerously.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai_investing.config import Settings  # noqa: E402
from ai_investing.learning.spine import (LearningSpine, SIZE_BOUNDS,  # noqa: E402
                                         BUDGET_BOUNDS, BUDGET_STEP, regime_of)


def _spine(tmp):
    s = Settings()
    s.state_path = os.path.join(tmp, "state.json")
    return LearningSpine(s)


def _run(sp, policy, n, move, signal=0.2, regime="neutral", vol=0.02, h=2):
    for i in range(n):
        sp.record(policy, f"S{i}", 1, signal, vol, h, regime=regime)
        sp.settle(policy, f"S{i}", move)


def test_untested_policy_is_neither_favoured_nor_punished():
    with tempfile.TemporaryDirectory() as tmp:
        sp = _spine(tmp)
        assert sp.size_multiplier("new") == 1.0
        assert sp.calibration_gain("new") == 1.0


def test_uncertainty_governs_how_fast_it_moves():
    """Same win rate, more evidence => stronger adjustment. Never unbounded."""
    with tempfile.TemporaryDirectory() as tmp:
        a = _spine(tmp); _run(a, "p", 5, 0.05)
        with tempfile.TemporaryDirectory() as tmp2:
            b = _spine(tmp2); _run(b, "p", 60, 0.05)
        m_small, m_big = a.size_multiplier("p"), b.size_multiplier("p")
        assert 1.0 < m_small < m_big <= SIZE_BOUNDS[1], (m_small, m_big)


def test_persistent_losses_shrink_size_to_the_floor_but_never_zero():
    with tempfile.TemporaryDirectory() as tmp:
        sp = _spine(tmp); _run(sp, "bad", 40, -0.05)
        m = sp.size_multiplier("bad")
        assert m == SIZE_BOUNDS[0], f"a losing policy must sit at the floor, got {m}"
        assert m > 0, "never zero — a policy at zero can never earn its way back"


def test_confidently_wrong_is_punished_harder_than_tentatively_wrong():
    with tempfile.TemporaryDirectory() as tmp:
        sp = _spine(tmp)
        sp.record("c", "A", 1, 0.5, 0.02, 2); hi = sp.settle("c", "A", -0.05)
        sp.record("c", "B", 1, 0.05, 0.02, 2); lo = sp.settle("c", "B", -0.05)
        assert hi["score"] < lo["score"], "conviction must raise the cost of being wrong"


def test_a_win_inside_costs_is_not_a_win():
    with tempfile.TemporaryDirectory() as tmp:
        sp = _spine(tmp)
        sp.record("c", "A", 1, 0.2, 0.02, 2)
        out = sp.settle("c", "A", 0.0005, cost_frac=0.002)
        assert out["score"] == 0.0 and not out["won"], "noise-sized gains are not skill"


def test_overprediction_is_corrected_toward_reality():
    with tempfile.TemporaryDirectory() as tmp:
        sp = _spine(tmp)
        for i in range(40):
            sp.record("opt", f"S{i}", 1, 0.3, 0.02, 4)
            exp = sp.expected_move(0.3, 0.02, 4, sp.calibration_gain("opt"))
            sp.settle("opt", f"S{i}", exp / 3.0)
        g = sp.calibration_gain("opt")
        assert g < 1.0, f"expectations must shrink toward what actually happens ({g})"


def test_skill_is_conditional_on_regime():
    """Good in calm, bad in panic must NOT average to mediocre."""
    with tempfile.TemporaryDirectory() as tmp:
        sp = _spine(tmp)
        _run(sp, "cond", 20, 0.05, regime="risk_on")
        _run(sp, "cond", 20, -0.05, regime="risk_off")
        on = sp.size_multiplier("cond", "risk_on")
        off = sp.size_multiplier("cond", "risk_off")
        assert on > off, f"regime conditioning lost: on={on} off={off}"


def test_capital_follows_skill_but_moves_slowly_and_stays_bounded():
    with tempfile.TemporaryDirectory() as tmp:
        sp = _spine(tmp)
        _run(sp, "winner", 40, 0.05)
        _run(sp, "loser", 40, -0.05)
        b = sp.risk_budgets(["winner", "loser"])
        assert b["winner"] > b["loser"], "capital must drift toward demonstrated skill"
        for v in b.values():
            assert BUDGET_BOUNDS[0] - 0.02 <= v <= BUDGET_BOUNDS[1] + 0.02, v
        start = 0.5
        assert abs(b["winner"] - start) <= BUDGET_STEP + 1e-6, "rate-limited per week"


def test_one_freak_outcome_cannot_rewrite_the_model():
    with tempfile.TemporaryDirectory() as tmp:
        sp = _spine(tmp); _run(sp, "x", 25, 0.01)
        before = sp.size_multiplier("x")
        sp.record("x", "MOON", 1, 0.2, 0.02, 2); sp.settle("x", "MOON", 5.0)
        assert abs(sp.size_multiplier("x") - before) < 0.15


def test_degraded_policy_is_cut_and_flagged():
    with tempfile.TemporaryDirectory() as tmp:
        sp = _spine(tmp); _run(sp, "rot", 40, -0.05)
        assert sp.status("rot") == "degraded"
        assert sp.size_multiplier("rot") == SIZE_BOUNDS[0]


def test_outage_tainted_outcomes_are_journalled_but_not_learned_from():
    """A stop that fired late because the engine was down says nothing about
    the SIGNAL — it must not move the posteriors."""
    import json as _json
    with tempfile.TemporaryDirectory() as tmp:
        sp = _spine(tmp)
        _run(sp, "p", 10, 0.05)
        before = sp.size_multiplier("p")
        n_before = sp.report()["policies"]["p"]["n"]
        with open(os.path.join(tmp, "learning_gaps.json"), "w") as fh:
            _json.dump([{"start": "2000-01-01T00:00:00+00:00",
                         "end": "2099-01-01T00:00:00+00:00", "hours": 6}], fh)
        sp.record("p", "GAPPY", 1, 0.2, 0.02, 2)
        out = sp.settle("p", "GAPPY", -0.30)          # a disaster, during an outage
        assert out.get("gap_affected"), "the outcome must be tagged"
        assert sp.report()["policies"]["p"]["n"] == n_before, "sample count must not grow"
        assert sp.size_multiplier("p") == before, "an outage must not teach the learner"


def test_regime_of_maps_the_three_states():
    assert regime_of(0.5) == "risk_on"
    assert regime_of(0.0) == "neutral"
    assert regime_of(-0.5) == "risk_off"
    assert regime_of(0.9, bear=True) == "risk_off", "an explicit bear overrides"


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
    print("All learning-spine tests passed." if not fails else f"{fails} failed")
    sys.exit(1 if fails else 0)
