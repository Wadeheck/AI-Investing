"""Regime / out-of-distribution gate.

Two ways the engine can be wrong about the world:
  - VOL REGIME: market-wide volatility spikes -> the model's assumptions weaken, so
    scale size down (linearly, to a floor) as vol runs above a threshold.
  - OUT OF DISTRIBUTION: today's feature vector is far (in z-score) from the data θ was
    fit on -> the model is extrapolating; cut size. Uses feature mean/std stored on the
    fitted FormulaModel.

Returns a size multiplier in [min_mult, 1.0]. The model should know when it doesn't know.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class RegimeGate:
    high_vol: float = 0.04          # daily vol above which we start de-risking
    ood_z: float = 4.0              # per-feature z beyond this = out-of-distribution
    min_mult: float = 0.4           # floor multiplier
    feature_mean: Optional[list[float]] = None
    feature_std: Optional[list[float]] = None

    def vol_multiplier(self, market_vol: float) -> float:
        if market_vol <= self.high_vol or self.high_vol <= 0:
            return 1.0
        excess = (market_vol - self.high_vol) / self.high_vol
        return max(self.min_mult, 1.0 - 0.5 * excess)

    def ood_multiplier(self, phi: list[float]) -> float:
        if not self.feature_mean or not self.feature_std:
            return 1.0
        zmax = 0.0
        for v, m, s in zip(phi, self.feature_mean, self.feature_std):
            if s > 1e-9:
                zmax = max(zmax, abs((v - m) / s))
        if zmax <= self.ood_z:
            return 1.0
        return max(self.min_mult, self.ood_z / zmax)

    def multiplier(self, market_vol: float, phi: Optional[list[float]] = None) -> float:
        m = self.vol_multiplier(market_vol)
        if phi is not None:
            m = min(m, self.ood_multiplier(phi))
        return m
