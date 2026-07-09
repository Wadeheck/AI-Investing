"""Data sanity guard — stops the engine acting on bad prices.

A single zero, a stale feed, or an unadjusted split can create a fake huge move that
triggers a wrong trade or a false stop. Each cycle the guard flags symbols whose price
is non-positive, stale (newest bar too old), or jumped more than a threshold vs. the last
good price. The runner excludes flagged symbols from trading that cycle (and alerts).
"""
from __future__ import annotations

from datetime import datetime, timezone


class DataGuard:
    def __init__(self, cfg):
        self.cfg = cfg
        self._last: dict[str, float] = {}

    def check(self, prices: dict[str, float], bars_by_key: dict | None = None):
        bad: set[str] = set()
        messages: list[str] = []
        now = datetime.now(timezone.utc)

        for key, px in prices.items():
            if px is None or px <= 0:
                bad.add(key)
                messages.append(f"{key}: non-positive price ({px})")
                continue

            prev = self._last.get(key)
            if prev and prev > 0 and abs(px - prev) / prev > self.cfg.max_price_jump:
                bad.add(key)
                messages.append(f"{key}: suspicious {abs(px - prev) / prev:.0%} jump {prev:.4g}->{px:.4g}")

            if bars_by_key and bars_by_key.get(key):
                ts = getattr(bars_by_key[key][-1], "ts", None)
                try:
                    age_days = (now - ts).total_seconds() / 86400 if ts else 0.0
                    if age_days > self.cfg.max_bar_staleness_days:
                        bad.add(key)
                        messages.append(f"{key}: stale data ({age_days:.1f}d old)")
                except (TypeError, ValueError):
                    pass  # naive/aware mismatch — skip staleness for this key

            self._last[key] = px   # baseline follows the latest good price

        return bad, messages
