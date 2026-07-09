"""Market-data providers behind one interface.

- synthetic : offline pseudo-random walk (default; zero setup, deterministic)
- stooq     : free real stock/ETF daily bars over HTTP (stdlib only, no key)
- yfinance  : free real stock data (pip install yfinance)
- ccxt      : real crypto OHLCV from an exchange (pip install ccxt)

Heavy libraries are imported lazily so the default path stays dependency-free.
"""
from __future__ import annotations

import csv
import io
import random
import urllib.request
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone

from ai_investing.models import Asset, AssetClass, Bar


class DataProvider(ABC):
    name = "provider"

    @abstractmethod
    def get_bars(self, asset: Asset, limit: int = 200) -> list[Bar]:
        ...

    def get_price(self, asset: Asset) -> float:
        bars = self.get_bars(asset, limit=2)
        return bars[-1].close if bars else 0.0


class SyntheticDataProvider(DataProvider):
    """Deterministic offline data so the engine runs with zero setup. Occasionally
    injects a pump so the political-hype fade signal has something to react to."""

    name = "synthetic"

    def __init__(self, seed: int = 42, days: int = 220):
        self.seed, self.days = seed, days

    def get_bars(self, asset: Asset, limit: int = 200) -> list[Bar]:
        rng = random.Random(self.seed + sum(ord(c) for c in asset.symbol))
        price = rng.uniform(20, 300)
        n = min(limit, self.days)
        now = datetime.now(timezone.utc)
        pump_at = rng.randint(int(n * 0.6), n - 3) if rng.random() < 0.3 else -1
        bars: list[Bar] = []
        for i in range(n):
            drift = rng.gauss(0.0006, 0.02) + (0.16 if i == pump_at else 0.0)
            new = max(0.5, price * (1 + drift))
            high = max(price, new) * (1 + abs(rng.gauss(0, 0.008)))
            low = min(price, new) * (1 - abs(rng.gauss(0, 0.008)))
            vol = rng.uniform(1e6, 5e6) * (4.0 if i == pump_at else 1.0)
            bars.append(Bar(now - timedelta(days=n - i), price, high, low, new, vol))
            price = new
        return bars


class StooqDataProvider(DataProvider):
    """Free real daily stock/ETF bars from stooq.com (no key, stdlib HTTP)."""

    name = "stooq"

    def get_bars(self, asset: Asset, limit: int = 200) -> list[Bar]:
        if asset.asset_class is not AssetClass.STOCK:
            return []
        symbol = asset.symbol.lower()
        url = f"https://stooq.com/q/d/l/?s={symbol}.us&i=d"
        try:
            with urllib.request.urlopen(url, timeout=15) as resp:
                text = resp.read().decode("utf-8", "replace")
        except Exception:
            return []
        bars: list[Bar] = []
        for row in csv.DictReader(io.StringIO(text)):
            try:
                bars.append(Bar(
                    datetime.strptime(row["Date"], "%Y-%m-%d").replace(tzinfo=timezone.utc),
                    float(row["Open"]), float(row["High"]), float(row["Low"]),
                    float(row["Close"]), float(row.get("Volume") or 0.0),
                ))
            except (KeyError, ValueError):
                continue
        return bars[-limit:]


class YFinanceDataProvider(DataProvider):
    """Real stock data via yfinance (lazy import)."""

    name = "yfinance"

    def get_bars(self, asset: Asset, limit: int = 200) -> list[Bar]:
        if asset.asset_class is not AssetClass.STOCK:
            return []
        try:
            import yfinance  # type: ignore
        except ImportError:
            return []
        df = yfinance.Ticker(asset.symbol).history(period="1y", interval="1d")
        bars: list[Bar] = []
        for ts, row in df.iterrows():
            bars.append(Bar(ts.to_pydatetime(), float(row["Open"]), float(row["High"]),
                            float(row["Low"]), float(row["Close"]), float(row["Volume"])))
        return bars[-limit:]


class CcxtDataProvider(DataProvider):
    """Real crypto OHLCV via ccxt (lazy import)."""

    name = "ccxt"

    def __init__(self, exchange: str = "coinbase"):
        self.exchange_id = exchange
        self._client = None

    def _client_or_none(self):
        if self._client is None:
            try:
                import ccxt  # type: ignore
            except ImportError:
                return None
            self._client = getattr(ccxt, self.exchange_id)()
        return self._client

    def get_bars(self, asset: Asset, limit: int = 200) -> list[Bar]:
        if asset.asset_class is not AssetClass.CRYPTO:
            return []
        client = self._client_or_none()
        if client is None:
            return []
        try:
            ohlcv = client.fetch_ohlcv(asset.symbol, timeframe="1d", limit=limit)
        except Exception:
            return []
        bars: list[Bar] = []
        for ts, o, h, low, c, v in ohlcv:
            bars.append(Bar(datetime.fromtimestamp(ts / 1000, tz=timezone.utc),
                            float(o), float(h), float(low), float(c), float(v)))
        return bars


class CompositeDataProvider(DataProvider):
    """Routes stocks and crypto to the right underlying provider."""

    name = "composite"

    def __init__(self, stock: DataProvider, crypto: DataProvider):
        self.stock, self.crypto = stock, crypto

    def get_bars(self, asset: Asset, limit: int = 200) -> list[Bar]:
        provider = self.crypto if asset.asset_class is AssetClass.CRYPTO else self.stock
        return provider.get_bars(asset, limit)


def get_provider(settings) -> DataProvider:
    """Build the provider stack from settings, with graceful fallbacks."""
    kind = (settings.data_provider or "synthetic").lower()
    if kind == "synthetic":
        synth = SyntheticDataProvider()
        return synth
    stock: DataProvider
    if kind == "stooq":
        stock = StooqDataProvider()
    elif kind == "yfinance":
        stock = YFinanceDataProvider()
    else:
        stock = SyntheticDataProvider()
    crypto: DataProvider = CcxtDataProvider(settings.crypto_exchange) if kind in ("ccxt", "yfinance", "stooq") else SyntheticDataProvider()
    return CompositeDataProvider(stock, crypto)
