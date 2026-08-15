"""Tests for the Binance long/short positioning crowding signal
(research/crypto_signals.py) and its gated wiring into brain resting levels
(brain/core.py Brain._crypto_anchors). Added 2026-08-15 alongside trend_zscore --
same "compute always, influence only once trusted" pattern."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

tmp = tempfile.mkdtemp()
for var, name in [("BRAIN_GRAPH_PATH", "g"), ("BRAIN_REGIME_PATH", "r"),
                  ("BRAIN_SCENARIOS_PATH", "s"), ("BRAIN_STATE_PATH", "b"),
                  ("BRAIN_MACRO_CACHE_PATH", "m"), ("BRAIN_FIELD_PATH", "f"),
                  ("BRAIN_DB_PATH", "db"), ("BRAIN_FEED_CACHE_PATH", "fc"),
                  ("BRAIN_ADVICE_PATH", "adv"), ("BRAIN_SENTIMENT_CACHE_PATH", "sc")]:
    os.environ[var] = os.path.join(tmp, name + ".json")

import ai_investing.research.crypto_signals as cs_mod  # noqa: E402
from ai_investing.brain.core import Brain  # noqa: E402
from ai_investing.config import Settings  # noqa: E402
from ai_investing.research.crypto_signals import _binance_perp, positioning_crowding_z  # noqa: E402


def test_binance_perp_mapping():
    assert _binance_perp("BTC/USD") == "BTCUSDT"
    assert _binance_perp("LINK/USD") == "LINKUSDT"


def test_positioning_z_insufficient_history_is_none():
    cs = {"positioning": {"BTC/USD": {"2026-08-01": 1.5, "2026-08-02": 1.6}}}
    assert positioning_crowding_z(cs, "BTC/USD") is None


def test_positioning_z_flags_a_crowded_outlier():
    series = {f"2026-07-{d:02d}": 1.5 for d in range(1, 30)}
    series["2026-07-29"] = 3.0   # today's ratio far above the recent range
    cs = {"positioning": {"BTC/USD": series}}
    z = positioning_crowding_z(cs, "BTC/USD")
    assert z is not None and z > 1.0


def test_positioning_z_flat_series_is_zero():
    series = {f"2026-07-{d:02d}": 1.5 for d in range(1, 10)}
    cs = {"positioning": {"BTC/USD": series}}
    assert positioning_crowding_z(cs, "BTC/USD") == 0.0


def _fake_cs():
    """funding covers BTC/USD only; positioning covers BTC/USD AND LINK/USD --
    exercises the union-of-symbols fix (positioning-only coins get a resting
    level too, not just the funding trio)."""
    flat = {f"2026-07-{d:02d}": 0.0001 for d in range(1, 30)}
    funding = dict(flat)
    funding["2026-07-29"] = 0.01   # extreme positive funding spike -> crowded longs
    link_pos = {f"2026-07-{d:02d}": 1.0 for d in range(1, 30)}
    link_pos["2026-07-29"] = 5.0   # extreme long-crowding on LINK
    return {"funding": {"BTC/USD": funding}, "fng": {}, "positioning": {"LINK/USD": link_pos}}


def test_crypto_anchors_dormant_by_default():
    settings = Settings()
    assert settings.altdata.positioning_enabled is False   # default off
    brain = Brain(settings)
    orig = cs_mod.refresh_live
    cs_mod.refresh_live = lambda *a, **kw: _fake_cs()
    try:
        a = brain._crypto_anchors()
    finally:
        cs_mod.refresh_live = orig
    btc = brain.graph.node_for_symbol("BTC/USD")
    link = brain.graph.node_for_symbol("LINK/USD")
    assert btc is not None and link is not None
    assert btc.id in a and a[btc.id] < 0          # funding crowding still live
    assert link.id not in a                       # positioning-only coin: dormant, no anchor


def test_crypto_anchors_positioning_enabled_reaches_positioning_only_coin():
    os.environ["CRYPTO_POSITIONING_ENABLED"] = "true"
    try:
        settings = Settings()
        assert settings.altdata.positioning_enabled is True
        brain = Brain(settings)
        orig = cs_mod.refresh_live
        cs_mod.refresh_live = lambda *a, **kw: _fake_cs()
        try:
            a = brain._crypto_anchors()
        finally:
            cs_mod.refresh_live = orig
        link = brain.graph.node_for_symbol("LINK/USD")
        assert link is not None
        assert link.id in a and a[link.id] < 0     # now reaches a coin funding never covered
    finally:
        del os.environ["CRYPTO_POSITIONING_ENABLED"]


def test_positioning_sweep_is_bounded_by_a_wall_clock_budget():
    """Positioning is the only source here that costs one HTTP call PER WATCHLIST
    SYMBOL, and refresh_live() runs synchronously inside Brain._crypto_anchors()
    in the think path. Unbounded, a rate-limited or hanging Binance would stall
    the engine for symbols x timeout every hour. The sweep must abandon the rest
    of the sweep rather than the cycle."""
    import time as _time

    calls = []
    orig_get, orig_budget = cs_mod._get, cs_mod.POSITIONING_BUDGET

    def _slow_get(url, timeout=25):
        calls.append(url)
        assert timeout <= cs_mod.POSITIONING_TIMEOUT, f"per-call timeout unbounded: {timeout}"
        _time.sleep(0.05)
        return [{"timestamp": 1755216000000, "longShortRatio": "1.5"}]

    cs_mod._get, cs_mod.POSITIONING_BUDGET = _slow_get, 0.12
    try:
        got = list(cs_mod._positioning_sweep(limit=3, budget=0.12))
    finally:
        cs_mod._get, cs_mod.POSITIONING_BUDGET = orig_get, orig_budget

    # ~0.05s per call against a 0.12s budget: a few calls get through, then the
    # sweep gives up. The point is that it stops early, not the exact count.
    assert len(calls) < len(cs_mod._positioning_symbols()), "budget never bit"
    assert len(got) == len(calls)


def test_positioning_sweep_survives_one_bad_symbol():
    """A single delisted/unsupported perp must not cost the whole sweep."""
    orig_get = cs_mod._get

    def _flaky_get(url, timeout=25):
        if "BTCUSDT" in url:
            raise RuntimeError("binance says no")
        return [{"timestamp": 1755216000000, "longShortRatio": "1.5"}]

    cs_mod._get = _flaky_get
    try:
        got = dict(cs_mod._positioning_sweep(limit=3))
    finally:
        cs_mod._get = orig_get

    assert "BTC/USD" not in got
    assert len(got) >= 1


if __name__ == "__main__":
    for _name, _fn in sorted(list(globals().items())):
        if _name.startswith("test_") and callable(_fn):
            _fn()
    print("ok")
