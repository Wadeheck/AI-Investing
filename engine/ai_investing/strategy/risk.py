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

import math
from typing import Optional

from ai_investing.config import RiskConfig
from ai_investing.indicators import correlation
from ai_investing.models import AssetClass, Decision, Order, Portfolio, Side


def _avg(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


class RiskManager:
    def __init__(self, cfg: RiskConfig, regime_gate=None, lots=None):
        self.cfg = cfg
        self.regime = regime_gate
        # Board lots (brokers/lots.LotBook), or None for the whole-share
        # behaviour this sizer has always had. Optional so the backtest, the
        # shadow book and every test keep working untouched.
        self.lots = lots
        self.day_start_equity: Optional[float] = None
        self.peak_equity: Optional[float] = None
        self.halted = False
        # symbol -> 0..1 decayed integrity/distress severity, refreshed each
        # cycle by the runner from brain/integrity.py (see set_name_risk)
        self._name_risk: dict[str, float] = {}

    def set_name_risk(self, flags: dict) -> None:
        """Per-name danger charge: tightens stops on longs and blocks adds."""
        self._name_risk = {sym: float(f.get("severity", 0.0))
                           for sym, f in (flags or {}).items()}

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
            # NAME RISK (2026-08-02): a holding under an active integrity /
            # distress flag gets a TIGHTER leash — up to half the normal stop
            # at full severity. The lockbox showed the stock book's drawdown is
            # idiosyncratic; this is the position-level answer index gates
            # could not give. Longs only: a flag is bearish, so a short's stop
            # (which triggers on the price RISING) must not be tightened by it.
            nr = self._name_risk.get(pos.asset.symbol, 0.0) if self._name_risk else 0.0
            if nr > 0.1 and pos.qty > 0:
                stop_frac *= max(0.5, 1.0 - 0.5 * min(1.0, nr))
            # hard rule: no position may lose more than max_loss_per_position
            stop_frac = min(stop_frac, self.cfg.max_loss_per_position)

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

        # structural cluster exposure (graph themes + supply chains): six AI-BOM
        # tickers are one bet — cap the bet, not just each ticker
        try:
            from ai_investing.strategy.clusters import cluster_gross, clusters_for
            notionals = {k: p.qty * prices.get(k, 0.0)
                         for k, p in portfolio.positions.items() if abs(p.qty) > 1e-9}
            cl_gross = cluster_gross(notionals)
        except Exception:
            clusters_for, cl_gross = (lambda s: frozenset()), {}
        cluster_cap = cfg.max_cluster_exposure * equity * derisk

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

            # name risk: never ADD to a long under an active distress flag —
            # exits and trims stay free (protection must never block getting out)
            nr = self._name_risk.get(d.asset.symbol, 0.0)
            if nr > 0.3 and delta > 0 and target_w > 0:
                continue

            # scheduled-event throttle: fresh risk shrinks into earnings/FOMC
            # (exits and stops are never touched by this)
            if opening_new and cfg.event_derisk:
                try:
                    from ai_investing.data.calendar_events import entry_risk_multiplier
                    ev_mult, ev_why = entry_risk_multiplier(
                        d.asset.symbol, window_days=cfg.earnings_window_days)
                    if ev_mult < 1.0:
                        delta *= ev_mult
                        d.rationale = (f"[{ev_why}: sized x{ev_mult:.1f}] " + d.rationale)[:200]
                        if abs(delta) < min_trade:
                            continue
                except Exception:
                    pass

            increasing = abs(cur_notional + delta) > abs(cur_notional)
            if increasing and gross + abs(delta) > gross_cap:
                delta = max(0.0, gross_cap - gross) * (1 if delta > 0 else -1)
                if abs(delta) < min_trade:
                    continue

            # cluster cap: adding to a bet the book is already full of gets
            # trimmed to whatever headroom the most-constrained cluster has
            if increasing:
                syms_clusters = clusters_for(d.asset.symbol)
                if syms_clusters:
                    headroom = min((cluster_cap - cl_gross.get(c, 0.0) for c in syms_clusters),
                                   default=float("inf"))
                    if headroom < abs(delta):
                        delta = max(0.0, headroom) * (1 if delta > 0 else -1)
                        if abs(delta) < min_trade:
                            continue
                        d.rationale = ("[cluster cap] " + d.rationale)[:200]

            side = Side.BUY if delta > 0 else Side.SELL
            orders.append(Order(d.asset, side, abs(delta) / px, reason=d.rationale[:140]))
            gross += abs(delta)
            for c in clusters_for(d.asset.symbol):
                cl_gross[c] = cl_gross.get(c, 0.0) + abs(delta)
            if opening_new:
                open_keys.add(key)

        orders = self._apply_portfolio_vol_target(orders, portfolio, prices, equity, market)
        return self._quantize_whole_shares(orders, prices, equity)

    # --- whole-share quantisation ------------------------------------------
    def _quantize_whole_shares(self, orders, prices, equity):
        """Round STOCK orders to whole shares HERE, not at the broker.

        WHY THIS EXISTS (2026-08-12). Every stock broker adapter did
        `qty = int(order.qty)` and rejected `qty < 1 share`. That truncation is
        correct — Longbridge cannot take 0.71 shares — but it was the LAST step,
        so the sizer happily emitted sub-share orders forever and the reject
        came back every cycle. The USO re-entry failed this way repeatedly.

        The root cause is that two gates contradicted each other: the minimum
        trade is 0.5% of equity ($50 on a $10k book), but ONE share of any stock
        priced above $50 costs more than that. So an order sized near the
        minimum passed the notional gate and then truncated to zero shares.
        Nothing upstream ever learned, because the rejection happened after
        sizing was done.

        Rounding here makes the constraint visible to the code that can act on
        it: an order that cannot be expressed in whole shares is dropped once,
        with a reason, instead of being retried into a broker reject forever.

        Sells are floored but never bumped or blocked — a stock position is
        already integral, so flooring an exit is a no-op, and protection must
        never be gated on affordability.

        BOARD LOTS, not just whole shares (2026-08-17). This carried "KNOWN GAP:
        HK board lots are not modelled" from the day it was written, which was
        harmless while the live book could only reach US listings. It stops being
        harmless the moment it can reach Hong Kong, Singapore and the mainland:
        Tencent trades in hundreds and China Mobile in five-hundreds, so an order
        for 37 shares is not a small order, it is a rejected one — the very
        failure this method exists to prevent, one level up.

        The unit comes from `self.lots` when it is present and is 1 otherwise, so
        the backtest, the shadow book and every existing test keep the exact
        whole-share behaviour they had.
        """
        out = []
        for o in orders:
            if o.asset.asset_class is not AssetClass.STOCK:
                out.append(o)                      # crypto is genuinely fractional
                continue
            px = prices.get(o.asset.key, 0.0)
            lot = self.lots.lot_size(o.asset.symbol) if self.lots else 1
            if not lot or lot < 1:
                # Unknown unit. Dropping a BUY is conservative; dropping a SELL
                # would strand a position, so a US-style single share is used to
                # let protection out. (`_live_universe` already excludes these
                # from entry, so in practice only an exit reaches here.)
                if o.side is Side.SELL:
                    lot = 1
                else:
                    continue
            q = math.floor(o.qty / lot + 1e-9) * lot
            if q >= lot:
                o.qty = float(q)
                out.append(o)
                continue
            if o.side is Side.SELL:
                continue                           # nothing left to sell after flooring
            # A buy that rounds to nothing: take ONE LOT only if a single lot is
            # a position this book would have been allowed to hold. On a $10k
            # book that admits 0020.HK (a $199 lot) and correctly refuses
            # 0700.HK (a $5,715 one).
            if px > 0 and px * lot <= self.cfg.max_position_weight * equity:
                o.qty = float(lot)
                tag = "1-share min" if lot == 1 else f"{lot}-share lot min"
                o.reason = (f"[{tag}] " + (o.reason or ""))[:140]
                out.append(o)
            # else: one lot breaches the position cap — drop it. Silently
            # retrying an unaffordable name is what the old path did.
        return out

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
