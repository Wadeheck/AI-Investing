"""The scalability criterion: a money circle must surface from DIGESTED NEWS
alone — private hub auto-created, legs accrued, cycle detected — with zero
company-specific code."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ai_investing.brain.deals import apply_deals, resolve
from ai_investing.brain.graph import Edge, KnowledgeGraph, Node


def _fresh_graph():
    """A graph that knows Nvidia and Oracle but has NO circle wiring and has
    never heard of OpenAI."""
    return KnowledgeGraph(
        [Node(id="nvda", type="asset", label="Nvidia", symbol="NVDA", market="US"),
         Node(id="oracle", type="asset", label="Oracle", symbol="ORCL", market="US",
              aliases=["orcl"])],
        [])


def _ev(summary, deals, cred=0.8):
    return {"summary": summary, "credibility": cred, "is_noise": False, "deals": deals}


def test_triangle_emerges_from_three_headlines():
    g = _fresh_graph()
    # Day 1: "Nvidia to invest up to $100bn in OpenAI"
    r1 = apply_deals(g, [_ev("Nvidia invests $100bn in OpenAI",
                             [{"party_a": "Nvidia", "party_b": "OpenAI",
                               "kind": "invests_in", "value_usd_bn": 100}])], ts="2026-01-01")
    assert "openai" in r1["nodes_created"]          # private hub auto-created
    assert g.nodes["openai"].symbol == ""           # and never tradable
    # Day 2: "OpenAI signs $300bn compute deal with Oracle"  (Oracle supplies OpenAI)
    apply_deals(g, [_ev("OpenAI signs $300bn Oracle compute deal",
                        [{"party_a": "Oracle", "party_b": "OpenAI",
                          "kind": "supplies", "value_usd_bn": 300}])], ts="2026-01-02")
    # Day 3: "Oracle orders $40bn of Nvidia GPUs"  (Nvidia supplies Oracle)
    r3 = apply_deals(g, [_ev("Oracle buys $40bn of Nvidia chips",
                             [{"party_a": "Nvidia", "party_b": "Oracle",
                               "kind": "supplies", "value_usd_bn": 40}])], ts="2026-01-03")
    tri = [lp for lp in r3["loops"] if set(lp["participants"]) == {"nvda", "openai", "oracle"}]
    assert tri, "circle must be detected from news-derived edges alone"
    assert 0 < tri[0]["severity"] <= 0.6            # llm legs capped below curated
    assert "-invests in->" in tri[0]["note"]


def test_entity_resolution_handles_suffixes_and_aliases():
    g = _fresh_graph()
    assert resolve(g, "NVIDIA Corp") == "nvda"
    assert resolve(g, "Oracle Corporation") == "oracle"
    assert resolve(g, "orcl") == "oracle"
    assert resolve(g, "Totally Unknown Startup") is None


def test_immaterial_unknown_party_is_dropped_not_noded():
    g = _fresh_graph()
    r = apply_deals(g, [_ev("Nvidia backs tiny startup",
                            [{"party_a": "Nvidia", "party_b": "TinyStartup",
                              "kind": "invests_in", "value_usd_bn": 0.05}])])
    assert r["nodes_created"] == [] and r["edges_added"] == []
    assert r["dropped"]


def test_corroboration_bumps_confidence_not_past_cap():
    g = _fresh_graph()
    deal = [{"party_a": "Nvidia", "party_b": "Oracle", "kind": "supplies",
             "value_usd_bn": 40}]
    apply_deals(g, [_ev("chips deal reported", deal, cred=0.5)])
    e = next(e for e in g.edges if e.type == "supplies")
    c1 = e.confidence
    apply_deals(g, [_ev("chips deal confirmed by both companies", deal, cred=0.9)])
    assert e.confidence > c1 and e.confidence <= 0.6


def test_noise_events_never_wire_the_graph():
    g = _fresh_graph()
    r = apply_deals(g, [{"summary": "pump post", "credibility": 0.1, "is_noise": True,
                         "deals": [{"party_a": "Nvidia", "party_b": "OpenAI",
                                    "kind": "invests_in", "value_usd_bn": 100}]}])
    assert r["nodes_created"] == [] and r["edges_added"] == []
