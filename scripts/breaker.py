#!/usr/bin/env python3
"""Inspect, repair, and clear the circuit breaker — the halt review tool.

The breaker latches on purpose: a halt that clears itself is not a safety
mechanism. But a latch with no inspection tool is its own failure mode. On
2026-08-04 the engine halted at 02:43 UTC and the only thing anyone could see
was an identical Telegram alert every five minutes; answering "should this halt
stand?" meant reading breaker.json by hand and cross-checking it against the
journal. This is that check, written down.

WHY MARKS GO WRONG, and why --repair-marks exists
-------------------------------------------------
Every threshold is measured against a stored mark: day_start_equity,
peak_equity, inception_equity. A mark taken from a bad valuation is permanent
damage, because the honest readings that follow are all measured against a
number that never happened.

That is exactly what happened. A feed outage valued twelve positions at 0.0, so
equity read as pure cash — $116,027, short proceeds included, against a true
$99,997. That reading became both the day's opening mark and the all-time peak.
The next honest cycle measured a 13.8% "daily drawdown" against it and flattened
a book that had not lost anything. The root cause is fixed (Portfolio._px now
falls back to cost basis, and the breaker refuses a non-finite equity), but the
poisoned marks outlive the fix and have to be corrected against the record.

`--repair-marks` recomputes the marks from data/journal.db, keeping only
valuations that can be trusted:

  * equity must be finite and positive
  * a row with positions>0 where equity == cash to the cent is a PHANTOM: every
    holding was valued at zero. Discarded, never used as a mark.

    (Yes, this can in principle discard a legitimate reading where the positions
    happen to net to exactly zero. That costs one mark; keeping a phantom costs
    a liquidation.)

  python3 scripts/breaker.py                  # status + verdict
  python3 scripts/breaker.py --repair-marks   # recompute marks from the journal
  python3 scripts/breaker.py --clear          # release the halt (asks first)
  python3 scripts/breaker.py --clear --yes    # release, unattended
"""
import argparse
import json
import math
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BREAKER = ROOT / "data" / "breaker.json"
JOURNAL = ROOT / "data" / "journal.db"


def load() -> dict:
    try:
        return json.loads(BREAKER.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"cannot read {BREAKER}: {exc}")
        sys.exit(1)


def save(s: dict) -> None:
    tmp = BREAKER.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(s, indent=2))
    tmp.replace(BREAKER)


def trusted_rows() -> list[tuple]:
    """(ts, equity) for every journal row whose valuation is believable."""
    out = []
    try:
        con = sqlite3.connect(JOURNAL)
        rows = list(con.execute(
            "SELECT ts, equity, cash, positions FROM equity ORDER BY ts"))
        con.close()
    except sqlite3.Error as exc:
        print(f"cannot read {JOURNAL}: {exc}")
        return out
    for ts, eq, cash, n in rows:
        if eq is None or not math.isfinite(eq) or eq <= 0:
            continue
        if n and cash is not None and abs(eq - cash) < 0.01:
            continue                       # phantom: positions valued at zero
        out.append((ts, float(eq)))
    return out


def status(s: dict) -> int:
    print(f"circuit breaker  ({BREAKER.relative_to(ROOT)})\n")
    halted = bool(s.get("halted"))
    print(f"  state            {'HALTED' if halted else 'running'}")
    if halted:
        print(f"  reason           {s.get('halt_reason') or '(none recorded)'}")
        if str(s.get("halt_reason", "")).startswith("daily"):
            print("                   (a DAILY halt clears itself at the next "
                  "UTC midnight)")
    for k in ("inception_equity", "peak_equity", "day_start_equity",
              "month_close_equity", "hwm"):
        v = s.get(k)
        print(f"  {k:<17}{f'${v:,.2f}' if isinstance(v, (int, float)) else v}")
    print(f"  day              {s.get('day')}  "
          f"trades {s.get('trades_today')}  notional ${s.get('notional_today', 0):,.0f}")

    rows = trusted_rows()
    if not rows:
        print("\n  no trustworthy journal rows — cannot cross-check the marks")
        return 1 if halted else 0
    true_peak = max(e for _, e in rows)
    latest_ts, latest = rows[-1]
    print(f"\n  cross-check against {len(rows)} trusted journal rows:")
    print(f"    true peak      ${true_peak:,.2f}")
    print(f"    latest         ${latest:,.2f}  ({latest_ts})")

    bad = []
    for k in ("peak_equity", "day_start_equity"):
        v = s.get(k)
        if isinstance(v, (int, float)) and v > true_peak * 1.001:
            bad.append(f"{k} ${v:,.2f} exceeds the highest equity ever "
                       f"honestly recorded (${true_peak:,.2f})")
    if bad:
        print("\n  MARKS ARE POISONED:")
        for b in bad:
            print(f"    - {b}")
        print("    A mark above any real reading means the book is measured as "
              "permanently\n    underwater and will re-halt. Fix with "
              "--repair-marks.")
        return 2
    print("\n  marks are consistent with the record")
    return 1 if halted else 0


def repair(s: dict) -> int:
    rows = trusted_rows()
    if not rows:
        print("no trustworthy journal rows — refusing to guess at the marks")
        return 1
    true_peak = max(e for _, e in rows)
    latest = rows[-1][1]
    today = str(s.get("day", ""))
    day_rows = [e for ts, e in rows if str(ts).startswith(today)]

    changes = []
    if isinstance(s.get("peak_equity"), (int, float)) and s["peak_equity"] > true_peak * 1.001:
        changes.append(("peak_equity", s["peak_equity"], true_peak))
        s["peak_equity"] = round(true_peak, 2)
    new_day = min(day_rows) if day_rows else latest
    # The day's opening mark should be the first TRUSTED equity of the day, not
    # the lowest — but if the poisoned mark opened the day, the honest rows that
    # follow are all we have, and the earliest of them is the closest available
    # stand-in. Use the day's minimum so the repair can never manufacture
    # headroom the book did not have.
    if isinstance(s.get("day_start_equity"), (int, float)) and s["day_start_equity"] > true_peak * 1.001:
        changes.append(("day_start_equity", s["day_start_equity"], new_day))
        s["day_start_equity"] = round(new_day, 2)
    if isinstance(s.get("month_close_equity"), (int, float)) and s["month_close_equity"] > true_peak * 1.001:
        changes.append(("month_close_equity", s["month_close_equity"], latest))
        s["month_close_equity"] = round(latest, 2)

    if not changes:
        print("marks already consistent with the record — nothing to repair")
        return 0
    for k, old, new in changes:
        print(f"  {k}: ${old:,.2f} -> ${new:,.2f}")
    save(s)
    print(f"\nrepaired {len(changes)} mark(s). The halt itself is UNCHANGED — "
          f"clear it deliberately with --clear once you agree it was spurious.")
    return 0


def clear(s: dict, yes: bool) -> int:
    if not s.get("halted"):
        print("not halted — nothing to clear")
        return 0
    print(f"halt reason: {s.get('halt_reason')}")
    if not yes:
        try:
            if input("release the halt and let the engine trade again? [y/N] "
                     ).strip().lower() not in ("y", "yes"):
                print("left halted")
                return 0
        except EOFError:
            print("no tty and no --yes — left halted")
            return 1
    s["halted"] = False
    s["halt_reason"] = ""
    save(s)
    print("halt released. The engine picks this up on its next cycle "
          "(within ~5 minutes); it does NOT reopen the closed positions — it "
          "re-decides from current signals.")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repair-marks", action="store_true")
    ap.add_argument("--clear", action="store_true")
    ap.add_argument("--status", action="store_true", help="default action")
    ap.add_argument("--yes", action="store_true", help="skip the confirmation")
    a = ap.parse_args(argv)
    s = load()
    if a.repair_marks:
        return repair(s)
    if a.clear:
        return clear(s, a.yes)
    return status(s)


if __name__ == "__main__":
    sys.exit(main())
