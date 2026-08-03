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
import time
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

    def __init__(self, timeframe: str = "1d"):
        self.timeframe = timeframe

    def get_bars(self, asset: Asset, limit: int = 200) -> list[Bar]:
        if asset.asset_class is not AssetClass.STOCK:
            return []
        try:
            import yfinance  # type: ignore
        except ImportError:
            return []
        period = "1y" if self.timeframe.endswith(("d", "wk", "mo")) else "60d"  # intraday needs a short window
        df = yfinance.Ticker(asset.symbol).history(period=period, interval=self.timeframe)
        bars: list[Bar] = []
        for ts, row in df.iterrows():
            bars.append(Bar(ts.to_pydatetime(), float(row["Open"]), float(row["High"]),
                            float(row["Low"]), float(row["Close"]), float(row["Volume"])))
        return bars[-limit:]


class CcxtDataProvider(DataProvider):
    """Real crypto OHLCV via ccxt (lazy import)."""

    name = "ccxt"

    def __init__(self, exchange: str = "coinbase", timeframe: str = "1d"):
        self.exchange_id = exchange
        self.timeframe = timeframe
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
            ohlcv = client.fetch_ohlcv(asset.symbol, timeframe=self.timeframe, limit=limit)
        except Exception:
            return []
        bars: list[Bar] = []
        for ts, o, h, low, c, v in ohlcv:
            bars.append(Bar(datetime.fromtimestamp(ts / 1000, tz=timezone.utc),
                            float(o), float(h), float(low), float(c), float(v)))
        return bars

    def spot(self, symbols: list[str]) -> dict[str, float]:
        """Live last-traded price, for valuation and stops only.

        Crypto trades around the clock but the books run on daily bars, so a
        position could sit all night marked at yesterday's close: a 10% stop
        measured off a stale mark is not a 10% stop. Signals deliberately keep
        using the daily bars — those are what the walk-forward gauntlet
        validated, and live spot must not quietly change what gets traded, only
        what gets protected.
        """
        client = self._client_or_none()
        if client is None or not symbols:
            return {}
        out: dict[str, float] = {}
        try:
            tickers = client.fetch_tickers(symbols)
            for sym, t in (tickers or {}).items():
                px = t.get("last") or t.get("close")
                if px:
                    out[sym] = float(px)
        except Exception:
            for sym in symbols:            # exchanges that reject bulk tickers
                try:
                    t = client.fetch_ticker(sym)
                    px = t.get("last") or t.get("close")
                    if px:
                        out[sym] = float(px)
                except Exception:
                    continue
        return out


class LastGoodBarCache(DataProvider):
    """Serve the last good bars when the upstream feed returns nothing.

    yfinance rate-limits by answering "possibly delisted; no price data found"
    for EVERY symbol at once. When that happened the whole book marked at price
    0: equity read as exactly cash, and only an accident of representation
    (`if not px` treating 0.0 as falsy) stopped stops from liquidating
    everything at a fabricated -100%.

    A blanket empty response is far more likely to be the provider throttling
    us than every holding delisting simultaneously, so the previous bars are
    reused and the staleness is left for DataGuard to judge on its own terms.
    Serving a slightly old price is strictly safer than serving no price:
    downstream, "no price" silently becomes zero.

    Genuinely delisted names age out via the guard's staleness check, so this
    cannot hide a real problem indefinitely.
    """

    name = "last-good-cache"
    MAX_AGE_S = 6 * 3600.0

    def __init__(self, inner: DataProvider):
        self.inner = inner
        self._cache: dict[str, tuple[float, list[Bar]]] = {}

    def get_bars(self, asset: Asset, limit: int = 200) -> list[Bar]:
        bars = self.inner.get_bars(asset, limit)
        now = time.time()
        if bars:
            self._cache[asset.key] = (now, bars)
            return bars
        hit = self._cache.get(asset.key)
        if hit and now - hit[0] < self.MAX_AGE_S:
            return hit[1]
        return bars

    def spot(self, symbols: list[str]) -> dict[str, float]:
        fn = getattr(self.inner, "spot", None)
        return fn(symbols) if fn else {}


class CompositeDataProvider(DataProvider):
    """Routes stocks and crypto to the right underlying provider."""

    name = "composite"

    def __init__(self, stock: DataProvider, crypto: DataProvider):
        self.stock, self.crypto = stock, crypto

    def get_bars(self, asset: Asset, limit: int = 200) -> list[Bar]:
        provider = self.crypto if asset.asset_class is AssetClass.CRYPTO else self.stock
        return provider.get_bars(asset, limit)

    def spot(self, symbols: list[str]) -> dict[str, float]:
        fn = getattr(self.crypto, "spot", None)
        return fn(symbols) if fn else {}


class UsdNormalizingProvider(DataProvider):
    """Wraps a provider so every bar comes back priced in USD.

    Placed at the data layer on purpose. The engine holds HK, KR, JP, TW, CN
    and EU names alongside US ones and sums them into a single equity figure;
    without this, 1,591,000 KRW read as $1,591,000 and the sizer bought a
    thousandth of a share. Normalising here means signals, sizing, stops, P&L
    and the learning spine all reason in one unit without knowing FX exists.
    Fixing it only at display would have left the trading maths just as wrong.
    """

    name = "usd-normalized"

    def __init__(self, inner: DataProvider, settings):
        self.inner, self.settings = inner, settings

    def get_bars(self, asset: Asset, limit: int = 200) -> list[Bar]:
        bars = self.inner.get_bars(asset, limit)
        if not bars:
            return bars
        from ai_investing.data import fx
        rate = fx.rate_for(asset.symbol, self.settings, asset.asset_class.value)
        if not rate or rate <= 0:
            return bars
        return [Bar(b.ts, b.open / rate, b.high / rate, b.low / rate,
                    b.close / rate, b.volume) for b in bars]

    def spot(self, symbols: list[str]) -> dict[str, float]:
        fn = getattr(self.inner, "spot", None)
        return fn(symbols) if fn else {}


def get_provider(settings) -> DataProvider:
    """Build the provider stack from settings, with graceful fallbacks."""
    kind = (settings.data_provider or "synthetic").lower()
    tf = getattr(settings, "data_timeframe", "1d")
    if kind == "synthetic":
        return SyntheticDataProvider()
    stock: DataProvider
    if kind == "stooq":
        stock = StooqDataProvider()
    elif kind == "yfinance":
        stock = YFinanceDataProvider(tf)
    else:
        stock = SyntheticDataProvider()
    crypto: DataProvider = (CcxtDataProvider(settings.crypto_exchange, tf)
                            if kind in ("ccxt", "yfinance", "stooq") else SyntheticDataProvider())
    # crypto pairs are already USD-quoted; only the stock leg needs converting
    # cache first (absorb blanket feed failures), then normalise to USD
    return CompositeDataProvider(
        UsdNormalizingProvider(LastGoodBarCache(stock), settings), crypto)
