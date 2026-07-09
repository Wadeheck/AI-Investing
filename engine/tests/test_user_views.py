"""Tests for the user-views overlay — your input as the decisive factor."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_investing.data.providers import SyntheticDataProvider
from ai_investing.models import Asset, AssetClass
from ai_investing.signals import default_signals
from ai_investing.strategy.decision import DecisionEngine
from ai_investing.strategy.user_views import UserViews


def _tmp() -> str:
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    return path


def test_no_view_is_pure_model():
    assert UserViews().apply("NVDA", 0.4) == 0.4          # normal stance, no view


def test_strong_view_is_decisive():
    uv = UserViews(decisiveness=1.0, views={"NVDA": 1.0})
    assert abs(uv.apply("NVDA", -0.5) - 1.0) < 1e-9        # your +1 overrides a bearish model


def test_partial_view_blends():
    uv = UserViews(decisiveness=0.5, views={"NVDA": 1.0})
    assert abs(uv.apply("NVDA", 0.0) - 0.5) < 1e-9         # w=0.5 -> half model, half you


def test_stance_scales_exposure():
    assert UserViews(stance="cash").apply("X", 0.9) == 0.0
    assert abs(UserViews(stance="cautious").apply("X", 0.5) - 0.3) < 1e-9   # 0.5 * 0.6


def test_risk_appetite_scales_exposure():
    assert abs(UserViews(risk_appetite=0.0).apply("X", 0.5) - 0.2) < 1e-9   # ×0.4
    assert abs(UserViews(risk_appetite=1.0).apply("X", 0.5) - 0.8) < 1e-9   # ×1.6
    assert abs(UserViews(risk_appetite=0.5).apply("X", 0.5) - 0.5) < 1e-9   # ×1.0 (default)


def test_blocklist_and_focus():
    uv = UserViews(blocklist=["TSLA"], focus=["NVDA", "AAPL"])
    assert not uv.is_allowed("TSLA")
    assert uv.is_allowed("nvda")           # case-insensitive
    assert not uv.is_allowed("MSFT")       # not in focus list


def test_persistence_roundtrip():
    uv = UserViews(stance="cautious", decisiveness=0.8, views={"NVDA": 0.5}, blocklist=["TSLA"])
    p = _tmp()
    uv.save(p)
    loaded = UserViews.load(p)
    assert loaded.stance == "cautious" and loaded.decisiveness == 0.8
    assert loaded.views["NVDA"] == 0.5 and "TSLA" in loaded.blocklist


def test_decision_engine_honors_view():
    asset = Asset("NVDA", AssetClass.STOCK)
    bars = SyntheticDataProvider().get_bars(asset, 250)
    eng = DecisionEngine(default_signals(), user_views=UserViews(decisiveness=1.0, views={"NVDA": 1.0}))
    d = eng.decide(asset, bars, {})
    assert d.direction.value == "long" and d.score > 0.5 and d.user_view == 1.0


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\nAll {len(tests)} user-views tests passed.")
