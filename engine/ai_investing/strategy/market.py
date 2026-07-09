"""Per-asset market statistics the risk layer needs: recent volatility, ATR, average
daily volume, and a returns series (for correlation / portfolio-vol estimation)."""
from __future__ import annotations

from dataclasses import dataclass, field

from ai_investing.indicators import atr, pct_returns, stdev
from ai_investing.models import Bar


@dataclass
class MarketStats:
    key: str
    price: float
    vol: float                      # recent daily return stdev
    atr: float                      # average true range (price units)
    adv: float                      # average daily volume (shares)
    returns: list[float] = field(default_factory=list)


def build_market_stats(bars_by_key: dict[str, list[Bar]], lookback: int = 20) -> dict[str, MarketStats]:
    out: dict[str, MarketStats] = {}
    for key, bars in bars_by_key.items():
        if not bars:
            continue
        closes = [b.close for b in bars]
        rets = pct_returns(closes[-(lookback + 1):])
        vols = [b.volume for b in bars[-lookback:]]
        out[key] = MarketStats(
            key=key,
            price=closes[-1],
            vol=stdev(rets) if rets else 0.0,
            atr=atr(bars, period=min(14, lookback)) or 0.0,
            adv=(sum(vols) / len(vols)) if vols else 0.0,
            returns=rets,
        )
    return out
