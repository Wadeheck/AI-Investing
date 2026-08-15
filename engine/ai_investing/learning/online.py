"""Online learning: Recursive Least Squares with a forgetting factor.

This is the "matures from realized P&L" loop. Each closed trade yields a sample
(φ, y) where y is the realized signed return; RLS updates θ to better predict y from
φ. Three things keep it a *curated* update rather than a reaction:

  - forgetting factor μ (<1): slowly discounts old regimes, never fully forgets.
  - the estimate starts from the curated θ with a confident prior covariance P,
    so early trades can't swing it much.
  - a trust region caps ‖Δθ‖ per update: no single trade jerks the formula.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from ai_investing.learning.linalg import dot, identity, mat_scale, mat_sub, matvec, outer


@dataclass
class RLSLearner:
    n: int
    theta: list[float]
    P: list[list[float]]
    mu: float = 0.999          # forgetting factor
    trust_region: float = 0.01  # max L2 change to θ per update
    updates: int = 0

    @classmethod
    def initialize(cls, theta0: list[float], prior_confidence: float = 1.0,
                   mu: float = 0.999, trust_region: float = 0.01) -> "RLSLearner":
        # P = (1/prior_confidence) I. Higher confidence -> smaller P -> gentler updates.
        n = len(theta0)
        return cls(n=n, theta=list(theta0),
                   P=identity(n, scale=1.0 / max(1e-9, prior_confidence)),
                   mu=mu, trust_region=trust_region)

    def predict(self, phi: list[float]) -> float:
        return dot(self.theta, phi)

    def update(self, phi: list[float], y: float) -> float:
        """Feed one realized outcome. Returns the prediction error (y − θ·φ)."""
        Pphi = matvec(self.P, phi)
        denom = self.mu + dot(phi, Pphi)
        if denom <= 1e-12:
            return 0.0
        k = [x / denom for x in Pphi]            # Kalman gain
        err = y - dot(self.theta, phi)
        step = [ki * err for ki in k]

        norm = math.sqrt(sum(s * s for s in step))
        if norm > self.trust_region and norm > 0:
            scale = self.trust_region / norm
            step = [s * scale for s in step]

        self.theta = [t + s for t, s in zip(self.theta, step)]
        self.P = mat_scale(mat_sub(self.P, outer(k, Pphi)), 1.0 / self.mu)
        self.updates += 1
        return err

    def grow(self, theta_new: list[float]) -> None:
        """Append new regressors to the END of θ, preserving everything already
        learned about the existing ones.

        Adding a feature to φ used to throw the whole RLS state away (ParamStore
        re-initialized it from θ), which silently reset the covariance — and with
        it the "how confident am I in each weight" memory built from every closed
        trade so far — every time the code grew a signal. That is a real cost paid
        for an unrelated reason, so grow instead of reset.

        The new dimensions start with zero cross-covariance against the old ones
        (nothing has been observed yet that ties them together) and a diagonal
        prior equal to the MEAN of the current diagonal, so a newly added feature
        is no more plastic than a typical existing one. The trust region still
        caps ‖Δθ‖ per update, so this cannot jerk the formula either way.
        """
        if not theta_new:
            return
        k = len(theta_new)
        diag = [self.P[i][i] for i in range(self.n)] if self.n else []
        prior = (sum(diag) / len(diag)) if diag else 1.0
        for row in self.P:
            row.extend([0.0] * k)
        for j in range(k):
            new_row = [0.0] * (self.n + k)
            new_row[self.n + j] = prior
            self.P.append(new_row)
        self.theta.extend(theta_new)
        self.n += k

    def to_dict(self) -> dict:
        return {"n": self.n, "theta": self.theta, "P": self.P, "mu": self.mu,
                "trust_region": self.trust_region, "updates": self.updates}

    @classmethod
    def from_dict(cls, d: dict) -> "RLSLearner":
        return cls(n=d["n"], theta=d["theta"], P=d["P"], mu=d.get("mu", 0.999),
                   trust_region=d.get("trust_region", 0.01), updates=d.get("updates", 0))
