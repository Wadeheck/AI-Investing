"""Event-driven backtester.

Runs the SAME components as live (signals -> DecisionEngine(formula) -> RiskManager ->
PaperBroker) over historical bars, now with a transaction-cost model and per-step market
stats feeding volatility-targeted sizing / ATR stops. Decisions at bar t use data through
t; fills happen at t+1's open, penalized by costs, to avoid look-ahead and free fills.
Also builds the dense (φ, forward-return) samples the ridge fit uses to curate θ.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from ai_investing.brokers.paper import PaperBroker
from ai_investing.config import RiskConfig
from ai_investing.execution.costs import CostModel
from ai_investing.learning.attribution import OutcomeTracker
from ai_investing.learning.features import FeatureExtractor
from ai_investing.learning.formula import FormulaModel
from ai_investing.learning.objective import metrics as compute_metrics
from ai_investing.models import Asset, Bar, Order
from ai_investing.signals import default_signals
from ai_investing.signals.base import Signal
from ai_investing.strategy.decision import DecisionEngine
from ai_investing.strategy.market import build_market_stats
from ai_investing.strategy.risk import RiskManager
from ai_investing.strategy.user_views import UserViews


@dataclass
class BacktestResult:
    equity_curve: list[float]
    returns: list[float]
    trade_returns: list[float]
    metrics: dict
    orders: int
    turnover: float


class Backtester:
    def __init__(self, signals: list[Signal] | None = None, risk_cfg: RiskConfig | None = None,
                 starting_cash: float = 100_000.0, warmup: int = 60, horizon: int = 5,
                 cost_model: CostModel | None = None):
        self.signals = signals or default_signals()
        self.risk_cfg = risk_cfg or RiskConfig()
        self.starting_cash = starting_cash
        self.warmup = warmup
        self.horizon = horizon
        self.costs = cost_model or CostModel()
        self.fx = FeatureExtractor()

    def _aligned(self, bars_by_key: dict[str, list[Bar]]) -> tuple[dict[str, list[Bar]], int]:
        if not bars_by_key:
            return {}, 0
        length = min(len(v) for v in bars_by_key.values())
        return {k: v[-length:] for k, v in bars_by_key.items()}, length

    def build_samples(self, assets: list[Asset], bars_by_key: dict[str, list[Bar]]):
        aligned, length = self._aligned(bars_by_key)
        asset_by_key = {a.key: a for a in assets}
        X: list[list[float]] = []
        y: list[float] = []
        for key, bars in aligned.items():
            asset = asset_by_key.get(key)
            if asset is None:
                continue
            for t in range(self.warmup, length - self.horizon):
                results = [s.evaluate(asset, bars[:t + 1], {}) for s in self.signals]
                feats = self.fx.build(results, bars[:t + 1])
                fwd = (bars[t + self.horizon].close - bars[t].close) / bars[t].close if bars[t].close else 0.0
                X.append(self.fx.vector(feats))
                y.append(fwd)
        return X, y

    def run(self, model: FormulaModel, assets: list[Asset], bars_by_key: dict[str, list[Bar]],
            sim_start: int | None = None, sim_end: int | None = None, regime_gate=None,
            user_views: UserViews | None = None) -> BacktestResult:
        aligned, length = self._aligned(bars_by_key)
        asset_by_key = {a.key: a for a in assets if a.key in aligned}
        keys = list(asset_by_key)
        if not keys or length < self.warmup + 2:
            return BacktestResult([self.starting_cash], [], [], compute_metrics([self.starting_cash], [], []), 0, 0.0)

        start = self.warmup if sim_start is None else max(self.warmup, sim_start)
        end = (length - 1) if sim_end is None else min(length - 1, sim_end)

        cfg = dataclasses.replace(self.risk_cfg, per_trade_stop_loss=model.stop_loss, take_profit=model.take_profit)
        broker = PaperBroker(self.starting_cash, allow_short=cfg.allow_short)
        engine = DecisionEngine(self.signals, model=model, user_views=user_views)
        risk = RiskManager(cfg, regime_gate=regime_gate)
        tracker = OutcomeTracker()

        equity_curve: list[float] = []
        returns: list[float] = []
        trade_returns: list[float] = []
        traded_notional = 0.0
        n_orders = 0
        prev_equity: float | None = None

        def fill(order: Order, stats) -> None:
            nonlocal traded_notional, n_orders
            key = order.asset.key
            ms = stats.get(key)
            eff = self.costs.effective_price(order.side, aligned[key][t + 1].open, order.qty,
                                             ms.adv if ms else None, ms.vol if ms else None)
            f = broker.submit(order, eff)
            traded_notional += abs((f.filled_qty or 0.0) * (f.filled_price or 0.0))
            n_orders += 1

        for t in range(start, end):
            close_prices = {k: aligned[k][t].close for k in keys}
            fill_mid = {k: aligned[k][t + 1].open for k in keys}
            stats = build_market_stats({k: aligned[k][:t + 1] for k in keys}, lookback=20)

            portfolio = broker.portfolio()
            equity = portfolio.equity(close_prices)
            equity_curve.append(equity)
            if prev_equity and prev_equity > 0:
                returns.append(equity / prev_equity - 1)
            prev_equity = equity

            for o in risk.stop_orders(portfolio, close_prices, market=stats):
                fill(o, stats)

            decisions = [engine.decide(asset_by_key[k], aligned[k][:t + 1], {}) for k in keys]
            features_by_key = {d.asset.key: d.features for d in decisions}

            portfolio = broker.portfolio()
            for o in risk.size_orders(decisions, portfolio, fill_mid, equity, market=stats, model=model):
                fill(o, stats)

            for sample in tracker.sync(broker.get_positions(), features_by_key, fill_mid):
                trade_returns.append(sample.realized_return)

        final_prices = {k: aligned[k][end].close for k in keys}
        equity_curve.append(broker.portfolio().equity(final_prices))
        turnover = traded_notional / (max(1, len(equity_curve)) * self.starting_cash)
        return BacktestResult(
            equity_curve=equity_curve,
            returns=returns,
            trade_returns=trade_returns,
            metrics=compute_metrics(equity_curve, returns, trade_returns),
            orders=n_orders,
            turnover=turnover,
        )
