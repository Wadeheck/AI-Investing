"""Zero-dependency tests for the learning engine + backtester.
Run: `python3 tests/test_learning.py` from the engine/ directory (or via pytest).
"""
import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_investing.backtest.engine import Backtester
from ai_investing.backtest.walkforward import WalkForwardOptimizer
from ai_investing.data.providers import SyntheticDataProvider
from ai_investing.learning.attribution import OutcomeTracker
from ai_investing.learning.formula import FormulaModel
from ai_investing.learning.linalg import dot, ridge_solve
from ai_investing.learning.online import RLSLearner
from ai_investing.models import Asset, AssetClass, Position


def test_ridge_recovers_coefficients():
    rng = random.Random(0)
    theta_true = [0.5, -0.3, 0.2]
    X = [[1.0, rng.uniform(-1, 1), rng.uniform(-1, 1)] for _ in range(200)]
    y = [dot(theta_true, row) for row in X]
    theta = ridge_solve(X, y, 1e-8)
    assert all(abs(a - b) < 0.01 for a, b in zip(theta, theta_true)), theta


def test_rls_learns_from_samples():
    """Online RLS should converge θ toward the true return-generating weights."""
    rng = random.Random(1)
    theta_true = [0.03, -0.02, 0.05]
    learner = RLSLearner.initialize([0.0, 0.0, 0.0], prior_confidence=0.001,
                                    mu=1.0, trust_region=100.0)
    errs = []
    for _ in range(300):
        x = [1.0, rng.uniform(-1, 1), rng.uniform(-1, 1)]
        y = dot(theta_true, x)
        errs.append(abs(learner.update(x, y)))
    early = sum(errs[:20]) / 20
    late = sum(errs[-20:]) / 20
    assert late < early * 0.2, (early, late)
    assert all(abs(a - b) < 0.01 for a, b in zip(learner.theta, theta_true)), learner.theta


def test_formula_bounds_and_deadzone():
    m = FormulaModel()
    hot = {n: 1.0 for n in m.feature_names}
    assert -1.0 <= m.conviction(hot) <= 1.0
    assert -1.0 <= m.target_weight(hot) <= 1.0
    flat = {n: 0.0 for n in m.feature_names}
    assert m.target_weight(flat) == 0.0  # deadzone -> no trade


def test_outcome_tracker_emits_on_close():
    t = OutcomeTracker()
    asset = Asset("Z", AssetClass.CRYPTO)
    feats = {"bias": 1.0, "momentum": 0.4}
    opened = t.sync({asset.key: Position(asset, 1.0, 100.0)}, {asset.key: feats}, {asset.key: 100.0})
    assert opened == []
    closed = t.sync({}, {}, {asset.key: 110.0})  # +10%
    assert len(closed) == 1 and abs(closed[0].realized_return - 0.10) < 1e-9


def _synthetic_assets():
    p = SyntheticDataProvider()
    assets = [Asset("AAA", AssetClass.STOCK), Asset("BBB", AssetClass.STOCK)]
    bars = {a.key: p.get_bars(a, 250) for a in assets}
    return assets, bars


def test_backtester_runs():
    assets, bars = _synthetic_assets()
    res = Backtester(warmup=60, horizon=5).run(FormulaModel(), assets, bars)
    assert len(res.equity_curve) > 0
    assert math.isfinite(res.metrics["sharpe"])
    assert math.isfinite(res.metrics["max_drawdown"])


def test_walkforward_runs():
    assets, bars = _synthetic_assets()
    opt = WalkForwardOptimizer(Backtester(warmup=60, horizon=5), n_windows=2, search=4)
    r = opt.optimize(assets, bars, FormulaModel())
    assert "model" in r and "windows" in r
    assert isinstance(r["adopted"], bool)
    assert isinstance(r["model"], FormulaModel)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\nAll {len(tests)} learning tests passed.")
