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
    # Was CcxtBroker (Gemini) — replaced, Gemini wasn't a working venue in
    # practice. long_only mirrors RISK_ALLOW_SHORT, same as the PaperBroker
    # fallback above. Runs on its own testnet account (crypto_trading_binance_*),
    # separate from the two crypto sleeves' accounts (crypto_book.py,
    # crypto_event_sleeve.py) — this book trades the full crypto watchlist,
    # not just majors, so sharing an account with either sleeve would let
    # their positions net together and corrupt each book's own tracking.
    from ai_investing.brokers.live import BinanceFuturesBroker
    return BinanceFuturesBroker(
        settings, long_only=not settings.risk.allow_short,
        api_key=settings.crypto_trading_binance_api_key,
        api_secret=settings.crypto_trading_binance_api_secret)


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
