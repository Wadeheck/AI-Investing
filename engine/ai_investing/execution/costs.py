"""Transaction-cost & slippage model.

Without this, backtests fill for free and the optimizer happily selects high-churn
strategies that are net-negative once real costs hit. Every fill is penalized by:

  commission + half-spread  (fixed bps per side)         -> the fee you always pay
  market impact             ~ coef · vol · sqrt(Q / ADV)  -> square-root impact law

so bigger orders (relative to average daily volume) and more volatile names cost more.
The result is a *price penalty*: buys fill above mid, sells below. Defaults are rough —
calibrate `COST_*` to your venues.
"""
from __future__ import annotations

from dataclasses import dataclass, replace as _dc_replace

from ai_investing.models import Side


@dataclass
class CostModel:
    commission_bps: float = 1.0    # per-side commission (0.01%)
    spread_bps: float = 2.0        # half-spread paid per side
    slippage_coef: float = 0.1     # square-root market-impact coefficient
    enabled: bool = True

    def cost_fraction(self, qty: float, price: float, adv: float | None, vol: float | None) -> float:
        if not self.enabled or price <= 0 or qty <= 0:
            return 0.0
        frac = (self.commission_bps + self.spread_bps) / 1e4
        if adv and adv > 0:
            participation = qty / adv                      # share of average daily volume
            impact = self.slippage_coef * (vol or 0.02) * (participation ** 0.5)
            frac += impact
        return frac

    def effective_price(self, side: Side, price: float, qty: float,
                        adv: float | None = None, vol: float | None = None) -> float:
        """Mid price worsened by costs — buys up, sells down."""
        frac = self.cost_fraction(qty, price, adv, vol)
        return price * (1 + frac) if side is Side.BUY else price * (1 - frac)


# ---------------------------------------------------------------------------
# Per-market frictions (evidence protocol v2, same table the walk-forward
# trainer uses): commissions + transaction taxes (HK stamp duty, KR/TW
# sell-side taxes averaged across sides) + realistic half-spreads. A flat
# US-grade 3bps would flatter every HK/Asia/crypto fill — paper must lose
# money exactly where real money would.
MARKET_COSTS_BPS = {
    "us":     (1.5, 2.5),
    "hk":     (15.0, 10.0),
    "cn":     (5.0, 5.0),
    "sg":     (8.0, 12.0),
    "jp":     (3.0, 5.0),
    "kr":     (12.0, 6.0),
    "tw":     (17.0, 6.0),
    "eu":     (5.0, 5.0),
    "crypto": (10.0, 5.0),
}

_SUFFIX_MKT = {"HK": "hk", "SS": "cn", "SZ": "cn", "SI": "sg", "T": "jp",
               "KS": "kr", "KQ": "kr", "TW": "tw", "TWO": "tw",
               "PA": "eu", "DE": "eu", "AS": "eu", "L": "eu", "MI": "eu"}


def market_of_symbol(symbol: str, asset_class: str = "stock") -> str:
    """Map a watchlist symbol to its cost market ('700.HK' -> 'hk')."""
    if asset_class == "crypto" or "/" in symbol:
        return "crypto"
    if "." in symbol:
        return _SUFFIX_MKT.get(symbol.rsplit(".", 1)[-1].upper(), "us")
    return "us"


def market_cost_model(base: "CostModel", market: str) -> "CostModel":
    """The base model (carries enabled/slippage_coef from settings) re-priced
    with the market's commission+spread."""
    comm, spr = MARKET_COSTS_BPS.get(market, MARKET_COSTS_BPS["us"])
    return _dc_replace(base, commission_bps=comm, spread_bps=spr)
