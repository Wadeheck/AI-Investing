#!/usr/bin/env python3
"""Hourly crypto-signal refresh — crypto trades 24/7, so its inputs cannot
sit on a daily or 6-hourly clock like equity macro does.

Refreshes:
  - funding rates / Fear & Greed / on-chain activity (crypto_signals.json)
  - Binance positioning: top-trader long/short ratio + open interest
    (crypto_positioning.json) — this one had NO refresh job at all and was
    running 100+ hours stale until 2026-08-02.

Free endpoints only, no keys. Safe to run repeatedly; each source dedupes or
overwrites its own file.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))


def step(name, fn):
    try:
        out = fn()
        print(f"  ok  {name}: {out}", flush=True)
    except Exception as exc:
        print(f"  FAIL {name}: {type(exc).__name__}: {str(exc)[:90]}", flush=True)


def signals():
    from ai_investing.research.crypto_signals import refresh_live
    cs = refresh_live(max_age_hours=0.0)      # force
    fng = sorted(cs.get("fng", {}).items())
    return (f"funding {len(cs.get('funding', {}))} syms, "
            f"F&G {fng[-1][1] if fng else '?'}, "
            f"on-chain {len(cs.get('btc_addr', {}))} days")


def positioning():
    from ai_investing.research import binance_metrics_fetch as bm
    bm.run()
    import json
    d = json.loads((ROOT / "data" / "crypto_positioning.json").read_text())
    days = max((len(v) for v in d.values()), default=0)
    return f"{len(d)} symbols, {days} days"


if __name__ == "__main__":
    print(f"[{datetime.now(timezone.utc):%Y-%m-%d %H:%M}] crypto live refresh", flush=True)
    step("crypto signals (funding/F&G/on-chain)", signals)
    step("Binance positioning (LSR/OI)", positioning)
    print("done", flush=True)
