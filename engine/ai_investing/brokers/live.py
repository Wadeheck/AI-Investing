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
    When CRYPTO_SANDBOX=true, uses CRYPTO_SANDBOX_API_KEY/SECRET/PASSWORD instead
    (sandbox accounts, e.g. exchange.sandbox.gemini.com, are separate from production
    and issue their own keys - they don't work against the production ones above).
    """

    name = "ccxt"
    live = True

    def __init__(self, settings):
        import ccxt  # type: ignore
        self.settings = settings
        self.base = settings.base_currency
        sandbox = getattr(settings, "crypto_sandbox", False)
        prefix = "CRYPTO_SANDBOX_API_" if sandbox else "CRYPTO_API_"
        self.client = getattr(ccxt, settings.crypto_exchange)({
            "apiKey": os.environ.get(f"{prefix}KEY", ""),
            "secret": os.environ.get(f"{prefix}SECRET", ""),
            "password": os.environ.get(f"{prefix}PASSWORD", ""),
            "enableRateLimit": True,
        })
        if sandbox:
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
        """Cash in BASE_CURRENCY.

        §4.2 AGAIN, IN THE LIVE ADAPTER (found 2026-08-04). `account_balance()`
        returns ONE entry per settlement currency, whose `currency` field is the
        currency the totals are *consolidated into* — for the paper account, a
        single HKD row with `total_cash=14,144,300`. The per-currency detail is in
        `cash_infos` (USD 1,000,000 + SGD 1,000,000 + HKD 1,000,000).

        The old code looked for a row whose `currency == "USD"`, found none, and
        fell through to `balances[0].total_cash` — returning **14.1M HKD as if it
        were USD**, overstating the account 7.8×. Exactly the class of error whose
        lesson was already written down: a caveat in a docstring is not a
        mitigation, and `routing.py` still carries one saying "mind
        cross-currency".
        """
        from ai_investing.data import fx

        balances = self.ctx.account_balance()
        base = self.settings.base_currency
        # 1) exact per-currency cash, the only figure that needs no conversion
        for b in balances:
            for ci in (getattr(b, "cash_infos", None) or []):
                if getattr(ci, "currency", None) == base:
                    return float(getattr(ci, "available_cash", 0) or 0)
        # 2) a row already consolidated into the base currency
        for b in balances:
            if getattr(b, "currency", None) == base:
                return float(b.total_cash)
        # 3) convert, and say so — never report a foreign figure as base
        if balances:
            b = balances[0]
            cur = getattr(b, "currency", None) or "?"
            amt = float(b.total_cash)
            rate = fx.rates(self.settings).get(cur)
            if rate:
                return amt / rate if rate > 1 else amt * rate
            print(f"  !! cannot convert {cur} {amt:,.0f} to {base} — reporting 0 cash "
                  f"rather than a wrong number")
        return 0.0

    def get_positions(self) -> dict[str, Position]:
        """Positions keyed the way the rest of the engine keys them.

        `p.symbol.split(".")[0]` USED TO BE HERE and quietly destroyed every
        non-US symbol: Longbridge reports `700.HK`, which became `700`, whose key
        `stock:700` matches nothing in a watchlist holding `0700.HK`. The engine
        would have seen its own HK holdings as somebody else's account and — since
        2026-08-04 — correctly refused to manage them (see
        runner.foreign_positions), never exiting a position it opened.

        Kept for US symbols only, where `AAPL.US` -> `AAPL` is what the watchlist
        actually uses. Anything else keeps its suffix.

        STILL WRONG for non-USD listings: `cost_price` is quoted in the listing
        currency while every price in this engine is USD-normalised, so a HK
        position's P&L would mix HKD against USD. That is why the live book is
        restricted to USD listings for now (see runner._live_universe) instead of
        being papered over here.
        """
        from ai_investing.data import fx

        out: dict[str, Position] = {}
        resp = self.ctx.stock_positions()
        for channel in getattr(resp, "channels", []):
            for p in channel.positions:
                qty = float(p.quantity)
                if abs(qty) < 1e-9:
                    continue
                sym = self.watchlist_symbol(p.symbol)
                asset = Asset(sym, AssetClass.STOCK)
                # §4.2, third appearance. cost_price arrives in the LISTING currency
                # while every price in this engine is USD-normalised, so an HK
                # position's basis would be compared against a USD mark — the exact
                # error that once read SK Hynix at $1.59M a share. Converted at the
                # boundary, like every other price.
                cost = float(getattr(p, "cost_price", 0) or 0)
                out[asset.key] = Position(asset, qty, fx.to_usd(cost, sym, self.settings))
        return out

    @staticmethod
    def watchlist_symbol(broker_symbol: str) -> str:
        """Longbridge's symbol -> the form this engine's watchlist uses.

        Two conversions, both learned the hard way:

        `.US` is stripped, because the watchlist says `AAPL`, not `AAPL.US`. The
        original code did `symbol.split(".")[0]` for every market, which turned
        `700.HK` into `700` and matched nothing at all.

        HK codes are zero-padded to four digits. Longbridge reports `700.HK`; the
        watchlist holds `0700.HK`. Same instrument, different string, and a dict
        lookup does not care that a human can see they are the same — the position
        would be classed as foreign and left unmanaged forever (see
        runner.foreign_positions).
        """
        s = (broker_symbol or "").strip()
        if s.upper().endswith(".US"):
            return s[:-3]
        if s.upper().endswith(".HK"):
            code, _, suffix = s.rpartition(".")
            if code.isdigit():
                return f"{int(code):04d}.{suffix.upper()}"
        return s

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
            # NEVER ASSUME THE FILL (fixed 2026-08-04). This used to read:
            #
            #     order.filled_qty = float(qty)
            #     order.filled_price = order.limit_price if is_limit else price
            #     order.status = OrderStatus.FILLED
            #
            # submit_order only ACKNOWLEDGES an order. It does not fill it. So the
            # adapter reported every accepted order as fully filled, at the price it
            # had merely hoped for: an exchange rejection recorded as a fill, a
            # partial recorded as complete, a resting limit recorded as done, and
            # every slippage and P&L figure downstream computed from a price that
            # was never traded. The book would have been fiction while every check
            # stayed green — and the ledger, the breaker and the learning spine all
            # read from it.
            self._confirm(order, price, is_limit)
        except Exception as exc:  # pragma: no cover - network path
            order.status = OrderStatus.REJECTED
            order.reason = f"longport: {exc}"
        return order

    # Longport status -> ours. Anything unmapped is deliberately NOT treated as a
    # fill: an unknown state must never be optimistically booked as executed.
    _TERMINAL_FILLED = {"Filled"}
    _TERMINAL_DEAD = {"Rejected", "Canceled", "Expired"}

    def _confirm(self, order: Order, mark: float, is_limit: bool,
                 attempts: int = 4, pause: float = 0.75) -> None:
        """Ask the broker what actually happened, and record only that.

        A market order normally fills in well under a second, but "normally" is not
        a guarantee, so this polls briefly and then reports the true state rather
        than guessing. A still-open order is PENDING, not FILLED — the runner and
        the ledger can handle a pending order; they cannot handle a lie.
        """
        import time as _time

        if not order.id:
            order.status = OrderStatus.PENDING
            order.reason = (order.reason or "") + " [no order id returned]"
            return
        last = None
        for i in range(attempts):
            try:
                d = self.ctx.order_detail(order.id)
            except Exception as exc:                     # transient: keep trying
                last = exc
                _time.sleep(pause)
                continue
            status = str(getattr(d, "status", "") or "").split(".")[-1]
            executed = float(getattr(d, "executed_quantity", 0) or 0)
            exec_px = float(getattr(d, "executed_price", 0) or 0)
            order.filled_qty = executed
            # Only trust a real execution price. Falling back to the mark is how the
            # old code invented fills; here it is used solely to keep the field
            # numeric when nothing has executed yet (filled_qty is 0 in that case,
            # so no P&L is derived from it).
            order.filled_price = exec_px if exec_px > 0 else (order.limit_price or mark)
            if status in self._TERMINAL_FILLED and executed > 0:
                order.status = OrderStatus.FILLED
                return
            if status in self._TERMINAL_DEAD:
                order.status = OrderStatus.REJECTED if status == "Rejected" else OrderStatus.CANCELLED
                order.reason = f"{order.reason or ''} [broker: {status}]".strip()
                return
            if executed > 0 and i == attempts - 1:
                # A partial that is still working. There is no PARTIAL status in this
                # codebase, and adding one would ripple through the journal and the
                # dashboard for little gain: `filled_qty` already carries the truth,
                # and every downstream calculation (notional, position, breaker,
                # ledger) reads that rather than the enum. Marked FILLED for the
                # quantity that ACTUALLY executed, with the shortfall in the reason.
                order.status = OrderStatus.FILLED
                order.reason = f"{order.reason or ''} [partial {executed:g}/{order.qty:g}]".strip()
                return
            if i < attempts - 1:
                _time.sleep(pause)
        order.status = OrderStatus.PENDING
        order.reason = (f"{order.reason or ''} [unconfirmed after {attempts} checks"
                        + (f": {last}" if last else "") + "]").strip()

    def place_stop(self, asset, side, qty: float, stop_price: float):
        """Rest a protective STOP at Longbridge, so it survives a crash and fires on
        an intraday gap between cycles.

        `MIT` = market-if-touched: when the trigger prints, a market order goes out.
        That is the right instrument for a protective stop — a limit-if-touched can be
        skipped straight through in exactly the fast move a stop exists for, and an
        un-executed stop is not a stop.

        Deliberately NOT trailing, though TSLPPCT/TSLPAMT exist. A trailing stop moves
        the exit on its own, which would silently diverge from the level the position
        was sized against and from what the learning ledger recorded as the claim. One
        source of truth for the exit.
        """
        from decimal import Decimal
        from longport.openapi import OrderSide, OrderType, TimeInForceType  # type: ignore

        q = int(qty)
        if q <= 0 or stop_price <= 0:
            return None
        try:
            resp = self.ctx.submit_order(
                symbol=self._symbol(asset),
                side=OrderSide.Sell if side is Side.SELL else OrderSide.Buy,
                order_type=OrderType.MIT,
                submitted_quantity=Decimal(str(q)),
                trigger_price=Decimal(str(round(stop_price, 3))),
                time_in_force=TimeInForceType.GoodTilCanceled)
            o = Order(asset, side, float(q), reason="exchange-stop")
            o.id = str(getattr(resp, "order_id", ""))
            o.status = OrderStatus.PENDING      # resting until touched — correct here
            return o
        except Exception as exc:
            print(f"  !! exchange stop REJECTED for {asset.symbol} @ {stop_price}: {exc}")
            return None

    def place_take_profit(self, asset, side, qty: float, limit_price: float):
        """Rest a take-profit at Longbridge. `LIT` = limit-if-touched: once the level
        prints, a limit order goes out at that price.

        A limit is right here and wrong for the stop above, and the asymmetry is the
        point: on the profit side a missed fill costs an opportunity; on the loss side
        it costs the position.
        """
        from decimal import Decimal
        from longport.openapi import OrderSide, OrderType, TimeInForceType  # type: ignore

        q = int(qty)
        if q <= 0 or limit_price <= 0:
            return None
        px = Decimal(str(round(limit_price, 3)))
        try:
            resp = self.ctx.submit_order(
                symbol=self._symbol(asset),
                side=OrderSide.Sell if side is Side.SELL else OrderSide.Buy,
                order_type=OrderType.LIT,
                submitted_quantity=Decimal(str(q)),
                trigger_price=px, submitted_price=px,
                time_in_force=TimeInForceType.GoodTilCanceled)
            o = Order(asset, side, float(q), reason="exchange-take-profit")
            o.id = str(getattr(resp, "order_id", ""))
            o.status = OrderStatus.PENDING
            return o
        except Exception as exc:
            print(f"  !! exchange take-profit REJECTED for {asset.symbol} @ {limit_price}: {exc}")
            return None

    def cancel(self, order_id: str) -> bool:
        try:
            self.ctx.cancel_order(order_id)
            return True
        except Exception as exc:
            print(f"  !! cancel failed for {order_id}: {exc}")
            return False

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
