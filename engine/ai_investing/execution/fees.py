"""What a real US-stock fill actually costs, in dollars, at Longbridge.

WHY THIS EXISTS
---------------
`execution/costs.py` models FRICTION — spread and slippage in basis points, a
proportional haircut on the fill price. That is the right shape for market
impact and the wrong shape for a fee schedule: the two fees that dominate a
small book are a FLAT amount per trade and a per-SHARE amount, neither of which
scales with notional. On a $500 event-sleeve entry a $0.99 platform fee is
20bps; on a $50,000 one it is 0.2bps. A bps model cannot express that, so it
either flatters the small trades or punishes the large ones.

This matters now rather than later because the sleeve and the investing book are
moving off an instant-fill, zero-fee `PaperBroker` onto a real venue. Their
journals feed the win-rate and average-P&L statistics that the learning spine
sizes future trades from. A book that thinks a round trip is free will keep
taking round trips that lose money net of costs and never learn otherwise.

THE SCHEDULE (verified 2026-08-16 against Longbridge's published US pricing)
---------------------------------------------------------------------------
  - Commission:  $0. Lifetime zero-commission on US and HK stocks.
  - Platform fee: charged per order. Defaults to $0.99 here and is
    env-overridable, because Longbridge's headline offer waives it under a
    standing promotion and the waiver is not permanent. Defaulting to the
    CHARGED amount is the safe direction: a book that over-estimates its costs
    trades slightly less than it could, while one that under-estimates them
    reports profits it did not make.
  - SEC fee: $20.60 per $1,000,000 of proceeds, ON SELLS ONLY. (Was $0 from
    May 2025 through April 2026; restored 2026-04-04. A regulator's fee that
    has already been zeroed once will move again — hence the env override.)
  - FINRA Trading Activity Fee: $0.000195 per share ON SELLS ONLY, with a
    $0.01 floor and a $9.79 per-trade cap. Both bounds are real and both bind
    in this book's size range: the floor bites under 52 shares, the cap over
    50,205.

Everything is a pure function of (qty, price, side) so the whole schedule is
unit-testable without a broker, and every number is overridable from the
environment so a rate change is an .env edit rather than a deploy.
"""
from __future__ import annotations

import os

from ai_investing.models import Side


def _f(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# Per ORDER, both sides. See the module docstring on why the default is the
# charged amount rather than the promotional $0.
PLATFORM_FEE_PER_TRADE = _f("FEE_PLATFORM_PER_TRADE", 0.99)
# Per dollar of SELL proceeds.
SEC_FEE_RATE = _f("FEE_SEC_PER_MILLION", 20.60) / 1_000_000.0
# Per SHARE sold, floored and capped per order.
FINRA_TAF_PER_SHARE = _f("FEE_FINRA_TAF_PER_SHARE", 0.000195)
FINRA_TAF_MIN = _f("FEE_FINRA_TAF_MIN", 0.01)
FINRA_TAF_CAP = _f("FEE_FINRA_TAF_CAP", 9.79)


def platform_fee() -> float:
    """Flat, per order, charged on both buys and sells."""
    return PLATFORM_FEE_PER_TRADE


def sec_fee(sell_notional: float) -> float:
    """SEC Section 31 fee. Sells only; the caller decides that, not this."""
    return max(0.0, float(sell_notional)) * SEC_FEE_RATE


def finra_taf(sell_shares: float) -> float:
    """FINRA TAF, floored and capped. Zero shares costs zero — the $0.01 floor
    is a floor on a CHARGE, not a charge on a non-trade."""
    shares = max(0.0, float(sell_shares))
    if shares <= 0:
        return 0.0
    return min(max(shares * FINRA_TAF_PER_SHARE, FINRA_TAF_MIN), FINRA_TAF_CAP)


def fill_fee(side: Side, qty: float, price: float) -> float:
    """The total cash cost of ONE filled leg. This is the function to call.

    Charged at the moment of the fill rather than estimated over a round trip,
    because a round trip is not an object this engine has: a position can be
    entered once and trimmed three times, entered as a short and closed as a
    buy, or left open across a restart. Every one of those is a sequence of
    legs, and every leg is billed on its own.
    """
    qty = max(0.0, float(qty))
    price = max(0.0, float(price))
    if qty <= 0 or price <= 0:
        return 0.0
    fee = platform_fee()
    if side is Side.SELL:
        fee += sec_fee(qty * price) + finra_taf(qty)
    return fee


def round_trip_fee(entry_qty: float, entry_price: float,
                   exit_qty: float, exit_price: float) -> float:
    """Both legs of a complete round trip. For EX-ANTE estimates only — "is this
    trade worth taking at all" — never for booking a fill, which goes through
    `fill_fee` one leg at a time.
    """
    return (fill_fee(Side.BUY, entry_qty, entry_price)
            + fill_fee(Side.SELL, exit_qty, exit_price))
