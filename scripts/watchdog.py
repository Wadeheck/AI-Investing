#!/usr/bin/env python3
"""The thing that notices, so a human doesn't have to.

Every health signal this project has was already being computed -- and every
one of them was invisible. daily_status.py printed to a terminal nobody was
watching; the 11.9h outage was found by accident, and the tagger discarded 57%
of the news for the life of the project with all checks green. On a headless
mini PC that gap is the whole problem: SSH tells you nothing until you log in
and ask.

This runs on a timer, checks what a human would check, and pushes to Telegram
only when something is WRONG. Silence means healthy.

Design rules learned the hard way:
  * Alerts are rate-limited per issue. A broken thing stays broken for hours;
    re-sending every 15 minutes trains you to ignore the channel, and an
    ignored alert channel is the same as no alert channel.
  * A RECOVERY message is sent when a previously-failing check passes, so the
    absence of alerts is trustworthy rather than ambiguous.
  * The watchdog must never crash: an exception here is a blind spot, so
    everything is defensive and failures self-report.

  python3 scripts/watchdog.py           # check, alert if needed
  python3 scripts/watchdog.py --test    # prove the alert path works
"""
import argparse
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))

STATE = ROOT / "data" / "watchdog_state.json"
RENOTIFY_S = 6 * 3600.0        # re-nag about the same issue at most every 6h
DISK_MIN_PCT = 10.0            # free space below this is an alert
SERVICES = ("ai-investing", "ai-investing-chat")


def _load() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _save(d: dict) -> None:
    try:
        tmp = str(STATE) + ".tmp"
        Path(tmp).write_text(json.dumps(d, indent=1))
        Path(tmp).replace(STATE)
    except OSError:
        pass


def check_services() -> list[str]:
    """systemd restarts a dead service, but a CRASH LOOP is still an outage."""
    bad = []
    for svc in SERVICES:
        try:
            active = subprocess.run(
                ["systemctl", "--user", "is-active", svc],
                capture_output=True, text=True, timeout=20).stdout.strip()
            if active != "active":
                bad.append(f"service {svc} is {active}")
                continue
            n = subprocess.run(
                ["systemctl", "--user", "show", svc, "-p", "NRestarts", "--value"],
                capture_output=True, text=True, timeout=20).stdout.strip()
            # restarts are normal over weeks; a burst means it cannot stay up
            prev = _load().get(f"restarts_{svc}")
            if prev is not None and n.isdigit() and int(n) - int(prev) >= 5:
                bad.append(f"{svc} restarted {int(n) - int(prev)}x since last check "
                           f"— crash loop, not a blip")
        except Exception as exc:                        # noqa: BLE001
            bad.append(f"cannot query {svc}: {type(exc).__name__}")
    return bad


def check_disk() -> list[str]:
    try:
        u = shutil.disk_usage(str(ROOT))
        free_pct = 100.0 * u.free / u.total
        if free_pct < DISK_MIN_PCT:
            return [f"disk {free_pct:.0f}% free ({u.free / 2**30:.1f} GB) — "
                    f"a full disk corrupts every book it tries to write"]
    except OSError as exc:
        return [f"cannot stat disk: {exc}"]
    return []


def check_health() -> list[str]:
    """Reuse daily_status: one definition of healthy, not two that drift."""
    try:
        r = subprocess.run([str(ROOT / ".venv" / "bin" / "python"),
                            str(ROOT / "scripts" / "daily_status.py")],
                           capture_output=True, text=True, timeout=600)
    except Exception as exc:                            # noqa: BLE001
        return [f"health check did not run: {type(exc).__name__}"]
    if r.returncode == 0:
        return []
    return [ln.strip() for ln in r.stdout.splitlines() if ln.strip().startswith("STALE")]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true", help="send a test alert and exit")
    args = ap.parse_args()

    from ai_investing.alerts import get_notifier
    from ai_investing.config import Settings
    notifier = get_notifier(Settings())

    if args.test:
        ok = notifier.send("🔔 watchdog test — if you can read this, "
                           "remote alerting works.")
        print("sent" if ok else "FAILED to send — check TELEGRAM_* in .env")
        return 0 if ok else 1

    issues = check_services() + check_disk() + check_health()
    state = _load()
    now = time.time()

    # refresh restart baselines regardless of outcome
    for svc in SERVICES:
        try:
            n = subprocess.run(
                ["systemctl", "--user", "show", svc, "-p", "NRestarts", "--value"],
                capture_output=True, text=True, timeout=20).stdout.strip()
            if n.isdigit():
                state[f"restarts_{svc}"] = n
        except Exception:                               # noqa: BLE001
            pass

    if not issues:
        if state.get("failing"):
            notifier.send("✅ *Recovered* — all checks green again.")
            print("recovered; notified")
        state["failing"] = []
        state["last_ok"] = datetime.now(timezone.utc).isoformat()
        _save(state)
        print("all healthy")
        return 0

    # only nag about issues that are new, or stale enough to repeat
    sent_at = state.get("sent_at", {})
    fresh = [i for i in issues if now - float(sent_at.get(i, 0)) > RENOTIFY_S]
    if fresh:
        body = "\n".join(f"• {i}" for i in fresh)
        notifier.send(f"🚨 *AI-Investing needs attention*\n{body}\n\n"
                      f"_ssh in and run: python3 scripts/daily_status.py_")
        for i in fresh:
            sent_at[i] = now
    state["sent_at"] = {k: v for k, v in sent_at.items() if k in issues}
    state["failing"] = issues
    _save(state)
    for i in issues:
        print(f"  ISSUE: {i}")
    print(f"({len(fresh)} alerted, {len(issues) - len(fresh)} already known)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
