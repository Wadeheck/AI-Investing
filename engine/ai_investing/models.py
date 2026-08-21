"""Core domain models shared across the engine.

Deliberately dependency-free (stdlib dataclasses) so the whole decision pipeline
runs without installing anything.
"""
from __future__ import annotations

import math
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
    user_view: float = 0.0                          # your tilt on this asset, -1..+1


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
    # WHAT THE ADAPTER ACTUALLY SENT, stamped by the adapter itself rather than
    # recomputed by the caller. Eight consecutive live orders were rejected with
    # "Wrong bid size, please change the price" and the cause could not be
    # established afterwards, because the journal recorded the FILL price (0.0 on
    # a reject) and nothing recorded the price that was submitted. A rejected
    # order you cannot reconstruct is an order you cannot learn from.
    submitted_price: Optional[float] = None
    submitted_qty: Optional[float] = None


@dataclass
class Position:
    asset: Asset
    qty: float
    avg_price: float

    def market_value(self, price: float) -> float:
        return self.qty * price

    def unrealized_pnl(self, price: float) -> float:
        return (price - self.avg_price) * self.qty


def mark_price(raw, fallback: float) -> float:
    """The price to VALUE a position at, or `fallback` (its cost basis) if there
    isn't a usable one. The single valuation rule for every book.

    Use this anywhere a position is being valued. Do NOT use it to gate a trading
    decision — refusing to act on a bad price (`if px <= 0: continue`) is correct
    and must stay. The distinction matters: skipping a *decision* is safe, but
    skipping a *position* silently rewrites the book's value.

    Each of the four books re-implemented this and each got it wrong in the same
    direction. The `_stamp_marks` variants read `if px > 0: mv += qty * px`, which
    OMITS an unpriced position from equity — so an unpriced short reads as a debt
    that vanished, and an unpriced long as an asset that vanished. Cost basis
    keeps the position in the book at the last price anyone actually paid, so an
    outage reads as "no change" rather than as a windfall or a collapse.
    """
    try:
        px = float(raw)
    except (TypeError, ValueError):
        return fallback
    if not math.isfinite(px) or px <= 0.0:
        return fallback
    return px


@dataclass
class Portfolio:
    cash: float
    positions: dict[str, Position] = field(default_factory=dict)
    # {AssetClass: that venue's OWN equity}. §4.36's real fix.
    #
    # `cash + sum(qty * price)` is only this account's equity when opening a
    # position EXCHANGES cash for the position's value. On a margined venue it
    # LOCKS cash instead, so the formula adds back a notional it never deducted
    # (leverage > 1) or subtracts it twice (a short) — the -$4,265-on-a-flat-book
    # signature. The venue always knows its own equity; it just could not be
    # blended into a book that also holds a marked stock leg.
    #
    # So: for every asset class named here, the venue's figure replaces both its
    # cash and its mark-to-market. `cash` must exclude those venues' cash — the
    # broker that supplies this is responsible for that split (see
    # BrokerAdapter.portfolio and RoutingBroker.venue_equity_parts).
    venue_equity: dict = field(default_factory=dict)

    def _overridden(self, key: str, pos: Position) -> bool:
        return bool(self.venue_equity) and pos.asset.asset_class in self.venue_equity

    def _px(self, key: str, pos: Position, prices: dict[str, float]) -> float:
        """The price to value `pos` at, or its cost basis if there isn't one.

        A MISSING key already fell back to avg_price. The hole was a key that is
        PRESENT and worthless: the runner builds prices as `b[-1].close if b else
        0.0`, so a feed outage writes 0.0 rather than omitting the symbol, and
        0.0 sailed straight through as a valuation. A short at price 0 looks like
        a debt that has been forgiven, so equity silently collapses to cash.

        That is not hypothetical. On 2026-08-03 every position valued at zero and
        equity read $116,027 — the book's cash, short proceeds and all — against
        a true $99,997. The reading became the day's opening mark, the next
        honest cycle measured a 13.8% "drawdown" against it, and the circuit
        breaker flattened twelve healthy positions and latched. NaN was worse
        still: it propagated to equity, and every breaker comparison against NaN
        is False, so hours of unvalued book passed every safety check in silence.

        Cost basis is the right fallback because it is the one number that is
        always known and never absurd. It makes an outage look like "no change",
        which is the honest reading of "we cannot see the price".
        """
        px = prices.get(key)
        if px is None:
            return pos.avg_price
        try:
            px = float(px)
        except (TypeError, ValueError):
            return pos.avg_price
        if not math.isfinite(px) or px <= 0.0:
            return pos.avg_price
        return px

    def equity(self, prices: dict[str, float]) -> float:
        """cash + marks, with any venue that reports its own equity substituted in.

        Without `venue_equity` this is byte-for-byte the old formula, so every
        book that has no margined leg is unaffected.
        """
        total = self.cash + sum(float(v) for v in self.venue_equity.values())
        for key, pos in self.positions.items():
            if self._overridden(key, pos):
                continue          # already inside that venue's own equity figure
            total += pos.market_value(self._px(key, pos, prices))
        return total

    def exposure(self, prices: dict[str, float]) -> float:
        """Gross exposure = sum of |position value|.

        NOT reduced by `venue_equity`: a margined position's exposure is its
        NOTIONAL, which is exactly what `qty * price` gives and exactly what the
        risk layer needs. Equity is what margin distorts; exposure is not.
        A long-only margined book whose exposure was hidden here is §4.36's
        third defect (`/assets` under-reporting).
        """
        return sum(abs(pos.market_value(self._px(key, pos, prices)))
                   for key, pos in self.positions.items())
