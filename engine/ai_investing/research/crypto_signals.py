"""Crypto-native signals: the data the web was blind to.

Free, keyless sources (historical + live from the same endpoints):
  funding      — Binance perpetual funding rates (BTC/ETH/SOL, 8h → daily avg).
                 Persistently high funding = crowded leveraged longs (fragile);
                 deeply negative = capitulation. A CONTRARIAN crowding signal.
  fng          — alternative.me crypto Fear & Greed index (daily, full history).
                 Extreme fear has historically been accumulation; extreme greed,
                 distribution. The crypto crowd's emotional thermometer.
  btc_addr     — blockchain.info unique active addresses (daily): raw on-chain
                 usage. A rising 30-day trend = organic adoption under price.
  positioning  — Binance futures global long/short ACCOUNT ratio, all watchlist
                 symbols (not just BTC/ETH/SOL). A more direct crowding read than
                 funding rate, but Binance retains only the trailing 30 days
                 server-side — no way to backfill deep history for this one, so
                 it starts accumulating from whenever this first runs. Computed
                 and cached every cycle; NOT blended into brain resting levels
                 until CRYPTO_POSITIONING_ENABLED=true (default off — dormant
                 until it has enough accumulated real days to be worth trusting;
                 see docs/design/FORMULA.md-style reasoning in
                 docs/status/STATE_OF_THE_SYSTEM.md §4A "positioning crowding").

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
from typing import Optional

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
OUT = DATA_DIR / "crypto_signals.json"
PERPS = {"BTC/USD": "BTCUSDT", "ETH/USD": "ETHUSDT", "SOL/USD": "SOLUSDT"}


def _binance_perp(sym: str) -> str:
    """'BTC/USD' -> 'BTCUSDT'. All watchlist symbols follow this pattern."""
    return sym.split("/")[0] + "USDT"


def _positioning_symbols() -> dict[str, str]:
    """Every watchlist symbol -> its Binance perp ticker, falling back to just
    the funding-rate trio if settings can't be read (keeps this module usable
    standalone, same spirit as the rest of the file)."""
    try:
        from ai_investing.config import settings
        return {sym: _binance_perp(sym) for sym in settings.crypto_watchlist}
    except Exception:
        return dict(PERPS)


def _get(url: str, timeout: int = 25):
    req = urllib.request.Request(url, headers={"user-agent": "ai-investing/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _day(ms: float) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date().isoformat()


def _load() -> dict:
    try:
        d = json.loads(OUT.read_text())
    except (OSError, json.JSONDecodeError):
        d = {"funding": {}, "fng": {}, "btc_addr": {}}
    d.setdefault("positioning", {})
    return d


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

    # positioning: Binance retains only 30 days server-side no matter what
    # startTime is requested (verified 2026-08-15) -- one call gets everything
    # available; refresh_live() tops it up daily from here on.
    for sym, perp in _positioning_symbols().items():
        try:
            rows = _get("https://fapi.binance.com/futures/data/globalLongShortAccountRatio"
                        f"?symbol={perp}&period=1d&limit=30")
            d["positioning"][sym] = {_day(r["timestamp"]): float(r["longShortRatio"])
                                     for r in rows if "timestamp" in r}
        except Exception:
            continue
    print(f"[crypto] positioning: {len(d['positioning'])} symbols", flush=True)

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
        for sym, perp in _positioning_symbols().items():
            try:
                rows = _get("https://fapi.binance.com/futures/data/globalLongShortAccountRatio"
                            f"?symbol={perp}&period=1d&limit=3")
                for r in rows:
                    if "timestamp" in r:
                        d["positioning"].setdefault(sym, {})[_day(r["timestamp"])] = \
                            float(r["longShortRatio"])
            except Exception:
                continue
        d["_refreshed"] = time.time()
        _save(d)
    except Exception:
        pass
    return d


def positioning_crowding_z(cs: dict, sym: str, lookback: int = 30, min_days: int = 5) -> Optional[float]:
    """Z-score of today's long/short account ratio vs its own recent history.
    Positive z = unusually long-crowded (fragile, prone to a long squeeze);
    negative z = unusually short-crowded. None if there isn't enough history
    yet to judge "unusual" against -- honest silence over a noisy guess."""
    series = (cs.get("positioning") or {}).get(sym) or {}
    if len(series) < min_days:
        return None
    vals = [v for _, v in sorted(series.items())][-lookback:]
    latest = vals[-1]
    mean = sum(vals) / len(vals)
    sd = (sum((v - mean) ** 2 for v in vals) / max(1, len(vals) - 1)) ** 0.5
    return (latest - mean) / sd if sd > 1e-12 else 0.0


if __name__ == "__main__":
    fetch_history(float(sys.argv[1]) if len(sys.argv) > 1 else 3.2)
