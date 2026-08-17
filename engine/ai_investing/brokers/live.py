"""Live broker adapters. Only constructed when LIVE_TRADING=true.

These are implemented against each provider's documented SDK API, but I could not
test them against your funded accounts. Treat them as ready-to-validate, NOT proven:
run `--check-broker` (read-only) first, then trade tiny against each venue's
sandbox / SIMULATE mode before setting LIVE_TRADING=true for real.
"""
from __future__ import annotations

import math
import os

from ai_investing.brokers.base import BrokerAdapter
from ai_investing.models import Asset, AssetClass, Order, OrderStatus, Position, Side

# HKEX spread table: (price is below this) -> minimum tick. Ends open-ended.
_HK_SPREADS = ((0.25, 0.001), (0.50, 0.005), (10.0, 0.010), (20.0, 0.020),
               (100.0, 0.050), (200.0, 0.100), (500.0, 0.200), (1000.0, 0.500),
               (2000.0, 1.000), (5000.0, 2.000), (float("inf"), 5.000))


def tick_size(symbol: str, price: float) -> float:
    """Minimum price increment for a fully-qualified symbol at a given price.

    Longbridge rejects any limit price off the tick with code 602035, "Wrong bid
    size, please change the price". Confirmed against the paper account on
    2026-08-10 with two orders identical but for the third decimal:
    AAPL.US @ 275.90 accepted, @ 275.903 rejected 602035.
    """
    mkt = symbol.rsplit(".", 1)[-1].upper() if "." in symbol else "US"
    if mkt == "HK":
        for below, tick in _HK_SPREADS:
            if price < below:
                return tick
    if mkt in ("SI", "SG"):
        return 0.001 if price < 1.0 else 0.01      # SGX minimum bid sizes
    # US and anything unrecognised: a penny, and a hundredth of a cent for
    # sub-dollar names. Defaulting an UNKNOWN market to the coarser US tick is
    # deliberate — too coarse merely shifts the price by a tick, while too fine
    # is the failure that cost eight live orders.
    return 0.0001 if price < 1.0 else 0.01


def _tick_decimal(price: float, symbol: str, side: Side):
    """snap_to_tick as a Decimal ready for the API, with no trailing-zero noise.

    One helper for all three order paths — entry, stop and take-profit — because
    the alternative is what actually happened: the tick rule was fixed in submit()
    and left wrong in the two that protect the position."""
    from decimal import Decimal
    px = snap_to_tick(price, symbol, side)
    return Decimal(f"{px:.4f}".rstrip("0").rstrip("."))


def snap_to_tick(price: float, symbol: str, side: Side) -> float:
    """Round a limit price onto a legal tick, never becoming more aggressive.

    A BUY limit rounds DOWN and a SELL limit rounds UP, so snapping can only ever
    make the order less likely to fill — never quietly raise what we are prepared
    to pay. The band this price came from is 25bps plus costs, so a tick either
    way is immaterial to whether it fills; being wrong in the paying direction
    would not be.
    """
    t = tick_size(symbol, price)
    steps = price / t
    # Guard the floating-point boundary: 275.90/0.01 is 27589.999... in binary,
    # which would floor to 275.89 and shift an already-legal price by a tick.
    if abs(steps - round(steps)) < 1e-6:
        steps = round(steps)
    elif side is Side.BUY:
        steps = math.floor(steps)
    else:
        steps = math.ceil(steps)
    return round(steps * t, 6)


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
            # ccxt often returns the fill inline; trust it ONLY when it is actually
            # there. The old fallback was `order.filled_qty = ... or order.qty`, which
            # invented a full fill for every market order the exchange did not report
            # on, and `... or price`, which invented the caller's mark as the traded
            # price. Same fabrication as §4.15, one degree milder.
            filled = res.get("filled")
            avg = res.get("average") or res.get("price")
            if filled is not None and float(filled) > 0 and avg and float(avg) > 0:
                order.filled_qty = float(filled)
                order.filled_price = float(avg)
                order.status = OrderStatus.FILLED
            else:
                self._symbol_for_fetch = order.asset.symbol
                self.confirm_or_pend(order)
        except Exception as exc:  # pragma: no cover - network path
            order.status = OrderStatus.REJECTED
            order.reason = f"ccxt: {exc}"
        return order

    def fetch_fill(self, order_id: str):
        """ccxt needs the symbol to query an order on most exchanges, so submit()
        stashes it. Returns None when it cannot be asked — the caller then reports
        PENDING rather than guessing."""
        sym = getattr(self, "_symbol_for_fetch", None)
        try:
            o = self.client.fetch_order(order_id, sym) if sym else self.client.fetch_order(order_id)
        except Exception:
            return None
        return (o.get("status"), o.get("filled") or 0.0,
                o.get("average") or o.get("price") or 0.0)

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
        self._assert_expected_channel()

    def _assert_expected_channel(self) -> None:
        """Refuse to start against the wrong Longbridge account.

        The access token alone decides whether orders hit the paper-trading
        account or a funded one, and nothing else in the config changes when
        the token is swapped. So on startup we ask the API which account
        channel the token maps to and require it to match
        LONGPORT_EXPECT_CHANNEL (default: lb_papertrading). To trade a real
        account, set LONGPORT_EXPECT_CHANNEL to that channel explicitly.

        Limitation: a channel only shows up in stock_positions() once it holds
        a position, so a freshly-opened empty account is unverifiable — we
        warn loudly rather than block, since it cannot be proven either way.

        This is the engine's first outbound call, so at boot it used to run
        before DNS was up and take the whole process down (see ai_investing.net).
        Only the *lookup* retries; the verdict below is still decided once and
        is fatal on the first try.
        """
        expected = os.environ.get("LONGPORT_EXPECT_CHANNEL", "lb_papertrading")
        if not expected:  # explicit opt-out: LONGPORT_EXPECT_CHANNEL=
            return
        from ai_investing.net import retry_transient
        positions = retry_transient(self.ctx.stock_positions,
                                    what="longbridge account-channel check")
        channels = [ch.account_channel for ch in positions.channels]
        wrong = [c for c in channels if c != expected]
        if wrong:
            raise RuntimeError(
                f"Longbridge token maps to account channel(s) {wrong!r}, but "
                f"LONGPORT_EXPECT_CHANNEL={expected!r}. Refusing to trade — "
                f"if this is intentional (e.g. going to a funded account), set "
                f"LONGPORT_EXPECT_CHANNEL to the new channel explicitly.")
        if not channels:
            print(f"  !! Longbridge: no positions yet, cannot verify the token's "
                  f"account channel is {expected!r} — verify manually with --check-broker")

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

        The currency hazard below IS handled: `cost_price` arrives in the listing
        currency and is converted at this boundary, like every other price. This
        docstring used to say it was "STILL WRONG for non-USD listings" and cite
        that as the reason `runner._live_universe()` restricts the book to USD —
        three lines above the `fx.to_usd` call that fixes it. A stale warning is
        worse than no warning: on 2026-08-17 it was read as a live constraint and
        repeated as fact, and the actual reasons non-USD names are not traded
        (no suffix map, no board-lot support) went unexamined for a fortnight.
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
                # `round(limit_price, 3)` sent a third decimal into a market whose
                # tick is a penny. Longbridge rejects that outright (602035), so a
                # limit order only got through when the third decimal happened to
                # be zero — about one attempt in ten, which is exactly the record:
                # eight rejects and one fill between 2026-08-05 and 08-10.
                kwargs["submitted_price"] = _tick_decimal(
                    order.limit_price, self._symbol(order.asset), order.side)
            else:
                kwargs["order_type"] = OrderType.MO
            # Stamped BEFORE the call, so a rejection carries what was sent. The
            # exception path below records nothing about the request otherwise,
            # which is precisely why 602035 could not be diagnosed.
            order.submitted_qty = float(qty)
            order.submitted_price = (float(kwargs["submitted_price"])
                                     if "submitted_price" in kwargs else None)
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
            self.confirm_or_pend(order)
        except Exception as exc:  # pragma: no cover - network path
            order.status = OrderStatus.REJECTED
            order.reason = f"longport: {exc}"
        return order

    def fetch_fill(self, order_id: str):
        """Longport's own view of the order — the only trustworthy source.

        Statuses are an enum whose names (`Filled`, `Rejected`, `Canceled`,
        `Expired`, `PartialFilled`, `New`, ...) the shared `confirm_or_pend` maps
        case-insensitively. Anything it does not recognise counts as still working,
        never as a fill: an unknown state must not be optimistically booked.
        """
        d = self.ctx.order_detail(order_id)
        return (getattr(d, "status", None),
                getattr(d, "executed_quantity", 0) or 0,
                getattr(d, "executed_price", 0) or 0)

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
                # Same tick rule as submit(). §4.23 was fixed in ONE of the three
                # places that price an order, which is §4.7's lesson wearing new
                # clothes — and this is the worst of the three to get wrong: a
                # rejected entry costs an opportunity, a rejected STOP leaves a
                # position open with nothing under it. Snapping a protective sell
                # stop rounds the trigger UP, i.e. a tick earlier, so the error is
                # always on the side of more protection.
                trigger_price=_tick_decimal(stop_price, self._symbol(asset), side),
                time_in_force=TimeInForceType.GoodTilCanceled)
            o = Order(asset, side, float(q), reason="exchange-stop")
            o.id = str(getattr(resp, "order_id", ""))
            o.status = OrderStatus.PENDING      # resting until touched — correct here
            return o
        except Exception as exc:
            # Kept on the adapter so the CALLER can journal it. The runner records
            # only `exchange_stop_unsupported` + the symbol, so when the live
            # AAPL stop failed on 2026-08-05 the reason went to stdout and died
            # with the next log rotation — leaving a live position with nothing
            # under it and no way to find out why. An unprotected position is the
            # last thing that should fail quietly.
            self.last_stop_error = f"{type(exc).__name__}: {exc}"
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
        px = _tick_decimal(limit_price, self._symbol(asset), side)   # see place_stop
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
                # NEVER assume. This read `filled_qty = qty; filled_price = limit_px;
                # status = FILLED` on any successful place_order — inventing both the
                # quantity and the price, exactly as the Longbridge adapter did
                # (§4.15). moomoo's order-status query is not implemented here and
                # cannot be tested (it needs the OpenD gateway running), so the
                # honest report is PENDING: unconfirmed, not fabricated.
                order.id = str(_moomoo_order_id(data) or "")
                self.confirm_or_pend(order, attempts=1)
        except Exception as exc:  # pragma: no cover - network path
            order.status = OrderStatus.REJECTED
            order.reason = f"moomoo: {exc}"
        return order

    def validate(self) -> dict:
        return {"broker": f"moomoo:{self.trd_env}", "cash": self.get_cash(),
                "positions": len(self.get_positions())}

def _moomoo_order_id(data) -> str | None:
    """moomoo returns a DataFrame; pull the order id if it is there."""
    try:
        return str(data["order_id"].iloc[0])
    except Exception:
        try:
            return str(data[0]["order_id"])
        except Exception:
            return None
