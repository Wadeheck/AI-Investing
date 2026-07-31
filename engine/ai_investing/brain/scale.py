"""Sense of scale: translate directionless field impacts into expected-move units.

A field impact of -0.3 on BTC and -0.3 on Coca-Cola are wildly different trades:
one asset moves 4-5% a day, the other under 1%. This module gives every tradable
node a volatility, so an impact becomes an EXPECTED MOVE in percent:

    expected_move(h days) = impact x daily_vol x sqrt(h) x gain

i.e. a full-scale impact (|impact| = 1) is read as "about one h-day sigma move",
scaled by the calibration `gain` (brain/calibration.py measures whether the
brain's reflexes over- or under-shoot reality and corrects the mapping).

Vol comes from realized daily moves in brain.db's price_history snapshots when
enough history exists (>= MIN_OBS observations), else from honest per-market
priors. Either way the number is explicit and lands in asset_impacts, so the
adviser can size risk instead of sizing conviction.
"""
from __future__ import annotations

import json
import math
import os
import sqlite3

MIN_OBS = 15                # snapshots needed before realized vol replaces the prior
HORIZON_DAYS = 5            # matches the scorecard's judgment horizon
# honest priors (daily sigma) by market / instrument kind
PRIOR_VOL = {"CRYPTO": 0.045, "US": 0.02, "HK": 0.022, "CN": 0.022, "SG": 0.013,
             "EU": 0.018, "JP": 0.018, "KR": 0.022, "TW": 0.02}
ETF_VOL = 0.011             # broad funds diversify away single-name variance
BOND_ETF_VOL = 0.008
_ETF_HINTS = ("ETF", "Tracker Fund", "Trust")


def _db_path(settings) -> str:
    return settings.brain.db_path


def price_series(settings, min_len: int = 2) -> dict[str, list[float]]:
    """{symbol: [price ordered by date]} from the scorecard's daily snapshots."""
    out: dict[str, list[float]] = {}
    try:
        conn = sqlite3.connect(_db_path(settings))
        rows = conn.execute(
            "SELECT symbol, date, price FROM price_history ORDER BY symbol, date").fetchall()
        conn.close()
    except sqlite3.Error:
        return out
    for sym, _date, px in rows:
        if px and px > 0:
            out.setdefault(sym, []).append(px)
    return {s: p for s, p in out.items() if len(p) >= min_len}


def volume_series(settings, min_len: int = 2) -> dict[str, list[float]]:
    """{symbol: [daily volume ordered by date]} — empty until the runner has
    snapshotted volumes (the column is a v4 migration; older rows are NULL)."""
    out: dict[str, list[float]] = {}
    try:
        conn = sqlite3.connect(_db_path(settings))
        rows = conn.execute(
            "SELECT symbol, date, volume FROM price_history "
            "WHERE volume IS NOT NULL ORDER BY symbol, date").fetchall()
        conn.close()
    except sqlite3.Error:
        return out                        # old schema without the column
    for sym, _date, v in rows:
        if v and v > 0:
            out.setdefault(sym, []).append(v)
    return {s: v for s, v in out.items() if len(v) >= min_len}


def relative_volume(vols: list[float], k: int = 5, base_n: int = 20) -> float | None:
    """Mean volume of the last k snapshots vs the prior base_n — the tape's
    conviction. >1 = heavy tape, <1 = thin drift. None without enough data."""
    if len(vols) < k + 5:
        return None
    recent = sum(vols[-k:]) / k
    base_window = vols[-(k + base_n):-k]
    base = sum(base_window) / len(base_window)
    if base <= 0:
        return None
    return recent / base


def realized_daily_vol(prices: list[float]) -> float | None:
    if len(prices) < MIN_OBS:
        return None
    rets = [math.log(b / a) for a, b in zip(prices[:-1], prices[1:]) if a > 0 and b > 0]
    if len(rets) < MIN_OBS - 1:
        return None
    m = sum(rets) / len(rets)
    var = sum((r - m) ** 2 for r in rets) / max(1, len(rets) - 1)
    return max(0.003, min(0.12, math.sqrt(var)))


def prior_vol(node) -> float:
    label = getattr(node, "label", "") or ""
    if any(h in label for h in _ETF_HINTS):
        return BOND_ETF_VOL if "Treasury" in label else ETF_VOL
    return PRIOR_VOL.get(getattr(node, "market", ""), 0.02)


def symbol_vols(settings, graph) -> dict[str, float]:
    """{SYMBOL: daily sigma} — realized where history allows, prior otherwise."""
    series = price_series(settings)
    vols: dict[str, float] = {}
    for n in graph.nodes.values():
        if n.type != "asset" or not n.symbol:
            continue
        sym = n.symbol.upper()
        rv = realized_daily_vol(series.get(sym, []))
        vols[sym] = rv if rv is not None else prior_vol(n)
    return vols


def load_gain(settings) -> float:
    """Calibration gain (brain/calibration.py). 1.0 until evidence says otherwise."""
    path = os.path.join(os.path.dirname(os.path.abspath(_db_path(settings))),
                        "edge_calibration.json")
    try:
        with open(path) as fh:
            return max(0.25, min(2.0, float(json.load(fh).get("gain", 1.0))))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return 1.0


def enrich_with_scale(asset_impacts: dict[str, dict], settings, graph,
                      horizon_days: int = HORIZON_DAYS) -> dict[str, float]:
    """Attach vol + expected move to each asset impact IN PLACE; returns the
    vol map so callers (adviser, priced_in) don't recompute it."""
    vols = symbol_vols(settings, graph)
    gain = load_gain(settings)
    root_h = math.sqrt(horizon_days)
    for sym, row in asset_impacts.items():
        vol = vols.get(sym.upper())
        if vol is None:
            continue
        row["vol_daily"] = round(vol, 4)
        row["expected_move_pct"] = round(row.get("impact", 0.0) * vol * root_h * gain * 100, 2)
        row["horizon_days"] = horizon_days
    return vols
