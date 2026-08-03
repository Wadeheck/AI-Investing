#!/usr/bin/env python3
"""Daily snapshot of the irreplaceable state.

Most of data/ can be rebuilt: news archives re-download, market numbers
refresh, the graph is in git. Four things cannot:

  * the books      -- positions, cost basis, cash. The forward paper record the
                      whole learning design is graded against.
  * brain.db       -- every article ever digested, and the dedup memory that
                      stops the tagger re-reading (and re-paying for) the world.
  * the ledgers    -- expectations.jsonl and the journals: the audit trail of
                      what was claimed and what happened.
  * the learned    -- params, learning gaps, FX migration sentinel.

A corrupted write, a bad migration, or a disk fault takes those permanently.
Atomic writes prevent tearing; they do not protect against a wrong value being
written correctly. Only a snapshot does.

Snapshots are compressed, dated, and pruned to KEEP days. They stay on the same
disk, which protects against everything except losing the disk -- copy the
newest tarball off the box periodically if that matters to you.

  python3 scripts/backup.py            # snapshot + prune
  python3 scripts/backup.py --list     # what exists
"""
import argparse
import os
import sys
import tarfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DEST = DATA / "backups"
KEEP_DAYS = 21

# Globs relative to data/. Small, high-value, irreplaceable.
PATTERNS = [
    "paper_state.json", "invest_state.json", "crypto_state.json",
    "event_state.json", "shadow.json", "state.json",
    "brain.db", "params.json", "expectations.jsonl",
    "crypto_journal.jsonl", "event_journal.jsonl", "journal.jsonl",
    "learning_gaps.json", "fx_migration.json", "fx_rates.json",
    "breaker.json", "heartbeat.json", "user_views.json",
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    DEST.mkdir(parents=True, exist_ok=True)
    if args.list:
        snaps = sorted(DEST.glob("state-*.tar.gz"))
        for s in snaps:
            print(f"  {s.name}  {s.stat().st_size / 1024:.0f} KB  "
                  f"{datetime.fromtimestamp(s.stat().st_mtime):%Y-%m-%d %H:%M}")
        print(f"({len(snaps)} snapshots)")
        return 0

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = DEST / f"state-{stamp}.tar.gz"
    included = 0
    # write to a temp name and rename, so an interrupted backup never leaves a
    # truncated archive wearing today's date and looking valid
    tmp = out.with_suffix(".tmp")
    with tarfile.open(tmp, "w:gz") as tar:
        for pat in PATTERNS:
            for p in DATA.glob(pat):
                if p.is_file():
                    tar.add(p, arcname=p.name)
                    included += 1
    os.replace(tmp, out)
    print(f"snapshot {out.name}: {included} files, {out.stat().st_size / 1024:.0f} KB")

    cutoff = time.time() - KEEP_DAYS * 86400
    pruned = 0
    for s in DEST.glob("state-*.tar.gz"):
        if s.stat().st_mtime < cutoff:
            s.unlink()
            pruned += 1
    if pruned:
        print(f"pruned {pruned} older than {KEEP_DAYS} days")
    return 0


if __name__ == "__main__":
    sys.exit(main())
