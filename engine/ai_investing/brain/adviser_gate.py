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
never an override -- to that cycle's decisions. Checked live 2026-08-15: not
eligible (adviser n=1,286/hit 0.532 on 11 days; needs >0.60 hit and 30+ days).
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
BLEND_WEIGHT = 0.25   # bounded tilt, never an override -- see apply_adviser_gate


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
    """Bounded nudge, never an override. Only runs at all once is_enabled()
    is true; until then every decision passes through completely unchanged --
    this is the whole difference between 'the adviser predicts well' staying
    advisory-only versus actually informing size."""
    if not is_enabled(settings):
        return decisions
    try:
        with open(settings.brain.advice_path) as fh:
            advice = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return decisions
    scores = {r["symbol"]: r["score"] for r in (advice.get("trades") or [])
             if isinstance(r.get("score"), (int, float))}
    scores.update({r["symbol"]: r["score"] for r in (advice.get("watch") or [])
                  if isinstance(r.get("score"), (int, float))})
    for d in decisions:
        adv_score = scores.get(d.asset.symbol)
        if adv_score is None:
            continue
        nudged = max(-1.0, min(1.0, d.target_weight + BLEND_WEIGHT * adv_score))
        if abs(nudged - d.target_weight) < 1e-9:
            continue
        d.rationale = (d.rationale + f" | adviser-gate {adv_score:+.2f}")[:200]
        d.target_weight = nudged
        d.direction = (SignalDirection.LONG if nudged > 1e-4 else
                      SignalDirection.SHORT if nudged < -1e-4 else SignalDirection.FLAT)
    return decisions
