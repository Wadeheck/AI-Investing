"""Benchmark-relative grading: one meaning per label, measured against the market.

The record this replaces, from data/brain.db on 2026-08-04:

    long             n=93  hit 0.505   avg realised +3.3%
    short_or_avoid   n=77  hit 0.182   avg realised +3.6%

`short_or_avoid` was graded as a prediction of a FALL, in a market that rose. So
correct avoids were marked wrong, ~82% of the time, and the blended 0.404 "hit
rate" measured nothing at all. These tests pin the definitions so it cannot
silently drift back.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_investing.brain.scorecard import (BENCH_SYMBOLS, DEADBAND, benchmark_for,
                                          verdict)


def test_avoid_is_judged_on_lagging_not_on_falling():
    """The bug, as a test. A name the brain said to avoid rose 2% while the market
    rose 6%: staying out was correct, and the old rule called it a miss."""
    assert verdict("avoid", ret=0.02, excess=0.02 - 0.06) == 1, \
        "rose less than the market — avoiding it was right"
    assert verdict("avoid", ret=0.02, excess=0.02 - 0.005) == 0, \
        "beat the market — avoiding it cost you"
    # and the whole 77-call population: up 3.6% in a tape that was up more
    assert verdict("avoid", ret=0.036, excess=-0.02) == 1


def test_long_must_beat_the_market_not_merely_rise():
    assert verdict("long", ret=0.05, excess=0.02) == 1
    assert verdict("long", ret=0.05, excess=-0.02) == 0, \
        "up 5% while the market did 7% is not a good long"
    assert verdict("long", ret=-0.01, excess=0.03) == 1, \
        "down 1% while the market fell 4% IS a good long"


def test_short_still_means_a_fall():
    """`short` is a different claim from `avoid` and keeps absolute grading —
    a short that loses money is a loss no matter what the index did."""
    assert verdict("short", ret=-0.05, excess=0.99) == 1
    assert verdict("short", ret=0.05, excess=-0.99) == 0
    assert verdict("short", ret=0.0001, excess=None) is None, "inside the deadband"


def test_nothing_is_claimed_without_a_benchmark_or_inside_the_noise_band():
    assert verdict("long", ret=0.09, excess=None) is None, \
        "no benchmark means no market-relative claim — record it, do not grade it"
    assert verdict("avoid", ret=0.09, excess=None) is None
    for tiny in (0.0, DEADBAND * 0.5, -DEADBAND * 0.5):
        assert verdict("long", ret=0.5, excess=tiny) is None, \
            "excess inside the deadband is noise, not skill"


def test_crypto_is_measured_against_crypto():
    assert benchmark_for("ETH/USD") == "BTC/USD"
    assert benchmark_for("DOGE/USD") == "BTC/USD"
    assert benchmark_for("BTC/USD") is None, \
        "BTC is the crypto benchmark; grading it against itself is a tautology"


def test_each_market_gets_its_own_index():
    assert benchmark_for("AAPL") == "SPY"
    assert benchmark_for("AAPL", "US") == "SPY"
    assert benchmark_for("0700.HK") == "2800.HK"
    assert benchmark_for("D05.SI") == "ES3.SI"
    assert benchmark_for("600519.SS") == "2800.HK"
    assert benchmark_for("9984.T") == "EWJ"
    assert benchmark_for("005930.KS") == "EWY"
    assert benchmark_for("MC.PA") == "VGK"
    assert benchmark_for("ADS.DE") == "VGK"


def test_a_benchmark_is_never_graded_against_itself():
    """Otherwise every benchmark in the watchlist contributes guaranteed-zero
    excess rows, which land inside the deadband and quietly dilute the record."""
    for b in BENCH_SYMBOLS:
        assert benchmark_for(b) is None, f"{b} is a benchmark and must not be scored"


def test_the_benchmarks_are_all_watched():
    """A benchmark whose price is never snapshotted silently downgrades its whole
    market back to absolute grading — the failure this change exists to remove,
    returning as a missing row rather than a wrong formula. SPY was NOT in the
    watchlist when this was written, which would have made the fix a no-op for
    every US name."""
    env = Path(__file__).resolve().parents[2] / ".env"
    if not env.exists():
        return                       # CI has no .env; the ProDesk run covers this
    watched = set()
    for line in env.read_text().splitlines():
        if line.startswith(("STOCK_WATCHLIST=", "CRYPTO_WATCHLIST=")):
            watched |= {s.strip() for s in
                        line.split("=", 1)[1].split("#")[0].split(",") if s.strip()}
    missing = [b for b in BENCH_SYMBOLS if b not in watched]
    assert not missing, (
        f"benchmark(s) {missing} are not in any watchlist, so no price history is "
        f"stored for them and calls in those markets cannot be graded vs the market")


def test_ten_of_each_asset_class_are_actually_watchable():
    """The requirement is >=10 stocks and >=10 crypto carrying graded directional
    calls. The universe has to be able to supply that before the adviser can."""
    env = Path(__file__).resolve().parents[2] / ".env"
    if not env.exists():
        return
    lists = {}
    for line in env.read_text().splitlines():
        for key in ("STOCK_WATCHLIST", "CRYPTO_WATCHLIST"):
            if line.startswith(key + "="):
                lists[key] = [s.strip() for s in
                              line.split("=", 1)[1].split("#")[0].split(",") if s.strip()]
    assert len(lists.get("CRYPTO_WATCHLIST", [])) >= 10, \
        f"only {len(lists.get('CRYPTO_WATCHLIST', []))} crypto watched — cannot make 10 calls"
    assert len(lists.get("STOCK_WATCHLIST", [])) >= 10


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\nAll {len(tests)} scorecard-benchmark tests passed.")
