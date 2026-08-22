"""The curated tier: content the operator hand-picked must not be scored like a feed.

DIGESTION_SPEC §A12. Every test here pins a gate that was MEASURED obstructing
hand-submitted research before this tier existed:

  1. `_prompt` truncated bodies at 400 chars, so ~90% of a long-form piece was
     never read — not rejected, never read.
  2. `credibility()` scored a curated submission 0.555 against a corroborated
     wire's 0.677, because corroboration is worth 0.15 and a single in-depth
     analysis has none BY CONSTRUCTION. `impulse` carries credibility as a
     factor, so the operator's own research pressed ~18% softer than a headline.
  3. `core.think` took `[:2]` proposed edges per event, discarding everything a
     piece argued after its second relationship.
  4. `propose_edge` refused any edge naming a node the graph did not already
     hold — silently, no tombstone, no counter — which is exactly the case a
     piece introducing a NEW mechanism hits.
  5. The 0.6 confidence cap and a 6/day budget shared with an 88.5/week RSS
     firehose, first-come-first-served, with no priority for curated content.

The operator's decision (2026-08-22) was the curated tier: full authority,
tagged and visible, never demoted. These tests are the record of what that
means, so a later refactor cannot quietly take it back.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_investing.brain import events as ev_mod  # noqa: E402
from ai_investing.brain.graph import Edge, KnowledgeGraph, Node  # noqa: E402


def _graph() -> KnowledgeGraph:
    return KnowledgeGraph(
        [Node(id="oil_supply", type="factor", label="Oil supply"),
         Node(id="us_cpi", type="factor", label="US CPI"),
         Node(id="xle", type="asset", label="XLE", symbol="XLE", market="US")],
        [Edge(src="oil_supply", dst="us_cpi", type="influences", sign=-1,
              weight=0.5, provenance="seed")])


# --- 1. depth reaches the extractor ----------------------------------------

def test_a_curated_body_is_not_truncated_at_400_chars():
    """The single most destructive gate, and the one furthest upstream: it ran
    BEFORE any judgement, so nothing downstream could recover what it dropped."""
    long_body = "MECHANISM. " + ("x" * 5000)
    wire = {"title": "t", "source": "reuters", "summary": long_body}
    curated = {"title": "t", "source": "user_curated", "summary": long_body}

    wire_prompt = ev_mod._prompt([wire], "oil_supply", None)
    curated_prompt = ev_mod._prompt([curated], "oil_supply", None)

    assert len(wire_prompt) < len(curated_prompt) - 4000, \
        "a wire item should still be capped at 400 chars of body"
    assert long_body[:5000] in curated_prompt, \
        "curated research must reach the extractor whole"


def test_a_curated_body_past_the_ceiling_says_so_out_loud():
    """There IS still a ceiling — an unbounded prompt overflows the local
    qwen3:8b fallback and the whole piece drops to `_fallback_extract`. The
    difference from the 400-char cap is that this one announces itself."""
    huge = "y" * (ev_mod.CURATED_PROMPT_CHARS + 5000)
    h = {"title": "t", "source": "user_curated", "summary": huge}
    prompt = ev_mod._prompt([h], "oil_supply", None)
    assert "TRUNCATED" in prompt, "silent truncation is what this tier exists to end"
    assert h.get("curated_truncated") == len(huge), \
        "the headline must carry the fact, so a caller can surface it"


def test_the_total_curated_budget_bounds_the_prompt_not_the_per_item_cap():
    """A per-item cap cannot bound a prompt. Forty files dropped at once, each
    legally under the per-item ceiling, would still overflow — so the per-item
    number was doing a job it could not do, and shrinking it to compensate just
    truncates single pieces for a burst that may never happen.

    The TOTAL is the real guard. Curated items are ordered newest-first by
    `build_market_context`, so the budget goes to the newest research and any
    overflow lands on the oldest, which is the right way round.
    """
    Q = "§§"                       # cannot occur in the prompt boilerplate
    def mk(n, chars):
        return {"title": f"t{n}", "source": f"user_curated:f{n}.md",
                "summary": Q * (chars // 2)}

    heads = [mk(i, 15000) for i in range(5)]        # 75k requested vs 45k budget
    prompt = ev_mod._prompt(heads, "oil_supply", None)
    assert prompt.count(Q) * 2 <= ev_mod.CURATED_PROMPT_TOTAL, \
        "the total budget must bound what reaches the model"
    assert sum(1 for h in heads if h.get("curated_truncated")) == 2, \
        "items past the budget must be ANNOUNCED, never dropped silently"

    # and one long piece well under the per-item cap is untouched
    solo = ev_mod._prompt([mk(9, 15000)], "oil_supply", None)
    assert solo.count(Q) * 2 == 15000 and "TRUNCATED" not in solo


def test_raising_the_ceiling_did_not_loosen_the_wire_cap():
    """The curated ceiling moved 12k -> 20k because a real digest hit it. That
    must not leak into feed items, whose 400 chars is correct and is what keeps
    a 100-headline prompt affordable."""
    Q = "§§"
    w = ev_mod._prompt([{"title": "w", "source": "reuters", "summary": Q * 2500}],
                       "oil_supply", None)
    assert w.count(Q) * 2 == 400, "a wire body is a lede; 400 is right for it"


def test_curated_items_are_shown_the_entity_ids_they_may_wire_to():
    """`node_ids` in the extraction prompt excludes EVERY asset node, so the
    model can only name one as an edge endpoint by guessing the slug. It guesses
    famous tickers (`nvda` wired fine) and cannot guess an internal hub minted
    by the deals path — `blue_owl_capital`, `athene`, `us_life_insurers`.

    That is exactly the wiring curated research exists to add: connecting the
    FIRMS running a financing structure to the MECHANISM itself. Measured twice
    on live pieces — the factor-to-factor edges landed and the entity bridge did
    not, so the graph knew compute securitisation existed and did not know who
    does it. A shock to `compute_securitization` moved NVDA +0.07 and
    `blue_owl_capital` exactly 0.0000.

    Feed items must NOT get this: a wire item is one line, the asset universe is
    ~470 nodes, and the exclusion is what keeps a 100-headline prompt affordable.
    """
    from ai_investing.brain.graph import Edge as _E  # noqa: F401
    g = KnowledgeGraph(
        [Node(id="blue_owl_capital", type="asset",
              label="Blue Owl Capital (private)", aliases=["blue owl capital"]),
         Node(id="compute_securitization", type="factor",
              label="Compute Securitization")], [])
    text = "Blue Owl Capital sells the paper on to insurers."
    curated = {"title": "Blue Owl securitises compute", "summary": text,
               "source": "user_curated:x.md"}
    wire = {"title": "Blue Owl securitises compute", "summary": text,
            "source": "reuters"}

    pc = ev_mod._prompt([curated], "compute_securitization", g)
    assert "entity ids that MATCHED" in pc and "blue_owl_capital" in pc, \
        "a curated piece must be told the exact hub ids it can wire to"
    assert "IGNORE any that matched a common word" in pc, \
        ("alias matching is substring-based, so `near`/`link` match the words "
         "'near term' and 'link'. A curated edge is confidence 1.0 and can "
         "never be demoted, so the shortlist must be a lookup, not an order.")

    pw = ev_mod._prompt([wire], "compute_securitization", g)
    assert "entity ids that MATCHED" not in pw, \
        "feed items keep the asset exclusion; it is what bounds the prompt"


# --- 2. credibility must not subtract from a human judgement ----------------

def test_curated_content_is_never_damped_by_the_noise_formula():
    """The measured numbers this replaces: curated 0.555, wire 0.677. `impulse`
    is polarity x magnitude x credibility x confidence, so 0.555 meant the
    operator's own research pressed softer than a headline it may be far more
    informative than."""
    curated = {"source": "user_curated", "headline": "deep piece",
               "manipulation_likelihood": 0.0, "type": "other"}
    scored = ev_mod.credibility(curated, [])
    assert scored < 0.6, \
        "guard on the premise: the raw formula really does under-score this"
    assert ev_mod.is_curated("user_curated")
    assert ev_mod.is_curated("user_curated:thesis.md"), \
        "the drop-directory tags the filename onto the source; same tier"
    assert not ev_mod.is_curated("reuters")


def test_promotional_register_cannot_push_curated_content_under_the_noise_line():
    """An argumentative piece reads as promotional to the extractor. Measured:
    manipulation_likelihood=0.4 scored a curated submission 0.355 against a
    0.35 threshold — five thousandths from being silenced entirely."""
    flagged = {"source": "user_curated", "headline": "why this re-rates",
               "manipulation_likelihood": 0.4, "type": "other"}
    assert ev_mod.credibility(flagged, []) < 0.36, \
        "guard on the premise: it really did sit on the noise line"


# --- 3/4/5. the graph lane --------------------------------------------------

def test_an_asserted_edge_creates_the_nodes_it_names():
    """`propose_edge` returns False when an endpoint is unknown — silently, with
    no tombstone and no counter. A piece introducing a genuinely new mechanism
    is precisely the case that hits it."""
    g = _graph()
    assert g.propose_edge("datacenter_water", "tsmc_output", "influences", 1,
                          0.5, 0.5, "x", "2026-08-22T00:00:00") is False, \
        "guard on the premise: the llm lane refuses unknown endpoints"

    assert g.assert_edge("datacenter_water", "tsmc_output", "influences", -1,
                         0.6, proposed_by="piece", ts="2026-08-22T00:00:00")
    assert "datacenter_water" in g.nodes and "tsmc_output" in g.nodes
    assert g.nodes["datacenter_water"].type == "factor", \
        "a new MECHANISM is a factor, not a (private) asset like the deals path"


def test_asserted_edges_enter_at_full_confidence_and_ignore_the_budget():
    g = _graph()
    g.daily_proposal_budget = 1
    ts = "2026-08-22T00:00:00"
    for i in range(6):
        assert g.assert_edge(f"factor_{i}", "us_cpi", "influences", 1, 0.5,
                             proposed_by="piece", ts=ts), \
            "curated wiring must not queue behind the RSS firehose for slots"
    user = g.user_edges()
    assert len(user) == 6
    assert all(e.confidence == 1.0 for e in user), \
        "0.6 encodes 'an LLM guessed'; a human assertion gets seed's 1.0"
    assert all(e.provenance == "user" for e in user)


def test_the_calibrator_may_promote_a_user_edge_but_never_demote_it():
    """The operator asked for wiring that acts NOW rather than waiting on
    evidence. A demotion is that wait arriving late: MIN_N=60 on 5-day forward
    returns is ~12 independent observations. Promotion still applies — evidence
    agreeing may strengthen; evidence disagreeing is reported, not acted on."""
    g = _graph()
    ts = "2026-08-22T00:00:00"
    g.assert_edge("oil_supply", "xle", "influences", 1, 0.5,
                  proposed_by="piece", ts=ts)
    user_key = g.edge_key(g.user_edges()[0])
    seed_key = g.edge_key(next(e for e in g.edges if e.provenance == "seed"))

    g.set_calibration({user_key: 0.5, seed_key: 0.5})
    assert user_key not in g._calibration, "a user edge must never be demoted"
    assert g._calibration[seed_key] == 0.5, "seed edges still demote normally"

    g.set_calibration({user_key: 1.15})
    assert g._calibration[user_key] == 1.15, "promotion still applies"


def test_re_asserting_an_edge_corrects_it_instead_of_duplicating_it():
    """How the operator overrules curated seed wiring they now disagree with."""
    g = _graph()
    ts = "2026-08-22T00:00:00"
    before = len(g.edges)
    assert g.assert_edge("oil_supply", "us_cpi", "influences", 1, 0.9,
                         proposed_by="piece", ts=ts)
    assert len(g.edges) == before, "must not duplicate an existing relationship"
    e = next(x for x in g.edges if x.src == "oil_supply" and x.dst == "us_cpi")
    assert (e.sign, e.weight, e.provenance) == (1, 0.9, "user"), \
        "the seed said sign=-1 weight=0.5; the operator overruled it"


def test_a_non_entity_is_refused_no_matter_who_submits_it():
    """§4.24 still applies. A curated piece is exactly as capable of containing
    the word 'none' as a wire is, and `none` once became the graph's 17th most
    connected node."""
    g = _graph()
    assert g.assert_node("none", "None") is False
    assert g.assert_edge("none", "us_cpi", "influences", 1, 0.5,
                         proposed_by="p", ts="2026-08-22T00:00:00") is False


def test_user_edges_survive_a_seed_merge():
    """`_merge_seed` refreshes edges whose provenance is 'seed'. A curated
    correction must not be silently reverted by the next seed version."""
    g = _graph()
    g.assert_edge("oil_supply", "us_cpi", "influences", 1, 0.9,
                  proposed_by="piece", ts="2026-08-22T00:00:00")
    g._merge_seed()
    e = next(x for x in g.edges if x.src == "oil_supply" and x.dst == "us_cpi")
    assert e.provenance == "user" and e.weight == 0.9, \
        "the seed merge must not overwrite an operator correction"


def test_the_curated_tier_is_visible_in_the_audit():
    """Full authority is only safe if it is also counted. This codebase's own
    history is a list of controls that existed and were never looked at."""
    src = (Path(__file__).resolve().parents[2] / "scripts" / "brain_audit.py").read_text()
    for key in ("user_edges", "user_nodes", "user_share_pct"):
        assert f'"{key}"' in src, f"brain_audit must report {key}"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\nAll {len(tests)} curated-tier tests passed.")
