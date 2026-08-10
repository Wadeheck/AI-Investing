"""Review of self-added wiring has to survive the engine that writes the file.

The failure this guards against is not "review is wrong", it is "review silently
evaporates": the engine loads the graph once at Brain construction and rewrites
the whole file whenever it adds an edge, so a decision made on disk in between
would be reverted by a process that never knew about it — and would look like it
had worked. Every test below is a way that could happen.
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ai_investing.brain.graph import Edge, KnowledgeGraph, Node

TS = "2026-08-10T00:00:00+00:00"
LATER = "2026-08-11T00:00:00+00:00"


def _graph():
    """Two factors and one asset, no wiring — proposals have somewhere to land."""
    return KnowledgeGraph(
        [Node(id="power_demand", type="factor", label="Power demand"),
         Node(id="uranium_price", type="commodity", label="Uranium price"),
         Node(id="nvda", type="asset", label="Nvidia", symbol="NVDA", market="US")],
        [])


def _propose(g, src="power_demand", dst="uranium_price", by="reactor restarts"):
    return g.propose_edge(src, dst, "influences", 1, 0.3, 0.4, by, TS)


def test_proposed_edge_starts_unreviewed_and_queues():
    g = _graph()
    assert _propose(g) is True
    assert len(g.pending_review()) == 1
    assert g.pending_review()[0].reviewed_at == ""


def test_keeping_an_edge_clears_the_queue_without_promoting_it():
    """A human keep is not evidence. The cap is what makes auto-application safe
    and review must not quietly undo it."""
    g = _graph()
    _propose(g)
    conf_before = g.edges[0].confidence
    assert g.review_edge("power_demand", "uranium_price", "influences", "real channel", TS)
    assert g.pending_review() == []
    assert g.edges[0].confidence == conf_before
    assert g.edges[0].reviewed_note == "real channel"


def test_rejecting_removes_the_edge_and_blocks_re_proposal():
    g = _graph()
    _propose(g)
    assert g.reject_edge("power_demand", "uranium_price", "influences", "no mechanism", TS)
    assert g.edges == []
    # The next similar headline must not walk it back in.
    assert _propose(g) is False
    assert g.edges == []


def test_a_suppressed_re_proposal_is_counted_never_silent():
    """The rejection stands, but the argument against it is recorded — otherwise
    this is a verdict nothing can ever grade."""
    g = _graph()
    _propose(g)
    g.reject_edge("power_demand", "uranium_price", "influences", "speculative", TS)
    for i in range(4):
        _propose(g, by=f"story {i}")
    tomb = g.rejected[0]
    assert tomb["suppressed"] == 4
    assert tomb["last_proposed_by"] == "story 3"
    assert len(g.contested_rejections(min_suppressed=3)) == 1
    assert g.contested_rejections(min_suppressed=99) == []


def test_curated_edges_are_not_this_tools_business():
    """A tombstone over a seed edge would be a rule that does nothing: _merge_seed
    re-appends curated wiring without consulting the list. Refuse, don't pretend."""
    g = _graph()
    g.edges.append(Edge(src="power_demand", dst="nvda", type="influences",
                        sign=1, weight=0.5, confidence=1.0, provenance="seed"))
    assert g.reject_edge("power_demand", "nvda", "influences", "nope", TS) is False
    assert g.review_edge("power_demand", "nvda", "influences", "sure", TS) is False
    assert len(g.edges) == 1 and g.rejected == []


def test_review_state_round_trips_through_disk():
    g = _graph()
    _propose(g)
    _propose(g, dst="nvda")
    g.review_edge("power_demand", "uranium_price", "influences", "kept", TS)
    g.reject_edge("power_demand", "nvda", "influences", "dropped", TS)
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "graph.json")
        g.save(p)
        raw = json.load(open(p))
        assert "rejected_edges" in raw          # discoverable by a human reading the file
        back = KnowledgeGraph.load(p)
        assert back.edges[0].reviewed_at == TS
        assert back.edges[0].reviewed_note == "kept"
        assert len(back.rejected) == 1
        assert back.rejected[0]["reason"] == "dropped"
        # and the tombstone still bites after a reload
        assert back.propose_edge("power_demand", "nvda", "influences",
                                 1, 0.3, 0.4, "again", LATER) is False


def test_a_long_running_engine_cannot_revert_a_review():
    """THE one that matters. Engine loads the graph, a review happens on disk,
    the engine then adds an edge and saves its stale in-memory copy."""
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "graph.json")
        g = _graph()
        _propose(g)
        _propose(g, dst="nvda")
        g.save(p)

        engine = KnowledgeGraph.load(p)        # long-running process, holds this
        reviewer = KnowledgeGraph.load(p)      # out-of-band review session
        reviewer.review_edge("power_demand", "uranium_price", "influences", "kept", LATER)
        reviewer.reject_edge("power_demand", "nvda", "influences", "dropped", LATER)
        reviewer.save(p)

        engine.propose_node("newco", "NewCo", ts=LATER)
        engine.save(p)                          # would have clobbered both decisions

        final = KnowledgeGraph.load(p)
        keys = {final.edge_key(e) for e in final.edges}
        assert "power_demand->nvda:influences" not in keys, "rejection was reverted"
        kept = [e for e in final.edges if e.dst == "uranium_price"]
        assert kept and kept[0].reviewed_at == LATER, "keep was reverted"
        assert len(final.rejected) == 1
        assert "newco" in final.nodes, "engine's own work must survive the merge"


def test_an_edge_re_added_in_memory_loses_to_a_disk_rejection():
    """The engine re-proposes an edge it does not know was rejected, then saves.
    The tombstone wins, and the collision is counted rather than dropped."""
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "graph.json")
        g = _graph()
        g.save(p)

        engine = KnowledgeGraph.load(p)
        reviewer = KnowledgeGraph.load(p)
        reviewer.reject_edge("power_demand", "uranium_price", "influences", "no", TS)
        # reject_edge tombstones a pair even when the edge is not currently present
        reviewer.save(p)

        assert engine.propose_edge("power_demand", "uranium_price", "influences",
                                   1, 0.3, 0.4, "fresh story", LATER) is True
        engine.save(p)

        final = KnowledgeGraph.load(p)
        assert final.edges == [], "a rejected edge came back through a stale process"
        assert final.rejected[0]["suppressed"] >= 1, "the collision went unrecorded"


def test_a_review_session_cannot_discard_edges_added_while_it_read():
    """The mirror of the test above, and the one that is easy to miss. A reviewer
    holds a stale copy from the moment it loads; the engine keeps proposing into
    the same file. A full save() from the reviewer would write its stale edge
    list back and destroy the engine's work with nothing to show for it."""
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "graph.json")
        g = _graph()
        _propose(g)
        g.save(p)

        reviewer = KnowledgeGraph.load(p)          # opens the queue, starts reading

        engine = KnowledgeGraph.load(p)            # meanwhile, the engine works
        engine.propose_edge("power_demand", "nvda", "influences",
                            1, 0.4, 0.5, "datacenter buildout", LATER)
        engine.propose_node("newco", "NewCo", ts=LATER)
        engine.save(p)

        reviewer.review_edge("power_demand", "uranium_price", "influences", "kept", LATER)
        reviewer.save_review(p)

        final = KnowledgeGraph.load(p)
        keys = {final.edge_key(e) for e in final.edges}
        assert "power_demand->nvda:influences" in keys, "edge added mid-review was lost"
        assert "newco" in final.nodes, "node added mid-review was lost"
        kept = [e for e in final.edges if e.dst == "uranium_price"]
        assert kept and kept[0].reviewed_at == LATER, "the review itself did not land"


def test_review_session_rejection_still_removes_and_tombstones():
    """save_review must still do its actual job against the fresh file."""
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "graph.json")
        g = _graph()
        _propose(g)
        g.save(p)

        reviewer = KnowledgeGraph.load(p)
        reviewer.reject_edge("power_demand", "uranium_price", "influences", "no", LATER)
        reviewer.save_review(p)

        final = KnowledgeGraph.load(p)
        assert final.edges == []
        assert len(final.rejected) == 1
        assert final.propose_edge("power_demand", "uranium_price", "influences",
                                  1, 0.3, 0.4, "again", LATER) is False


def test_suppressed_counts_merge_without_double_counting():
    """Both sides descend from a common ancestor, so max() is right and sum() is
    not — a merge that inflates the count would manufacture a contested rejection
    that nobody actually argued for."""
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "graph.json")
        g = _graph()
        g.reject_edge("power_demand", "uranium_price", "influences", "no", TS)
        for _ in range(3):
            _propose(g)                      # suppressed -> 3, on disk
        g.save(p)

        other = KnowledgeGraph.load(p)       # inherits 3
        _propose(other)                      # -> 4
        other.save(p)

        assert KnowledgeGraph.load(p).rejected[0]["suppressed"] == 4


def test_proposal_rate_counts_only_llm_edges_in_window():
    g = _graph()
    g.edges.append(Edge(src="power_demand", dst="nvda", type="influences",
                        sign=1, weight=0.5, confidence=1.0, provenance="seed",
                        proposed_at=LATER))
    _propose(g)                               # llm, at TS
    assert g.proposal_rate("2026-08-09T00:00:00+00:00") == 1
    assert g.proposal_rate("2026-08-10T12:00:00+00:00") == 0


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\nAll {len(tests)} edge-review tests passed.")
