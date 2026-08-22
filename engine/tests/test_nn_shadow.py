"""The NN's shadow book: it must decide, record, and be gradable — and it must
never be able to touch the live brain.

The isolation tests are the important half. A shadow that can reach the live
formula, the live book, or the real broker is not a shadow, and the failure
would be silent: the engine would keep trading and the numbers would drift.
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_TMP = tempfile.mkdtemp()
os.environ["STATE_PATH"] = os.path.join(_TMP, "state.json")

from ai_investing.config import Settings  # noqa: E402
from ai_investing.learning import nn_shadow  # noqa: E402
from ai_investing.learning.nn_formula import NNFormulaModel  # noqa: E402


def _settings():
    d = tempfile.mkdtemp()
    os.environ["STATE_PATH"] = os.path.join(d, "state.json")
    return Settings()


def _fit_a_net(s, feature_names=None):
    """Write a plausible fitted net where the lane expects one."""
    names = feature_names or ["bias", "momentum", "mean_reversion"]
    m = NNFormulaModel(hidden=2, feature_names=names,
                       W1=[[0.1] * len(names), [-0.1] * len(names)],
                       b1=[0.0, 0.0], W2=[0.5, -0.5], b2=0.0)
    d = os.path.join(os.path.dirname(os.path.abspath(s.state_path)),
                     nn_shadow.SHADOW_DIR)
    os.makedirs(d, exist_ok=True)
    Path(d, "formula.json").write_text(json.dumps(
        {"model_type": "nn", "model": m.to_dict()}))
    return m


# --- availability -----------------------------------------------------------

def test_no_net_yet_is_the_normal_state_and_it_says_why():
    """Unavailable until the weekly challenger fits one. A randomly initialised
    net trading a book would produce a record that LOOKS like evidence."""
    b = nn_shadow.NNShadowBook(_settings())
    assert not b.available
    assert "no net fitted yet" in b.reason, b.reason


def test_a_fitted_net_brings_the_lane_up():
    s = _settings()
    _fit_a_net(s)
    b = nn_shadow.NNShadowBook(s)
    assert b.available and b.model is not None
    assert b.engine.user_views.view_for("AAPL") is None, \
        "the net is judged on its own read, not the operator's tilts"


# --- the counting unit ------------------------------------------------------

def test_one_primary_per_symbol_per_day_not_one_per_cycle():
    """§4.37. The engine cycles every ~8 minutes; journalling a primary per
    cycle would re-log one standing view ~65 times a day against the same
    forward return, which is exactly the defect that inflated the brain's whole
    evidence base 65x. Every row is written; one per (symbol, day) counts."""
    s = _settings()
    _fit_a_net(s)
    b = nn_shadow.NNShadowBook(s)
    day = nn_shadow._sgt_day(datetime.now(timezone.utc))

    b._append([{"day": day, "symbol": "AAPL", "is_primary": True, "nn": {}},
               {"day": day, "symbol": "AAPL", "is_primary": False, "nn": {}},
               {"day": day, "symbol": "MSFT", "is_primary": True, "nn": {}}])
    assert b._primary_symbols_for(day) == {"AAPL", "MSFT"}
    assert len(b.read_primaries()) == 2, "replicas must never be counted"


def test_a_restart_mid_day_cannot_mint_a_second_primary():
    """`_primary_symbols_for` reads DISK, not memory. If it kept the set in
    process state, every restart would create a fresh primary for symbols
    already recorded that day — the 65x defect returning through the back
    door, and invisible because the rows would all look correct."""
    s = _settings()
    _fit_a_net(s)
    day = nn_shadow._sgt_day(datetime.now(timezone.utc))
    first = nn_shadow.NNShadowBook(s)
    first._append([{"day": day, "symbol": "AAPL", "is_primary": True, "nn": {}}])

    reborn = nn_shadow.NNShadowBook(s)          # simulates a process restart
    assert reborn._primary_symbols_for(day) == {"AAPL"}


# --- grading, including the half that is normally missing -------------------

def _row(day, symbol, direction, price, brain=None):
    return {"day": day, "symbol": symbol, "is_primary": True, "price": price,
            "nn": {"direction": direction},
            "brain": None if brain is None else {"direction": brain}}


def test_standing_aside_is_graded_as_a_decision():
    """The half the operator asked for. A book that never trades has no losses
    and looks disciplined; counting its MISSES is what separates discipline
    from paralysis. A P&L-only record can never show this."""
    s = _settings()
    _fit_a_net(s)
    old = nn_shadow._sgt_day(datetime.now(timezone.utc) - timedelta(days=30))
    b = nn_shadow.NNShadowBook(s)
    b._append([
        _row(old, "AAPL", "LONG", 100.0),     # settles 110 -> captured
        _row(old, "MSFT", "LONG", 100.0),     # settles  90 -> wrong
        _row(old, "NVDA", "FLAT", 100.0),     # settles 110 -> MISSED
        _row(old, "KO",   "FLAT", 100.0),     # settles 100.5 -> avoided
    ])
    settle = {"AAPL": 110.0, "MSFT": 90.0, "NVDA": 110.0, "KO": 100.5}
    out = nn_shadow.grade(s, lambda sym, d: settle.get(sym))

    assert (out["captured"], out["wrong"]) == (1, 1)
    assert out["missed"] == 1, "a FLAT call through a 10% move is a missed opportunity"
    assert out["avoided"] == 1, "a FLAT call through a 0.5% move is correct restraint"
    assert out["hit_rate_when_positioned"] == 0.5


def test_a_small_move_is_not_a_missed_opportunity():
    """Without the threshold, every FLAT call scores as a miss and the net is
    pushed to be permanently long everything."""
    s = _settings()
    _fit_a_net(s)
    old = nn_shadow._sgt_day(datetime.now(timezone.utc) - timedelta(days=30))
    b = nn_shadow.NNShadowBook(s)
    b._append([_row(old, "KO", "FLAT", 100.0)])
    just_under = 100.0 + nn_shadow.OPPORTUNITY_PCT - 0.01
    out = nn_shadow.grade(s, lambda sym, d: just_under)
    assert out["missed"] == 0 and out["avoided"] == 1


def test_the_brain_is_scored_on_the_same_rows():
    """The comparison is a row lookup, not a join across two systems on a
    timestamp — which is where this kind of comparison usually rots."""
    s = _settings()
    _fit_a_net(s)
    old = nn_shadow._sgt_day(datetime.now(timezone.utc) - timedelta(days=30))
    b = nn_shadow.NNShadowBook(s)
    b._append([
        _row(old, "AAPL", "LONG", 100.0, brain="FLAT"),   # rises: nn right
        _row(old, "MSFT", "FLAT", 100.0, brain="LONG"),   # rises: brain right
        _row(old, "NVDA", "LONG", 100.0, brain="LONG"),   # agree
    ])
    out = nn_shadow.grade(s, lambda sym, d: 110.0)
    assert out["agree_with_brain"] == 1 and out["disagree"] == 2
    assert out["nn_right_brain_wrong"] == 1
    assert out["brain_right_nn_wrong"] == 1


def test_overlapping_windows_are_deflated_not_counted_raw():
    """AUDITING.md trap 2. Daily readings of a 5-day forward return share 4/5 of
    their window, so `graded` overstates the evidence ~5x."""
    s = _settings()
    _fit_a_net(s)
    old = nn_shadow._sgt_day(datetime.now(timezone.utc) - timedelta(days=30))
    b = nn_shadow.NNShadowBook(s)
    b._append([_row(old, f"S{i}", "LONG", 100.0) for i in range(20)])
    out = nn_shadow.grade(s, lambda sym, d: 110.0)
    assert out["graded"] == 20
    assert out["n_independent"] == 4, "20 daily readings of a 5d return are ~4 bets"


# --- ISOLATION: the part that must never regress ----------------------------

def test_the_lane_writes_nothing_outside_its_own_directory():
    """Structural, not conventional. If this ever fails, a shadow is writing
    where the live system reads and the engine keeps trading regardless."""
    s = _settings()
    _fit_a_net(s)
    data_dir = Path(os.path.dirname(os.path.abspath(s.state_path)))
    for name in ("formula.json", "state.json", "shadow.json", "live_book.json"):
        Path(data_dir, name).write_text('{"sentinel": true}')
    before = {p.name: p.read_text() for p in data_dir.iterdir() if p.is_file()}

    b = nn_shadow.NNShadowBook(s)
    day = nn_shadow._sgt_day(datetime.now(timezone.utc))
    b._append([_row(day, "AAPL", "LONG", 100.0)])

    after = {p.name: p.read_text() for p in data_dir.iterdir() if p.is_file()}
    assert after == before, \
        f"the NN lane wrote into the live data dir: {set(after) ^ set(before)}"
    assert Path(data_dir, nn_shadow.SHADOW_DIR, nn_shadow.DECISIONS).exists()


def test_the_lane_never_shares_a_model_object_with_the_live_formula():
    """The live engine trades `runner.model`. If the shadow held the same
    object, fitting or perturbing the net would silently move live sizing."""
    s = _settings()
    _fit_a_net(s)
    from ai_investing.learning.formula import FormulaModel
    live = FormulaModel()
    b = nn_shadow.NNShadowBook(s)
    assert b.model is not live
    assert not isinstance(b.model, FormulaModel), "the shadow must run the NN"
    assert b.engine.model is b.model


def test_an_unpriced_order_is_dropped_not_filled_at_zero():
    """§4A: `prices.get(key, 0.0)` is how `shadow.json` came to hold NaN. The
    same sentinel must not be reintroduced in a new lane."""
    s = _settings()
    _fit_a_net(s)
    b = nn_shadow.NNShadowBook(s)
    filled = []
    b.broker.submit = lambda o, p: filled.append((o, p))

    class _A:
        key, symbol = "AAPL", "AAPL"

    class _O:
        asset = _A()
    b._fill(_O(), {})                     # absent
    b._fill(_O(), {"AAPL": 0.0})          # zero
    b._fill(_O(), {"AAPL": float("nan")})  # NaN
    assert filled == [], "an unpriced order must never reach the broker"
    b._fill(_O(), {"AAPL": 10.0})
    assert len(filled) == 1


# --- persisting the net: NOT adoption, and structurally cannot become it ----

def test_the_fitted_net_is_reachable_even_when_the_gate_refuses_it():
    """ADOPTION and SHADOW-PERSISTENCE are different questions. `result["model"]`
    is the CHOSEN model, so a net the deflated-Sharpe gate refused used to be
    unreachable — meaning the one candidate most worth watching was the one
    nobody could watch. `nn_model` exposes it win or lose; `adopted` is
    untouched."""
    import inspect
    from ai_investing.backtest import walkforward
    src = inspect.getsource(walkforward)
    assert '"nn_model": nn["model"]' in src, \
        "the fitted net must be reachable regardless of adoption"


def test_saving_the_shadow_net_refuses_any_path_outside_nn_shadow():
    """The guard is STRUCTURAL, not a convention. Redirecting PARAMS_PATH in a
    systemd unit is a convention and conventions get edited; this is a rule the
    code enforces, so a mis-set env var cannot drop an unadopted net where the
    live engine loads its formula."""
    from ai_investing.backtest.main import _save_nn_shadow

    d = tempfile.mkdtemp()
    live = Path(d, "formula.json")

    class _S:
        params_path = str(live)
    _save_nn_shadow(_S(), {"nn_model": NNFormulaModel(
        hidden=2, feature_names=["bias", "momentum"],
        W1=[[0.1, 0.1], [-0.1, -0.1]], b1=[0.0, 0.0], W2=[0.5, -0.5], b2=0.0)})
    assert not live.exists(), \
        "an unadopted net must never be written where the live engine reads"


def test_saving_the_shadow_net_writes_inside_nn_shadow():
    from ai_investing.backtest.main import _save_nn_shadow
    d = tempfile.mkdtemp()
    dest = Path(d, "nn_shadow", "formula.json")

    class _S:
        params_path = str(dest)
    _save_nn_shadow(_S(), {"nn_model": NNFormulaModel(
        hidden=2, feature_names=["bias", "momentum"],
        W1=[[0.1, 0.1], [-0.1, -0.1]], b1=[0.0, 0.0], W2=[0.5, -0.5], b2=0.0)})
    assert dest.exists()
    assert json.loads(dest.read_text()).get("model_type") == "nn"


def test_no_net_fitted_writes_nothing_rather_than_an_empty_file():
    from ai_investing.backtest.main import _save_nn_shadow
    d = tempfile.mkdtemp()
    dest = Path(d, "nn_shadow", "formula.json")

    class _S:
        params_path = str(dest)
    _save_nn_shadow(_S(), {"nn_model": None})
    assert not dest.exists(), "a run that fitted nothing must leave no net behind"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\nAll {len(tests)} nn-shadow tests passed.")
