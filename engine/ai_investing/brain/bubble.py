"""🫧 The bubble indicator — one explicit number instead of scattered hints.

A bubble has a signature: prices justified by stories rather than earnings
(valuation stretch), money moving in circles between the players (circular
financing), and a crowd leaning hard one way (field heat + greed). Each
ingredient already lives somewhere in the system; this module combines them
into per-symbol and per-cluster scores in [0, 1]:

  bubble(sym) = 0.45·valuation_stretch + 0.30·circular_financing + 0.25·field_heat

Clusters come from the knowledge graph itself (theme node -> its asset
members), so "AI/datacenter 0.7" means the *cluster* smells frothy, not one
ticker. Scores are shown in the daily overview, fed to the strategist as
evidence, and the adviser haircuts LONG conviction on frothy names — a
bubble is a reason not to chase, and (for the strategist) a shorting
candidate when fundamentals agree.
"""
from __future__ import annotations

import json
import os

W_VAL, W_CIRC, W_HEAT = 0.45, 0.30, 0.25
FLAG_LEVEL = 0.55


def _data(settings, name: str) -> dict:
    path = os.path.join(os.path.dirname(os.path.abspath(settings.state_path)), name)
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}


def _valuation_stretch(f: dict) -> float:
    """0 at sane multiples, →1 as pricing detaches from earnings."""
    pe = f.get("trailingPE") or f.get("forwardPE")
    pb = f.get("priceToBook")
    s = 0.0
    if pe and pe > 0:
        s = max(s, min(1.0, (pe - 30.0) / 120.0))     # PE 30→0, 150→1
    if pb and pb > 0:
        s = max(s, min(1.0, (pb - 8.0) / 22.0))       # PB 8→0, 30→1
    return round(max(0.0, s), 3)


def bubble_scores(settings) -> dict:
    """{"symbols": {sym: score}, "clusters": [{name, score, members}], "flagged": [...]}"""
    graph = _data(settings, "knowledge_graph.json")
    fund = _data(settings, "fundamentals.json")
    brain = _data(settings, "brain.json")
    acts = brain.get("activations") or {}
    circular_syms: set[str] = set()
    label_by_id: dict[str, dict] = {n["id"]: n for n in graph.get("nodes", [])}
    sym_node: dict[str, dict] = {n["symbol"]: n for n in graph.get("nodes", []) if n.get("symbol")}
    for loop in brain.get("circular_financing") or []:
        for nid in (loop.get("investor"), loop.get("counterparty")):
            n = label_by_id.get(nid)
            if n and n.get("symbol"):
                circular_syms.add(n["symbol"])

    symbols: dict[str, float] = {}
    for sym, node in sym_node.items():
        val = _valuation_stretch(fund.get(sym, {}))
        circ = 1.0 if sym in circular_syms else 0.0
        heat = min(1.0, max(0.0, acts.get(node["id"], 0.0)))   # only positive froth counts
        score = W_VAL * val + W_CIRC * circ + W_HEAT * heat
        if score > 0.05:
            symbols[sym] = round(score, 3)

    # clusters = theme nodes scored by their asset members (graph-driven, no hardcoding)
    members: dict[str, list[str]] = {}
    for e in graph.get("edges", []):
        for a, b in ((e.get("src"), e.get("dst")), (e.get("dst"), e.get("src"))):
            na, nb = label_by_id.get(a), label_by_id.get(b)
            if na and nb and na.get("type") in ("theme", "sector") and nb.get("symbol"):
                members.setdefault(a, []).append(nb["symbol"])
    clusters = []
    for tid, syms in members.items():
        scored = [symbols.get(s, 0.0) for s in syms]
        if len(scored) < 2:
            continue
        theme_heat = min(1.0, max(0.0, acts.get(tid, 0.0)))
        score = round(min(1.0, sum(scored) / len(scored) + 0.2 * theme_heat), 3)
        if score >= 0.15:
            clusters.append({"name": label_by_id[tid].get("label", tid), "score": score,
                             "members": [s for s in syms if symbols.get(s, 0) >= FLAG_LEVEL][:5]})
    clusters.sort(key=lambda c: -c["score"])

    flagged = sorted((s for s, v in symbols.items() if v >= FLAG_LEVEL),
                     key=lambda s: -symbols[s])
    return {"symbols": symbols, "clusters": clusters[:6], "flagged": flagged[:10]}


def bubble_line(scores: dict, labels: dict[str, str] | None = None) -> str:
    """One plain-language line for the daily overview."""
    labels = labels or {}
    tops = scores.get("clusters") or []
    if not tops or tops[0]["score"] < 0.3:
        return "🫧 Bubble watch: nothing looks frothy right now."
    parts = []
    for c in tops[:3]:
        level = "🔴 bubble territory" if c["score"] >= 0.6 else \
                ("🟠 getting frothy" if c["score"] >= 0.45 else "🟡 warm")
        parts.append(f"{c['name']} {c['score']:.2f} {level}")
    line = "🫧 *Bubble watch:* " + " · ".join(parts)
    flagged = scores.get("flagged") or []
    if flagged:
        names = ", ".join(f"{labels.get(s, s)}" for s in flagged[:4])
        line += f"\n   most stretched: {names}"
    return line
