from __future__ import annotations

from typing import Optional

from ai_investing.indicators import rsi, sma
from ai_investing.models import Asset, Bar, SignalDirection, SignalResult
from ai_investing.signals.base import Signal


class MomentumSignal(Signal):
    """Trend-following: fast SMA vs slow SMA, tempered by RSI extremes."""

    name = "momentum"

    def __init__(self, fast: int = 20, slow: int = 50, rsi_period: int = 14):
        self.fast, self.slow, self.rsi_period = fast, slow, rsi_period

    def evaluate(self, asset: Asset, bars: list[Bar], context: Optional[dict] = None) -> SignalResult:
        closes = [b.close for b in bars]
        f, s, r = sma(closes, self.fast), sma(closes, self.slow), rsi(closes, self.rsi_period)
        if f is None or s is None or r is None or s == 0:
            return SignalResult(self.name, SignalDirection.FLAT, 0.0, 0.0, "insufficient history")

        spread = (f - s) / s
        score = max(-1.0, min(1.0, spread * 10))
        if score > 0.05:
            direction = SignalDirection.LONG
        elif score < -0.05:
            direction = SignalDirection.SHORT
        else:
            direction = SignalDirection.FLAT

        conf = min(1.0, abs(score))
        # Don't chase overbought longs / oversold shorts.
        if direction == SignalDirection.LONG and r > 70:
            conf *= 0.5
        elif direction == SignalDirection.SHORT and r < 30:
            conf *= 0.5

        rationale = f"SMA{self.fast}={f:.2f} vs SMA{self.slow}={s:.2f} ({spread * 100:+.1f}%), RSI={r:.0f}"
        return SignalResult(self.name, direction, score, conf, rationale,
                            {"rsi": r, "sma_fast": f, "sma_slow": s})
