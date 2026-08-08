"""The inference-consultation gate: a tap must MOVE MONEY, not be filed.

The whole design rests on four claims, and each gets a test here, because each
one is a promise made to the user in the Telegram message itself:

  1. 👍/😐/👎 scale the impulse that reaches the graph — immediately, same pass.
  2. A 👎 can be outvoted ONLY by much stronger fresh evidence, and the override
     is recorded so it can be reported (an unseen override IS being ignored).
  3. A SECOND 👎 blocks the read outright — no override, at any conviction.
  4. Opposite-signed news on a damped node is NOT damped: that is the evidence
     that should change the user's mind, and silencing it would be the worst
     possible failure of this module.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_investing.brain import consult
from ai_investing.config import Settings


def _settings(tmp: str) -> Settings:
    s = Settings()
    s.brain.state_path = str(Path(tmp) / "brain.json")
    s.brain.consult_ttl_hours = 72.0
    return s


def _event(impulse: float, node: str = "oil_supply", **kw) -> dict:
    return {"summary": "OPEC cuts output", "headline": "OPEC cuts output",
            "source": "reuters", "nodes": [node], "impulse": impulse,
            "confidence": 0.8, "credibility": 0.9, "magnitude": 0.6,
            "direction": "less oil supply", "is_noise": False, **kw}


def _filed(book: consult.ConsultBook, impulse: float = -0.5) -> dict:
    return book.file(claim="c", assumption="a", nodes=["oil_supply"],
                     impulse=impulse, confidence=0.8, headlines=[])


def test_verdicts_scale_the_impulse_in_the_same_pass():
    with tempfile.TemporaryDirectory() as tmp:
        s = _settings(tmp)
        for verdict, expect in (("agree", 1.30), ("neutral", 0.85), ("disagree", 0.45)):
            book = consult.ConsultBook(s)
            book._save([])                       # fresh book per verdict
            rec = _filed(book)
            book.decide(rec["id"], verdict)
            ev = _event(-0.5)
            consult.damp([ev], s)
            assert abs(ev["impulse"] - (-0.5 * expect)) < 1e-6, \
                f"{verdict} must scale the impulse by {expect}, got {ev['impulse']}"


def test_undecided_and_unmatched_reads_pass_through_untouched():
    with tempfile.TemporaryDirectory() as tmp:
        s = _settings(tmp)
        book = consult.ConsultBook(s)
        _filed(book)                             # asked, never answered
        ev = _event(-0.5)
        consult.damp([ev], s)
        assert ev["impulse"] == -0.5, "silence is not a verdict"

        book.decide(_filed(book, -0.5)["id"], "disagree")
        other = _event(-0.5, node="fed_policy")   # different node entirely
        consult.damp([other], s)
        assert other["impulse"] == -0.5, "a verdict must not leak onto other nodes"


def test_disagree_is_overridden_only_by_much_stronger_evidence():
    with tempfile.TemporaryDirectory() as tmp:
        s = _settings(tmp)
        book = consult.ConsultBook(s)
        rec = _filed(book, -0.5)                  # disputed conviction 0.5
        book.decide(rec["id"], "disagree")
        bar = max(consult.OVERRIDE_FLOOR, 0.5 * consult.OVERRIDE_MULT)   # 0.75

        weak = _event(-0.70)                      # stronger than before, under the bar
        assert not consult.damp([weak], s), "0.70 must not clear a 0.75 bar"
        assert weak["impulse"] < 0.0 and abs(weak["impulse"]) < 0.70, "still damped"

        strong = _event(-(bar + 0.05))
        notices = consult.damp([strong], s)
        assert len(notices) == 1, "past the bar the read must reassert AND report"
        assert strong["impulse"] == -(bar + 0.05), "an override passes at full weight"
        assert book._load()[0]["overrides"] == 1, "the override must be recorded"
        assert consult.override_text(notices[0])                 # renders without raising


def test_second_disagree_blocks_outright_at_any_conviction():
    with tempfile.TemporaryDirectory() as tmp:
        s = _settings(tmp)
        book = consult.ConsultBook(s)
        rec = _filed(book, -0.5)
        book.decide(rec["id"], "disagree")
        rec = book.decide(rec["id"], "disagree")
        assert rec["disagrees"] == 2
        assert consult.weight_for(rec) == consult.BLOCKED

        overwhelming = _event(-0.99)
        assert not consult.damp([overwhelming], s), "a block cannot be overridden"
        assert overwhelming["impulse"] == 0.0, "a blocked read contributes nothing"


def test_opposite_signed_news_is_never_damped():
    """The evidence that should change your mind must reach the graph intact."""
    with tempfile.TemporaryDirectory() as tmp:
        s = _settings(tmp)
        book = consult.ConsultBook(s)
        book.decide(_filed(book, -0.5)["id"], "disagree")
        good_news = _event(+0.5)                  # same node, opposite direction
        consult.damp([good_news], s)
        assert good_news["impulse"] == 0.5


def test_harvest_asks_only_about_strong_confident_uncovered_reads():
    with tempfile.TemporaryDirectory() as tmp:
        s = _settings(tmp)
        s.brain.consult_max_asks = 2
        weak = _event(-0.10, node="fed_policy")
        unsure = _event(-0.90, node="china_stance", confidence=0.2)
        noise = _event(-0.90, node="usd_trend", is_noise=True)
        real = _event(-0.60)
        filed = consult.harvest([weak, unsure, noise, real], s)
        assert [r["nodes"] for r in filed] == [["oil_supply"]], \
            "only the strong, confident, non-noise read is worth a ping"

        again = consult.harvest([_event(-0.55)], s)
        assert again == [], "one live question per node+direction — never ask twice"


def test_harvest_respects_the_per_cycle_cap():
    with tempfile.TemporaryDirectory() as tmp:
        s = _settings(tmp)
        s.brain.consult_max_asks = 2
        evs = [_event(-0.6, node=n) for n in
               ("oil_supply", "fed_policy", "china_stance", "usd_trend")]
        assert len(consult.harvest(evs, s)) == 2, "flooding the user is the failure mode"


def test_every_ask_tap_and_override_is_logged_append_only():
    with tempfile.TemporaryDirectory() as tmp:
        s = _settings(tmp)
        book = consult.ConsultBook(s)
        rec = _filed(book, -0.5)
        book.decide(rec["id"], "disagree")
        consult.damp([_event(-0.9)], s)           # triggers an override
        kinds = [json.loads(l)["kind"] for l in Path(book.log_path).read_text().splitlines()]
        assert kinds == ["asked", "decided", "override"]
        assert book.record()["asked"] == 1 and book.record()["overrides"] == 1


def test_trust_factor_deepens_both_directions_and_never_touches_a_block():
    with tempfile.TemporaryDirectory() as tmp:
        s = _settings(tmp)
        Path(tmp).mkdir(exist_ok=True)
        (Path(tmp) / "inference_trust.json").write_text('{"factor": 2.0}')
        assert consult.trust_factor(s) == 2.0
        assert consult.weight_for({"verdict": "disagree"}, 2.0) < consult.WEIGHTS["disagree"]
        assert consult.weight_for({"verdict": "agree"}, 2.0) > consult.WEIGHTS["agree"]
        assert consult.weight_for({"verdict": "disagree", "disagrees": 2}, 2.0) == 0.0
        assert consult.weight_for({"verdict": "disagree"}, 1.0) == consult.WEIGHTS["disagree"]


def test_the_ask_message_shows_headlines_inference_and_assumption():
    with tempfile.TemporaryDirectory() as tmp:
        book = consult.ConsultBook(_settings(tmp))
        rec = book.file(claim="OPEC cut — I read this as *less oil supply*.",
                        assumption="that the cuts are actually delivered",
                        nodes=["oil_supply"], impulse=-0.6, confidence=0.8,
                        headlines=[{"title": "OPEC agrees deeper cut", "source": "reuters"},
                                   {"title": "Brent jumps 4%", "source": "bloomberg"}])
        text = consult.ask_text(rec)
        assert "OPEC agrees deeper cut" in text and "Brent jumps 4%" in text
        assert "less oil supply" in text and "actually delivered" in text
        assert [d for _, d in consult.ask_buttons(rec)[0]] == \
            [f"ia:{rec['id']}", f"im:{rec['id']}", f"ix:{rec['id']}"]


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\nAll {len(tests)} consult tests passed.")
