#!/usr/bin/env python3
"""Restate stored price HISTORY in USD, so the FX fix does not read as a crash.

Converting live prices to USD (data/fx.py) left a one-day discontinuity in
data/brain.db: 1211.HK is 94.15 on 2026-08-02 and 12.19 on 2026-08-03. Nothing
happened -- the unit changed. But two consumers read that series as fact:

  * scorecard.score_due() graded it as a real -87% move. 72 of 170 outcomes
    (42%) were FX artifacts, and shorts were being credited with "wins" they
    never earned -- the system learning a lie about its own skill.
  * scorecard.day_moves() pulses the graph with yesterday->today price moves,
    so the same phantom crash was injected into the brain as a genuine shock.

This converts every pre-migration row for a non-USD symbol into USD, making the
series continuous, then clears the contaminated outcomes so they re-score
against honest numbers.

Today's rate is applied to historical rows. That is a real approximation -- HKD
is pegged so the error is negligible, CNY/KRW drift a few percent -- but a few
percent of drift is not comparable to an 87% phantom move, and leaving it is
not an option.

  python3 scripts/migrate_fx_history.py --dry-run
  python3 scripts/migrate_fx_history.py
"""
import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))

from ai_investing.config import Settings          # noqa: E402
from ai_investing.data import fx                  # noqa: E402

SENTINEL = ROOT / "data" / "fx_migration.json"
KEY = "price_history_usd"
CUTOVER = "2026-08-03"        # the day live prices started arriving in USD


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    try:
        done = KEY in json.loads(SENTINEL.read_text()).get("migrated", [])
    except (OSError, json.JSONDecodeError):
        done = False
    if done:
        print("price history already restated — nothing to do")
        return 0

    settings = Settings()
    if not fx.rates(settings, force=True):
        print("no FX rates — refusing to migrate blind")
        return 1

    db = ROOT / "data" / "brain.db"
    if not args.dry_run:
        shutil.copy2(db, str(db) + ".bak")
    con = sqlite3.connect(db)
    symbols = [r[0] for r in con.execute("SELECT DISTINCT symbol FROM price_history")]
    touched = rows = 0
    for sym in symbols:
        rate = fx.rate_for(sym, settings)
        if not rate or rate <= 0:
            continue
        n = list(con.execute(
            "SELECT COUNT(*) FROM price_history WHERE symbol=? AND date < ?",
            (sym, CUTOVER)))[0][0]
        if not n:
            continue
        touched += 1
        rows += n
        print(f"  {sym:12} {n:>4} rows  ÷{rate:.2f}")
        if not args.dry_run:
            con.execute("UPDATE price_history SET price = price / ? "
                        "WHERE symbol=? AND date < ?", (rate, sym, CUTOVER))
    bad = list(con.execute(
        "SELECT COUNT(*) FROM advice_outcomes WHERE ABS(realized_ret) > 0.5"))[0][0]
    print(f"\n  {touched} symbols, {rows} history rows restated")
    print(f"  {bad} contaminated outcomes to clear for re-scoring")
    if args.dry_run:
        print("  (dry run — nothing written)")
        return 0
    con.execute("DELETE FROM advice_outcomes WHERE ABS(realized_ret) > 0.5")
    con.commit()
    con.close()

    try:
        blob = json.loads(SENTINEL.read_text())
    except (OSError, json.JSONDecodeError):
        blob = {"migrated": []}
    blob.setdefault("migrated", []).append(KEY)
    blob["ts"] = datetime.now(timezone.utc).isoformat()
    SENTINEL.write_text(json.dumps(blob, indent=1))
    print(f"  done (backup at {db.name}.bak)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
