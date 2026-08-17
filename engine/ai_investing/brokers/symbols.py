"""Watchlist symbols <-> Longbridge symbols, and which markets are reachable.

WHY THIS EXISTS
---------------
The watchlist speaks Yahoo, because that is where the bars come from. Longbridge
speaks its own dialect. For most markets the two agree; for two of them they do
not, and nobody had noticed:

    Singapore   watchlist  D05.SI      Longbridge  D05.SG
    Shanghai    watchlist  600519.SS   Longbridge  600519.SH

`static_info(["D05.SI"])` returns an EMPTY LIST — not an error, not a rejection.
So every check of "can we trade this?" answered no, and the answer was recorded
as a fact about the venue rather than about the string. `runner._live_universe()`
narrowed the live book to USD listings, a stale docstring in `live.py` supplied a
plausible reason (currency conversion, which was already fixed), and the real
cause went unexamined for a fortnight while 78% of the engine's strongest
convictions pointed at names it had decided were unreachable.

Probed against the live account on 2026-08-17: Longbridge resolves **116 of the
126** non-USD watchlist names once the suffix is translated, and the account
holds SGD 1,000,000 and HKD 1,000,000 alongside its USD specifically to trade
them. Ten names have no Longbridge symbol in any form — Korea, Tokyo, Taiwan,
Frankfurt, Paris, Amsterdam — and those are genuinely out of reach.

ONE TABLE, BOTH DIRECTIONS
--------------------------
The map is defined once and inverted, rather than written twice. Two hand-kept
tables that must agree is precisely how `watchlist_symbol` and `_symbol` could
have drifted apart, and a symbol that converts one way but not the other is
worse than one that never converts: the order goes out fine and the fill comes
back under a name the engine does not recognise, so it manages a position it
believes belongs to someone else (see `runner.foreign_positions`).
"""
from __future__ import annotations

# Watchlist (Yahoo) suffix -> Longbridge suffix. Absent = identical in both
# dialects (HK, SZ); no suffix at all means US.
_TO_LB = {
    "SI": "SG",      # Singapore Exchange
    "SS": "SH",      # Shanghai
}
_FROM_LB = {v: k for k, v in _TO_LB.items()}

# Suffixes Longbridge serves. Everything else has no symbol there in any form —
# verified by probing `static_info` with every plausible spelling.
REACHABLE = {"US", "HK", "SG", "SH", "SZ"}

# Markets whose prices are NOT the currency this engine reasons in. Bars are
# USD-normalised at the data layer (see data/fx.py), so any price sent BACK to
# the venue — a limit, a stop, a take-profit — has to be converted the other way
# first. Getting this wrong is not a missed fill: a SELL limit priced in USD
# against an HKD book is ~7.8x below the market and fills instantly at the worst
# price available.
NON_USD_SUFFIXES = {"HK", "SG", "SH", "SZ"}


def market_of(symbol: str) -> str:
    """The Longbridge market suffix for a WATCHLIST symbol."""
    if "." not in (symbol or ""):
        return "US"
    suf = symbol.rsplit(".", 1)[-1].upper()
    return _TO_LB.get(suf, suf)


def to_longbridge(symbol: str) -> str | None:
    """Watchlist symbol -> Longbridge symbol, or None if unreachable.

    None rather than a best guess: an unreachable name must be excluded from the
    tradable universe, and a plausible-looking string that the venue silently
    does not know would put it back in.
    """
    if not symbol or "/" in symbol:
        return None                      # crypto never goes to a stock venue
    if "." not in symbol:
        return f"{symbol}.US"
    base, suf = symbol.rsplit(".", 1)
    mkt = _TO_LB.get(suf.upper(), suf.upper())
    return f"{base}.{mkt}" if mkt in REACHABLE else None


def from_longbridge(symbol: str) -> str:
    """Longbridge symbol -> the form the watchlist uses.

    Two conversions beyond the suffix map, both learned the hard way and both
    kept from `LongbridgeBroker.watchlist_symbol`: `.US` is stripped, because the
    watchlist says `AAPL`; and HK codes are zero-padded to four digits, because
    Longbridge reports `700.HK` while the watchlist holds `0700.HK` and a dict
    lookup does not care that a human can see they are the same.
    """
    s = (symbol or "").strip()
    if "." not in s:
        return s
    base, suf = s.rsplit(".", 1)
    suf = suf.upper()
    if suf == "US":
        return base
    if suf == "HK" and base.isdigit():
        base = f"{int(base):04d}"
    return f"{base}.{_FROM_LB.get(suf, suf)}"


def reachable(symbol: str) -> bool:
    """Can this watchlist symbol be sent to Longbridge at all?"""
    return to_longbridge(symbol) is not None


def is_non_usd(symbol: str) -> bool:
    """Does this symbol trade in something other than USD at the venue?"""
    return market_of(symbol) in NON_USD_SUFFIXES
