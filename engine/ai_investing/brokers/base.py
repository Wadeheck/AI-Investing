from __future__ import annotations

from abc import ABC, abstractmethod

from ai_investing.models import Order, Portfolio, Position


class BrokerAdapter(ABC):
    """Uniform interface over paper and live brokers.

    `submit` receives a reference `price` (the engine's current mark). Paper fills
    at that price; live adapters may ignore it and send a real market/limit order.
    """

    name = "broker"
    live = False

    @abstractmethod
    def get_cash(self) -> float:
        ...

    @abstractmethod
    def get_positions(self) -> dict[str, Position]:
        ...

    @abstractmethod
    def submit(self, order: Order, price: float) -> Order:
        ...

    def portfolio(self) -> Portfolio:
        return Portfolio(self.get_cash(), self.get_positions())

    def place_stop(self, asset, side, qty: float, stop_price: float):
        """Place a resting protective stop AT THE VENUE, so it survives a crash/hang and
        triggers on an intraday gap between cycles. Default: unsupported (returns None)."""
        return None
