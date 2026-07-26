"""Human-in-the-loop gate for NEW position entries.

When TRADE_APPROVAL is on, the engine does not open a position on its own:
it files a *proposal* here and pushes it to you on Telegram with
approve / skip buttons. The entry executes only after you approve (sized
fresh at the next cycle's prices). Protective exits, stops, circuit-breaker
flattens, and your blocklist exits are NEVER gated — safety doesn't wait
for a human.

Proposals expire after `ttl_hours` (market context goes stale); a rejected
proposal also blocks re-asking for the same symbol+side until it expires,
so the bot doesn't nag every five minutes.

The file (data/proposals.json) is shared state between the engine loop and
the chat bot process — both read-modify-write whole-file, which is fine at
this scale (a handful of proposals, two slow writers).
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ProposalBook:
    def __init__(self, path: str, ttl_hours: float = 12.0):
        self.path = path
        self.ttl_hours = ttl_hours

    # -- storage ---------------------------------------------------------------
    def _load(self) -> list[dict]:
        try:
            with open(self.path) as fh:
                return json.load(fh).get("proposals", [])
        except (OSError, json.JSONDecodeError):
            return []

    def _save(self, proposals: list[dict]) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        with open(self.path, "w") as fh:
            json.dump({"proposals": proposals}, fh, indent=1)

    @staticmethod
    def _pid(symbol: str, side: str, ts: str) -> str:
        return hashlib.sha1(f"{symbol}|{side}|{ts}".encode()).hexdigest()[:8]

    def _fresh(self, p: dict) -> bool:
        try:
            return datetime.fromisoformat(p["expires"]) > _now()
        except (KeyError, ValueError):
            return False

    # -- api -------------------------------------------------------------------
    def prune(self) -> None:
        self._save([p for p in self._load() if self._fresh(p)])

    def get(self, symbol: str, side: str, horizon: str = "short") -> dict | None:
        """Latest unexpired proposal for this symbol+side in one book
        ('short' = trading book, 'long' = investing book)."""
        for p in reversed(self._load()):
            if (p["symbol"] == symbol and p["side"] == side
                    and p.get("horizon", "short") == horizon and self._fresh(p)):
                return p
        return None

    def propose(self, symbol: str, side: str, qty: float, price: float,
                reason: str = "", extra: dict | None = None) -> dict:
        """File a pending proposal (idempotent per symbol+side+book while fresh).
        `extra` carries the plain-language explanation shown to the human."""
        existing = self.get(symbol, side, (extra or {}).get("horizon", "short"))
        if existing:
            return existing
        ts = _now().isoformat()
        p = {"id": self._pid(symbol, side, ts), "symbol": symbol, "side": side,
             "qty": round(qty, 6), "price": round(price, 4), "reason": reason[:300],
             "ts": ts, "expires": (_now() + timedelta(hours=self.ttl_hours)).isoformat(),
             "status": "pending", **(extra or {})}
        proposals = self._load()
        proposals.append(p)
        self._save(proposals)
        return p

    def decide(self, pid: str, approved: bool) -> dict | None:
        """Record the human's tap. Returns the updated proposal, or None if unknown/expired."""
        proposals = self._load()
        for p in proposals:
            if p["id"] == pid and self._fresh(p) and p["status"] == "pending":
                p["status"] = "approved" if approved else "rejected"
                p["decided"] = _now().isoformat()
                self._save(proposals)
                return p
        return None

    def consume(self, pid: str) -> None:
        """Remove a proposal after its entry executed."""
        self._save([p for p in self._load() if p["id"] != pid])

    def pending(self) -> list[dict]:
        return [p for p in self._load() if p["status"] == "pending" and self._fresh(p)]
