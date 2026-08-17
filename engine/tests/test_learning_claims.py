"""The (φ, y) pairing has to survive a restart, or the model learns nonsense.

`OutcomeTracker` maps each open position back to the feature vector that opened
it. It was memory-only: rebuilt empty in every `Runner` constructor, written
nowhere. The ProDesk powers down 05:00-07:30 SGT every night and the trading
book holds for days to weeks, so a position was re-registered each morning with
THAT MORNING's φ — and when it finally closed, the learner was handed
(today's φ, a two-week return).

A lost sample is slow. A mis-paired sample is wrong: it teaches the model that
this morning's features caused a move decided on a fortnight ago.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_investing.learning.attribution import OutcomeTracker
from ai_investing.models import Asset, AssetClass, Position

A = Asset("AAPL", AssetClass.STOCK)
KEY = "stock:AAPL"


def _pos(qty=10.0, avg=100.0):
    return {KEY: Position(A, qty, avg)}


def test_a_closed_position_emits_the_phi_that_opened_it():
    t = OutcomeTracker()
    t.sync(_pos(), {KEY: {"momentum": 0.9}}, {KEY: 100.0})
    samples = t.sync({}, {}, {KEY: 110.0})
    assert len(samples) == 1
    assert samples[0].features == {"momentum": 0.9}
    assert abs(samples[0].realized_return - 0.10) < 1e-9


def test_the_pairing_survives_a_restart():
    """THE BUG. Open on Monday with momentum 0.9, restart every night, close on
    Friday when momentum reads -0.4. The sample must carry Monday's 0.9."""
    t = OutcomeTracker()
    t.sync(_pos(), {KEY: {"momentum": 0.9}}, {KEY: 100.0})

    for daily_restart in range(4):
        saved = json.loads(json.dumps(t.state()))       # the box powers off
        t = OutcomeTracker.from_state(saved)            # ...and comes back
        t.sync(_pos(), {KEY: {"momentum": -0.4}}, {KEY: 105.0})

    samples = t.sync({}, {KEY: {"momentum": -0.4}}, {KEY: 110.0})
    assert len(samples) == 1, "the close must still produce a sample"
    assert samples[0].features == {"momentum": 0.9}, \
        f"learned from the wrong features: {samples[0].features}"
    assert abs(samples[0].realized_return - 0.10) < 1e-9, \
        "and the return must be measured from the ENTRY price, not the restart"


def test_a_short_is_credited_in_its_own_direction():
    t = OutcomeTracker()
    t.sync(_pos(qty=-10.0), {KEY: {"momentum": -0.5}}, {KEY: 100.0})
    s = t.sync({}, {}, {KEY: 90.0})[0]
    assert abs(s.realized_return - 0.10) < 1e-9, "a short that fell 10% made 10%"


def test_a_corrupt_claims_file_costs_a_sample_not_the_engine():
    t = OutcomeTracker.from_state({"open": {KEY: "not a record", "x": None}})
    assert t._open == {}
    assert t.sync(_pos(), {KEY: {"m": 1.0}}, {KEY: 100.0}) == []


def test_from_state_tolerates_junk():
    for junk in (None, {}, {"open": None}, {"nope": 1}):
        assert OutcomeTracker.from_state(junk)._open == {}


def test_claim_ages_are_reported_so_starvation_is_visible():
    """"Zero samples" and "nothing has closed yet" look identical from outside
    and mean very different things."""
    t = OutcomeTracker()
    t.sync(_pos(), {KEY: {"m": 1.0}}, {KEY: 100.0})
    ages = t.pending_ages()
    assert KEY in ages and ages[KEY] < 1.0


def test_an_untracked_open_is_retried_not_abandoned():
    """A position that opens on a cycle with no decision for it (no φ) must not
    be silently excluded from learning for the rest of its life."""
    t = OutcomeTracker()
    t.sync(_pos(), {}, {KEY: 100.0})            # no features available yet
    assert t._open == {}
    t.sync(_pos(), {KEY: {"m": 0.3}}, {KEY: 100.0})   # they arrive next cycle
    assert KEY in t._open
    assert t.sync({}, {}, {KEY: 110.0})[0].features == {"m": 0.3}


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"test_learning_claims: all {len(fns)} passed")
