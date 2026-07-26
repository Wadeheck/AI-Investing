"""Anticipatory scenario registry: pre-committed "if X then Y" reasoning.

Each scenario names trigger nodes + a required shock direction. When a credible
event shocks a trigger node in the registered direction, the scenario FIRES —
the implication is already reasoned out, so the reaction is immediate instead of
being re-derived from scratch under time pressure. Fired scenarios boost the
MacroLinkageSignal on their named assets.

The registry is a JSON file you can edit by hand; the seed formalizes hypotheses
already researched rather than inventing new ones.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

SEED_SCENARIOS = [
    {"id": "pboc-cut-icbc-nim", "status": "watching",
     "trigger": {"nodes": ["pboc_rate"], "direction": -1},
     "implication": "further PBOC easing compresses ICBC NIM",
     "assets": {"1398.HK": -0.5}},
    {"id": "china-stimulus-consumer", "status": "watching",
     "trigger": {"nodes": ["china_stimulus"], "direction": 1},
     "implication": "real stimulus lifts China consumer names (Moutai, Meituan, Alibaba)",
     "assets": {"600519.SS": 0.6, "3690.HK": 0.5, "9988.HK": 0.4}},
    {"id": "tariff-escalation-catl", "status": "watching",
     "trigger": {"nodes": ["us_china_tariffs"], "direction": 1},
     "implication": "tariff escalation threatens CATL/BYD overseas expansion",
     "assets": {"300750.SZ": -0.5, "1211.HK": -0.4}},
    {"id": "chip-controls-nvda", "status": "watching",
     "trigger": {"nodes": ["china_export_controls"], "direction": 1},
     "implication": "new chip curbs cut NVDA China revenue",
     "assets": {"NVDA": -0.4}},
    {"id": "boj-hike-risk-off", "status": "watching",
     "trigger": {"nodes": ["yen_carry"], "direction": 1},
     "implication": "BOJ tightening unwinds carry trades; broad risk-off, crypto hit first",
     "assets": {"BTC/USD": -0.4, "ETH/USD": -0.4, "XLK": -0.3}},
    {"id": "fed-cut-gold-crypto", "status": "watching",
     "trigger": {"nodes": ["fed_rate"], "direction": -1},
     "implication": "Fed easing weakens USD, lifts gold and crypto liquidity",
     "assets": {"GLD": 0.4, "BTC/USD": 0.4}},
    {"id": "gulf-escalation-oil", "status": "watching",
     "trigger": {"nodes": ["geopolitical_tension"], "direction": 1},
     "implication": "Middle East escalation spikes oil and gold, sinks risk assets",
     "assets": {"USO": 0.5, "GLD": 0.4, "XLE": 0.4}},
]

_MIN_IMPULSE = 0.08   # ignore trigger shocks weaker than this


class ScenarioRegistry:
    def __init__(self, scenarios: list[dict]):
        self.scenarios = scenarios

    @classmethod
    def load(cls, path: str) -> "ScenarioRegistry":
        if not os.path.exists(path):
            reg = cls([dict(s) for s in SEED_SCENARIOS])
            reg.save(path)
            return reg
        try:
            with open(path) as fh:
                return cls(json.load(fh).get("scenarios", []))
        except (OSError, json.JSONDecodeError):
            return cls([dict(s) for s in SEED_SCENARIOS])

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w") as fh:
            json.dump({"scenarios": self.scenarios}, fh, indent=2)

    def match(self, events: list[dict]) -> list[dict]:
        """Return scenarios fired by this cycle's credible events (and stamp them)."""
        fired = []
        now = datetime.now(timezone.utc).isoformat()
        for sc in self.scenarios:
            if sc.get("status") == "retired":
                continue
            trig = sc.get("trigger", {})
            want_dir = trig.get("direction", 0)
            for ev in events:
                if ev.get("is_noise"):
                    continue
                overlap = set(trig.get("nodes", [])) & set(ev.get("nodes", []))
                if not overlap or abs(ev.get("impulse", 0.0)) < _MIN_IMPULSE:
                    continue
                if want_dir and (ev["impulse"] > 0) != (want_dir > 0):
                    continue
                fired.append({**sc, "fired_by": ev.get("summary", ""), "fired_at": now,
                              "strength": round(abs(ev["impulse"]), 3)})
                sc["last_fired"] = now
                break
        return fired
