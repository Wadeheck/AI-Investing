"""Trend continuation via a volatility-normalized z-score.

Inspired by a widely-shared r/algotrading post (2026-08) claiming 65.92% CAGR / 26.79%
max DD from an EMA(65)/stdev(65) z-score trend state machine on BTC since 2014: long
above a bull threshold, flat below a bear threshold, price normalized by its own recent
volatility so the same "trend strength" reads consistently across price regimes.

An independent rerun on real BTC-USD daily data (2014-09 -> 2026-08, no lookahead,
10bps round-trip cost) reproduced the CAGR in the right ballpark (51-67% across a 25-cell
threshold grid) but NOT the drawdown claim -- actual max DD ran 51-78%, never once under
50%, traced to a real Dec-2017 -> Aug-2018 giveback. It also lost to plain buy-and-hold
over just the last 4 years (13.5% vs 27.1% CAGR), the exact out-of-sample-by-time check
requested in the thread. See chat log 2026-08-15 for the full writeup.

Folded in here as ONE candidate feature for the walk-forward optimizer to weigh against
every other signal on real recent data and a Deflated-Sharpe gate -- not adopted as a
standalone system, and not given any special trust over what it earns.
"""
from __future__ import annotations

from typing import Optional

from ai_investing.indicators import ema, stdev
from ai_investing.models import Asset, Bar, SignalDirection, SignalResult
from ai_investing.signals.base import Signal


class TrendZScoreSignal(Signal):
    """EMA(period) baseline, stdev(period) of price -> z-score trend filter."""

    name = "trend_zscore"

    def __init__(self, period: int = 65, bull: float = 1.0, bear: float = -1.0):
        self.period, self.bull, self.bear = period, bull, bear

    def evaluate(self, asset: Asset, bars: list[Bar], context: Optional[dict] = None) -> SignalResult:
        closes = [b.close for b in bars]
        if len(closes) < self.period:
            return SignalResult(self.name, SignalDirection.FLAT, 0.0, 0.0, "insufficient history")

        baseline = ema(closes, self.period)
        sd = stdev(closes[-self.period:])
        if baseline is None or sd == 0:
            return SignalResult(self.name, SignalDirection.FLAT, 0.0, 0.0, "no volatility")

        z = (closes[-1] - baseline) / sd
        span = max(abs(self.bull), abs(self.bear))
        score = max(-1.0, min(1.0, z / (2 * span)))
        if z > self.bull:
            direction, conf = SignalDirection.LONG, min(1.0, z / (2 * self.bull))
        elif z < self.bear:
            direction, conf = SignalDirection.SHORT, min(1.0, abs(z) / (2 * abs(self.bear)))
        else:
            direction, conf = SignalDirection.FLAT, 0.0
        return SignalResult(self.name, direction, score, conf,
                            f"z={z:+.2f} vs EMA{self.period} (bull>{self.bull:g}, bear<{self.bear:g})",
                            {"z": z, "ema": baseline})
