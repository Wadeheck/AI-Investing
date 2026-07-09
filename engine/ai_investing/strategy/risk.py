"""The risk layer. Every order passes through here. Beyond the original caps and the
daily kill switch it now does real portfolio risk management:

  - VOL TARGETING  : size each position toward equal risk (∝ target_vol / asset_vol),
                     so a calm blue chip and a wild memecoin don't get the same weight.
  - ATR STOPS      : stops/takes scale with each asset's true range, not a flat %.
  - CORRELATION    : shrink a candidate that's highly correlated with the current book
                     (five correlated longs should not read as five independent bets).
  - PORTFOLIO VOL  : scale the whole book down if projected portfolio vol exceeds target.
  - DRAWDOWN DERISK: gross exposure shrinks as drawdown from the equity peak grows.
  - REGIME GATE    : cut size in high-vol regimes / when features are out-of-distribution.

`market` (a dict key -> MarketStats) and `model` are optional; without them the manager
degrades to the original simple caps, so existing callers/tests keep working.
"""
from __future__ import annotations

from typing import Optional

from ai_investing.config import RiskConfig
from ai_investing.indicators import correlation
from ai_investing.models import Decision, Order, Portfolio, Side


def _avg(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


class RiskManager:
    def __init__(self, cfg: RiskConfig, regime_gate=None):
        self.cfg = cfg
        self.regime = regime_gate
        self.day_start_equity: Optional[float] = None
        self.peak_equity: Optional[float] = None
        self.halted = False

    # --- kill switch --------------------------------------------------------
    def mark_day_start(self, equity: float) -> None:
        self.day_start_equity = equity
        self.peak_equity = equity
        self.halted = False

    def kill_switch_triggered(self, equity: float) -> bool:
        if self.day_start_equity is None:
            self.day_start_equity = equity
        if self.day_start_equity <= 0:
            return self.halted
        if (self.day_start_equity - equity) / self.day_start_equity >= self.cfg.max_daily_drawdown:
            self.halted = True
        return self.halted

    def _update_peak(self, equity: float) -> None:
        self.peak_equity = equity if self.peak_equity is None else max(self.peak_equity, equity)

    # --- protective exits ---------------------------------------------------
    def stop_orders(self, portfolio: Portfolio, prices: dict[str, float], market=None) -> list[Order]:
        orders: list[Order] = []
        for key, pos in portfolio.positions.items():
            px = prices.get(key)
            if not px or pos.qty == 0 or pos.avg_price <= 0:
                continue
            move = (px - pos.avg_price) / pos.avg_price
            if pos.qty < 0:
                move = -move

            stop_frac, take_frac = self.cfg.per_trade_stop_loss, self.cfg.take_profit
            ms = market.get(key) if market else None
            if self.cfg.use_atr_stops and ms and ms.atr > 0:
                atr_frac = ms.atr / pos.avg_price
                stop_frac = self.cfg.atr_stop_mult * atr_frac
                take_frac = self.cfg.atr_take_mult * atr_frac

            reason = None
            if move <= -stop_frac:
                reason = f"stop {move * 100:+.1f}%"
            elif move >= take_frac:
                reason = f"take {move * 100:+.1f}%"
            if reason:
                side = Side.SELL if pos.qty > 0 else Side.BUY
                orders.append(Order(pos.asset, side, abs(pos.qty), reason=reason))
        return orders

    # --- sizing -------------------------------------------------------------
    def size_orders(self, decisions: list[Decision], portfolio: Portfolio,
                    prices: dict[str, float], equity: float, market=None, model=None) -> list[Order]:
        if equity <= 0:
            return []
        cfg = self.cfg
        self._update_peak(equity)

        drawdown = 0.0 if not self.peak_equity else max(0.0, (self.peak_equity - equity) / self.peak_equity)
        derisk = max(cfg.dd_derisk_floor, 1.0 - cfg.dd_derisk_scale * drawdown)
        gross_cap = cfg.max_gross_exposure * equity * derisk

        regime_mult = 1.0
        if self.regime and market:
            regime_mult = self.regime.vol_multiplier(_avg([m.vol for m in market.values()]))

        open_keys = {k for k, p in portfolio.positions.items() if abs(p.qty) > 1e-9}
        gross = portfolio.exposure(prices)
        min_trade = 0.005 * equity
        orders: list[Order] = []

        for d in sorted(decisions, key=lambda x: abs(x.score) * x.confidence, reverse=True):
            key = d.asset.key
            px = prices.get(key)
            if not px or d.confidence < cfg.min_confidence:
                continue

            target_w = max(-1.0, min(1.0, d.target_weight)) * cfg.max_position_weight
            if target_w < 0 and not cfg.allow_short:
                target_w = 0.0

            ms = market.get(key) if market else None
            if cfg.use_vol_target and ms and ms.vol > 1e-6:
                target_w *= min(3.0, cfg.target_position_vol / ms.vol)  # equal-risk, capped boost
            target_w = max(-cfg.max_position_weight, min(cfg.max_position_weight, target_w))

            if cfg.corr_penalty > 0 and market and ms and ms.returns:
                others = [market[k].returns for k in open_keys if k != key and k in market and market[k].returns]
                avg_corr = _avg([abs(correlation(ms.returns, r)) for r in others]) if others else 0.0
                target_w *= max(0.0, 1.0 - cfg.corr_penalty * avg_corr)

            mult = regime_mult
            if self.regime and model is not None and d.features:
                phi = [d.features.get(n, 0.0) for n in model.feature_names]
                mult = min(mult, self.regime.ood_multiplier(phi))
            target_w *= mult

            cur = portfolio.positions.get(key)
            cur_notional = (cur.qty * px) if cur else 0.0
            delta = target_w * equity - cur_notional
            if abs(delta) < min_trade:
                continue

            opening_new = key not in open_keys and target_w != 0
            if opening_new and len(open_keys) >= cfg.max_open_positions:
                continue

            if abs(cur_notional + delta) > abs(cur_notional) and gross + abs(delta) > gross_cap:
                delta = max(0.0, gross_cap - gross) * (1 if delta > 0 else -1)
                if abs(delta) < min_trade:
                    continue

            side = Side.BUY if delta > 0 else Side.SELL
            orders.append(Order(d.asset, side, abs(delta) / px, reason=d.rationale[:140]))
            gross += abs(delta)
            if opening_new:
                open_keys.add(key)

        return self._apply_portfolio_vol_target(orders, portfolio, prices, equity, market)

    # --- portfolio volatility target ---------------------------------------
    def _portfolio_vol(self, notionals: dict[str, float], equity: float, market) -> float:
        keys = [k for k in notionals if market and k in market and market[k].returns]
        if not keys or equity <= 0:
            return 0.0
        w = {k: notionals[k] / equity for k in keys}
        var = 0.0
        for i in keys:
            for j in keys:
                rho = 1.0 if i == j else correlation(market[i].returns, market[j].returns)
                var += w[i] * w[j] * market[i].vol * market[j].vol * rho
        return var ** 0.5 if var > 0 else 0.0

    def _apply_portfolio_vol_target(self, orders, portfolio, prices, equity, market):
        cfg = self.cfg
        if not market or cfg.portfolio_vol_target <= 0 or not orders:
            return orders
        notionals = {k: p.qty * prices.get(k, p.avg_price) for k, p in portfolio.positions.items()}
        for o in orders:
            k = o.asset.key
            signed = o.qty * prices.get(k, 0.0) * (1 if o.side is Side.BUY else -1)
            notionals[k] = notionals.get(k, 0.0) + signed
        pv = self._portfolio_vol(notionals, equity, market)
        if pv > cfg.portfolio_vol_target and pv > 0:
            scale = cfg.portfolio_vol_target / pv
            for o in orders:
                o.qty *= scale
            orders = [o for o in orders if o.qty * prices.get(o.asset.key, 0.0) >= 0.005 * equity]
        return orders
