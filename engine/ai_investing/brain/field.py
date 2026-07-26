"""The field state: persistent node activations + the delayed-effects pipeline.

Implements the useful core of the world-systems "master equation"
(dX/dt = Σ w·X(t−τ) − damping): each node carries an activation that

  * absorbs this cycle's propagated impacts,
  * decays exponentially toward 0 — its stable point — with a half-life
    (the balancing feedback loop: shocks fade unless refreshed), and
  * receives time-delayed contributions (τ-edges) when they mature; a matured
    effect re-enters propagation as a fresh impulse on its destination node.

This is what makes the brain remember: yesterday's tariff shock still tilts the
field today, at reduced strength, instead of vanishing with the headline. It also
doubles as the narrative/belief layer — a persistently activated node IS a live
narrative.
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timedelta, timezone

HALF_LIFE_HOURS = 36.0     # a shock loses half its strength in ~1.5 days unless refreshed
MIN_ACTIVATION = 0.01


class FieldState:
    def __init__(self, activations: dict[str, float] | None = None,
                 pending: list[dict] | None = None, updated: str = ""):
        self.activations = activations or {}
        self.pending = pending or []       # [{node, contribution, due, via, edge_type}]
        self.updated = updated

    @classmethod
    def load(cls, path: str) -> "FieldState":
        try:
            with open(path) as fh:
                d = json.load(fh)
            return cls(d.get("activations", {}), d.get("pending", []), d.get("updated", ""))
        except (OSError, json.JSONDecodeError):
            return cls()

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w") as fh:
            json.dump({"activations": self.activations, "pending": self.pending,
                       "updated": self.updated}, fh, indent=1)

    # -- dynamics --------------------------------------------------------------
    def decay(self, now: datetime) -> None:
        """Exponential decay toward the stable point since the last update."""
        if self.updated:
            try:
                prev = datetime.fromisoformat(self.updated)
                hours = max(0.0, (now - prev).total_seconds() / 3600.0)
            except ValueError:
                hours = 0.0
            factor = math.pow(0.5, hours / HALF_LIFE_HOURS)
            self.activations = {k: round(v * factor, 4) for k, v in self.activations.items()
                                if abs(v * factor) >= MIN_ACTIVATION}
        self.updated = now.isoformat()

    def absorb(self, impacts: dict[str, float]) -> None:
        """Fold this cycle's propagated impacts into the persistent activations."""
        for node, val in impacts.items():
            cur = self.activations.get(node, 0.0)
            self.activations[node] = round(max(-1.0, min(1.0, cur + val)), 4)

    # -- the τ pipeline ----------------------------------------------------------
    def mature_pending(self, now: datetime) -> dict[str, float]:
        """Pop every delayed effect whose time has come; return them as impulses
        (strongest per node) ready to re-enter propagation."""
        due: dict[str, float] = {}
        keep: list[dict] = []
        for p in self.pending:
            try:
                is_due = datetime.fromisoformat(p["due"]) <= now
            except (KeyError, ValueError):
                continue   # malformed entries are dropped
            if is_due:
                node, c = p["node"], float(p["contribution"])
                if abs(c) > abs(due.get(node, 0.0)):
                    due[node] = c
            else:
                keep.append(p)
        self.pending = keep
        return due

    def defer(self, deferred: list[dict], now: datetime) -> None:
        """Queue this cycle's delayed contributions with their due dates.
        Duplicate (node, via) pairs are refreshed, not stacked — the same story
        re-read next cycle must not double the future effect."""
        for d in deferred:
            due = (now + timedelta(days=float(d.get("delay_days", 0)))).isoformat()
            entry = {"node": d["node"], "contribution": d["contribution"], "due": due,
                     "via": d.get("via", ""), "edge_type": d.get("edge_type", "")}
            self.pending = [p for p in self.pending
                            if not (p["node"] == entry["node"] and p.get("via") == entry["via"])]
            self.pending.append(entry)
        self.pending = self.pending[-100:]   # hard cap; oldest drop first
