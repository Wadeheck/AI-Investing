"""Binance futures positioning backfill: open interest, top-trader long/short
ratio, taker buy/sell imbalance — the 'crowd positioning' data that perp
scalpers trade on — for BTC/ETH/SOL, daily, across the replay window.

Source: data.binance.vision daily metrics zips (free, no key). Each zip has
5-minute rows for one day; we aggregate to one daily record. Resumable.

Output: data/crypto_positioning.json
  {"BTCUSDT": {"2024-03-05": {"oi": <sum_open_interest last>,
                              "tlsr": <top-trader long/short ratio mean>,
                              "taker": <taker buy/sell vol ratio mean>}, ...}}
"""
from __future__ import annotations

import csv
import io
import json
import sys
import time
import urllib.request
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
OUT = DATA_DIR / "crypto_positioning.json"
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
START = date(2023, 7, 1)
URL = ("https://data.binance.vision/data/futures/um/daily/metrics/"
       "{sym}/{sym}-metrics-{d}.zip")


def log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc):%H:%M:%S}] {msg}", flush=True)


def fetch_day(sym: str, d: str) -> dict | None:
    req = urllib.request.Request(URL.format(sym=sym, d=d),
                                 headers={"User-Agent": "ai-investing/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            blob = resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:          # day not published (too old/new)
            return {}
        return None                  # transient — retry next run
    except Exception:
        return None
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            with zf.open(zf.namelist()[0]) as fh:
                rows = list(csv.DictReader(io.TextIOWrapper(fh)))
    except Exception:
        return None
    if not rows:
        return {}
    def col(name, agg):
        vals = []
        for r in rows:
            try:
                vals.append(float(r[name]))
            except (KeyError, TypeError, ValueError):
                pass
        if not vals:
            return None
        return vals[-1] if agg == "last" else sum(vals) / len(vals)
    return {"oi": col("sum_open_interest", "last"),
            "tlsr": col("sum_toptrader_long_short_ratio", "mean"),
            "taker": col("sum_taker_long_short_vol_ratio", "mean")}


def run() -> None:
    out = json.loads(OUT.read_text()) if OUT.exists() else {}
    today = datetime.now(timezone.utc).date()
    fetched = 0
    for sym in SYMBOLS:
        out.setdefault(sym, {})
        d = START
        while d < today:
            ds = d.isoformat()
            d += timedelta(days=1)
            if ds in out[sym]:
                continue
            rec = fetch_day(sym, ds)
            if rec is None:
                continue             # transient failure: never record fake data
            out[sym][ds] = rec
            fetched += 1
            if fetched % 200 == 0:
                OUT.write_text(json.dumps(out))
                log(f"{fetched} day-records fetched (at {sym} {ds})")
            time.sleep(0.15)
    OUT.write_text(json.dumps(out))
    log(f"positioning backfill complete: "
        + ", ".join(f"{s}:{len(out[s])}" for s in SYMBOLS))


if __name__ == "__main__":
    run()
