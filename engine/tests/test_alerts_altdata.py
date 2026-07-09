"""Offline tests for alerts + alt-data (no network calls)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_investing.alerts import get_notifier
from ai_investing.alerts.telegram import NullNotifier, TelegramNotifier
from ai_investing.config import settings
from ai_investing.data import altdata
from ai_investing.data.altdata import AltSignal, aggregate


def test_null_notifier():
    n = NullNotifier()
    assert n.enabled is False and n.send("x") is False


def test_telegram_disabled_without_creds():
    n = TelegramNotifier("", "")
    assert n.enabled is False and n.send("x") is False


def test_get_notifier_never_raises():
    n = get_notifier(settings)
    assert n.send("x") in (True, False)  # must never raise
    if not (settings.alerts.telegram_bot_token and settings.alerts.telegram_chat_id):
        assert isinstance(n, NullNotifier)


def test_options_flow_unconfigured():
    if not settings.altdata.polygon_api_key:          # returns before any network call
        s = altdata.options_flow(settings, "AAPL")
        assert s.available is False and "POLYGON" in s.detail


def test_aggregate_merges_available_only():
    sigs = [
        AltSignal("a", available=True, intensity=0.3, bullish=0.5),
        AltSignal("b", available=True, intensity=0.8, bullish=-0.1),
        AltSignal("c", available=False, intensity=0.9, bullish=1.0),  # ignored
    ]
    agg = aggregate(sigs)
    assert agg["available"] is True
    assert abs(agg["intensity"] - 0.8) < 1e-9      # max of available
    assert abs(agg["bullish"] - 0.2) < 1e-9        # mean of available
    assert aggregate([])["available"] is False


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\nAll {len(tests)} alerts/alt-data tests passed.")
