"""The digester's node reference must describe the graph it teaches.

§4.34: `SONNET_DIGEST_BRIEF.md` §7 had drifted **12 nodes behind** the graph,
and nothing noticed because nothing compared them. The fix then was to
transcribe the missing twelve — which closed the instance and left the
mechanism. A reference maintained by hand against a graph that grows weekly
will drift again, and the next drift is exactly as silent as the first.

The brief is injected VERBATIM as the digester's system prompt and says "Tag
ONLY these ids", so drift is not cosmetic — it is what the digester believes.
The two directions are not symmetric:

  MISSING  in the graph, not in the brief -> the digester CANNOT tag it, so
           every story about that node lands nowhere. Silent under-coverage,
           and the expensive one. This was §4.34.
  STALE    in the brief, not in the graph -> the digester emits an id the
           runner rejects. Wasteful and noisy, but it cannot corrupt the web.

Run by hand with `python3 scripts/brief_node_audit.py`, which prints the detail.
This is the same comparison as an assertion, so a seed bump that adds a node
fails here rather than quietly teaching the digester an out-of-date map.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import brief_node_audit as bna  # noqa: E402

from ai_investing.brain.graph import KnowledgeGraph  # noqa: E402


def _seed_taggable() -> dict:
    """The CURATED seed, not a deployed graph file.

    Deliberate: a deployed graph also carries llm-proposed nodes, which are
    per-instance and are not taggable vocabulary the brief should describe. The
    seed is the thing the brief is a hand transcription of.
    """
    g = KnowledgeGraph.seeded()
    return {n.id: n.type for n in g.nodes.values() if n.type in bna.TAGGABLE_TYPES}


def test_every_taggable_seed_node_is_in_the_brief():
    """The §4.34 direction. A node the brief omits is a node the digester
    cannot tag, so news about it reaches the graph as nothing."""
    missing = sorted(set(_seed_taggable()) - bna._brief_ids(bna.BRIEF.read_text()))
    assert not missing, (
        f"{len(missing)} taggable node(s) exist in the seed and NOT in the "
        f"digester's brief — it cannot tag them: {missing}")


def test_the_brief_names_no_node_the_graph_does_not_have():
    stale = sorted(bna._brief_ids(bna.BRIEF.read_text()) - set(_seed_taggable()))
    assert not stale, f"the brief teaches ids the graph will reject: {stale}"


def test_the_briefs_own_headings_agree_with_its_table():
    """A heading that overstates completeness is how a reader concludes the
    reference is finished when it is not."""
    text = bna.BRIEF.read_text()
    stated, taggable = bna._stated_counts(text), _seed_taggable()
    by_type: dict[str, int] = {}
    for t in taggable.values():
        by_type[t] = by_type.get(t, 0) + 1
    for t, actual in sorted(by_type.items()):
        said = stated.get(bna._plural(t))
        assert said is None or said == actual, \
            f"heading says {t} ({said}), the graph has {actual}"
    assert stated.get("_total") in (None, len(taggable)), \
        f"the brief claims {stated.get('_total')} nodes, the graph has {len(taggable)}"


def test_the_parser_reads_declarations_not_every_backtick():
    """A drift detector that cries wolf gets ignored, which is worse than not
    having one. The first version matched any `backticked_word` in §7 and so
    reported a JSON field (`equilibrium`) and an edge type (`supplies`) as
    stale node ids — both are prose, neither is a declaration."""
    ids = bna._brief_ids(bna.BRIEF.read_text())
    assert "equilibrium" not in ids and "supplies" not in ids, \
        "prose mentions must not be read as node declarations"
    assert "ai_capex_cycle" in ids, "a real table row must still be found"
    assert "oil_price" in ids, "a real prose-LIST id must still be found"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\nAll {len(tests)} brief-node-reference tests passed.")
