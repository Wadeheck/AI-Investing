"""Distinguishes a fresh shock from a sustained regime, on the SAME node.

`macro_linkage` reads the graph's current impact level for an asset's origin
node -- a node that crossed saturation yesterday and one that has sat there
for six weeks read identically to it, since both are just "near max" (the
level itself is clamped to [-1, 1] in field.py, so duration is the only thing
left that can still distinguish them). This reads consecutive DAYS the origin
node has held its saturation and sign (brain/persistence.py, backed by the
real node_history time series in brain.db): zero for a brand-new shock,
ramping up only once a level has proven it isn't going to mean-revert away
within the week -- exactly the "this graduated from news to a structural
fact" read a level-only signal can't make.

Added 2026-08-18, following the `trend_zscore` pattern documented in
docs/design/FORMULA.md #7: a CANDIDATE feature. It runs every cycle and its
value reaches phi, but starts at theta=0 (learning/formula.py:_DEFAULT_WEIGHTS)
and is kept out of `consensus` -- it earns a nonzero weight only through the
same online-RLS / walk-forward gauntlet every other feature matures through,
never by fiat.
"""
from __future__ import annotations

from typing import Optional

from ai_investing.models import Asset, Bar, SignalDirection, SignalResult
from ai_investing.signals.base import Signal

# Below this many days, "how long has it been true" isn't a real read yet --
# give a fresh shock time to prove it's not just noise before this wakes up.
MIN_DAYS = 7.0
# A node pinned at the ceiling for this long or more is treated as a
# structural fact of the regime, not news -- full confidence.
SATURATE_DAYS = 45.0


class RegimePersistenceSignal(Signal):
    name = "regime_persistence"

    def evaluate(self, asset: Asset, bars: list[Bar], context: Optional[dict] = None) -> SignalResult:
        brain = (context or {}).get("brain") or {}
        impacts = brain.get("asset_impacts") or {}
        entry = impacts.get(asset.symbol.upper())
        if entry is None:
            # Longbridge-style symbols (700.HK) vs canonical (0700.HK): same
            # bare-ticker fallback macro_linkage uses, for the same reason.
            bare = asset.symbol.split(".")[0].lstrip("0").upper()
            for sym, e in impacts.items():
                if bare and sym.split(".")[0].lstrip("0").upper() == bare:
                    entry = e
                    break

        days = float((entry or {}).get("persistence_days", 0.0))
        impact = float((entry or {}).get("impact", 0.0))
        if not entry or days < MIN_DAYS or abs(impact) < 1e-6:
            return SignalResult(self.name, SignalDirection.FLAT, 0.0, 0.0,
                                "not sustained (<7d) or no active macro impact")

        sign = 1.0 if impact > 0 else -1.0
        ramp = min(1.0, (days - MIN_DAYS) / (SATURATE_DAYS - MIN_DAYS))
        score = sign * ramp
        if score > 0.05:
            direction = SignalDirection.LONG
        elif score < -0.05:
            direction = SignalDirection.SHORT
        else:
            direction = SignalDirection.FLAT

        return SignalResult(
            self.name, direction, score, ramp,
            f"{entry.get('node', '')} sustained {days:.0f}d at impact {impact:+.2f}",
            {"days": days, "node": entry.get("node", "")})
