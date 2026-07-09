from ai_investing.brokers.base import BrokerAdapter
from ai_investing.brokers.paper import PaperBroker

__all__ = ["BrokerAdapter", "PaperBroker", "get_broker", "build_live_broker"]


def _make_stock_broker(settings) -> BrokerAdapter:
    broker = (settings.stock_broker or "paper").lower()
    if broker == "longbridge":
        from ai_investing.brokers.live import LongbridgeBroker
        return LongbridgeBroker(settings)
    if broker == "moomoo":
        from ai_investing.brokers.live import MoomooBroker
        return MoomooBroker(settings)
    return PaperBroker(settings.starting_cash, allow_short=settings.risk.allow_short)


def _make_crypto_broker(settings) -> BrokerAdapter:
    from ai_investing.brokers.live import CcxtBroker
    return CcxtBroker(settings)


def build_live_broker(settings) -> BrokerAdapter:
    """Construct the routed live broker (stocks + crypto). Used in live mode and by
    the read-only --check-broker validation."""
    from ai_investing.brokers.routing import RoutingBroker
    return RoutingBroker(_make_stock_broker(settings), _make_crypto_broker(settings))


def get_broker(settings) -> BrokerAdapter:
    """Paper mode (default) => a single simulated broker. Live mode => routed live
    brokers. Live adapters are only imported/constructed when LIVE_TRADING=true, so a
    missing SDK or missing keys can never accidentally route real orders."""
    if not settings.live:
        return PaperBroker(settings.starting_cash, allow_short=settings.risk.allow_short)
    return build_live_broker(settings)
