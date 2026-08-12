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
        # evidence weighting: saved edge-calibration verdicts adjust edge
        # confidence in memory (supported x1.15, contradicted x0.5)
        try:
            from ai_investing.brain import calibration
            self.calibration_summary = calibration.apply(settings, self.graph)
        except Exception:
            self.calibration_summary = {}

    def _regime_dials(self) -> dict:
        """The regime snapshot propagate() needs for gates + crisis convergence."""
        r = self.regime
        return {"risk_appetite": r.risk_appetite, "inflation_trend": r.inflation_trend,
                "rate_trajectory": r.rate_trajectory, "dollar_trend": r.dollar_trend,
                "fear": r.fear, "greed": r.greed}

    # -- the per-cycle pass ---------------------------------------------------
    def think(self, headlines: list[dict], macro: Optional[dict] = None,
              price_moves: Optional[dict] = None) -> dict:
        cfg = self.settings.brain
        now = datetime.now(timezone.utc)

        # THE COST GATE: only never-digested articles reach an LLM. Everything
        # already known is remembered in brain.db and skipped. Busy cycles cap
        # the batch; the backlog stays undigested and returns next cycle.
        fresh, seen = self.store.filter_new(headlines)
        new_heads, backlog = fresh[:30], max(0, len(fresh) - 30)
        self.last_new_headlines = new_heads
        events = events_mod.extract_events(new_heads, self.graph, self.settings) if new_heads else []

        # YOUR VERDICTS, APPLIED BEFORE ANYTHING PROPAGATES (brain/consult.py).
        # A reading you disagreed with sends a damped impulse into the graph, so
        # the tap moves node activations, asset impacts, conviction and position
        # size on THIS cycle — not in a weekly report. Returns the overrides the
        # runner must tell you about; damping itself is deliberately silent.
        self.consult_overrides: list[dict] = []
        self.consult_asks: list[dict] = []
        if events and getattr(cfg, "consult_enabled", True):
            try:
                from ai_investing.brain import consult
                self.consult_overrides = consult.damp(events, self.settings)
                self.consult_asks = consult.harvest(events, self.settings, new_heads)
            except Exception as exc:      # degrade, never silently
                print(f"  [consult] skipped: {type(exc).__name__}: {exc}")

        if events:
            self.store.save_events(events)
        self.store.mark_digested(new_heads)

        impulses: dict[str, float] = {}
        for ev in events:
            if ev.get("is_noise"):
                continue
            for node in ev.get("nodes", []):
                impulses[node] = max(impulses.get(node, 0.0), ev["impulse"], key=abs)

        # price action IS world state: once a day the market's own moves shock
        # their asset nodes and ripple through the web like any other event —
        # a supplier crashing perturbs its customers' nodes, not just its own.
        for sym, ret in (price_moves or {}).items():
            if abs(ret) < 0.01:
                continue
            node = self.graph.node_for_symbol(sym)
            if node is None:
                continue
            pulse = max(-0.4, min(0.4, 3.0 * ret))
            impulses[node.id] = max(impulses.get(node.id, 0.0), pulse, key=abs)

        # τ pipeline: yesterday's delayed effects that are due today re-enter as
        # impulses on their destination nodes and propagate onward from there.
        node_types = {nid: n.type for nid, n in self.graph.nodes.items()}
        self.field.decay(now, node_types,
                         anchors={**self._anchors(macro), **self._valuation_anchors(),
                                  **self._crypto_anchors()})
        for node, contrib in self.field.mature_pending(now).items():
            impulses[node] = max(impulses.get(node, 0.0), contrib, key=abs)

        # regime BEFORE propagation: the gates and crisis-convergence must see
        # TODAY'S dials (a hot CPI print this morning should flip the Fed edge
        # this cycle, not next) — EMA smoothing already prevents whiplash
        self.regime.update(macro, events, performance=self._performance())

        impacts, trace, deferred = self.graph.propagate(impulses, max_hops=cfg.max_hops,
                                                        decay=cfg.decay,
                                                        regime=self._regime_dials())
        self.field.defer(deferred, now)
        # FRESH SHOCK (event sleeve, 2026-08-02): what TODAY's news alone says,
        # before it is absorbed into the accumulated field. The other books
        # trade the field (conviction that builds); the event sleeve trades
        # this — the same brain read at a faster clock.
        self._shock_assets = self.graph.asset_impacts(impacts) if impacts else {}
        # persistent field: today's ripple lands on top of what's still ringing
        self.field.absorb(impacts)
        asset_impacts = self.graph.asset_impacts(self.field.activations)
        # sense of scale + what's already priced: impacts become expected moves
        # (impact x vol x sqrt(h) x calibration gain), then get discounted by how
        # far the tape already ran in the signal's direction
        try:
            from ai_investing.brain.priced_in import priced_in_scores
            from ai_investing.brain.scale import enrich_with_scale
            vols = enrich_with_scale(asset_impacts, self.settings, self.graph)
            priced_in_scores(self.settings, asset_impacts, vols)
        except Exception:
            pass
        fired = self.scenarios.match(events)
        for sc in fired:
            for sym, tilt in (sc.get("assets") or {}).items():
                cur = asset_impacts.setdefault(sym.upper(),
                                               {"impact": 0.0, "node": "", "label": sym, "market": ""})
                cur["impact"] = round(max(-1.0, min(1.0, cur["impact"] + tilt * sc["strength"])), 4)
                cur.setdefault("scenarios", []).append(sc["id"])

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

        # Deal wiring: digested deals grow the relationship graph itself —
        # private hubs auto-created, owns/supplies legs accrued — so money
        # circles surface structurally without per-company code (brain/deals.py).
        try:
            from ai_investing.brain import deals as deals_mod
            deal_report = deals_mod.apply_deals(self.graph, events, ts=now)
        except Exception:
            deal_report = {}

        # Integrity layer: hardcoded patterns (auditor walks, withdrawal halts…)
        # + the digester's open-ended `integrity` judgments (novel mechanisms).
        # Both merge into decaying per-asset flags that override good numbers.
        try:
            from ai_investing.brain import integrity as integ
            integ.scan_headlines(new_heads, self.graph, self.settings)
            integ.absorb_llm_integrity(events, self.graph, self.settings)
            self._integrity = integ.current_flags(self.settings)
        except Exception:
            self._integrity = {}

        # The bullshit/emotion layer: WHERE the crowd is scared or greedy
        # (per-node emotion field), WHO is paying to excite a name (campaign
        # pressure + pump lifecycle), whether sources/emotions have EARNED
        # trust (outcome scoring -> learned source trust + measured contrarian
        # coefficients), and the OFFENSE composed from all of it (buy panic in
        # clean value / fade euphoric froth / tilt to fraud beneficiaries).
        emotions, campaigns_report, contrarian_report = {}, {}, {}
        layer_error = ""
        try:
            from ai_investing.brain import calibration as edge_calibration
            from ai_investing.brain import campaign as campaign_mod
            from ai_investing.brain import contrarian as contrarian_mod
            from ai_investing.brain import emotion_calibration
            from ai_investing.brain import emotion_field
            from ai_investing.brain import source_learning
            now_dt = datetime.now(timezone.utc)
            emotions = emotion_field.update(self.settings, events, now_dt)
            campaigns_report = campaign_mod.update(self.settings, self.store,
                                                   self.graph, now_dt)
            # evidence loops (cheap idempotent batches, all local data): when
            # fresh outcomes land, EVERYTHING recalibrates — source trust, the
            # emotion coefficients, and the edge/path calibrator itself, whose
            # new verdicts re-weight the live graph immediately (not next boot)
            if source_learning.score_events(self.settings, self.graph):
                source_learning.learn(self.settings)
                emotion_calibration.calibrate(self.settings)
                cal_report = edge_calibration.calibrate(self.settings, self.graph)
                self.graph.set_calibration(
                    edge_calibration.factors_from_report(cal_report))
                self.calibration_summary = {
                    "generated": cal_report.get("generated"),
                    "gain": cal_report.get("gain", 1.0),
                    **(cal_report.get("summary") or {})}
            contrarian_report = contrarian_mod.compose(
                self.settings, self.graph, self.field.activations,
                emotions, campaigns_report)
        except Exception as exc:   # degrade gracefully but NEVER silently
            layer_error = f"{type(exc).__name__}: {exc}"

        state = self._state(events, impulses, impacts, trace, asset_impacts, fired, macro)
        if deal_report.get("nodes_created") or deal_report.get("edges_added") \
                or deal_report.get("edges_corroborated"):
            state["deal_wiring"] = {k: deal_report[k] for k in
                                    ("nodes_created", "edges_added", "edges_corroborated")}
        state["activations"] = dict(sorted(self.field.activations.items(),
                                           key=lambda kv: -abs(kv[1])))
        state["pending_effects"] = self.field.pending
        state["centrality"] = self.graph.centrality()
        state["memory"] = {**self.store.stats(), "headlines_seen_before": seen,
                           "headlines_new": len(new_heads), "backlog": backlog}
        state["circular_financing"] = self.graph.detect_circular_financing()
        state["integrity_flags"] = getattr(self, "_integrity", {})
        state["shock_assets"] = getattr(self, "_shock_assets", {})   # fresh-shock read for the event sleeve
        # what the runner must put in front of you: new readings to judge, and
        # any reading that outvoted a previous 👎 (brain/consult.py)
        state["consult_asks"] = getattr(self, "consult_asks", [])
        state["consult_overrides"] = getattr(self, "consult_overrides", [])
        state["calibration"] = self.calibration_summary   # proof-of-reflexes status
        if emotions:
            state["emotion_field"] = dict(sorted(
                emotions.items(), key=lambda kv: -max(kv[1].get("fear", 0),
                                                      kv[1].get("greed", 0)))[:20])
        if campaigns_report:
            state["campaigns"] = campaigns_report
        if contrarian_report:
            state["contrarian"] = {k: contrarian_report.get(k) for k in
                                   ("buys", "watching", "fades", "beneficiaries",
                                    "coefficients")}
        if layer_error:
            state["layer_error"] = layer_error   # visible on the dashboard, not swallowed
        try:                    # standing stress report (risk-committee view)
            from ai_investing.brain.stress import run_stress
            state["stress"] = run_stress(self.graph, top_n=5)
        except Exception:
            pass
        self.store.record_node_history(state["ts"], self.field.activations)

        # the adviser reads the fresh field — every cycle, zero LLM cost
        try:
            from ai_investing.brain.adviser import advise
            state["advice"] = advise(self.settings, self, log=bool(new_heads))
        except Exception:
            state["advice"] = None

        self._persist(state, added_edges + len(deal_report.get("nodes_created", []))
                      + len(deal_report.get("edges_added", []))
                      + len(deal_report.get("edges_corroborated", [])))
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
                                                        decay=cfg.decay,
                                                        regime=self._regime_dials())
        fired = self.scenarios.match(events)
        asset_impacts = self.graph.asset_impacts(impacts)
        try:
            from ai_investing.brain.priced_in import priced_in_scores
            from ai_investing.brain.scale import enrich_with_scale
            vols = enrich_with_scale(asset_impacts, self.settings, self.graph)
            priced_in_scores(self.settings, asset_impacts, vols)
        except Exception:
            pass
        state = self._state(events, impulses, impacts, trace,
                            asset_impacts, fired, macro=None,
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

    @staticmethod
    def _anchors(macro: Optional[dict]) -> dict[str, float]:
        """Translate hard indicator readings into node resting levels in [-1, 1].
        Each formula is (reading − equilibrium) / scale, matching the node's
        documented stable point — data anchors the field, news moves around it."""
        m = macro or {}
        a: dict[str, float] = {}

        def put(node: str, val, eq: float, scale: float, invert: bool = False):
            if val is None:
                return
            x = (float(val) - eq) / scale
            a[node] = round(max(-1.0, min(1.0, -x if invert else x)), 4)

        put("us_inflation", m.get("cpi_yoy"), 2.0, 3.0)          # Fed target 2%
        put("fed_rate", m.get("fed_funds"), 3.0, 3.0)            # neutral ~3%
        put("us_employment", m.get("unemployment"), 4.2, 2.0, invert=True)  # low U = hot labor
        put("us_gov_debt", m.get("us_debt_gdp"), 100.0, 40.0)    # % GDP above 100 = strained
        put("money_supply", m.get("m2_yoy"), 5.0, 6.0)           # nominal-GDP-ish growth
        put("ecb_policy", m.get("eu_cpi_yoy"), 2.0, 2.5)         # hot HICP = hawkish ECB
        put("china_consumer", m.get("cn_cpi_yoy"), 1.5, 2.5)     # deflation = weak demand
        put("yen_carry", m.get("jp_cpi_yoy"), 2.0, 2.5)          # hot JP CPI = BOJ normalizes
        # stablecoin supply growth: ~+1%/30d is cruise; +5% = strong inflow,
        # sustained contraction = liquidity leaving crypto's rails (bear tell)
        put("crypto_liquidity", m.get("stablecoin_chg_30d"), 0.01, 0.04)
        # Same observable, second consequence (seed v26). Stablecoin float is both
        # a crypto-flow tell AND a dollar aggregate whose reserve leg bids T-bills
        # and whose float competes with bank deposits. Those legs act in a crypto
        # bear market too, so they need their own node. Anchored from the same
        # series but DELIBERATELY not edged into crypto_liquidity — that node has
        # its own anchor on this series, and an edge would double-count it.
        put("stablecoin_supply", m.get("stablecoin_chg_30d"), 0.01, 0.04)
        return a

    def _valuation_anchors(self) -> dict[str, float]:
        """Fundamentals as resting levels for ASSET nodes — valuation lives IN
        the web, not beside it. A stretched multiple is a standing downward
        pull on that node (a bubble node 'wants' to fall); cheap-and-healthy
        rests positive; heavy debt or negative margins drag. News and ripples
        move the node around this resting level, exactly like macro anchors."""
        data_dir = os.path.dirname(os.path.abspath(self.settings.state_path))
        try:
            with open(os.path.join(data_dir, "fundamentals.json")) as fh:
                fund = json.load(fh)
        except (OSError, json.JSONDecodeError):
            return {}
        from ai_investing.brain.bubble import _valuation_stretch
        # multi-year trajectory (fundamentals_history.py): the SNAPSHOT says
        # cheap/expensive today; the trajectory says whether the business is
        # compounding or decaying — both belong in the resting level.
        try:
            from ai_investing.data.fundamentals_history import health_scores
            health = health_scores(self.settings)
        except Exception:
            health = {}
        a: dict[str, float] = {}
        for sym, f in fund.items():
            node = self.graph.node_for_symbol(sym)
            if node is None:
                continue
            v = -0.35 * _valuation_stretch(f)
            pe, margin, de = f.get("trailingPE"), f.get("profitMargins"), f.get("debtToEquity")
            if pe and 0 < pe < 12 and (margin or 0) > 0.05:
                v += 0.2                       # cheap and actually profitable
            if (de and de > 250) or (margin is not None and margin < 0):
                v -= 0.15                      # balance-sheet / profitability stress
            v += 0.15 * health.get(sym, 0.0)   # multi-year FCF/debt/revenue trend
            if abs(v) >= 0.05:
                a[node.id] = round(max(-0.4, min(0.4, v)), 4)
        # trajectory-only anchors for symbols the snapshot cache hasn't covered
        for sym, h in health.items():
            node = self.graph.node_for_symbol(sym)
            if node is None or node.id in a or sym in fund or abs(h) < 0.35:
                continue
            a[node.id] = round(max(-0.4, min(0.4, 0.15 * h)), 4)
        # circular-financing haircut: participants in a detected money
        # round-trip get a STANDING discount — their statements (and therefore
        # the snapshot/trajectory scores above) are flattered by revenue that
        # is partly the same dollar counted at every stop of the circle.
        try:
            haircut: dict[str, float] = {}
            for lp in self.graph.detect_circular_financing():
                sev = float(lp.get("severity", 0.3))
                for nid in lp.get("participants", []):
                    # severity-scaled: a circle is only as fake as its thinnest leg
                    haircut[nid] = haircut.get(nid, 0.0) + 0.05 + 0.25 * sev
            for nid, h in haircut.items():
                if self.graph.nodes.get(nid) is None:
                    continue
                a[nid] = round(max(-0.4, a.get(nid, 0.0) - min(0.25, h)), 4)
        except Exception:
            pass
        # undervaluation: cheap+honest+resilient names get a positive resting
        # pull (value_scanner vetoes traps via the integrity/accrual layers;
        # the trend gates still decide WHEN — this only says WHAT is mispriced)
        try:
            from ai_investing.data.value_scanner import stock_value_scores
            for sym, r in stock_value_scores(self.settings).items():
                if r["score"] <= 0:
                    continue
                node = self.graph.node_for_symbol(sym)
                if node is not None:
                    a[node.id] = round(max(-0.4, min(0.4, a.get(node.id, 0.0)
                                                     + 0.25 * r["score"])), 4)
        except Exception:
            pass
        # expectations & ownership tilts (cache-only reads; refreshed by their
        # own CLIs/cycles): revision momentum + earnings surprises, and insider
        # cluster-buys / crowded shorts — small weights, the banker's edges
        try:
            from ai_investing.data.estimates import expectation_scores
            from ai_investing.data.ownership import ownership_scores
            for sym, sc in expectation_scores(self.settings).items():
                node = self.graph.node_for_symbol(sym)
                if node is not None and abs(sc) >= 0.1:
                    a[node.id] = round(max(-0.4, min(0.4, a.get(node.id, 0.0) + 0.1 * sc)), 4)
            for sym, sc in ownership_scores(self.settings).items():
                node = self.graph.node_for_symbol(sym)
                if node is not None and abs(sc) >= 0.1:
                    a[node.id] = round(max(-0.4, min(0.4, a.get(node.id, 0.0) + 0.1 * sc)), 4)
        except Exception:
            pass
        # integrity flags OVERRIDE good numbers: when the books themselves are
        # in doubt (auditor walked, withdrawals halted, fraud probe, or a novel
        # mechanism the digester judged), the fundamentals above are exactly
        # what can't be trusted — force the resting level negative.
        try:
            from ai_investing.brain.integrity import current_flags
            for nid, f in current_flags(self.settings).items():
                if self.graph.nodes.get(nid) is None or f["severity"] < 0.15:
                    continue
                a[nid] = round(min(a.get(nid, 0.0), -0.4 * f["severity"]), 4)
        except Exception:
            pass
        return a

    def _crypto_anchors(self) -> dict[str, float]:
        """Crypto-native signals as resting levels on the crypto asset nodes:
        extreme fear/greed (contrarian) and stretched funding (crowded
        leverage wants to unwind). Live values refreshed every ~6h, free."""
        try:
            from ai_investing.research.crypto_signals import refresh_live
            cs = refresh_live()
            a: dict[str, float] = {}
            fng_days = sorted(cs.get("fng", {}).items())
            fng = int(fng_days[-1][1]) if fng_days else None
            for sym, series in (cs.get("funding") or {}).items():
                node = self.graph.node_for_symbol(sym)
                if node is None or not series:
                    continue
                vals = [v for _, v in sorted(series.items())][-90:]
                latest = vals[-1]
                mean = sum(vals) / len(vals)
                sd = (sum((v - mean) ** 2 for v in vals) / max(1, len(vals) - 1)) ** 0.5
                z = (latest - mean) / sd if sd > 1e-12 else 0.0
                v = 0.0
                if abs(z) > 1.0:
                    v -= max(-1.0, min(1.0, z / 2.5)) * 0.15   # crowded longs = drag
                if fng is not None and (fng <= 20 or fng >= 75):
                    v += 0.12 if fng <= 20 else -0.12          # contrarian emotion
                if abs(v) >= 0.05:
                    a[node.id] = round(max(-0.3, min(0.3, v)), 4)
            # value-zone tilt: deep below long-run trend + usage/price
            # divergence + extreme fear (see value_scanner) — capped small;
            # the winter gate still times the entry
            try:
                from ai_investing.data.value_scanner import crypto_value_scores
                for sym, r in crypto_value_scores(self.settings).items():
                    node = self.graph.node_for_symbol(sym)
                    if node is not None and r["score"] > 0:
                        a[node.id] = round(max(-0.3, min(0.3, a.get(node.id, 0.0)
                                                         + 0.2 * r["score"])), 4)
            except Exception:
                pass
            return a
        except Exception:
            return {}

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
