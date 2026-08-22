"""The curated tier, end to end through `Brain.think` — and the drop-directory.

The unit tests in `test_curated_tier.py` pin each gate. This file pins the
property that only shows up when the whole cycle runs: **a submitted piece
rewires the graph and is felt THROUGH its own rewiring, on the cycle it
arrives.**

That ordering is the part most easily broken by a later refactor, and it was
wrong in the first draft of this feature. `impulses` is built from `ev["nodes"]`
near the top of `think()`; the edge-application loop sat ~90 lines below, after
`propagate()`. So curated wiring landed a cycle late — and for a piece
introducing a NEW mechanism it was worse than late: the origin node did not
exist when `impulses` was built, the article is marked digested at the end of
that same pass and never re-extracted, so the impulse was lost PERMANENTLY
while the wiring appeared with nothing flowing through it. Silent, and it would
have looked like the feature working.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

tmp = tempfile.mkdtemp()
for var, name in [("BRAIN_GRAPH_PATH", "g"), ("BRAIN_REGIME_PATH", "r"),
                  ("BRAIN_SCENARIOS_PATH", "s"), ("BRAIN_STATE_PATH", "b"),
                  ("BRAIN_MACRO_CACHE_PATH", "m"), ("BRAIN_FIELD_PATH", "f"),
                  ("BRAIN_DB_PATH", "db"), ("BRAIN_FEED_CACHE_PATH", "fc"),
                  ("BRAIN_ADVICE_PATH", "adv"), ("BRAIN_SENTIMENT_CACHE_PATH", "sc"),
                  # STATE_PATH is the one the BRAIN_* block does not cover, and
                  # it is the one the curated directory and the submission queue
                  # derive from. Without it `Settings()` points at the repo's
                  # REAL data/ — the first draft of this file wrote 43 fixture
                  # files into it and unlinked the drop-directory's README.
                  # §4.21's rule is about modules reaching past their caller;
                  # this is the same failure from the other end, a TEST that
                  # forgot to redirect the path its subject correctly honoured.
                  ("STATE_PATH", "state")]:
    os.environ[var] = os.path.join(tmp, name + ".json")

from ai_investing.brain import Brain  # noqa: E402
from ai_investing.brain import core as core_mod  # noqa: E402
from ai_investing.config import Settings  # noqa: E402
from ai_investing.data import news as news_mod  # noqa: E402


_CURATED_EVENT = {
    "summary": "Datacenter water draw constrains fab output in drought years",
    "headline": "Water, not power, is the binding constraint on fab expansion",
    "source": "user_curated:water_thesis.md",
    "type": "supply_chain",
    "nodes": ["datacenter_water_draw"],          # a node the graph does NOT hold
    "polarity": 1.0, "magnitude": 0.8, "confidence": 0.9,
    "manipulation_likelihood": 0.0, "emotion": "neutral", "emotion_intensity": 0.0,
    "proposed_edges": [
        {"src": "datacenter_water_draw", "dst": "semiconductor_supply",
         "type": "influences", "sign": -1, "weight": 0.6,
         "why": "fabs need ultrapure water; drought caps wafer starts"},
        {"src": "datacenter_water_draw", "dst": "us_cpi", "type": "influences",
         "sign": 1, "weight": 0.3, "delay_days": 45,
         "why": "chip scarcity feeds goods inflation with a lag"},
        {"src": "semiconductor_supply", "dst": "nvda", "type": "influences",
         "sign": 1, "weight": 0.5, "why": "supply constraint on the主 supplier"},
    ],
}


def _brain_with_stubbed_extractor(event: dict) -> Brain:
    """A Brain on a FRESH graph every call.

    Without this the two Brain tests share one persisted graph, and whichever
    runs first mints `datacenter_water_draw` for the other — so the second's
    "premise: node is new" assert depends on execution ORDER. pytest runs
    definition order and passed; the `__main__` runner the ProDesk uses sorts
    alphabetically and failed. A test whose premise depends on its neighbours
    is not testing what it claims, and it took the two runners disagreeing to
    show it.
    """
    d = tempfile.mkdtemp()
    for var, name in [("BRAIN_GRAPH_PATH", "g"), ("BRAIN_FIELD_PATH", "f"),
                      ("BRAIN_STATE_PATH", "b"), ("BRAIN_DB_PATH", "db"),
                      ("BRAIN_REGIME_PATH", "r"), ("BRAIN_ADVICE_PATH", "adv")]:
        os.environ[var] = os.path.join(d, name + ".json")
    s = Settings()
    b = Brain(s)

    def _fake_extract(headlines, graph, settings):
        from ai_investing.brain.events import is_curated
        ev = dict(event)
        ev["curated"] = is_curated(ev.get("source", ""))
        ev["credibility"] = 1.0
        ev["is_noise"] = False
        ev["impulse"] = round(ev["polarity"] * ev["magnitude"]
                              * ev["credibility"] * ev["confidence"], 4)
        ev["ts"] = "2026-08-22T00:00:00+00:00"
        raw = list(ev.get("nodes") or [])
        ev["nodes"] = [n for n in raw if n in graph.nodes]
        ev["proposed_nodes"] = [n for n in raw if n not in graph.nodes]
        return [ev]

    core_mod.events_mod.extract_events = _fake_extract
    return b


def test_a_submitted_piece_rewires_the_graph_and_is_felt_the_same_cycle():
    b = _brain_with_stubbed_extractor(_CURATED_EVENT)
    assert "datacenter_water_draw" not in b.graph.nodes, "premise: node is new"

    state = b.think([{"title": "Water, not power", "source": "user_curated:water_thesis.md",
                      "summary": "long piece", "published": "2026-08-22T00:00:00+00:00"}])

    # 1. the mechanism now exists, as a FACTOR (not a "(private)" asset)
    assert "datacenter_water_draw" in b.graph.nodes
    assert b.graph.nodes["datacenter_water_draw"].type == "factor"
    assert b.graph.nodes["datacenter_water_draw"].state.startswith("user-asserted")

    # 2. every relationship the piece argued was wired — not just the first two
    user = {(e.src, e.dst) for e in b.graph.user_edges()}
    assert ("datacenter_water_draw", "semiconductor_supply") in user
    assert ("datacenter_water_draw", "us_cpi") in user
    assert ("semiconductor_supply", "nvda") in user, \
        "the `[:2]` throttle must not apply to curated research"
    assert state.get("user_edges_added") == 3
    assert state.get("user_nodes_added", 0) >= 1

    # 3. THE ORDERING PROPERTY: the impulse landed on the node the piece created,
    #    on this cycle, and travelled the wiring the same piece asserted.
    assert "datacenter_water_draw" in (state.get("impulses") or {}), \
        "the piece's own origin node must receive its impulse THIS cycle"
    lag = next(e for e in b.graph.user_edges() if e.dst == "us_cpi")
    assert lag.delay_days == 45, "an asserted lag must survive into the edge"


def test_a_curated_piece_is_never_silenced_as_noise():
    ev = dict(_CURATED_EVENT, type="rumor_hype", manipulation_likelihood=0.9)
    b = _brain_with_stubbed_extractor(ev)
    state = b.think([{"title": "rumour piece", "source": "user_curated:r.md",
                      "summary": "x", "published": "2026-08-22T00:00:00+00:00"}])
    assert state.get("user_edges_added", 0) > 0, \
        "submitting a piece ABOUT a rumour is a deliberate call to track it"



def _settings_in_tmp():
    """`Settings()` reads STATE_PATH at INSTANTIATION, and eleven test modules
    set it at import time — so the last module pytest imports wins, whichever
    that happens to be. Setting it here, immediately before constructing, is
    the only way this file owns the path it is about to write into. The
    module-level default below is kept for the Brain tests; it is not enough on
    its own, and the full-suite run is where that shows up.
    """
    os.environ["STATE_PATH"] = os.path.join(tmp, "state.json")
    return Settings()


def _clean_curated_dir(s) -> str:
    """Empty the curated directory — after PROVING it is the temp one.

    A test that unlinks a glob is one forgotten env var away from deleting the
    operator's research. The first draft of this file was exactly that, and it
    did delete the drop-directory's README. The assert is the whole point: it
    fails loudly instead of removing files if `STATE_PATH` is ever not redirected.
    """
    d = news_mod.curated_dir_path(s)
    assert str(Path(d).resolve()).startswith(str(Path(tmp).resolve())), \
        f"REFUSING to clear {d}: not inside the test temp dir {tmp}"
    os.makedirs(d, exist_ok=True)
    for f in Path(d).glob("*"):
        f.unlink()
    return d


# --- the drop-directory ----------------------------------------------------

def test_the_drop_directory_reads_whole_files_newest_first():
    s = _settings_in_tmp()
    d = _clean_curated_dir(s)

    body = "# Water is the constraint\n\n" + ("detail. " * 800)
    Path(d, "old.md").write_text("# Older piece\n\nolder body")
    Path(d, "water.md").write_text(body)
    os.utime(Path(d, "old.md"), (1, 1))          # force the ordering

    # the directory's own instructions must never be digested as research
    Path(d, "README.md").write_text("# Drop research here\n\nhow this works")

    heads = news_mod._curated_dir_headlines(s)
    assert not any("README" in h["source"] for h in heads), \
        "a doc explaining high-authority ingestion, fed through high-authority " \
        "ingestion, is how something absurd gets wired at confidence 1.0"
    assert [h["title"] for h in heads] == ["Water is the constraint", "Older piece"], \
        "newest first, and the markdown heading marker is not part of the title"
    assert heads[0]["source"] == "user_curated:water.md", \
        "the filename must survive into the source, so a curated edge is traceable"
    assert heads[0]["summary"] == body.strip(), "the whole file, not a lede"
    assert len(heads[0]["summary"]) > 4000, \
        "past the old Telegram-shaped 4000-char ceiling"


def test_the_drop_directory_overflow_is_loud():
    s = _settings_in_tmp()
    d = _clean_curated_dir(s)
    for i in range(news_mod._CURATED_FILE_LIMIT + 3):
        Path(d, f"p{i:03d}.md").write_text(f"# piece {i}\n\nbody")

    heads = news_mod._curated_dir_headlines(s)
    assert any("_overflow" in h["source"] for h in heads), \
        "a door that stops opening must say so — silence here is the whole bug class"


def test_a_telegram_submission_is_no_longer_capped_at_a_message():
    s = _settings_in_tmp()
    long_text = "Title line\n\n" + ("y" * 30000)
    rec = news_mod.submit_user_news(s, long_text, sender="test")
    assert len(rec["summary"]) > 4000, "4000 was one Telegram message, not a judgement"
    assert rec["source"] == "user_curated"
    # and it round-trips through the queue reader
    got = news_mod._user_submitted_headlines(s)
    assert any(len(h.get("summary", "")) > 4000 for h in got)
    assert json.loads(json.dumps(rec))["title"].startswith("Title line")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\nAll {len(tests)} curated end-to-end tests passed.")
