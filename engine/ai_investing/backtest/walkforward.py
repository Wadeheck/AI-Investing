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
from ai_investing.learning.features import FEATURE_NAMES, feature_stats
from ai_investing.learning.formula import FormulaModel
from ai_investing.learning.linalg import ridge_solve
from ai_investing.learning.nn_formula import MIN_SAMPLES, NNFormulaModel, build_nn_samples, fit_nn
from ai_investing.learning.objective import deflated_sharpe_ratio, mean

HYPER_SPACE = {
    "gain": [8.0, 15.0, 25.0, 40.0, 60.0],
    "entry_threshold": [0.05, 0.10, 0.15, 0.20],
    "size_scale": [0.6, 0.8, 1.0, 1.2],
    "stop_loss": [0.05, 0.08, 0.12],
    "take_profit": [0.15, 0.25, 0.40],
}
REG_OPTIONS = [1e-3, 1e-2, 1e-1]

# The NN challenger's own search space. Its trial count is deliberately NOT pooled
# with the linear model's: pooling would understate the multiple-comparisons penalty
# each candidate has to pay in its own deflated Sharpe.
NN_L2_OPTIONS = [1e-3, 1e-2, 1e-1]


def adoption_decision(linear_ok: bool, nn_ok: bool, sharpe_linear: float,
                      sharpe_nn: float, margin: float) -> str:
    """Which candidate wins — "linear", "nn", or "none". docs/design/NN_CHALLENGER.md §2.4.

    The five cases, in order: (1)/(2) each candidate clears its OWN deflated-Sharpe bar
    independently — the NN's is higher, because more complexity earns a higher
    evidentiary bar, not an equal one. (3) neither clears -> keep the incumbent.
    (4) exactly one clears -> it wins. (5) both clear -> the NN wins only by beating
    the linear model by `margin` in relative terms; ties and anything inside the margin
    go to the linear model, which is the interpretable one. A neural net has to earn
    its opacity, not merely avoid disqualification.

    The margin is relative to |sharpe_linear| rather than sharpe_linear so it stays a
    genuine hurdle when the linear Sharpe is negative — `sharpe_linear * (1 + margin)`
    would LOWER the bar there, which is exactly backwards.
    """
    if not linear_ok and not nn_ok:
        return "none"
    if linear_ok and not nn_ok:
        return "linear"
    if nn_ok and not linear_ok:
        return "nn"
    required = sharpe_linear + margin * abs(sharpe_linear)
    return "nn" if sharpe_nn > required else "linear"


ADOPTION_CASE_TEXT = {
    "none": "case 3: neither candidate cleared its DSR bar -- kept the incumbent",
    "linear_only": "case 4: only the linear candidate cleared its bar -- adopted linear",
    "nn_only": "case 4: only the NN candidate cleared its bar -- adopted NN",
    "both_nn": "case 5: both cleared; NN beat linear by more than the margin -- adopted NN",
    "both_linear": "case 5: both cleared; NN did not beat linear by the margin -- kept linear",
    "no_nn": "NN challenger not run (try_nn=False)",
    "nn_unfit": "NN challenger ran but never fit (see nn_reason) -- linear rule only",
}




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
                 min_dsr: float = 0.60, try_nn: bool = False, nn_min_dsr: float = 0.75,
                 nn_adoption_margin: float = 0.20, nn_hidden: int = 4,
                 nn_min_samples: int = MIN_SAMPLES) -> dict:
        """Curate the formula out-of-sample. With try_nn=False (the default) this is
        byte-for-byte the behavior that shipped before the NN challenger existed: the
        second candidate track is opt-in and additive, never a silent change to what is
        running today. See docs/design/NN_CHALLENGER.md §2.4."""
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
            fmean, fstd = feature_stats(X)

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

        linear_ok = best_overall is not None and challenger_avg > default_avg and dsr >= min_dsr

        nn = None
        if try_nn:
            nn = self._optimize_nn(assets, aligned, start, fold, length, default_scores,
                                   nn_hidden, nn_min_samples, prior_model)

        out = {"model": None, "adopted": False, "windows": windows,
               "challenger_avg": round(challenger_avg, 3), "default_avg": round(default_avg, 3),
               "dsr": round(dsr, 3), "n_trials": n_trials, "min_dsr": min_dsr,
               "model_type": "linear"}

        if nn is None:
            # Untouched pre-NN path: the linear rule alone decides.
            adopt = linear_ok
            chosen = best_overall if adopt else prior_model
            chosen.fitted = bool(adopt)
            out.update({"model": chosen, "adopted": adopt,
                        "adoption_case": ADOPTION_CASE_TEXT["no_nn"]})
            return out

        nn_ok = (nn["model"] is not None and nn["challenger_avg"] > default_avg
                 and nn["dsr"] >= nn_min_dsr)
        winner = adoption_decision(linear_ok, nn_ok, challenger_avg, nn["challenger_avg"],
                                   nn_adoption_margin)
        if nn["model"] is None:
            # The NN never produced a candidate at all, so no comparison happened.
            # Say that, rather than reporting a linear win over an opponent that
            # never showed up.
            case = ADOPTION_CASE_TEXT["nn_unfit"]
        elif winner == "none":
            case = ADOPTION_CASE_TEXT["none"]
        elif linear_ok and nn_ok:
            case = ADOPTION_CASE_TEXT["both_nn" if winner == "nn" else "both_linear"]
        else:
            case = ADOPTION_CASE_TEXT["linear_only" if winner == "linear" else "nn_only"]

        chosen = {"linear": best_overall, "nn": nn["model"]}.get(winner) or prior_model
        adopt = winner != "none"
        chosen.fitted = bool(adopt)
        out.update({
            "model": chosen, "adopted": adopt, "model_type": winner if adopt else "linear",
            "adoption_case": case, "linear_ok": linear_ok, "nn_ok": nn_ok,
            "nn_adoption_margin": nn_adoption_margin, "nn_min_dsr": nn_min_dsr,
            "nn_challenger_avg": nn["challenger_avg"], "nn_dsr": nn["dsr"],
            "nn_n_trials": nn["n_trials"], "nn_windows": nn["windows"],
            "nn_reason": nn["reason"], "nn_train_samples": nn["train_samples"],
            "nn_windows_fit": nn["windows_fit"],
            "nn_n_params": nn["n_params"],
            # The fitted net itself, exposed WIN OR LOSE.
            #
            # ADOPTION and SHADOW-PERSISTENCE are different questions and were
            # previously conflated by `model` being the only way out: a net that
            # the deflated-Sharpe gate refused was unreachable, so it could not
            # even be watched. Refusing to let it TRADE is the gate doing its
            # job; refusing to let it be RECORDED just means nobody ever finds
            # out whether the refusal was right.
            #
            # Nothing downstream may treat this as adopted — `adopted` and
            # `model_type` are unchanged above, and the only writer of this
            # object refuses any path outside an `nn_shadow` directory.
            "nn_model": nn["model"],
        })
        return out

    def _optimize_nn(self, assets, aligned, start, fold, length, default_scores,
                     hidden: int, min_samples: int, prior_model) -> dict:
        """The NN candidate track: same windows, same validation slices, same scoring as
        the linear track — only the fitter differs. Its trial count is kept separate so
        its deflated Sharpe pays its OWN multiple-comparisons penalty (§2.4).

        THE TRIAL BUDGET IS THE BINDING CONSTRAINT, and this function used to spend it
        carelessly. It drew `self.search` (16) random hyperparameter combinations per
        window and kept the max, so a 3-window run scored 48 candidates on the very
        returns its deflated Sharpe was computed from. Against the same synthetic return
        stream, `deflated_sharpe_ratio` gives DSR 0.394 at 48 trials and 0.822 at 4 —
        the trial count alone was the difference between "hopeless" and "arguable", and
        at 48 trials the 0.75 bar effectively demanded a Sharpe-3 strategy.

        What those 48 trials bought was mostly nothing. Five of the six searched axes
        (`entry_threshold`, `size_scale`, `stop_loss`, `take_profit`, and `gain`) do not
        touch the network at all — they are decision-layer sizing knobs, and the
        incumbent already has curated values for them. Re-searching them for the NN
        asked "does the net PLUS a different risk config beat theta PLUS the old one",
        which is not the question. So now:

          - decision-layer hyperparameters are INHERITED from `prior_model`, holding
            everything but the predictor fixed. That is the cleaner experiment.
          - `gain` is derived inside `fit_nn` from the spread of the net's own training
            predictions (and must be, under the vol-scaled label).
          - the L2 choice is made on each net's PURGED OUT-OF-TIME early-stopping loss,
            not on validation Sharpe, so selecting it costs no trial.

        One candidate is scored per window, and the trial count is the number of windows
        (3, not 48). This is a *tightening*, not a loophole: nothing here lowers
        `nn_min_dsr`, it stops spending the net's evidence on questions nobody asked.
        """
        windows, scores = [], []
        best_overall, best_val, n_trials = None, -float("inf"), 0
        reason, train_samples, n_params, windows_fit = "", 0, 0, 0

        # Everything except the predictor, held fixed at the incumbent's values.
        inherited = {"entry_threshold": prior_model.entry_threshold,
                     "size_scale": prior_model.size_scale,
                     "stop_loss": prior_model.stop_loss,
                     "take_profit": prior_model.take_profit}

        for w in range(self.n_windows):
            train_end, val_start, val_end = self._bounds(w, start, fold, length)
            # The NN-specific sample builder returns risk-adjusted, cross-sectionally
            # demeaned labels and a time index for the purged early-stopping split.
            X, y, t_idx = build_nn_samples(
                self.bt, assets, {k: v[:train_end] for k, v in aligned.items()})
            train_samples = max(train_samples, len(X))

            # One fit per L2 setting. Seeded from (window, l2 index) rather than
            # self.rng so the NN track is reproducible independently of how many
            # draws the linear search happened to consume first.
            nets = []
            for i, l2 in enumerate(NN_L2_OPTIONS):
                net, err = fit_nn(X, y, hidden=hidden, l2=l2, seed=7 + 100 * w + i,
                                  min_samples=min_samples, t_index=t_idx,
                                  purge=self.bt.horizon)
                if net is not None:
                    nets.append(net)
                    n_params = net.n_params
                elif err:
                    reason = err
            if not nets:
                scores.append(default_scores[w])
                windows.append({"window": w, "train_end": train_end, "val_end": val_end,
                                "train_samples": len(X), "nn_sharpe": None,
                                "default_sharpe": round(default_scores[w], 3)})
                continue

            windows_fit += 1
            # Model selection on held-out-in-training loss, so it costs no trial.
            best_net = min(nets, key=lambda n: n.val_loss if n.val_loss is not None
                           else float("inf"))
            cand = best_net.clone(**inherited)
            n_trials += 1
            local_score = self._val(assets, aligned, cand, val_start, val_end).metrics["sharpe"]

            scores.append(local_score)
            windows.append({"window": w, "train_end": train_end, "val_end": val_end,
                            "train_samples": len(X), "nn_sharpe": round(local_score, 3),
                            "default_sharpe": round(default_scores[w], 3)})
            if local_score > best_val:
                best_val, best_overall = local_score, cand

        dsr = 0.0
        if best_overall is not None:
            oos: list[float] = []
            for w in range(self.n_windows):
                _, vs, ve = self._bounds(w, start, fold, length)
                oos += self._val(assets, aligned, best_overall, vs, ve).returns
            dsr = deflated_sharpe_ratio(oos, n_trials)

        return {"model": best_overall, "challenger_avg": round(mean(scores), 3),
                "dsr": round(dsr, 3), "n_trials": n_trials, "windows": windows,
                # `reason` is the last refusal seen, which can come from an EARLY window
                # that was still too short while later ones fit -- so it is only
                # meaningful next to windows_fit, and both are reported together.
                "reason": reason if windows_fit < self.n_windows else "",
                "windows_fit": windows_fit, "train_samples": train_samples,
                "n_params": n_params}
