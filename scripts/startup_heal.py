#!/usr/bin/env python3
"""Self-heal on startup: recover cleanly from any shutdown, planned or not.

Cron does not catch up on jobs missed while a machine was off, and crypto keeps
trading while the engine sleeps. So on every start we:

  1. measure the gap (how long the engine was down, from the last heartbeat)
  2. refresh anything now stale — market numbers, crypto signals/positioning,
     RSS news — so the first cycle after waking decides on CURRENT data, never
     on a snapshot from before the gap
  3. record the gap in each book's journal, so the forward record shows
     honestly where the system was blind (stops that could not fire, bear
     signals that could not act)
  4. leave the books untouched otherwise — they persist themselves; the engine
     re-evaluates every holding on its first cycle, hard stops first

Safe to run repeatedly. Never trades, never deletes.
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
PY = str(ROOT / ".venv" / "bin" / "python")


def age_h(p: Path):
    try:
        return (time.time() - p.stat().st_mtime) / 3600.0
    except OSError:
        return None


def run(script: str, why: str) -> None:
    print(f"  healing: {why} -> {script}", flush=True)
    try:
        subprocess.run([PY, str(ROOT / "scripts" / script)], timeout=900,
                       stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    except Exception as exc:
        print(f"    FAILED: {type(exc).__name__}: {str(exc)[:80]}", flush=True)


def note_gap(hours: float) -> None:
    """Record the blind window: journals for the audit trail, and a machine-
    readable window the learning spine uses to REFUSE to learn from trades
    whose exits were delayed by the outage (a late stop is not a bad signal)."""
    now = datetime.now(timezone.utc)
    start = (now - timedelta(hours=hours)).isoformat()
    try:
        wins = []
        gp = DATA / "learning_gaps.json"
        if gp.exists():
            wins = json.loads(gp.read_text())
        # EXTEND the open window rather than appending a new one. This runs on
        # every start attempt, and heartbeat.json is not touched until the engine
        # actually trades — so four failed starts wrote four near-identical
        # windows for one outage. Harmless to the spine, but it inflates the
        # outage count and buries the real events in the audit trail.
        same = (wins and wins[-1].get("start", "")[:16] == start[:16])
        rec = {"start": start, "end": now.isoformat(), "hours": round(hours, 2)}
        if same:
            wins[-1] = rec
        else:
            wins.append(rec)
        gp.write_text(json.dumps(wins[-200:], indent=1))
    except (OSError, json.JSONDecodeError):
        pass
    entry = {"ts": datetime.now(timezone.utc).isoformat(), "event": "gap",
             "down_hours": round(hours, 2),
             "note": ("engine was down; stops and bear exits could not fire in this "
                      "window. Positions are re-evaluated against current prices on "
                      "the first cycle after this entry.")}
    for j in ("crypto_journal.jsonl",):
        try:
            with open(DATA / j, "a") as fh:
                fh.write(json.dumps(entry) + "\n")
        except OSError:
            pass


def main() -> int:
    defer = "--defer-refresh" in sys.argv
    print(f"[{datetime.now(timezone.utc):%Y-%m-%d %H:%M}] startup self-heal", flush=True)
    gap = age_h(DATA / "heartbeat.json")
    if gap is None:
        print("  no heartbeat — first run or fresh checkout", flush=True)
    else:
        print(f"  engine was down for ~{gap:.1f}h", flush=True)
        if gap >= 2.0:
            note_gap(gap)

    # Only step 1 — journalling the gap — genuinely has to finish before the
    # engine trades, because the spine needs the window on disk before any exit
    # settles. The refreshes do not: the first cycle can read slightly stale
    # numbers, and the timers refresh them regardless.
    #
    # Blocking on them was actively harmful. As ExecStartPre these calls can run
    # for minutes on a cold network, systemd's TimeoutStartSec is 90s, and it
    # killed the start four times in a row — turning "some data is stale" into
    # eight extra minutes of NO ENGINE AT ALL. The safety net must not be able to
    # outweigh the thing it protects.
    if defer:
        try:
            subprocess.Popen(
                [PY, str(Path(__file__).resolve())],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True)
            print("  refresh handed off to a detached process; engine may start now",
                  flush=True)
        except Exception as exc:
            print(f"  could not detach refresh ({type(exc).__name__}) — "
                  f"timers will catch it", flush=True)
        return 0

    # crypto first: it trades 24/7, so it goes stalest fastest
    a = age_h(DATA / "crypto_signals.json")
    if a is None or a > 1.5:
        run("refresh_crypto_live.py", f"crypto signals {a and round(a,1)}h old")
    a = age_h(DATA / "crypto_history" / "fear_greed_daily.json")
    if a is None or a > 24:
        run("refresh_market_data.py", f"market numbers {a and round(a,1)}h old")
    a = age_h(DATA / "news_archive_live.jsonl")
    if a is None or a > 4:
        run("accumulate_once.py", f"news {a and round(a,1)}h old")

    # report the healed state
    try:
        subprocess.run([PY, str(ROOT / "scripts" / "daily_status.py")], timeout=120)
    except Exception:
        pass
    print("self-heal complete — engine may start", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
