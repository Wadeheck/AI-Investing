from __future__ import annotations

from typing import Optional

from ai_investing.indicators import stdev
from ai_investing.models import Asset, Bar, SignalDirection, SignalResult
from ai_investing.signals.base import Signal


class MeanReversionSignal(Signal):
    """Fade statistical extremes: price far below its mean -> long, far above -> short."""

    name = "mean_reversion"

    def __init__(self, period: int = 20, band: float = 2.0):
        self.period, self.band = period, band

    def evaluate(self, asset: Asset, bars: list[Bar], context: Optional[dict] = None) -> SignalResult:
        closes = [b.close for b in bars]
        if len(closes) < self.period:
            return SignalResult(self.name, SignalDirection.FLAT, 0.0, 0.0, "insufficient history")

        window = closes[-self.period:]
        mean = sum(window) / len(window)
        sd = stdev(window)
        if sd == 0:
            return SignalResult(self.name, SignalDirection.FLAT, 0.0, 0.0, "no volatility")

        z = (closes[-1] - mean) / sd
        score = max(-1.0, min(1.0, -z / self.band))  # oversold (z<0) -> positive score
        if score > 0.1:
            direction = SignalDirection.LONG
        elif score < -0.1:
            direction = SignalDirection.SHORT
        else:
            direction = SignalDirection.FLAT
        conf = min(1.0, abs(z) / self.band)
        return SignalResult(self.name, direction, score, conf,
                            f"z-score {z:+.2f} vs {self.band:.0f}σ band", {"z": z})
