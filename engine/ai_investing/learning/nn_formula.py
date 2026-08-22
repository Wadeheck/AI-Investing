"""Small MLP challenger to the linear formula (learning/formula.py).

Same interface as FormulaModel (see docs/design/NN_CHALLENGER.md §2.1) so it drops
into Backtester/DecisionEngine/RiskManager unchanged. Trained by full-batch gradient
descent in pure Python — no numpy/torch (see engine/requirements.txt: the core engine
runs on the stdlib alone).

This is a CHALLENGER, never adopted automatically: WalkForwardOptimizer only proposes
it, and nn_min_dsr (config) sets a stricter bar than the linear model's min_dsr,
matching the project's existing rule that more model complexity earns a *higher*, not
equal, evidentiary bar (see brain/calibration.py's MIN_N asymmetry between causal
`influences` edges and structural `member_of` edges — same reasoning applied elsewhere).

Kept small ON PURPOSE: 10 -> 4 -> 1 is 49 parameters, ~5x the linear model's 10. The
binding constraint is independent (symbol, day) observations, not capacity; a bigger
net is a strictly worse bet against the same scarcity. See docs/design/NN_CHALLENGER.md
§0 and §3 before touching `hidden`.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Optional

from ai_investing.learning.features import FEATURE_NAMES, feature_stats


@dataclass
class NNFormulaModel:
    feature_names: list[str] = field(default_factory=lambda: list(FEATURE_NAMES))
    hidden: int = 4
    # W1: hidden x n_features, b1: hidden ; W2: hidden (the single output row), b2: scalar
    W1: list[list[float]] = field(default_factory=list)
    b1: list[float] = field(default_factory=list)
    W2: list[float] = field(default_factory=list)
    b2: float = 0.0
    gain: float = 20.0
    entry_threshold: float = 0.10   # deadzone: no trade below this conviction
    size_scale: float = 1.0
    stop_loss: float = 0.08
    take_profit: float = 0.25
    version: int = 0
    fitted: bool = False
    # REQUIRED in practice for this model, unlike the linear one: an unnormalized input
    # saturates the tanh units and the net predicts a constant.
    feature_mean: Optional[list[float]] = None
    feature_std: Optional[list[float]] = None

    # -- the formula --------------------------------------------------------
    def _normalize(self, feats: dict[str, float]) -> list[float]:
        x = [feats.get(n, 0.0) for n in self.feature_names]
        if not self.feature_mean or not self.feature_std:
            return x
        return [(xi - m) / s if s > 1e-9 else 0.0
                for xi, m, s in zip(x, self.feature_mean, self.feature_std)]

    def raw(self, feats: dict[str, float]) -> float:
        if not self.W1:
            return 0.0   # unfit net is inert, same safe default as an all-zero θ
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
        # An MLP has no per-feature weight to report. Returning 0.0 rather than raising
        # means anything reading attribution degrades to "none available", not a crash.
        return 0.0

    @property
    def n_params(self) -> int:
        return sum(len(r) for r in self.W1) + len(self.b1) + len(self.W2) + 1

    # -- (de)serialization --------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "feature_names": self.feature_names,
            "hidden": self.hidden,
            "W1": self.W1,
            "b1": self.b1,
            "W2": self.W2,
            "b2": self.b2,
            "gain": self.gain,
            "entry_threshold": self.entry_threshold,
            "size_scale": self.size_scale,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "version": self.version,
            "fitted": self.fitted,
            "feature_mean": self.feature_mean,
            "feature_std": self.feature_std,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "NNFormulaModel":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def describe(self) -> str:
        return (f"NN[v{self.version}{' fitted' if self.fitted else ''}] "
                f"hidden={self.hidden} params={self.n_params} gain={self.gain:.1f} "
                f"entry_threshold={self.entry_threshold:.3f} size_scale={self.size_scale:.2f} "
                f"stop={self.stop_loss:.3f} take={self.take_profit:.3f}")

    def clone(self, **overrides) -> "NNFormulaModel":
        d = self.to_dict()
        d.update(overrides)
        return NNFormulaModel.from_dict(d)


# -- training ---------------------------------------------------------------
# Free parameters must stay under roughly n_samples/10 (the same rule of thumb the
# rest of this codebase uses for how much evidence a fit needs). 49 params -> ~500 rows.
#
# Read this as a floor, not a licence: a "sample" here is one (symbol, day) row out of
# Backtester.build_samples, and twenty symbols on the same day are one market moving,
# not twenty independent draws. Clearing 500 is necessary, not sufficient -- the real
# evidence count is the independent (symbol, day) count that
# docs/status/BRAIN_REVIEW_2026-08-21.md establishes the discipline for, and it is
# always smaller. The deflated-Sharpe gate, not this constant, is what actually stops
# an overfit net being adopted.
MIN_SAMPLES = 500


def _forward(W1, b1, W2, b2, x):
    h = [math.tanh(sum(w * xi for w, xi in zip(row, x)) + b) for row, b in zip(W1, b1)]
    return h, sum(w * hi for w, hi in zip(W2, h)) + b2


def _mse(W1, b1, W2, b2, X, y) -> float:
    if not X:
        return float("inf")
    return sum((_forward(W1, b1, W2, b2, x)[1] - t) ** 2 for x, t in zip(X, y)) / len(X)


def fit_nn(X: list[list[float]], y: list[float], hidden: int = 4,
           lr: float = 0.05, epochs: int = 300, l2: float = 1e-2,
           seed: int = 7, min_samples: int = MIN_SAMPLES
           ) -> tuple[Optional[NNFormulaModel], str]:
    """Full-batch gradient descent, deterministic given `seed`.

    Returns (model, "") or (None, reason). Refusing to fit is a normal outcome, not an
    error: with fewer than `min_samples` rows a 49-parameter net memorizes, and a
    memorized net that clears a Sharpe gate by luck is the exact failure this whole
    challenger apparatus exists to prevent.

    Early stopping uses the LAST 20% of the training slice, not the walk-forward
    validation window — that one is reserved for the outer champion/challenger
    comparison, exactly as it is for the linear model.
    """
    if len(X) < min_samples or len(X) != len(y):
        return None, "insufficient data for NN challenger"
    n_val = max(20, len(X) // 5)
    if len(X) - n_val < 2:
        return None, "insufficient data for NN challenger"

    X_train, y_train = X[:-n_val], y[:-n_val]
    X_val, y_val = X[-n_val:], y[-n_val:]

    fmean, fstd = feature_stats(X_train)
    n_feat = len(X_train[0])

    def norm(row):
        return [(v - m) / s if s > 1e-9 else 0.0 for v, m, s in zip(row, fmean, fstd)]

    Xn_train = [norm(r) for r in X_train]
    Xn_val = [norm(r) for r in X_val]

    rng = random.Random(seed)
    scale = 1.0 / math.sqrt(n_feat)
    W1 = [[rng.gauss(0, scale) for _ in range(n_feat)] for _ in range(hidden)]
    b1 = [0.0] * hidden
    W2 = [rng.gauss(0, 1.0 / math.sqrt(hidden)) for _ in range(hidden)]
    b2 = 0.0

    n = len(Xn_train)
    best_val, best_state, patience, bad_epochs = float("inf"), None, 20, 0

    for _ in range(epochs):
        gW1 = [[0.0] * n_feat for _ in range(hidden)]
        gb1 = [0.0] * hidden
        gW2 = [0.0] * hidden
        gb2 = 0.0
        for x, t in zip(Xn_train, y_train):
            h, out = _forward(W1, b1, W2, b2, x)
            d = 2.0 * (out - t) / n            # dLoss/dout, averaged over the batch
            gb2 += d
            for j in range(hidden):
                gW2[j] += d * h[j]
                dz = d * W2[j] * (1.0 - h[j] * h[j])   # tanh' = 1 - tanh^2
                gb1[j] += dz
                row = gW1[j]
                for k in range(n_feat):
                    row[k] += dz * x[k]

        # L2 on weights only, never biases: penalizing the intercept just shrinks the
        # net's mean prediction toward zero without buying any capacity control.
        for j in range(hidden):
            gW2[j] += 2.0 * l2 * W2[j]
            for k in range(n_feat):
                gW1[j][k] += 2.0 * l2 * W1[j][k]

        for j in range(hidden):
            W2[j] -= lr * gW2[j]
            b1[j] -= lr * gb1[j]
            for k in range(n_feat):
                W1[j][k] -= lr * gW1[j][k]
        b2 -= lr * gb2

        val_loss = _mse(W1, b1, W2, b2, Xn_val, y_val)
        if not math.isfinite(val_loss):
            break   # diverged; keep whatever best_state we had, if any
        if val_loss < best_val - 1e-12:
            best_val = val_loss
            best_state = ([row[:] for row in W1], b1[:], W2[:], b2)
            bad_epochs = 0
        else:
            bad_epochs += 1
            if bad_epochs >= patience:
                break

    if best_state is None:
        return None, "NN training did not converge"
    W1, b1, W2, b2 = best_state
    return NNFormulaModel(hidden=hidden, W1=W1, b1=b1, W2=W2, b2=b2,
                          feature_mean=fmean, feature_std=fstd, fitted=True), ""
