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

    def _weights_changed(self, model: FormulaModel) -> bool:
        """Has θ moved since what is on disk?

        A first save (nothing on disk) counts as a change: version 1 is real. An
        unreadable file also counts, because refusing to record a version bump we
        cannot rule out is the safer error — an over-counted version is misleading,
        a silently dropped one loses history.
        """
        try:
            with open(self.path) as fh:
                prev = (json.load(fh) or {}).get("model") or {}
        except (OSError, json.JSONDecodeError):
            return True
        if not prev:
            return True
        if list(prev.get("feature_names") or []) != list(model.feature_names):
            return True
        old_w = [float(x) for x in (prev.get("weights") or [])]
        new_w = [float(x) for x in model.weights]
        if len(old_w) != len(new_w):
            return True
        return any(abs(a - b) > 1e-12 for a, b in zip(old_w, new_w))

    def save(self, model: FormulaModel, rls: Optional[RLSLearner] = None,
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
