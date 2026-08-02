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
        wins.append({"start": start, "end": now.isoformat(), "hours": round(hours, 2)})
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
    print(f"[{datetime.now(timezone.utc):%Y-%m-%d %H:%M}] startup self-heal", flush=True)
    gap = age_h(DATA / "heartbeat.json")
    if gap is None:
        print("  no heartbeat — first run or fresh checkout", flush=True)
    else:
        print(f"  engine was down for ~{gap:.1f}h", flush=True)
        if gap >= 2.0:
            note_gap(gap)

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
