from __future__ import annotations

from ai_investing.brokers.base import BrokerAdapter
from ai_investing.models import Order, OrderStatus, Position, Side


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
                pos.avg_price = (pos.avg_price * pos.qty + cost) / total_qty if total_qty else price
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
