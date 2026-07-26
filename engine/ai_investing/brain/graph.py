"""The knowledge graph: the brain's wiring.

Nodes are macro factors, themes/sectors, assets (multi-market), and policy actors.
Edges are typed and *signed*: `sign=+1` means the source moving up pushes the
destination up; `sign=-1` the opposite. `weight` (0..1) is how strongly, and each
edge carries provenance (seed vs LLM-proposed) so auto-learned wiring never
silently outranks curated wiring.

Propagation: an event lands on one or more nodes as an impulse in [-1, +1]
(polarity x magnitude x credibility). The impulse then walks the graph — factor to
factor first, then down membership edges into assets — decaying per hop. The
result is a per-node impact map plus the full traversal trace (for the dashboard
visualization: you can watch a headline ripple through the field).

Factor nodes can carry an `equilibrium` note (the stable point) and a live
`state`, so the graph doesn't just know the wiring — it knows where the system
currently sits relative to stable.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Optional

# How a shock travels across each edge type: "fwd" src->dst, "rev" dst->src, "both".
# member_of edges point asset -> theme, so shocks flow in REVERSE (theme hits members).
EDGE_FLOW = {
    "influences": "fwd",
    "supplies": "both",        # supplier disruption hits customer and vice versa
    "competes_with": "both",   # competitor's win is your loss (sign forced negative)
    "member_of": "rev",        # theme/sector shock hits its members
    "regulated_by": "rev",     # regulator/policy action hits the regulated
    "correlates_with": "both",
    "owns": "rev",             # src owns a stake in dst: the holding's move flows
                               # back to the owner's value — follow the money.
                               # weight ≈ how much of the owner the stake represents
}


@dataclass
class Node:
    id: str
    type: str                    # factor | theme | sector | asset | actor | commodity
    label: str
    aliases: list[str] = field(default_factory=list)
    symbol: str = ""             # canonical data-provider symbol for asset nodes
    market: str = ""             # US | HK | CN | SG | CRYPTO for asset nodes
    equilibrium: str = ""        # what "stable" looks like for this factor
    state: str = ""              # current qualitative state (updated by regime)

    def to_dict(self) -> dict:
        d = {"id": self.id, "type": self.type, "label": self.label}
        for k in ("aliases", "symbol", "market", "equilibrium", "state"):
            v = getattr(self, k)
            if v:
                d[k] = v
        return d


@dataclass
class Edge:
    src: str
    dst: str
    type: str                    # see EDGE_FLOW
    sign: int = 1                # +1 same direction, -1 inverse
    weight: float = 0.5          # 0..1 strength
    confidence: float = 1.0      # curated=1.0; LLM-proposed lower
    delay_days: float = 0.0      # τ: real-world lag before the effect lands (0 = immediate)
    provenance: str = "seed"     # "seed" | "llm"
    note: str = ""
    proposed_by: str = ""        # event summary that proposed it (llm edges)
    proposed_at: str = ""

    def to_dict(self) -> dict:
        d = {"src": self.src, "dst": self.dst, "type": self.type, "sign": self.sign,
             "weight": self.weight, "confidence": self.confidence, "provenance": self.provenance}
        if self.delay_days:
            d["delay_days"] = self.delay_days
        for k in ("note", "proposed_by", "proposed_at"):
            v = getattr(self, k)
            if v:
                d[k] = v
        return d


class KnowledgeGraph:
    def __init__(self, nodes: list[Node], edges: list[Edge]):
        self.nodes: dict[str, Node] = {n.id: n for n in nodes}
        self.edges: list[Edge] = edges
        self._adj: Optional[dict] = None
        self._alias_index: Optional[dict[str, str]] = None

    # -- persistence ---------------------------------------------------------
    @classmethod
    def load(cls, path: str) -> "KnowledgeGraph":
        """Load from JSON; seed the file if missing. If the code's curated seed is
        newer than the file's, merge it in: new seed nodes/edges are added and
        curated edges are refreshed, while LLM-proposed edges and any nodes the
        seed doesn't know about are preserved untouched."""
        from ai_investing.brain.seed import SEED_VERSION
        if not os.path.exists(path):
            g = cls.seeded()
            g.save(path)
            return g
        with open(path) as fh:
            d = json.load(fh)
        nodes = [Node(**n) for n in d.get("nodes", [])]
        edges = [Edge(**e) for e in d.get("edges", [])]
        g = cls(nodes, edges)
        if d.get("seed_version", 1) < SEED_VERSION:
            g._merge_seed()
            g.save(path)
        return g

    def _merge_seed(self) -> None:
        seed = KnowledgeGraph.seeded()
        for nid, node in seed.nodes.items():
            self.nodes.setdefault(nid, node)
        by_key = {(e.src, e.dst, e.type): i for i, e in enumerate(self.edges)}
        for e in seed.edges:
            i = by_key.get((e.src, e.dst, e.type))
            if i is None:
                self.edges.append(e)
            elif self.edges[i].provenance == "seed":
                self.edges[i] = e   # curated wiring refreshes; llm edges keep theirs
        self._adj = None
        self._alias_index = None

    @classmethod
    def seeded(cls) -> "KnowledgeGraph":
        from ai_investing.brain.seed import SEED_EDGES, SEED_NODES
        return cls([Node(**n) for n in SEED_NODES], [Edge(**e) for e in SEED_EDGES])

    def save(self, path: str) -> None:
        from ai_investing.brain.seed import SEED_VERSION
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w") as fh:
            json.dump({"seed_version": SEED_VERSION,
                       "nodes": [n.to_dict() for n in self.nodes.values()],
                       "edges": [e.to_dict() for e in self.edges]}, fh, indent=1)

    # -- indexing ------------------------------------------------------------
    def _adjacency(self) -> dict:
        """node_id -> list of (neighbor_id, effective_sign, weight*confidence, edge)."""
        if self._adj is not None:
            return self._adj
        adj: dict[str, list] = {nid: [] for nid in self.nodes}
        for e in self.edges:
            if e.src not in self.nodes or e.dst not in self.nodes:
                continue
            flow = EDGE_FLOW.get(e.type, "fwd")
            sign = -1 if e.type == "competes_with" else e.sign
            w = max(0.0, min(1.0, e.weight)) * max(0.0, min(1.0, e.confidence))
            if flow in ("fwd", "both"):
                adj[e.src].append((e.dst, sign, w, e))
            if flow in ("rev", "both"):
                adj[e.dst].append((e.src, sign, w, e))
        self._adj = adj
        return adj

    def alias_index(self) -> dict[str, str]:
        """lowercase alias/label/symbol -> node id (for text matching + symbol lookup)."""
        if self._alias_index is not None:
            return self._alias_index
        idx: dict[str, str] = {}
        for n in self.nodes.values():
            names = [n.id, n.label] + list(n.aliases)
            if n.symbol:
                names.append(n.symbol)
                names.append(n.symbol.split(".")[0])  # bare ticker
            for name in names:
                idx[name.lower()] = n.id
        self._alias_index = idx
        return idx

    def node_for_symbol(self, symbol: str) -> Optional[Node]:
        nid = self.alias_index().get(symbol.lower())
        return self.nodes.get(nid) if nid else None

    def match_text(self, text: str) -> list[str]:
        """Which nodes does this text mention? Word-boundary match on labels/aliases.
        This is the LLM-free fallback for event extraction and simulation."""
        low = text.lower()
        hits = []
        for alias, nid in self.alias_index().items():
            if len(alias) < 3:
                continue
            if re.search(r"(?<![\w])" + re.escape(alias) + r"(?![\w])", low):
                if nid not in hits:
                    hits.append(nid)
        return hits

    # -- propagation (the actual thinking) ------------------------------------
    def propagate(self, impulses: dict[str, float], max_hops: int = 3,
                  decay: float = 0.6) -> tuple[dict[str, float], list[dict], list[dict]]:
        """Ripple impulses through the graph.

        Returns (impacts, trace, deferred). `impacts` maps node_id -> accumulated
        impact in [-1, 1] — the SAME-CYCLE effects. `trace` lists every traversal
        step so the dashboard can animate the ripple: {from, to, edge_type, hop,
        contribution}. `deferred` carries contributions crossing time-delayed
        edges (τ > 0): they do NOT land now — the caller queues them and re-injects
        each as a fresh impulse on its dst node once due, at which point it
        propagates onward from there. Best-magnitude relaxation per node prevents
        loops from compounding.
        """
        adj = self._adjacency()
        impacts: dict[str, float] = {}
        trace: list[dict] = []
        deferred: list[dict] = []
        # visited[n] = strongest |impulse| already propagated OUT of n; a node only
        # re-enters the frontier if a stronger shock reaches it (prevents loops).
        visited: dict[str, float] = {}
        frontier = {n: max(-1.0, min(1.0, v)) for n, v in impulses.items()
                    if n in self.nodes and abs(v) > 1e-4}
        for n, v in frontier.items():
            impacts[n] = v
        for hop in range(1, max_hops + 1):
            nxt: dict[str, float] = {}
            for src, val in frontier.items():
                if abs(val) <= visited.get(src, 0.0):
                    continue
                visited[src] = abs(val)
                for dst, sign, w, edge in adj.get(src, []):
                    contrib = val * sign * w * decay
                    if abs(contrib) < 0.02:
                        continue
                    if edge.delay_days > 0:
                        deferred.append({"node": dst, "contribution": round(contrib, 4),
                                         "delay_days": edge.delay_days, "via": src,
                                         "edge_type": edge.type})
                        continue
                    impacts[dst] = max(-1.0, min(1.0, impacts.get(dst, 0.0) + contrib))
                    if abs(contrib) > abs(nxt.get(dst, 0.0)):
                        nxt[dst] = contrib
                    trace.append({"from": src, "to": dst, "edge_type": edge.type,
                                  "hop": hop, "contribution": round(contrib, 4)})
            if not nxt:
                break
            frontier = nxt
        return impacts, trace, deferred

    def asset_impacts(self, impacts: dict[str, float]) -> dict[str, dict]:
        """Collapse node impacts onto tradable symbols: {SYMBOL: {impact, node, drivers}}."""
        out: dict[str, dict] = {}
        for nid, val in impacts.items():
            n = self.nodes.get(nid)
            if not n or n.type != "asset" or not n.symbol:
                continue
            out[n.symbol.upper()] = {"impact": round(val, 4), "node": nid, "label": n.label,
                                     "market": n.market}
        return out

    def centrality(self, iterations: int = 30, damping: float = 0.85) -> dict[str, float]:
        """PageRank-style centrality over |weight|: which nodes are systemically
        important — shocks to them reach everything. Out-weight normalization +
        damping keep tight 2-cycles (asset↔proxy) from swallowing the mass that
        plain eigenvector centrality would give them. Normalized to max=1."""
        adj = self._adjacency()
        n = len(self.nodes) or 1
        out_w = {src: sum(w for _d, _s, w, _e in nbrs) for src, nbrs in adj.items()}
        score = {nid: 1.0 / n for nid in self.nodes}
        for _ in range(iterations):
            nxt = {nid: (1 - damping) / n for nid in self.nodes}
            for src, neighbors in adj.items():
                if not out_w.get(src):
                    continue
                for dst, _sign, w, _e in neighbors:
                    nxt[dst] += damping * score[src] * (w / out_w[src])
            score = nxt
        top = max(score.values()) or 1.0
        return {k: round(v / top, 4) for k, v in score.items()}

    # -- growth: LLM-proposed edges -------------------------------------------
    def propose_edge(self, src: str, dst: str, type_: str, sign: int, weight: float,
                     confidence: float, proposed_by: str, ts: str) -> bool:
        """Append an LLM-proposed edge (never overwrites a curated one). Returns
        True if added. Proposed edges carry provenance for periodic human review."""
        if src not in self.nodes or dst not in self.nodes or type_ not in EDGE_FLOW:
            return False
        for e in self.edges:
            if e.src == src and e.dst == dst and e.type == type_:
                return False
        self.edges.append(Edge(src=src, dst=dst, type=type_, sign=1 if sign >= 0 else -1,
                               weight=max(0.05, min(1.0, weight)),
                               confidence=max(0.05, min(0.6, confidence)),  # capped below curated
                               provenance="llm", proposed_by=proposed_by[:160], proposed_at=ts))
        self._adj = None
        return True
