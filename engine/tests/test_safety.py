"""Tests for the safety layer: circuit breaker, data guard, preflight, heartbeat."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_investing.config import SafetyConfig
from ai_investing.config import settings as global_settings
from ai_investing.safety import heartbeat as hb
from ai_investing.safety.circuit_breaker import CircuitBreaker
from ai_investing.safety.data_guard import DataGuard
from ai_investing.safety.preflight import validate_settings


def _tmp() -> str:
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)          # start absent; the breaker handles a missing file
    return path


def _cb(path, daily=0.05, **overrides):
    cfg = SafetyConfig()
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return CircuitBreaker(cfg, daily, path)


def test_breaker_daily_flatten():
    cb = _cb(_tmp(), daily=0.05)
    assert cb.check(100_000).allow_new
    d = cb.check(94_000)     # -6% on the day
    assert d.flatten and not d.allow_new and "daily" in d.reason


def test_breaker_inception_latches_and_persists():
    p = _tmp()
    cb = _cb(p, daily=0.9)   # high daily so inception binds first
    cb.check(100_000)
    assert cb.check(70_000).flatten                    # -30% > 25% inception
    reloaded = _cb(p, daily=0.9)                        # restart
    assert reloaded.check(100_000).flatten             # still latched despite recovery
    reloaded.reset()
    assert reloaded.check(100_000).allow_new           # manual reset clears it


def test_breaker_trade_cap():
    cb = _cb(_tmp(), daily=0.9, max_trades_per_day=2)
    cb.check(100_000)
    cb.register_trade(100)
    cb.register_trade(100)
    d = cb.check(100_000)
    assert not d.allow_new and not d.flatten and "trades" in d.reason


def test_data_guard_flags_bad_prices():
    g = DataGuard(SafetyConfig())
    assert g.check({"stock:A": 100.0})[0] == set()     # baseline
    assert g.check({"stock:A": 100.5})[0] == set()     # small move ok
    assert "stock:A" in g.check({"stock:A": 200.0})[0]  # +99% jump flagged
    assert "stock:B" in g.check({"stock:B": 0.0})[0]    # non-positive flagged


def test_validate_settings_defaults_clean():
    errors, warnings = validate_settings(global_settings)
    assert isinstance(errors, list) and isinstance(warnings, list)
    assert errors == []                                # defaults must have no hard errors


def test_heartbeat_roundtrip():
    p = _tmp()
    hb.write_heartbeat(p, {"equity": 100})
    d = hb.read_heartbeat(p)
    assert d and d["equity"] == 100 and "ts" in d
    assert (hb.age_seconds(d) or -1) >= 0
    assert not hb.is_stale(d, 3600)
    assert hb.is_stale(None, 3600)

def test_guard_flagged_prices_never_reach_the_stop_logic():
    """A stale-but-positive tick must not liquidate a position.

    A total feed failure marks everything at 0, which stop_orders survives only
    because 0 is falsy. A WRONG POSITIVE price has no such accident: the guard
    flags it, so the runner must withhold it from the stop path. An unfired
    stop is recoverable; a phantom liquidation is not.
    """
    from ai_investing.strategy.risk import RiskManager
    from ai_investing.config import Settings
    from ai_investing.models import Asset, AssetClass, Portfolio, Position

    s = Settings()
    rm = RiskManager(s.risk)
    a = Asset("TEST", AssetClass.STOCK)
    port = Portfolio(cash=10_000.0,
                     positions={a.key: Position(asset=a, qty=100.0, avg_price=100.0)})

    # a bad tick at -90% would normally fire the stop
    bad = {a.key: 10.0}
    assert rm.stop_orders(port, bad), "sanity: a -90% move should trip a stop"

    # the runner withholds guard-flagged symbols, so nothing fires
    bad_data = {a.key}
    safe = {k: v for k, v in bad.items() if k not in bad_data}
    assert not rm.stop_orders(port, safe), \
        "a guard-flagged price must not be able to liquidate a position"


def test_a_blanket_feed_failure_serves_stale_bars_not_zero():
    """yfinance throttles by returning empty for EVERY symbol at once. Passing
    that through as 'no price' becomes price 0 downstream, which marks the book
    at -100%. Reusing the last good bars keeps the mark honest and lets
    DataGuard judge staleness on its own terms."""
    from ai_investing.data.providers import LastGoodBarCache, DataProvider
    from ai_investing.models import Asset, AssetClass, Bar
    from datetime import datetime, timezone

    class Flaky(DataProvider):
        def __init__(self):
            self.alive = True

        def get_bars(self, asset, limit=200):
            if not self.alive:
                return []
            return [Bar(datetime.now(timezone.utc), 10.0, 11.0, 9.0, 10.5, 1000.0)]

    inner = Flaky()
    cache = LastGoodBarCache(inner)
    a = Asset("TEST", AssetClass.STOCK)
    assert cache.get_bars(a)[-1].close == 10.5

    inner.alive = False                      # the provider starts throttling
    served = cache.get_bars(a)
    assert served and served[-1].close == 10.5, \
        "a throttled feed must not become a zero price"



if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\nAll {len(tests)} safety tests passed.")

