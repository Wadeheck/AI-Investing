"""Sanity tests for RegimePersistenceSignal and its graduation path, mirroring
tests/test_trend_zscore.py for the same candidate-feature lifecycle documented
in docs/design/FORMULA.md #7.
"""
import os
import random
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ai_investing.brain.persistence import persistence_days
from ai_investing.learning.features import FeatureExtractor
from ai_investing.learning.formula import FormulaModel
from ai_investing.learning.online import RLSLearner
from ai_investing.learning.store import ParamStore
from ai_investing.models import Asset, AssetClass, Bar, SignalDirection, SignalResult
from ai_investing.signals.regime_persistence import RegimePersistenceSignal

ASSET = Asset("NKE", AssetClass.STOCK)


def _bars(n=30):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [Bar(start + timedelta(days=i), 100.0, 100.0, 100.0, 100.0, 1000.0) for i in range(n)]


class _FakeStore:
    """Minimal stand-in for BrainStore.node_trend: one row per day, given as
    {day_offset_from_now: activation}, oldest first."""

    def __init__(self, rows_by_days_ago: dict[int, float], now=None):
        self.now = now or datetime.now(timezone.utc)
        self._rows = [
            ((self.now - timedelta(days=d)).isoformat(), a)
            for d, a in sorted(rows_by_days_ago.items(), reverse=True)
        ]

    def node_trend(self, node, days=60):
        return list(self._rows)


# -- brain/persistence.py -----------------------------------------------------

def test_persistence_zero_when_not_currently_saturated():
    store = _FakeStore({0: 0.98, 1: 0.98, 2: 0.98})
    assert persistence_days(store, "bond_stress", current=0.5) == 0.0


def test_persistence_counts_consecutive_saturated_days_same_sign():
    now = datetime.now(timezone.utc)
    store = _FakeStore({0: 0.97, 1: 0.96, 2: 0.95, 3: 0.90, 4: 0.40}, now=now)
    # days 0-3 saturated same sign, day 4 breaks it -> streak of 4
    assert persistence_days(store, "bond_stress", current=0.97, now=now) == 4.0


def test_persistence_breaks_on_sign_flip():
    now = datetime.now(timezone.utc)
    store = _FakeStore({0: 0.90, 1: -0.92, 2: -0.95}, now=now)
    assert persistence_days(store, "bond_stress", current=0.90, now=now) == 1.0


def test_persistence_no_history_is_zero():
    store = _FakeStore({})
    assert persistence_days(store, "bond_stress", current=0.99) == 0.0


# -- signals/regime_persistence.py --------------------------------------------

def _brain_ctx(impact, days, node="sportswear"):
    return {"brain": {"asset_impacts": {"NKE": {"impact": impact, "node": node,
                                                "persistence_days": days}}}}


def test_fresh_shock_under_min_days_is_flat():
    sig = RegimePersistenceSignal()
    r = sig.evaluate(ASSET, _bars(), context=_brain_ctx(impact=-0.9, days=2))
    assert r.direction == SignalDirection.FLAT
    assert r.score == 0.0 and r.confidence == 0.0


def test_sustained_negative_impact_is_short_and_ramps_with_days():
    sig = RegimePersistenceSignal()
    r10 = sig.evaluate(ASSET, _bars(), context=_brain_ctx(impact=-0.9, days=10))
    r40 = sig.evaluate(ASSET, _bars(), context=_brain_ctx(impact=-0.9, days=40))
    assert r10.direction == SignalDirection.SHORT
    assert r40.direction == SignalDirection.SHORT
    assert r10.score < 0 and r40.score < 0
    # longer sustained streak => larger-magnitude (more confident) short read
    assert abs(r40.score) > abs(r10.score)
    assert r40.confidence > r10.confidence


def test_sustained_positive_impact_is_long():
    sig = RegimePersistenceSignal()
    r = sig.evaluate(ASSET, _bars(), context=_brain_ctx(impact=0.9, days=45))
    assert r.direction == SignalDirection.LONG
    assert r.score > 0.9   # fully saturated at/after SATURATE_DAYS


def test_no_active_impact_is_flat():
    sig = RegimePersistenceSignal()
    r = sig.evaluate(ASSET, _bars(), context=_brain_ctx(impact=0.0, days=30))
    assert r.direction == SignalDirection.FLAT


def test_no_brain_context_is_flat():
    sig = RegimePersistenceSignal()
    r = sig.evaluate(ASSET, _bars(), context=None)
    assert r.direction == SignalDirection.FLAT


# -- graduation lifecycle (mirrors test_trend_zscore.py) ----------------------

def test_feature_reaches_formula_but_not_consensus():
    sustained = RegimePersistenceSignal().evaluate(
        ASSET, _bars(), context=_brain_ctx(impact=-0.9, days=40))
    other = SignalResult("momentum", SignalDirection.FLAT, 0.0, 0.0)
    feats = FeatureExtractor().build([sustained, other], _bars())

    assert feats["regime_persistence"] == sustained.score * sustained.confidence
    assert feats["regime_persistence"] != 0.0
    assert feats["consensus"] == 0.0


def test_old_saved_formula_migrates_regime_persistence_at_zero_weight():
    stale = FormulaModel(feature_names=["bias", "momentum"], weights=[0.0, 0.02])
    changed = ParamStore._migrate(stale)
    assert changed is True
    assert "regime_persistence" in stale.feature_names
    assert stale.weights[stale.feature_names.index("regime_persistence")] == 0.0


def test_rls_can_graduate_regime_persistence_from_realized_pnl():
    fx = FeatureExtractor()
    idx = fx.names.index("regime_persistence")
    theta0 = [0.0] * len(fx.names)

    rng = random.Random(7)
    true_weight = 0.03
    learner = RLSLearner.initialize(theta0, prior_confidence=0.01, mu=1.0, trust_region=100.0)
    for _ in range(400):
        phi = [0.0] * len(fx.names)
        phi[idx] = rng.uniform(-1, 1)
        y = true_weight * phi[idx] + rng.gauss(0, 0.002)
        learner.update(phi, y)

    assert abs(learner.theta[idx] - true_weight) < 0.01, learner.theta[idx]
    assert all(abs(w) < 0.01 for i, w in enumerate(learner.theta) if i != idx)


if __name__ == "__main__":
    for _name, _fn in sorted(list(globals().items())):
        if _name.startswith("test_") and callable(_fn):
            _fn()
    print("ok")
