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


# EVERY CHECK'S RESULT, KEYED BY A STABLE IDENTITY.
#
# The watchdog used to scrape this script's stdout and rate-limit on the whole
# rendered line -- detail included. Every detail string here carries live
# counters, so "the same issue" was never byte-equal to itself two runs apart
# and the 6-hour re-nag never once applied: 15 identical-looking alerts in 90
# minutes reached the user on 2026-08-05.
#
# The identity of a check is the CHECK, not the sentence it prints. It is
# declared here, by the producer, and passed to the watchdog as data. Nothing
# downstream parses prose to work out what broke.
RESULTS: list[dict] = []


def row(name, ok, detail):
    RESULTS.append({"key": name, "ok": bool(ok), "detail": str(detail)})
    print(f"  {'OK  ' if ok else 'STALE'}  {name:<26} {detail}")
    return ok


RECENT_H = 4.0                  # window used to measure the CURRENT burn rate


def _free_token_cap() -> int:
    """The engine's cap, not a copy of it."""
    try:
        sys.path.insert(0, os.path.join(ROOT, "engine"))
        from ai_investing.config import Settings
        return int(Settings().llm_daily_free_tokens) or 5_000_000
    except Exception:                                   # noqa: BLE001
        return 5_000_000                                # documented default


def _project_eod(usage: dict, cap: int) -> tuple[float, str]:
    """Percent of an endpoint's daily allowance in use by 23:59 UTC.

    WHY NOT A LINE THROUGH THE ORIGIN. The old estimator was
    `used * 24 / hours_elapsed`, which assumes today's tokens arrived at a
    steady rate. They do not: the nightly digest crons run just after 00:00
    UTC and spend most of the day's tokens in the first ninety minutes, after
    which the live loop trickles. Dividing a burst by a small elapsed_h
    manufactures an emergency -- on 2026-08-05 it read 262% at 01:51 UTC and
    decayed to 130% by 05:03 while actual use rose only 20%->27%. The endpoint
    finished the day near 50%. Every one of those alerts was false.

    So: extrapolate from the rate over the LAST few hours, not the whole day.
    A burst that has stopped stops counting; a burn that is genuinely ongoing
    still projects over the cap. Falls back to the old shape only when no
    hourly history exists (a file written by an older build), and says which
    basis it used so a surprising number can be traced.
    """
    by_model = usage.get("by_model") or {}
    if not by_model:
        return 0.0, "no use"
    hour_now = NOW.hour + NOW.minute / 60.0
    remaining_h = max(24.0 - hour_now, 0.0)
    by_hour = usage.get("by_hour") or {}

    worst, basis = 0.0, "elapsed-rate"
    for model, total in by_model.items():
        hours = by_hour.get(model) or {}
        if hours:
            recent = sum(t for h, t in hours.items()
                         if hour_now - int(h) < RECENT_H)
            # tokens/hour over the window actually covered so far today
            window = min(RECENT_H, max(hour_now, 0.25))
            rate = recent / window
            projected = total + rate * remaining_h
            basis = f"last {RECENT_H:.0f}h rate"
        else:
            projected = total * 24.0 / max(hour_now, 0.5)
        worst = max(worst, 100.0 * projected / cap)
    return worst, basis


def main() -> int:
    print(f"daily status @ {NOW:%Y-%m-%d %H:%M UTC}\n")
    ok = True
    yday = (NOW - timedelta(days=1)).date().isoformat()
    today = NOW.date().isoformat()

    # --- gathering channels ---
    a = age_h(D("news_archive_live.jsonl"))
    row("RSS archive (4h cron)", a is not None and a < 8,
        f"last write {a:.1f}h ago" if a else "missing")
    # What actually matters is whether the BRAIN is current. The archive above is
    # a 4-hourly writer; the live path polls every cycle, so reporting the
    # archive's age read as "news is 2h stale" while the brain was 2 MINUTES
    # behind live. Measure the thing that decides.
    try:
        import sqlite3
        con = sqlite3.connect(D("brain.db"))
        newest = list(con.execute("select max(first_seen) from articles"))[0][0]
        n_today = list(con.execute(
            "select count(*) from articles where first_seen >= ?", (today,)))[0][0]
        con.close()
        lag_m = (NOW - datetime.fromisoformat(newest)).total_seconds() / 60.0
        ok &= row("news reaching the brain", lag_m < 60,
                  f"newest article {lag_m:.0f}m old, {n_today} seen today")
    except Exception:
        pass
    a = age_h(D("crypto_history", "fear_greed_daily.json"))
    ok &= row("market numbers (daily)", a is not None and a < 30,
              f"last refresh {a:.1f}h ago" if a else "missing")
    # X capture needs an interactive browser session (no API, by instruction),
    # so it CANNOT self-heal like every other channel. Reported, never fatal --
    # a channel that only a human can refill must not make the health check cry
    # wolf every day, or the real failures get lost in it.
    a = age_h(D("news_archive_x.jsonl"))
    row("X capture (manual)", a is not None and a < 30,
              f"last capture {a:.1f}h ago" if a else "missing")
    # ...but freshness of the FILE says nothing about whether the capture reached
    # the brain, and for the life of the project it did not: the archive was
    # write-only, so a perfectly fresh row above sat next to zero X content in
    # brain.db. Measure arrival, not deposit — the same mistake as reporting the
    # 4-hourly RSS archive's age instead of the brain's lag.
    try:
        import sqlite3
        con = sqlite3.connect(D("brain.db"))
        arts = list(con.execute(
            "select coalesce(sum(digested),0), count(*) from articles "
            "where source like 'x.com%'"))[0]
        evs = list(con.execute(
            "select count(*) from events where source like 'x.com%'"))[0][0]
        con.close()
        done, total = int(arts[0]), int(arts[1])
        ok &= row("X capture -> brain", total > 0 and done > 0,
                  f"{done}/{total} posts digested, {evs} events tagged"
                  + ("" if total else "  <-- captured but NEVER ingested"))
    except Exception:
        pass
    a = age_h(D("crypto_signals.json"))
    ok &= row("crypto signals (hourly)", a is not None and a < 3,
              f"funding/F&G {a:.1f}h ago" if a else "missing")
    a = age_h(D("crypto_positioning.json"))
    ok &= row("crypto positioning (daily)", a is not None and a < 30,
              f"LSR/OI {a:.1f}h ago" if a else "missing")
    a = age_h(D("macro_cache.json"))
    ok &= row("macro anchors (6h)", a is not None and a < 8,
              f"VIX/DXY/FRED {a:.1f}h ago" if a else "missing")
    gd_run = subprocess.run(["pgrep", "-f", "gdelt_crypto_fetch"],
                            capture_output=True).returncode == 0
    # "newest day" hid the real state: the archive is 78 scattered gaps, not a
    # frontier — the max date said 2025-12 while whole years were missing.
    # Count coverage against the crawler's own target range instead.
    try:
        from datetime import date as _date, timedelta as _td
        covered = set()
        for _l in open(D("news_archive_gdelt_crypto.jsonl")):
            try:
                covered.add(json.loads(_l)["date"])
            except (json.JSONDecodeError, KeyError):
                pass
        _start = _date(2023, 7, 1)   # gdelt_crypto_fetch.START
        _total = ( _date.today() - _start).days
        _miss = sum(1 for i in range(_total)
                    if (_start + _td(days=i)).isoformat() not in covered)
        detail = f"{len(covered)}/{_total} days fetched, {_miss} to go"
    except OSError:
        detail = "archive unreadable"
    row("GDELT crawler", True, f"{'running' if gd_run else 'paused'}, {detail}")

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
    # WHICH BOOK IS ACTUALLY BEING TRADED. paper_state.json stopped being the
    # trading book the moment LIVE_TRADING was enabled — it is now a frozen
    # snapshot, and reporting it as "the book" is this project's oldest failure
    # wearing yet another hat: the status tool confidently printing a number
    # nobody is trading. Found 2026-08-04, minutes after the live switch, on the
    # one line a person actually glances at to check the bot.
    live_book = D("live_book.json")
    if os.path.exists(live_book):
        lb = json.load(open(live_book))
        base = float(lb.get("base") or 0.0)
        realized = float(lb.get("realized") or 0.0)
        marks = lb.get("marks") or {}
        row("LIVE book (traded)", True,
            f"${base:,.0f} slice, realised ${realized:+,.2f}, "
            f"{len(marks)} position(s) — orders go to a real broker")
    if os.path.exists(D("paper_state.json")):
        p = json.load(open(D("paper_state.json")))
        label = "paper book (FROZEN)" if os.path.exists(live_book) else "paper book"
        note = "" if not os.path.exists(live_book) else "  <-- not traded while LIVE is on"
        row(label, True,
            f"${p['cash']:,.0f} cash, {len(p['positions'])} positions{note}")

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
        # ONE definition of the cap. This used to hardcode 5_000_000 while the
        # engine read LLM_DAILY_FREE_TOKENS, so setting the env var would have
        # moved the rotation threshold and left the alert measuring the old one.
        cap = _free_token_cap()
        u = json.load(open(D("llm_usage.json")))
        if u.get("day") == today:
            worst = 0.0
            parts = []
            for model, tok in sorted(u.get("by_model", {}).items(),
                                     key=lambda kv: -kv[1]):
                frac = 100.0 * tok / cap
                worst = max(worst, frac)
                parts.append(f"{model[-5:]}={tok / 1000:.0f}k({frac:.1f}%)")
            proj, basis = _project_eod(u, cap)
            # DO NOT PAGE ON AN ESTIMATOR KNOWN TO BE WRONG. The elapsed-rate
            # fallback is the line-through-the-origin that produced 15 false
            # alerts (§4.20); it is kept only to report a number for usage files
            # written before hourly buckets existed. Such a file can only be
            # today's, so this is self-expiring. The real protection against
            # overspend is `_over_free_budget`, which rotates an endpoint away on
            # 90% ACTUAL use and does not extrapolate at all.
            trustworthy = basis != "elapsed-rate"
            ok &= row("LLM free allowance", proj < 100 or not trustworthy,
                      f"{', '.join(parts) or 'unused'} of {cap // 1_000_000}M/day each"
                      f" — busiest projects to {proj:.0f}% by day end ({basis}"
                      f"{'' if trustworthy else ', not alerting: no hourly history'})")
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
    # --json: same checks, same exit code, machine-readable result.
    # The human report still runs (it is where the checks live) but goes to
    # stderr so stdout carries nothing but the JSON. A consumer that has to
    # split prose from data will eventually get it wrong.
    if "--json" in sys.argv:
        import contextlib
        with contextlib.redirect_stdout(sys.stderr):
            code = main()
        json.dump(RESULTS, sys.stdout)
        sys.stdout.write("\n")
        sys.exit(code)
    sys.exit(main())
