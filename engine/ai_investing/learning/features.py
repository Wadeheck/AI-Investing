"""Builds the feature vector φ that the decision formula consumes.

Features are kept directional (their sign carries meaning) so that θ·φ can be read
as a predicted forward return and learned by regression on realized returns.
"""
from __future__ import annotations

from ai_investing.indicators import pct_returns, stdev
from ai_investing.models import Bar, SignalDirection, SignalResult

# Order matters: θ is aligned to this list everywhere.
FEATURE_NAMES = [
    "bias",            # intercept / baseline drift
    "momentum",        # momentum score × confidence
    "mean_reversion",  # mean-reversion score × confidence
    "sentiment",       # news sentiment score × confidence
    "political_hype",  # hype-fade score × confidence (negative on detected pumps)
    "macro_linkage",   # brain: graph-propagated macro impact × confidence
    "consensus",       # mean of the directional signal features
    "mom_lowvol",      # momentum × low-volatility regime (interaction term)
]

_SIGNAL_FEATURES = ["momentum", "mean_reversion", "sentiment", "political_hype",
                    "macro_linkage"]


class FeatureExtractor:
    names = FEATURE_NAMES

    def build(self, results: list[SignalResult], bars: list[Bar]) -> dict[str, float]:
        by = {r.name: r for r in results}
        f: dict[str, float] = {"bias": 1.0}
        for nm in _SIGNAL_FEATURES:
            r = by.get(nm)
            f[nm] = (r.score * r.confidence) if r else 0.0

        f["consensus"] = sum(f[nm] for nm in _SIGNAL_FEATURES) / len(_SIGNAL_FEATURES)

        vol = self._vol_regime(bars)
        f["mom_lowvol"] = f["momentum"] * (1.0 / (1.0 + vol))
        return f

    @staticmethod
    def _vol_regime(bars: list[Bar]) -> float:
        closes = [b.close for b in bars][-21:]
        rets = pct_returns(closes)
        if not rets:
            return 0.0
        # normalized so a "typical" 2% daily vol maps to ~1.0
        return min(3.0, stdev(rets) / 0.02)

    def vector(self, feats: dict[str, float]) -> list[float]:
        return [feats.get(n, 0.0) for n in FEATURE_NAMES]
