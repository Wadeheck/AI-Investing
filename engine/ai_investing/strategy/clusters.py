"""Structural risk clusters from the knowledge graph.

Return correlation says how two names HAVE moved; the graph says why they
WILL move together: shared theme membership and supply-chain adjacency.
NVDA, SMCI, Vertiv, ASE, SK Hynix and Broadcom are six tickers but one bet
(AI capex) — a risk desk limits the BET, not the ticker. This module maps
each tradable symbol to its structural cluster ids so the RiskManager can
cap gross exposure per cluster.

Cluster ids are theme/sector node ids (member_of), plus the theme reached
through ONE supplies hop (a supplier is inside its customer's cluster).
Cheap to compute, cached per process.
"""
from __future__ import annotations

from functools import lru_cache


@lru_cache(maxsize=1)
def symbol_clusters() -> dict[str, frozenset[str]]:
    """UPPER symbol -> frozenset of cluster ids (theme/sector node ids)."""
    from ai_investing.brain.graph import KnowledgeGraph
    g = KnowledgeGraph.seeded()
    theme_types = {"theme", "sector"}
    member: dict[str, set[str]] = {}
    for e in g.edges:
        if e.type == "member_of" and e.dst in g.nodes and g.nodes[e.dst].type in theme_types:
            member.setdefault(e.src, set()).add(e.dst)
    # theme hierarchy: a BOM tier that SUPPLIES (or is member_of) a parent
    # theme belongs to the parent's bet (ai_servers -> ai_datacenter)
    theme_parent: dict[str, set[str]] = {}
    for e in g.edges:
        if (e.type in ("supplies", "member_of") and e.src in g.nodes and e.dst in g.nodes
                and g.nodes[e.src].type in theme_types and g.nodes[e.dst].type in theme_types):
            theme_parent.setdefault(e.src, set()).add(e.dst)
    # driver factors: the TRUE name of a shared bet is often the factor that
    # drives every tier (ai_capex_cycle -> semis, hbm, power gear, optics...).
    # A strong positive influences edge from a factor makes that factor a
    # cluster id for the theme's members.
    theme_driver: dict[str, set[str]] = {}
    for e in g.edges:
        if (e.type == "influences" and e.sign > 0 and e.weight >= 0.5
                and e.src in g.nodes and e.dst in g.nodes
                and g.nodes[e.src].type == "factor"
                and g.nodes[e.dst].type in theme_types):
            theme_driver.setdefault(e.dst, set()).add(e.src)

    def expand(themes: set) -> set:
        cl = set(themes)
        for t in list(themes):                       # one parent hop
            cl |= theme_parent.get(t, set())
        for t in list(cl):
            cl |= theme_driver.get(t, set())         # + shared driver factors
        return cl

    # asset->asset supplies: supplier joins the customer's themes (NVDA rides
    # CoreWeave's cluster even without a membership edge)
    supplier_extra: dict[str, set[str]] = {}
    for e in g.edges:
        if (e.type == "supplies" and e.src in g.nodes and e.dst in g.nodes
                and g.nodes[e.src].type == "asset" and g.nodes[e.dst].type == "asset"):
            supplier_extra.setdefault(e.src, set()).update(member.get(e.dst, ()))

    out: dict[str, frozenset[str]] = {}
    for nid, n in g.nodes.items():
        if n.type != "asset" or not n.symbol:
            continue
        cl = expand(set(member.get(nid, ())) | supplier_extra.get(nid, set()))
        if cl:
            out[n.symbol.upper()] = frozenset(cl)
    return out


def clusters_for(symbol: str) -> frozenset[str]:
    return symbol_clusters().get(symbol.upper(), frozenset())


def cluster_gross(positions_notional: dict[str, float]) -> dict[str, float]:
    """cluster id -> sum of |notional| across symbols belonging to it.
    positions_notional keys may be 'stock:AAPL'-style asset keys or bare symbols."""
    out: dict[str, float] = {}
    for key, notional in positions_notional.items():
        sym = key.split(":", 1)[-1].upper()
        for c in clusters_for(sym):
            out[c] = out.get(c, 0.0) + abs(notional)
    return out
