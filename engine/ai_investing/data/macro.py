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


def _yoy(series: list[float]) -> float | None:
    """Year-over-year % change from a newest-first monthly index."""
    if len(series) >= 13 and series[12]:
        return round((series[0] / series[12] - 1.0) * 100, 2)
    return None


def _fred_snapshot(api_key: str) -> dict:
    """Hard indicators for the MAJOR economies + US debt/liquidity levels.
    Every fetch is independent and optional — a missing series just leaves
    its key absent."""
    out: dict = {}
    if not api_key:
        return out
    fetches = [
        # --- United States ---
        ("cpi_yoy", "CPIAUCSL", _yoy),
        ("fed_funds", "FEDFUNDS", lambda s: s[0] if s else None),
        ("unemployment", "UNRATE", lambda s: s[0] if s else None),
        ("yield_curve_10y2y", "T10Y2Y", lambda s: s[0] if s else None),
        ("us_debt_gdp", "GFDEGDQ188S", lambda s: s[0] if s else None),   # federal debt % GDP
        ("m2_yoy", "M2SL", _yoy),                                        # money supply growth
        # --- Euro area / Japan / China (OECD MEI series on FRED) ---
        ("eu_cpi_yoy", "CP0000EZ19M086NEST", _yoy),
        ("eu_unemployment", "LRHUTTTTEZM156S", lambda s: s[0] if s else None),
        ("jp_cpi_yoy", "JPNCPIALLMINMEI", _yoy),
        ("cn_cpi_yoy", "CHNCPIALLMINMEI", _yoy),
    ]
    for key, series_id, fn in fetches:
        try:
            val = fn(_fred_series(series_id, api_key, limit=14))
            if val is not None:
                out[key] = val
        except Exception:
            continue
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
