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
from ai_investing.learning.online import RLSLearner


class ParamStore:
    def __init__(self, path: str):
        self.path = path

    def load(self) -> tuple[FormulaModel, Optional[RLSLearner]]:
        try:
            with open(self.path) as fh:
                d = json.load(fh)
            model = FormulaModel.from_dict(d["model"])
            rls = RLSLearner.from_dict(d["rls"]) if d.get("rls") else None
            if self._migrate(model):
                rls = None   # dimensions changed: RLS state re-initializes from θ
            return model, rls
        except (OSError, KeyError, json.JSONDecodeError):
            return FormulaModel(), None

    @staticmethod
    def _migrate(model: FormulaModel) -> bool:
        """Append any features the code has grown since the model was saved (new
        signals start at their default weight and earn trust through learning).
        Returns True if the θ dimension changed."""
        missing = [n for n in FEATURE_NAMES if n not in model.feature_names]
        if not missing:
            return False
        for n in missing:
            model.feature_names.append(n)
            model.weights.append(_DEFAULT_WEIGHTS.get(n, 0.0))
            if model.feature_mean is not None:
                model.feature_mean.append(0.0)
            if model.feature_std is not None:
                model.feature_std.append(1.0)
        return True

    def load_model(self) -> FormulaModel:
        return self.load()[0]

    def save(self, model: FormulaModel, rls: Optional[RLSLearner] = None,
             metrics: Optional[dict] = None, journal=None) -> None:
        model.version += 1
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "model": model.to_dict(),
            "rls": rls.to_dict() if rls else None,
            "metrics": metrics or {},
        }
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        with open(self.path, "w") as fh:
            json.dump(payload, fh, indent=2)
        if journal is not None:
            journal.record_params(model, metrics or {})
