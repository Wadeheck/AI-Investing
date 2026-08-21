"""The learning spine: posteriors, regime conditioning, allocation, self-defence.

These tests encode the DESIGN CONTRACT in docs/design/LEARNING.md. If one fails, the
learner is either not learning or learning dangerously.
"""
import json
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


def test_a_second_claim_on_a_live_symbol_is_refused_not_swallowed():
    """2026-08-04: the event sleeve's broken re-entry guard opened two USO claims
    44 minutes apart. `open` is keyed policy:symbol, so the second REPLACED the
    first — which was then never settled and remains a dangling `open` record in
    expectations.jsonl forever.

    The claim corpus is the one artefact here that cannot be rebuilt, so silent
    corruption of it is the worst outcome. Refuse the duplicate, keep the claim the
    position was actually opened on, and say so out loud.
    """
    with tempfile.TemporaryDirectory() as tmp:
        sp = _spine(tmp)
        first = sp.record("event", "USO", 1, 0.0571, 0.02, 2, driver="uso")
        again = sp.record("event", "USO", 1, 0.1090, 0.02, 2, driver="uso")

        assert again == first, "the duplicate must resolve to the ORIGINAL claim id"
        assert len(sp._s["open"]) == 1
        assert sp._s["open"]["event:USO"]["id"] == first, \
            "the first claim is the one the position was opened on; it must survive"
        # the original expected_move must be intact — the exit is judged against it
        assert abs(sp._s["open"]["event:USO"]["expected_move"] - 0.00162) < 1e-4

        # and the refusal is on the record, not just printed
        rows = [json.loads(l) for l in open(sp.ledger_path)]
        assert any(r.get("state") == "rejected" for r in rows), \
            "a refused claim must be journalled, not merely logged"
        assert sum(1 for r in rows if r.get("state") == "open") == 1, \
            "exactly one claim may be opened for one position"

        # settling still works, and settles the surviving claim exactly once
        out = sp.settle("event", "USO", -0.1006, exit_reason="hard stop")
        assert out is not None and out["id"] == first
        assert sp.settle("event", "USO", -0.05) is None, "nothing left to settle"


def test_a_stop_out_is_punished_harder_than_a_scratch():
    """The old score was blind to HOW wrong a call was: at equal conviction a -10%
    stop-out and a -0.3% scratch scored identically (-0.772 in the real USO case).
    For a system whose hard rule is a max loss per position, that is a blind spot
    in exactly the place it matters.

    Severity scales the penalty, bounded by RATIO_CLIP so one freak outcome still
    cannot rewrite the model.
    """
    with tempfile.TemporaryDirectory() as tmp:
        scores = {}
        for label, realized in (("scratch", -0.004), ("stop_out", -0.1006)):
            sp = _spine(os.path.join(tmp, label))
            sp.record("event", "USO", 1, 0.109, 0.02, 2, driver="uso")
            scores[label] = sp.settle("event", "USO", realized)["score"]

        assert scores["stop_out"] < scores["scratch"], (
            f"a stop-out ({scores['stop_out']}) must cost more than a scratch "
            f"({scores['scratch']})")
        assert scores["stop_out"] >= -1.0, "the penalty stays bounded at -1"

        # and a catastrophe far beyond the clip must not exceed the floor
        sp = _spine(os.path.join(tmp, "catastrophe"))
        sp.record("event", "USO", 1, 0.109, 0.02, 2, driver="uso")
        assert sp.settle("event", "USO", -0.90)["score"] >= -1.0



# ---------------------------------------------------------------------------
# §4A: "RATIO_CLIP hides severity beyond 3x". It hid far more than severity.
# ---------------------------------------------------------------------------
def _settled(tmp, expected_signal, vol, realized):
    """One open->settle round trip, returning the journalled outcome."""
    sp = _spine(tmp)
    sp.record("event", "AAA", 1, expected_signal, vol, 1, driver="d")
    return sp, sp.settle("event", "AAA", realized, held_days=1)


def test_the_record_keeps_the_true_ratio_not_only_the_clipped_one():
    """The live USO case: expected +0.31%, realised -10.06%, true ratio -32.7,
    recorded for weeks as -3.0. 15 of 19 settled claims were clipped like this,
    for true ratios spanning 4.8 to 106."""
    with tempfile.TemporaryDirectory() as tmp:
        _, out = _settled(tmp, expected_signal=0.0308, vol=0.10, realized=-0.10057)
        assert abs(out["ratio"]) <= 3.0, "the SCORE bound is unchanged and still applies"
        assert out["ratio_clipped"] is True
        assert out["ratio_true"] < -20, (
            f"the record must show how far off it really was, got {out['ratio_true']}")


def test_the_gain_grows_an_expectation_that_is_too_small():
    """THE INVERSION. `calibration_gain` read `abs(EMA(signed ratio))`, so wins
    and losses cancelled: on the live record the signed EMA sat at -0.274 while
    the median |true ratio| was 14.4. It told the model to SHRINK an
    expected_move that was already ~14x too small.

    Alternating big wins and big losses is exactly the shape that cancelled.
    """
    with tempfile.TemporaryDirectory() as tmp:
        sp = _spine(tmp)
        for i in range(12):
            sp.record("event", f"S{i}", 1, 0.002, 0.02, 1, driver="d")
            # +20x and -20x alternating: the signed average is ~0, the magnitude is 20
            sp.settle("event", f"S{i}", 0.0008 * (1 if i % 2 == 0 else -1), held_days=1)

        b = sp._s["policies"]["event"]
        assert abs(b["ratio"]) < 5, "fixture: the SIGNED average must be near zero"
        assert b["abs_ratio"] > 5 * max(0.5, abs(b["ratio"])), (
            "the MAGNITUDE average must see an error the signed one cancels away: "
            f"signed={b['ratio']:.2f} abs={b['abs_ratio']:.2f}")
        assert sp.calibration_gain("event") > 1.5, (
            f"a systematically too-small expectation must be GROWN, got "
            f"{sp.calibration_gain('event'):.2f}")


def test_the_correction_converges_instead_of_running_away():
    """The loop closes: as the gain grows, expected_move grows, and the measured
    error falls toward 1. A correction that did not converge would be a feedback
    loop, not a calibration."""
    with tempfile.TemporaryDirectory() as tmp:
        sp = _spine(tmp)
        seen = []
        for i in range(12):
            sp.record("event", f"S{i}", 1, 0.002, 0.02, 1, driver="d")
            sp.settle("event", f"S{i}", 0.0008 * (1 if i % 2 == 0 else -1), held_days=1)
            seen.append(sp._s["policies"]["event"]["abs_ratio"])
        assert seen[-1] < seen[0] / 2, (
            f"the measured error must shrink as the gain corrects: "
            f"{seen[0]:.1f} -> {seen[-1]:.1f}")


def test_the_gain_ceiling_is_visible_when_it_binds():
    """GAIN_BOUNDS caps the correction at 3x. On evidence of a 20x error the
    gain pins there and the residual stays visible in `abs_ratio` — the same
    saturation the edge calibrator shows at `gain=2.0`. The bound is a
    deliberate choice; what must never happen is it hiding that it bound."""
    from ai_investing.learning.spine import GAIN_BOUNDS
    with tempfile.TemporaryDirectory() as tmp:
        sp = _spine(tmp)
        for i in range(12):
            sp.record("event", f"S{i}", 1, 0.002, 0.02, 1, driver="d")
            sp.settle("event", f"S{i}", 0.0008 * (1 if i % 2 == 0 else -1), held_days=1)
        gain = sp.calibration_gain("event")
        residual = sp._s["policies"]["event"]["abs_ratio"]
        assert gain == GAIN_BOUNDS[1], "fixture: the ceiling must actually bind here"
        assert residual > 2.0, (
            "and the un-corrected remainder must remain legible rather than "
            f"being absorbed silently: residual {residual:.1f}x")


def test_the_gain_still_shrinks_an_expectation_that_is_too_large():
    """The correction must work in both directions — this is not a licence to
    always inflate."""
    with tempfile.TemporaryDirectory() as tmp:
        sp = _spine(tmp)
        for i in range(12):
            sp.record("event", f"S{i}", 1, 0.20, 0.02, 1, driver="d")
            sp.settle("event", f"S{i}", 0.0004 * (1 if i % 2 == 0 else -1), held_days=1)
        assert sp.calibration_gain("event") < 1.0, "an over-prediction must shrink"


def test_the_gain_is_bounded_however_extreme_the_evidence():
    """106x was a real observation. The correction must stay inside GAIN_BOUNDS
    no matter what — an unbounded gain is how one outcome rewrites the model."""
    from ai_investing.learning.spine import GAIN_BOUNDS
    with tempfile.TemporaryDirectory() as tmp:
        sp = _spine(tmp)
        for i in range(20):
            sp.record("event", f"S{i}", 1, 0.0001, 0.02, 1, driver="d")
            sp.settle("event", f"S{i}", 0.5, held_days=1)      # absurd overshoot
        assert GAIN_BOUNDS[0] <= sp.calibration_gain("event") <= GAIN_BOUNDS[1]


def test_drift_detection_still_reads_the_SIGNED_average():
    """The two averages must not be confused: `status()` needs sign, and would
    be blinded by magnitude. A policy that alternates +/- is NOT drifting."""
    with tempfile.TemporaryDirectory() as tmp:
        sp = _spine(tmp)
        for i in range(25):
            sp.record("event", f"S{i}", 1, 0.002, 0.02, 1, driver="d")
            sp.settle("event", f"S{i}", 0.0008 * (1 if i % 2 == 0 else -1), held_days=1)
        b = sp._s["policies"]["event"]
        assert b["ratio"] is not None and b["abs_ratio"] is not None
        assert abs(b["ratio"]) < b["abs_ratio"], \
            "the signed and magnitude averages must be genuinely different numbers"


def test_an_old_state_file_without_abs_ratio_still_works():
    """Backward compatibility: a bucket written before `abs_ratio` existed must
    keep its learned gain rather than silently reverting to 1.0."""
    with tempfile.TemporaryDirectory() as tmp:
        sp = _spine(tmp)
        sp._s["policies"]["event"] = {"n": 20, "wins": 10, "ratio": -2.0,
                                      "score": 0.0, "recent": []}
        assert sp.calibration_gain("event") != 1.0, \
            "an old bucket must fall back to the signed reading, not to neutral"


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
