"""Offline tests for the evidence-protocol-v2 pieces of the web trainer:
per-market frictions, cost fractions, and benchmark metrics (no network)."""
import math
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_investing.research.train_web import (
    COST_MODELS, bench_metrics, cost_frac, market_of, series_metrics,
)


def test_market_of_covers_the_universe():
    assert market_of("NVDA") == "us"
    assert market_of("BRK-B") == "us"
    assert market_of("0700.HK") == "hk"
    assert market_of("600519.SS") == "cn"
    assert market_of("300750.SZ") == "cn"
    assert market_of("D05.SI") == "sg"
    assert market_of("9984.T") == "jp"
    assert market_of("005930.KS") == "kr"
    assert market_of("2317.TW") == "tw"
    assert market_of("MC.PA") == "eu"
    assert market_of("ADS.DE") == "eu"
    assert market_of("PRX.AS") == "eu"
    assert market_of("BTC/USD") == "crypto"


def test_frictions_are_ordered_sensibly():
    def base_bps(mkt):
        cm = COST_MODELS[mkt]
        return cm.commission_bps + cm.spread_bps
    # HK stamp duty makes HK the priciest stock market; US the cheapest
    assert base_bps("hk") > base_bps("us") * 3
    assert base_bps("crypto") >= 10.0
    for mkt, cm in COST_MODELS.items():
        assert 3.0 <= cm.commission_bps + cm.spread_bps <= 30.0, mkt


def _fake_ds():
    idx = pd.date_range("2024-01-01", periods=60, freq="B")
    px = pd.DataFrame({"NVDA": 100.0, "0700.HK": 300.0, "BTC/USD": 50000.0},
                      index=idx)
    adv = pd.DataFrame({"NVDA": 1e7, "0700.HK": 5e6, "BTC/USD": 1e9}, index=idx)
    vol = pd.DataFrame({"NVDA": 0.02, "0700.HK": 0.02, "BTC/USD": 0.04}, index=idx)
    return {"adv": adv, "vol20": vol, "close": px,
            "bench": {"SPY": pd.Series(range(100, 160), index=idx, dtype=float)}}


def test_cost_frac_per_market():
    ds = _fake_ds()
    f_us = cost_frac(ds, "NVDA", 100, 100.0, 30)
    f_hk = cost_frac(ds, "0700.HK", 100, 300.0, 30)
    f_cr = cost_frac(ds, "BTC/USD", 1.0, 50000.0, 30)
    assert f_hk > 3 * f_us > 0
    assert abs(f_cr - 0.0015) < 1e-9          # crypto: fee+spread, no impact term
    # impact grows with participation: a 5%-of-ADV order costs more per share
    f_big = cost_frac(ds, "NVDA", 5e5, 100.0, 30)
    assert f_big > f_us


def test_series_and_bench_metrics():
    ds = _fake_ds()
    m = series_metrics(ds["bench"]["SPY"])
    assert m["cagr"] > 0 and m["maxdd"] == 0.0 and not math.isnan(m["sharpe"])
    b = bench_metrics(ds, 0, 60)
    assert b["SPY"]["cagr"] == m["cagr"]


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\nAll {len(tests)} train_web cost tests passed.")
