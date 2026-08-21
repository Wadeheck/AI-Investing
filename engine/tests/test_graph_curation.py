"""Vocabulary that never became wiring, and nodes that are not one thing.

§4A carried *"198 assets are inert to every macro shock"* as curation work with
no mechanism behind it — *"wire the real companies, delete the vocabulary"*,
which is a sentence, not a process. Measured on 2026-08-21 the graph held **31
LLM-proposed nodes with zero edges**, and `orphan_nodes()` had been able to NAME
them since §4.26 while nothing ever removed them.

Reading the actual 31 showed they are not one problem but two:

  NOT ONE THING   `amazon_alphabet_microsoft` (three companies in one node),
                  `uk_domestic_chip_startups` (a category, not a member of
                  one), `fenway_sports__liverpool_fc` (two entities joined by
                  a separator). A node that is three companies cannot have a
                  coherent response signature — it is guaranteed to be inert
                  or wrong. This is a SHAPE defect, same family as §4.38's
                  `none`, and belongs in `is_non_entity`.

  NEVER WIRED     `databricks`, `skanska`, `hejing` — real, single, correctly
                  named companies the digester met in one sentence and minted
                  a node for, which no later story ever connected to anything.
                  Nothing is wrong with the NAME, so no shape rule can catch
                  them. This is an AGE defect.

The distinction matters because the fixes have opposite failure modes. A shape
rule that is too eager refuses a real company permanently. An age rule that is
too eager fights the digester, deleting nodes that would have been wired by
tomorrow's story about them.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_investing.brain.graph import Edge, KnowledgeGraph, Node  # noqa: E402


def _g(nodes, edges=()):
    return KnowledgeGraph(list(nodes), list(edges))


def _llm(nid, born="2026-01-01", label=None):
    return Node(id=nid, type="asset", label=label or nid,
                state=f"llm-proposed {born}: some headline")


# --- SHAPE: a node that is not one thing ------------------------------------

def test_a_node_naming_two_entities_is_refused():
    """`Fenway Sports Group / Liverpool FC` survives id-normalisation as a
    DOUBLE underscore. That is a separator, never a company's own name."""
    assert KnowledgeGraph.is_non_entity("fenway_sports__liverpool_fc")


def test_a_category_is_not_a_member_of_one():
    """...when it is standing where an ASSET belongs."""
    for nid in ("uk_domestic_chip_startups", "regional_banks", "lithium_miners",
                "ev_makers", "chinese_retailers"):
        assert KnowledgeGraph.is_non_entity(nid, "asset"), nid


def test_a_theme_node_naming_a_category_is_exactly_right():
    """The false positive the curated seed caught, and the reason
    `is_non_entity` takes a type at all.

    A first version applied the category rule to every id and flagged three
    CURATED nodes — `uk_banks`, `sg_banks`, `china_property_stocks`. For a
    THEME node, naming a category is not a defect, it is the definition. Only
    `propose_node` mints assets, so the strict rule still covers the path that
    actually admits junk.
    """
    for nid in ("uk_banks", "sg_banks", "china_property_stocks", "lithium_miners"):
        assert not KnowledgeGraph.is_non_entity(nid, "theme"), nid
        assert not KnowledgeGraph.is_non_entity(nid, "sector"), nid


def test_a_placeholder_is_refused_whatever_type_it_claims_to_be():
    """The type escape hatch must not become a way in for `none`."""
    for t in ("asset", "theme", "sector", "factor", "actor"):
        assert KnowledgeGraph.is_non_entity("none", t)
        assert KnowledgeGraph.is_non_entity("undisclosed_buyer", t)
        assert KnowledgeGraph.is_non_entity("fenway_sports__liverpool_fc", t)


def test_an_ampersand_becomes_and_rather_than_vanishing():
    """The false positive that reached the LIVE graph, and the reason the fix
    belongs in normalisation rather than in a rule.

    `re.sub(r"[^a-z0-9_]", "", ...)` DELETES `&`, so "Procter & Gamble" became
    `procter__gamble` — byte-identical in shape to
    "Fenway Sports Group / Liverpool FC" -> `fenway_sports_group__liverpool_fc`.
    One is a company, the other is two companies, and the character that told
    them apart was gone before any rule could look. The `__` rule then deleted
    P&G from the live graph and tombstoned a real `procter__gamble -> thorne`
    edge on 2026-08-21.

    No downstream rule could have got this right. The information has to
    survive normalisation, which is where it is fixed.
    """
    g = _g([Node(id="seed", type="asset", label="seed")])
    for name in ("Procter & Gamble", "Johnson & Johnson", "Standard & Poors"):
        assert g.propose_node(name, name, proposed_by="t", ts="2026-08-21"), name
    assert "procter_and_gamble" in g.nodes
    assert "johnson_and_johnson" in g.nodes
    assert "standard_and_poors" in g.nodes
    assert not any("__" in nid for nid in g.nodes), \
        f"an ampersand still collapses into a separator: {sorted(g.nodes)}"


def test_a_slash_still_marks_two_entities_and_is_refused():
    """The other half: with `&` handled, a surviving `__` really does come from
    a separator, so the rule that reads it is sound again."""
    g = _g([Node(id="seed", type="asset", label="seed")])
    for name in ("Fenway Sports Group / Liverpool FC",
                 "Datacenter / HFT infrastructure"):
        assert not g.propose_node(name, name, proposed_by="t", ts="2026-08-21"), name
    assert len(g.nodes) == 1, f"a two-entity name was admitted: {sorted(g.nodes)}"


def test_a_real_company_whose_name_contains_and_is_never_refused():
    """The rule deliberately omitted, and this test is why.

    `_and_` looks like a conjunction and is one — inside `larsen_and_toubro`
    and `johnson_and_johnson` it is part of a SINGLE company's registered name.
    A false positive here refuses a real company permanently, which is far
    worse than leaving one junk node for the age rule below to collect. Any
    future widening of the shape rules has to keep these green.
    """
    for nid in ("larsen_and_toubro", "johnson_and_johnson", "procter_and_gamble",
                "standard_and_poors", "black_and_decker"):
        assert not KnowledgeGraph.is_non_entity(nid), nid


def test_ordinary_company_ids_are_untouched():
    for nid in ("databricks", "icici_bank", "nebius", "hon_hai_foxconn",
                "uk_government", "s_oil", "ea"):
        assert not KnowledgeGraph.is_non_entity(nid), nid


def test_the_original_placeholder_family_still_fails():
    """§4.38 must not regress while §4.49's family is added beside it."""
    for nid in ("none", "undisclosed_buyer", "various_investors", "unknown"):
        assert KnowledgeGraph.is_non_entity(nid), nid


# --- AGE: vocabulary that never became wiring -------------------------------

def test_an_unwired_llm_node_is_collected_once_it_is_old_enough():
    g = _g([_llm("databricks", born="2026-01-01")])
    assert g.prune_stale_orphans("2026-08-21", min_age_days=30) == ["databricks"]
    assert "databricks" not in g.nodes


def test_a_young_unwired_node_is_left_alone():
    """The rule that stops this fighting the digester. A node minted today may
    be wired by tomorrow's story about the same company; deleting on sight
    would make the graph unable to learn a company exists (§4.24's defect,
    reintroduced from the other direction)."""
    g = _g([_llm("brand_new_co", born="2026-08-19")])
    assert g.prune_stale_orphans("2026-08-21", min_age_days=30) == []
    assert "brand_new_co" in g.nodes


def test_a_wired_node_is_never_collected_however_old():
    """Age alone is not the criterion — being USELESS is, and an edge is the
    evidence of use."""
    g = _g([_llm("old_but_useful", born="2026-01-01"), _llm("semis", born="2026-01-01")],
           [Edge(src="old_but_useful", dst="semis", type="member_of", provenance="llm")])
    assert g.prune_stale_orphans("2026-08-21", min_age_days=30) == []
    assert "old_but_useful" in g.nodes


def test_a_curated_node_is_never_collected():
    """An unwired SEED node is the opposite problem: a gap to fill, which
    `scripts/graph_gap_scan.py` exists for. Deleting it would erase the very
    signal that says wiring is missing."""
    g = _g([Node(id="oil_price", type="factor", label="Oil")])
    assert g.prune_stale_orphans("2026-08-21", min_age_days=30) == []
    assert "oil_price" in g.nodes


def test_a_node_with_no_recorded_birthday_is_left_alone():
    """Nothing may be deleted on an age that cannot be read. Silently treating
    'unknown age' as 'old' is how a cleanup takes something it should not."""
    g = _g([Node(id="mystery", type="asset", label="?", state="llm-proposed: no date")])
    assert g.prune_stale_orphans("2026-08-21", min_age_days=30) == []
    assert "mystery" in g.nodes


def test_collection_leaves_no_tombstone():
    """Deliberate. A tombstone records a rejected CLAIM, and no claim was ever
    made about these nodes — nothing was asserted, they were merely named. If
    the company turns up later inside a real relationship, it must be free to
    come back with that relationship attached rather than be suppressed by a
    rejection it never earned."""
    g = _g([_llm("skanska", born="2026-01-01")])
    g.prune_stale_orphans("2026-08-21", min_age_days=30)
    assert not g.rejected, f"collection left a tombstone: {g.rejected}"


def test_a_malformed_timestamp_collects_nothing():
    g = _g([_llm("databricks", born="2026-01-01")])
    assert g.prune_stale_orphans("not-a-date", min_age_days=30) == []
    assert "databricks" in g.nodes


def test_no_caller_asks_is_non_entity_without_a_type():
    """Three separate callers got this wrong the same way, so it is pinned.

    `is_non_entity(nid)` defaults to "asset". The seed's own theme nodes
    (`uk_banks`, `sg_banks`, `china_property_stocks`) are categories, which is
    correct for a theme and junk for an asset — so every type-blind caller
    reported three curated nodes as placeholders. `test_graph_hygiene`,
    `brain_audit.py --section graph` and `review_edges.py --hygiene` each did.
    """
    import ast
    root = Path(__file__).resolve().parents[2]
    offenders = []
    for path in sorted((root / "scripts").glob("*.py")) + \
            sorted((root / "engine" / "ai_investing").rglob("*.py")):
        if path.name == "graph.py":
            continue                      # the definition itself
        for node in ast.walk(ast.parse(path.read_text())):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "is_non_entity"
                    and len(node.args) < 2):
                offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, (
        "these callers judge every node as an asset, so a curated THEME node "
        f"naming a category reads as junk: {offenders}")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\nAll {len(tests)} graph-curation tests passed.")
