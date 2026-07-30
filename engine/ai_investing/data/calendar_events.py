"""Scheduled-event awareness: the desk calendar the model was blind to.

Institutions treat "size into a scheduled catalyst" as a policy decision.
This module answers two questions before any NEW position is opened:
  1. Is this symbol inside its earnings window? (binary single-name event)
  2. Is today a macro-event day (FOMC decision)? (market-wide vol event)

Earnings dates come from the provider per symbol (cached 3 days — dates
rarely move). The FOMC schedule is published a year ahead and hardcoded per
year below; UPDATE IT each January (a stale year fails soft: no gating).
Ex-dividend awareness comes free with the dates the dividend layer fetches.
"""
from __future__ import annotations

import json
import os
import time
from datetime import date, datetime, timezone

CACHE_AGE = 3 * 86400

# FOMC decision days (second day of each meeting). Published schedule; update yearly.
FOMC = {
    2026: ["2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
           "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09"],
}


def _cache_path(settings=None) -> str:
    if settings is not None:
        return os.path.join(os.path.dirname(os.path.abspath(settings.state_path)),
                            "earnings_calendar.json")
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))))
    return os.path.join(root, "data", "earnings_calendar.json")


def next_earnings_date(symbol: str, settings=None) -> str | None:
    """ISO date of the next scheduled earnings report, or None (unknown/ETF)."""
    path = _cache_path(settings)
    try:
        with open(path) as fh:
            cache = json.load(fh)
    except (OSError, json.JSONDecodeError):
        cache = {}
    rec = cache.get(symbol)
    now = time.time()
    if rec and now - rec.get("asof", 0) < CACHE_AGE:
        return rec.get("next")
    nxt = None
    try:
        import warnings
        warnings.filterwarnings("ignore")
        import yfinance as yf
        cal = yf.Ticker(symbol).calendar or {}
        dates = cal.get("Earnings Date") or []
        today = date.today().isoformat()
        for d in dates:
            iso = d.isoformat() if hasattr(d, "isoformat") else str(d)[:10]
            if iso >= today:
                nxt = iso
                break
    except Exception:
        pass
    cache[symbol] = {"asof": now, "next": nxt}
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            json.dump(cache, fh)
    except OSError:
        pass
    return nxt


def days_to_earnings(symbol: str, settings=None) -> int | None:
    nxt = next_earnings_date(symbol, settings)
    if not nxt:
        return None
    try:
        return (date.fromisoformat(nxt) - date.today()).days
    except ValueError:
        return None


def is_macro_event_day(today: date | None = None) -> bool:
    """True on FOMC decision days (add CPI later if a reliable free source
    appears — CPI release dates are irregular enough that guessing is worse
    than not gating)."""
    d = today or datetime.now(timezone.utc).date()
    return d.isoformat() in FOMC.get(d.year, [])


def entry_risk_multiplier(symbol: str, settings=None, window_days: int = 2,
                          earnings_mult: float = 0.5, macro_mult: float = 0.7) -> tuple[float, str]:
    """Sizing multiplier for a NEW entry given the calendar: 1.0 = clear.
    Never blocks exits or stops — only fresh risk-taking is throttled."""
    mult, why = 1.0, ""
    dte = days_to_earnings(symbol, settings)
    if dte is not None and 0 <= dte <= window_days:
        mult *= earnings_mult
        why = f"earnings in {dte}d"
    if is_macro_event_day():
        mult *= macro_mult
        why = (why + "; " if why else "") + "FOMC day"
    return mult, why
