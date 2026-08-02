"""Crypto-native signals: the data the web was blind to.

Three free, keyless sources (historical + live from the same endpoints):
  funding   — Binance perpetual funding rates (BTC/ETH/SOL, 8h → daily avg).
              Persistently high funding = crowded leveraged longs (fragile);
              deeply negative = capitulation. A CONTRARIAN crowding signal.
  fng       — alternative.me crypto Fear & Greed index (daily, full history).
              Extreme fear has historically been accumulation; extreme greed,
              distribution. The crypto crowd's emotional thermometer.
  btc_addr  — blockchain.info unique active addresses (daily): raw on-chain
              usage. A rising 30-day trend = organic adoption under price.

Cached to data/crypto_signals.json; `python -m ...crypto_signals` refreshes
history, `refresh_live()` tops up the latest points (cheap, for the live
engine). The trainer injects these as impulses on the crypto nodes so the
WEB carries them — decisions still come only from the nodes and the web.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
OUT = DATA_DIR / "crypto_signals.json"
PERPS = {"BTC/USD": "BTCUSDT", "ETH/USD": "ETHUSDT", "SOL/USD": "SOLUSDT"}


def _get(url: str, timeout: int = 25):
    req = urllib.request.Request(url, headers={"user-agent": "ai-investing/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _day(ms: float) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date().isoformat()


def _load() -> dict:
    try:
        return json.loads(OUT.read_text())
    except (OSError, json.JSONDecodeError):
        return {"funding": {}, "fng": {}, "btc_addr": {}}


def _save(d: dict) -> None:
    OUT.write_text(json.dumps(d))


def fetch_history(years: float = 3.2) -> dict:
    d = _load()
    start_ms = int((time.time() - years * 365 * 86400) * 1000)

    for sym, perp in PERPS.items():
        rates: dict[str, list[float]] = {}
        cursor = start_ms
        for _ in range(40):                      # 1000×8h ≈ 333d per page
            try:
                rows = _get(f"https://fapi.binance.com/fapi/v1/fundingRate"
                            f"?symbol={perp}&startTime={cursor}&limit=1000")
            except Exception:
                time.sleep(10)
                continue
            if not rows:
                break
            for r in rows:
                rates.setdefault(_day(r["fundingTime"]), []).append(float(r["fundingRate"]))
            nxt = rows[-1]["fundingTime"] + 1
            if nxt <= cursor:
                break
            cursor = nxt
            time.sleep(0.5)
        d["funding"][sym] = {day: round(sum(v) / len(v), 8) for day, v in rates.items()}
        print(f"[crypto] funding {sym}: {len(d['funding'][sym])} days", flush=True)

    try:
        rows = _get("https://api.alternative.me/fng/?limit=0")["data"]
        d["fng"] = {datetime.fromtimestamp(int(r["timestamp"]), tz=timezone.utc)
                    .date().isoformat(): int(r["value"]) for r in rows}
        print(f"[crypto] fear&greed: {len(d['fng'])} days", flush=True)
    except Exception as exc:
        print(f"[crypto] fng failed: {exc}", flush=True)

    try:
        vals = _get("https://api.blockchain.info/charts/n-unique-addresses"
                    f"?timespan={int(years * 365)}days&format=json")["values"]
        d["btc_addr"] = {datetime.fromtimestamp(v["x"], tz=timezone.utc)
                         .date().isoformat(): v["y"] for v in vals}
        print(f"[crypto] active addresses: {len(d['btc_addr'])} days", flush=True)
    except Exception as exc:
        print(f"[crypto] btc_addr failed: {exc}", flush=True)

    _save(d)
    return d


def refresh_live(max_age_hours: float = 1.0) -> dict:
    # crypto trades 24/7 — a 6h cache meant the engine could act on a
    # funding/F&G read a quarter of a day old. 1h (2026-08-02).
    """Cheap top-up of the latest points, for the live engine's cycles."""
    d = _load()
    stamp = d.get("_refreshed", 0)
    if time.time() - stamp < max_age_hours * 3600:
        return d
    try:
        for sym, perp in PERPS.items():
            rows = _get(f"https://fapi.binance.com/fapi/v1/fundingRate?symbol={perp}&limit=6")
            for r in rows:
                day = _day(r["fundingTime"])
                d["funding"].setdefault(sym, {})[day] = float(r["fundingRate"])
        for r in _get("https://api.alternative.me/fng/?limit=3")["data"]:
            day = datetime.fromtimestamp(int(r["timestamp"]), tz=timezone.utc).date().isoformat()
            d["fng"][day] = int(r["value"])
        d["_refreshed"] = time.time()
        _save(d)
    except Exception:
        pass
    return d


if __name__ == "__main__":
    fetch_history(float(sys.argv[1]) if len(sys.argv) > 1 else 3.2)
