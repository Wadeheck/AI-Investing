"""The risk layer: position sizing, stop-loss / take-profit, exposure caps, and a
daily-drawdown kill switch. Every order the engine places passes through here.
"""
from __future__ import annotations

from ai_investing.config import RiskConfig
from ai_investing.models import Decision, Order, Portfolio, Side


class RiskManager:
    def __init__(self, cfg: RiskConfig):
        self.cfg = cfg
        self.day_start_equity: float | None = None
        self.halted = False

    # --- kill switch --------------------------------------------------------
    def mark_day_start(self, equity: float) -> None:
        self.day_start_equity = equity
        self.halted = False

    def kill_switch_triggered(self, equity: float) -> bool:
        if self.day_start_equity is None:
            self.day_start_equity = equity
        if self.day_start_equity <= 0:
            return self.halted
        drawdown = (self.day_start_equity - equity) / self.day_start_equity
        if drawdown >= self.cfg.max_daily_drawdown:
            self.halted = True
        return self.halted

    # --- protective exits ---------------------------------------------------
    def stop_orders(self, portfolio: Portfolio, prices: dict[str, float]) -> list[Order]:
        orders: list[Order] = []
        for key, pos in portfolio.positions.items():
            px = prices.get(key)
            if not px or pos.qty == 0 or pos.avg_price <= 0:
                continue
            move = (px - pos.avg_price) / pos.avg_price
            if pos.qty < 0:
                move = -move  # for shorts, profit when price falls
            reason = None
            if move <= -self.cfg.per_trade_stop_loss:
                reason = f"stop-loss {move * 100:+.1f}%"
            elif move >= self.cfg.take_profit:
                reason = f"take-profit {move * 100:+.1f}%"
            if reason:
                side = Side.SELL if pos.qty > 0 else Side.BUY
                orders.append(Order(pos.asset, side, abs(pos.qty), reason=reason))
        return orders

    # --- sizing new/adjusted positions -------------------------------------
    def size_orders(self, decisions: list[Decision], portfolio: Portfolio,
                    prices: dict[str, float], equity: float) -> list[Order]:
        if equity <= 0:
            return []
        orders: list[Order] = []
        open_positions = {k for k, p in portfolio.positions.items() if abs(p.qty) > 1e-9}
        gross = portfolio.exposure(prices)
        gross_cap = self.cfg.max_gross_exposure * equity
        min_trade = 0.005 * equity  # ignore dust trades < 0.5% of equity

        # Strongest convictions first.
        for d in sorted(decisions, key=lambda x: abs(x.score) * x.confidence, reverse=True):
            key = d.asset.key
            px = prices.get(key)
            if not px:
                continue
            if d.confidence < self.cfg.min_confidence:
                continue

            target_w = max(-1.0, min(1.0, d.target_weight)) * self.cfg.max_position_weight
            if target_w < 0 and not self.cfg.allow_short:
                target_w = 0.0  # long-only: negative conviction just means exit

            cur = portfolio.positions.get(key)
            cur_notional = (cur.qty * px) if cur else 0.0
            delta = target_w * equity - cur_notional
            if abs(delta) < min_trade:
                continue

            opening_new = key not in open_positions and target_w != 0
            if opening_new and len(open_positions) >= self.cfg.max_open_positions:
                continue

            # Respect the gross exposure cap when increasing exposure.
            if abs(cur_notional + delta) > abs(cur_notional):
                if gross + abs(delta) > gross_cap:
                    delta = max(0.0, gross_cap - gross) * (1 if delta > 0 else -1)
                    if abs(delta) < min_trade:
                        continue

            side = Side.BUY if delta > 0 else Side.SELL
            orders.append(Order(d.asset, side, abs(delta) / px, reason=d.rationale[:140]))
            gross += abs(delta)
            if opening_new:
                open_positions.add(key)
        return orders
