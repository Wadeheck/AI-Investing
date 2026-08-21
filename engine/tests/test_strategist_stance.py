"""A thesis the system cannot express is a wasted slot, not a cautious one.

§4.42. `strategist._PROMPT` told the model "shorting overvalued/bubble names is
a valid thesis when valuations support it" — while `SHARED_STOCK_ACCOUNT`
refuses every stock short at the venue. On 2026-08-21 the live strategy held 5
theses (`MAX_THESES = 5`) and TWO were shorts: `short-tech-bubble` -> TSLA and
`short-energy-stress` -> JKS. Both had been re-submitted and rejected every
cycle since 08-19; the investing book sat 57% cash. 40% of scarce idea capacity
producing a daily rejection and never a position.

Two layers, deliberately, because a prompt instruction is not a control:
  1. the RULE follows execution (`_shorts_rule`), and
  2. INGESTION enforces it, because the model may ignore the instruction and the
     cost of that is a permanently dead slot.

Crypto is untouched — the event sleeve genuinely can short perpetual futures.
"""
import json
import os
import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_investing.brain import strategist as st

_TMP = tempfile.mkdtemp()


def _settings(shared=True, allow_short=False):
    return types.SimpleNamespace(
        shared_stock_account=shared,
        risk=types.SimpleNamespace(allow_short=allow_short))


# ------------------------------------------------------------ the rule ----
def test_the_rule_follows_what_execution_accepts():
    banned = st._shorts_rule(_settings(shared=True))
    assert "CANNOT BE EXECUTED" in banned
    assert 'stance "avoid"' in banned, "it must name the claim that DOES work"

    allowed = st._shorts_rule(_settings(shared=False, allow_short=True))
    assert "valid thesis" in allowed and "CANNOT" not in allowed


def test_shorts_are_unavailable_under_a_shared_account_or_a_risk_veto():
    assert st.stock_shorts_available(_settings(shared=True, allow_short=True)) is False, \
        "the shared account refuses shorts regardless of the risk flag"
    assert st.stock_shorts_available(_settings(shared=False, allow_short=False)) is False
    assert st.stock_shorts_available(_settings(shared=False, allow_short=True)) is True


def test_an_unreadable_config_assumes_shorts_are_impossible():
    """Fail closed. Proposing a thesis that cannot open is the expensive
    direction of this decision."""
    assert st.stock_shorts_available(object()) is False


# ------------------------------------------------------- the enforcement ----
def _ingest(settings, proposals):
    """Drive the REAL ingestion path (`challenge_strategy`) with a stubbed model.

    `web={}` skips the web-veto lookup, which is a separate rule with its own
    coverage and would otherwise need live brain state.
    """
    settings.stock_watchlist = ["TSLA", "JKS"]
    settings.crypto_watchlist = ["BTC/USD"]
    settings.brain = types.SimpleNamespace(graph_path=os.path.join(_TMP, "graph.json"))
    settings.state_path = os.path.join(_TMP, "state.json")
    strat = {"theses": [], "changes": [], "market_outlook": ""}
    return st.challenge_strategy(
        settings, strat, evidence={},
        # the real llm hook returns TEXT that the caller parses
        llm=lambda _p: json.dumps({"market_outlook": "x", "theses": proposals}),
        web={})


def test_a_stock_short_is_downgraded_to_avoid_when_it_cannot_execute():
    """The enforcement, on the exact live shape: `short-tech-bubble` -> TSLA."""
    out = _ingest(_settings(shared=True), [
        {"id": "short-tech-bubble", "title": "Short Overvalued Tech",
         "stance": "short", "symbols": ["TSLA"], "thesis": "t", "assumptions": "a"},
    ])
    thesis = next(t for t in out["theses"] if t["id"] == "short-tech-bubble")
    assert thesis["stance"] == "avoid", \
        "a stock short that cannot open must become the claim that can"
    assert "short -> avoid" in (out.get("challenge_note") or ""), \
        f"the downgrade must be recorded, not silent: {out.get('challenge_note')!r}"


def test_a_stock_short_survives_where_shorting_really_works():
    out = _ingest(_settings(shared=False, allow_short=True), [
        {"id": "short-tech-bubble", "title": "Short Overvalued Tech",
         "stance": "short", "symbols": ["TSLA"], "thesis": "t", "assumptions": "a"},
    ])
    thesis = next(t for t in out["theses"] if t["id"] == "short-tech-bubble")
    assert thesis["stance"] == "short", "do not disarm a book that CAN short"


def test_a_crypto_short_is_never_downgraded():
    """The event sleeve genuinely shorts perpetual futures. The stock venue's
    limitation must not reach it."""
    out = _ingest(_settings(shared=True), [
        {"id": "short-crypto", "title": "Short crypto", "stance": "short",
         "symbols": ["BTC/USD"], "thesis": "t", "assumptions": "a"},
    ])
    thesis = next(t for t in out["theses"] if t["id"] == "short-crypto")
    assert thesis["stance"] == "short"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\nAll {len(tests)} strategist-stance tests passed.")
