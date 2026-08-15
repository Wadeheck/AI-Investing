"""Tests for the automatic adviser-sizing evidence gate (brain/adviser_gate.py).

Verifies: the measurement queries against real schemas, the eligibility
threshold logic (fails closed on every axis independently), and the bounded,
capped nudge apply_adviser_gate() applies to live decisions once (and only
once) the gate has been independently marked eligible."""
import json
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ai_investing.brain import adviser_gate as ag  # noqa: E402
from ai_investing.models import Asset, AssetClass, Decision, SignalDirection  # noqa: E402


class FakeBrainCfg:
    def __init__(self, db_path, advice_path):
        self.db_path = db_path
        self.advice_path = advice_path


class FakeSettings:
    def __init__(self, tmp):
        self.db_path = os.path.join(tmp, "journal.db")
        self.state_path = os.path.join(tmp, "state.json")
        self.brain = FakeBrainCfg(os.path.join(tmp, "brain.db"), os.path.join(tmp, "advice.json"))


def _make_brain_db(path, advice_rows, price_rows):
    con = sqlite3.connect(path)
    con.execute("""CREATE TABLE advice_outcomes (
        advice_id INTEGER, symbol TEXT, direction TEXT, ts_issued TEXT,
        hit INTEGER, is_conviction INTEGER)""")
    con.executemany(
        "INSERT INTO advice_outcomes (advice_id,symbol,direction,ts_issued,hit,is_conviction) "
        "VALUES (?,?,?,?,?,?)", advice_rows)
    con.execute("CREATE TABLE price_history (date TEXT, symbol TEXT, price REAL)")
    con.executemany("INSERT INTO price_history (date,symbol,price) VALUES (?,?,?)", price_rows)
    con.commit()
    con.close()


def _make_journal_db(path, decision_rows):
    con = sqlite3.connect(path)
    con.execute("""CREATE TABLE decisions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, symbol TEXT, direction TEXT,
        score REAL, confidence REAL)""")
    con.executemany(
        "INSERT INTO decisions (ts,symbol,direction,score,confidence) VALUES (?,?,?,?,?)",
        decision_rows)
    con.commit()
    con.close()


def test_adviser_long_stats_counts_only_conviction_long_hits():
    tmp = tempfile.mkdtemp()
    rows = [
        (1, "GLD", "long", "2026-08-01T00:00:00", 1, 1),
        (2, "GLD", "long", "2026-08-02T00:00:00", 0, 1),
        (3, "TSLA", "avoid", "2026-08-01T00:00:00", 1, 1),      # wrong direction, excluded
        (4, "AAPL", "long", "2026-08-01T00:00:00", 1, 0),       # not conviction, excluded
        (5, "SOL/USD", "long", "2026-08-03T00:00:00", None, 1), # ungraded, excluded
    ]
    _make_brain_db(os.path.join(tmp, "brain.db"), rows, [])
    stats = ag._adviser_long_stats(os.path.join(tmp, "brain.db"))
    assert stats["n"] == 2
    assert stats["hit"] == 0.5
    assert stats["days"] == 2


def test_formula_short_stats_dedupes_and_grades_against_benchmark():
    tmp = tempfile.mkdtemp()
    day = "2026-08-01"
    exit_day = (datetime.fromisoformat(day) + timedelta(days=ag.HORIZON_DAYS)).date().isoformat()
    prices = [
        (day, "AAPL", 100.0), (exit_day, "AAPL", 90.0),      # AAPL fell 10% -> correct avoid
        (day, "SPY", 100.0), (exit_day, "SPY", 100.0),        # benchmark flat
    ]
    _make_brain_db(os.path.join(tmp, "brain.db"), [], prices)
    decisions = [
        ("2026-08-01T09:00:00", "AAPL", "short", -0.5, 0.5),   # earlier same-day call
        ("2026-08-01T15:00:00", "AAPL", "short", -0.6, 0.6),   # LAST call that day -> the graded one
        ("2026-08-01T10:00:00", "AAPL", "long", 0.4, 0.4),     # different direction, ignored
    ]
    _make_journal_db(os.path.join(tmp, "journal.db"), decisions)
    stats = ag._formula_short_stats(os.path.join(tmp, "journal.db"), os.path.join(tmp, "brain.db"))
    assert stats["n"] == 1
    assert stats["hit"] == 1.0     # AAPL underperformed SPY -> a correct "avoid"
    assert stats["days"] == 1


def test_formula_short_stats_diverges_from_absolute_fall_rule():
    """The case that pins down which grading rule is used. AAPL FELL (a hit
    under the absolute-fall rule) but the market fell MORE, so AAPL actually
    OUTPERFORMED -- a MISS under the excess/avoid rule this system is
    supposed to use, since nothing here can short stocks. If this ever
    regresses to verdict("short", ...), this test flips to a false hit."""
    tmp = tempfile.mkdtemp()
    day = "2026-08-01"
    exit_day = (datetime.fromisoformat(day) + timedelta(days=ag.HORIZON_DAYS)).date().isoformat()
    prices = [
        (day, "AAPL", 100.0), (exit_day, "AAPL", 95.0),    # AAPL fell 5%...
        (day, "SPY", 100.0), (exit_day, "SPY", 85.0),      # ...but SPY fell 15% -> AAPL beat it
    ]
    _make_brain_db(os.path.join(tmp, "brain.db"), [], prices)
    decisions = [("2026-08-01T09:00:00", "AAPL", "short", -0.5, 0.5)]
    _make_journal_db(os.path.join(tmp, "journal.db"), decisions)
    stats = ag._formula_short_stats(os.path.join(tmp, "journal.db"), os.path.join(tmp, "brain.db"))
    assert stats["n"] == 1
    assert stats["hit"] == 0.0     # excess = -5% - (-15%) = +10% -> AAPL beat the market -> miss


def test_evaluate_fails_closed_below_every_threshold():
    tmp = tempfile.mkdtemp()
    _make_brain_db(os.path.join(tmp, "brain.db"), [], [])
    _make_journal_db(os.path.join(tmp, "journal.db"), [])
    settings = FakeSettings(tmp)
    result = ag.evaluate(settings)
    assert result["eligible"] is False
    assert os.path.exists(ag._gate_path(settings))
    assert ag.is_enabled(settings) is False


def test_evaluate_flips_eligible_once_all_four_conditions_clear():
    tmp = tempfile.mkdtemp()
    start = datetime(2026, 6, 1)
    # 45 consecutive calendar days -> every day's +horizon exit date is itself
    # one of these days too, so each (date, symbol) gets exactly one price --
    # a real daily series, not two colliding synthetic entry/exit values.
    calendar = [(start + timedelta(days=i)).date().isoformat() for i in range(45)]
    days = calendar[:31]   # the 31 days actually used as decision/advice days

    advice_rows = []
    for i in range(560):
        d = days[i % len(days)]
        hit = 1 if i % 10 != 0 else 0   # 90% hit rate, well above 0.60
        advice_rows.append((i, "GLD", "long", f"{d}T00:00:00", hit, 1))

    symbols = [f"SYM{k}" for k in range(20)]   # 20 symbols x 31 days = 620 graded (symbol, day) calls
    price_rows = [(d, "SPY", 100.0) for d in calendar]   # benchmark flat throughout
    for sym in symbols:
        for i, d in enumerate(calendar):
            price_rows.append((d, sym, 100.0 * (1.01 ** i)))   # steadily rising -> every "short" is wrong
    decision_rows = []
    for d in days:
        for sym in symbols:
            decision_rows.append((f"{d}T09:00:00", sym, "short", -0.5, 0.5))
            decision_rows.append((f"{d}T15:00:00", sym, "short", -0.6, 0.6))  # same-day dup
    _make_brain_db(os.path.join(tmp, "brain.db"), advice_rows, price_rows)
    _make_journal_db(os.path.join(tmp, "journal.db"), decision_rows)

    settings = FakeSettings(tmp)
    result = ag.evaluate(settings)
    assert result["adviser_long"]["n"] >= 500
    assert result["adviser_long"]["days"] >= 30
    assert result["adviser_long"]["hit"] > 0.60
    assert result["formula_short"]["n"] >= 500
    assert result["formula_short"]["days"] >= 30
    assert result["formula_short"]["hit"] < 0.35    # AAPL rose every time -> shorts all wrong
    assert result["eligible"] is True
    assert ag.is_enabled(settings) is True


def _decision(symbol, target_weight):
    return Decision(asset=Asset(symbol, AssetClass.STOCK), target_weight=target_weight,
                    direction=SignalDirection.FLAT, score=0.0, confidence=0.0)


def test_apply_adviser_gate_is_a_no_op_when_disabled():
    tmp = tempfile.mkdtemp()
    settings = FakeSettings(tmp)   # no gate file written -> is_enabled() False
    decisions = [_decision("GLD", 0.1)]
    out = ag.apply_adviser_gate(decisions, settings)
    assert out[0].target_weight == 0.1


def test_apply_adviser_gate_nudges_and_caps_when_enabled():
    tmp = tempfile.mkdtemp()
    settings = FakeSettings(tmp)
    with open(ag._gate_path(settings), "w") as fh:
        json.dump({"eligible": True}, fh)
    with open(settings.brain.advice_path, "w") as fh:
        json.dump({"trades": [{"symbol": "GLD", "score": 1.0}],
                   "watch": [{"symbol": "O39.SI", "score": -1.0}]}, fh)

    decisions = [_decision("GLD", 0.85), _decision("O39.SI", -0.85), _decision("UNRELATED", 0.2)]
    out = ag.apply_adviser_gate(decisions, settings)
    by_sym = {d.asset.symbol: d for d in out}

    assert by_sym["GLD"].target_weight == 1.0          # 0.85 + 0.25*1.0 capped at 1.0
    assert "adviser-gate" in by_sym["GLD"].rationale
    assert by_sym["GLD"].direction == SignalDirection.LONG

    assert by_sym["O39.SI"].target_weight == -1.0       # capped at -1.0
    assert by_sym["O39.SI"].direction == SignalDirection.SHORT

    assert by_sym["UNRELATED"].target_weight == 0.2     # no adviser score -> untouched


def _enabled_settings(advice):
    """A gate that is switched ON, with a given adviser advice file."""
    tmp = tempfile.mkdtemp()
    settings = FakeSettings(tmp)
    with open(ag._gate_path(settings), "w") as fh:
        json.dump({"eligible": True}, fh)
    with open(settings.brain.advice_path, "w") as fh:
        json.dump(advice, fh)
    return settings


def test_apply_adviser_gate_never_originates_a_position():
    """The gate scales conviction the formula already has; it does not create
    conviction the formula declined to have. The evidence this gate measures is
    that the adviser out-ranks the formula's short/avoid calls -- nothing in it
    says the adviser can pick entries the formula passed on entirely, so a flat
    decision must stay flat no matter how strongly the adviser likes the name."""
    settings = _enabled_settings({"trades": [{"symbol": "GLD", "score": 5.0}]})
    out = ag.apply_adviser_gate([_decision("GLD", 0.0)], settings)
    assert out[0].target_weight == 0.0
    assert out[0].direction == SignalDirection.FLAT
    assert "adviser-gate" not in out[0].rationale


def test_apply_adviser_gate_clamps_an_unbounded_adviser_score():
    """adviser.py's `score` is a weighted SUM (W_FIELD 1.0 + W_FORMULA 0.6 +
    W_SCENARIO 0.5 + ...), not a [-1,1] conviction -- it can exceed 1 comfortably.
    Without clamping, BLEND_WEIGHT stops meaning "at most a 0.25 shift" and the
    tilt is bounded only by the book's own ±1.0 cap, which is a completely
    different (and much larger) claim than 'bounded nudge, never an override'."""
    settings = _enabled_settings({"trades": [{"symbol": "GLD", "score": 12.0}]})
    out = ag.apply_adviser_gate([_decision("GLD", 0.30)], settings)
    # 0.30 + 0.25*clamp(12.0) == 0.55, NOT 0.30 + 0.25*12.0 clipped to 1.0
    assert abs(out[0].target_weight - 0.55) < 1e-9, out[0].target_weight


def test_apply_adviser_gate_cannot_flip_the_formulas_sign():
    """A 'nudge' that reverses the direction of the trade is an override wearing
    a smaller number. A hostile adviser score can zero the position out, but it
    cannot turn the formula's long into a short."""
    settings = _enabled_settings({"trades": [{"symbol": "GLD", "score": -1.0}]})
    out = ag.apply_adviser_gate([_decision("GLD", 0.10)], settings)
    assert out[0].target_weight == 0.0          # 0.10 - 0.25 would have been -0.15
    assert out[0].direction == SignalDirection.FLAT


if __name__ == "__main__":
    for _name, _fn in sorted(list(globals().items())):
        if _name.startswith("test_") and callable(_fn):
            _fn()
    print("ok")
