# A neural-net challenger for the decision formula

**Status: PLANNED, not built.** This is an implementation plan for another
engineer/agent to execute. It does not touch `brain/graph.py` edge weights and
does not change what goes live today. Read `docs/design/FORMULA.md` and
`docs/design/LEARNING.md` first — this document assumes both.

## 0. Why this document exists

We were asked "can the brain be upgraded with a neural network." The honest
answer: the current linear formula (`θ·φ`, 10 features, fit by ridge + online
RLS) isn't linear because linear is inherently better than a neural net — it's
linear because that's what the amount of independent evidence this system
produces can support without overfitting (`docs/status/BRAIN_REVIEW_2026-08-21.md`
§4h: the live audit found the whole track record yields on the order of a few
hundred independent (symbol, day) observations; a single graph edge needs
60-120 of those just to get one calibration verdict on a **1-parameter** test).
A neural net has far more parameters than the 10-weight linear formula, so with
today's data it would fit noise and *look* more authoritative while being
worse.

The resolution is not to argue about which architecture is better in the
abstract. It's to let the walk-forward gate — the same one `FormulaModel`
already has to clear — decide, on real out-of-sample evidence, whether a small
NN beats the linear champion. If it never clears the gate, that's the answer,
and it cost nothing but compute. If it does, it earned it.

**This plan has two independent tracks. Do both; neither blocks the other:**

- **Track A — grow the labeled-outcome count.** This is the actual bottleneck
  (see §1). It benefits the linear formula, the edge calibrator, and any future
  NN equally.
- **Track B — build the NN challenger mechanism.** This is the bulk of this
  document (§2 onward). It's safe to build now even while Track A's sample
  count is still small: it will simply keep losing to the linear model on the
  DSR gate until there's enough data, which is the correct behavior, not a bug.

## 1. Track A — grow the labeled-outcome count

Read `docs/status/BRAIN_REVIEW_2026-08-21.md` before touching this — it documents
exactly how the last attempt to read "the record" overcounted by 65x. Any work
here must respect the counting discipline already built (`advice_outcomes.is_primary`,
`(symbol, day)` as the unit, embargo gaps, binomial not t-tests). Concretely,
in priority order:

1. **Widen the tradable/observed universe** (`docs/design/BRAIN.md` §3.1,
   §4c) — more symbols observed daily is more independent (symbol, day) rows
   per calendar day, which is the actual scarce resource. Check
   `STOCK_WATCHLIST` / `CRYPTO_WATCHLIST` / `MACRO_WATCHLIST` for room to grow
   within what's already fetchable via `yfinance` free tier, and confirm
   `scripts/brain_audit.py --section graph`'s `resolution_pct` doesn't regress
   (adding symbols that just duplicate an existing theme's signature doesn't
   help — see BRAIN.md's "graph resolves fewer objects than it holds").
2. **Backfill history where possible.** If `brain.db` price snapshots or
   `event_outcomes` can be extended further back using already-available
   historical data (yfinance/FRED go back years; the constraint has been *when
   the brain started running*, not data availability), do it — more days is
   more independent samples without adding any new mechanism.
3. **Do not shortcut this by lowering `MIN_N` or embargo requirements.**
   That's the failure mode the 2026-08-21 review fixed. Growing `n` must mean
   growing genuine independent observations, not relaxing what counts as one.

This track has no code deliverable beyond "more data flows through the
existing pipes." It is prerequisite to the NN challenger ever winning, not to
building it.

## 2. Track B — the NN challenger

### 2.1 The interface it must satisfy

Nothing in `Backtester.run()` or `DecisionEngine.decide()` is hardcoded to
`FormulaModel` — both duck-type against it. Confirmed call sites:

- `strategy/decision.py: DecisionEngine.decide()` calls `model.raw(feats)`,
  `model.conviction(feats)`, `model.target_from_conviction(final_conv)`.
- `backtest/engine.py: Backtester.run()` reads `model.stop_loss`,
  `model.take_profit` (via `dataclasses.replace(self.risk_cfg, ...)`) and
  passes `model=model` into `RiskManager.size_orders()`.
- `strategy/risk.py: RiskManager.size_orders()` reads `model.feature_names`
  to build `phi` for the OOD gate (`RegimeGate.ood_multiplier`, which reads
  `model.feature_mean` / `model.feature_std`).

So a new model class must expose exactly this surface (mirror
`FormulaModel`'s public API in `learning/formula.py`):

```
feature_names: list[str]
gain: float
entry_threshold: float
size_scale: float
stop_loss: float
take_profit: float
version: int
fitted: bool
feature_mean: Optional[list[float]]
feature_std: Optional[list[float]]

raw(feats: dict[str, float]) -> float
conviction(feats: dict[str, float]) -> float
target_from_conviction(c: float) -> float
target_weight(feats: dict[str, float]) -> float
weight_of(name: str) -> float          # can raise/return 0.0 — see §2.4 caveat
to_dict() -> dict
from_dict(d: dict) -> "NNFormulaModel"     # classmethod
describe() -> str
clone(**overrides) -> "NNFormulaModel"
```

Because `raw()` for a linear model is interpretable as feature attribution
(`weight_of`) and for an NN it isn't in the same way, `weight_of()` on the NN
model should return **0.0 for every name** rather than raising — anything that
reads it (there is currently nothing critical that does; grep before shipping)
degrades to "no attribution available," not a crash.

### 2.2 New file: `engine/ai_investing/learning/nn_formula.py`

A small MLP, pure Python — **no numpy/torch**. `engine/requirements.txt` states
the core engine runs on the standard library alone; this must not become the
first thing that breaks that invariant. The feature dimension is 10 and the
sample counts are in the hundreds-to-low-thousands, so pure-Python forward/
backward passes are fast enough; nothing here needs a tensor library.

Architecture: **keep it small on purpose.** 10 inputs → 4-unit hidden layer
(tanh) → 1 linear output. That's `10*4 + 4 + 4*1 + 1 = 49` parameters, roughly
5x the linear model's 10 — deliberately not 10x or 100x. A bigger network is
not "the next experiment to try if this one wins"; it's a strictly worse bet
against the same data-scarcity constraint documented in §0, so don't scale it
up without a specific, data-backed reason.

```python
"""Small MLP challenger to the linear formula (learning/formula.py).

Same interface as FormulaModel (see docs/design/NN_CHALLENGER.md §2.1) so it
drops into Backtester/DecisionEngine/RiskManager unchanged. Trained by full-batch
gradient descent in pure Python — no numpy/torch (see engine/requirements.txt:
the core engine runs on the stdlib alone).

This is a CHALLENGER, never adopted automatically: WalkForwardOptimizer only
proposes it, and NN_MIN_DSR (config) sets a stricter bar than the linear
model's min_dsr, matching the project's existing rule that more model
complexity earns a *higher*, not equal, evidentiary bar (see
brain/calibration.py's MIN_N asymmetry between causal `influences` edges and
structural `member_of` edges for the same reasoning applied elsewhere).
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Optional

from ai_investing.learning.features import FEATURE_NAMES


@dataclass
class NNFormulaModel:
    feature_names: list[str] = field(default_factory=lambda: list(FEATURE_NAMES))
    hidden: int = 4
    # W1: hidden x n_features, b1: hidden ; W2: hidden (output row), b2: scalar
    W1: list[list[float]] = field(default_factory=list)
    b1: list[float] = field(default_factory=list)
    W2: list[float] = field(default_factory=list)
    b2: float = 0.0
    gain: float = 20.0
    entry_threshold: float = 0.10
    size_scale: float = 1.0
    stop_loss: float = 0.08
    take_profit: float = 0.25
    version: int = 0
    fitted: bool = False
    feature_mean: Optional[list[float]] = None   # REQUIRED for this model, not optional in practice —
    feature_std: Optional[list[float]] = None    # unlike the linear model, an untrained-scale input wrecks tanh units

    # -- forward pass ---------------------------------------------------------
    def _normalize(self, feats: dict[str, float]) -> list[float]:
        x = [feats.get(n, 0.0) for n in self.feature_names]
        if not self.feature_mean or not self.feature_std:
            return x
        return [(xi - m) / s if s > 1e-9 else 0.0
                for xi, m, s in zip(x, self.feature_mean, self.feature_std)]

    def raw(self, feats: dict[str, float]) -> float:
        if not self.W1:
            return 0.0
        x = self._normalize(feats)
        h = [math.tanh(sum(w * xi for w, xi in zip(row, x)) + b)
             for row, b in zip(self.W1, self.b1)]
        return sum(w * hi for w, hi in zip(self.W2, h)) + self.b2

    def conviction(self, feats: dict[str, float]) -> float:
        return math.tanh(self.gain * self.raw(feats))

    def target_from_conviction(self, c: float) -> float:
        sign = 1.0 if c >= 0 else -1.0
        if self.entry_threshold >= 1.0:
            return 0.0
        mag = max(0.0, abs(c) - self.entry_threshold) / (1.0 - self.entry_threshold)
        return max(-1.0, min(1.0, sign * mag * self.size_scale))

    def target_weight(self, feats: dict[str, float]) -> float:
        return self.target_from_conviction(self.conviction(feats))

    def weight_of(self, name: str) -> float:
        return 0.0   # no linear attribution for an MLP — see §2.1

    # -- (de)serialization ----------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "feature_names": self.feature_names, "hidden": self.hidden,
            "W1": self.W1, "b1": self.b1, "W2": self.W2, "b2": self.b2,
            "gain": self.gain, "entry_threshold": self.entry_threshold,
            "size_scale": self.size_scale, "stop_loss": self.stop_loss,
            "take_profit": self.take_profit, "version": self.version,
            "fitted": self.fitted, "feature_mean": self.feature_mean,
            "feature_std": self.feature_std,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "NNFormulaModel":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def describe(self) -> str:
        n_params = sum(len(r) for r in self.W1) + len(self.b1) + len(self.W2) + 1
        return (f"NN[v{self.version}{' fitted' if self.fitted else ''}] "
                f"hidden={self.hidden} params={n_params} gain={self.gain:.1f} "
                f"entry_threshold={self.entry_threshold:.3f} size_scale={self.size_scale:.2f}")

    def clone(self, **overrides) -> "NNFormulaModel":
        d = self.to_dict()
        d.update(overrides)
        return NNFormulaModel.from_dict(d)
```

### 2.3 Training: `fit_nn()` in the same file

Full-batch gradient descent, deterministic given a seed, with:

- **Feature normalization** using the training slice's own mean/std (store on
  the returned model exactly like `WalkForwardOptimizer._feature_stats` already
  does for the linear model — reuse that function, don't duplicate it).
- **L2 weight decay**, not just early stopping — with ~49 params and a few
  hundred training rows this is the main defense against memorization.
- **Early stopping on a held-out slice inside the training window** (not the
  walk-forward validation window — that one is reserved for the outer
  champion/challenger comparison, exactly as it is for the linear model. Split
  the training slice itself, e.g. last 20%, as the early-stopping set).
- **A hard minimum sample count before attempting to fit at all.** Rule of
  thumb used elsewhere in this codebase: don't fit a model with more free
  parameters than roughly `n_samples / 10` can support. With 49 params that's
  ~500 rows minimum — if `len(X) < 500`, return `(None, "insufficient data for
  NN challenger")` and let the caller skip straight to "not adopted," mirroring
  `WalkForwardOptimizer.optimize()`'s existing `"insufficient data for
  walk-forward"` early return.

```python
def fit_nn(X: list[list[float]], y: list[float], hidden: int = 4,
           lr: float = 0.05, epochs: int = 300, l2: float = 1e-2,
           seed: int = 7, min_samples: int = 500) -> tuple[Optional[NNFormulaModel], str]:
    if len(X) < min_samples:
        return None, "insufficient data for NN challenger"
    rng = random.Random(seed)
    n_val = max(20, len(X) // 5)
    X_train, y_train = X[:-n_val], y[:-n_val]
    X_val, y_val = X[-n_val:], y[-n_val:]

    fmean, fstd = _feature_stats(X_train)   # reuse backtest/walkforward.py's helper
    n_feat = len(X_train[0])

    def norm(row):
        return [(v - m) / s if s > 1e-9 else 0.0 for v, m, s in zip(row, fmean, fstd)]
    Xn_train = [norm(r) for r in X_train]
    Xn_val = [norm(r) for r in X_val]

    scale = 1.0 / math.sqrt(n_feat)
    W1 = [[rng.gauss(0, scale) for _ in range(n_feat)] for _ in range(hidden)]
    b1 = [0.0] * hidden
    W2 = [rng.gauss(0, 1.0 / math.sqrt(hidden)) for _ in range(hidden)]
    b2 = 0.0

    best_val, best_state, patience, bad_epochs = float("inf"), None, 20, 0
    for epoch in range(epochs):
        # forward + backward over the full training batch, plain SGD/GD step,
        # L2 term added to every weight gradient (not biases)
        ...  # see reference implementation notes below
        val_loss = _mse(W1, b1, W2, b2, Xn_val, y_val)
        if val_loss < best_val - 1e-6:
            best_val, best_state, bad_epochs = val_loss, (W1, b1, W2, b2), 0
        else:
            bad_epochs += 1
            if bad_epochs >= patience:
                break

    if best_state is None:
        return None, "NN training did not converge"
    W1, b1, W2, b2 = best_state
    model = NNFormulaModel(hidden=hidden, W1=W1, b1=b1, W2=W2, b2=b2,
                           feature_mean=fmean, feature_std=fstd, fitted=True)
    return model, ""
```

The `...` is deliberately left for the implementer: a plain full-batch forward/
backward pass (MSE loss, tanh hidden activation, its derivative
`1 - tanh(z)^2`) using only `math` and list comprehensions, matching the style
already established in `learning/linalg.py` and `learning/online.py`. Do not
add a numpy dependency to do this — the whole point of keeping the network at
49 parameters and a few hundred rows is that a hand-rolled loop is fast enough.

### 2.4 Wiring into the walk-forward optimizer

`backtest/walkforward.py: WalkForwardOptimizer.optimize()` currently does one
thing per window: ridge-solve a linear candidate, hyperparameter-search it,
score it on the validation slice, and average across windows into
`challenger_avg` vs the running `default_avg`. Add a **second, independent
candidate track** for the NN, evaluated the same way, so the method ends with
three tagged results per run, not two:

```python
def optimize(self, assets, bars_by_key, prior_model=None,
             min_dsr=0.60, nn_min_dsr=0.75, try_nn=False) -> dict:
    ...
    # existing linear ridge/hyperparameter search: unchanged, produces
    # best_overall (linear) exactly as today

    nn_result = None
    if try_nn:
        nn_result = self._optimize_nn(assets, aligned, start, fold, length, nn_min_dsr)

    # adoption: the linear candidate's existing rule is untouched. The NN
    # candidate additionally must beat the (already gate-cleared) linear
    # candidate's challenger_avg by a real margin, not merely clear its own
    # bar -- extra complexity has to buy something, not just avoid disqualification
    ...
```

`_optimize_nn` mirrors the existing per-window loop but calls `fit_nn(X, y)`
instead of `ridge_solve`, uses the same `self._val(...)` scoring against the
same validation windows, and computes its own deflated Sharpe with its own
`n_trials` (NN hyperparameter search, if any, is a separate trial count from
the linear one — don't pool them, that would understate the NN's multiple-
comparisons penalty).

**The adoption rule, stated precisely (this is the load-bearing part of the
whole plan):**

1. Linear candidate must independently clear `min_dsr` (0.60, unchanged) to be
   adoptable at all — exactly today's behavior.
2. NN candidate must independently clear `nn_min_dsr` (higher — default 0.75,
   configurable) to be *eligible*. This is the "higher evidentiary bar for
   higher complexity" rule from §0/§2.2, made concrete.
3. If neither clears its bar: keep `prior_model` (today's behavior, unchanged).
4. If only one clears its bar: adopt that one.
5. If both clear their bars: adopt the NN **only if** its out-of-sample Sharpe
   beats the linear candidate's by a configurable relative margin (default
   20%) — e.g. `NN_ADOPTION_MARGIN = 0.20`. Ties, and anything inside the
   margin, go to the linear model. This encodes "a neural net has to actually
   earn its opacity, not just tie" instead of leaving it to chance which one a
   `>` comparison happens to favor on a given run.

This keeps the existing linear path's behavior **completely unchanged** when
`try_nn=False` (the default) — Track B is opt-in and additive, never a
silent behavior change to what's running today.

### 2.5 Config

Add to `LearningConfig` in `engine/ai_investing/config.py`, next to the
existing `min_dsr` line:

```python
nn_challenger_enabled: bool = field(default_factory=lambda: _get_bool("LEARN_NN_ENABLED", False))
nn_min_dsr: float = field(default_factory=lambda: _get_float("LEARN_NN_MIN_DSR", 0.75))
nn_adoption_margin: float = field(default_factory=lambda: _get_float("LEARN_NN_ADOPTION_MARGIN", 0.20))
nn_hidden: int = field(default_factory=lambda: _get_int("LEARN_NN_HIDDEN", 4))
nn_min_samples: int = field(default_factory=lambda: _get_int("LEARN_NN_MIN_SAMPLES", 500))
```

Default `nn_challenger_enabled=False`. Whatever calls
`WalkForwardOptimizer.optimize()` in production (the offline curation job —
find it via `grep -rn "\.optimize(" engine/ai_investing/`) should pass
`try_nn=self.settings.learning.nn_challenger_enabled`. Until someone
deliberately flips that flag, this entire plan has zero effect on the running
system — that's intentional; it lets Track B be built, reviewed, and tested
independently of any decision to actually try it live.

### 2.6 Persistence and rollback

`ParamStore` (`learning/store.py`) currently assumes `FormulaModel` on load.
Whichever model type `optimize()` adopts needs a type tag so `ParamStore.load()`
knows which class to reconstruct:

```json
{"model_type": "linear", "model": {...}}
{"model_type": "nn", "model": {...}}
```

Add `model_type` (default `"linear"` if absent, for backward compatibility
with every `formula.json` written before this change) and dispatch
`FormulaModel.from_dict` vs `NNFormulaModel.from_dict` accordingly. Keep the
append-only version log `ParamStore` already writes — an NN adoption must be
just as visible and just as revertible in that log as a linear one. Do **not**
add any online (RLS-style) update path for the NN in this phase — RLS's linear
update rule doesn't apply to a nonlinear model, and building a safe online
update for an MLP is a separate, harder problem than this plan covers. The NN
challenger is walk-forward-only (curated offline, like the linear model's
*hyperparameters* already are); it does not mature between offline runs the
way `RLSLearner` matures the linear θ.

### 2.7 Testing

New file `engine/tests/test_nn_formula.py` — **must have a `__main__` block**
(project convention: `engine/tests/` files without one silently report green on
the box without ever running — see memory note on this exact failure mode).
Cover:

1. `NNFormulaModel.to_dict()` / `from_dict()` round-trips exactly (weights,
   biases, feature_mean/std, hyperparameters).
2. `raw()` on an unfit model (`W1=[]`) returns `0.0` and doesn't raise —
   mirrors `FormulaModel`'s safe default behavior.
3. `fit_nn()` with `len(X) < min_samples` returns `(None, "insufficient data...")`
   without attempting to train.
4. `fit_nn()` on a small synthetic dataset with a genuine learnable linear
   relationship (e.g. `y = 0.02*momentum - 0.01*sentiment + noise`) converges
   to a validation MSE below a naive baseline (predicting the mean) — proves
   the training loop actually learns something, not just that it runs.
5. Determinism: same `seed` → bit-identical `W1/b1/W2/b2` across two calls.
6. `WalkForwardOptimizer.optimize(..., try_nn=True)` on synthetic data with
   `len(X)` deliberately below `nn_min_samples`: confirms it falls through to
   the linear-only path and never raises, i.e. Track B degrades safely on
   exactly the small-sample regime this system currently lives in.
7. A test that the **adoption rule in §2.4** is followed exactly — construct
   fake `(dsr_linear, dsr_nn, sharpe_linear, sharpe_nn)` tuples covering all
   four cases (neither clears, only linear, only NN, both — margin met and
   margin missed) and assert the right model is chosen each time. This is the
   single most important test in this plan; get it in before anything else.

### 2.8 Reporting

Extend `scripts/brain_audit.py`'s `learning` section (or add a
`scripts/nn_challenger_report.py` if that file is getting crowded) to print,
whenever a `formula.json` with `model_type: "nn"` exists or an NN run has been
attempted:

- `n_params`, `n_training_samples`, and their ratio (the thing §2.3's minimum
  sample rule exists to protect).
- Per-window linear vs NN Sharpe, and both DSRs, side by side — not just the
  winner. A report that only shows the winner is exactly the "brochure"
  failure mode `brain_audit.py`'s own docstring warns about for symbol
  tracking (§ HOW TO READ THIS: "A track record that reports only its winners
  is a brochure").
- Which adoption case (§2.4, cases 1-5) fired on the most recent run, in
  plain language, not just the resulting model type.

## 3. Explicit non-goals for this phase

- **Do not touch `brain/graph.py` edge weights with a trainable/backprop
  mechanism.** That's a harder, separate problem (learning a weight per graph
  edge needs even more independent samples than this 10-feature MLP, and the
  existing univariate edge calibrator in `brain/calibration.py` is already
  data-starved at `MIN_N=60-120` per edge — see BRAIN.md §4d).
- **Do not give the NN an online/live update path.** Walk-forward-curated
  only, in this phase (§2.6).
- **Do not scale the network up** (more hidden units, more layers) as a
  follow-on "if this works, let's go bigger" move without first re-checking
  Track A's sample count against the `n_samples / 10 >= n_params` rule this
  plan uses in §2.3. Bigger is not the next experiment; more data is.
- **Do not change the default behavior of anything currently running.**
  `nn_challenger_enabled` defaults to `False`; every new code path is additive
  and gated behind it.

## 4. Definition of done

- `NNFormulaModel` implements the full interface in §2.1 and passes the tests
  in §2.7.
- `WalkForwardOptimizer.optimize(try_nn=True)` runs both candidate tracks and
  applies the exact adoption rule in §2.4, with `try_nn=False` (default)
  behaving identically to the code before this change.
- `ParamStore` round-trips both model types via `model_type`, old
  `formula.json` files with no `model_type` key still load as `FormulaModel`.
- `scripts/brain_audit.py` (or the new report script) shows linear-vs-NN
  side by side whenever an NN run has been attempted.
- A dry run with `LEARN_NN_ENABLED=true` against current production history
  is executed and its `nn_challenger_report` output is attached to the PR —
  expected result, given Track A's current sample size, is "insufficient data"
  or "NN did not clear nn_min_dsr." That is a successful outcome for this
  phase, not a failure: it means the gate is doing its job.
