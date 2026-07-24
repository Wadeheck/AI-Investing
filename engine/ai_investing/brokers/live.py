"""Live broker adapters. Only constructed when LIVE_TRADING=true.

These are implemented against each provider's documented SDK API, but I could not
test them against your funded accounts. Treat them as ready-to-validate, NOT proven:
run `--check-broker` (read-only) first, then trade tiny against each venue's
sandbox / SIMULATE mode before setting LIVE_TRADING=true for real.
"""
from __future__ import annotations

import os

from ai_investing.brokers.base import BrokerAdapter
from ai_investing.models import Asset, AssetClass, Order, OrderStatus, Position, Side


class CcxtBroker(BrokerAdapter):
    """Crypto execution via ccxt (Coinbase / Gemini / Binance / Kraken).

    Env: CRYPTO_API_KEY, CRYPTO_API_SECRET, CRYPTO_API_PASSWORD (Coinbase passphrase).
    Test on the exchange sandbox (Gemini sandbox, Binance testnet) first.
    """

    name = "ccxt"
    live = True

    def __init__(self, settings):
        import ccxt  # type: ignore
        self.settings = settings
        self.base = settings.base_currency
        self.client = getattr(ccxt, settings.crypto_exchange)({
            "apiKey": os.environ.get("CRYPTO_API_KEY", ""),
            "secret": os.environ.get("CRYPTO_API_SECRET", ""),
            "password": os.environ.get("CRYPTO_API_PASSWORD", ""),
            "enableRateLimit": True,
        })
        if getattr(settings, "crypto_sandbox", False):
            try:
                self.client.set_sandbox_mode(True)   # exchange testnet/sandbox (test first!)
            except Exception:
                pass

    def get_cash(self) -> float:
        free = (self.client.fetch_balance().get("free") or {})
        return float(free.get(self.base, 0.0) or 0.0)

    def get_positions(self) -> dict[str, Position]:
        out: dict[str, Position] = {}
        totals = (self.client.fetch_balance().get("total") or {})
        for cur, amt in totals.items():
            if cur == self.base or not amt or abs(float(amt)) < 1e-9:
                continue
            symbol = f"{cur}/{self.base}"
            try:
                price = float(self.client.fetch_ticker(symbol)["last"])
            except Exception:
                price = 0.0
            asset = Asset(symbol, AssetClass.CRYPTO, exchange=self.settings.crypto_exchange)
            # Exchanges don't expose cost basis via balance; use last price as avg.
            out[asset.key] = Position(asset, float(amt), price)
        return out

    def submit(self, order: Order, price: float) -> Order:
        side = "buy" if order.side is Side.BUY else "sell"
        is_limit = order.order_type is not None and order.order_type.value == "limit" and order.limit_price
        try:
            if is_limit:
                res = self.client.create_order(order.asset.symbol, "limit", side, order.qty, order.limit_price)
            else:
                res = self.client.create_order(order.asset.symbol, "market", side, order.qty)
            order.id = str(res.get("id"))
            order.filled_qty = float(res.get("filled") or (0.0 if is_limit else order.qty))
            order.filled_price = float(res.get("average") or res.get("price") or price)
            # a resting limit order may not be filled yet
            order.status = OrderStatus.FILLED if (order.filled_qty or 0) > 0 else OrderStatus.PENDING
        except Exception as exc:  # pragma: no cover - network path
            order.status = OrderStatus.REJECTED
            order.reason = f"ccxt: {exc}"
        return order

    def place_stop(self, asset, side, qty, stop_price):
        s = "sell" if side is Side.SELL else "buy"
        try:  # ccxt unified stop-loss (support varies by exchange)
            res = self.client.create_order(asset.symbol, "market", s, qty, None,
                                           {"stopLossPrice": stop_price, "reduceOnly": True})
            o = Order(asset, side, qty, reason="exchange-stop")
            o.id = str(res.get("id"))
            o.status = OrderStatus.PENDING
            return o
        except Exception:  # pragma: no cover - network path
            return None

    def validate(self) -> dict:
        return {"broker": f"ccxt:{self.settings.crypto_exchange}",
                "cash": self.get_cash(), "positions": len(self.get_positions())}


class LongbridgeBroker(BrokerAdapter):
    """Stock execution via Longbridge / LongPort OpenAPI (pip install longbridge).

    Env: LONGPORT_APP_KEY, LONGPORT_APP_SECRET, LONGPORT_ACCESS_TOKEN.
    Use fully-qualified symbols in the watchlist for live (e.g. AAPL.US, 700.HK, D05.SG).
    """

    name = "longbridge"
    live = True

    def __init__(self, settings):
        from longport.openapi import Config, TradeContext  # type: ignore
        self.settings = settings
        cfg = Config.from_apikey(app_key=os.environ["LONGPORT_APP_KEY"],
                                  app_secret=os.environ["LONGPORT_APP_SECRET"],
                                  access_token=os.environ["LONGPORT_ACCESS_TOKEN"])
        self.ctx = TradeContext(cfg)

    def _symbol(self, asset: Asset) -> str:
        return asset.symbol if "." in asset.symbol else f"{asset.symbol}.US"

    def get_cash(self) -> float:
        balances = self.ctx.account_balance()
        for b in balances:
            if getattr(b, "currency", None) == self.settings.base_currency:
                return float(b.total_cash)
        return float(balances[0].total_cash) if balances else 0.0

    def get_positions(self) -> dict[str, Position]:
        out: dict[str, Position] = {}
        resp = self.ctx.stock_positions()
        for channel in getattr(resp, "channels", []):
            for p in channel.positions:
                qty = float(p.quantity)
                if abs(qty) < 1e-9:
                    continue
                sym = p.symbol.split(".")[0]
                asset = Asset(sym, AssetClass.STOCK)
                out[asset.key] = Position(asset, qty, float(getattr(p, "cost_price", 0) or 0))
        return out

    def submit(self, order: Order, price: float) -> Order:
        from decimal import Decimal
        from longport.openapi import OrderSide, OrderType, TimeInForceType  # type: ignore
        side = OrderSide.Buy if order.side is Side.BUY else OrderSide.Sell
        qty = int(order.qty)  # whole shares
        if qty <= 0:
            order.status = OrderStatus.REJECTED
            order.reason = "qty < 1 share"
            return order
        is_limit = order.order_type is not None and order.order_type.value == "limit" and order.limit_price
        try:
            kwargs = dict(symbol=self._symbol(order.asset), side=side,
                          submitted_quantity=Decimal(str(qty)), time_in_force=TimeInForceType.Day)
            if is_limit:
                kwargs["order_type"] = OrderType.LO
                kwargs["submitted_price"] = Decimal(str(round(order.limit_price, 3)))
            else:
                kwargs["order_type"] = OrderType.MO
            resp = self.ctx.submit_order(**kwargs)
            order.id = str(getattr(resp, "order_id", ""))
            order.filled_qty = float(qty)
            order.filled_price = order.limit_price if is_limit else price
            order.status = OrderStatus.FILLED
        except Exception as exc:  # pragma: no cover - network path
            order.status = OrderStatus.REJECTED
            order.reason = f"longport: {exc}"
        return order

    def validate(self) -> dict:
        return {"broker": "longbridge", "cash": self.get_cash(),
                "positions": len(self.get_positions())}


class MoomooBroker(BrokerAdapter):
    """Stock execution via moomoo OpenAPI (pip install moomoo-api). Requires the
    moomoo OpenD gateway running at MOOMOO_HOST:MOOMOO_PORT.

    Defaults to the SIMULATE (paper) trading environment. Set MOOMOO_TRD_ENV=REAL
    only once you've validated. Watchlist symbols for live should be market-qualified
    like US.AAPL / HK.00700 / SG.D05 (this adapter prefixes bare US symbols).
    """

    name = "moomoo"
    live = True

    def __init__(self, settings):
        from moomoo import (OpenSecTradeContext, SecurityFirm, TrdEnv,  # type: ignore
                            TrdMarket)
        self.settings = settings
        self.TrdEnv = TrdEnv
        self.trd_env = TrdEnv.REAL if os.environ.get("MOOMOO_TRD_ENV", "SIMULATE").upper() == "REAL" else TrdEnv.SIMULATE
        self.ctx = OpenSecTradeContext(
            filter_trdmarket=TrdMarket.US,
            host=os.environ.get("MOOMOO_HOST", "127.0.0.1"),
            port=int(os.environ.get("MOOMOO_PORT", "11111")),
            security_firm=SecurityFirm.FUTUSG)

    def _code(self, asset: Asset) -> str:
        return asset.symbol if "." in asset.symbol else f"US.{asset.symbol}"

    def get_cash(self) -> float:
        from moomoo import RET_OK  # type: ignore
        ret, data = self.ctx.accinfo_query(trd_env=self.trd_env)
        if ret != RET_OK:
            return 0.0
        return float(data["cash"][0])

    def get_positions(self) -> dict[str, Position]:
        from moomoo import RET_OK  # type: ignore
        out: dict[str, Position] = {}
        ret, data = self.ctx.position_list_query(trd_env=self.trd_env)
        if ret != RET_OK:
            return out
        for _, row in data.iterrows():
            qty = float(row.get("qty", 0) or 0)
            if abs(qty) < 1e-9:
                continue
            sym = str(row["code"]).split(".")[-1]
            asset = Asset(sym, AssetClass.STOCK)
            out[asset.key] = Position(asset, qty, float(row.get("cost_price", 0) or 0))
        return out

    def submit(self, order: Order, price: float) -> Order:
        from moomoo import OrderType, RET_OK, TrdSide  # type: ignore
        side = TrdSide.BUY if order.side is Side.BUY else TrdSide.SELL
        qty = int(order.qty)
        if qty <= 0:
            order.status = OrderStatus.REJECTED
            order.reason = "qty < 1 share"
            return order
        is_limit = order.order_type is not None and order.order_type.value == "limit" and order.limit_price
        limit_px = order.limit_price if is_limit else price
        try:
            ret, data = self.ctx.place_order(
                price=limit_px, qty=qty, code=self._code(order.asset), trd_side=side,
                order_type=OrderType.NORMAL if is_limit else OrderType.MARKET, trd_env=self.trd_env)
            if ret != RET_OK:
                order.status = OrderStatus.REJECTED
                order.reason = f"moomoo: {data}"
            else:
                order.filled_qty = float(qty)
                order.filled_price = limit_px
                order.status = OrderStatus.FILLED
        except Exception as exc:  # pragma: no cover - network path
            order.status = OrderStatus.REJECTED
            order.reason = f"moomoo: {exc}"
        return order

    def validate(self) -> dict:
        return {"broker": f"moomoo:{self.trd_env}", "cash": self.get_cash(),
                "positions": len(self.get_positions())}
