#!/usr/bin/env python3
"""The inbox for everything the machine cannot do alone.

Most of this system self-heals: data refreshes on timers, digestion runs
unattended, systemd restarts what dies. A few things genuinely need a human —
and those were the ones with no mechanism at all. Two sell proposals sat pending
for eighteen hours because they were pushed to Telegram once and never mentioned
again, and the X capture went stale for thirty hours because nothing asked for
it. Silence looked identical to "nothing needed".

This collects every open ask and pings Telegram with it, on a timer.

Rules, learned from the watchdog:
  * ONE digest message, not one per item. Several separate pings train you to
    swipe them away.
  * Rate-limited per item, and escalating: a proposal ignored for an hour is
    probably unread, one ignored for a day is a decision not to act, so it is
    mentioned less often rather than more.
  * Silence is meaningful. If nothing needs you, nothing is sent.

  python3 scripts/needs_you.py          # ping if anything is open
  python3 scripts/needs_you.py --show   # print, never send
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))

STATE = ROOT / "data" / "needs_you_state.json"
# Ask again after this long. Deliberately increasing: the longer something sits,
# the more likely leaving it IS the decision, and nagging harder is wrong.
BACKOFF_H = [2, 8, 24, 72]


def _load() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _save(d: dict) -> None:
    try:
        tmp = str(STATE) + ".tmp"
        Path(tmp).write_text(json.dumps(d, indent=1))
        os.replace(tmp, STATE)
    except OSError:
        pass


def _age_h(p: Path):
    try:
        return (time.time() - p.stat().st_mtime) / 3600.0
    except OSError:
        return None


def _trade_approval_on() -> bool:
    """Read TRADE_APPROVAL the way the engine does, .env fallback included —
    this script runs from cron, where the engine's env is not exported."""
    v = os.environ.get("TRADE_APPROVAL")
    if v is None:
        try:
            for line in (ROOT / ".env").read_text().splitlines():
                line = line.strip()
                if line.startswith("TRADE_APPROVAL="):
                    v = line.split("=", 1)[1].split("#")[0].strip()
        except OSError:
            pass
    return (v or "false").lower() in ("1", "true", "yes", "on")


def collect() -> list[dict]:
    """Everything currently waiting on the user. key = stable id for backoff."""
    asks: list[dict] = []

    # 1. Trade proposals awaiting approve/skip. These have real money meaning
    #    (in paper terms) and were the thing that silently sat for 18h.
    #    With TRADE_APPROVAL off the engine no longer waits for taps, so any
    #    proposal still on disk is a relic from before autonomy — nagging about
    #    it asks for a decision that no longer exists (seen 2026-08-05: eight
    #    dead proposals in the 21:00 digest). Expired ones are equally moot.
    if _trade_approval_on():
        try:
            blob = json.loads((ROOT / "data" / "proposals.json").read_text())
            now = datetime.now(timezone.utc)
            for p in blob.get("proposals", []):
                if p.get("status") != "pending":
                    continue
                try:
                    if datetime.fromisoformat(p["expires"]) <= now:
                        continue
                except (KeyError, ValueError):
                    pass
                try:
                    age = (now - datetime.fromisoformat(p["ts"])).total_seconds() / 3600.0
                except (KeyError, ValueError):
                    age = 0.0
                asks.append({
                    "key": f"proposal:{p['id']}",
                    "text": f"*{p['side'].upper()} {p['symbol']}* qty {float(p['qty']):.2f} "
                            f"@ ${float(p['price']):,.2f} — pending {age:.0f}h",
                    "how": "tap ⏳ pending approvals, or /pending",
                })
        except (OSError, json.JSONDecodeError):
            pass

    # 1b. Inference reads awaiting 👍😐👎. Unlike a dead trade proposal, an
    #     unanswered read is ALWAYS live work: it is already steering money at
    #     full weight until you weigh in, so silence here has a cost.
    try:
        blob = json.loads((ROOT / "data" / "inferences.json").read_text())
        now = datetime.now(timezone.utc)
        for r in blob.get("inferences", []):
            if r.get("verdict"):
                continue
            try:
                if datetime.fromisoformat(r["expires"]) <= now:
                    continue
            except (KeyError, ValueError):
                pass
            asks.append({
                "key": f"inference:{r['id']}",
                "text": f"*Do you agree with this read?* {r.get('claim', '')[:120]}",
                "how": "tap ⚖️ my reads, or /inferences",
            })
    except (OSError, json.JSONDecodeError):
        pass

    # 2. X capture. Needs an interactive browser session because the no-API
    #    constraint rules out the alternative — the one channel that cannot
    #    self-heal, so it must be asked for explicitly.
    a = _age_h(ROOT / "data" / "news_archive_x.jsonl")
    if a is None or a > 26:   # a DAILY task: more than a day late means ask
        asks.append({
            "key": "x_capture",
            "text": f"*X/Twitter capture* — last harvest "
                    f"{'never' if a is None else f'{a:.0f}h ago'}",
            "how": "start a Claude session and ask for the X capture "
                   "(one browser session only, or it throttles)",
        })

    # 3. Graph edges the digester proposed but cannot adopt on its own —
    #    structure changes are deliberately human-gated (docs LEARNING.md §2).
    try:
        pl = (ROOT / "data" / "proposal_log.jsonl").read_text().splitlines()
        openish = [l for l in pl if '"status": "open"' in l or '"reviewed"' not in l]
        if len(openish) >= 10:
            asks.append({
                "key": "graph_edges",
                "text": f"*{len(openish)} proposed graph edges* awaiting review",
                "how": "ask for a batch review of data/proposal_log.jsonl",
            })
    except OSError:
        pass

    # 4. Standing decisions — things I have flagged and cannot decide alone.
    #    Read from a file so they can be added or cleared without a code change.
    try:
        for d in json.loads((ROOT / "data" / "open_decisions.json").read_text()):
            if not d.get("resolved"):
                asks.append({"key": f"decision:{d['id']}",
                             "text": f"*{d['title']}*", "how": d.get("how", "your call")})
    except (OSError, json.JSONDecodeError):
        pass

    return asks


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true", help="print only, never send")
    args = ap.parse_args()

    asks = collect()
    if args.show:
        for a in asks:
            print(f"  [{a['key']}] {a['text']}\n      -> {a['how']}")
        print(f"({len(asks)} open)" if asks else "nothing needs you")
        return 0

    state = _load()
    now = time.time()
    due = []
    for a in asks:
        rec = state.get(a["key"], {})
        sent = int(rec.get("sent", 0))
        wait = BACKOFF_H[min(sent, len(BACKOFF_H) - 1)] * 3600
        if now - float(rec.get("at", 0)) >= wait:
            due.append(a)

    # forget items that are no longer open, so a returning ask starts fresh
    live = {a["key"] for a in asks}
    state = {k: v for k, v in state.items() if k in live}

    if not due:
        print(f"{len(asks)} open, none due for a nudge")
        _save(state)
        return 0

    from ai_investing.alerts import get_notifier
    from ai_investing.config import Settings
    body = "\n\n".join(f"• {a['text']}\n  _{a['how']}_" for a in due)
    ok = get_notifier(Settings()).send(
        f"🙋 *{len(due)} thing{'s' if len(due) > 1 else ''} need you*\n\n{body}")
    if ok:
        for a in due:
            rec = state.get(a["key"], {})
            state[a["key"]] = {"at": now, "sent": int(rec.get("sent", 0)) + 1}
    _save(state)
    print(f"pinged {len(due)} of {len(asks)} open asks" if ok else "send FAILED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
