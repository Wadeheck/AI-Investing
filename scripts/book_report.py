#!/usr/bin/env python3
"""The forward record — every book, graded on its own trades.

This is the cross-check the system runs against ITSELF: not backtest numbers,
but what the live paper books actually did. It answers, per policy:

  - is it making money, and with how much drawdown
  - which EXIT reasons pay and which bleed (take vs clock vs stop vs flip)
  - does entry conviction actually predict the outcome (the honesty test:
    if strong signals don't beat weak ones, the signal isn't a signal)
  - how long the system was blind (gap entries from downtime)

Run any time:  python3 scripts/book_report.py [--days 30]
"""
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = lambda *p: os.path.join(ROOT, "data", *p)


def load(path):
    rows = []
    try:
        for line in open(path):
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        pass
    return rows


def pct(x):
    return f"{x*100:+.2f}%"


def grade(name, rows, since):
    sells = [r for r in rows if r.get("event") == "sell" and r.get("ts", "") >= since]
    marks = [r for r in rows if r.get("event") == "mark" and r.get("ts", "") >= since]
    gaps = [r for r in rows if r.get("event") == "gap" and r.get("ts", "") >= since]
    print(f"\n=== {name} ===")
    if marks:
        eq = [m["equity"] for m in marks]
        peak, dd = eq[0], 0.0
        for e in eq:
            peak = max(peak, e)
            dd = min(dd, e / peak - 1.0)
        print(f"  equity {eq[0]:,.0f} -> {eq[-1]:,.0f} ({pct(eq[-1]/eq[0]-1)}) "
              f"over {len(marks)} marked days | worst drawdown {pct(dd)}")
    if gaps:
        print(f"  BLIND WINDOWS: {len(gaps)} outages, "
              f"{sum(g.get('down_hours', 0) for g in gaps):.1f}h total — stops could not fire")
    if not sells:
        print("  no closed trades yet — nothing to grade")
        return
    wins = [s for s in sells if s.get("pnl", 0) > 0]
    pnl = sum(s.get("pnl", 0) for s in sells)
    print(f"  closed {len(sells)} trades | win rate {len(wins)/len(sells):.0%} | "
          f"net P&L ${pnl:,.2f} | avg hold {sum(s.get('held_days',0) for s in sells)/len(sells):.1f}d")

    by_reason = defaultdict(list)
    for s in sells:
        key = (s.get("reason", "?").split()[0] + " " + s.get("reason", "").split()[1]
               if s.get("reason", "").startswith("hard") else s.get("reason", "?").split()[0])
        by_reason[key].append(s)
    print("  by exit reason:")
    for k, v in sorted(by_reason.items(), key=lambda kv: -sum(x.get("pnl", 0) for x in kv[1])):
        p = sum(x.get("pnl", 0) for x in v)
        w = sum(1 for x in v if x.get("pnl", 0) > 0)
        print(f"    {k:16} n={len(v):3}  win {w/len(v):3.0%}  P&L ${p:>10,.2f}")

    # the honesty test: does conviction predict outcome?
    conv = [(s.get("shock") or 0, s.get("ret", 0)) for s in sells if s.get("shock")]
    if len(conv) >= 6:
        conv.sort()
        half = len(conv) // 2
        lo = sum(r for _, r in conv[:half]) / half
        hi = sum(r for _, r in conv[half:]) / (len(conv) - half)
        verdict = "signal HOLDS" if hi > lo else "signal DOES NOT hold — investigate"
        print(f"  conviction check: weak-half avg {pct(lo)} vs strong-half {pct(hi)} -> {verdict}")


def main():
    days = 3650
    if "--days" in sys.argv:
        days = int(sys.argv[sys.argv.index("--days") + 1])
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    print(f"FORWARD RECORD (live paper) — trailing {days}d, as of "
          f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}")
    grade("₿ crypto book", load(D("crypto_journal.jsonl")), since)
    grade("⚡ event sleeve", load(D("event_journal.jsonl")), since)

    # trading + investing books from their state files (journal.db has the fills)
    for label, f in (("📈 trading book", "paper_state.json"),
                     ("🏛 investing book", "invest_state.json")):
        try:
            st = json.load(open(D(f)))
            b = st.get("broker", st)
            print(f"\n=== {label} ===")
            print(f"  cash ${b.get('cash', 0):,.2f} | positions {len(b.get('positions', []))}")
        except (OSError, json.JSONDecodeError):
            pass
    # --- the learning loop: expectation vs outcome, and what it changed ---
    try:
        sys.path.insert(0, os.path.join(ROOT, "engine"))
        from ai_investing.config import Settings
        from ai_investing.learning.expectations import ExpectationLedger, MIN_N
        led = ExpectationLedger(Settings())
        rep = led.report()
        print("\n=== 🎓 LEARNING LOOP (expectation vs outcome) ===")
        if not rep["policies"]:
            print("  no settled claims yet — the loop starts with the first closed trade")
        for pol, b in sorted(rep["policies"].items()):
            n = b.get("n", 0)
            state = "LEARNING" if n >= MIN_N else f"gathering ({n}/{MIN_N})"
            print(f"  {pol:14} n={n:3} | calibration {b.get('ratio', 0):+.2f}x "
                  f"| trust score {b.get('score', 0):+.2f} "
                  f"-> size x{led.size_multiplier(pol):.2f}, "
                  f"expectations x{led.calibration_gain(pol):.2f}  [{state}]")
        drv = {k: v for k, v in rep["drivers"].items() if v.get("n", 0) >= 3}
        if drv:
            print("  by driver (which part of the web actually predicts):")
            for d, b in sorted(drv.items(), key=lambda kv: -(kv[1].get("score") or 0))[:8]:
                print(f"    {d:22} n={b['n']:3} score {b.get('score', 0):+.2f} "
                      f"calib {b.get('ratio', 0):+.2f}x")
        print(f"  open claims awaiting outcome: {rep['open_claims']}")
    except Exception as exc:
        print(f"\n  [learning loop unavailable: {type(exc).__name__}]")

    print("\nNote: paper money. Books never reset — this record accumulates.")


if __name__ == "__main__":
    main()
