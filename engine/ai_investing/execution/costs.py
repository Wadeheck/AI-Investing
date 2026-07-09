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

from dataclasses import dataclass

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
