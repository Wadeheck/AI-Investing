"""The counting unit: one graded observation per (issue-day, symbol).

The defect these pin, measured on the production record 2026-08-21:

    advice_outcomes rows (hit is not null)     38,900
    distinct (symbol, issue-day)                  598
    inflation factor                             65.1x

`advice_log` is written every cycle (~126/day at a ~10-minute cadence) and
`score_due()` grades every row of it, so one standing view was frozen and
counted ~126 times against the same forward return out of the same 5-day
window. Nothing downstream could see it: two scorecard reviews reached opposite
conclusions about the short side, every t-statistic was ~sqrt(65)=8x too large,
and `adviser_gate.THRESH["min_n"]` of 500 rows was a bar of 7.7 real
observations.

Two invariants, and the second is the one that bit hardest in production:
  1. statistics count observations, never rows;
  2. `update_reliability`'s EMA steps once per observation — at 65 steps a day
     with alpha=0.12 it retained 0.88^65 = 0.00026 of yesterday, which made it a
     same-day step function, and left 46% of 122 live symbols pinned at a bound.

Nothing is deleted: every row is still written and still auditable. Only the
unit of account is new.
"""
import json
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_investing.brain.scorecard import R_MAX, R_MIN, Scorecard


class _Cfg:
    def __init__(self, tmp):
        self.state_path = os.path.join(tmp, "state.json")


def _issued(days_ago: int, hour: int = 0) -> str:
    """A UTC timestamp `days_ago` old. Hours stay under 16 so +8h (SGT) keeps
    every row of a synthetic 'day' on one calendar day."""
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)
            ).replace(hour=hour, minute=0, second=0, microsecond=0).isoformat()


def _seed(tmp, advice_lists, prices):
    """advice_lists: [(ts, [{symbol,direction,...}, ...]), ...]"""
    con = sqlite3.connect(os.path.join(tmp, "brain.db"))
    con.execute("CREATE TABLE IF NOT EXISTS advice_log (ts TEXT, advice TEXT)")
    con.executemany("INSERT INTO advice_log(ts,advice) VALUES(?,?)",
                    [(ts, json.dumps({"trades": tr})) for ts, tr in advice_lists])
    con.execute("CREATE TABLE IF NOT EXISTS price_history ("
                "date TEXT NOT NULL, symbol TEXT NOT NULL, price REAL NOT NULL,"
                " PRIMARY KEY(date,symbol))")
    con.executemany("INSERT OR REPLACE INTO price_history(date,symbol,price) VALUES(?,?,?)",
                    prices)
    con.commit()
    con.close()


def _price_rows(symbol_prices, days_back=9):
    """A flat daily series per symbol, then a final price, so a call issued
    `days_back` days ago has both an entry and a latest snapshot."""
    rows = []
    for sym, (p0, p1) in symbol_prices.items():
        for i in range(days_back, 0, -1):
            d = (datetime.now(timezone.utc) - timedelta(days=i)).date().isoformat()
            rows.append((d, sym, p0))
        rows.append((datetime.now(timezone.utc).date().isoformat(), sym, p1))
    return rows


def test_re_issuing_one_view_all_day_is_one_observation():
    """126 advice lists a day, one symbol, one view: 126 rows, one observation."""
    tmp = tempfile.mkdtemp()
    ts_list = [(_issued(8, hour=h % 16),
                [{"symbol": "NVDA", "direction": "long", "market": "US"}])
               for h in range(126)]
    _seed(tmp, ts_list, _price_rows({"NVDA": (100.0, 110.0), "SPY": (100.0, 100.0)}))

    sc = Scorecard(_Cfg(tmp))
    out = sc.score_due()

    rows = sc.conn.execute("SELECT COUNT(*), SUM(is_primary) FROM advice_outcomes").fetchone()
    assert rows[0] == 126, "every row is still written — the ledger is not pruned"
    assert rows[1] == 1, "exactly one of them is the counted observation"
    assert sum(1 for o in out if o["primary"]) == 1
    sc.close()


def test_the_primary_row_is_the_first_call_of_the_day():
    tmp = tempfile.mkdtemp()
    _seed(tmp, [(_issued(8, hour=2), [{"symbol": "GLD", "direction": "long", "market": "US"}]),
                (_issued(8, hour=9), [{"symbol": "GLD", "direction": "avoid", "market": "US"}])],
          _price_rows({"GLD": (100.0, 110.0), "SPY": (100.0, 100.0)}))
    sc = Scorecard(_Cfg(tmp))
    sc.score_due()
    row = sc.conn.execute(
        "SELECT direction FROM advice_outcomes WHERE is_primary=1").fetchall()
    assert row == [("long",)], "the earliest actionable call of the day is the graded one"
    sc.close()


def test_two_different_days_are_two_observations():
    tmp = tempfile.mkdtemp()
    _seed(tmp, [(_issued(9, hour=1), [{"symbol": "AMD", "direction": "long", "market": "US"}]),
                (_issued(8, hour=1), [{"symbol": "AMD", "direction": "long", "market": "US"}])],
          _price_rows({"AMD": (100.0, 110.0), "SPY": (100.0, 100.0)}))
    sc = Scorecard(_Cfg(tmp))
    sc.score_due()
    n = sc.conn.execute("SELECT SUM(is_primary) FROM advice_outcomes").fetchone()[0]
    assert n == 2, "the unit is per DAY, not one observation per symbol forever"
    sc.close()


def test_reliability_steps_once_per_day_not_once_per_row():
    """The estimator defect. 126 misses in a day used to take 126 EMA steps and
    slam r to the floor; it must take exactly one step of alpha."""
    tmp = tempfile.mkdtemp()
    ts_list = [(_issued(8, hour=h % 16),
                [{"symbol": "TSLA", "direction": "long", "market": "US"}])
               for h in range(126)]
    # TSLA flat while SPY rises => excess negative => a long MISS, 126 times over
    _seed(tmp, ts_list, _price_rows({"TSLA": (100.0, 100.0), "SPY": (100.0, 120.0)}))

    sc = Scorecard(_Cfg(tmp))
    out = sc.score_due()
    assert any(o["hit"] == 0 for o in out), "fixture must actually produce misses"
    sc.update_reliability(out)
    sc.close()

    r = json.load(open(os.path.join(tmp, "reliability.json")))["TSLA"]
    # one step from the 1.0 default toward R_MIN, alpha=0.12
    assert abs(r["r"] - (1.0 + 0.12 * (R_MIN - 1.0))) < 1e-6, \
        f"expected a single EMA step, got r={r['r']}"
    assert r["r"] > R_MIN + 0.3, "a single bad day must not pin trust to the floor"


def test_backfill_labels_a_database_written_before_the_column_existed():
    """The 42,674 production rows. They are labelled in place, never deleted."""
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "brain.db")
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE advice_outcomes ("
                "advice_id INTEGER NOT NULL, symbol TEXT NOT NULL, direction TEXT NOT NULL,"
                " ts_issued TEXT NOT NULL, horizon_days INTEGER NOT NULL,"
                " realized_ret REAL, hit INTEGER, scored_at TEXT NOT NULL,"
                " PRIMARY KEY(advice_id,symbol))")
    rows = [(i, "MP", "avoid", f"2026-08-01T{i % 16:02d}:00:00", 5, 0.01, 1, "x")
            for i in range(40)]
    rows += [(100 + i, "MP", "avoid", f"2026-08-02T{i % 16:02d}:00:00", 5, 0.01, 1, "x")
             for i in range(40)]
    con.executemany("INSERT INTO advice_outcomes VALUES(?,?,?,?,?,?,?,?)", rows)
    con.commit()
    con.close()

    sc = Scorecard(_Cfg(tmp))
    total, primary = sc.conn.execute(
        "SELECT COUNT(*), SUM(is_primary) FROM advice_outcomes").fetchone()
    assert total == 80, "no row is deleted by the migration"
    assert primary == 2, "80 rows over two days is two observations"
    # and it is idempotent — reopening must not relabel or double-count
    sc.close()
    sc2 = Scorecard(_Cfg(tmp))
    assert sc2.conn.execute(
        "SELECT SUM(is_primary) FROM advice_outcomes").fetchone()[0] == 2
    sc2.close()


def test_track_record_reports_observations_not_rows():
    tmp = tempfile.mkdtemp()
    ts_list = [(_issued(8, hour=h % 16),
                [{"symbol": "NVDA", "direction": "long", "market": "US"}])
               for h in range(60)]
    _seed(tmp, ts_list, _price_rows({"NVDA": (100.0, 130.0), "SPY": (100.0, 100.0)}))
    sc = Scorecard(_Cfg(tmp))
    sc.score_due()
    rec = sc.track_record(days=30)
    sc.close()
    ns = [v["n"] for v in rec.values() if isinstance(v, dict) and "n" in v]
    assert ns and max(ns) == 1, f"track_record must count 1, not 60 — got {rec}"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\nAll {len(tests)} counting-unit tests passed.")
