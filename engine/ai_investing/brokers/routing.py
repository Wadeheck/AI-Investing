"""Routes orders to the right live broker by asset class: crypto -> ccxt exchange,
stocks -> Longbridge/moomoo, presented behind the single BrokerAdapter interface the
engine uses. Cash is summed across venues (mind cross-currency — a known v1 caveat).
"""
from __future__ import annotations

from ai_investing.brokers.base import BrokerAdapter
from ai_investing.models import AssetClass, Asset, Order, Position


class RoutingBroker(BrokerAdapter):
    name = "routing"
    live = True

    def __init__(self, stock: BrokerAdapter, crypto: BrokerAdapter):
        self.stock = stock
        self.crypto = crypto

    def _for(self, asset: Asset) -> BrokerAdapter:
        return self.crypto if asset.asset_class is AssetClass.CRYPTO else self.stock

    def get_cash(self) -> float:
        return self.stock.get_cash() + self.crypto.get_cash()

    def get_positions(self) -> dict[str, Position]:
        out: dict[str, Position] = {}
        out.update(self.stock.get_positions())
        out.update(self.crypto.get_positions())
        return out

    def submit(self, order: Order, price: float) -> Order:
        return self._for(order.asset).submit(order, price)
