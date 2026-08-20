#!/usr/bin/env python3
"""Structural gap check: node PAIRS that belong together but the graph never wired.

WHY THIS EXISTS.

graph_gap_scan.py catches a company that keeps appearing in headlines with no
node at all. It has no counterpart for the other failure mode: two nodes that
both already exist, are obviously part of the same real-world mechanism, and
have no edge (or only a long, indirect path) between them. That gap is real
and was caught by hand once already (china_tech <-> ai_circularity, 2026-08-20):
the graph knew "China's AI progress pressures US megacap tech sentiment"
(china_tech->us_megacap_tech) and "China's AI progress pressures US AI capex
pace" (china_tech<->ai_capex_cycle), but had ZERO path to ai_circularity, the
one node that actually measures whether the $2.1T vendor-financing backlog
stays solvent. Same underlying fact, and the graph only wired the shallower
consequence.

This script looks for MORE cases like that one, systematically, on two kinds
of evidence:

  1. THEMATIC CLUSTERS (hand-defined below, CLUSTERS dict) -- node ids grouped
     by real-world mechanism (AI financing/compute, monetary fragmentation,
     Japan/yen, credit & insurance, China macro, energy/geopolitics, crypto).
     Within each cluster, every pair with no edge (or a long shortest path)
     between them is a candidate: they were judged related enough by a human
     to belong to the same cluster, so a missing edge is a real coverage gap,
     not noise. This is the intentional, extensible layer -- add a cluster,
     rerun, and every future gap in that theme gets caught automatically
     instead of waiting for someone to notice one example in a video.

  2. CO-TAGGED EVENTS (data-driven, from data/brain.db) -- node pairs that
     have actually been tagged TOGETHER on the same real digested event, which
     is strong empirical evidence they are related (a human or the live LLM
     digester read one story and reached for both), cross-referenced against
     whether the graph has an edge between them. This signal needs no manual
     cluster definition and will surface pairs the CLUSTERS dict didn't think
     of.

This script is READ-ONLY. It does not call graph.propose_edge() or write
anything. Getting the SIGN of a structural edge right needs a real causal
story, not just "these are in the same neighborhood" -- auto-writing a
wrong-signed edge into a live trading graph is a worse outcome than a gap
report a human (or a follow-up news submission) has to act on. This is a
diagnostic, the same spirit and safety posture as graph_gap_scan.py.

CO-TAG RANKING USES LIFT, NOT RAW COUNT (2026-08-20 fix). The first version of
this script ranked co-tagged pairs by raw count, which is confounded by each
node's overall tagging frequency: geopolitical_tension alone appears on 14.5%
of all digested events, so it produces high raw co-tag counts with almost
everything regardless of whether a real relationship exists. Two of the four
edges the first version led to (financial_fraud->crypto_regulation, cotag=9;
ai_datacenter->private_credit, cotag=2) turned out to have lift <= 1.1 --
at or below what independence alone predicts -- and were added on narrative
plausibility, not evidence. They were reverted. Lift = P(a,b) / (P(a)*P(b))
corrects for this: it asks "how much more often do these co-occur than their
individual frequencies alone would predict," not "how often do they
co-occur." A pair needs BOTH a minimum raw count (so lift isn't noise off a
sample of 2) and a high lift to be worth a human's time.

  python3 scripts/cluster_gap_scan.py                 # full report
  python3 scripts/cluster_gap_scan.py --min-cotag 3 --min-lift 5   # stricter
  python3 scripts/cluster_gap_scan.py --json          # machine-readable
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter, deque
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))

from ai_investing.brain.graph import KnowledgeGraph  # noqa: E402
from ai_investing.config import settings  # noqa: E402

# ---------------------------------------------------------------------------
# Hand-defined thematic clusters. Extend this as new themes show up in news --
# each cluster is a one-time investment that then audits itself on every rerun.
# Node ids only; unknown ids are silently ignored so this survives graph churn.
# ---------------------------------------------------------------------------
CLUSTERS: dict[str, list[str]] = {
    "ai_financing": [
        "ai_capex_cycle", "ai_circularity", "ai_datacenter", "ai_servers",
        "financial_engineering", "private_credit", "credit_conditions",
        "credit_spreads", "us_megacap_tech", "semis", "china_semis",
        "china_tech", "advanced_packaging", "hbm_memory", "datacenter_power_gear",
        "power_demand", "us_tech_regulation", "china_export_controls",
    ],
    "monetary_fragmentation": [
        "monetary_fragmentation", "cbdc_rollout", "payment_rail_access",
        "stablecoin_supply", "em_dollarization", "fx_intervention",
        "sanctions", "sanctioned_economy_stress", "crypto_regulation",
        "crypto_adoption", "cb_gold_buying", "gold_price", "usd_strength",
    ],
    "japan_yen": [
        "japan_debt", "yen_carry", "fx_intervention", "us_10y_yield",
        "us_gov_debt", "bond_stress", "money_supply",
    ],
    "credit_insurance": [
        "private_credit", "credit_conditions", "credit_spreads",
        "financial_engineering", "financial_fraud", "us_cre",
        "bond_stress", "us_gov_debt",
    ],
    "china_macro": [
        "china_growth", "china_stimulus", "china_property",
        "china_property_stocks", "china_consumer", "china_export_controls",
        "china_anti_corruption", "china_tech", "china_semis", "china_financials",
        "china_staples", "china_fnb", "china_healthcare", "cnh_devaluation",
        "pboc_rate",
    ],
    "energy_geopolitics": [
        "geopolitical_tension", "oil_supply", "oil_price", "shipping_costs",
        "sanctions", "sanctioned_economy_stress", "defense_spending",
        "defense_industry", "natural_gas",
    ],
    "crypto_structure": [
        "crypto_adoption", "crypto_liquidity", "crypto_regulation",
        "custody_risk", "stablecoin_supply", "tokenization", "crypto_majors",
        "btc_halving", "financial_fraud",
    ],
}

_EDGE_TYPES_UNDIRECTED = True  # for distance purposes, treat any edge as traversable


def _adjacency(graph: KnowledgeGraph) -> dict[str, set[str]]:
    adj: dict[str, set[str]] = {nid: set() for nid in graph.nodes}
    for e in graph.edges:
        if e.src in adj and e.dst in adj:
            adj[e.src].add(e.dst)
            adj[e.dst].add(e.src)
    return adj


def _bfs_dist(adj: dict[str, set[str]], src: str, targets: set[str]) -> dict[str, int]:
    """Shortest-path distance from src to every node in targets (BFS, unweighted)."""
    seen = {src: 0}
    q = deque([src])
    remaining = set(targets) - {src}
    while q and remaining:
        cur = q.popleft()
        for nxt in adj.get(cur, ()):
            if nxt not in seen:
                seen[nxt] = seen[cur] + 1
                remaining.discard(nxt)
                q.append(nxt)
    return seen


def _direct_edge(graph: KnowledgeGraph, a: str, b: str) -> bool:
    return any((e.src == a and e.dst == b) or (e.src == b and e.dst == a)
               for e in graph.edges)


def _cluster_gaps(graph: KnowledgeGraph, min_dist: int) -> list[dict]:
    adj = _adjacency(graph)
    out = []
    for cname, members in CLUSTERS.items():
        present = [m for m in members if m in graph.nodes]
        for a, b in combinations(sorted(present), 2):
            if _direct_edge(graph, a, b):
                continue
            dist = _bfs_dist(adj, a, {b}).get(b)
            if dist is None or dist >= min_dist:
                out.append({
                    "cluster": cname, "a": a, "b": b,
                    "graph_distance": dist if dist is not None else "unreachable",
                })
    return out


def _cotag_stats(db_path: str) -> tuple[Counter, Counter, int]:
    """Returns (marginal frequency per node, raw co-tag count per pair, N events)."""
    marginal: Counter = Counter()
    cotag: Counter = Counter()
    n = 0
    try:
        con = sqlite3.connect(db_path)
    except sqlite3.OperationalError:
        return marginal, cotag, 0
    try:
        cur = con.execute("SELECT nodes FROM events WHERE nodes IS NOT NULL AND nodes != '[]'")
        for (raw,) in cur:
            try:
                nodes = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                continue
            uniq = sorted(set(n2 for n2 in nodes if isinstance(n2, str)))
            if not uniq:
                continue
            n += 1
            for node in uniq:
                marginal[node] += 1
            for a, b in combinations(uniq, 2):
                cotag[(a, b)] += 1
    finally:
        con.close()
    return marginal, cotag, n


def _lift(marginal: Counter, cotag_count: int, n: int, a: str, b: str) -> float:
    """P(a,b) / (P(a)*P(b)). 1.0 = co-occur exactly as often as chance predicts;
    below 1.0 = LESS than chance (raw count can still look high if both nodes
    are individually common -- lift is what corrects for that)."""
    fa, fb = marginal.get(a, 0), marginal.get(b, 0)
    if not (cotag_count and fa and fb and n):
        return 0.0
    return (cotag_count / n) / ((fa / n) * (fb / n))


def _cotagged_pairs(db_path: str, min_count: int, min_lift: float) -> list[tuple[str, str, int, float]]:
    marginal, cotag, n = _cotag_stats(db_path)
    out = []
    for (a, b), c in cotag.items():
        if c < min_count:
            continue
        lift = _lift(marginal, c, n, a, b)
        if lift < min_lift:
            continue
        out.append((a, b, c, lift))
    out.sort(key=lambda t: -t[3])
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--min-dist", type=int, default=3,
                    help="flag same-cluster pairs at or beyond this graph distance (default 3)")
    ap.add_argument("--min-cotag", type=int, default=3,
                    help="minimum raw co-tag count before lift is trusted (default 3)")
    ap.add_argument("--min-lift", type=float, default=3.0,
                    help="minimum lift over random co-occurrence to flag (default 3.0)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    graph = KnowledgeGraph.load(settings.brain.graph_path)
    cluster_gaps = _cluster_gaps(graph, args.min_dist)
    cotag_ranked = _cotagged_pairs(settings.brain.db_path, args.min_cotag, args.min_lift)

    cotag_gaps = []
    for a, b, c, lift in cotag_ranked:
        if a not in graph.nodes or b not in graph.nodes:
            continue
        if _direct_edge(graph, a, b):
            continue
        cotag_gaps.append({"a": a, "b": b, "cotag_count": c, "lift": round(lift, 1)})

    # cross-reference: candidates backed by BOTH signals are highest priority.
    # NOTE: cluster_gaps are annotated with lift too, but at NO lift/count floor
    # (cluster membership alone is the evidence there) -- 0.0 means "not enough
    # co-tag data to compute a lift", not "lift is exactly zero".
    lift_index = {frozenset((a, b)): (c, lift) for a, b, c, lift in
                 _cotagged_pairs(settings.brain.db_path, 1, 0.0)}
    for g in cluster_gaps:
        c, lift = lift_index.get(frozenset((g["a"], g["b"])), (0, 0.0))
        g["cotag_count"] = c
        g["lift"] = round(lift, 1)
    cluster_gaps.sort(key=lambda g: (-g["lift"],
                                     g["graph_distance"] if isinstance(g["graph_distance"], int) else 99))

    if args.json:
        print(json.dumps({"cluster_gaps": cluster_gaps, "cotag_only_gaps": cotag_gaps}, indent=2))
        return

    print(f"=== Cluster gaps (same theme, graph-distance >= {args.min_dist} or unreachable) ===")
    print(f"    {len(cluster_gaps)} candidate(s), sorted by lift (co-tag evidence may be thin/zero)\n")
    for g in cluster_gaps:
        flag = "  <-- also co-tagged, lift-supported" if g["lift"] >= args.min_lift else ""
        print(f"  [{g['cluster']}] {g['a']} <-> {g['b']}  "
              f"(graph_distance={g['graph_distance']}, cotag={g['cotag_count']}, lift={g['lift']}){flag}")

    print(f"\n=== Co-tagged >= {args.min_cotag}x with lift >= {args.min_lift} (not in a defined cluster) ===")
    only_new = [g for g in cotag_gaps
               if not any({g['a'], g['b']} <= set(v) for v in CLUSTERS.values())]
    print(f"    {len(only_new)} candidate(s), ranked by lift -- consider adding to a CLUSTERS entry\n")
    for g in only_new[:30]:
        print(f"  {g['a']} <-> {g['b']}  (cotag={g['cotag_count']}, lift={g['lift']})")


if __name__ == "__main__":
    main()
