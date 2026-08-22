"""Persistence for the formula: versioned θ + online RLS state on disk (JSON), plus
an append-only log of every version so you can watch the formula mature over time.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Optional

from ai_investing.learning.features import FEATURE_NAMES
from ai_investing.learning.formula import _DEFAULT_WEIGHTS, FormulaModel
from ai_investing.learning.nn_formula import NNFormulaModel
from ai_investing.learning.online import RLSLearner


def _params_of(model) -> list[float]:
    """The model's free parameters, flattened — what "did θ actually change?" compares.

    For the linear model that is θ itself. For the NN it is every weight and bias:
    the version counter exists to let you watch the formula mature, so it has to see
    a net whose weights moved, not just one whose file was rewritten.
    """
    if isinstance(model, NNFormulaModel):
        return [v for row in model.W1 for v in row] + list(model.b1) + list(model.W2) + [model.b2]
    return list(model.weights)


def _model_type(model) -> str:
    return "nn" if isinstance(model, NNFormulaModel) else "linear"


def _rebuild(prev: dict):
    """Reconstruct a saved model dict (no model_type key = pre-NN = linear)."""
    if "W1" in prev:
        return NNFormulaModel.from_dict(prev)
    return FormulaModel.from_dict(prev)


class ParamStore:
    def __init__(self, path: str):
        self.path = path

    def load(self) -> tuple[FormulaModel | NNFormulaModel, Optional[RLSLearner]]:
        try:
            with open(self.path) as fh:
                d = json.load(fh)
            # Absent model_type means every formula.json written before the NN
            # challenger existed — those are all linear, so that is the default.
            if d.get("model_type") == "nn":
                model = NNFormulaModel.from_dict(d["model"])
                # No online path for the NN in this phase (NN_CHALLENGER.md §2.6): RLS's
                # linear update rule doesn't apply to it, so any saved RLS state is not
                # the net's to mature and is dropped rather than misapplied.
                self._migrate(model)
                return model, None
            model = FormulaModel.from_dict(d["model"])
            rls = RLSLearner.from_dict(d["rls"]) if d.get("rls") else None
            old_names = list(model.feature_names)
            if self._migrate(model):
                # θ grew a dimension. Don't discard what RLS has already learned
                # about the OTHER features just because the code added a signal --
                # extend the covariance instead (see RLSLearner.grow). Only fall
                # back to a reset if the saved RLS doesn't line up with the saved
                # model, where growing it would silently misalign θ.
                added = [n for n in model.feature_names if n not in old_names]
                if rls is not None and rls.n == len(old_names):
                    rls.grow([model.weights[model.feature_names.index(n)] for n in added])
                else:
                    rls = None
            return model, rls
        except (OSError, KeyError, json.JSONDecodeError):
            return FormulaModel(), None

    @staticmethod
    def _migrate(model) -> bool:
        """Append any features the code has grown since the model was saved (new
        signals start at their default weight and earn trust through learning).
        Returns True if the input dimension changed."""
        missing = [n for n in FEATURE_NAMES if n not in model.feature_names]
        if not missing:
            return False
        for n in missing:
            model.feature_names.append(n)
            if isinstance(model, NNFormulaModel):
                # A new input to the net enters at zero weight into every hidden unit:
                # inert until a retrain gives it one, which is the same "starts at its
                # default and earns trust" contract the linear branch has.
                for row in model.W1:
                    row.append(0.0)
            else:
                model.weights.append(_DEFAULT_WEIGHTS.get(n, 0.0))
            if model.feature_mean is not None:
                model.feature_mean.append(0.0)
            if model.feature_std is not None:
                model.feature_std.append(1.0)
        return True

    def load_model(self) -> FormulaModel | NNFormulaModel:
        return self.load()[0]

    def _weights_changed(self, model) -> bool:
        """Has θ moved since what is on disk?

        A first save (nothing on disk) counts as a change: version 1 is real. An
        unreadable file also counts, because refusing to record a version bump we
        cannot rule out is the safer error — an over-counted version is misleading,
        a silently dropped one loses history.
        """
        try:
            with open(self.path) as fh:
                payload = json.load(fh) or {}
            prev = payload.get("model") or {}
        except (OSError, json.JSONDecodeError):
            return True
        if not prev:
            return True
        if list(prev.get("feature_names") or []) != list(model.feature_names):
            return True
        if (payload.get("model_type") or "linear") != _model_type(model):
            return True   # swapping linear <-> NN is the biggest change there is
        old_w = [float(x) for x in _params_of(_rebuild(prev))]
        new_w = [float(x) for x in _params_of(model)]
        if len(old_w) != len(new_w):
            return True
        return any(abs(a - b) > 1e-12 for a, b in zip(old_w, new_w))

    def save(self, model, rls: Optional[RLSLearner] = None,
             metrics: Optional[dict] = None, journal=None) -> None:
        # BUMP THE VERSION ONLY WHEN θ ACTUALLY CHANGED (fixed 2026-08-05).
        # This used to increment unconditionally, and save() is called from
        # run_forever()'s `finally` — so every process exit advanced the version.
        # A crash loop took the engine from θv1 to θv21 in twenty minutes without a
        # single trade being learned from, and every one of those numbers was
        # reported to the user on Telegram and appended to the params history as
        # though the formula had matured.
        #
        # The version is supposed to let you watch the formula mature (see this
        # module's docstring). Counting restarts instead makes it worse than
        # useless: it looks like learning.
        changed = self._weights_changed(model)
        if changed:
            model.version += 1
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "model_type": _model_type(model),
            "model": model.to_dict(),
            "rls": rls.to_dict() if rls else None,
            "metrics": metrics or {},
        }
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        with open(self.path, "w") as fh:
            json.dump(payload, fh, indent=2)
        # The params history is a record of the formula CHANGING. Appending a row on
        # every shutdown filled it with identical θ under rising version numbers.
        if journal is not None and changed:
            journal.record_params(model, metrics or {})
