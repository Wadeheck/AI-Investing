#!/usr/bin/env python3
"""Daily, automatic check of the §4B cues that are pure arithmetic.

WHY THIS EXISTS. `docs/status/STATE_OF_THE_SYSTEM.md` §4B was added because
*"needs more data" by itself is not a plan* — every open item got a number, a
date, or an event to watch for. That was the right idea and it has one flaw:
almost every cue is checked by a human remembering to run a script.

Measured on 2026-08-21, in BRAIN_REVIEW_2026-08-21:

  - the LLM-edge cue ("revisit when llm edges cross 328, ~2026-09-19") had
    already fired — 354 edges, at 88.5/week rather than the 35/week the cue
    was dated from — and nothing surfaced it;
  - the sleeve's completed-cycle count had moved and nobody had counted;
  - the ONE cue that has never been missed is the adviser gate, and it is the
    one cue that watches itself (`adviser_gate_check.py`).

So: this is that pattern, applied to the cues that need no judgement to
EVALUATE — only to act on. It never decides anything and never trades. It
computes each threshold, persists the answers, and notifies on Telegram only
when a cue CHANGES state, so it is silent on the many days nothing has moved
and says something on the day one fires.

Judgement-call cues are deliberately NOT here (whether to place the first
non-USD order, whether to relax a materiality bar). A cue that needs a person
to evaluate is not made better by a cron job guessing.
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))

from ai_investing.brain.graph import KnowledgeGraph  # noqa: E402
from ai_investing.config import Settings  # noqa: E402

STATE = "cue_state.json"


def _llm_edges(settings) -> dict:
    """§4B: 'LLM-proposed edges cross 328 (half the 656 curated edges).'

    Reported against the CURRENT curated count rather than the 656 the cue was
    written against — the point of the cue is the ratio, and hard-coding a
    stale denominator is how a cue quietly stops meaning what it said.
    """
    g = KnowledgeGraph.load(settings.brain.graph_path)
    llm = [e for e in g.edges if e.provenance == "llm"]
    curated = len(g.edges) - len(llm)
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    rate = g.proposal_rate(week_ago)
    return {
        "llm_edges": len(llm), "curated_edges": curated,
        "half_curated": curated // 2, "per_week": rate,
        "unreviewed": sum(1 for e in llm if not e.reviewed_at),
        "fired": len(llm) >= curated // 2,
        "note": f"{len(llm)} llm vs {curated} curated ({rate}/wk)",
    }


def _sleeve_cycles(settings) -> dict:
    """§4B: 'revisit the sleeve's 32:1 risk/reward at the first 10% stop-out on
    any leg, or at 15 completed 2-day cycles.'"""
    path = Path(settings.state_path).parent / "event_journal.jsonl"
    clock, stops, realized = 0, 0, 0.0
    try:
        for line in path.read_text().splitlines():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("event") != "sell":
                continue
            reason = str(r.get("reason") or "")
            clock += reason.startswith("clock")
            stops += "stop" in reason
            if isinstance(r.get("pnl"), (int, float)):
                realized += r["pnl"]
    except OSError:
        pass
    return {"clock_exits": clock, "stop_outs": stops,
            "realized_pnl": round(realized, 2),
            "fired": stops > 0 or clock >= 45,     # 15 cycles x 3 legs
            "note": f"{clock} clock exits, {stops} stop-outs, "
                    f"${realized:,.2f} realized"}


def _issuance_days(settings) -> dict:
    """§4B: 'per-symbol reliability weights are provisional until 20-30 distinct
    issuance days.' Counted in the deduplicated unit (brain/scorecard.py)."""
    import sqlite3
    try:
        con = sqlite3.connect(f"file:{settings.brain.db_path}?mode=ro", uri=True)
        cols = {r[1] for r in con.execute("PRAGMA table_info(advice_outcomes)")}
        where = " where is_primary=1" if "is_primary" in cols else ""
        days, obs = con.execute(
            "select count(distinct date(ts_issued,'+8 hours')), count(*) "
            f"from advice_outcomes{where}").fetchone()
        con.close()
    except sqlite3.Error as exc:
        # Say WHAT could not be read. "unreadable" is how §4.6 hid an
        # OperationalError for 195 advice lists.
        return {"days": 0, "observations": 0, "fired": False,
                "note": f"advice_outcomes unreadable: {exc}"}
    return {"days": days or 0, "observations": obs or 0,
            "fired": (days or 0) >= 20,
            "note": f"{days} distinct issuance days, {obs} observations"}


def _calibration(settings) -> dict:
    """§4B: the calibrator can issue no verdict until an edge reaches MIN_N.
    0 of 643 as of 2026-08-21 — the cue is the FIRST verdict of either sign."""
    path = Path(settings.brain.db_path).parent / "edge_calibration.json"
    try:
        rep = json.loads(path.read_text())
        s = rep.get("summary") or {}
    except (OSError, json.JSONDecodeError):
        return {"fired": False, "note": "no calibration report yet"}
    decided = int(s.get("supported", 0)) + int(s.get("contradicted", 0))
    return {"supported": s.get("supported", 0),
            "contradicted": s.get("contradicted", 0),
            "unproven": s.get("unproven", 0), "gain": rep.get("gain"),
            "fired": decided > 0,
            "note": f"{decided} decided of {s.get('scored', 0)} scored "
                    f"(gain={rep.get('gain')})"}


CUES = {
    "llm_edges_vs_curated": _llm_edges,
    "sleeve_risk_reward": _sleeve_cycles,
    "reliability_issuance_days": _issuance_days,
    "edge_calibration_first_verdict": _calibration,
}


def main() -> int:
    settings = Settings()
    state_path = Path(settings.state_path).parent / STATE
    try:
        previous = json.loads(state_path.read_text()).get("cues", {})
    except (OSError, json.JSONDecodeError):
        previous = {}

    cues, newly_fired = {}, []
    for name, fn in CUES.items():
        try:
            cues[name] = fn(settings)
        except Exception as exc:            # one broken cue must not hide the rest
            cues[name] = {"fired": False, "note": f"check failed: {exc}"}
        was = bool((previous.get(name) or {}).get("fired"))
        if cues[name].get("fired") and not was:
            newly_fired.append(name)
        print(f"  {'FIRED ' if cues[name].get('fired') else '  --  '} "
              f"{name:<32} {cues[name]['note']}", flush=True)

    out = {"checked_at": datetime.now(timezone.utc).isoformat(), "cues": cues}
    try:
        state_path.write_text(json.dumps(out, indent=1))
    except OSError:
        pass

    if newly_fired:
        lines = "\n".join(f"• *{n}* — {cues[n]['note']}" for n in newly_fired)
        try:
            from ai_investing.alerts import get_notifier
            get_notifier(settings).send(
                f"📋 *§4B cue fired*\n{lines}\n\n"
                "This is a prompt to make a decision, not a decision. See "
                "docs/status/STATE_OF_THE_SYSTEM.md §4B.")
        except Exception as exc:
            print(f"(notify failed: {exc})", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
