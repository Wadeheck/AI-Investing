#!/usr/bin/env python3
"""The NN shadow book's record, beside the brain's, on identical rows.

Read-only. Touches nothing the engine reads and places no orders.

    python3 scripts/nn_shadow_report.py
    python3 scripts/nn_shadow_report.py --json

WHAT TO READ, and in this order:

  1. `n_independent`, never `graded`. Daily readings of a 5-day forward return
     overlap by 4/5, so `graded` overstates the evidence ~5x. The gap between
     the two IS the finding (AUDITING.md trap 2), which is why both print.
  2. `missed`. A book that never trades has no losses and looks disciplined.
     Counting the moves it stood aside for is what separates discipline from
     paralysis, and a P&L-only record cannot show it at all.
  3. The disagreement rows. `agree_with_brain` is not evidence about either
     model — two models fed the same features agreeing is the default. What
     carries information is where they SPLIT and who was right.

WHAT THIS CANNOT TELL YOU YET, stated here so nobody quotes it as though it
could: with a handful of independent observations, none of these figures can
separate either model from luck. This is a RECORD being accumulated, not a
verdict. The brain's own P&L took 26 days to reach "not demonstrably better
than chance" (§4.56); this starts from zero.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))


def _price_lookup(db_path: str):
    """settled price for (symbol, day) from the brain's own price history, so
    the grading uses exactly the tape the live system recorded."""
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return lambda s, d: None
    cache: dict = {}
    try:
        for sym, date, px in con.execute(
                "select symbol, date, price from price_history order by date"):
            cache.setdefault(sym, {})[str(date)[:10]] = float(px)
    except sqlite3.Error:
        pass
    finally:
        con.close()

    def look(symbol, day):
        series = cache.get(symbol) or {}
        if not series or not day:
            return None
        # first mark strictly after the decision day: the settle, not the entry
        later = sorted(d for d in series if d > day)
        return series[later[0]] if later else None
    return look


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    from ai_investing.config import Settings
    from ai_investing.learning import nn_shadow

    s = Settings()
    book = nn_shadow.NNShadowBook(s)
    if not book.available:
        out = {"available": False, "reason": book.reason}
        print(json.dumps(out, indent=1) if args.json else
              f"NN shadow inactive — {book.reason}")
        return 0

    rows = book.read_primaries()
    report = nn_shadow.grade(s, _price_lookup(s.brain.db_path))
    report["primary_rows"] = len(rows)
    report["book_equity"] = book.broker.portfolio().equity({})

    if args.json:
        print(json.dumps(report, indent=1))
        return 0

    g, ind = report["graded"], report["n_independent"]
    print(f"\nNN shadow book — {len(rows)} primary decisions, {g} graded\n")
    print(f"  positioned   captured {report['captured']:4d}   wrong {report['wrong']:4d}"
          f"   hit {report['hit_rate_when_positioned']}")
    print(f"  stood aside  avoided  {report['avoided']:4d}   MISSED {report['missed']:4d}"
          f"   (moves >{nn_shadow.OPPORTUNITY_PCT}% it did not take)")
    print(f"\n  vs the brain, same rows:")
    print(f"    agreed              {report['agree_with_brain']:4d}")
    print(f"    disagreed           {report['disagree']:4d}")
    print(f"      NN right          {report['nn_right_brain_wrong']:4d}")
    print(f"      brain right       {report['brain_right_nn_wrong']:4d}")
    print(f"\n  pending (not yet matured)  {report['pending']}")
    print(f"\n  SAMPLE: {g} graded rows are ~{ind} INDEPENDENT observations "
          f"(5-day windows overlap 4/5).")
    if ind < 20:
        print("  At this n nothing here separates either model from luck. It is a\n"
              "  record being accumulated, not a verdict.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
