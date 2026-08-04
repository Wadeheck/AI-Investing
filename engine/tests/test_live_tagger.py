"""Contract for the LIVE tagger — the one that runs in the engine every cycle.

This exists because of a defect that ran undetected for the life of the project:
the corpus digester (Sonnet) was audited to 100% on the golden set, while the
in-engine tagger (a local 8B model) was never audited at all. It was returning
polarity 0 on 57% of events, and since

    impulse = polarity x magnitude x credibility

a zero polarity deletes the event. The brain was reading the world and throwing
away half of it, silently, with every health check green.

These tests are pure — no LLM, no network. They pin the invariants that made the
loss possible, so a future prompt or parsing change cannot quietly restore it.
Fidelity itself (how OFTEN the model is right) is measured separately by
scripts/audit_live_tagger.py against the same 50 golden items.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai_investing.brain.events import (_attach_headline, _keyword_sign,  # noqa: E402
                                       _polarity_of, _resolve_unsigned, _BATCH)


class _FakeNode:
    def __init__(self, nid, label):
        self.id, self.label, self.type = nid, label, "factor"


class _FakeGraph:
    def __init__(self):
        self.nodes = {"oil_supply": _FakeNode("oil_supply", "Oil supply"),
                      "credit_spreads": _FakeNode("credit_spreads", "Credit spreads")}

    def match_text(self, _text):
        return []


def test_direction_words_beat_the_numeric_sign():
    """The model reports sentiment when asked for a number ('grim news => -1'),
    which inverts every stress-type node. The words carry the truth."""
    ev = {"direction": "more credit spreads", "magnitude_signed": 0.6,
          "polarity": -0.9}          # the number disagrees, and is wrong
    assert _polarity_of(ev) == 0.6, "the written direction must win"
    ev = {"direction": "less oil supply", "magnitude_signed": 0.5, "polarity": 0.9}
    assert _polarity_of(ev) == -0.5


def test_magnitude_never_flips_the_direction():
    """Sign lives in the words only; a stray negative size must not invert it."""
    assert _polarity_of({"direction": "more X", "magnitude_signed": -0.7}) == 0.7


def test_numeric_polarity_still_honoured_when_no_direction_given():
    assert _polarity_of({"polarity": -0.3}) == -0.3


def test_an_event_with_nodes_is_never_left_at_zero_silently():
    """The whole defect in one assertion: a tagged event that keeps polarity 0
    contributes nothing, so it must either be signed or explicitly marked."""
    events = [{"headline": "OPEC+ agrees surprise output cut",
               "nodes": ["oil_supply"], "polarity": 0.0}]
    out = _resolve_unsigned(events, _FakeGraph(), _NoLLM())
    ev = out[0]
    assert abs(ev["polarity"]) > 0 or ev.get("unsigned") is True
    assert abs(ev["polarity"]) > 0, "the headline's own verb ('cut') gives a sign"
    assert ev["polarity"] < 0, "an output CUT is less supply"


def test_unsignable_events_are_flagged_not_dropped():
    """No sign available anywhere: it must be COUNTED, so daily_status can see
    the rate. Silence is what caused this bug."""
    events = [{"headline": "Royal wedding announcement", "nodes": ["oil_supply"],
               "polarity": 0.0}]
    out = _resolve_unsigned(events, _FakeGraph(), _NoLLM())
    assert out[0].get("unsigned") is True
    assert abs(out[0]["polarity"]) < 1e-9


def test_untagged_events_are_left_alone():
    """No nodes means nothing to sign; it must not be marked as a failure."""
    events = [{"headline": "fluff", "nodes": [], "polarity": 0.0}]
    out = _resolve_unsigned(events, _FakeGraph(), _NoLLM())
    assert not out[0].get("unsigned")


def test_keyword_sign_reads_the_verb_not_the_mood():
    assert _keyword_sign("OPEC+ cuts output") < 0
    assert _keyword_sign("Fed hikes rates") > 0
    assert _keyword_sign("Iran denies reports") < 0, "a denial is a negation"
    assert _keyword_sign("Royal wedding draws viewers") == 0, "no verb, no guess"


def test_headline_is_repaired_from_the_batch_index():
    """Small models paraphrase the headline they were told to copy verbatim,
    which breaks dedup, corroboration and credibility. The index is truth."""
    chunk = [{"title": "First", "source": "a"}, {"title": "Second", "source": "b"}]
    out = _attach_headline([{"n": 2, "headline": "a loose paraphrase"}], chunk)
    assert out[0]["headline"] == "Second" and out[0]["source"] == "b"


def test_out_of_range_index_does_not_corrupt_a_headline():
    chunk = [{"title": "Only", "source": "a"}]
    out = _attach_headline([{"n": 9, "headline": "kept as-is"}], chunk)
    assert out[0]["headline"] == "kept as-is"


def test_batch_stays_small_enough_for_recall():
    """Measured: at 25 headlines per call the small model answers for about half
    and drops the rest. Raising this silently loses news."""
    assert _BATCH <= 12, "recall collapses on large batches — see the audit script"


def test_x_capture_reaches_the_live_headline_feed():
    """The X capture was a WRITE-ONLY channel for the life of the project.

    x_capture_ingest.py filled news_archive_x.jsonl, daily_status and needs_you
    watched its age, and nothing ever read it into the live brain — verified
    against brain.db: of 36 X headlines captured for 2026-08-03/04, exactly one
    appeared, and that arrived via an RSS feed carrying the same story. The daily
    manual harvest shaped future retraining while contributing nothing to the
    decisions being made that day.
    """
    import json
    import tempfile
    from datetime import datetime, timedelta, timezone
    from ai_investing.brain.events import source_trust
    from ai_investing.data.news import _x_capture_headlines

    d = tempfile.mkdtemp()
    now = datetime.now(timezone.utc)
    fresh, stale = now - timedelta(hours=2), now - timedelta(days=30)
    with open(os.path.join(d, "news_archive_x.jsonl"), "w") as fh:
        fh.write(json.dumps({"date": "2026-08-03", "ts": fresh.isoformat(), "headlines": [
            {"title": "Bitcoin ETF Daily Flow: +14.1 million net",
             "source": "x.com/FarsideUK", "ts": fresh.isoformat()},
            {"title": "Coldcard hack losses exceed $100 million",
             "source": "x.com/TheBlockCo", "ts": fresh.isoformat()},
            {"title": "", "source": "x.com/TheBlockCo", "ts": fresh.isoformat()},
        ]}) + "\n")
        fh.write(json.dumps({"date": "2026-07-01", "ts": stale.isoformat(), "headlines": [
            {"title": "ancient post far outside the window",
             "source": "x.com/TheBlockCo", "ts": stale.isoformat()}]}) + "\n")

    class S:
        state_path = os.path.join(d, "state.json")

    got = _x_capture_headlines(S())
    titles = [h["title"] for h in got]
    assert len(got) == 2, f"expected 2 in-window posts, got {titles}"
    assert "Bitcoin ETF Daily Flow: +14.1 million net" in titles
    assert not any("ancient" in t for t in titles), "window not applied"
    assert all(t for t in titles), "an empty title must never be fed to the brain"

    # the per-handle trust values in SOURCE_TRUST must actually resolve, or the
    # curated channel arrives no more credible than an anonymous account
    assert source_trust("x.com/FarsideUK") == 0.8
    assert source_trust("x.com/TheBlockCo") == 0.65
    assert source_trust("x.com/SomeRandomAnon") == 0.25    # generic x.com floor

    # a missing archive must be silent, not fatal: the capture is manual and
    # will often be absent on a fresh checkout
    class Empty:
        state_path = os.path.join(tempfile.mkdtemp(), "state.json")
    assert _x_capture_headlines(Empty()) == []


class _NoLLM:
    """Settings stand-in with no model reachable, so escalation is skipped and
    the deterministic fallbacks are what gets tested."""
    llm_available = False
    llm_prefer_local = False
    local_llm_url = ""


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok  {name}")
            except AssertionError as exc:
                fails += 1
                print(f"  FAIL {name}: {exc}")
    print("All live-tagger tests passed." if not fails else f"{fails} failed")
    sys.exit(1 if fails else 0)
