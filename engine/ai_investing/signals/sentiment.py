from __future__ import annotations

from typing import Optional

from ai_investing.models import Asset, Bar, SignalDirection, SignalResult
from ai_investing.signals.base import Signal


class SentimentSignal(Signal):
    """Turns per-asset news sentiment (scored by Claude in the news module) into a
    signal. The runner precomputes `context["sentiment_scores"][symbol]` once per
    cycle so the LLM is called in a single batch, not per signal.
    """

    name = "sentiment"

    def evaluate(self, asset: Asset, bars: list[Bar], context: Optional[dict] = None) -> SignalResult:
        entry = (context or {}).get("sentiment_scores", {}).get(asset.symbol)
        if not entry:
            return SignalResult(self.name, SignalDirection.FLAT, 0.0, 0.0, "no news")

        score = max(-1.0, min(1.0, float(entry.get("score", 0.0))))
        conf = max(0.0, min(1.0, float(entry.get("confidence", 0.0))))
        if score > 0.15:
            direction = SignalDirection.LONG
        elif score < -0.15:
            direction = SignalDirection.SHORT
        else:
            direction = SignalDirection.FLAT
        return SignalResult(self.name, direction, score, conf,
                            entry.get("summary", "news sentiment"), dict(entry))
