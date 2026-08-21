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


def test_adviser_long_stats_counts_symbol_days_not_rows():
    """The 65x defect, pinned.

    `advice_log` is written every cycle, so the scorecard freezes one graded row
    per cycle for the SAME standing view against the SAME forward return. On the
    production record that was 38,900 rows against 598 real observations. This
    side of the gate counted rows while `_formula_short_stats` counted
    (symbol, day) observations -- two units, one shared `min_n`.

    130 rows of one view on one day is one observation, and the hit-rate must be
    that of the FIRST call of the day, not of whichever re-issue happened to
    land last.
    """
    tmp = tempfile.mkdtemp()
    # all within 00:00-15:00 UTC, so +8h keeps every row on the same SGT day
    rows = [(1, "NVDA", "long", "2026-08-01T00:10:00", 1, 1)]     # first call: a hit
    rows += [(i, "NVDA", "long", f"2026-08-01T{i % 16:02d}:30:00", 0, 1)
             for i in range(2, 131)]                              # 129 re-issues, all misses
    _make_brain_db(os.path.join(tmp, "brain.db"), rows, [])
    stats = ag._adviser_long_stats(os.path.join(tmp, "brain.db"))
    assert stats["n"] == 1, "130 re-issues of one view is one observation"
    assert stats["hit"] == 1.0, "the first call of the day is the graded one"
    assert stats["days"] == 1
    # and the whole point: this can never reach the threshold on volume alone
    assert stats["n"] < ag.THRESH["min_n"]


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

    # n counts (symbol, day) observations on BOTH sides now, so the adviser
    # fixture needs real breadth rather than volume: 4 symbols x 31 days = 124
    # observations, above min_n=80. The `+ many re-issues of each` below is
    # deliberate — it is the shape that used to inflate n to 65x and must not
    # move the number.
    advice_rows = []
    adv_symbols = ["GLD", "O39.SI", "2899.HK", "AMD"]
    aid = 0
    for d in days:
        for k, sym in enumerate(adv_symbols):
            hit = 1 if (k + days.index(d)) % 10 != 0 else 0   # ~90%, well above 0.60
            aid += 1
            advice_rows.append((aid, sym, "long", f"{d}T00:00:00", hit, 1))
            for _ in range(9):        # 9 re-issues of the same view, same day
                aid += 1
                advice_rows.append((aid, sym, "long", f"{d}T12:00:00", hit, 1))

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
    # 4 symbols x 31 days = 124 observations, NOT the 1,240 rows that were written
    assert result["adviser_long"]["n"] == len(adv_symbols) * len(days)
    assert result["adviser_long"]["n"] >= ag.THRESH["min_n"]
    assert result["adviser_long"]["days"] >= 30
    assert result["adviser_long"]["hit"] > 0.60
    assert result["formula_short"]["n"] >= ag.THRESH["min_n"]
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


# Every driver dict below is pure `field`, i.e. entirely INDEPENDENT of the
# formula, so independent_score() passes the score through unchanged and these
# tests exercise the blending arithmetic rather than the decomposition.
FIELD_ONLY = {"field": 1.0, "formula": 0.0, "scenarios": 0.0}


def test_apply_adviser_gate_nudges_and_caps_when_enabled():
    tmp = tempfile.mkdtemp()
    settings = FakeSettings(tmp)
    with open(ag._gate_path(settings), "w") as fh:
        json.dump({"eligible": True, "adviser_long": {"hit": 0.75}}, fh)   # beta = BLEND_MAX
    with open(settings.brain.advice_path, "w") as fh:
        json.dump({"trades": [{"symbol": "GLD", "score": 1.0, "drivers": FIELD_ONLY}],
                   "watch": [{"symbol": "O39.SI", "score": -1.0, "drivers": FIELD_ONLY}]}, fh)

    decisions = [_decision("GLD", 0.95), _decision("O39.SI", -0.95), _decision("UNRELATED", 0.2)]
    out = ag.apply_adviser_gate(decisions, settings)
    by_sym = {d.asset.symbol: d for d in out}

    assert by_sym["GLD"].target_weight == 1.0          # 0.95 + 0.10*1.0 capped at 1.0
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
        json.dump({"eligible": True, "adviser_long": {"hit": 0.75}}, fh)
    with open(settings.brain.advice_path, "w") as fh:
        json.dump(advice, fh)
    return settings


def test_apply_adviser_gate_never_originates_a_position():
    """The gate scales conviction the formula already has; it does not create
    conviction the formula declined to have. The evidence this gate measures is
    that the adviser out-ranks the formula's short/avoid calls -- nothing in it
    says the adviser can pick entries the formula passed on entirely, so a flat
    decision must stay flat no matter how strongly the adviser likes the name."""
    settings = _enabled_settings({"trades": [{"symbol": "GLD", "score": 5.0, "drivers": FIELD_ONLY}]})
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
    settings = _enabled_settings({"trades": [{"symbol": "GLD", "score": 12.0, "drivers": FIELD_ONLY}]})
    out = ag.apply_adviser_gate([_decision("GLD", 0.30)], settings)
    # 0.30 + 0.10*clamp(12.0) == 0.40, NOT 0.30 + 0.10*12.0 clipped to 1.0
    assert abs(out[0].target_weight - 0.40) < 1e-9, out[0].target_weight


def test_apply_adviser_gate_cannot_flip_the_formulas_sign():
    """A 'nudge' that reverses the direction of the trade is an override wearing
    a smaller number. A hostile adviser score can zero the position out, but it
    cannot turn the formula's long into a short."""
    settings = _enabled_settings({"trades": [{"symbol": "GLD", "score": -1.0, "drivers": FIELD_ONLY}]})
    out = ag.apply_adviser_gate([_decision("GLD", 0.05)], settings)
    assert out[0].target_weight == 0.0          # 0.05 - 0.10 would have been -0.05
    assert out[0].direction == SignalDirection.FLAT



# -- the blend weight itself -------------------------------------------------

def test_blend_weight_is_zero_until_the_gate_is_eligible():
    assert ag.blend_weight({"eligible": False, "adviser_long": {"hit": 0.99}}) == 0.0
    assert ag.blend_weight({}) == 0.0
    assert ag.blend_weight({"eligible": True}) == 0.0            # no measurement -> no tilt
    assert ag.blend_weight({"eligible": True, "adviser_long": {"hit": None}}) == 0.0


def test_blend_weight_has_no_cliff_at_the_eligibility_threshold():
    """The day the gate flips eligible, a 0.601 hit-rate is not meaningfully
    better than the 0.600 that failed the day before. If beta jumped straight to
    its full value, every position in the book would move at once on that
    distinction. It must ramp from zero instead."""
    at_bar = ag.blend_weight({"eligible": True,
                              "adviser_long": {"hit": ag.THRESH["adviser_long_hit"]}})
    just_over = ag.blend_weight({"eligible": True,
                                 "adviser_long": {"hit": ag.THRESH["adviser_long_hit"] + 0.001}})
    assert at_bar == 0.0
    assert 0.0 < just_over < 0.01, just_over


def test_blend_weight_ramps_to_the_cap_and_stops():
    lo = ag.THRESH["adviser_long_hit"]
    hi = ag.BLEND_FULL_CONFIDENCE_HIT
    mid = ag.blend_weight({"eligible": True, "adviser_long": {"hit": (lo + hi) / 2}})
    assert abs(mid - ag.BLEND_MAX / 2) < 1e-9, mid
    for hit in (hi, 0.90, 1.0):
        assert ag.blend_weight({"eligible": True, "adviser_long": {"hit": hit}}) == ag.BLEND_MAX
    # monotone in the evidence
    seq = [ag.blend_weight({"eligible": True, "adviser_long": {"hit": h / 100}})
           for h in range(60, 101)]
    assert seq == sorted(seq)


def test_blend_max_keeps_the_tilt_a_minority_of_a_typical_position():
    """Sizing check against the live record (scripts/adviser_gate_fit.py):
    median |target_weight| is 0.202 and the largest independent adviser score
    observed is 0.958. The tilt has to stay a minority of a typical position or
    it is not a nudge -- at the old hand-set 0.25 the worst case was 142% of one."""
    median_position, worst_score = 0.2022, 0.958
    assert ag.BLEND_MAX * worst_score < median_position, "tilt can exceed a typical position"


# -- the tilt must be independent of what it is tilting ----------------------

def test_independent_score_ignores_a_pure_restatement_of_the_formula():
    """An adviser row whose conviction comes ENTIRELY from the formula driver is
    telling us what target_weight already says. Tilting on it would size a
    position up on the strength of its own conviction."""
    assert ag.independent_score(
        {"score": 0.8, "drivers": {"field": 0.0, "formula": 0.9, "scenarios": 0.0}}) == 0.0


def test_independent_score_passes_through_a_purely_independent_view():
    assert ag.independent_score(
        {"score": 0.8, "drivers": {"field": 0.9, "formula": 0.0, "scenarios": 0.0}}) == 0.8


def test_independent_score_apportions_a_mixed_view_and_keeps_the_haircuts():
    """W_FIELD*0.5 = 0.5 independent vs W_FORMULA*0.5 = 0.3 restatement -> the
    independent share is 0.5/0.8 = 0.625. Crucially this apportions the FINAL
    score, so every multiplicative haircut adviser.py applied (campaign,
    crowding, integrity, bubble, mood) is preserved rather than rebuilt away."""
    got = ag.independent_score(
        {"score": 0.16, "drivers": {"field": 0.5, "formula": 0.5, "scenarios": 0.0}})
    assert abs(got - 0.16 * 0.625) < 1e-9, got


def test_independent_score_is_safe_on_junk():
    assert ag.independent_score({}) == 0.0
    assert ag.independent_score({"score": 0.5}) == 0.0                      # no drivers
    assert ag.independent_score({"score": None, "drivers": {"field": 1}}) == 0.0
    # drivers that disagree in sign must not produce a share outside [0, 1]
    got = ag.independent_score(
        {"score": 1.0, "drivers": {"field": 1.0, "formula": -3.0, "scenarios": 0.0}})
    assert 0.0 <= got <= 1.0, got


def test_apply_adviser_gate_does_not_tilt_on_the_formulas_own_view():
    """End to end: the gate is on and confident, but the adviser's conviction is
    purely a restatement of the formula. Nothing should move."""
    settings = _enabled_settings({"trades": [
        {"symbol": "GLD", "score": 0.9,
         "drivers": {"field": 0.0, "formula": 1.0, "scenarios": 0.0}}]})
    out = ag.apply_adviser_gate([_decision("GLD", 0.40)], settings)
    assert out[0].target_weight == 0.40
    assert "adviser-gate" not in out[0].rationale


def test_apply_adviser_gate_is_inert_at_the_bar_even_when_eligible():
    tmp = tempfile.mkdtemp()
    settings = FakeSettings(tmp)
    with open(ag._gate_path(settings), "w") as fh:
        json.dump({"eligible": True,
                   "adviser_long": {"hit": ag.THRESH["adviser_long_hit"]}}, fh)
    with open(settings.brain.advice_path, "w") as fh:
        json.dump({"trades": [{"symbol": "GLD", "score": 1.0, "drivers": FIELD_ONLY}]}, fh)
    out = ag.apply_adviser_gate([_decision("GLD", 0.40)], settings)
    assert out[0].target_weight == 0.40


if __name__ == "__main__":
    for _name, _fn in sorted(list(globals().items())):
        if _name.startswith("test_") and callable(_fn):
            _fn()
    print("ok")
