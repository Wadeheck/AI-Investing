"""Graph hygiene: what may become a node, and how fast wiring may grow.

Two defects found in the live graph on 2026-08-21, both in the self-wiring path:

  1. A node literally called `none` was the 17th most connected node in the
     graph -- 23 llm edges, `skhynix -owns-> none 0.24`, `tsmc -owns-> none
     0.50`, `avgo 0.35`, `amazon_alphabet_microsoft 0.50`, `xrp 0.05`. Asked
     for a counterparty the extractor had none to give and answered "none";
     `propose_node` created it. `owns` flows REVERSE (EDGE_FLOW), so a shock
     landing on `none` flowed back out into TSMC at half strength: a junk
     collector wired as a transmission hub between semis, megacap tech and XRP.

  2. LLM edges were being proposed at 88.5/week against DIGESTION_SPEC §A10's
     stated assumption of <=1/week -- with `reviewed & kept: 0`, i.e. the review
     queue built as the control surface had never been used once. Review is a
     control on quality and needs a human; a budget is a control on volume and
     does not.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_investing.brain.graph import KnowledgeGraph, Node, Edge

TS = "2026-08-21T00:00:00"


def _tiny():
    """Two real nodes and nothing else, so budgets are easy to reason about."""
    nodes = [Node(id="aaa", type="asset", label="A", symbol="AAA", market="US"),
             Node(id="bbb", type="asset", label="B", symbol="BBB", market="US"),
             Node(id="ccc", type="asset", label="C", symbol="CCC", market="US")]
    return KnowledgeGraph(nodes, [], [])


def test_a_non_answer_never_becomes_a_node():
    """Every shape found in the live graph, refused."""
    g = _tiny()
    for nid in ("none", "null", "n_a", "unknown", "undisclosed", "various",
                "unnamed_acquirer", "multiple_banks", "public_markets",
                "saudi_led_investor", "consortium_including_jeff_bezos_amit_bhatia",
                "undisclosed_investor", "several_lenders", "unidentified_buyer"):
        assert g.propose_node(nid, nid.replace("_", " "), proposed_by="x", ts=TS) is False, \
            f"{nid} is a placeholder for 'no named counterparty', not a company"
        assert nid not in g.nodes


def test_real_companies_are_still_admitted():
    """The filter must refuse non-answers without refusing obscure REAL names --
    the graph's whole growth path is 'the next IPO wires itself in'."""
    g = _tiny()
    for nid in ("quest_global", "cxmt", "shiprocket", "molbio_diagnostics",
                "kakao_mobility", "hengrui"):
        assert g.propose_node(nid, nid.replace("_", " "), proposed_by="x", ts=TS) is True
        assert nid in g.nodes


def test_prune_removes_placeholder_nodes_and_tombstones_their_edges():
    g = _tiny()
    # simulate the live graph: the node exists from before the filter
    g.nodes["none"] = Node(id="none", type="asset", label="None (private)",
                           state="llm-proposed 2026-08-07: SK Hynix board approved...")
    g.edges.append(Edge(src="aaa", dst="none", type="owns", sign=1, weight=0.5,
                        provenance="llm", proposed_at=TS))
    g.edges.append(Edge(src="bbb", dst="none", type="supplies", sign=1, weight=0.1,
                        provenance="llm", proposed_at=TS))

    out = g.prune_non_entities(TS)
    assert out["nodes"] == ["none"]
    assert out["edges"] == 2
    assert "none" not in g.nodes
    assert not [e for e in g.edges if e.src == "none" or e.dst == "none"]
    # tombstoned, so the next digest cannot re-add the same wiring
    assert len(g.rejected) == 2
    assert all("non-entity" in r["reason"] for r in g.rejected)


def test_prune_never_touches_curated_nodes():
    """`public_markets` matches the non-entity list, but if a human curated it
    the graph must not delete it -- only llm-proposed nodes are prunable."""
    g = _tiny()
    g.nodes["public_markets"] = Node(id="public_markets", type="theme",
                                     label="Public markets")     # no llm state
    out = g.prune_non_entities(TS)
    assert out["nodes"] == []
    assert "public_markets" in g.nodes


def test_orphan_nodes_lists_only_unwired_llm_nodes():
    g = _tiny()
    g.nodes["shiprocket"] = Node(id="shiprocket", type="asset", label="Shiprocket",
                                 state="llm-proposed 2026-08-10: funding round")
    g.nodes["wired"] = Node(id="wired", type="asset", label="Wired",
                            state="llm-proposed 2026-08-10: x")
    g.edges.append(Edge(src="aaa", dst="wired", type="owns", provenance="llm"))
    orphans = g.orphan_nodes()
    assert "shiprocket" in orphans
    assert "wired" not in orphans
    assert "aaa" not in orphans, "an unwired CURATED node is a gap to fill, not junk"


def test_daily_budget_bounds_self_wiring():
    g = _tiny()
    g.daily_proposal_budget = 2
    pairs = [("aaa", "bbb"), ("bbb", "ccc"), ("aaa", "ccc"), ("ccc", "aaa")]
    added = [g.propose_edge(a, b, "supplies", 1, 0.2, 0.4, "deal", f"2026-08-21T0{i}:00:00")
             for i, (a, b) in enumerate(pairs)]
    assert added == [True, True, False, False]
    assert g.proposals_on("2026-08-21") == 2
    assert g.budget_deferred == 2
    # deferred is NOT rejected: nothing was judged wrong, so no tombstone
    assert g.rejected == []
    # ...and tomorrow the budget resets
    assert g.propose_edge("aaa", "ccc", "supplies", 1, 0.2, 0.4, "deal",
                          "2026-08-22T00:00:00") is True


def test_budget_of_zero_disables_the_limit():
    g = _tiny()
    g.daily_proposal_budget = 0
    for i, (a, b) in enumerate([("aaa", "bbb"), ("bbb", "ccc"), ("aaa", "ccc")]):
        assert g.propose_edge(a, b, "supplies", 1, 0.2, 0.4, "d", TS) is True


def test_the_live_seed_still_loads_and_propagates():
    """A guard that none of the above broke the real graph."""
    g = KnowledgeGraph.seeded()
    assert len(g.nodes) > 400 and len(g.edges) > 700
    assert not [nid for nid in g.nodes if KnowledgeGraph.is_non_entity(nid)], \
        "the curated seed must not itself contain a placeholder id"
    impacts, _, _ = g.propagate({"fed_rate": 0.6}, max_hops=3)
    assert impacts, "seeded graph still transmits a shock"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\nAll {len(tests)} graph-hygiene tests passed.")
