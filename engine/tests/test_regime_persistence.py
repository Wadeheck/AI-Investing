"""Sanity tests for RegimePersistenceSignal and its graduation path, mirroring
tests/test_trend_zscore.py for the same candidate-feature lifecycle documented
in docs/design/FORMULA.md #7.
"""
import os
import random
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ai_investing.brain.graph import KnowledgeGraph, Node, Edge
from ai_investing.brain.persistence import persistence_days, driver_persistence_days
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


# -- brain/graph.py: predecessors() -------------------------------------------

def _tlt_graph():
    """bond_stress --influences(0.8)--> tlt; a weak, incidental edge from
    china_growth (0.1) also reaches it; gld is a fellow asset (must be
    excluded as a driver, origin-only)."""
    nodes = [
        Node("bond_stress", "factor", "Bond Market Stress"),
        Node("china_growth", "factor", "China Growth"),
        Node("gld", "asset", "Gold ETF", symbol="GLD", market="US"),
        Node("tlt", "asset", "20Y+ Treasury ETF", symbol="TLT", market="US"),
    ]
    edges = [
        Edge("bond_stress", "tlt", "influences", sign=-1, weight=0.8),
        Edge("china_growth", "tlt", "influences", sign=1, weight=0.1),
        Edge("gld", "tlt", "correlates_with", sign=1, weight=0.3),
    ]
    return KnowledgeGraph(nodes, edges)


def test_predecessors_ranks_by_weight_descending():
    g = _tlt_graph()
    preds = g.predecessors("tlt")
    assert [p[0] for p in preds] == ["bond_stress", "gld", "china_growth"]


def test_predecessors_respects_k():
    g = _tlt_graph()
    assert len(g.predecessors("tlt", k=1)) == 1


# -- brain/persistence.py: driver_persistence_days() --------------------------

class _MultiFakeStore:
    """Per-node node_trend: {node: {days_ago: activation}}."""

    def __init__(self, by_node: dict[str, dict[int, float]], now=None):
        self.now = now or datetime.now(timezone.utc)
        self._by_node = by_node

    def node_trend(self, node, days=60):
        rows = self._by_node.get(node, {})
        return [((self.now - timedelta(days=d)).isoformat(), a)
                for d, a in sorted(rows.items(), reverse=True)]


def test_driver_persistence_borrows_from_saturated_origin():
    """The live case this was built for: TLT's own activation (-0.76) has
    never crossed the saturation threshold, but bond_stress -- its strongest
    driver, edge weight 0.8 -- has been pinned there for 20 days."""
    g = _tlt_graph()
    now = datetime.now(timezone.utc)
    store = _MultiFakeStore({
        "tlt": {d: -0.76 for d in range(20)},
        "bond_stress": {d: -0.98 for d in range(20)},
    }, now=now)
    activations = {"tlt": -0.76, "bond_stress": -0.98}

    own = persistence_days(store, "tlt", -0.76, now=now)
    assert own == 0.0    # confirms the gap this feature closes

    blended = driver_persistence_days(g, store, activations, "tlt", now=now)
    assert blended == 20.0 * 0.8   # bond_stress's streak, scaled by edge weight


def test_driver_persistence_never_worse_than_own_streak():
    """An asset whose OWN activation is sustained keeps full, unscaled credit
    even if no driver is currently saturated."""
    g = _tlt_graph()
    now = datetime.now(timezone.utc)
    store = _MultiFakeStore({"tlt": {d: -0.90 for d in range(15)}}, now=now)
    activations = {"tlt": -0.90}
    assert driver_persistence_days(g, store, activations, "tlt", now=now) == 15.0


def test_driver_persistence_excludes_asset_type_predecessors():
    """gld correlates_with tlt, but it's an asset, not an origin -- it must
    never be allowed to lend TLT a persistence read."""
    g = _tlt_graph()
    now = datetime.now(timezone.utc)
    store = _MultiFakeStore({
        "tlt": {d: -0.1 for d in range(30)},         # never saturated
        "gld": {d: 0.99 for d in range(30)},          # saturated, but it's an asset
    }, now=now)
    activations = {"tlt": -0.1, "gld": 0.99}
    assert driver_persistence_days(g, store, activations, "tlt", now=now) == 0.0


def test_driver_persistence_graph_error_degrades_to_own():
    """If graph traversal blows up for any reason, this must never take a
    cycle down with it -- degrade to the plain per-node read."""
    class _BrokenGraph:
        def predecessors(self, node_id, k=None):
            raise RuntimeError("boom")

    now = datetime.now(timezone.utc)
    store = _MultiFakeStore({"tlt": {d: -0.9 for d in range(10)}}, now=now)
    activations = {"tlt": -0.9}
    assert driver_persistence_days(_BrokenGraph(), store, activations, "tlt", now=now) == 10.0


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
