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
    a = age_h(D("crypto_signals.json"))
    ok &= row("crypto signals (hourly)", a is not None and a < 3,
              f"funding/F&G {a:.1f}h ago" if a else "missing")
    a = age_h(D("crypto_positioning.json"))
    ok &= row("crypto positioning (daily)", a is not None and a < 30,
              f"LSR/OI {a:.1f}h ago" if a else "missing")
    a = age_h(D("macro_cache.json"))
    ok &= row("macro anchors (6h)", a is not None and a < 8,
              f"VIX/DXY/FRED {a:.1f}h ago" if a else "missing")
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
    eng = a is not None and a < 1.0
    ok &= row("paper engine", eng,
              (f"cycle {a:.2f}h ago" if a else "never run") +
              ("" if eng else "  <-- STALLED: restart with `make run`"))
    if os.path.exists(D("paper_state.json")):
        p = json.load(open(D("paper_state.json")))
        row("paper book", True, f"${p['cash']:,.0f} cash, {len(p['positions'])} positions")

    # --- live perception quality ---
    # The corpus digester was always audited; the tagger that actually runs in
    # the engine was not, and it had been returning polarity 0 on 57% of events.
    # Since impulse = polarity x magnitude x credibility, those events reached
    # the graph as nothing: the brain was reading the news and discarding half
    # of it. This row exists so that can never again be invisible.
    try:
        import sqlite3
        con = sqlite3.connect(D("brain.db"))
        since = (NOW - timedelta(days=2)).isoformat()
        rows = list(con.execute(
            "select polarity, nodes from events where ts >= ?", (since,)))
        con.close()
        if rows:
            dead = sum(1 for p, n in rows
                       if abs(p or 0) < 1e-9 and n not in ("[]", "", None))
            pctd = 100.0 * dead / len(rows)
            ok &= row("live tagger (unsigned)", pctd <= 15,
                      f"{pctd:.0f}% of {len(rows)} events unsigned "
                      f"(>15% means the brain is discarding what it reads)")
    except Exception:
        pass

    # --- LLM free-allowance budget ---
    # Each authorized endpoint has a free daily token allowance. Crossing it
    # starts costing money with no error and no signal, so it is metered.
    try:
        cap = 5_000_000
        u = json.load(open(D("llm_usage.json")))
        if u.get("day") == today:
            worst = 0.0
            parts = []
            for model, tok in sorted(u.get("by_model", {}).items(),
                                     key=lambda kv: -kv[1]):
                frac = 100.0 * tok / cap
                worst = max(worst, frac)
                parts.append(f"{model[-5:]}={tok / 1000:.0f}k({frac:.1f}%)")
            ok &= row("LLM free allowance", worst < 80,
                      f"{', '.join(parts) or 'unused'} of {cap // 1_000_000}M/day each")
        else:
            row("LLM free allowance", True, "no calls yet today")
    except (OSError, json.JSONDecodeError):
        pass

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
