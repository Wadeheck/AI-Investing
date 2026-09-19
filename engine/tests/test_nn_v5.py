"""NNv5 residual challenger tests."""
from __future__ import annotations

import math

import pytest

from ai_investing.learning.formula import FormulaModel
from ai_investing.learning.nn_v5 import NN5ResidualModel, fit_nn5


def _baseline():
    return FormulaModel(feature_names=["bias", "momentum"], weights=[0.01, 0.02], gain=10.0)


def test_zero_residual_is_exactly_the_linear_brain():
    base = _baseline()
    model = NN5ResidualModel(feature_names=["bias", "momentum"], baseline=base.to_dict())
    feats = {"bias": 1.0, "momentum": 0.5}
    assert model.residual(feats) == 0.0
    assert model.raw(feats) == base.raw(feats)
    assert model.target_weight(feats) == base.target_weight(feats)


def test_fit_produces_a_persistable_incremental_model():
    pytest.importorskip("torch")
    base = _baseline()
    X = [[1.0, math.sin(i / 7.0)] for i in range(120)]
    y = [0.01 * row[1] + 0.001 * math.cos(i / 5.0) for i, row in enumerate(X)]
    model, reason = fit_nn5(X, y, base, hidden=4, epochs=200,
                            min_samples=80, t_index=list(range(120)),
                            purge=5, device="cpu")
    assert reason == ""
    assert model is not None and model.fitted
    restored = NN5ResidualModel.from_dict(model.to_dict())
    feats = {"bias": 1.0, "momentum": 0.25}
    assert math.isfinite(restored.raw(feats))
    assert restored.baseline["weights"] == base.to_dict()["weights"]


def test_model_type_is_not_the_live_linear_type():
    base = _baseline()
    model = NN5ResidualModel(baseline=base.to_dict())
    assert model.version == 5
    assert not hasattr(model, "weights")
