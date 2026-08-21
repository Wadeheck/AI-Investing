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
    reviewed_at: str = ""        # ISO ts a human ruled on this llm edge and KEPT it.
                                 # Deliberately does NOT raise confidence past the
                                 # 0.6 cap: a human "keep" says the mechanism is
                                 # plausible, not that it predicts. Only evidence
                                 # may promote wiring (LEARNING.md §2), and the
                                 # calibrator cannot reach these edges at all —
                                 # none terminates on a tradable symbol, so
                                 # `_score_pair` has no price series to score.
                                 # Review therefore clears the QUEUE, never the bar.
    reviewed_note: str = ""      # why it was kept, in the reviewer's words
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
        for k in ("note", "proposed_by", "proposed_at", "reviewed_at", "reviewed_note"):
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
    def __init__(self, nodes: list[Node], edges: list[Edge],
                 rejected: Optional[list[dict]] = None):
        self.nodes: dict[str, Node] = {n.id: n for n in nodes}
        self.edges: list[Edge] = edges
        # Tombstones for llm edges a human reviewed and threw out. Without these,
        # review is not durable: propose_edge dedupes only against edges that
        # currently EXIST, so a rejected edge is re-proposed by the next similar
        # headline and the reviewer does the same work forever.
        self.rejected: list[dict] = list(rejected or [])
        self._adj: Optional[dict] = None
        self._alias_index: Optional[dict[str, str]] = None
        self._calibration: dict[str, float] = {}   # edge key -> evidence multiplier
        # Volume control on self-wiring — see propose_edge. 0 disables it.
        # 6/day is ~42/week against a measured 88.5 and a §A10 assumption of <=1;
        # it is deliberately a reduction rather than an attempt to reach the spec,
        # because the spec's number was an estimate that has never been true and
        # the honest bar is "slower than curated wiring grows", not "1".
        self.daily_proposal_budget: int = 6
        self.budget_deferred: int = 0              # refused today for budget, not merit

    @staticmethod
    def edge_key(e: Edge) -> str:
        return f"{e.src}->{e.dst}:{e.type}"

    @staticmethod
    def pair_key(src: str, dst: str, type_: str) -> str:
        """Same shape as edge_key, addressable before an Edge exists (or after it
        has been rejected and no longer does)."""
        return f"{src}->{dst}:{type_}"

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
        g = cls(nodes, edges, d.get("rejected_edges") or [])
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
        self._absorb_disk_review(path)
        # Written via a temp file and renamed, because this file now has two
        # writers: the engine on its own cycle, and a human running the review
        # tool whenever they happen to. `open(path, "w")` truncates first, so an
        # ill-timed crash or an overlapping write leaves a half-written graph —
        # and the loader would either fail outright or, worse, read a truncated
        # edge list as a smaller graph. os.replace is atomic within a filesystem,
        # so a reader sees the old file or the new one and never a partial.
        tmp = f"{path}.tmp"
        with open(tmp, "w") as fh:
            json.dump({"seed_version": SEED_VERSION,
                       "nodes": [n.to_dict() for n in self.nodes.values()],
                       "edges": [e.to_dict() for e in self.edges],
                       # Always written, even when empty: a reviewer opening this
                       # file should be able to see that rejection is a thing the
                       # graph records, without having to find the code first.
                       "rejected_edges": self.rejected}, fh, indent=1)
        os.replace(tmp, path)

    def save_review(self, path: str) -> None:
        """Persist ONLY review decisions, against the file as it stands right now.

        `save()` writes this object's whole edge and node list, which is correct
        for the engine — it owns that state — and quietly destructive for a review
        session, which does not. A reviewer loads the graph, reads for a while,
        and saves; the engine adds edges several times a day (~35/week). Anything
        it added inside that window would be absent from the reviewer's in-memory
        list and would vanish on write, with nothing to indicate wiring had been
        lost. The reviewer holds a stale copy by construction, so it must never
        write one back.

        So this re-reads the file at the moment of writing and applies only the
        deltas a reviewer can legitimately make: stamp kept edges, drop rejected
        ones, carry the tombstones. Disk owns the nodes and every edge not ruled
        on — including the ones added while the reviewer was reading."""
        from ai_investing.brain.seed import SEED_VERSION
        try:
            with open(path) as fh:
                d = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"cannot read {path} to apply review: {exc}") from exc

        stamps = {self.edge_key(e): (e.reviewed_at, e.reviewed_note)
                  for e in self.edges if e.provenance == "llm" and e.reviewed_at}
        tombs = self._rejected_index()

        edges_out = []
        for raw in d.get("edges") or []:
            key = self.pair_key(raw.get("src", ""), raw.get("dst", ""), raw.get("type", ""))
            if raw.get("provenance") == "llm" and key in tombs:
                continue                                  # rejected — drop it
            if key in stamps and raw.get("provenance") == "llm":
                raw["reviewed_at"], raw["reviewed_note"] = stamps[key]
            edges_out.append(raw)

        merged = {self.pair_key(r.get("src", ""), r.get("dst", ""), r.get("type", "")): r
                  for r in (d.get("rejected_edges") or [])}
        for key, r in tombs.items():
            cur = merged.get(key)
            if cur is None:
                merged[key] = dict(r)
            else:
                cur["suppressed"] = max(int(cur.get("suppressed", 0)),
                                        int(r.get("suppressed", 0)))
                cur["reason"] = r.get("reason", cur.get("reason", ""))
                cur["rejected_at"] = r.get("rejected_at", cur.get("rejected_at", ""))

        tmp = f"{path}.tmp"
        with open(tmp, "w") as fh:
            json.dump({"seed_version": d.get("seed_version", SEED_VERSION),
                       "nodes": d.get("nodes") or [],      # disk owns the nodes
                       "edges": edges_out,
                       "rejected_edges": list(merged.values())}, fh, indent=1)
        os.replace(tmp, path)

    def _absorb_disk_review(self, path: str) -> None:
        """Fold review decisions made on disk into this in-memory graph before
        overwriting it.

        The engine loads the graph ONCE at Brain construction and holds it for the
        life of the process, then rewrites the whole file whenever it adds an edge
        (`core.py::_persist`). A reviewer editing that file out-of-band would
        therefore have every decision silently reverted by the next proposal —
        review that evaporates is worse than no review, because it looks like it
        worked. Rather than demand a restart after each review (a rule that has to
        be remembered exactly when someone is mid-task), the writer reconciles.

        Safe to merge blindly because review state is MONOTONE: a keep or a reject
        is never withdrawn by the engine, only ever added by a human. Where both
        sides touched the same tombstone, `suppressed` takes the max rather than
        the sum — both counts descend from a common ancestor, so adding them would
        double-count the shared history."""
        try:
            with open(path) as fh:
                d = json.load(fh)
        except (OSError, json.JSONDecodeError):
            return                      # first write, or a file we cannot read
        disk_tombs = {self.pair_key(r.get("src", ""), r.get("dst", ""), r.get("type", "")): r
                      for r in (d.get("rejected_edges") or [])}
        disk_reviewed = {self.pair_key(e.get("src", ""), e.get("dst", ""), e.get("type", "")):
                         (e.get("reviewed_at", ""), e.get("reviewed_note", ""))
                         for e in (d.get("edges") or []) if e.get("reviewed_at")}

        mine = self._rejected_index()
        for key, r in disk_tombs.items():
            cur = mine.get(key)
            if cur is None:
                self.rejected.append(dict(r))
            else:
                cur["suppressed"] = max(int(cur.get("suppressed", 0)),
                                        int(r.get("suppressed", 0)))
                # Whichever side rejected it LAST owns the stated reason.
                if str(r.get("rejected_at", "")) > str(cur.get("rejected_at", "")):
                    cur["reason"] = r.get("reason", cur.get("reason", ""))
                    cur["rejected_at"] = r.get("rejected_at", "")

        tombs = self._rejected_index()
        kept: list[Edge] = []
        for e in self.edges:
            key = self.edge_key(e)
            stamp = disk_reviewed.get(key)
            if stamp and e.provenance == "llm" and not e.reviewed_at:
                e.reviewed_at, e.reviewed_note = stamp
            tomb = tombs.get(key) if e.provenance == "llm" else None
            if tomb is not None:
                # Proposed again in memory after a human rejected it on disk.
                # The tombstone wins, and the argument is recorded rather than lost.
                tomb["suppressed"] = int(tomb.get("suppressed", 0)) + 1
                tomb["last_seen"] = e.proposed_at or tomb.get("last_seen", "")
                tomb["last_proposed_by"] = e.proposed_by or tomb.get("last_proposed_by", "")
                self._adj = None
                continue
            kept.append(e)
        self.edges = kept

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

    def predecessors(self, node_id: str, k: Optional[int] = None) -> list[tuple[str, float]]:
        """Nodes whose activation reaches `node_id` directly (one hop), by
        |weight| descending -- the inverse of `_adjacency()`, which lists
        who a node reaches, not who reaches it. Used to find what's actually
        DRIVING a node (e.g. brain/persistence.py's look-through for an asset
        whose own landed activation hasn't itself sustained saturation)."""
        adj = self._adjacency()
        out: list[tuple[str, float]] = []
        for src, neighbors in adj.items():
            for dst, _sign, w, _e in neighbors:
                if dst == node_id and w > 0:
                    out.append((src, w))
        out.sort(key=lambda t: -t[1])
        return out[:k] if k else out

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
    # A NON-ANSWER IS NOT AN ENTITY. Asked for a counterparty the extractor
    # sometimes has none to give, and answers "none", "undisclosed", "multiple
    # banks", "a Saudi-led investor". Those went straight through propose_node
    # and became asset nodes with real edges.
    #
    # What that cost, found 2026-08-21: a node literally called `none` had
    # accumulated 23 llm edges and was the 17th most connected node in the live
    # graph — skhynix -owns-> none 0.24, tsmc -owns-> none 0.50, avgo 0.35,
    # `amazon_alphabet_microsoft` (itself a merged non-entity) 0.50, xrp 0.05.
    # `owns` flows REVERSE (EDGE_FLOW), so any shock landing on `none` flowed
    # back out into TSMC at half strength. A junk collector wired as a
    # transmission hub between semiconductors, megacap tech and XRP.
    #
    # Refused by shape rather than by blocklist, so the next phrasing of "I
    # don't know" is refused too — the blocklist alone would have caught `none`
    # and missed `unnamed_acquirer`.
    _NON_ENTITY_IDS = frozenset({
        "none", "null", "na", "n_a", "nil", "unknown", "unspecified", "undisclosed",
        "other", "others", "various", "tbd", "not_applicable", "not_disclosed",
        "private", "private_investor", "private_investors", "anonymous",
        "undisclosed_buyer", "undisclosed_investor", "multiple_banks", "public_markets",
    })
    _NON_ENTITY_MARKERS = ("unnamed", "undisclosed", "unknown", "anonymous",
                           "consortium", "multiple_", "several_", "various_",
                           "_led_investor", "_and_others", "unidentified")

    # A SECOND kind of non-entity, found 2026-08-21 among the unwired nodes:
    # not "we do not know who", but "this is not ONE thing". The digester had
    # created `amazon_alphabet_microsoft` (three companies in one node),
    # `uk_domestic_chip_startups` (a category) and `fenway_sports__liverpool_fc`
    # (two entities joined by a separator). A node that is three companies
    # cannot have a coherent response signature — it is guaranteed to be either
    # inert or wrong, and it inflates the node count either way.
    _CATEGORY_SUFFIXES = ("_startups", "_companies", "_firms", "_makers",
                          "_producers", "_miners", "_banks", "_lenders",
                          "_retailers", "_suppliers", "_stocks", "_names",
                          "_players", "_operators", "_manufacturers")

    @classmethod
    def is_non_entity(cls, node_id: str, node_type: str = "asset") -> bool:
        """True when an id cannot be the thing its TYPE says it is.

        Two families, failing for different reasons:
          PLACEHOLDER    "no named counterparty" — `none`, `undisclosed_buyer`.
                         Wrong for every node type.
          NOT-ONE-THING  several entities in one id, or a category standing
                         where a member of one belongs. Wrong for an ASSET and
                         perfectly right for a theme.

        `node_type` is load-bearing, and the seed taught it. A first version
        applied the category rule to every id and flagged three CURATED nodes —
        `uk_banks`, `sg_banks`, `china_property_stocks`. Those are theme nodes,
        and a theme node naming a category is not a defect, it is the
        definition. `propose_node` only ever mints assets, so the strict rule
        still covers the path that actually admits junk.
        """
        nid = (node_id or "").strip().lower()
        if not nid or nid in cls._NON_ENTITY_IDS:
            return True
        if any(m in nid for m in cls._NON_ENTITY_MARKERS):
            return True
        # "X / Y" survives id-normalisation as a DOUBLE underscore: two entities
        # joined by a separator, never one company's own name. True of any type.
        if "__" in nid:
            return True
        if node_type != "asset":
            return False
        # A plural category standing where a company belongs. Deliberately NOT
        # a rule: a bare `_and_`, because `larsen_and_toubro` and
        # `johnson_and_johnson` are single companies whose own names contain it.
        # A false positive here refuses a real company permanently, so every
        # rule has to be one that cannot fire on a legitimate name.
        return any(nid.endswith(sfx) for sfx in cls._CATEGORY_SUFFIXES)

    def propose_node(self, node_id: str, label: str, aliases: list[str] | None = None,
                     proposed_by: str = "", ts: str = "", symbol: str = "",
                     market: str = "") -> bool:
        """Create a hub node from digested news. This is how the graph scales to
        new companies (the next OpenAI, the next IPO) without a code change.
        Provenance is recorded in `state` since Node has no provenance field;
        curated seeds always win on id clash.

        Two flavors, distinguished by whether a symbol is known:
          - no symbol (deals.py invests_in/supplies/acquires on an unresolved
            private party): labeled "(private)" — never tradable, but still
            propagates shocks and anchors circular-financing detection.
          - symbol given (deals.py lists_on, an IPO/listing event): a REAL
            tradable node, same as a curated one, just llm-sourced — no
            "(private)" suffix, and graph_stock_symbols() will pick it up for
            fundamentals once symbol+market are both set."""
        node_id = re.sub(r"[^a-z0-9_]", "", node_id.lower().replace(" ", "_").replace("-", "_"))
        if not node_id or node_id in self.nodes:
            return False
        if self.is_non_entity(node_id):
            return False        # a non-answer is not an entity — see above
        display_label = label if symbol else f"{label} (private)"
        self.nodes[node_id] = Node(
            id=node_id, type="asset", label=display_label[:60],
            aliases=[a.lower() for a in (aliases or []) if a][:6],
            symbol=symbol, market=market,
            state=f"llm-proposed {ts[:10]}: {proposed_by[:120]}")
        self._adj = None
        self._alias_index = None
        return True

    # -- growth: LLM-proposed edges -------------------------------------------
    def propose_edge(self, src: str, dst: str, type_: str, sign: int, weight: float,
                     confidence: float, proposed_by: str, ts: str) -> bool:
        """Append an LLM-proposed edge (never overwrites a curated one). Returns
        True if added. Proposed edges carry provenance for periodic human review.

        A previously REJECTED pair is refused — but never silently. The refusal
        is counted on the tombstone, because an edge the world keeps re-proposing
        is evidence the rejection may have been wrong, and burying that would
        repeat the mistake this codebase has now made four times: rendering a
        verdict nothing will ever grade. `contested_rejections()` is how it comes
        back for a second hearing (see `scripts/review_edges.py --contested`).

        A DAILY BUDGET bounds the stream. DIGESTION_SPEC §A10 justifies applying
        llm edges automatically because "a bad proposal is damped by the cap" and
        "Rare: expect <=1 per week". Measured 2026-08-21: 88.5/week, 131 in the
        last 7 days, 354 pending review and — the part that matters —
        `reviewed & kept: 0`. The review queue built as the control surface for
        this has never been used once, on any edge, ever, so in practice there
        was no control surface at all and llm wiring reaches parity with the 802
        curated edges in about five weeks.

        Review is a control on QUALITY and needs a human. A budget is a control
        on VOLUME and does not — it holds regardless of how noisy the extractor
        is on any given day, which is the property §A10 assumed and never had.
        Edges refused for budget are not tombstoned: nothing is being judged
        wrong, only deferred, and a genuinely recurring relationship will be
        re-proposed tomorrow.
        """
        if src not in self.nodes or dst not in self.nodes or type_ not in EDGE_FLOW:
            return False
        if self.daily_proposal_budget and ts:
            if self.proposals_on(ts[:10]) >= self.daily_proposal_budget:
                self.budget_deferred += 1
                return False
        for e in self.edges:
            if e.src == src and e.dst == dst and e.type == type_:
                return False
        tomb = self._rejected_index().get(self.pair_key(src, dst, type_))
        if tomb is not None:
            tomb["suppressed"] = int(tomb.get("suppressed", 0)) + 1
            tomb["last_seen"] = ts
            tomb["last_proposed_by"] = proposed_by[:160]
            return False
        self.edges.append(Edge(src=src, dst=dst, type=type_, sign=1 if sign >= 0 else -1,
                               weight=max(0.05, min(1.0, weight)),
                               confidence=max(0.05, min(0.6, confidence)),  # capped below curated
                               provenance="llm", proposed_by=proposed_by[:160], proposed_at=ts))
        self._adj = None
        return True

    # -- review: the only control these edges will ever get --------------------
    #
    # DIGESTION_SPEC §A10 chose auto-apply over a queue: "a bad proposal is damped
    # by the cap, not blocked by a queue". That argument is sound at the rate the
    # spec assumed — "Rare: expect <=1 per week". It is doing much more work than
    # intended at the rate actually observed, and nothing was measuring the gap.
    # The cap still holds; what follows is the review the spec promised but never
    # built, so the backlog can be worked down instead of only growing.

    def _rejected_index(self) -> dict[str, dict]:
        """key -> tombstone record. Rebuilt per call: the list is small (one row
        per human rejection, ever) and a stale cache here would silently let a
        rejected edge back in, which is the one failure this mechanism exists to
        prevent."""
        return {self.pair_key(r.get("src", ""), r.get("dst", ""), r.get("type", "")): r
                for r in self.rejected}

    def pending_review(self) -> list[Edge]:
        """LLM edges no human has ruled on yet, oldest proposal first — review
        order should follow how long an edge has been steering unvetted."""
        return sorted((e for e in self.edges
                       if e.provenance == "llm" and not e.reviewed_at),
                      key=lambda e: e.proposed_at or "")

    def review_edge(self, src: str, dst: str, type_: str, note: str, ts: str) -> bool:
        """Keep an llm edge and stamp it reviewed. Confidence is untouched — see
        the note on `Edge.reviewed_at` for why a human keep is not a promotion."""
        for e in self.edges:
            if e.src == src and e.dst == dst and e.type == type_:
                if e.provenance != "llm":
                    return False        # curated wiring is not this tool's business
                e.reviewed_at = ts
                e.reviewed_note = note[:200]
                return True
        return False

    def reject_edge(self, src: str, dst: str, type_: str, reason: str, ts: str) -> bool:
        """Remove an llm edge and tombstone the pair so it does not walk back in.

        Curated edges are refused outright rather than tombstoned: `_merge_seed`
        re-appends seed wiring on every version bump without consulting this list
        (correctly — curated always wins), so a tombstone over a seed edge would
        be a rule that silently does nothing. Better to refuse than to pretend."""
        key = self.pair_key(src, dst, type_)
        for i, e in enumerate(self.edges):
            if e.src == src and e.dst == dst and e.type == type_:
                if e.provenance != "llm":
                    return False
                del self.edges[i]
                break
        existing = self._rejected_index().get(key)
        if existing is not None:
            existing["reason"] = reason[:200]
            existing["rejected_at"] = ts
            return True
        self.rejected.append({"src": src, "dst": dst, "type": type_,
                              "reason": reason[:200], "rejected_at": ts,
                              "suppressed": 0, "last_seen": "", "last_proposed_by": ""})
        self._adj = None
        return True

    def prune_non_entities(self, ts: str) -> dict:
        """Remove placeholder nodes admitted before `propose_node` refused them,
        and tombstone every edge they carried so the same wiring cannot walk back
        in on the next digest.

        Curated nodes are never touched — only nodes whose `state` records an
        llm origin, which is the only provenance mark Node carries.

        Returns {"nodes": [...], "edges": n} for the caller to report.
        """
        victims = [nid for nid, n in self.nodes.items()
                   if self.is_non_entity(nid, n.type)
                   and str(n.state or "").startswith("llm-proposed")]
        removed_edges = 0
        for nid in victims:
            for e in [e for e in self.edges if e.src == nid or e.dst == nid]:
                # tombstone first (it records WHY), then drop the edge
                if e.provenance == "llm":
                    self.reject_edge(e.src, e.dst, e.type,
                                     f"non-entity node '{nid}': a placeholder for "
                                     f"'no named counterparty', not a company", ts)
                else:
                    self.edges.remove(e)
                removed_edges += 1
            self.nodes.pop(nid, None)
        if victims:
            self._adj = None
            self._alias_index = None
        return {"nodes": victims, "edges": removed_edges}

    def orphan_nodes(self) -> list[str]:
        """LLM-proposed nodes with no edges at all — they cannot transmit or
        receive a shock, so they are vocabulary, not wiring. Curated nodes are
        excluded: an unwired seed node is a gap to FILL (see
        scripts/graph_gap_scan.py), not something to delete."""
        wired = {e.src for e in self.edges} | {e.dst for e in self.edges}
        return sorted(nid for nid, n in self.nodes.items()
                      if nid not in wired and str(n.state or "").startswith("llm-proposed"))

    def prune_stale_orphans(self, ts: str, min_age_days: int = 30) -> list[str]:
        """Delete LLM-proposed nodes that never acquired a single edge.

        `orphan_nodes()` has been able to NAME these since §4.26; nothing ever
        removed them, so they accumulated — 31 of them by 2026-08-21, against
        609 nodes. They are the residue of the digester meeting a company name
        in a sentence and minting a node for it that no later story ever wired
        to anything.

        Why age and not shape: a node proposed today may be wired tomorrow by
        the next story about it, so deleting on sight would fight the digester.
        A node that has sat unwired for a MONTH is not waiting for wiring, it is
        vocabulary. That is a measurement, not a judgement about the name — the
        thing the review queue keeps failing to supply.

        Deliberately NOT tombstoned. A tombstone records a rejected CLAIM, and
        no claim was made here — nothing was ever asserted about these nodes.
        If the same company appears in a real relationship later, it should be
        free to come back with that relationship attached.

        Curated nodes are never touched: an unwired seed node is a gap to FILL
        (`scripts/graph_gap_scan.py`), which is the opposite problem.
        """
        import datetime as _dt
        try:
            now = _dt.date.fromisoformat(str(ts)[:10])
        except ValueError:
            return []
        removed = []
        for nid in self.orphan_nodes():
            m = re.search(r"llm-proposed (\d{4}-\d{2}-\d{2})", str(self.nodes[nid].state or ""))
            if not m:
                continue                      # no date to age against — leave it
            try:
                born = _dt.date.fromisoformat(m.group(1))
            except ValueError:
                continue
            if (now - born).days >= min_age_days:
                self.nodes.pop(nid, None)
                removed.append(nid)
        if removed:
            self._adj = None
            self._alias_index = None
        return sorted(removed)

    def contested_rejections(self, min_suppressed: int = 3) -> list[dict]:
        """Tombstones the world keeps arguing with, most-argued first. A rejection
        re-proposed many times is the graph's version of noise-rescue: the source
        that keeps being right while flagged should be able to climb back out."""
        return sorted((r for r in self.rejected
                       if int(r.get("suppressed", 0)) >= min_suppressed),
                      key=lambda r: -int(r.get("suppressed", 0)))

    def proposals_on(self, day: str) -> int:
        """LLM edges proposed on a given YYYY-MM-DD. The budget's meter."""
        return sum(1 for e in self.edges
                   if e.provenance == "llm" and (e.proposed_at or "")[:10] == day)

    def proposal_rate(self, since_iso: str) -> int:
        """LLM edges proposed on or after `since_iso`. The number that matters is
        the RATE, not the backlog: a backlog says work is waiting, a rate says
        whether the design's core assumption still holds."""
        return sum(1 for e in self.edges
                   if e.provenance == "llm" and (e.proposed_at or "") >= since_iso)
