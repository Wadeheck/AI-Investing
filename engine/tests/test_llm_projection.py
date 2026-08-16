"""The nightly false alarm on the LLM budget row, and the fix.

The digest crons spend most of the day's tokens just after 00:00 UTC. Any
estimator that extrapolates a window containing that burst manufactures an
emergency. This was fixed once (§4.20, elapsed-rate -> trailing-window rate) and
the trailing window still contained the burst for the ~3 hours after it ran, so
it kept firing every night, just with smaller numbers.

The curves below are REAL, measured from data/llm_usage.json on the ProDesk.
2026-08-15 finished the day near 48% of a 5M cap, so every reading above 100%
on that row is by definition false.
"""
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import daily_status as ds  # noqa: E402

CAP = 5_000_000

# ep-...vgxfw, hours 00..13 UTC
DAY_0815 = [157519, 496084, 138036, 126409, 155478, 177133, 129732, 137609,
            141640, 131012, 121185, 127595, 123510, 160816]
# 2026-08-16, the morning the row read 146%
DAY_0816 = [164509, 429554, 85097]
# quiet, then a burn that climbs and never stops
RUNAWAY = [130000, 140000, 135000, 300000, 450000, 600000, 700000, 800000]

ALERTING = object()   # sentinel: a basis that main() allows to page


def project_at(curve, hour):
    """Run the estimator as it would run a quarter of the way into `hour`."""
    ds.NOW = datetime(2026, 8, 16, hour, 15, tzinfo=timezone.utc)
    usage = {"by_model": {"m": sum(curve[:hour + 1])},
             "by_hour": {"m": {str(h): v for h, v in enumerate(curve[:hour + 1])}}}
    return ds._project_eod(usage, CAP)


def would_page(curve, hour):
    """Mirrors main()'s gate: only a basis measured from real complete hours
    is allowed to raise ACTION NEEDED."""
    proj, basis = project_at(curve, hour)
    if basis in ("elapsed-rate", "too few complete hours"):
        return False
    return proj >= 100


def test_a_normal_day_never_pages():
    """2026-08-15 finished near 48%. Every hour of it must stay quiet — this is
    the whole point, and the shipped estimator failed it at 00, 01, 02, 03 and
    04 UTC, i.e. five false pages every single night."""
    fired = [h for h in range(len(DAY_0815)) if would_page(DAY_0815, h)]
    assert not fired, f"false alarm at hours {fired} on a day that ended at ~48%"


def test_the_146_percent_morning_reads_sanely():
    """The specific reading that started this: 02:15 UTC on 2026-08-16."""
    proj, basis = project_at(DAY_0816, 2)
    assert "burst hour dropped" in basis, basis
    assert proj < 100, f"still projecting {proj:.0f}%"
    # and it should be in the neighbourhood of where the day actually lands,
    # not merely under the alerting line
    assert 60 <= proj <= 95, proj


def test_the_burst_hour_is_what_gets_dropped():
    """Not just 'a smaller number' — the estimator must specifically discount
    the digest hour. Hour 01 on 08-15 is 3.6x the surrounding hours."""
    ds.NOW = datetime(2026, 8, 16, 4, 15, tzinfo=timezone.utc)
    with_burst = {"by_model": {"m": sum(DAY_0815[:5])},
                  "by_hour": {"m": {str(h): v for h, v in enumerate(DAY_0815[:5])}}}
    flat = list(DAY_0815[:5])
    flat[1] = 140000                      # same day, minus the digest spike
    without = {"by_model": {"m": sum(flat)},
               "by_hour": {"m": {str(h): v for h, v in enumerate(flat)}}}
    a, _ = ds._project_eod(with_burst, CAP)
    b, _ = ds._project_eod(without, CAP)
    # the projections must agree closely: the burst is excluded from the RATE,
    # and only its already-spent tokens (a fixed amount) separate them
    assert abs(a - b) < 8, f"burst still moving the projection: {a:.0f}% vs {b:.0f}%"


def test_a_real_runaway_still_pages():
    """The check must not be defanged. A burn that keeps climbing has to fire —
    later than the old estimator did, which is the accepted cost of not crying
    wolf nightly, and acceptable because the REAL protection is
    _over_free_budget rotating the endpoint away at 90% actual use."""
    fired = [h for h in range(len(RUNAWAY)) if would_page(RUNAWAY, h)]
    assert fired, "a genuine runaway never raised the alarm"
    assert min(fired) <= 5, f"fired too late, first at hour {min(fired)}"
    # and having fired, it must stay fired rather than flickering
    assert fired == list(range(min(fired), len(RUNAWAY))), fired


def test_the_early_hours_report_but_never_page():
    """Before two complete hours exist there is nothing to measure a baseline
    against. Report a number so it can be traced; never wake anyone with it."""
    for hour in (0, 1):
        _proj, basis = project_at(DAY_0815, hour)
        assert basis == "too few complete hours", basis
        assert not would_page(DAY_0815, hour)


if __name__ == "__main__":
    for _name, _fn in sorted(list(globals().items())):
        if _name.startswith("test_") and callable(_fn):
            _fn()
    print("ok")
