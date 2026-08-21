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


def check_services() -> list[tuple[str, str]]:
    """systemd restarts a dead service, but a CRASH LOOP is still an outage."""
    bad = []
    for svc in SERVICES:
        try:
            active = subprocess.run(
                ["systemctl", "--user", "is-active", svc],
                capture_output=True, text=True, timeout=20).stdout.strip()
            if active != "active":
                bad.append((f"service:{svc}", f"service {svc} is {active}"))
                continue
            n = subprocess.run(
                ["systemctl", "--user", "show", svc, "-p", "NRestarts", "--value"],
                capture_output=True, text=True, timeout=20).stdout.strip()
            # restarts are normal over weeks; a burst means it cannot stay up
            prev = _load().get(f"restarts_{svc}")
            if prev is not None and n.isdigit() and int(n) - int(prev) >= 5:
                bad.append((f"crashloop:{svc}",
                            f"{svc} restarted {int(n) - int(prev)}x since last check "
                            f"— crash loop, not a blip"))
        except Exception as exc:                        # noqa: BLE001
            bad.append((f"query:{svc}", f"cannot query {svc}: {type(exc).__name__}"))
    return bad


def check_disk() -> list[tuple[str, str]]:
    try:
        u = shutil.disk_usage(str(ROOT))
        free_pct = 100.0 * u.free / u.total
        if free_pct < DISK_MIN_PCT:
            return [("disk",
                     f"disk {free_pct:.0f}% free ({u.free / 2**30:.1f} GB) — "
                     f"a full disk corrupts every book it tries to write")]
    except OSError as exc:
        return [("disk-stat", f"cannot stat disk: {exc}")]
    return []


def check_health() -> list[tuple[str, str]]:
    """Reuse daily_status: one definition of healthy, not two that drift.

    Returns (key, description) pairs. The KEY is the check's stable identity,
    declared by daily_status itself; the description is what the user reads.
    Rate limiting keys on the former -- see the note above `_alert_key`.
    """
    try:
        r = subprocess.run([str(ROOT / ".venv" / "bin" / "python"),
                            str(ROOT / "scripts" / "daily_status.py"), "--json"],
                           capture_output=True, text=True, timeout=600)
    except Exception as exc:                            # noqa: BLE001
        return [("health-runner", f"health check did not run: {type(exc).__name__}")]
    if r.returncode == 0:
        return []
    try:
        rows = json.loads(r.stdout)
    except (json.JSONDecodeError, ValueError):
        # Fail LOUD but ONCE: a health check that cannot be read is itself an
        # issue, and it has a stable key so it cannot storm either.
        return [("health-unparseable",
                 "health check produced no readable result — ssh in and run it")]
    return [(f"check:{row['key']}", f"{row['key']}: {row['detail']}")
            for row in rows if not row.get("ok")]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true", help="send a test alert and exit")
    args = ap.parse_args(argv)

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

    # ONLY NAG ABOUT ISSUES THAT ARE NEW, OR STALE ENOUGH TO REPEAT.
    #
    # Keyed on the issue's IDENTITY, never on its wording. This rate limit was
    # written on day one and had never once fired, because the key was the
    # rendered sentence and every sentence here carries a live number: token
    # counts, restart counts, free-disk percentage. "LLM free allowance at
    # 20.2%" and "...at 20.8%" are the same issue and were treated as two,
    # so the user got 15 pages in 90 minutes for a condition that was both
    # unchanged and, as it turned out, not real.
    #
    # A rate limit whose key includes the thing that changes is not a rate
    # limit. The description still shows the current numbers -- it just no
    # longer decides whether to send.
    keys = [k for k, _ in issues]
    sent_at = state.get("sent_at", {})
    fresh = [(k, d) for k, d in issues if now - float(sent_at.get(k, 0)) > RENOTIFY_S]
    if fresh:
        body = "\n".join(f"• {d}" for _, d in fresh)
        notifier.send(f"🚨 *AI-Investing needs attention*\n{body}\n\n"
                      f"_ssh in and run: python3 scripts/daily_status.py_")
        for k, _ in fresh:
            sent_at[k] = now
    state["sent_at"] = {k: v for k, v in sent_at.items() if k in keys}
    state["failing"] = keys
    _save(state)
    for _, d in issues:
        print(f"  ISSUE: {d}")
    print(f"({len(fresh)} alerted, {len(issues) - len(fresh)} already known)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
