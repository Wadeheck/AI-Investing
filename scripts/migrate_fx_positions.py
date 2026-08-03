#!/usr/bin/env python3
"""One-time repair: restate non-USD positions and their cash in USD.

Before data/fx.py existed, a HK/KR/JP/TW/CN/EU fill was recorded at its LOCAL
price and then summed into a USD book. Two things are therefore wrong in the
saved state:

  1. avg_price is in local units. Left alone, the new USD marks would show a
     fabricated ~87% loss on every Hong Kong name -- an accounting artefact,
     not a trade.
  2. cash is wrong by the same factor. Shorting 11.84 of 2097.HK credited
     $2,677 when the true proceeds were $341, so the book believes it holds
     cash it never received.

This restates both. It is NOT a reset and does not close, open or re-price any
position: the holdings and their economics are unchanged, only the unit they
were recorded in is corrected. Every book keeps trading its existing positions.

Writes a .bak of each file first.

Idempotency is tracked in data/fx_migration.json, NOT inside the book files:
the engine rewrites those every cycle from its own in-memory broker, which
silently strips any marker added here. A second run would then convert already
-converted prices and destroy the book. The sentinel lives where only this
script writes.

  python3 scripts/migrate_fx_positions.py --dry-run   # show, change nothing
  python3 scripts/migrate_fx_positions.py             # apply
"""
import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))

from ai_investing.config import Settings          # noqa: E402
from ai_investing.data import fx                  # noqa: E402

BOOKS = ["paper_state.json", "invest_state.json", "crypto_state.json",
         "event_state.json"]
SENTINEL = ROOT / "data" / "fx_migration.json"


def already_done(name: str) -> bool:
    try:
        return name in json.loads(SENTINEL.read_text()).get("migrated", [])
    except (OSError, json.JSONDecodeError):
        return False


def mark_done(name: str) -> None:
    try:
        blob = json.loads(SENTINEL.read_text())
    except (OSError, json.JSONDecodeError):
        blob = {"migrated": []}
    if name not in blob.setdefault("migrated", []):
        blob["migrated"].append(name)
    blob["ts"] = datetime.now(timezone.utc).isoformat()
    SENTINEL.write_text(json.dumps(blob, indent=1))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    settings = Settings()
    rates = fx.rates(settings, force=True)
    if not rates:
        print("no FX rates available — refusing to migrate blind")
        return 1
    print(f"rates: {({k: round(v, 2) for k, v in rates.items()})}\n")

    for name in BOOKS:
        path = ROOT / "data" / name
        if not path.exists():
            continue
        blob = json.loads(path.read_text())
        book = blob.get("broker") if isinstance(blob.get("broker"), dict) else blob
        if already_done(name):
            print(f"{name}: already migrated, skipping")
            continue
        positions = book.get("positions") or []
        cash_fix = 0.0
        changed = []
        for p in positions:
            sym = p.get("symbol", "")
            rate = fx.rate_for(sym, settings)
            if not rate or rate <= 0:
                continue
            qty, avg = float(p.get("qty", 0)), float(p.get("avg_price", 0))
            new_avg = avg / rate
            # cash moved by -qty*price at open; it was booked in local units,
            # so the book over-credited (or over-debited) by the difference
            cash_fix += qty * avg * (1.0 - 1.0 / rate)
            changed.append((sym, avg, new_avg, qty))
            if not args.dry_run:
                p["avg_price"] = round(new_avg, 6)
                for k in ("entry_price", "stop_price", "take_price", "high_water"):
                    if isinstance(p.get(k), (int, float)) and p[k]:
                        p[k] = round(float(p[k]) / rate, 6)
        if not changed:
            print(f"{name}: nothing to convert")
            continue
        old_cash = float(book.get("cash", 0.0))
        print(f"{name}:")
        for sym, a, b, q in changed:
            print(f"   {sym:12} qty {q:>10.3f}   avg {a:>12,.2f} -> {b:>10,.2f} USD")
        print(f"   cash {old_cash:>12,.0f} -> {old_cash + cash_fix:>10,.0f} USD "
              f"({cash_fix:+,.0f} correction)")
        if args.dry_run:
            print("   (dry run — not written)\n")
            continue
        shutil.copy2(path, str(path) + ".bak")
        book["cash"] = round(old_cash + cash_fix, 2)
        path.write_text(json.dumps(blob, indent=1))
        mark_done(name)
        print(f"   written (backup at {path.name}.bak)\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
