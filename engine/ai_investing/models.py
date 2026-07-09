"""Core domain models shared across the engine.

Deliberately dependency-free (stdlib dataclasses) so the whole decision pipeline
runs without installing anything.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class AssetClass(str, Enum):
    STOCK = "stock"
    CRYPTO = "crypto"


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"


class OrderStatus(str, Enum):
    PENDING = "pending"
    FILLED = "filled"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class SignalDirection(str, Enum):
    LONG = "long"    # bullish
    SHORT = "short"  # bearish (fade / exit / short if allowed)
    FLAT = "flat"    # no opinion


@dataclass(frozen=True)
class Asset:
    symbol: str
    asset_class: AssetClass
    exchange: str = ""
    quote: str = "USD"

    @property
    def key(self) -> str:
        return f"{self.asset_class.value}:{self.symbol}"

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.symbol


@dataclass(frozen=True)
class Bar:
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class SignalResult:
    name: str
    direction: SignalDirection
    score: float           # -1.0 (strong short) .. +1.0 (strong long)
    confidence: float      # 0.0 .. 1.0
    rationale: str = ""
    meta: dict = field(default_factory=dict)


@dataclass
class Decision:
    asset: Asset
    target_weight: float   # desired conviction, -1.0 .. 1.0 (scaled by risk sizing)
    direction: SignalDirection
    score: float
    confidence: float
    signals: list[SignalResult] = field(default_factory=list)
    rationale: str = ""
    features: dict = field(default_factory=dict)   # feature vector φ used by the formula
    expected_return: float = 0.0                    # raw = θ·φ, pre-squash


@dataclass
class Order:
    asset: Asset
    side: Side
    qty: float
    order_type: OrderType = OrderType.MARKET
    limit_price: Optional[float] = None
    status: OrderStatus = OrderStatus.PENDING
    filled_price: Optional[float] = None
    filled_qty: float = 0.0
    id: Optional[str] = None
    client_order_id: Optional[str] = None   # idempotency key: dedupes double-submits
    ts: Optional[datetime] = None
    reason: str = ""


@dataclass
class Position:
    asset: Asset
    qty: float
    avg_price: float

    def market_value(self, price: float) -> float:
        return self.qty * price

    def unrealized_pnl(self, price: float) -> float:
        return (price - self.avg_price) * self.qty


@dataclass
class Portfolio:
    cash: float
    positions: dict[str, Position] = field(default_factory=dict)

    def equity(self, prices: dict[str, float]) -> float:
        total = self.cash
        for key, pos in self.positions.items():
            total += pos.market_value(prices.get(key, pos.avg_price))
        return total

    def exposure(self, prices: dict[str, float]) -> float:
        """Gross exposure = sum of |position value|."""
        return sum(abs(pos.market_value(prices.get(key, pos.avg_price)))
                   for key, pos in self.positions.items())
