"""Tests for the NN challenger (docs/design/NN_CHALLENGER.md §2.7).

The load-bearing one is test_adoption_rule_*: everything else here can be right and
the system still be wrong if a 49-parameter net can displace the linear formula
without clearing a higher bar AND beating it by a margin.
"""
import json
import math
import os
import random
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ai_investing.backtest.engine import Backtester
from ai_investing.backtest.walkforward import WalkForwardOptimizer, adoption_decision
from ai_investing.learning.features import FEATURE_NAMES
from ai_investing.learning.formula import FormulaModel
from ai_investing.learning.nn_formula import NNFormulaModel, _mse, fit_nn
from ai_investing.learning.store import ParamStore
from ai_investing.data.providers import SyntheticDataProvider
from ai_investing.models import Asset, AssetClass


# -- §2.7 #7: the adoption rule, all five cases ----------------------------------
def test_adoption_rule_neither_clears():
    # case 3: keep the incumbent, regardless of how good the raw Sharpes look
    assert adoption_decision(False, False, 9.0, 9.0, 0.20) == "none"


def test_adoption_rule_only_one_clears():
    # case 4: the one that cleared wins even when the other's Sharpe is higher --
    # an uncleared DSR bar means that Sharpe is not believable in the first place
    assert adoption_decision(True, False, 0.5, 5.0, 0.20) == "linear"
    assert adoption_decision(False, True, 5.0, 0.5, 0.20) == "nn"


def test_adoption_rule_both_clear_margin_met():
    # case 5, met: 1.0 -> needs > 1.20
    assert adoption_decision(True, True, 1.0, 1.21, 0.20) == "nn"


def test_adoption_rule_both_clear_margin_missed():
    # case 5, missed: beating linear is not enough, it has to beat it by the margin
    assert adoption_decision(True, True, 1.0, 1.19, 0.20) == "linear"
    assert adoption_decision(True, True, 1.0, 1.20, 0.20) == "linear"   # exactly at the bar
    assert adoption_decision(True, True, 1.0, 1.0, 0.20) == "linear"    # an exact tie


def test_adoption_margin_is_a_hurdle_when_linear_sharpe_is_negative():
    # The trap this guards: sharpe_linear * (1 + margin) would make the bar -1.2 when
    # linear is -1.0, i.e. the NN could adopt while being WORSE. Required is -0.8.
    assert adoption_decision(True, True, -1.0, -0.9, 0.20) == "linear"
    assert adoption_decision(True, True, -1.0, -1.1, 0.20) == "linear"
    assert adoption_decision(True, True, -1.0, -0.5, 0.20) == "nn"


def test_adoption_margin_zero_linear_still_requires_strictly_better():
    assert adoption_decision(True, True, 0.0, 0.0, 0.20) == "linear"
    assert adoption_decision(True, True, 0.0, 0.01, 0.20) == "nn"


# -- §2.7 #1, #2: the model ------------------------------------------------------
def test_roundtrip_is_exact():
    m = NNFormulaModel(hidden=2, W1=[[0.1, -0.2], [0.3, 0.4]], b1=[0.01, -0.02],
                       W2=[0.5, -0.6], b2=0.07, gain=33.0, entry_threshold=0.17,
                       size_scale=0.9, stop_loss=0.11, take_profit=0.31, version=4,
                       fitted=True, feature_mean=[1.0, 2.0], feature_std=[0.5, 0.25],
                       feature_names=["a", "b"])
    back = NNFormulaModel.from_dict(json.loads(json.dumps(m.to_dict())))
    assert back.to_dict() == m.to_dict()
    assert back.raw({"a": 1.5, "b": 2.5}) == m.raw({"a": 1.5, "b": 2.5})


def test_unfit_model_is_inert_and_does_not_raise():
    m = NNFormulaModel()
    assert m.raw({"momentum": 5.0}) == 0.0
    assert m.conviction({"momentum": 5.0}) == 0.0
    assert m.target_weight({"momentum": 5.0}) == 0.0


def test_weight_of_reports_no_attribution_rather_than_raising():
    m = NNFormulaModel()
    assert all(m.weight_of(n) == 0.0 for n in FEATURE_NAMES)
    assert m.weight_of("not_a_feature") == 0.0


def test_interface_matches_formula_model():
    """§2.1: the duck-typed surface Backtester/DecisionEngine/RiskManager rely on."""
    for attr in ("feature_names", "gain", "entry_threshold", "size_scale", "stop_loss",
                 "take_profit", "version", "fitted", "feature_mean", "feature_std",
                 "raw", "conviction", "target_from_conviction", "target_weight",
                 "weight_of", "to_dict", "from_dict", "describe", "clone"):
        assert hasattr(NNFormulaModel(), attr), attr
        assert hasattr(FormulaModel(), attr), attr


def test_clone_overrides_hyperparameters_without_touching_weights():
    m = NNFormulaModel(hidden=1, W1=[[0.5]], b1=[0.0], W2=[1.0], b2=0.0, feature_names=["a"])
    c = m.clone(gain=50.0, entry_threshold=0.3)
    assert c.gain == 50.0 and c.entry_threshold == 0.3
    assert c.W1 == m.W1 and c.b2 == m.b2


# -- §2.7 #3, #4, #5: training ---------------------------------------------------
def _learnable_dataset(n, seed=3):
    rng = random.Random(seed)
    idx_m, idx_s = FEATURE_NAMES.index("momentum"), FEATURE_NAMES.index("sentiment")
    X, y = [], []
    for _ in range(n):
        row = [0.0] * len(FEATURE_NAMES)
        row[0] = 1.0
        for j in range(1, len(FEATURE_NAMES)):
            row[j] = rng.gauss(0, 1)
        X.append(row)
        y.append(0.02 * row[idx_m] - 0.01 * row[idx_s] + rng.gauss(0, 0.004))
    return X, y


def test_refuses_to_fit_below_min_samples():
    X, y = _learnable_dataset(120)
    model, reason = fit_nn(X, y, min_samples=500)
    assert model is None
    assert reason == "insufficient data for NN challenger"


def test_learns_a_real_relationship_better_than_predicting_the_mean():
    X, y = _learnable_dataset(900)
    model, reason = fit_nn(X, y, min_samples=500)
    assert model is not None and reason == ""
    n_val = max(20, len(X) // 5)
    X_val, y_val = X[-n_val:], y[-n_val:]
    baseline_mean = sum(y[:-n_val]) / len(y[:-n_val])
    baseline_mse = sum((baseline_mean - t) ** 2 for t in y_val) / len(y_val)

    def norm(row):
        return [(v - m) / s if s > 1e-9 else 0.0
                for v, m, s in zip(row, model.feature_mean, model.feature_std)]
    fit_mse = _mse(model.W1, model.b1, model.W2, model.b2, [norm(r) for r in X_val], y_val)
    assert fit_mse < baseline_mse * 0.5, (fit_mse, baseline_mse)


def test_training_is_deterministic_given_a_seed():
    X, y = _learnable_dataset(700)
    a, _ = fit_nn(X, y, seed=11, min_samples=500)
    b, _ = fit_nn(X, y, seed=11, min_samples=500)
    c, _ = fit_nn(X, y, seed=12, min_samples=500)
    assert (a.W1, a.b1, a.W2, a.b2) == (b.W1, b.b1, b.W2, b.b2)
    assert (a.W1, a.b1, a.W2, a.b2) != (c.W1, c.b1, c.W2, c.b2)


def test_default_architecture_is_49_parameters():
    """A guard on §0's whole argument: capacity is bounded on purpose."""
    X, y = _learnable_dataset(600)
    model, _ = fit_nn(X, y, min_samples=500)
    assert model.n_params == 49


# -- §2.7 #6: degrades safely on today's small-sample regime ---------------------
def _synthetic_assets(n_bars=400):
    p = SyntheticDataProvider()
    assets = [Asset("AAA", AssetClass.STOCK), Asset("BBB", AssetClass.STOCK)]
    return assets, {a.key: p.get_bars(a, n_bars) for a in assets}


def test_walkforward_with_nn_below_min_samples_falls_through_safely():
    assets, bars = _synthetic_assets()
    opt = WalkForwardOptimizer(Backtester(warmup=60, horizon=5), n_windows=2, search=3)
    r = opt.optimize(assets, bars, FormulaModel(), try_nn=True, nn_min_samples=10 ** 9)
    assert r["nn_reason"] == "insufficient data for NN challenger"
    assert r["nn_ok"] is False
    assert isinstance(r["model"], FormulaModel)      # never an unfit net
    assert r["model_type"] in ("linear",)
    assert "adoption_case" in r


def test_walkforward_default_path_is_unchanged_without_try_nn():
    assets, bars = _synthetic_assets()
    a = WalkForwardOptimizer(Backtester(warmup=60, horizon=5), n_windows=2, search=3, seed=4)
    r = a.optimize(assets, bars, FormulaModel())
    assert "nn_dsr" not in r and r["model_type"] == "linear"
    assert isinstance(r["model"], FormulaModel)
    assert isinstance(r["adopted"], bool)


def test_walkforward_runs_the_nn_track_when_it_has_the_rows():
    assets, bars = _synthetic_assets()
    opt = WalkForwardOptimizer(Backtester(warmup=60, horizon=5), n_windows=2, search=3)
    r = opt.optimize(assets, bars, FormulaModel(), try_nn=True, nn_min_samples=50)
    assert r["nn_windows_fit"] == 2
    assert r["nn_reason"] == ""
    assert r["nn_n_trials"] > 0
    assert math.isfinite(r["nn_challenger_avg"])
    assert r["nn_n_params"] == 49
    # whichever won, it is a usable model of a declared type
    assert isinstance(r["model"], (FormulaModel, NNFormulaModel))
    assert (r["model_type"] == "nn") == isinstance(r["model"], NNFormulaModel)


def test_nn_model_drives_the_backtester_end_to_end():
    """The duck-typing claim in §2.1, actually exercised rather than asserted."""
    assets, bars = _synthetic_assets()
    X, y = _learnable_dataset(600)
    model, _ = fit_nn(X, y, min_samples=500)
    res = Backtester(warmup=60, horizon=5).run(model, assets, bars)
    assert len(res.equity_curve) > 0
    assert math.isfinite(res.metrics["sharpe"])


# -- §2.6: persistence -----------------------------------------------------------
def test_paramstore_roundtrips_the_nn_and_drops_rls():
    X, y = _learnable_dataset(600)
    model, _ = fit_nn(X, y, min_samples=500)
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "formula.json")
        store = ParamStore(path)
        store.save(model)
        assert json.load(open(path))["model_type"] == "nn"
        back, rls = store.load()
        assert isinstance(back, NNFormulaModel)
        assert rls is None            # no online path for the NN in this phase
        assert back.W1 == model.W1 and back.b2 == model.b2
        assert back.feature_mean == model.feature_mean


def test_paramstore_reads_pre_nn_files_as_linear():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "formula.json")
        # exactly what shipped before this change: no model_type key at all
        json.dump({"ts": "2026-01-01", "model": FormulaModel().to_dict(), "rls": None},
                  open(path, "w"))
        model, _ = ParamStore(path).load()
        assert isinstance(model, FormulaModel)


def test_paramstore_version_bumps_on_model_type_swap_but_not_on_a_rewrite():
    X, y = _learnable_dataset(600)
    nn, _ = fit_nn(X, y, min_samples=500)
    with tempfile.TemporaryDirectory() as d:
        store = ParamStore(os.path.join(d, "formula.json"))
        lin = FormulaModel()
        store.save(lin)
        v1 = lin.version
        store.save(lin)
        assert lin.version == v1              # unchanged θ must not advance the version
        store.save(nn)
        assert nn.version == 1                # linear -> NN is a real change


def test_migration_adds_a_new_feature_to_the_net_at_zero_weight():
    m = NNFormulaModel(feature_names=list(FEATURE_NAMES)[:-1],
                       hidden=2,
                       W1=[[0.1] * (len(FEATURE_NAMES) - 1) for _ in range(2)],
                       b1=[0.0, 0.0], W2=[1.0, 1.0], b2=0.0,
                       feature_mean=[0.0] * (len(FEATURE_NAMES) - 1),
                       feature_std=[1.0] * (len(FEATURE_NAMES) - 1))
    assert ParamStore._migrate(m) is True
    assert m.feature_names == list(FEATURE_NAMES)
    assert all(len(row) == len(FEATURE_NAMES) for row in m.W1)
    assert all(row[-1] == 0.0 for row in m.W1)
    assert len(m.feature_mean) == len(FEATURE_NAMES)


# -- the live runner must survive an NN on disk ----------------------------------
def test_runner_boots_with_an_nn_model_and_has_no_online_learner():
    """The gap §2.6 left: ParamStore.load() can now hand the RUNNER a net, and the
    runner's RLS path assumes model.weights. If an NN is ever adopted and saved, the
    engine must still start -- with the online learner simply absent, not crashed."""
    from ai_investing.learning.online import RLSLearner

    X, y = _learnable_dataset(600)
    nn, _ = fit_nn(X, y, min_samples=500)
    lin = FormulaModel()

    # the exact expression runner.__init__ uses to decide whether RLS applies
    assert not hasattr(nn, "weights")
    assert hasattr(lin, "weights")
    assert RLSLearner.initialize(lin.weights, prior_confidence=50.0) is not None

    # and the two attribute reads the runner does per cycle degrade, never raise
    feats = dict(zip(FEATURE_NAMES, [1.0] * len(FEATURE_NAMES)))
    assert math.isfinite(nn.raw(feats))
    assert (dict(zip(nn.feature_names, nn.weights)) if hasattr(nn, "weights") else {}) == {}


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\nAll {len(tests)} NN challenger tests passed.")
