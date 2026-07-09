"""Zero-dependency smoke test. Run directly: `python tests/test_smoke.py`
(from the engine/ directory) or with pytest. Exercises the full pipeline offline.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_investing.brokers.paper import PaperBroker
from ai_investing.data.providers import SyntheticDataProvider
from ai_investing.models import Asset, AssetClass, Order, Side
from ai_investing.signals import default_signals
from ai_investing.strategy import DecisionEngine, RiskManager
from ai_investing.config import RiskConfig


def test_synthetic_bars():
    p = SyntheticDataProvider()
    bars = p.get_bars(Asset("AAPL", AssetClass.STOCK), limit=250)
    assert len(bars) == 220
    assert all(b.close > 0 for b in bars)


def test_signals_and_decision():
    p = SyntheticDataProvider()
    asset = Asset("NVDA", AssetClass.STOCK)
    bars = p.get_bars(asset, limit=250)
    engine = DecisionEngine(default_signals())
    d = engine.decide(asset, bars, context={})
    assert -1.0 <= d.score <= 1.0
    assert 0.0 <= d.confidence <= 1.0
    assert len(d.signals) == 4


def test_paper_broker_roundtrip():
    b = PaperBroker(10_000)
    asset = Asset("TSLA", AssetClass.STOCK)
    o = b.submit(Order(asset, Side.BUY, 10), price=100.0)
    assert o.status.value == "filled"
    assert b.get_cash() == 9_000
    assert b.get_positions()[asset.key].qty == 10
    b.submit(Order(asset, Side.SELL, 10), price=110.0)
    assert b.get_cash() == 10_100  # +$100 profit
    assert not b.get_positions()


def test_risk_stop_loss():
    from ai_investing.models import Portfolio, Position
    risk = RiskManager(RiskConfig())
    asset = Asset("BTC/USD", AssetClass.CRYPTO)
    pf = Portfolio(0.0, {asset.key: Position(asset, 1.0, 100.0)})
    stops = risk.stop_orders(pf, {asset.key: 80.0})  # -20% > 8% stop
    assert len(stops) == 1 and stops[0].side == Side.SELL


def test_hype_fade_is_bearish():
    """A violent pump with a political-hype flag must produce a negative score."""
    from ai_investing.signals.political_hype import PoliticalHypeSignal
    p = SyntheticDataProvider()
    asset = Asset("MEME", AssetClass.CRYPTO)
    bars = p.get_bars(asset, limit=250)
    ctx = {"hype_flags": {"MEME": {"promotional": True, "political": True, "intensity": 0.9}}}
    r = PoliticalHypeSignal().evaluate(asset, bars, ctx)
    assert r.score < 0, "hype should be faded (negative score)"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\nAll {len(tests)} smoke tests passed.")
