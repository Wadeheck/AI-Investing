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

from ai_investing.indicators import pct_returns, stdev
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
    # Best early-stopping loss this net reached, on its own purged out-of-time slice.
    # Carried on the model so a caller can choose BETWEEN nets (e.g. which L2) without
    # scoring each one on the walk-forward validation window -- every candidate scored
    # there is a trial the deflated Sharpe has to pay for. Diagnostic only: nothing in
    # the decision path reads it.
    val_loss: Optional[float] = None

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
            "val_loss": self.val_loss,
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
# build_nn_samples, and twenty symbols on the same day are one market moving,
# not twenty independent draws. Clearing 500 is necessary, not sufficient -- the real
# evidence count is the independent (symbol, day) count that
# docs/status/BRAIN_REVIEW_2026-08-21.md establishes the discipline for, and it is
# always smaller. The deflated-Sharpe gate, not this constant, is what actually stops
# an overfit net being adopted.
MIN_SAMPLES = 500
MIN_XS_BREADTH = 3


def build_nn_samples(backtester, assets, bars_by_key: dict) -> tuple[list[list[float]], list[float], list[int]]:
    """Build NN-only risk-adjusted, cross-sectionally demeaned training labels.

    This intentionally does not extend ``Backtester.build_samples``: the live and
    linear paths retain their original raw-forward-return labels and API.  ``t_index``
    identifies the common, aligned bar time for every row and is used to create the
    purged early-stopping split in ``fit_nn``.
    """
    aligned, length = backtester._aligned(bars_by_key)
    asset_by_key = {asset.key: asset for asset in assets}
    X: list[list[float]] = []
    y: list[float] = []
    t_index: list[int] = []

    for key, bars in aligned.items():
        asset = asset_by_key.get(key)
        if asset is None:
            continue
        for t in range(backtester.warmup, length - backtester.horizon):
            results = [signal.evaluate(asset, bars[:t + 1], {}) for signal in backtester.signals]
            features = backtester.fx.build(results, bars[:t + 1])
            forward_return = ((bars[t + backtester.horizon].close - bars[t].close) / bars[t].close
                              if bars[t].close else 0.0)
            returns = pct_returns([bar.close for bar in bars[max(0, t - 20):t + 1]])
            sigma = stdev(returns) * (backtester.horizon ** 0.5)
            label = max(-3.0, min(3.0, forward_return / sigma)) if sigma > 1e-9 else 0.0
            X.append(backtester.fx.vector(features))
            y.append(label)
            t_index.append(t)

    by_time: dict[int, list[int]] = {}
    for row, t in enumerate(t_index):
        by_time.setdefault(t, []).append(row)
    for rows in by_time.values():
        if len(rows) < MIN_XS_BREADTH:
            continue
        average = sum(y[row] for row in rows) / len(rows)
        for row in rows:
            y[row] -= average
    return X, y, t_index


def _forward(W1, b1, W2, b2, x):
    h = [math.tanh(sum(w * xi for w, xi in zip(row, x)) + b) for row, b in zip(W1, b1)]
    return h, sum(w * hi for w, hi in zip(W2, h)) + b2


def _mse(W1, b1, W2, b2, X, y) -> float:
    if not X:
        return float("inf")
    return sum((_forward(W1, b1, W2, b2, x)[1] - t) ** 2 for x, t in zip(X, y)) / len(X)


def _time_split(t_index: list[int], purge: int) -> tuple[list[int], list[int]]:
    """Rows for training and for early stopping, split by TIME with a purge gap.

    The validation side is the last ~20% of distinct timestamps. The training side
    stops `purge` timestamps before that boundary, because a row at t carries an
    h-day forward label that reaches to t+h: without the gap the last h training
    labels are drawn from the validation period, and early stopping then selects
    its epoch using the very data it is supposed to be held out from. Same reason
    WalkForwardOptimizer embargoes its own train/validation boundary.
    """
    ts = sorted(set(t_index))
    cut = ts[max(0, int(len(ts) * 0.8) - 1)]
    train = [i for i, t in enumerate(t_index) if t <= cut - purge]
    val = [i for i, t in enumerate(t_index) if t > cut]
    return train, val


def fit_nn(X: list[list[float]], y: list[float], hidden: int = 4,
           lr: float = 0.05, epochs: int = 300, l2: float = 1e-2,
           seed: int = 7, min_samples: int = MIN_SAMPLES,
           t_index: Optional[list[int]] = None, purge: int = 0
           ) -> tuple[Optional[NNFormulaModel], str]:
    """Full-batch gradient descent, deterministic given `seed`.

    Returns (model, "") or (None, reason). Refusing to fit is a normal outcome, not an
    error: with fewer than `min_samples` rows a 49-parameter net memorizes, and a
    memorized net that clears a Sharpe gate by luck is the exact failure this whole
    challenger apparatus exists to prevent.

    Early stopping never touches the walk-forward validation window — that one is
    reserved for the outer champion/challenger comparison, exactly as it is for the
    linear model. It uses a slice of the TRAINING data instead, and HOW that slice is
    chosen is the whole point of `t_index`:

      - With `t_index` (the bar index of each row, from `build_nn_samples`)
        the slice is the last ~20% of timestamps, with a `purge`-length gap. This is
        what you want, and callers inside the optimizer always pass it.

      - Without it, the slice falls back to the last 20% of ROWS. **That is a symbol
        split, not a time split**, because `build_samples` emits rows symbol-major:
        all of symbol A's history, then all of symbol B's. On the live 22+2 universe
        that made the last 598 of 2992 rows the final ~4.4 symbols in dict-insertion
        order — i.e. both crypto names plus a couple of trailing stocks — so the net's
        epoch selection was decided by BTC/ETH over the same calendar period it trained
        on. Contemporaneous and correlated, so validation loss tracked training loss
        and the patience counter barely bit. The fallback is kept only so a caller with
        no notion of time (synthetic data in the tests) still fits.
    """
    if len(X) < min_samples or len(X) != len(y):
        return None, "insufficient data for NN challenger"

    if t_index is not None and len(t_index) == len(X):
        tr, va = _time_split(t_index, purge)
        if len(tr) < 2 or len(va) < 20:
            return None, "insufficient data for NN challenger"
        X_train, y_train = [X[i] for i in tr], [y[i] for i in tr]
        X_val, y_val = [X[i] for i in va], [y[i] for i in va]
    else:
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

    # DERIVE gain rather than searching it. conviction = tanh(gain * raw), so gain is
    # purely a scale: the right value is whatever makes `raw` order-unity, and that is
    # readable straight off the training predictions. Searching it instead costs a
    # 5-way axis in the outer hyperparameter draw, and every draw scored on the
    # validation window is a trial the deflated Sharpe pays for (see _optimize_nn).
    # It is also required for NN-specific volatility-scaled labels, whose output is in
    # volatility units, so the hand-set gain=20.0 -- chosen for a model whose output
    # was in return units -- would saturate tanh and make every conviction ±1.
    preds = [_forward(W1, b1, W2, b2, x)[1] for x in Xn_train]
    mu = sum(preds) / len(preds)
    sd = (sum((p - mu) ** 2 for p in preds) / max(1, len(preds) - 1)) ** 0.5
    gain = 1.0 / sd if sd > 1e-9 else 1.0

    return NNFormulaModel(hidden=hidden, W1=W1, b1=b1, W2=W2, b2=b2, gain=gain,
                          feature_mean=fmean, feature_std=fstd, fitted=True,
                          val_loss=best_val), ""
