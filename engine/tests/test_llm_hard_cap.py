"""The free-allowance cap must be a CAP, not a preference.

On 2026-09-18 every BytePlus endpoint went past 90% of its free daily tokens and
`ep-...vgxfw` finished the day at 122.7% -- 1.16M tokens the provider can bill
for. The guard existed and was tested; it just could not stop anything:

    spare = [m for m in chain if not _over_free_budget(settings, m)]
    for model in (spare or chain):

`spare` only *reorders* the chain, and the fallback is the FULL chain, whose head
is the endpoint that accumulated first -- i.e. the most spent. So the moment
every endpoint crossed 90%, the guard routed straight back into the one it was
supposed to rotate away from. §4.25 recorded this as a "cost, not correctness"
risk; this file is the fix.

The distinction the tests below protect:

  * rotation (`_over_free_budget`) keeps failing OPEN -- an unreadable meter
    must not stop the brain reading the news;
  * the cost gate (`_at_free_cap`) fails CLOSED, because a call we cannot prove
    is free is exactly the call that bills silently;
  * an ABSENT meter is neither: it means nothing has been spent today.
"""
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine"))
sys.path.insert(0, str(ROOT / "scripts"))

from ai_investing.data import news                         # noqa: E402

CAP = 5_000_000


class _Patch:
    """Set attributes and put them back, without pulling in a framework."""

    def __init__(self):
        self._undo = []

    def attr(self, obj, name, value):
        self._undo.append((obj, name, getattr(obj, name, None)))
        setattr(obj, name, value)
        return self

    def undo(self):
        for obj, name, old in reversed(self._undo):
            setattr(obj, name, old)
        self._undo = []


class _Settings:
    """Just the fields the chain and the meter actually read."""

    def __init__(self, tmp, chain_fast, chain_smart=(), cap=CAP, key="k"):
        self.state_path = str(Path(tmp) / "state.json")
        self.llm_daily_free_tokens = cap
        self.byteplus_api_key = key
        self.byteplus_chain_fast = list(chain_fast)
        self.byteplus_chain_smart = list(chain_smart)
        self.byteplus_model_fast = chain_fast[0] if chain_fast else ""
        self.byteplus_model_smart = chain_smart[0] if chain_smart else ""


class _Spy:
    """Records which endpoint would have been called. Never hits the network."""

    def __init__(self, answer="{}"):
        self.calls = []
        self.answer = answer

    def __call__(self, prompt, settings, model, max_tokens=1500, json_mode=False):
        self.calls.append(model)
        return self.answer


def _meter(tmp, by_model, refused=0, day=None):
    path = Path(tmp) / "llm_usage.json"
    data = {"day": day or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "by_model": by_model, "by_hour": {}}
    if refused:
        data["refused"] = refused
    path.write_text(json.dumps(data))
    return path


def _chain(tmp, by_model, max_tokens=1000, chain=("vgxfw", "9bxhf", "fj4vw")):
    """Run the real chain against a stubbed meter; return (result, spy)."""
    s = _Settings(tmp, chain)
    _meter(tmp, by_model)
    spy = _Spy()
    p = _Patch().attr(news, "_call_byteplus", spy)
    try:
        out = news._call_byteplus_chain("prompt", s, "fast", max_tokens, False)
    finally:
        p.undo()
    return out, spy


# ------------------------------------------------------------ the core fix ---

def test_every_endpoint_at_the_cap_refuses_instead_of_billing():
    """The bug, exactly: all three past the line, the old code called the head."""
    with tempfile.TemporaryDirectory() as tmp:
        out, spy = _chain(tmp, {"vgxfw": CAP, "9bxhf": CAP, "fj4vw": CAP})
        assert out is None, f"called a spent endpoint: {spy.calls}"
        assert spy.calls == [], f"a spent endpoint was called: {spy.calls}"


def test_the_90_to_100_band_is_used_and_the_head_is_not():
    """The live 2026-09-18 numbers. Spare is empty, but two endpoints still have
    free room -- so the call must land there, never on
    the 122.7% head the old fallback returned to."""
    with tempfile.TemporaryDirectory() as tmp:
        out, spy = _chain(tmp, {"vgxfw": 6_137_482,      # 122.7%
                                "9bxhf": 4_610_282,      # 92.2%
                                "fj4vw": 4_530_679})     # 90.6%
        assert spy.calls == ["9bxhf"], f"went to the wrong endpoint: {spy.calls}"
        assert "vgxfw" not in spy.calls, "routed back into the most-spent endpoint"


def test_preference_order_survives_while_there_is_room():
    """Well under 90% on the head: it is still preferred, so behaviour on a
    normal day is unchanged."""
    with tempfile.TemporaryDirectory() as tmp:
        _out, spy = _chain(tmp, {"vgxfw": 100_000, "9bxhf": 4_900_000,
                                 "fj4vw": 4_900_000})
        assert spy.calls == ["vgxfw"], spy.calls


def test_the_call_that_would_cross_the_line_is_refused():
    """The meter is read BEFORE the call and written AFTER it, so a call must
    not be started that cannot fit inside what is left."""
    with tempfile.TemporaryDirectory() as tmp:
        # 1,000 tokens of room, an 8,000-token response cap -> refuse
        out, spy = _chain(tmp, {"vgxfw": CAP - 1_000}, max_tokens=8_000,
                          chain=("vgxfw",))
        assert out is None and spy.calls == [], spy.calls

        # ...and the same endpoint is callable when the call does fit
        _out2, spy2 = _chain(tmp, {"vgxfw": CAP - 1_000}, max_tokens=500,
                             chain=("vgxfw",))
        assert spy2.calls == ["vgxfw"], spy2.calls


def test_a_refusal_is_recorded_and_surfaced():
    """Refusing is the point, but a brain that stopped reading is a
    degradation -- daily_status.py reports it and the watchdog pages on it."""
    with tempfile.TemporaryDirectory() as tmp:
        out, _spy = _chain(tmp, {"vgxfw": CAP}, chain=("vgxfw",))
        assert out is None
        data = json.loads((Path(tmp) / "llm_usage.json").read_text())
        assert data.get("refused") == 1, data


# ------------------------------------------------- the failure directions ---

def test_an_absent_meter_is_not_a_blackout():
    """`_record_usage` creates the file on the first call of the day, so its
    absence means 'nothing spent yet'. Failing closed here would blind a fresh
    install over a file that is not due to exist."""
    with tempfile.TemporaryDirectory() as tmp:
        s = _Settings(tmp, ("vgxfw",))
        assert not (Path(tmp) / "llm_usage.json").exists()
        assert news._at_free_cap(s, "vgxfw") is False
        spy = _Spy()
        p = _Patch().attr(news, "_call_byteplus", spy)
        try:
            out = news._call_byteplus_chain("p", s, "fast", 1000, False)
        finally:
            p.undo()
        assert out and spy.calls == ["vgxfw"], spy.calls


def test_an_unreadable_meter_splits_the_two_directions():
    """Present but corrupt: rotation must still fail OPEN (the brain keeps
    reading) and the cost gate must fail CLOSED (we cannot prove it is free)."""
    with tempfile.TemporaryDirectory() as tmp:
        s = _Settings(tmp, ("vgxfw",))
        (Path(tmp) / "llm_usage.json").write_text("{ this is not json")
        assert news._over_free_budget(s, "vgxfw") is False, "rotation went closed"
        assert news._at_free_cap(s, "vgxfw") is True, "the cost gate went open"
        spy = _Spy()
        p = _Patch().attr(news, "_call_byteplus", spy)
        try:
            out = news._call_byteplus_chain("p", s, "fast", 1000, False)
        finally:
            p.undo()
        assert out is None and spy.calls == [], spy.calls


def test_stale_meter_from_yesterday_does_not_count_toward_today():
    with tempfile.TemporaryDirectory() as tmp:
        s = _Settings(tmp, ("vgxfw",))
        _meter(tmp, {"vgxfw": 9_000_000}, day="2026-09-17")
        assert news._at_free_cap(s, "vgxfw") is False
        assert news.llm_budget_exhausted(s) is False


def test_no_cap_configured_disables_the_gate():
    """LLM_DAILY_FREE_TOKENS<=0 is an explicit opt-out, not a blackout."""
    with tempfile.TemporaryDirectory() as tmp:
        s = _Settings(tmp, ("vgxfw",), cap=0)
        _meter(tmp, {"vgxfw": 99_000_000})
        assert news._at_free_cap(s, "vgxfw") is False


def test_budget_exhausted_is_about_the_whole_chain():
    with tempfile.TemporaryDirectory() as tmp:
        s = _Settings(tmp, ("vgxfw", "9bxhf"), chain_smart=("9bxhf", "fj4vw"))
        _meter(tmp, {"vgxfw": CAP, "9bxhf": CAP, "fj4vw": CAP})
        assert news.llm_budget_exhausted(s) is True
        # fj4vw is only in the SMART chain -- exhaustion is about both chains,
        # so one endpoint with room anywhere is enough to keep working
        _meter(tmp, {"vgxfw": CAP, "9bxhf": CAP, "fj4vw": CAP - 1_000_000})
        assert news.llm_budget_exhausted(s) is False
        # a box with no BytePlus key cannot be budget-exhausted
        s2 = _Settings(tmp, ("vgxfw",), key="")
        _meter(tmp, {"vgxfw": CAP})
        assert news.llm_budget_exhausted(s2) is False


# ------------------------------------------- the digests must not lose days ---

def _wave():
    import crypto_wave_digest as cw
    return cw


def test_the_wave_digest_leaves_a_day_pending_rather_than_writing_it_empty():
    """An empty amendment is LEGAL here (most staged stories are already
    covered), and it marks the day permanently done -- so a day digested while
    the chain is refusing would silently drop every headline in it."""
    cw = _wave()
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        p = (_Patch()
             .attr(cw, "AMEND_OUT", out)
             .attr(cw, "staged_headlines", lambda date: [{"ts": "2026-09-18T00:00:00Z",
                                                          "title": "t", "source": "s"}])
             .attr(cw, "llm_budget_exhausted", lambda settings: True))
        try:
            kept = cw.digest_day("2026-09-18", object(), _Graph(), False)
        finally:
            p.undo()
        assert kept is False, "a capped day was reported as digested"
        assert not (out / "2026-09-18.json").exists(), \
            "a capped day was written as an empty amendment"


def test_the_wave_digest_stops_mid_day_without_writing_a_partial():
    """The allowance can run out BETWEEN batches. Half a day filed as complete
    is worse than no day at all -- it is unretryable."""
    cw = _wave()
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        seen = {"n": 0}

        def budget(_settings):
            seen["n"] += 1
            return seen["n"] > 1          # pre-flight passes, mid-day fails

        heads = [{"ts": "2026-09-18T00:00:00Z", "title": f"h{i}", "source": "s"}
                 for i in range(cw.CHUNK + 5)]
        p = (_Patch()
             .attr(cw, "AMEND_OUT", out)
             .attr(cw, "staged_headlines", lambda date: heads)
             .attr(cw, "llm_budget_exhausted", budget)
             .attr(cw, "_call_llm", lambda *a, **k: '{"events": [], "amendments": []}')
             .attr(cw, "existing_events", lambda date: []))
        try:
            kept = cw.digest_day("2026-09-18", object(), _Graph(), False)
        finally:
            p.undo()
        assert kept is False, "a truncated day was reported as digested"
        assert not (out / "2026-09-18.json").exists(), \
            "a truncated day was written as complete"


def test_the_daily_digest_keeps_its_checkpoint_when_capped():
    """digest_day.py already refuses to write an empty day; the cap must also
    stop it writing a PARTIAL one, and must not throw away the checkpoint."""
    import digest_day as dd
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        brief = out / "brief.md"
        brief.write_text("brief")
        heads = [{"ts": "2026-09-18T00:00:00Z", "title": f"h{i}", "source": "s"}
                 for i in range(dd.CHUNK * 2)]
        p = (_Patch()
             .attr(dd, "OUT_DIR", out)
             .attr(dd, "BRIEF", brief)
             .attr(dd, "headlines_for", lambda date: heads)
             .attr(dd, "llm_budget_exhausted", lambda settings: True))
        try:
            rc = dd.digest("2026-09-18", object(), _Graph(), False)
        finally:
            p.undo()
        assert rc == 1, f"capped digest reported success ({rc})"
        assert not (out / "2026-09-18.json").exists(), "wrote a capped day"


class _Graph:
    class _Nodes:
        def values(self):
            return []

    nodes = _Nodes()


if __name__ == "__main__":
    for _name, _fn in sorted(list(globals().items())):
        if _name.startswith("test_") and callable(_fn):
            _fn()
    print("ok")
