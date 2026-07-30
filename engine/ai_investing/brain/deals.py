"""Deal wiring: turn digested DEAL records into graph relationships, so
circular money flows surface AUTOMATICALLY — no per-company code.

The pipeline (each step generic):
  1. The digester (LLM) emits `deals` on events: who invested in / supplies /
     acquired whom, and the stated size. Pure entity extraction — scales to
     any company the news ever names.
  2. Entity resolution: names resolve against the graph's alias index. An
     UNKNOWN party in a MATERIAL deal (>= $1B stated) becomes a new private
     hub node via `propose_node` — the next OpenAI wires itself in.
  3. Materiality-scaled edges: `invests_in`/`acquires` -> owns, `supplies` ->
     supplies, weight scaled by deal size, confidence capped (llm provenance,
     always below curated). Repeat corroboration bumps confidence, never past
     the cap.
  4. `detect_circular_financing()` then finds any cycle the new legs close —
     the detection layer never needs to know company names at all.

Skepticism gates: noise events are ignored; unresolved parties in small deals
are dropped (materiality first); weights cap at 0.5 so no news-derived leg
ever outranks curated wiring.
"""
from __future__ import annotations

import re

_SUFFIXES = re.compile(r"\b(inc|corp|corporation|co|ltd|plc|holdings|group|"
                       r"technologies|technology|labs|ai)\b\.?", re.I)
MATERIAL_NEW_NODE_BN = 1.0        # unknown party must be in a >=$1B deal to earn a node
KIND_TO_EDGE = {"invests_in": "owns", "acquires": "owns", "supplies": "supplies"}


def _norm_name(name: str) -> str:
    return re.sub(r"\s+", " ", _SUFFIXES.sub("", name or "")).strip().lower()


def resolve(graph, name: str) -> str | None:
    """Company name -> node id, via the alias index (exact, then de-suffixed)."""
    if not name:
        return None
    idx = graph.alias_index()
    for cand in (name.lower().strip(), _norm_name(name)):
        if cand in idx:
            return idx[cand]
    # de-suffixed match against de-suffixed labels ("Oracle Corp" -> "Oracle")
    target = _norm_name(name)
    if target:
        for n in graph.nodes.values():
            if _norm_name(n.label) == target:
                return n.id
    return None


def _weight_for(value_bn: float | None) -> float:
    """Deal size -> edge weight: $1B -> ~0.06, $10B -> 0.15, $100B+ -> 0.5 cap."""
    if not value_bn or value_bn <= 0:
        return 0.1
    return round(min(0.5, 0.05 + value_bn / 200.0), 3)


def apply_deals(graph, events: list[dict], ts: str = "") -> dict:
    """Wire every credible deal on this cycle's events into the graph.
    Returns a report: nodes created, edges added/corroborated, and the loops
    the graph sees afterwards (with severity)."""
    report = {"nodes_created": [], "edges_added": [], "edges_corroborated": [],
              "dropped": []}
    by_key = {(e.src, e.dst, e.type): e for e in graph.edges}
    for ev in events:
        if ev.get("is_noise"):
            continue
        for d in (ev.get("deals") or [])[:4]:
            if not isinstance(d, dict):
                continue
            kind = str(d.get("kind", "")).strip()
            etype = KIND_TO_EDGE.get(kind)
            a_name, b_name = str(d.get("party_a", "")), str(d.get("party_b", ""))
            if not etype or not a_name or not b_name:
                continue
            try:
                value_bn = float(d.get("value_usd_bn") or 0) or None
            except (TypeError, ValueError):
                value_bn = None
            a, b = resolve(graph, a_name), resolve(graph, b_name)
            # unknown party: create a private hub only for MATERIAL deals
            for nid, nm in ((a, a_name), (b, b_name)):
                if nid is None and value_bn and value_bn >= MATERIAL_NEW_NODE_BN:
                    slug = _norm_name(nm).replace(" ", "_")
                    if graph.propose_node(slug, nm.strip(), aliases=[nm.strip()],
                                          proposed_by=ev.get("summary", "")[:120], ts=ts):
                        report["nodes_created"].append(slug)
            a, b = a or resolve(graph, a_name), b or resolve(graph, b_name)
            if a is None or b is None or a == b:
                report["dropped"].append(f"{a_name}/{b_name} ({kind}): unresolved or immaterial")
                continue
            w = _weight_for(value_bn)
            conf = round(min(0.6, 0.2 + 0.4 * float(ev.get("credibility", 0.5))), 3)
            existing = by_key.get((a, b, etype))
            if existing is not None:
                if existing.provenance == "llm":
                    # corroboration: firmer, never past the llm cap; weight ratchets up only
                    existing.confidence = min(0.6, existing.confidence + 0.1)
                    existing.weight = max(existing.weight, w)
                    graph._adj = None
                    report["edges_corroborated"].append(f"{a}-{etype}->{b}")
                continue          # curated edge already covers it
            if graph.propose_edge(a, b, etype, 1, w, conf,
                                  proposed_by=f"deal: {ev.get('summary', '')[:100]}", ts=ts):
                report["edges_added"].append(f"{a}-{etype}->{b} (w={w}, conf={conf})")
    report["loops"] = graph.detect_circular_financing()
    return report
