"""The Brain orchestrator: one `think()` per engine cycle.

    headlines ──> structured events (credibility-scored, emotion-tagged)
        credible events ──> impulses on graph nodes ──> propagation ripple
        hard macro data + events ──> regime state + market emotion + own mood
        events x scenario registry ──> fired scenarios
        everything ──> per-asset impacts for MacroLinkageSignal + data/brain.json
                       (the dashboard's Brain page renders that file)

`simulate()` runs the same pipeline on a single user-supplied headline without
persisting anything — that's the "inject a news item and watch it ripple" tool.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Optional

from ai_investing.brain import events as events_mod
from ai_investing.brain.field import FieldState
from ai_investing.brain.graph import KnowledgeGraph
from ai_investing.brain.regime import MacroRegime
from ai_investing.brain.scenarios import ScenarioRegistry
from ai_investing.brain.store import BrainStore


class Brain:
    def __init__(self, settings):
        self.settings = settings
        cfg = settings.brain
        self.graph = KnowledgeGraph.load(cfg.graph_path)
        self.regime = MacroRegime.load(cfg.regime_path)
        self.scenarios = ScenarioRegistry.load(cfg.scenarios_path)
        self.field = FieldState.load(cfg.field_path)
        self.store = BrainStore(cfg.db_path)
        self.last_new_headlines: list[dict] = []   # set by think(); consumed by news.py

    # -- the per-cycle pass ---------------------------------------------------
    def think(self, headlines: list[dict], macro: Optional[dict] = None) -> dict:
        cfg = self.settings.brain
        now = datetime.now(timezone.utc)

        # THE COST GATE: only never-digested articles reach an LLM. Everything
        # already known is remembered in brain.db and skipped. Busy cycles cap
        # the batch; the backlog stays undigested and returns next cycle.
        fresh, seen = self.store.filter_new(headlines)
        new_heads, backlog = fresh[:30], max(0, len(fresh) - 30)
        self.last_new_headlines = new_heads
        events = events_mod.extract_events(new_heads, self.graph, self.settings) if new_heads else []
        if events:
            self.store.save_events(events)
        self.store.mark_digested(new_heads)

        impulses: dict[str, float] = {}
        for ev in events:
            if ev.get("is_noise"):
                continue
            for node in ev.get("nodes", []):
                impulses[node] = max(impulses.get(node, 0.0), ev["impulse"], key=abs)

        # τ pipeline: yesterday's delayed effects that are due today re-enter as
        # impulses on their destination nodes and propagate onward from there.
        self.field.decay(now)
        for node, contrib in self.field.mature_pending(now).items():
            impulses[node] = max(impulses.get(node, 0.0), contrib, key=abs)

        impacts, trace, deferred = self.graph.propagate(impulses, max_hops=cfg.max_hops,
                                                        decay=cfg.decay)
        self.field.defer(deferred, now)
        # persistent field: today's ripple lands on top of what's still ringing
        self.field.absorb(impacts)
        asset_impacts = self.graph.asset_impacts(self.field.activations)
        fired = self.scenarios.match(events)
        for sc in fired:
            for sym, tilt in (sc.get("assets") or {}).items():
                cur = asset_impacts.setdefault(sym.upper(),
                                               {"impact": 0.0, "node": "", "label": sym, "market": ""})
                cur["impact"] = round(max(-1.0, min(1.0, cur["impact"] + tilt * sc["strength"])), 4)
                cur.setdefault("scenarios", []).append(sc["id"])

        self.regime.update(macro, events, performance=self._performance())

        # LLM-proposed edges: append with provenance, capped confidence (see graph.py)
        now = datetime.now(timezone.utc).isoformat()
        added_edges = 0
        for ev in events:
            if ev.get("is_noise"):
                continue
            for pe in (ev.get("proposed_edges") or [])[:2]:
                try:
                    if self.graph.propose_edge(pe["src"], pe["dst"], pe.get("type", "influences"),
                                               int(pe.get("sign", 1)), float(pe.get("weight", 0.3)),
                                               float(ev.get("confidence", 0.3)),
                                               ev.get("summary", ""), now):
                        added_edges += 1
                except (KeyError, TypeError, ValueError):
                    continue

        state = self._state(events, impulses, impacts, trace, asset_impacts, fired, macro)
        state["activations"] = dict(sorted(self.field.activations.items(),
                                           key=lambda kv: -abs(kv[1])))
        state["pending_effects"] = self.field.pending
        state["centrality"] = self.graph.centrality()
        state["memory"] = {**self.store.stats(), "headlines_seen_before": seen,
                           "headlines_new": len(new_heads), "backlog": backlog}
        self.store.record_node_history(state["ts"], self.field.activations)

        # the adviser reads the fresh field — every cycle, zero LLM cost
        try:
            from ai_investing.brain.adviser import advise
            state["advice"] = advise(self.settings, self, log=bool(new_heads))
        except Exception:
            state["advice"] = None

        self._persist(state, added_edges)
        return state

    def simulate(self, headline: str) -> dict:
        """Run one hypothetical headline through the brain WITHOUT persisting."""
        fake = [{"title": headline, "summary": "", "published": "", "source": "user"}]
        events = events_mod.extract_events(fake, self.graph, self.settings)
        if not events:
            # last-ditch: match nodes straight from the text so the viz shows something
            nodes = [n for n in self.graph.match_text(headline)
                     if self.graph.nodes[n].type != "asset"]
            events = [{"summary": headline, "headline": headline, "source": "user",
                       "type": "other", "nodes": nodes, "polarity": 1.0, "magnitude": 0.5,
                       "confidence": 0.3, "credibility": 0.5, "is_noise": not nodes,
                       "emotion": "neutral", "emotion_intensity": 0.0,
                       "impulse": 0.15 if nodes else 0.0, "fallback": True}]
        impulses: dict[str, float] = {}
        for ev in events:
            for node in ev.get("nodes", []):
                impulses[node] = max(impulses.get(node, 0.0), ev["impulse"], key=abs)
        cfg = self.settings.brain
        impacts, trace, deferred = self.graph.propagate(impulses, max_hops=cfg.max_hops,
                                                        decay=cfg.decay)
        fired = self.scenarios.match(events)
        state = self._state(events, impulses, impacts, trace,
                            self.graph.asset_impacts(impacts), fired, macro=None,
                            simulated=True)
        state["delayed_preview"] = deferred   # what WOULD land later (τ-edges)
        state["centrality"] = self.graph.centrality()
        return state

    # -- internals ------------------------------------------------------------
    def _state(self, events, impulses, impacts, trace, asset_impacts, fired,
               macro, simulated: bool = False) -> dict:
        ranked = sorted(impacts.items(), key=lambda kv: -abs(kv[1]))
        return {
            "ts": datetime.now(timezone.utc).isoformat(),
            "simulated": simulated,
            "events": events,
            "impulses": {k: round(v, 4) for k, v in impulses.items()},
            "impacts": {k: round(v, 4) for k, v in ranked},
            "trace": trace,
            "asset_impacts": asset_impacts,
            "scenarios_fired": fired,
            "regime": self.regime.to_dict(),
            "conviction_multiplier": self.regime.conviction_multiplier(),
            "macro": {k: v for k, v in (macro or {}).items() if not k.startswith("_")},
            "noise_events": sum(1 for e in events if e.get("is_noise")),
            "signal_events": sum(1 for e in events if not e.get("is_noise")),
        }

    def _performance(self) -> dict:
        """Own-performance inputs for mood: drawdown (history.json) and portfolio
        fragility = exposure × concentration (state.json positions)."""
        out: dict = {}
        data_dir = os.path.dirname(os.path.abspath(self.settings.state_path))
        try:
            with open(os.path.join(data_dir, "history.json")) as fh:
                pts = json.load(fh).get("points", [])[-90:]
            eq = [p["equity"] for p in pts if p.get("equity")]
            if eq:
                peak = max(eq)
                out["drawdown"] = max(0.0, (peak - eq[-1]) / peak) if peak > 0 else 0.0
        except (OSError, json.JSONDecodeError, KeyError):
            pass
        try:
            with open(self.settings.state_path) as fh:
                st = json.load(fh)
            equity = float(st.get("equity", 0.0))
            values = [abs(float(p.get("value", 0.0))) for p in st.get("positions", [])]
            gross = sum(values)
            if equity > 0 and gross > 0:
                weights = [v / gross for v in values]
                hhi = sum(w * w for w in weights)          # 1/N (diversified) .. 1 (all-in)
                exposure = gross / equity                   # gross leverage
                out["fragility"] = round(min(1.0, exposure * (hhi ** 0.5)), 3)
            else:
                out["fragility"] = 0.0
        except (OSError, json.JSONDecodeError, ValueError):
            pass
        return out

    def _persist(self, state: dict, added_edges: int) -> None:
        cfg = self.settings.brain
        try:
            self.regime.save(cfg.regime_path)
            self.scenarios.save(cfg.scenarios_path)
            self.field.save(cfg.field_path)
            if added_edges:
                self.graph.save(cfg.graph_path)
            os.makedirs(os.path.dirname(os.path.abspath(cfg.state_path)), exist_ok=True)
            with open(cfg.state_path, "w") as fh:
                json.dump(state, fh, indent=1)
        except OSError:
            pass
