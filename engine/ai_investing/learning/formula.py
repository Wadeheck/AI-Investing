"""The parametric decision formula.

    raw        = θ · φ                       (≈ predicted forward return)
    conviction = tanh(gain · raw)            ∈ (−1, 1)
    target_wt  = deadzone(conviction, τ) · size_scale     ∈ [−1, 1]

θ (the `weights`) and the scalar hyperparameters below are the "decision variables"
the learning engine curates and matures. See docs/FORMULA.md.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from ai_investing.learning.features import FEATURE_NAMES


# A sane starting formula (theta in return units). Directionally correct out of the
# box: positive weight on political_hype fades pumps (its feature is negative then).
_DEFAULT_WEIGHTS = {
    "bias": 0.0,
    "momentum": 0.020,
    "mean_reversion": 0.015,
    "sentiment": 0.020,
    "political_hype": 0.030,
    "consensus": 0.010,
    "mom_lowvol": 0.008,
}


@dataclass
class FormulaModel:
    feature_names: list[str] = field(default_factory=lambda: list(FEATURE_NAMES))
    weights: list[float] = field(default_factory=lambda: [_DEFAULT_WEIGHTS[n] for n in FEATURE_NAMES])
    gain: float = 20.0
    entry_threshold: float = 0.10   # deadzone: no trade below this conviction
    size_scale: float = 1.0
    stop_loss: float = 0.08
    take_profit: float = 0.25
    version: int = 0
    fitted: bool = False
    feature_mean: Optional[list[float]] = None   # training-set feature stats, for OOD gating
    feature_std: Optional[list[float]] = None

    # -- the formula --------------------------------------------------------
    def raw(self, feats: dict[str, float]) -> float:
        return sum(w * feats.get(n, 0.0) for n, w in zip(self.feature_names, self.weights))

    def conviction(self, feats: dict[str, float]) -> float:
        return math.tanh(self.gain * self.raw(feats))

    def target_weight(self, feats: dict[str, float]) -> float:
        c = self.conviction(feats)
        sign = 1.0 if c >= 0 else -1.0
        if self.entry_threshold >= 1.0:
            return 0.0
        mag = max(0.0, abs(c) - self.entry_threshold) / (1.0 - self.entry_threshold)
        return max(-1.0, min(1.0, sign * mag * self.size_scale))

    def weight_of(self, name: str) -> float:
        try:
            return self.weights[self.feature_names.index(name)]
        except ValueError:
            return 0.0

    # -- (de)serialization --------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "feature_names": self.feature_names,
            "weights": self.weights,
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
    def from_dict(cls, d: dict) -> "FormulaModel":
        names = d.get("feature_names", list(FEATURE_NAMES))
        return cls(
            feature_names=names,
            weights=d.get("weights", [_DEFAULT_WEIGHTS.get(n, 0.0) for n in names]),
            gain=d.get("gain", 20.0),
            entry_threshold=d.get("entry_threshold", 0.10),
            size_scale=d.get("size_scale", 1.0),
            stop_loss=d.get("stop_loss", 0.08),
            take_profit=d.get("take_profit", 0.25),
            version=d.get("version", 0),
            fitted=d.get("fitted", False),
            feature_mean=d.get("feature_mean"),
            feature_std=d.get("feature_std"),
        )

    def describe(self) -> str:
        terms = "  ".join(f"{n}={w:+.4f}" for n, w in zip(self.feature_names, self.weights))
        return (f"θ[v{self.version}{' fitted' if self.fitted else ''}]: {terms}\n"
                f"    gain={self.gain:.1f} entry_threshold={self.entry_threshold:.3f} "
                f"size_scale={self.size_scale:.2f} stop={self.stop_loss:.3f} take={self.take_profit:.3f}")

    def clone(self, **overrides) -> "FormulaModel":
        d = self.to_dict()
        d.update(overrides)
        return FormulaModel.from_dict(d)
