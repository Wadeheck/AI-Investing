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
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))

STATE = ROOT / "data" / "needs_you_state.json"
# Ask again after this long. Deliberately increasing: the longer something sits,
# the more likely leaving it IS the decision, and nagging harder is wrong.
BACKOFF_H = [2, 8, 24, 72]
# The proposal rate DIGESTION_SPEC §A10 tells the digester to aim for, and the
# rate its "damped by the cap, not blocked by a queue" reasoning assumes.
SPEC_EDGES_PER_WEEK = 1


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

    # 2. X capture. No longer a standing human task — `3e0c77a` automated it as a
    #    headless harvest on a jittered 4h timer — but it is still the one channel
    #    that cannot fully self-heal: it runs on session cookies, and only a real
    #    browser can mint new ones when they expire. So the ask survives, with the
    #    action inverted. It is now a REPORT OF FAILURE ("the timer stopped
    #    delivering") rather than a reminder of a chore, and the threshold stays at
    #    26h rather than tightening to the 4h cadence, because a couple of missed
    #    runs is X throttling us and is not worth a human's attention; a full day of
    #    silence means the cookies are dead.
    a = _age_h(ROOT / "data" / "news_archive_x.jsonl")
    if a is None or a > 26:
        asks.append({
            "key": "x_capture",
            "text": f"*X/Twitter capture has stalled* — last harvest "
                    f"{'never' if a is None else f'{a:.0f}h ago'}, "
                    f"despite the 4h timer",
            "how": "session cookies have almost certainly expired: refresh "
                   "`data/x_cookies.json` from a real logged-in browser "
                   "(`x_login.py` cannot — X rejects headless logins)",
        })

    # 3. Wiring the brain added to itself and nothing can grade.
    #
    #    This asked the wrong question for its whole life. It counted lines in
    #    data/proposal_log.jsonl and called them graph edges — but that file is
    #    the append-only TRADE audit (`execution/approvals.py`), written once per
    #    proposal with `status: "pending"` frozen at write time and no `reviewed`
    #    key, ever. So the filter matched every line, the count was "trades ever
    #    proposed" and could only grow, and the suggested action (review that
    #    file) was impossible: there is nothing in it to review. The first digest
    #    on 2026-08-03 announced "23 proposed graph edges" — exactly that day's
    #    trade count. A plausible number is the easiest kind of wrong to keep.
    #
    #    The real population is llm-provenance edges in the knowledge graph:
    #    applied automatically at capped confidence per DIGESTION_SPEC §A10,
    #    unreachable by the L0 calibrator (which scores seed edges only, and
    #    could not score these anyway — none terminates on a tradable symbol),
    #    and therefore controlled by nothing except that cap and a human.
    #
    #    Report the RATE alongside the backlog. A backlog says work is waiting;
    #    the rate says whether §A10's "expect <=1 per week" — the assumption its
    #    cap-not-queue argument rests on — is still true. That is the number
    #    worth waking someone for, and nobody was measuring it.
    #
    #    Deliberately NOT included: the offline proposals in data/digest_v2/.
    #    Those were never applied to the graph, so they steer nothing while they
    #    wait, and nagging about inert items is the mistake this file already
    #    made once with dead trade proposals (see §1).
    try:
        from ai_investing.brain.graph import KnowledgeGraph      # engine/ is on
                                                                 # sys.path already
        from ai_investing.config import Settings

        graph_path = Settings().brain.graph_path
        # KnowledgeGraph.load SEEDS a fresh graph when the file is absent. That is
        # right for the engine and wrong here: a mistyped BRAIN_GRAPH_PATH would
        # have this status check write a brand-new graph and then truthfully
        # report zero edges pending — a clean bill of health manufactured by the
        # act of checking. A reporting path must never create what it measures.
        if not os.path.exists(graph_path):
            raise FileNotFoundError(f"no graph at {graph_path}")
        graph = KnowledgeGraph.load(graph_path)
        pending = graph.pending_review()
        week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        rate = graph.proposal_rate(week_ago)
        # Two independent triggers, because they are different problems. A backlog
        # is work; a rate breach is the design premise failing, and that one is
        # worth saying even when the backlog is short.
        # Paths and node ids go in BACKTICKS, not bare. Telegram parses `_` as an
        # italic marker, so `us_gov_debt->credit_conditions` contributes three of
        # them; an odd count anywhere makes the Markdown unbalanced, and because
        # this digest is ONE message that costs every ask in it its formatting
        # (the notifier's plain-text retry saves the delivery, not the rendering —
        # see 262b437). A code span suppresses the parsing entirely.
        if len(pending) >= 10 or rate > SPEC_EDGES_PER_WEEK:
            note = (f" — *{rate} proposed this week* against a spec of "
                    f"<={SPEC_EDGES_PER_WEEK}/wk" if rate > SPEC_EDGES_PER_WEEK else "")
            asks.append({
                "key": "graph_edges",
                "text": f"*{len(pending)} self-added graph edges* awaiting review{note}",
                "how": "`python3 scripts/review_edges.py --stats` (then --show, "
                       "--keep/--reject); nothing else can grade these",
            })
        contested = graph.contested_rejections()
        if contested:
            top = contested[0]
            asks.append({
                "key": "graph_edges_contested",
                "text": f"*{len(contested)} rejected edge(s) the digester keeps "
                        f"re-proposing* — e.g. "
                        f"`{graph.pair_key(top['src'], top['dst'], top['type'])}` "
                        f"({top.get('suppressed', 0)}x)",
                "how": "`python3 scripts/review_edges.py --contested` — a rejection "
                       "argued with this often may be the one that was wrong",
            })
    except Exception as exc:
        # A broken check must not read as a clean one. §4.6 is the whole argument:
        # the scorecard raised OperationalError every cycle for weeks, the caller
        # swallowed it, and "no findings" was indistinguishable from "never ran".
        # So this degrades to an ask ABOUT ITSELF rather than to silence — and it
        # still cannot take the digest down with it, because the other asks here
        # are the ones with money attached.
        asks.append({
            "key": "graph_edges_broken",
            "text": f"*The graph-edge review check is broken* — {type(exc).__name__}: "
                    f"{str(exc)[:120]}",
            "how": "`python3 scripts/review_edges.py --stats` to see the real "
                   "error; until it runs, self-added wiring is unwatched",
        })

    # 4. Standing decisions — things I have flagged and cannot decide alone.
    #    Read from a file so they can be added or cleared without a code change.
    try:
        for d in json.loads((ROOT / "data" / "open_decisions.json").read_text()):
            if not d.get("resolved"):
                asks.append({"key": f"decision:{d['id']}",
                             "text": f"*{d['title']}*", "how": d.get("how", "your call")})
    except (OSError, json.JSONDecodeError):
        pass

    # 5. Foresight gap-scan: names the news keeps mentioning that the graph
    #    doesn't know. Built 2026-08 after Unitree Robotics' and CXMT's IPOs
    #    both sat undiscovered until a human noticed by hand — the deals
    #    pipeline's lists_on kind (brain/deals.py) now catches most future
    #    IPOs automatically, but only if the digester actually saw and framed
    #    the headline correctly. This is the backstop: a periodic sweep of the
    #    raw news archives, independent of the digester entirely, so a miss in
    #    one layer doesn't compound into a miss in both.
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        from graph_gap_scan import scan as gap_scan
        results, seen_rows = gap_scan(days=30, min_mentions=3, min_sources=2)
        if results:
            top = ", ".join(r["candidate"] for r in results[:3])
            more = f" (+{len(results) - 3} more)" if len(results) > 3 else ""
            asks.append({
                "key": "graph_gap_scan",
                "text": f"*{len(results)} name(s) the news keeps mentioning "
                        f"aren't in the graph*: {top}{more}",
                "how": "`python3 scripts/graph_gap_scan.py` for the full list "
                       "with sources; add real ones to brain/seed.py",
            })
    except Exception as exc:
        asks.append({
            "key": "graph_gap_scan_broken",
            "text": f"*The graph gap-scan is broken* — {type(exc).__name__}: "
                    f"{str(exc)[:120]}",
            "how": "`python3 scripts/graph_gap_scan.py` to see the real error; "
                   "until it runs, new-company detection is unwatched",
        })

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
