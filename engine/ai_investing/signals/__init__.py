"""Trading signals. Each produces a SignalResult in [-1, +1] with a confidence."""
from ai_investing.signals.base import Signal
from ai_investing.signals.momentum import MomentumSignal
from ai_investing.signals.mean_reversion import MeanReversionSignal
from ai_investing.signals.sentiment import SentimentSignal
from ai_investing.signals.political_hype import PoliticalHypeSignal
from ai_investing.signals.macro_linkage import MacroLinkageSignal
from ai_investing.signals.trend_zscore import TrendZScoreSignal
from ai_investing.signals.regime_persistence import RegimePersistenceSignal

__all__ = [
    "Signal",
    "MomentumSignal",
    "MeanReversionSignal",
    "SentimentSignal",
    "PoliticalHypeSignal",
    "MacroLinkageSignal",
    "TrendZScoreSignal",
    "RegimePersistenceSignal",
    "default_signals",
]


def default_signals() -> list[Signal]:
    """The signal stack the engine runs by default."""
    return [
        MomentumSignal(),
        MeanReversionSignal(),
        SentimentSignal(),
        PoliticalHypeSignal(),
        MacroLinkageSignal(),
        TrendZScoreSignal(),
        RegimePersistenceSignal(),
    ]
