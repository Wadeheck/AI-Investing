"""Hard macro data: market context tickers (VIX, DXY, yields, commodities) via
yfinance and economic series (CPI, Fed funds, unemployment) via FRED.

Everything degrades gracefully (no key / no network -> None fields) and is cached
on disk with a TTL so the engine's 5-minute cycles don't hammer free APIs.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request

FRED_URL = "https://api.stlouisfed.org/fred/series/observations"
CACHE_TTL_SECONDS = 6 * 3600

# context tickers -> snapshot field name
CONTEXT_TICKERS = {
    "^VIX": "vix",
    "DX-Y.NYB": "dxy",
    "^TNX": "tnx",          # 10Y yield x10 (CBOE convention: 42.5 = 4.25%)
    "GC=F": "gold",
    "CL=F": "oil",
    "HG=F": "copper",
}


def _yf_snapshot() -> dict:
    """Level + 20-day change for each context ticker. Lazy yfinance import."""
    out: dict = {}
    try:
        import yfinance  # type: ignore
    except ImportError:
        return out
    for ticker, name in CONTEXT_TICKERS.items():
        try:
            hist = yfinance.Ticker(ticker).history(period="2mo", interval="1d")
            closes = list(hist["Close"].dropna())
            if not closes:
                continue
            out[name] = round(float(closes[-1]), 4)
            if len(closes) > 20 and closes[-21]:
                out[f"{name}_chg_20d"] = round(float(closes[-1]) / float(closes[-21]) - 1.0, 4)
        except Exception:
            continue
    if out.get("tnx") is not None:
        out["us10y"] = round(out["tnx"] / 10.0, 3)
    return out


def _fred_series(series_id: str, api_key: str, limit: int = 14) -> list[float]:
    url = (f"{FRED_URL}?series_id={series_id}&api_key={api_key}&file_type=json"
           f"&sort_order=desc&limit={limit}")
    with urllib.request.urlopen(url, timeout=20) as resp:
        obs = json.loads(resp.read().decode()).get("observations", [])
    vals = []
    for o in obs:
        try:
            vals.append(float(o["value"]))
        except (KeyError, ValueError):
            continue
    return vals  # newest first


def _fred_snapshot(api_key: str) -> dict:
    out: dict = {}
    if not api_key:
        return out
    try:
        cpi = _fred_series("CPIAUCSL", api_key)         # monthly index
        if len(cpi) >= 13:
            out["cpi_yoy"] = round((cpi[0] / cpi[12] - 1.0) * 100, 2)
        ff = _fred_series("FEDFUNDS", api_key, limit=2)
        if ff:
            out["fed_funds"] = ff[0]
        un = _fred_series("UNRATE", api_key, limit=2)
        if un:
            out["unemployment"] = un[0]
        spread = _fred_series("T10Y2Y", api_key, limit=2)
        if spread:
            out["yield_curve_10y2y"] = spread[0]
    except Exception:
        pass
    return out


def get_snapshot(settings) -> dict:
    """The per-cycle macro snapshot, disk-cached. Keys may be missing — consumers
    must treat every field as optional."""
    cache_path = settings.brain.macro_cache_path
    try:
        with open(cache_path) as fh:
            cached = json.load(fh)
        if time.time() - cached.get("_fetched_at", 0) < CACHE_TTL_SECONDS:
            return cached
    except (OSError, json.JSONDecodeError):
        pass

    snap = _yf_snapshot()
    snap.update(_fred_snapshot(settings.brain.fred_api_key))
    snap["_fetched_at"] = time.time()
    try:
        os.makedirs(os.path.dirname(os.path.abspath(cache_path)), exist_ok=True)
        with open(cache_path, "w") as fh:
            json.dump(snap, fh)
    except OSError:
        pass
    return snap
