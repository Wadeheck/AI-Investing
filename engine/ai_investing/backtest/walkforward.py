"""Walk-forward optimizer — the offline curation of θ, done honestly.

For each expanding window it fits θ by ridge on the training slice, then searches
hyperparameters for the best Sharpe on the *next* slice. Two anti-overfitting guards
beyond plain champion/challenger:

  - EMBARGO: a gap (= label horizon) between train and validation so the h-day
    forward-return label of the last training sample can't leak into validation.
  - DEFLATED SHARPE: the winner is the best of many trials, so its Sharpe is biased
    upward. We deflate it by the number of trials and only adopt if the probability
    the true Sharpe is positive (DSR) clears a threshold. This is what stops the
    optimizer from adopting the max-of-noise.
"""
from __future__ import annotations

import random

from ai_investing.backtest.engine import Backtester
from ai_investing.learning.features import FEATURE_NAMES
from ai_investing.learning.formula import FormulaModel
from ai_investing.learning.linalg import ridge_solve
from ai_investing.learning.objective import deflated_sharpe_ratio, mean

HYPER_SPACE = {
    "gain": [8.0, 15.0, 25.0, 40.0, 60.0],
    "entry_threshold": [0.05, 0.10, 0.15, 0.20],
    "size_scale": [0.6, 0.8, 1.0, 1.2],
    "stop_loss": [0.05, 0.08, 0.12],
    "take_profit": [0.15, 0.25, 0.40],
}
REG_OPTIONS = [1e-3, 1e-2, 1e-1]


def _feature_stats(X: list[list[float]]):
    if not X:
        return None, None
    n, d = len(X), len(X[0])
    fmean = [sum(row[j] for row in X) / n for j in range(d)]
    fstd = []
    for j in range(d):
        m = fmean[j]
        v = sum((row[j] - m) ** 2 for row in X) / max(1, n - 1)
        fstd.append(v ** 0.5)
    return fmean, fstd


class WalkForwardOptimizer:
    def __init__(self, backtester: Backtester | None = None, n_windows: int = 3,
                 search: int = 16, seed: int = 7, embargo: int | None = None):
        self.bt = backtester or Backtester()
        self.n_windows = n_windows
        self.search = search
        self.rng = random.Random(seed)
        self.embargo = self.bt.horizon if embargo is None else embargo

    def _val(self, assets, aligned, model, sim_start, sim_end):
        return self.bt.run(model, assets, aligned, sim_start=sim_start, sim_end=sim_end)

    def _bounds(self, w: int, start: int, fold: int, length: int):
        train_end = start + fold * (w + 1)
        val_start = min(length - 1, train_end + self.embargo)   # embargo gap
        val_end = min(length - 1, train_end + fold)
        return train_end, val_start, val_end

    def optimize(self, assets, bars_by_key, prior_model: FormulaModel | None = None,
                 min_dsr: float = 0.60) -> dict:
        prior_model = prior_model or FormulaModel()
        aligned, length = self.bt._aligned(bars_by_key)
        start = self.bt.warmup
        fold = (length - start) // (self.n_windows + 1)
        if fold < self.bt.horizon + self.embargo + 10:
            return {"model": prior_model, "adopted": False, "windows": [],
                    "reason": "insufficient data for walk-forward",
                    "challenger_avg": 0.0, "default_avg": 0.0, "dsr": 0.0, "n_trials": 0}

        windows, default_scores, challenger_scores = [], [], []
        best_overall, best_val, n_trials = None, -float("inf"), 0

        for w in range(self.n_windows):
            train_end, val_start, val_end = self._bounds(w, start, fold, length)
            X, y = self.bt.build_samples(assets, {k: v[:train_end] for k, v in aligned.items()})
            fmean, fstd = _feature_stats(X)

            local_best, local_score = None, -float("inf")
            for _ in range(self.search):
                theta = ridge_solve(X, y, self.rng.choice(REG_OPTIONS))
                if not theta:
                    continue
                hyper = {k: self.rng.choice(v) for k, v in HYPER_SPACE.items()}
                cand = FormulaModel(feature_names=list(FEATURE_NAMES), weights=theta,
                                    fitted=True, feature_mean=fmean, feature_std=fstd, **hyper)
                n_trials += 1
                score = self._val(assets, aligned, cand, val_start, val_end).metrics["sharpe"]
                if score > local_score:
                    local_score, local_best = score, cand

            default_score = self._val(assets, aligned, prior_model, val_start, val_end).metrics["sharpe"]
            default_scores.append(default_score)
            challenger_scores.append(local_score if local_best else default_score)
            windows.append({"window": w, "train_end": train_end, "val_end": val_end,
                            "default_sharpe": round(default_score, 3),
                            "challenger_sharpe": round(local_score, 3)})
            if local_best and local_score > best_val:
                best_val, best_overall = local_score, local_best

        challenger_avg, default_avg = mean(challenger_scores), mean(default_scores)

        # Deflated Sharpe on the winner's out-of-sample returns, penalized by #trials.
        dsr = 0.0
        if best_overall is not None:
            oos: list[float] = []
            for w in range(self.n_windows):
                _, vs, ve = self._bounds(w, start, fold, length)
                oos += self._val(assets, aligned, best_overall, vs, ve).returns
            dsr = deflated_sharpe_ratio(oos, n_trials)

        adopt = best_overall is not None and challenger_avg > default_avg and dsr >= min_dsr
        chosen = best_overall if adopt else prior_model
        chosen.fitted = bool(adopt)
        return {"model": chosen, "adopted": adopt, "windows": windows,
                "challenger_avg": round(challenger_avg, 3), "default_avg": round(default_avg, 3),
                "dsr": round(dsr, 3), "n_trials": n_trials, "min_dsr": min_dsr}
