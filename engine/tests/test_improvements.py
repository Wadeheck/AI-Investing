"""Tests for the Tier 1-3 improvements: costs, deflated Sharpe, ATR/correlation,
regime gate, vol-targeted sizing, cost-aware backtest, event study.
Run: `python3 tests/test_improvements.py` from engine/ (or pytest).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_investing.backtest.engine import Backtester
from ai_investing.config import RiskConfig
from ai_investing.data.providers import SyntheticDataProvider
from ai_investing.execution.costs import CostModel
from ai_investing.indicators import atr, correlation
from ai_investing.learning.formula import FormulaModel
from ai_investing.learning.objective import deflated_sharpe_ratio, probabilistic_sharpe_ratio
from ai_investing.models import Asset, AssetClass, Decision, Portfolio, SignalDirection
from ai_investing.research.event_study import study
from ai_investing.strategy.market import MarketStats
from ai_investing.strategy.regime import RegimeGate
from ai_investing.strategy.risk import RiskManager
from ai_investing.models import Side


def test_cost_model_penalizes():
    c = CostModel(commission_bps=1, spread_bps=2, slippage_coef=0.1)
    buy = c.effective_price(Side.BUY, 100.0, 10, adv=1000, vol=0.02)
    sell = c.effective_price(Side.SELL, 100.0, 10, adv=1000, vol=0.02)
    assert buy > 100.0 > sell
    big = c.effective_price(Side.BUY, 100.0, 500, adv=1000, vol=0.02)  # more of ADV
    assert big > buy


def test_deflated_sharpe_penalizes_trials():
    rets = [0.01, -0.005, 0.012, 0.008, -0.002, 0.015, 0.006, -0.001, 0.009, 0.011] * 5
    psr = probabilistic_sharpe_ratio(rets, 0.0)
    assert 0.0 <= psr <= 1.0
    d1 = deflated_sharpe_ratio(rets, 1)
    d100 = deflated_sharpe_ratio(rets, 100)
    assert d100 <= d1  # more trials searched -> harder to be significant


def test_atr_and_correlation():
    bars = SyntheticDataProvider().get_bars(Asset("X", AssetClass.STOCK), 120)
    a = atr(bars, 14)
    assert a and a > 0
    r = [b.close for b in bars]
    assert abs(correlation(r, r) - 1.0) < 1e-6


def test_regime_gate():
    g = RegimeGate(high_vol=0.04, ood_z=3.0, min_mult=0.4, feature_mean=[0, 0], feature_std=[1, 1])
    assert g.vol_multiplier(0.02) == 1.0
    assert g.vol_multiplier(0.12) < 1.0
    assert g.ood_multiplier([0.5, 0.5]) == 1.0
    assert g.ood_multiplier([10.0, 0.0]) < 1.0        # far out of distribution


def test_vol_targeting_sizes_smaller_for_higher_vol():
    rm = RiskManager(RiskConfig())
    lo, hi = Asset("LO", AssetClass.STOCK), Asset("HI", AssetClass.STOCK)
    decisions = [
        Decision(lo, 0.9, SignalDirection.LONG, 0.9, 0.9, rationale="x"),
        Decision(hi, 0.9, SignalDirection.LONG, 0.9, 0.9, rationale="x"),
    ]
    prices = {lo.key: 100.0, hi.key: 100.0}
    market = {
        lo.key: MarketStats(lo.key, 100, 0.01, 1.0, 1e6, [0.001] * 20),
        hi.key: MarketStats(hi.key, 100, 0.08, 1.0, 1e6, [0.02] * 20),
    }
    orders = rm.size_orders(decisions, Portfolio(100_000.0, {}), prices, 100_000.0, market=market)
    qty = {o.asset.key: o.qty for o in orders}
    assert qty.get(lo.key, 0) > qty.get(hi.key, 0)  # lower-vol name gets more size


def test_costs_reduce_backtest_equity():
    p = SyntheticDataProvider()
    assets = [Asset("AAA", AssetClass.STOCK), Asset("BBB", AssetClass.STOCK)]
    bars = {a.key: p.get_bars(a, 250) for a in assets}
    m = FormulaModel()
    free = Backtester(warmup=60, horizon=5, cost_model=CostModel(enabled=False)).run(m, assets, bars)
    costly = Backtester(warmup=60, horizon=5,
                        cost_model=CostModel(enabled=True, commission_bps=5, spread_bps=5, slippage_coef=0.3)
                        ).run(m, assets, bars)
    if costly.orders > 0:
        assert costly.metrics["final_equity"] <= free.metrics["final_equity"] + 1e-6


def test_event_study_runs():
    p = SyntheticDataProvider()
    bars = {f"stock:{s}": p.get_bars(Asset(s, AssetClass.STOCK), 300) for s in ["A", "B", "C", "D"]}
    n, stats = study(bars)
    assert n >= 0 and len(stats) == 4


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\nAll {len(tests)} improvement tests passed.")
