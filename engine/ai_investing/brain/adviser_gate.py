"""Automatic evidence gate: decides -- without a human in the loop -- whether the
adviser's (proven, on large samples) long-side calls are trustworthy enough to
nudge real position sizing. This is exactly the criterion
docs/status/STATE_OF_THE_SYSTEM.md §4B already named for the open item "the
adviser predicts well; the books do not trade it":

    adviser long-side hit-rate   > 0.60   (n >= 500)
    formula short/avoid hit-rate < 0.35   (n >= 500)
    both measured over >= 30 distinct calendar days

The point of this module is that nobody has to notice the cue fired and flip a
switch by hand. `scripts/adviser_gate_check.py` (systemd timer, daily) calls
evaluate() and persists the verdict; runner.py reads the cached verdict once per
cycle (cheap file read, no live DB query in the hot path) via is_enabled() and,
only when true, lets apply_adviser_gate() apply a small, BOUNDED nudge --
never an override -- to that cycle's decisions. Checked live 2026-08-15 against
production copies of journal.db/brain.db: not eligible on either side --
adviser n=1,361 / hit 0.558 over 10 days (needs >0.60 and 30+ days), formula
short/avoid n=359 / hit 0.415 over 11 days (needs <0.35 and 30+ days).
Nothing here is a one-off manual judgment call; re-running evaluate() is what
changes the answer, the same way the walk-forward Deflated-Sharpe gate already
decides for the formula's own weights without asking anyone.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone

from ai_investing.brain.scorecard import DEADBAND, HORIZON_DAYS, benchmark_for, verdict
from ai_investing.models import SignalDirection

THRESH = {
    "adviser_long_hit": 0.60,
    "formula_short_hit": 0.35,
    "min_n": 500,
    "min_days": 30,
}
# -- how big may the tilt be? ------------------------------------------------
# BLEND_WEIGHT used to be a hand-set 0.25 with nothing behind it. Two things
# measured against the production record on 2026-08-15 replaced it:
#
# 1. IT CANNOT BE FITTED. Everything the system has recorded -- journal
#    decisions, brain advice_log, brain price_history -- starts 2026-07-26.
#    Joining formula target_weight to adviser score to a realized 5-day excess
#    return yields n=251 over 11 distinct days, one regime, overlapping
#    horizons. In that window EVERY term anti-predicted (corr with excess ret:
#    target_weight -0.204, adviser score -0.218), so the P&L-optimal beta is 0.00
#    on 8/8 days and the curve falls monotonically. That is a fact about three
#    adverse weeks, NOT a structural result -- which is exactly why it must not
#    be fitted to. Re-run scripts/adviser_gate_fit.py once there are enough
#    distinct regimes to say anything; today there are not.
# 2. 0.25 WAS TOO BIG TO BE A "NUDGE". Median |target_weight| in the live record
#    is 0.202. At beta=0.25 the largest observed tilt was 0.151 -- 75% of a
#    typical position. A term that can move a position by three quarters of its
#    size is not a nudge. At BLEND_MAX below, the median tilt is ~8% of a typical
#    position and the largest observed is 47%.
BLEND_MAX = 0.10
# ...and the tilt RAMPS from zero at the eligibility bar rather than switching on
# at full size. Without this the day the gate flips eligible, every position in
# the book jumps by the full blend at once -- a discontinuity nothing in the
# evidence justifies, since a 0.601 hit-rate is not meaningfully better than the
# 0.600 that failed. Full size is only reached at a 0.75 hit-rate, which on 5-day
# excess returns would be exceptional.
BLEND_FULL_CONFIDENCE_HIT = 0.75


def blend_weight(gate: dict) -> float:
    """The tilt coefficient implied by the evidence, not a constant. Zero at the
    eligibility threshold, BLEND_MAX at BLEND_FULL_CONFIDENCE_HIT, linear
    between. Anything not eligible gets 0.0."""
    if not gate.get("eligible"):
        return 0.0
    hit = (gate.get("adviser_long") or {}).get("hit")
    if not isinstance(hit, (int, float)):
        return 0.0
    lo = THRESH["adviser_long_hit"]
    span = BLEND_FULL_CONFIDENCE_HIT - lo
    if span <= 0:
        return BLEND_MAX
    return BLEND_MAX * max(0.0, min(1.0, (hit - lo) / span))


def independent_score(row: dict) -> float:
    """The part of an adviser score that is NOT a restatement of the formula
    conviction the decision is already made of.

    adviser.py composes score as W_FIELD*field + W_FORMULA*formula +
    W_SCENARIO*scenarios + ..., so `score` carries the formula's own view at
    W_FORMULA=0.6. Measured on the production record: the adviser score's formula
    driver correlates +0.848 with the very target_weight it would be tilting,
    while its field+scenarios part correlates only +0.260. Blending the raw score
    therefore mostly AMPLIFIES the formula rather than adding a second opinion --
    it makes a confident position more confident on the strength of its own
    conviction, which is the one thing a "second opinion" must not do.

    So the tilt rides the independent part only. `drivers` holds the components
    pre-haircut, while `score` is post-haircut (campaign, crowding, integrity,
    bubble, mood), so rather than rebuilding the score from drivers -- which
    would silently discard every haircut -- apportion the FINAL score by the
    independent share of its own drivers.

    NOTE the tension, deliberately left visible: the gate's eligibility evidence
    measures the adviser's hit-rate on its FULL score, not on this residual. Using
    the residual is the conservative reading (never double-count), but it is a
    reading, and it is the piece of this design most worth arguing with.
    """
    dr = row.get("drivers") or {}
    score = row.get("score")
    if not isinstance(score, (int, float)) or not dr:
        return 0.0
    try:
        from ai_investing.brain.adviser import W_FIELD, W_FORMULA, W_SCENARIO
    except ImportError:                     # keep the gate usable standalone
        W_FIELD, W_FORMULA, W_SCENARIO = 1.0, 0.6, 0.5
    ind = W_FIELD * float(dr.get("field") or 0.0) + W_SCENARIO * float(dr.get("scenarios") or 0.0)
    fml = W_FORMULA * float(dr.get("formula") or 0.0)
    total = ind + fml
    if abs(total) < 1e-9:
        return 0.0
    share = max(0.0, min(1.0, ind / total))   # clamped: the drivers can disagree in sign
    return score * share


def _gate_path(settings) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(settings.state_path)), "adviser_gate.json")


def _adviser_long_stats(brain_db_path: str) -> dict:
    try:
        con = sqlite3.connect(brain_db_path)
        cur = con.cursor()
        cur.execute(
            "select count(*), avg(hit), count(distinct date(ts_issued)) from advice_outcomes "
            "where direction='long' and is_conviction=1 and hit is not null")
        n, hit, days = cur.fetchone()
        con.close()
    except sqlite3.OperationalError:
        return {"n": 0, "hit": 0.0, "days": 0}
    return {"n": n or 0, "hit": hit or 0.0, "days": days or 0}


def _formula_short_stats(journal_db_path: str, brain_db_path: str,
                         horizon_days: int = HORIZON_DAYS, deadband: float = DEADBAND) -> dict:
    """Grade the formula-engine's own 'short' decisions the same way the
    adviser's 'avoid' calls are graded: excess return vs. benchmark, not an
    absolute-fall claim. Stocks can't be shorted on either paper venue, so a
    formula 'short' functions exactly like an adviser 'avoid'. One graded call
    per (symbol, calendar day): the LAST decision issued that day."""
    try:
        jcon = sqlite3.connect(journal_db_path)
        jcur = jcon.cursor()
        jcur.execute("""
            select d.symbol, date(d.ts) as day
            from decisions d
            join (select symbol, date(ts) as day, max(ts) as mts
                  from decisions group by symbol, date(ts)) latest
              on d.symbol = latest.symbol and date(d.ts) = latest.day and d.ts = latest.mts
            where d.direction = 'short'
        """)
        rows = jcur.fetchall()
        jcon.close()
    except sqlite3.OperationalError:
        return {"n": 0, "hit": 0.0, "days": 0}
    if not rows:
        return {"n": 0, "hit": 0.0, "days": 0}

    bcon = sqlite3.connect(brain_db_path)
    bcur = bcon.cursor()
    cache: dict[str, dict[str, float]] = {}

    def _price(sym: str, day: str):
        if sym not in cache:
            bcur.execute("select date, price from price_history where symbol=?", (sym,))
            cache[sym] = dict(bcur.fetchall())
        series = cache[sym]
        if day in series:
            return series[day]
        later = sorted(d for d in series if d >= day)
        return series[later[0]] if later else None

    hits: list[int] = []
    days_seen: set[str] = set()
    for sym, day in rows:
        entry = _price(sym, day)
        exit_day = (datetime.fromisoformat(day) + timedelta(days=horizon_days)).date().isoformat()
        exitp = _price(sym, exit_day)
        if not entry or not exitp or entry <= 0:
            continue
        ret = exitp / entry - 1
        excess = None
        bench = benchmark_for(sym)
        if bench:
            bentry, bexit = _price(bench, day), _price(bench, exit_day)
            if bentry and bexit and bentry > 0:
                excess = ret - (bexit / bentry - 1)
        # NOT verdict("short", ...) -- that branch grades the literal "will FALL"
        # claim on absolute return, ignoring excess entirely. Nothing here can
        # short stocks, so a formula "short" IS an "avoid" claim ("will lag the
        # market"), and must be graded the same way: excess vs. benchmark. Passing
        # the literal string "short" through was a real bug, caught 2026-08-15
        # because the first test suite for this used a flat benchmark in every
        # fixture, where absolute return and excess return are numerically
        # identical -- the two methodologies could never disagree, so the bug
        # was invisible to it. See test_formula_short_stats_diverges_from_absolute_fall_rule.
        v = verdict("avoid", ret, excess)
        if v is not None:
            hits.append(v)
            days_seen.add(day)
    bcon.close()
    if not hits:
        return {"n": 0, "hit": 0.0, "days": 0}
    return {"n": len(hits), "hit": sum(hits) / len(hits), "days": len(days_seen)}


def evaluate(settings) -> dict:
    """Measure both sides and persist the verdict. Safe to call repeatedly
    (e.g. from a daily timer); never trades, only writes the gate file."""
    adv = _adviser_long_stats(settings.brain.db_path)
    fml = _formula_short_stats(settings.db_path, settings.brain.db_path)
    eligible = (
        adv["n"] >= THRESH["min_n"] and adv["days"] >= THRESH["min_days"]
        and adv["hit"] > THRESH["adviser_long_hit"]
        and fml["n"] >= THRESH["min_n"] and fml["days"] >= THRESH["min_days"]
        and fml["hit"] < THRESH["formula_short_hit"]
    )
    result = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "eligible": eligible,
        "adviser_long": adv,
        "formula_short": fml,
        "threshold": THRESH,
    }
    path = _gate_path(settings)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            json.dump(result, fh, indent=1)
    except OSError:
        pass
    return result


def is_enabled(settings) -> bool:
    """Cheap read for the hot path. Never recomputes -- trusts the last
    evaluate() run. Missing/unreadable file = not eligible, fail closed."""
    try:
        with open(_gate_path(settings)) as fh:
            return bool(json.load(fh).get("eligible", False))
    except (OSError, json.JSONDecodeError):
        return False


def apply_adviser_gate(decisions: list, settings) -> list:
    """Bounded nudge, never an override. Does nothing at all until the gate is
    eligible AND the adviser's measured hit-rate is above the bar it had to clear
    (blend_weight); until then every decision passes through completely
    unchanged -- this is the whole difference between 'the adviser predicts well'
    staying advisory-only versus actually informing size.

    Four bounds, each of which the earlier version of this function lacked:
      - a flat decision stays flat (never originates a position)
      - the tilt rides the adviser's INDEPENDENT view, not its restatement of the
        formula conviction already in target_weight (independent_score)
      - the score is clamped before scaling, so beta means what it says
      - the sign the formula chose is never reversed, only scaled or zeroed
    """
    try:
        with open(_gate_path(settings)) as fh:
            gate = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return decisions
    beta = blend_weight(gate)          # 0.0 unless eligible AND above the bar
    if beta <= 0.0:
        return decisions
    try:
        with open(settings.brain.advice_path) as fh:
            advice = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return decisions
    scores = {}
    for bucket in ("trades", "watch"):
        for r in (advice.get(bucket) or []):
            if isinstance(r.get("symbol"), str):
                scores[r["symbol"]] = independent_score(r)
    for d in decisions:
        adv_score = scores.get(d.asset.symbol)
        if adv_score is None:
            continue
        # A NUDGE, not an originator. The formula deciding "no position" is itself
        # a decision, and the evidence measured by this gate is only that the
        # adviser ranks better than the formula's SHORT/AVOID calls -- nothing
        # here measures whether the adviser can pick entries the formula declined
        # entirely. Sizing those from scratch would be a different claim on a
        # different piece of evidence, so a flat decision stays flat.
        if abs(d.target_weight) <= 1e-9:
            continue
        # adviser scores are an unbounded weighted sum (brain/adviser.py: W_FIELD
        # 1.0 + W_FORMULA 0.6 + W_SCENARIO 0.5 + ...), NOT a [-1,1] conviction.
        # Clamping first is what makes beta mean what it says: at most a `beta`
        # shift in target weight, rather than "whatever the score happened to be,
        # then clipped at the book limit."
        tilt = beta * max(-1.0, min(1.0, adv_score))
        # never flip the sign the formula chose, and never grow a position by more
        # than the tilt: this can scale conviction, not reverse it.
        nudged = max(-1.0, min(1.0, d.target_weight + tilt))
        if (nudged >= 0) != (d.target_weight >= 0):
            nudged = 0.0
        if abs(nudged - d.target_weight) < 1e-9:
            continue
        d.rationale = (d.rationale + f" | adviser-gate {adv_score:+.2f}")[:200]
        d.target_weight = nudged
        d.direction = (SignalDirection.LONG if nudged > 1e-4 else
                      SignalDirection.SHORT if nudged < -1e-4 else SignalDirection.FLAT)
    return decisions
