"""Routes orders to the right live broker by asset class: crypto -> Binance Futures,
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
        self._check_equity_is_reconstructable()

    def _check_equity_is_reconstructable(self) -> None:
        """Refuse a config where the main book's equity formula silently lies.

        §4.36 fixed `cash + sum(qty * price)` for the two crypto SLEEVES, which
        each own one broker and can therefore just ask the venue via
        `get_equity()`. This book cannot: the runner values it through
        `Portfolio.equity(prices)`, which needs ONE cash figure spanning two
        venues, and `get_equity()` returns a finished number with no way to
        blend a venue's own equity with a mark-to-market of the other leg's
        stock positions. So the reconstruction stays — and it is only correct
        for the margined leg under both of these:

          * leverage == 1: initial margin then equals the position's notional,
            so the cash the venue locks and the `qty * price` the formula adds
            back cancel, leaving wallet + unrealized — the right answer.
            At 2x, half the notional is added back that was never deducted.
          * long_only: a SHORT is the §4.36 case outright. Margin is locked
            (cash down) AND `qty * price` is negative, so the notional is
            subtracted twice — the -$4,265-on-a-flat-book signature.

        Both are one env var away (`CRYPTO_FUTURES_LEVERAGE`,
        `RISK_ALLOW_SHORT`), neither would raise anything on its own, and the
        number they corrupt is what the circuit breaker halts on (§4.7). Fail
        at construction, loudly, rather than trade against a fictional equity.
        """
        if not getattr(self.crypto, "margined", False):
            return
        # The blend is available: the crypto leg is valued by its own venue
        # (`venue_equity_parts`), so leverage and direction no longer corrupt
        # the number and neither condition below is load-bearing any more.
        # The guard stays for the case where the venue cannot be read at
        # startup, because then the book really does fall back to
        # `cash + qty*price` and both conditions bite again.
        if self.venue_equity_parts() is not None:
            return
        why = []
        if int(getattr(self.crypto, "leverage", 1) or 1) != 1:
            why.append(f"leverage is {self.crypto.leverage}x, not 1x "
                       "(CRYPTO_FUTURES_LEVERAGE)")
        if not getattr(self.crypto, "long_only", True):
            why.append("the crypto leg can short (RISK_ALLOW_SHORT)")
        if why:
            raise RuntimeError(
                "RoutingBroker refuses to start: this book reconstructs equity as "
                "cash + qty*price, which a margined crypto leg only satisfies at 1x "
                f"long-only — but {', and '.join(why)}. See failure register §4.36; "
                "fixing this properly means teaching Portfolio.equity() to blend a "
                "venue's own equity with a marked stock leg, not relaxing this check.")

    def get_equity(self) -> float | None:
        """None on purpose. There is no single venue to ask, and returning the
        crypto leg's own equity here would drop the entire stock book out of the
        number. The blend happens in `Portfolio.equity` via
        `venue_equity_parts()` below, which is the §4.36 fix proper."""
        return None

    def venue_equity_parts(self):
        """Split this book so a margined crypto leg is valued by its own venue.

            equity = stock cash + marked stock positions + crypto venue equity

        The crypto term is the venue's own figure (wallet + unrealized), which
        is correct at ANY leverage and in EITHER direction — so the two
        conditions `_check_equity_is_reconstructable` used to enforce stop being
        load-bearing once this is available.

        Returns None when the crypto leg is not margined (nothing to blend, keep
        the old formula) or when the venue cannot be read — in which case the
        caller falls back to the reconstruction, and the startup guard is what
        keeps that fallback honest.
        """
        if not getattr(self.crypto, "margined", False):
            return None
        try:
            eq = self.crypto.get_equity()
        except Exception:
            return None
        if eq is None:
            return None
        from ai_investing.models import AssetClass
        return float(self.stock.get_cash()), {AssetClass.CRYPTO: float(eq)}

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
