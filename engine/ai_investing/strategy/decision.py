"""Turns the signal stack into a single conviction per asset via the learned formula.

    raw        = θ · φ
    conviction = tanh(gain · raw)
    target_wt  = deadzone(conviction, entry_threshold) · size_scale

θ and the hyperparameters live in the FormulaModel, which the learning engine curates
(walk-forward) and matures (online RLS).
"""
from __future__ import annotations

from typing import Optional

from ai_investing.learning.features import FeatureExtractor
from ai_investing.learning.formula import FormulaModel
from ai_investing.models import Asset, Bar, Decision, SignalDirection
from ai_investing.signals.base import Signal


class DecisionEngine:
    def __init__(self, signals: list[Signal], model: Optional[FormulaModel] = None):
        self.signals = signals
        self.model = model or FormulaModel()
        self.features = FeatureExtractor()

    def decide(self, asset: Asset, bars: list[Bar], context: Optional[dict] = None) -> Decision:
        results = [s.evaluate(asset, bars, context) for s in self.signals]
        feats = self.features.build(results, bars)

        raw = self.model.raw(feats)
        conviction = self.model.conviction(feats)
        target = self.model.target_weight(feats)

        if target > 1e-4:
            direction = SignalDirection.LONG
        elif target < -1e-4:
            direction = SignalDirection.SHORT
        else:
            direction = SignalDirection.FLAT

        confidence = abs(conviction)  # the formula's conviction IS its confidence
        drivers = ", ".join(
            f"{r.name}{'+' if r.score >= 0 else ''}{r.score:.2f}"
            for r in results if r.direction is not SignalDirection.FLAT
        ) or "no active signals"
        rationale = f"E[r]={raw * 100:+.2f}% conv={conviction:+.2f} | {drivers}"

        return Decision(
            asset=asset,
            target_weight=target,
            direction=direction,
            score=conviction,
            confidence=confidence,
            signals=results,
            rationale=rationale,
            features=feats,
            expected_return=raw,
        )
