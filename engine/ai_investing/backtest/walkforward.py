"""Walk-forward optimizer — the offline curation of θ.

For each expanding window it fits θ by ridge regression on the training slice, searches
hyperparameters for the best out-of-sample Sharpe on the *next* (unseen) slice, and
only adopts the challenger if it beats the incumbent formula averaged across windows
(champion/challenger). That out-of-sample gate is the anti-overfitting safeguard.
"""
from __future__ import annotations

import random

from ai_investing.backtest.engine import Backtester
from ai_investing.learning.features import FEATURE_NAMES
from ai_investing.learning.formula import FormulaModel
from ai_investing.learning.linalg import ridge_solve
from ai_investing.learning.objective import mean

HYPER_SPACE = {
    "gain": [8.0, 15.0, 25.0, 40.0, 60.0],
    "entry_threshold": [0.05, 0.10, 0.15, 0.20],
    "size_scale": [0.6, 0.8, 1.0, 1.2],
    "stop_loss": [0.05, 0.08, 0.12],
    "take_profit": [0.15, 0.25, 0.40],
}
REG_OPTIONS = [1e-3, 1e-2, 1e-1]


class WalkForwardOptimizer:
    def __init__(self, backtester: Backtester | None = None, n_windows: int = 3,
                 search: int = 16, seed: int = 7):
        self.bt = backtester or Backtester()
        self.n_windows = n_windows
        self.search = search
        self.rng = random.Random(seed)

    def _val(self, assets, aligned, model, train_end, val_end):
        return self.bt.run(model, assets, aligned, sim_start=train_end, sim_end=val_end)

    def optimize(self, assets, bars_by_key, prior_model: FormulaModel | None = None) -> dict:
        prior_model = prior_model or FormulaModel()
        aligned, length = self.bt._aligned(bars_by_key)
        start = self.bt.warmup
        fold = (length - start) // (self.n_windows + 1)
        if fold < self.bt.horizon + 10:
            return {"model": prior_model, "adopted": False, "windows": [],
                    "reason": "insufficient data for walk-forward",
                    "challenger_avg": 0.0, "default_avg": 0.0}

        windows = []
        default_scores, challenger_scores = [], []
        best_overall, best_val = None, -float("inf")

        for w in range(self.n_windows):
            train_end = start + fold * (w + 1)
            val_end = min(length - 1, train_end + fold)

            train_bars = {k: v[:train_end] for k, v in aligned.items()}
            X, y = self.bt.build_samples(assets, train_bars)

            local_best, local_score = None, -float("inf")
            for _ in range(self.search):
                reg = self.rng.choice(REG_OPTIONS)
                theta = ridge_solve(X, y, reg)
                if not theta:
                    continue
                hyper = {k: self.rng.choice(v) for k, v in HYPER_SPACE.items()}
                cand = FormulaModel(feature_names=list(FEATURE_NAMES), weights=theta, fitted=True, **hyper)
                score = self._val(assets, aligned, cand, train_end, val_end).metrics["sharpe"]
                if score > local_score:
                    local_score, local_best = score, cand

            default_score = self._val(assets, aligned, prior_model, train_end, val_end).metrics["sharpe"]
            default_scores.append(default_score)
            challenger_scores.append(local_score if local_best else default_score)
            windows.append({"window": w, "train_end": train_end, "val_end": val_end,
                            "default_sharpe": round(default_score, 3),
                            "challenger_sharpe": round(local_score, 3)})
            if local_best and local_score > best_val:
                best_val, best_overall = local_score, local_best

        challenger_avg = mean(challenger_scores)
        default_avg = mean(default_scores)
        adopt = best_overall is not None and challenger_avg > default_avg
        chosen = best_overall if adopt else prior_model
        chosen.fitted = bool(adopt)
        return {"model": chosen, "adopted": adopt, "windows": windows,
                "challenger_avg": round(challenger_avg, 3), "default_avg": round(default_avg, 3)}
