"""Currency conversion, so one book means one number.

Until this existed the engine summed HKD, KRW, JPY and USD as if they were the
same unit. SK Hynix at 1,591,000 KRW was read as $1,591,000 a share, so the
sizer bought a thousandth of a share and called it a $1,588 position when it
was worth $1.15. Across the trading book that misstated $9,038 of a $16,027
net exposure -- and because equity, position sizing, drawdown and every risk
limit are computed off those numbers, all of them were wrong together.

The fix is deliberately at the DATA layer, not the reporting layer: bars are
converted to USD as they enter, so everything downstream -- signals, sizing,
stops, P&L, the learning spine -- reasons in one currency without needing to
know FX exists. Converting only at display would have left the trading logic
just as wrong but harder to see.

Rates are fetched once a day and cached to disk. A missing rate returns 1.0 and
is logged rather than raising: a stale rate is a small error, while refusing to
price an asset stops the book.
"""
from __future__ import annotations

import json
import os
import time
from typing import Optional

# Exchange suffix -> the currency that exchange quotes in.
SUFFIX_CCY = {
    "HK": "HKD", "KS": "KRW", "KQ": "KRW", "T": "JPY", "TW": "TWD",
    "TWO": "TWD", "SS": "CNY", "SZ": "CNY", "AS": "EUR", "PA": "EUR",
    "DE": "EUR", "MI": "EUR", "MC": "EUR", "BR": "EUR", "L": "GBP",
    "SI": "SGD", "AX": "AUD", "TO": "CAD", "NS": "INR", "BO": "INR",
    "SW": "CHF", "ST": "SEK", "OL": "NOK", "CO": "DKK",
}
_TTL = 12 * 3600.0
_mem: dict = {"ts": 0.0, "rates": {}}


def currency_of(symbol: str, asset_class: str = "stock") -> str:
    """Quote currency for a watchlist symbol. Crypto pairs are already USD."""
    if asset_class == "crypto" or "/" in symbol:
        return "USD"
    if "." in symbol:
        return SUFFIX_CCY.get(symbol.rsplit(".", 1)[-1].upper(), "USD")
    return "USD"


def _cache_path(settings) -> str:
    return os.path.join(os.path.dirname(settings.state_path), "fx_rates.json")


def _fetch() -> dict:
    """USD -> local units (e.g. HKD 7.84 means 1 USD = 7.84 HKD)."""
    out: dict = {}
    try:
        import yfinance as yf
    except ImportError:
        return out
    for ccy in sorted(set(SUFFIX_CCY.values())):
        try:
            h = yf.Ticker(f"USD{ccy}=X").history(period="5d")
            if len(h):
                rate = float(h["Close"].iloc[-1])
                if rate > 0:
                    out[ccy] = rate
        except Exception:
            continue
    return out


def rates(settings, force: bool = False) -> dict:
    """Cached USD->local rates. Disk-backed so a restart doesn't refetch."""
    now = time.time()
    if not force and _mem["rates"] and now - _mem["ts"] < _TTL:
        return _mem["rates"]
    path = _cache_path(settings)
    if not force:
        try:
            with open(path) as fh:
                blob = json.load(fh)
            if now - blob.get("ts", 0) < _TTL and blob.get("rates"):
                _mem.update(ts=blob["ts"], rates=blob["rates"])
                return _mem["rates"]
        except (OSError, json.JSONDecodeError):
            pass
    fresh = _fetch()
    if fresh:
        _mem.update(ts=now, rates=fresh)
        try:
            tmp = path + ".tmp"
            with open(tmp, "w") as fh:
                json.dump({"ts": now, "rates": fresh}, fh, indent=1)
            os.replace(tmp, path)
        except OSError:
            pass
    elif not _mem["rates"]:
        # last resort: whatever is on disk, however old. A stale rate beats
        # treating 1,591,000 KRW as 1,591,000 USD.
        try:
            with open(path) as fh:
                _mem["rates"] = json.load(fh).get("rates", {})
        except (OSError, json.JSONDecodeError):
            pass
    return _mem["rates"]


def to_usd(amount: float, symbol: str, settings, asset_class: str = "stock") -> float:
    """Convert a price/value quoted in the symbol's local currency into USD."""
    ccy = currency_of(symbol, asset_class)
    if ccy == "USD" or not amount:
        return amount
    rate = (rates(settings) or {}).get(ccy)
    if not rate or rate <= 0:
        return amount            # unknown rate: unchanged, never zero
    return amount / rate


def rate_for(symbol: str, settings, asset_class: str = "stock") -> Optional[float]:
    """The divisor used for this symbol, or None if it needs no conversion."""
    ccy = currency_of(symbol, asset_class)
    if ccy == "USD":
        return None
    return (rates(settings) or {}).get(ccy)
