"""Offline tests for the scalp module: indicators, strategy gating, and the
paper engine's fill/fee mechanics (no network)."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_investing.scalp import engine as eng
from ai_investing.scalp import indicators as ind
from ai_investing.scalp import strategies as st


def _bars(n=400, start=100.0, drift=0.0, seed=7):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-01-01", periods=n, freq="5min", tz="UTC")
    c = start * np.cumprod(1 + drift + rng.normal(0, 0.002, n))
    o = np.roll(c, 1); o[0] = start
    h = np.maximum(o, c) * (1 + rng.uniform(0, 0.001, n))
    l = np.minimum(o, c) * (1 - rng.uniform(0, 0.001, n))
    v = rng.uniform(50, 150, n)
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "vol": v,
                         "taker_buy_vol": v * rng.uniform(0.3, 0.7, n),
                         "n_trades": rng.integers(100, 1000, n)}, index=idx)


def test_enrich_and_delta():
    df = ind.enrich(_bars())
    assert {"atr", "ema9", "vwap24", "delta", "cvd", "rvol"} <= set(df.columns)
    # delta = 2*taker_buy - vol, bounded by +-vol
    assert (df["delta"].abs() <= df["vol"] + 1e-9).all()


def test_green_run_resets_on_red():
    idx = pd.date_range("2026-01-01", periods=6, freq="1h", tz="UTC")
    df = pd.DataFrame({"open": [1, 1, 1.2, 1.1, 1.3, 1.5],
                       "close": [1.1, 0.9, 1.3, 1.3, 1.5, 1.7],
                       "vol": [1] * 6}, index=idx)
    df["dvol"] = [1, 2, 3, 4, 5, 6]
    run, esc = ind.green_run(df)
    assert run == 4 and esc          # red bar at position 1 caps the run
    df2 = df.copy(); df2.loc[df2.index[-1], "close"] = 1.0
    run2, _ = ind.green_run(df2)
    assert run2 == 0                 # latest bar red -> no run at all


def test_min_stop_floor():
    stop = st._floor_stop(100.0, 99.9, +1)      # 10 bps structural stop
    assert (100.0 - stop) / 100.0 >= st.MIN_STOP_FRAC - 1e-9


def test_engine_limit_fill_and_stop_fees():
    bk = eng.Book(equity=10_000.0)
    idx = pd.date_range("2026-01-01", periods=4, freq="5min", tz="UTC")
    intent = {"side": 1, "entry": 100.0, "stop": 99.0, "target": 102.0,
              "tag": "T", "ttl": 6}
    bars = pd.DataFrame({"open": [101, 100.5, 99.4, 98.9],
                         "high": [101.5, 100.8, 99.6, 99.0],
                         "low": [100.8, 99.9, 98.9, 98.5],
                         "close": [101, 100.0, 99.0, 98.6],
                         "ema9": [101, 100.4, 99.8, 99.3]}, index=idx)
    eng.on_bar(bk, "X", idx[0], bars.iloc[0], [intent])   # accepted, no fill (low 100.8)
    assert len(bk.pending) == 1 and not bk.positions
    eng.on_bar(bk, "X", idx[1], bars.iloc[1], [])          # low 99.9 <= 100 -> maker fill
    assert len(bk.positions) == 1 and not bk.pending
    eng.on_bar(bk, "X", idx[2], bars.iloc[2], [])          # low 98.9 <= 99 -> stopped
    assert not bk.positions and len(bk.trades) == 1
    t = bk.trades[0]
    assert t["how"] == "stop" and t["pnl"] < 0
    # equity lost roughly qty*(entry-stop) + fees + slip; must be below start
    assert bk.equity < 10_000.0
    # no re-entry at the just-stopped level
    eng.on_bar(bk, "X", idx[3], bars.iloc[3], [dict(intent)])
    assert not bk.pending


def test_daily_halt_blocks_new_entries():
    bk = eng.Book(equity=10_000.0)
    idx = pd.date_range("2026-01-01", periods=2, freq="5min", tz="UTC")
    bar = pd.Series({"open": 100, "high": 100, "low": 100, "close": 100, "ema9": 100})
    eng.on_bar(bk, "X", idx[0], bar, [])
    bk.equity = bk.day_start_eq * 0.975           # -2.5% on the day: halted
    eng.on_bar(bk, "X", idx[1], bar,
               [{"side": 1, "entry": 99.5, "stop": 99.0, "target": 101.0,
                 "tag": "T", "ttl": 6}])
    assert not bk.pending and not bk.positions     # halted: intent refused outright


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\nAll {len(tests)} scalp tests passed.")
