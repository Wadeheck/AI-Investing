"""Event study: does fading pumps actually pay?

The political/pump hype-fade is a *hypothesis*. Before sizing into it, measure it:
find historical pump events (sharp price + volume spike) and look at forward returns.
If fading works, forward returns after a pump should be NEGATIVE and significant.

    cd engine
    python3 -m ai_investing.research.event_study
    DATA_PROVIDER=yfinance python3 -m ai_investing.research.event_study   # real test
"""
from __future__ import annotations

from dataclasses import dataclass

from ai_investing.config import settings
from ai_investing.data import get_provider
from ai_investing.indicators import stdev
from ai_investing.models import Asset, AssetClass


@dataclass
class HorizonStat:
    horizon: int
    n: int
    mean: float
    median: float
    neg_rate: float
    tstat: float


def detect_events(bars, window: int = 3, ret_thr: float = 0.12, vol_mult: float = 2.0) -> list[int]:
    """Indices where a pump occurred: >= ret_thr over `window` bars on >= vol_mult volume."""
    closes = [b.close for b in bars]
    vols = [b.volume for b in bars]
    events = []
    for t in range(21, len(bars) - 1):
        base = closes[t - window]
        if not base:
            continue
        ret = (closes[t] - base) / base
        prior = vols[t - 21:t - 1]
        avg_vol = sum(prior) / len(prior) if prior else 0.0
        vol_spike = (vols[t] / avg_vol) if avg_vol else 1.0
        if ret >= ret_thr and vol_spike >= vol_mult:
            events.append(t)
    return events


def study(bars_by_key, horizons=(1, 3, 5, 10)) -> tuple[int, list[HorizonStat]]:
    fwd: dict[int, list[float]] = {h: [] for h in horizons}
    n_events = 0
    for bars in bars_by_key.values():
        closes = [b.close for b in bars]
        for t in detect_events(bars):
            n_events += 1
            for h in horizons:
                if t + h < len(closes) and closes[t]:
                    fwd[h].append(closes[t + h] / closes[t] - 1)
    stats = []
    for h in horizons:
        xs = fwd[h]
        if not xs:
            stats.append(HorizonStat(h, 0, 0.0, 0.0, 0.0, 0.0))
            continue
        m = sum(xs) / len(xs)
        srt = sorted(xs)
        med = srt[len(srt) // 2]
        neg = sum(1 for x in xs if x < 0) / len(xs)
        sd = stdev(xs)
        tstat = (m / (sd / len(xs) ** 0.5)) if sd > 0 else 0.0
        stats.append(HorizonStat(h, len(xs), m, med, neg, tstat))
    return n_events, stats


def main() -> None:
    provider = get_provider(settings)
    assets = ([Asset(s, AssetClass.STOCK) for s in settings.stock_watchlist]
              + [Asset(s, AssetClass.CRYPTO, exchange=settings.crypto_exchange)
                 for s in settings.crypto_watchlist])
    bars = {a.key: provider.get_bars(a, 400) for a in assets}
    bars = {k: v for k, v in bars.items() if v}

    n, stats = study(bars)
    print(f"Event study: {n} pump events across {len(bars)} assets ({settings.data_provider} data)")
    print("Thesis: if fading works, forward returns AFTER a pump are negative.\n")
    print(f"  {'horizon':>8} {'n':>5} {'mean_fwd':>9} {'median':>8} {'neg_rate':>9} {'t-stat':>7}")
    for s in stats:
        print(f"  {s.horizon:>6}d  {s.n:>5} {s.mean * 100:>8.2f}% {s.median * 100:>7.2f}% "
              f"{s.neg_rate * 100:>8.0f}% {s.tstat:>7.2f}")

    significant = [s for s in stats if s.n >= 10 and s.mean < 0 and abs(s.tstat) >= 2]
    if significant:
        hz = ", ".join(f"{s.horizon}d" for s in significant)
        print(f"\n  VERDICT: fade has statistical support — significant negative forward returns at {hz}.")
    else:
        print("\n  VERDICT: no significant fade edge in this data. Do NOT size the hype-fade on this basis.")
    print("  (Synthetic data has no real edge by design — run with DATA_PROVIDER=yfinance/ccxt to test for real.)")


if __name__ == "__main__":
    main()
