#!/usr/bin/env python3
"""Monthly gauntlet re-run: rejected ideas get to keep auditioning.

A verdict like R36-REJECTED is a fact about the data that existed when the
gauntlet ran, not a law. The corpus grows every day (news, X, GDELT waves),
and improved variants (R38 conditional leverage, R39 winter shorts) deserve
periodic re-hearing on the full record. This runs the complete walk-forward
gauntlet — every guard intact: plateau, holdout, book-Pareto — and reports
ADOPTED/REJECTED per round to Telegram. Adoption changes the saved formula
exactly as a hand-run would; nothing skips the guards.

Runs monthly (systemd timer) because a gauntlet pass is hours of compute and
the verdict only shifts meaningfully with months of new evidence.
"""
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))

LOG = ROOT / "data" / "research_retest.log"


def notify(text: str) -> None:
    try:
        from ai_investing.alerts import get_notifier
        from ai_investing.config import Settings
        get_notifier(Settings()).send(text)
    except Exception as exc:
        print(f"(telegram notify failed: {exc})")


def main() -> int:
    started = datetime.now(timezone.utc)
    print(f"gauntlet re-run started {started.isoformat()}", flush=True)
    r = subprocess.run(
        [str(ROOT / ".venv" / "bin" / "python"), "-m",
         "ai_investing.research.train_web", "--v2", "--once", "--no-wait"],
        cwd=str(ROOT / "engine"), capture_output=True, text=True, timeout=6 * 3600)
    out = (r.stdout or "") + "\n" + (r.stderr or "")
    LOG.write_text(out[-100_000:])

    verdicts = [l.strip() for l in out.splitlines()
                if re.search(r"\b(ADOPTED|REJECTED)\b", l)]
    hours = (datetime.now(timezone.utc) - started).total_seconds() / 3600
    adopted = [v for v in verdicts if "ADOPTED" in v]
    head = (f"🧪 *Monthly gauntlet re-run* ({hours:.1f}h, exit {r.returncode})\n"
            f"{len(adopted)} adopted / {len(verdicts) - len(adopted)} rejected")
    lines = [head]
    if adopted:
        lines.append("\n*Newly holding up:*")
        lines += [f"  • {v[:180]}" for v in adopted[:10]]
    watch = [v for v in verdicts if re.search(r"\bR3[6-9]\b", v)]
    if watch:
        lines.append("\n*The leverage/shorts watchlist:*")
        lines += [f"  • {v[:180]}" for v in watch[:6]]
    lines.append(f"\n_full log: data/research_retest.log_")
    notify("\n".join(lines))
    print("\n".join(lines))
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
