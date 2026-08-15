"""Sanity tests for TrendZScoreSignal (EMA/stdev z-score trend filter) and for the
two graduation paths documented in docs/design/FORMULA.md #7: does the feature
actually reach the formula unweighted-but-visible, and can RLS actually learn a
nonzero weight for it from realized P&L, exactly like every other feature does?
"""
import math
import os
import random
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ai_investing.learning.features import FeatureExtractor
from ai_investing.learning.formula import FormulaModel
from ai_investing.learning.linalg import dot
from ai_investing.learning.online import RLSLearner
from ai_investing.learning.store import ParamStore
from ai_investing.models import Asset, AssetClass, Bar, SignalDirection, SignalResult
from ai_investing.signals.trend_zscore import TrendZScoreSignal

ASSET = Asset("BTC/USD", AssetClass.CRYPTO)


def _bars(closes, vol=1000.0):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [Bar(start + timedelta(days=i), c, c, c, c, vol) for i, c in enumerate(closes)]


def test_insufficient_history_is_flat():
    sig = TrendZScoreSignal(period=65)
    r = sig.evaluate(ASSET, _bars([100.0] * 30))
    assert r.direction == SignalDirection.FLAT
    assert r.score == 0.0 and r.confidence == 0.0


def test_breakout_above_baseline_is_long():
    # flat, low-volatility base then a sharp spike: z should clear the bull threshold
    closes = [100.0 + (i % 2) * 0.01 for i in range(65)] + [140.0]
    sig = TrendZScoreSignal(period=65, bull=1.0, bear=-1.0)
    r = sig.evaluate(ASSET, _bars(closes))
    assert r.direction == SignalDirection.LONG
    assert r.score > 0
    assert r.meta["z"] > 1.0


def test_breakdown_below_baseline_is_short():
    closes = [100.0 - (i % 2) * 0.01 for i in range(65)] + [60.0]
    sig = TrendZScoreSignal(period=65, bull=1.0, bear=-1.0)
    r = sig.evaluate(ASSET, _bars(closes))
    assert r.direction == SignalDirection.SHORT
    assert r.score < 0
    assert r.meta["z"] < -1.0


def test_inside_band_is_flat():
    # oscillation completes whole cycles inside the window, ending back at the
    # EMA baseline -> z == 0, well inside the +-1 band
    closes = [100.0 + 3 * math.sin(2 * math.pi * i / 13) for i in range(66)]
    sig = TrendZScoreSignal(period=65, bull=1.0, bear=-1.0)
    r = sig.evaluate(ASSET, _bars(closes))
    assert r.direction == SignalDirection.FLAT
    assert -1.0 <= r.meta["z"] <= 1.0


def test_feature_reaches_formula_but_not_consensus():
    """The dormant feature must be visible in phi (so learning can see it) but
    must NOT leak into 'consensus' (which already carries a live nonzero weight) --
    the exact bug fixed 2026-08-15."""
    closes = [100.0 + (i % 2) * 0.01 for i in range(65)] + [140.0]
    bars = _bars(closes)
    breakout = TrendZScoreSignal(period=65, bull=1.0, bear=-1.0).evaluate(ASSET, bars)
    other = SignalResult("momentum", SignalDirection.FLAT, 0.0, 0.0)
    feats = FeatureExtractor().build([breakout, other], bars)

    assert feats["trend_zscore"] == breakout.score * breakout.confidence
    assert feats["trend_zscore"] != 0.0
    # consensus averages ONLY the original signal set -- unaffected by trend_zscore
    assert feats["consensus"] == 0.0


def test_old_saved_formula_migrates_trend_zscore_at_zero_weight():
    """A formula persisted before this feature existed must gain the new
    dimension at weight 0 -- ParamStore._migrate is the mechanism, this proves
    it actually covers trend_zscore specifically, not just in theory."""
    stale = FormulaModel(feature_names=["bias", "momentum"], weights=[0.0, 0.02])
    changed = ParamStore._migrate(stale)
    assert changed is True
    assert "trend_zscore" in stale.feature_names
    assert stale.weights[stale.feature_names.index("trend_zscore")] == 0.0


def test_rls_can_graduate_trend_zscore_from_realized_pnl():
    """The live, automatic graduation path: if trend_zscore genuinely predicts
    realized returns, online RLS should move its weight away from 0 toward the
    true relationship -- the same mechanism every other feature matures through,
    proven here specifically for this feature's position in the vector."""
    fx = FeatureExtractor()
    tz_idx = fx.names.index("trend_zscore")
    theta0 = [0.0] * len(fx.names)

    rng = random.Random(42)
    true_tz_weight = 0.04
    learner = RLSLearner.initialize(theta0, prior_confidence=0.01, mu=1.0, trust_region=100.0)
    for _ in range(400):
        phi = [0.0] * len(fx.names)
        phi[tz_idx] = rng.uniform(-1, 1)
        y = true_tz_weight * phi[tz_idx] + rng.gauss(0, 0.002)  # small noise
        learner.update(phi, y)

    assert abs(learner.theta[tz_idx] - true_tz_weight) < 0.01, learner.theta[tz_idx]
    # every other dimension had zero signal and should stay near zero
    assert all(abs(w) < 0.01 for i, w in enumerate(learner.theta) if i != tz_idx)


def test_migration_grows_rls_instead_of_discarding_what_it_learned():
    """Adding a feature to phi must not silently reset the online learner.

    ParamStore used to null the RLS out whenever theta changed dimension, which
    threw away the covariance -- the "how confident am I in each weight" memory
    built from every closed trade so far -- for a reason that has nothing to do
    with those trades. This pins the fix: the old weights and their covariance
    block survive, the new dimension is appended with zero cross-covariance, and
    `updates` (the count of realized outcomes learned from) is preserved."""
    import json as _json
    import tempfile as _tempfile
    from ai_investing.learning.online import RLSLearner as _RLS

    old_names = [n for n in FeatureExtractor.names if n != "trend_zscore"]
    model = FormulaModel(feature_names=list(old_names),
                         weights=[0.01 * (i + 1) for i in range(len(old_names))])
    rls = _RLS.initialize(list(model.weights), prior_confidence=4.0)
    rls.updates = 137
    old_P00 = rls.P[0][0]

    path = os.path.join(_tempfile.mkdtemp(), "params.json")
    with open(path, "w") as fh:
        _json.dump({"model": model.to_dict(), "rls": rls.to_dict()}, fh)

    loaded, learner = ParamStore(path).load()
    assert learner is not None, "RLS was discarded on a feature append"
    assert learner.updates == 137
    assert learner.n == len(loaded.feature_names)
    assert learner.P[0][0] == old_P00                      # old covariance intact
    tz = loaded.feature_names.index("trend_zscore")
    assert learner.theta[tz] == 0.0                        # new dim at its default
    assert learner.P[0][tz] == 0.0 and learner.P[tz][0] == 0.0   # no cross-covariance
    assert learner.P[tz][tz] > 0.0                         # but a real prior
    # theta stays aligned to the model's own name order, which is what runner.py
    # builds phi from -- a mismatch here would silently mislearn every weight
    assert len(learner.theta) == len(loaded.feature_names)


def test_migration_still_resets_rls_when_it_does_not_match_the_model():
    """Growing an RLS whose dimension never matched the saved model would
    misalign theta against phi. That case must still fall back to a reset."""
    import json as _json
    import tempfile as _tempfile
    from ai_investing.learning.online import RLSLearner as _RLS

    model = FormulaModel(feature_names=["bias", "momentum"], weights=[0.0, 0.02])
    mismatched = _RLS.initialize([0.0] * 5)          # 5 != 2
    path = os.path.join(_tempfile.mkdtemp(), "params.json")
    with open(path, "w") as fh:
        _json.dump({"model": model.to_dict(), "rls": mismatched.to_dict()}, fh)

    _loaded, learner = ParamStore(path).load()
    assert learner is None


if __name__ == "__main__":
    for _name, _fn in sorted(list(globals().items())):
        if _name.startswith("test_") and callable(_fn):
            _fn()
    print("ok")
