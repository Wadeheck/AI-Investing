"""Board lots: the quantity unit each market actually trades in.

US stocks trade in single shares, so for the whole of this project's life
"quantise the order" meant `math.floor(qty)` and that was right. It is wrong
everywhere else. Hong Kong trades Tencent in lots of 100 and China Mobile in
lots of 500; Singapore and the mainland exchanges use 100. An order for 37
shares of a 100-lot stock is not a small order, it is a rejected one — the same
failure mode as the sub-share orders in `risk._quantize_whole_shares`, one level
up, and that docstring has carried "KNOWN GAP: HK board lots are not modelled"
since it was written.

Lot sizes are a property of the listing, not of the day, so they are fetched
once and cached to disk. The cache is authoritative for the order path: a
network call between deciding to trade and sizing the trade is a network call
that can fail at the worst moment, and an order sized against a guess is exactly
what this module exists to prevent.

UNKNOWN MEANS DO NOT TRADE, for non-US listings. Defaulting an unknown lot to 1
would send 37 shares of a 100-lot stock and collect a reject every cycle
forever; defaulting it to 100 would silently multiply a US order by a hundred.
There is no safe guess, so there is no guess.
"""
from __future__ import annotations

import json
import os

from ai_investing.brokers import symbols as sym_map
from ai_investing.util import atomic

_CACHE = "lot_sizes.json"


class LotBook:
    """Lot size per WATCHLIST symbol, cached on disk."""

    def __init__(self, path: str, lots: dict | None = None):
        self.path = path
        self._lots: dict[str, int] = dict(lots or {})

    # -- loading / saving ---------------------------------------------------
    @classmethod
    def load(cls, data_dir: str) -> "LotBook":
        path = os.path.join(data_dir, _CACHE)
        try:
            with open(path) as fh:
                blob = json.load(fh) or {}
            lots = {k: int(v) for k, v in (blob.get("lots") or {}).items()
                    if str(v).lstrip("-").isdigit() and int(v) > 0}
        except (OSError, json.JSONDecodeError, AttributeError, ValueError):
            lots = {}
        return cls(path, lots)

    def save(self) -> None:
        try:
            atomic.write_json(self.path, {"lots": self._lots})
        except OSError:
            pass

    # -- the question everything else asks ----------------------------------
    def lot_size(self, symbol: str) -> int | None:
        """Shares per board lot, or None if unknown.

        US listings are 1 without a lookup: every US venue this engine reaches
        trades single shares, and making the US path depend on a cache that
        might be cold would break the book that already works in order to widen
        one that does not.
        """
        if sym_map.market_of(symbol) == "US":
            return 1
        return self._lots.get(symbol)

    def known(self) -> dict[str, int]:
        return dict(self._lots)

    def update(self, lots: dict) -> int:
        """Merge fetched sizes in. Returns how many were new or changed."""
        changed = 0
        for k, v in (lots or {}).items():
            try:
                v = int(v)
            except (TypeError, ValueError):
                continue
            if v > 0 and self._lots.get(k) != v:
                self._lots[k] = v
                changed += 1
        return changed

    # -- quantisation --------------------------------------------------------
    def floor_to_lot(self, symbol: str, qty: float) -> float:
        """Largest tradable quantity at or below `qty`. 0.0 when none is.

        Floors, never rounds up: rounding up invents shares the cash ceilings
        were never checked against, and on a 500-lot stock "round up" is not a
        rounding error, it is up to 499 extra shares.
        """
        lot = self.lot_size(symbol)
        if not lot or lot < 1:
            return 0.0                      # unknown => untradable, see module doc
        return float(int(qty / lot) * lot)


def fetch_lot_sizes(watchlist: list[str], quote_ctx) -> dict:
    """Ask the venue for board lots. `quote_ctx` is a longport QuoteContext.

    Batched, and tolerant: a market this account has no data entitlement for
    returns an empty list rather than raising, and one bad chunk must not cost
    the other two hundred symbols.
    """
    want = {}
    for w in watchlist:
        lb = sym_map.to_longbridge(w)
        if lb and sym_map.market_of(w) != "US":
            want[lb] = w
    out: dict[str, int] = {}
    keys = list(want)
    for i in range(0, len(keys), 20):
        chunk = keys[i:i + 20]
        try:
            for info in quote_ctx.static_info(chunk) or []:
                lot = int(getattr(info, "lot_size", 0) or 0)
                if lot > 0:
                    out[want[info.symbol]] = lot
        except Exception:                                         # noqa: BLE001
            continue
    return out
