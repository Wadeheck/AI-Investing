"""Turns the signal stack into one conviction per asset via the learned formula, then
lets YOUR view tilt it (see user_views.py):

    model_conviction = tanh(gain · θ·φ)          # signals + news + sentiment
    final_conviction = user_views.apply(...)     # your per-asset view + risk stance
    target_weight    = deadzone(final_conviction, entry_threshold) · size_scale

θ and the hyperparameters are curated (walk-forward) and matured (online RLS); your
input is the decisive overlay on top.
"""
from __future__ import annotations

from typing import Optional

from ai_investing.learning.features import FeatureExtractor
from ai_investing.learning.formula import FormulaModel
from ai_investing.models import Asset, Bar, Decision, SignalDirection
from ai_investing.signals.base import Signal
from ai_investing.strategy.user_views import UserViews


class DecisionEngine:
    def __init__(self, signals: list[Signal], model: Optional[FormulaModel] = None,
                 user_views: Optional[UserViews] = None):
        self.signals = signals
        self.model = model or FormulaModel()
        self.features = FeatureExtractor()
        self.user_views = user_views or UserViews()

    def decide(self, asset: Asset, bars: list[Bar], context: Optional[dict] = None) -> Decision:
        results = [s.evaluate(asset, bars, context) for s in self.signals]
        feats = self.features.build(results, bars)

        raw = self.model.raw(feats)
        model_conv = self.model.conviction(feats)
        final_conv = self.user_views.apply(asset.symbol, model_conv)
        target = self.model.target_from_conviction(final_conv)

        if target > 1e-4:
            direction = SignalDirection.LONG
        elif target < -1e-4:
            direction = SignalDirection.SHORT
        else:
            direction = SignalDirection.FLAT

        user_view = self.user_views.view_for(asset.symbol)
        drivers = ", ".join(
            f"{r.name}{'+' if r.score >= 0 else ''}{r.score:.2f}"
            for r in results if r.direction is not SignalDirection.FLAT
        ) or "no active signals"
        rationale = f"E[r]={raw * 100:+.2f}% model={model_conv:+.2f}"
        if user_view is not None:
            rationale += f" user={user_view:+.2f}->{final_conv:+.2f}"
        if self.user_views.stance != "normal":
            rationale += f" [{self.user_views.stance}]"
        rationale += f" | {drivers}"

        return Decision(
            asset=asset,
            target_weight=target,
            direction=direction,
            score=final_conv,
            confidence=abs(final_conv),
            signals=results,
            rationale=rationale,
            features=feats,
            expected_return=raw,
            user_view=user_view if user_view is not None else 0.0,
        )
