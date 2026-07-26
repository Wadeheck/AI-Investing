"""The Adviser: turn the brain's field into a ranked, explained trade list.

    score(asset) = field impact reaching the asset (persistent activations)
                 + latest formula conviction (state.json decisions, if present)
                 + fired-scenario boosts (last 48h)
                 + regime fit (risk-off tilts defensives up, high-beta down)
                 − crowding/hype penalty (noise events touching the asset's wiring)
    all × the brain's mood conviction multiplier.

Every recommendation carries its CAUSAL CHAIN — the strongest activated path
through the graph into the asset — plus what would invalidate it and how fresh
the driving events are. No LLM calls: this is pure graph + arithmetic, so it
runs every cycle for free.

Honest framing: this is decision support feeding your views, not an autonomous
trader. Orders still flow through the formula, risk caps, and safety stack, and
every list is frozen in advice_log so the adviser's hit-rate can be measured.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

DEFENSIVE = {"GLD", "XLP", "TLT"}
HIGH_BETA = {"BTC/USD", "ETH/USD", "SOL/USD", "XLK", "NVDA", "TSLA"}

W_FIELD, W_FORMULA, W_SCENARIO, W_REGIME, W_CROWD = 1.0, 0.6, 0.5, 0.25, 0.6
MIN_SCORE = 0.03


def _formula_views(settings) -> dict[str, float]:
    """Latest per-symbol conviction from the engine's last cycle (θ·φ squashed)."""
    try:
        with open(settings.state_path) as fh:
            decisions = json.load(fh).get("decisions", [])
        return {d["symbol"].upper(): float(d.get("score", 0.0)) for d in decisions}
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return {}


def _scenario_boosts(brain, now: datetime) -> dict[str, float]:
    boosts: dict[str, float] = {}
    cutoff = (now - timedelta(hours=48)).isoformat()
    for sc in brain.scenarios.scenarios:
        if (sc.get("last_fired") or "") < cutoff:
            continue
        for sym, tilt in (sc.get("assets") or {}).items():
            boosts[sym.upper()] = boosts.get(sym.upper(), 0.0) + tilt
    return boosts


def _crowding(brain, hours: float = 48.0) -> dict[str, float]:
    """Noise pressure per node: how much manipulation-flagged flow touched the
    wiring recently. An asset pumped by noise gets its LONG score haircut."""
    pressure: dict[str, float] = {}
    try:
        noisy = [e for e in brain.store.recent_events(hours, signal_only=False)
                 if e.get("is_noise")]
    except Exception:
        return pressure
    for e in noisy:
        for n in e.get("nodes", []):
            pressure[n] = pressure.get(n, 0.0) + abs(e.get("magnitude", 0.0)) * 0.5
    return pressure


def _chain(graph, activations: dict[str, float], asset_node: str, depth: int = 3) -> list[str]:
    """Greedy strongest activated path INTO the asset — the human-readable 'why'."""
    adj = graph._adjacency()
    incoming: dict[str, list] = {}
    for src, nbrs in adj.items():
        for dst, sign, w, edge in nbrs:
            incoming.setdefault(dst, []).append((src, sign, w))
    path, cur, seen = [], asset_node, {asset_node}
    for _ in range(depth):
        cands = [(src, sign, w, abs(activations.get(src, 0.0)) * w)
                 for src, sign, w in incoming.get(cur, []) if src not in seen]
        if not cands:
            break
        src, sign, w, strength = max(cands, key=lambda c: c[3])
        if strength < 0.01:
            break
        path.append(src)
        seen.add(src)
        cur = src
    path.reverse()
    labels = []
    for nid in path + [asset_node]:
        n = graph.nodes.get(nid)
        a = activations.get(nid, 0.0)
        arrow = "↑" if a > 0.01 else ("↓" if a < -0.01 else "")
        labels.append(f"{n.label if n else nid} {arrow}".strip())
    return labels


def advise(settings, brain, log: bool = True) -> dict:
    """Rank the top-N trades from the current field. Pure computation, no LLM."""
    now = datetime.now(timezone.utc)
    graph, field = brain.graph, brain.field
    activations = field.activations
    asset_impacts = graph.asset_impacts(activations)
    formula = _formula_views(settings)
    boosts = _scenario_boosts(brain, now)
    crowding = _crowding(brain)
    mood_mult = brain.regime.conviction_multiplier()
    risk_off = brain.regime.risk_appetite < -0.2
    risk_on = brain.regime.risk_appetite > 0.2
    # circular-financing haircut: revenue booked around an owns+supplies loop is
    # partly the same dollar twice — never take that growth story at face value
    in_loop: set[str] = set()
    for loop in graph.detect_circular_financing():
        in_loop.add(loop["investor"])
        in_loop.add(loop["counterparty"])

    # learned trust: symbols where past field-driven calls kept missing get
    # listened to less (scorecard EMA, r ∈ [0.5, 1.4]); bubble froth haircuts longs
    from ai_investing.brain.scorecard import reliability_weights
    from ai_investing.brain.bubble import bubble_scores
    rel = reliability_weights(settings)
    try:
        froth = bubble_scores(settings).get("symbols", {})
    except Exception:
        froth = {}

    rows = []
    symbols = set(asset_impacts) | set(boosts) | set(formula)
    for sym in symbols:
        node = graph.node_for_symbol(sym)
        if node is None or node.type != "asset":
            continue
        impact = asset_impacts.get(sym, {}).get("impact", 0.0)
        score = W_FIELD * impact * rel.get(sym, 1.0)
        score += W_FORMULA * formula.get(sym, 0.0)
        score += W_SCENARIO * boosts.get(sym, 0.0)
        if risk_off:
            score += W_REGIME * (0.5 if sym in DEFENSIVE else (-0.5 if sym in HIGH_BETA else 0.0))
        elif risk_on:
            score += W_REGIME * (0.4 if sym in HIGH_BETA else 0.0)
        # crowding: never BUY what noise is pumping (short/fade is unaffected)
        crowd = sum(p for n, p in crowding.items()
                    if n == node.id or any(e.src == node.id and e.dst == n for e in graph.edges))
        if score > 0 and crowd > 0:
            score -= W_CROWD * min(score, crowd)
        circular = node.id in in_loop
        if circular and score > 0:
            score *= 0.6    # 40% haircut on long conviction inside a financing circle
        b = froth.get(sym, 0.0)
        if b >= 0.4 and score > 0:
            score *= max(0.4, 1.0 - 0.6 * b)   # don't chase what already smells like a bubble
        score *= mood_mult
        if abs(score) < MIN_SCORE:
            continue
        chain = _chain(graph, activations, node.id)
        root = chain[0] if len(chain) > 1 else None
        rows.append({
            "symbol": sym, "market": node.market, "label": node.label,
            "direction": "long" if score > 0 else "short_or_avoid",
            "score": round(score, 4),
            "weight_suggestion": round(min(settings.risk.max_position_weight,
                                           abs(score) * 0.3) * mood_mult, 4),
            "chain": " → ".join(chain) if len(chain) > 1 else "formula/scenario driven",
            "invalidation": f"reversal of: {root}" if root else "formula conviction fading",
            "drivers": {"field": round(impact, 3), "formula": round(formula.get(sym, 0.0), 3),
                        "scenarios": round(boosts.get(sym, 0.0), 3),
                        "crowding_penalty": round(crowd, 3)},
            **({"circular_financing": True} if circular else {}),
        })
    rows.sort(key=lambda r: -abs(r["score"]))
    top = rows[:settings.brain.advise_top_n]
    for i, r in enumerate(top, 1):
        r["rank"] = i

    advice = {
        "ts": now.isoformat(),
        "trades": top,
        "considered": len(rows),
        "mood": brain.regime.mood_label,
        "conviction_multiplier": mood_mult,
        "regime_note": ("risk-off tilt: defensives favored" if risk_off
                        else "risk-on tilt: beta favored" if risk_on else "neutral regime"),
    }
    try:
        os.makedirs(os.path.dirname(os.path.abspath(settings.brain.advice_path)), exist_ok=True)
        with open(settings.brain.advice_path, "w") as fh:
            json.dump(advice, fh, indent=1)
        if log and top:
            brain.store.log_advice(advice)
    except OSError:
        pass
    return advice
