from __future__ import annotations

from ai_investing.brokers.base import BrokerAdapter
from ai_investing.models import Asset, AssetClass, Order, OrderStatus, OrderType, Position, Side


class PaperBroker(BrokerAdapter):
    """In-memory simulated broker. Instant fills at the reference price."""

    name = "paper"
    live = False

    def __init__(self, cash: float, allow_short: bool = False):
        self._cash = float(cash)
        self._positions: dict[str, Position] = {}
        self.allow_short = allow_short

    def get_cash(self) -> float:
        return self._cash

    def get_positions(self) -> dict[str, Position]:
        return {k: v for k, v in self._positions.items() if abs(v.qty) > 1e-9}

    def submit(self, order: Order, price: float) -> Order:
        if price <= 0 or order.qty <= 0:
            order.status = OrderStatus.REJECTED
            order.reason = (order.reason + " | invalid price/qty").strip(" |")
            return order

        # Limit orders: don't fill worse than the limit price.
        if order.order_type is OrderType.LIMIT and order.limit_price is not None:
            if (order.side is Side.BUY and price > order.limit_price) or \
               (order.side is Side.SELL and price < order.limit_price):
                order.status = OrderStatus.REJECTED
                order.reason = (order.reason + " | limit not reached").strip(" |")
                return order

        key = order.asset.key
        pos = self._positions.get(key)

        if order.side is Side.BUY:
            cost = price * order.qty
            if cost > self._cash + 1e-6:
                # Scale down to affordable size rather than reject outright.
                order.qty = self._cash / price
                cost = self._cash
            if order.qty <= 1e-9:
                order.status = OrderStatus.REJECTED
                order.reason = "insufficient cash"
                return order
            self._cash -= cost
            if pos:
                total_qty = pos.qty + order.qty
                # Buying back a SHORT to exactly flat lands here, not in the SELL
                # branch — and only SELL cleaned up emptied positions. So closing
                # a short left a qty=0.0 tombstone behind forever. get_positions()
                # filters those, so equity was never wrong, but state() persisted
                # them: after the 2026-08-04 flatten the book reported "10
                # positions" while holding none, and a flat book whose equity
                # equals its cash is exactly the signature the phantom-valuation
                # detector looks for. Drop them at the source.
                if abs(total_qty) < 1e-9:
                    self._positions.pop(key, None)
                else:
                    pos.avg_price = (pos.avg_price * pos.qty + cost) / total_qty
                    pos.qty = total_qty
            else:
                self._positions[key] = Position(order.asset, order.qty, price)
        else:  # SELL
            held = pos.qty if pos else 0.0
            if not self.allow_short and order.qty > held + 1e-9:
                order.qty = max(0.0, held)  # long-only: can't sell more than held
            if order.qty <= 1e-9:
                order.status = OrderStatus.REJECTED
                order.reason = "nothing to sell"
                return order
            self._cash += price * order.qty
            new_qty = held - order.qty
            if abs(new_qty) < 1e-9:
                self._positions.pop(key, None)
            elif pos:
                pos.qty = new_qty
            else:  # opening a short
                self._positions[key] = Position(order.asset, -order.qty, price)

        order.filled_qty = order.qty
        order.filled_price = price
        order.status = OrderStatus.FILLED
        return order

    # -- persistence (used by the shadow / formula-only portfolio) ----------
    def state(self) -> dict:
        # Persist only LIVE positions: a zero-qty entry carries no information
        # (the avg_price of a closed position is meaningless) and every reader
        # that counts the list overstates what the book holds.
        return {"cash": self._cash, "positions": [
            {"symbol": p.asset.symbol, "asset_class": p.asset.asset_class.value,
             "exchange": p.asset.exchange, "quote": p.asset.quote,
             "qty": p.qty, "avg_price": p.avg_price}
            for p in self._positions.values() if abs(p.qty) > 1e-9]}

    @classmethod
    def from_state(cls, d: dict, allow_short: bool = False) -> "PaperBroker":
        b = cls(float(d.get("cash", 0.0)), allow_short=allow_short)
        for p in d.get("positions", []):
            try:
                asset = Asset(p["symbol"], AssetClass(p["asset_class"]),
                              exchange=p.get("exchange", ""), quote=p.get("quote", "USD"))
                b._positions[asset.key] = Position(asset, float(p["qty"]), float(p["avg_price"]))
            except (KeyError, ValueError):
                continue
        return b
