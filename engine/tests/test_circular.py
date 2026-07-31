"""Circular-financing detection: multi-party money round-trips."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ai_investing.brain.graph import Edge, KnowledgeGraph, Node


def _g(edges):
    nodes = [Node(id=i, type="asset", label=i.upper(), symbol=i.upper() if i != "hub" else "")
             for i in ("a", "b", "c", "d", "hub")]
    return KnowledgeGraph(nodes, [Edge(**e) for e in edges])


def test_two_party_vendor_financing_still_detected():
    g = _g([{"src": "a", "dst": "b", "type": "owns", "weight": 0.2},
            {"src": "a", "dst": "b", "type": "supplies", "weight": 0.5}])
    loops = g.detect_circular_financing()
    assert len(loops) == 1 and loops[0]["participants"] == ["a", "b"]


def test_three_party_round_trip_through_private_hub():
    """a invests in hub; hub buys from c; c buys from a — no single pair looks
    circular, the triangle is. hub has no ticker (private) and still counts."""
    g = _g([{"src": "a", "dst": "hub", "type": "owns", "weight": 0.1},
            {"src": "c", "dst": "hub", "type": "supplies", "weight": 0.4},   # hub pays c
            {"src": "a", "dst": "c", "type": "supplies", "weight": 0.4}])    # c pays a
    loops = g.detect_circular_financing()
    tri = [lp for lp in loops if "3-party" in lp["pattern"]]
    assert len(tri) == 1
    assert set(tri[0]["participants"]) == {"a", "hub", "c"}
    assert "-invests in->" in tri[0]["note"] and "-pays->" in tri[0]["note"]


def test_no_false_positive_on_plain_supply_chain():
    """a supplies b supplies c — money flows one way, no cycle."""
    g = _g([{"src": "a", "dst": "b", "type": "supplies", "weight": 0.5},
            {"src": "b", "dst": "c", "type": "supplies", "weight": 0.5}])
    assert g.detect_circular_financing() == []


def test_live_seed_finds_the_nvda_openai_oracle_triangle():
    g = KnowledgeGraph.seeded()
    loops = g.detect_circular_financing()
    multi = [lp for lp in loops if set(lp["participants"]) == {"nvda", "openai", "oracle"}]
    assert multi, "the NVDA->OpenAI->Oracle->NVDA round-trip must be detected"
    # every classic vendor-financing pair still present
    pairs = {frozenset(lp["participants"]) for lp in loops}
    assert frozenset({"nvda", "crwv"}) in pairs
    assert frozenset({"msft", "openai"}) in pairs
    # private hubs are never tradable
    assert not any(v.get("node") in ("openai", "anthropic", "xai")
                   for v in g.asset_impacts({"openai": -0.5, "anthropic": -0.5}).values())
