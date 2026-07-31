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
    weight: float = 0.5          # 0..1 strength in the edge's forward direction
    weight_rev: Optional[float] = None   # asymmetric back-flow for "both" edges:
                                 # NVDA is ~11% of TSMC's revenue, but TSMC is ~100%
                                 # of NVDA's supply — the two directions differ.
                                 # None = symmetric (weight both ways).
    confidence: float = 1.0      # curated=1.0; LLM-proposed lower
    delay_days: float = 0.0      # τ: real-world lag before the effect lands (0 = immediate)
    provenance: str = "seed"     # "seed" | "llm"
    note: str = ""
    proposed_by: str = ""        # event summary that proposed it (llm edges)
    proposed_at: str = ""
    regime_gate: Optional[dict] = None   # {"dial","lo","hi","outside"}: some
                                 # relationships are only true in one regime.
                                 # While the named regime dial sits inside
                                 # [lo, hi] the edge behaves normally; outside
                                 # the band it flips sign ("flip"), goes quiet
                                 # ("mute"), or halves ("damp"). Example: Fed
                                 # hikes hurt risk when inflation is the fear,
                                 # but in a growth scare cuts ARE the fear.

    def to_dict(self) -> dict:
        d = {"src": self.src, "dst": self.dst, "type": self.type, "sign": self.sign,
             "weight": self.weight, "confidence": self.confidence, "provenance": self.provenance}
        if self.weight_rev is not None:
            d["weight_rev"] = self.weight_rev
        if self.delay_days:
            d["delay_days"] = self.delay_days
        if self.regime_gate:
            d["regime_gate"] = self.regime_gate
        for k in ("note", "proposed_by", "proposed_at"):
            v = getattr(self, k)
            if v:
                d[k] = v
        return d

    def gated(self, regime: Optional[dict]) -> tuple[int, float]:
        """(sign_multiplier, weight_multiplier) after evaluating the regime gate."""
        g = self.regime_gate
        if not g or not regime:
            return 1, 1.0
        v = regime.get(g.get("dial", ""))
        if v is None:
            return 1, 1.0
        if g.get("lo", -1.0) <= v <= g.get("hi", 1.0):
            return 1, 1.0
        action = g.get("outside", "damp")
        if action == "flip":
            return -1, 1.0
        if action == "mute":
            return 1, 0.0
        return 1, 0.5                      # "damp"


class KnowledgeGraph:
    def __init__(self, nodes: list[Node], edges: list[Edge]):
        self.nodes: dict[str, Node] = {n.id: n for n in nodes}
        self.edges: list[Edge] = edges
        self._adj: Optional[dict] = None
        self._alias_index: Optional[dict[str, str]] = None
        self._calibration: dict[str, float] = {}   # edge key -> evidence multiplier

    @staticmethod
    def edge_key(e: Edge) -> str:
        return f"{e.src}->{e.dst}:{e.type}"

    def set_calibration(self, factors: dict[str, float]) -> None:
        """Attach evidence-based per-edge multipliers (from brain/calibration.py).
        Applied at adjacency-build time, IN MEMORY ONLY — never persisted into
        edge confidence, so reloading and reapplying can't compound the discount."""
        self._calibration = {k: max(0.25, min(1.5, float(v)))
                             for k, v in (factors or {}).items()}
        self._adj = None

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
            cur = self.nodes.get(nid)
            if cur is None:
                self.nodes[nid] = node
            else:
                # curated node METADATA refreshes too (labels/aliases/equilibrium
                # updates must reach existing graph files — a sign-convention fix
                # in the seed is meaningless if deployed labels keep the old
                # wording); only the live `state` survives from the old node.
                node.state = cur.state
                self.nodes[nid] = node
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
            conf = max(0.0, min(1.0, e.confidence))
            conf *= self._calibration.get(self.edge_key(e), 1.0)   # evidence weighting
            w_fwd = max(0.0, min(1.0, e.weight)) * conf
            w_back = e.weight_rev if e.weight_rev is not None else e.weight
            w_rev = max(0.0, min(1.0, w_back)) * conf
            if flow in ("fwd", "both"):
                adj[e.src].append((e.dst, sign, w_fwd, e))
            if flow in ("rev", "both"):
                adj[e.dst].append((e.src, sign, w_rev, e))
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
            if alias.isascii():
                if len(alias) < 3:
                    continue
                if re.search(r"(?<![\w])" + re.escape(alias) + r"(?:e?s)?(?![\w])", low):
                    if nid not in hits:
                        hits.append(nid)
            else:
                # CJK aliases: no spaces between words, so word boundaries
                # don't exist — plain substring match (2+ chars is specific
                # enough in Chinese/Japanese)
                if len(alias) >= 2 and alias in low and nid not in hits:
                    hits.append(nid)
        return hits

    # -- propagation (the actual thinking) ------------------------------------
    # markets front-run known real-economy lags: this share of a τ-edge's
    # contribution lands NOW when the destination is a PRICED thing (asset /
    # theme / sector / commodity); the rest still arrives on schedule as the
    # data prints. Factor destinations (CPI, growth...) stay fully deferred —
    # the real economy doesn't reprice, it arrives.
    ANTICIPATION = 0.5
    _PRICED_TYPES = {"asset", "theme", "sector", "commodity"}

    def propagate(self, impulses: dict[str, float], max_hops: int = 3,
                  decay: float = 0.6,
                  regime: Optional[dict] = None) -> tuple[dict[str, float], list[dict], list[dict]]:
        """Ripple impulses through the graph — exact truncated path-sum.

        The math: for every directed path p = (n0 -> n1 -> ... -> nk), k <= max_hops,
        the contribution to nk is

            impulse(n0) x prod_i [ sign_i x weight_i x decay ]

        and a node's raw impact is the SUM over all such paths (linear
        superposition — three medium paths converging on a node push their
        combined force onward, unlike max-path relaxation). `decay` per hop
        encodes growing model uncertainty with inference depth, on top of the
        edge weights. Paths are enumerated with magnitude pruning (<0.015 dies),
        which bounds the expansion; a path never immediately re-crosses the edge
        it just arrived by, so bidirectional pairs (asset <-> proxy) cannot echo
        a shock straight back onto its source. Genuine feedback loops through
        DISTINCT edges are allowed and correctly summed.

        `regime` (optional dial snapshot: risk_appetite, inflation_trend, fear…)
        activates two non-linear corrections the linear sum can't express:
          * regime gates — edges whose sign/strength is only true in one regime
            (see Edge.regime_gate) flip, mute, or damp outside their band;
          * crisis correlation convergence — in deep risk-off, diversification
            dies: membership/correlation wiring is pushed toward weight 1, so
            everything risky becomes one trade, the way it actually does.

        Raw sums are squashed through tanh at read time — smooth saturation, so
        stacked shocks keep their ordering instead of flat-lining at a clip.

        Returns (impacts, trace, deferred). `deferred` carries contributions that
        crossed time-delayed edges (τ > 0) into REAL-ECONOMY nodes: they land
        later via the field's pending queue. For priced destinations, the market
        discounts the known lag: ANTICIPATION of the contribution lands now and
        only the remainder is deferred.
        """
        import math
        adj = self._adjacency()
        raw: dict[str, float] = {}
        trace: list[dict] = []
        deferred: list[dict] = []
        # crisis correlation convergence: 0 (calm) .. 1 (full panic)
        conv = 0.0
        if regime and regime.get("risk_appetite") is not None:
            conv = max(0.0, min(1.0, (-float(regime["risk_appetite"]) - 0.35) / 0.65))
        # frontier entries: (node, delta_to_push, edge_arrived_by | None)
        frontier: list[tuple[str, float, Optional[Edge]]] = []
        for n, v in impulses.items():
            if n in self.nodes and abs(v) > 1e-4:
                v = max(-1.0, min(1.0, v))
                raw[n] = raw.get(n, 0.0) + v
                frontier.append((n, v, None))
        for hop in range(1, max_hops + 1):
            nxt: list[tuple[str, float, Optional[Edge]]] = []
            for src, delta, in_edge in frontier:
                for dst, sign, w, edge in adj.get(src, []):
                    if edge is in_edge:
                        continue           # no instant echo back along the same edge
                    g_sign, g_w = edge.gated(regime)
                    if g_w == 0.0:
                        continue           # muted outside its regime band
                    if conv > 0 and edge.type in ("member_of", "correlates_with"):
                        w = w + (1.0 - w) * conv * 0.6   # correlations -> 1 in a crash
                    contrib = delta * sign * g_sign * w * g_w * decay
                    if abs(contrib) < 0.015:
                        continue
                    if edge.delay_days > 0:
                        dst_type = self.nodes[dst].type if dst in self.nodes else ""
                        now_part = 0.0
                        if dst_type in self._PRICED_TYPES:
                            now_part = contrib * self.ANTICIPATION
                        later = contrib - now_part
                        deferred.append({"node": dst, "contribution": round(later, 4),
                                         "delay_days": edge.delay_days, "via": src,
                                         "edge_type": edge.type})
                        if abs(now_part) < 0.015:
                            continue
                        raw[dst] = raw.get(dst, 0.0) + now_part
                        nxt.append((dst, now_part, edge))
                        trace.append({"from": src, "to": dst, "edge_type": edge.type,
                                      "hop": hop, "contribution": round(now_part, 4),
                                      "anticipated": True})
                        continue
                    raw[dst] = raw.get(dst, 0.0) + contrib
                    nxt.append((dst, contrib, edge))
                    trace.append({"from": src, "to": dst, "edge_type": edge.type,
                                  "hop": hop, "contribution": round(contrib, 4)})
            if not nxt:
                break
            frontier = nxt
        impacts = {n: round(math.tanh(v), 4) for n, v in raw.items()}
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

    def detect_circular_financing(self, max_len: int = 5) -> list[dict]:
        """Spot round-tripped money — the value-inflation circles where the
        same dollar is booked as growth by everyone it passes through.

        Two detections:
        1. Direct vendor financing: A OWNS a stake in B while ALSO supplying B
           (A invests, B spends the investment on A's product).
        2. Multi-party round-trips: cycles in the MONEY-FLOW digraph, where
           money moves along `owns` edges as investment (owner -> holding) and
           along `supplies` edges as payment (customer -> supplier). E.g.
           NVDA -invests-> OpenAI -pays-> Oracle -pays-> NVDA: every leg is a
           legitimate transaction, every financial statement looks great, and
           part of it is still the same dollar going in a circle. Private
           hubs (no ticker) count as participants — the loop is real even
           when its center can't be traded.

        The adviser discounts long conviction on every participant; the
        valuation anchors apply a standing haircut (statements flattered by
        circular revenue are structurally less trustworthy)."""
        loops: list[dict] = []
        owns_e = {(e.src, e.dst): e for e in self.edges if e.type == "owns"}
        supplies = {(e.src, e.dst): e for e in self.edges if e.type == "supplies"}

        def _strength(e: Edge) -> float:
            return max(0.0, min(1.0, e.weight)) * max(0.0, min(1.0, e.confidence))

        for (a, b), oe in owns_e.items():
            e = supplies.get((a, b)) or supplies.get((b, a))
            if e is not None:
                na, nb = self.nodes.get(a), self.nodes.get(b)
                loops.append({
                    "investor": a, "counterparty": b, "participants": [a, b],
                    "labels": f"{na.label if na else a} ↔ {nb.label if nb else b}",
                    "pattern": "owns + supplies (vendor financing)",
                    "severity": round(min(_strength(oe), _strength(e)), 3),
                    "note": e.note or "capital goes out as investment, comes back as revenue",
                })
        # --- multi-party: cycles in the money-flow digraph ---
        # A circle is only as fake as its THINNEST leg, so severity = min leg
        # strength (weight x confidence) around the loop.
        flow: dict[str, list[tuple[str, str, float]]] = {}
        for e in self.edges:
            if e.type == "owns":
                flow.setdefault(e.src, []).append((e.dst, "invests in", _strength(e)))
            elif e.type == "supplies":
                flow.setdefault(e.dst, []).append((e.src, "pays", _strength(e)))
        seen: set[frozenset] = {frozenset(lp["participants"]) for lp in loops}

        def dfs(start: str, node: str, path: list[tuple[str, str, float]]) -> None:
            for nxt, verb, st in flow.get(node, []):
                if nxt == start and len(path) >= 2:
                    members = [start] + [p[0] for p in path]
                    key = frozenset(members)
                    if key in seen:
                        continue
                    seen.add(key)
                    labels = [self.nodes[m].label if m in self.nodes else m for m in members]
                    verbs = [p[1] for p in path] + [verb]
                    chain = labels[0]
                    for lab, vb in zip(labels[1:] + [labels[0]], verbs):
                        chain += f" -{vb}-> {lab}"
                    loops.append({
                        "investor": start, "counterparty": members[1],
                        "participants": members,
                        "labels": " ↔ ".join(labels),
                        "pattern": f"{len(members)}-party money round-trip",
                        "severity": round(min([p[2] for p in path] + [st]), 3),
                        "note": chain,
                    })
                elif nxt != start and all(nxt != p[0] for p in path) and len(path) < max_len - 1:
                    if nxt > start:      # canonical start = smallest id, kills duplicates
                        dfs(start, nxt, path + [(nxt, verb, st)])

        for n in sorted(flow):
            dfs(n, n, [])
        return loops

    # -- growth: LLM-proposed nodes -------------------------------------------
    def propose_node(self, node_id: str, label: str, aliases: list[str] | None = None,
                     proposed_by: str = "", ts: str = "") -> bool:
        """Create a PRIVATE-COMPANY hub node from digested news (no symbol —
        never tradable, but it propagates shocks and anchors circular-financing
        detection). This is how the graph scales to new deal hubs (the next
        OpenAI) without a code change. Provenance is recorded in `state` since
        Node has no provenance field; curated seeds always win on id clash."""
        node_id = re.sub(r"[^a-z0-9_]", "", node_id.lower().replace(" ", "_").replace("-", "_"))
        if not node_id or node_id in self.nodes:
            return False
        self.nodes[node_id] = Node(
            id=node_id, type="asset", label=f"{label} (private)"[:60],
            aliases=[a.lower() for a in (aliases or []) if a][:6],
            state=f"llm-proposed {ts[:10]}: {proposed_by[:120]}")
        self._adj = None
        self._alias_index = None
        return True

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
