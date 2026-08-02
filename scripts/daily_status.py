#!/usr/bin/env python3
"""Daily-loop health check: is every channel current, and what is due?

One command any session (or the user) can run to see the whole pipeline's
freshness at a glance. Exit code 1 if anything is STALE, so it can gate the
daily routine.

    python3 scripts/daily_status.py
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = lambda *p: os.path.join(ROOT, "data", *p)
NOW = datetime.now(timezone.utc)


def age_h(path):
    try:
        return (time.time() - os.path.getmtime(path)) / 3600.0
    except OSError:
        return None


def last_day(path, key="date"):
    last = None
    try:
        for line in open(path):
            try:
                last = json.loads(line).get(key) or last
            except json.JSONDecodeError:
                continue
    except OSError:
        return None
    return last


def row(name, ok, detail):
    print(f"  {'OK  ' if ok else 'STALE'}  {name:<26} {detail}")
    return ok


def main() -> int:
    print(f"daily status @ {NOW:%Y-%m-%d %H:%M UTC}\n")
    ok = True
    yday = (NOW - timedelta(days=1)).date().isoformat()
    today = NOW.date().isoformat()

    # --- gathering channels ---
    a = age_h(D("news_archive_live.jsonl"))
    ok &= row("RSS feeds (4h cron)", a is not None and a < 6,
              f"last write {a:.1f}h ago" if a else "missing")
    a = age_h(D("crypto_history", "fear_greed_daily.json"))
    ok &= row("market numbers (daily)", a is not None and a < 30,
              f"last refresh {a:.1f}h ago" if a else "missing")
    a = age_h(D("news_archive_x.jsonl"))
    ok &= row("X capture (daily)", a is not None and a < 30,
              f"last capture {a:.1f}h ago" if a else "missing")
    g_last = last_day(D("news_archive_gdelt_crypto.jsonl"))
    gd_run = subprocess.run(["pgrep", "-f", "gdelt_crypto_fetch"],
                            capture_output=True).returncode == 0
    row("GDELT crawler", True, f"{'running' if gd_run else 'paused'}, newest day {g_last}")

    # --- digestion ---
    ev = D("digest_v2", "events", f"{yday}.json")
    n_ev = 0
    if os.path.exists(ev):
        try:
            n_ev = len(json.load(open(ev)).get("events", []))
        except json.JSONDecodeError:
            pass
    ok &= row(f"digest for {yday}", n_ev > 0, f"{n_ev} events" if n_ev else "NOT DIGESTED")
    imp_last = last_day(D("news_impulses_v2.jsonl"))
    ok &= row("impulses (brain food)", imp_last in (yday, today), f"current through {imp_last}")

    # --- live engine ---
    st = D("state.json")
    a = age_h(st)
    eng = a is not None and a < 1
    row("paper engine", True, f"cycle {a:.2f}h ago" if a else "not run")
    if os.path.exists(D("paper_state.json")):
        p = json.load(open(D("paper_state.json")))
        row("paper book", True, f"${p['cash']:,.0f} cash, {len(p['positions'])} positions")

    # --- backlog triggers ---
    try:
        import glob
        amended = {os.path.basename(f)[:-5]
                   for f in glob.glob(D("digest_v2", "events_amend_crypto", "*.json"))}
        gd = [json.loads(l)["date"] for l in open(D("news_archive_gdelt_crypto.jsonl"))]
        pend = [d for d in gd if d >= "2023-07-01" and d not in amended]
        row("crypto wave backlog", len(pend) < 250,
            f"{len(pend)} GDELT days undigested (wave due at 250)")
    except (OSError, json.JSONDecodeError):
        pass

    print("\n" + ("all channels current" if ok else "ACTION NEEDED — see STALE rows above"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
