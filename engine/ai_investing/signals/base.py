from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from ai_investing.models import Asset, Bar, SignalResult


class Signal(ABC):
    """A signal scores an asset from -1 (strong bearish) to +1 (strong bullish).

    `context` carries shared, cross-asset info the runner computes once per cycle
    (news sentiment, hype flags, macro state) so signals stay cheap and pure.
    """

    name: str = "signal"

    @abstractmethod
    def evaluate(self, asset: Asset, bars: list[Bar], context: Optional[dict] = None) -> SignalResult:
        ...
