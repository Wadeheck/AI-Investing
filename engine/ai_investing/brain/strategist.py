"""The strategist: a persistent 6-month strategy, challenged daily.

Once per (Singapore) day, after the news is digested, this module sends the
user a plain-language overview:

  1. What caught the brain's attention — the nodes rippling hardest, tagged
     bull / bear / steady.
  2. The standing 6-month strategy — a handful of theses grounded in the
     macro field, valuations (weekly fundamentals), and financial health.
  3. The assumptions each thesis rests on.

The strategy is the OPPOSITE of reactive: it lives in data/strategy.json and
survives across days. Each day the LLM is asked to CHALLENGE it against fresh
evidence — and stability is enforced in code, not trusted to the model:

  - a thesis judged "kept" retains its previous wording verbatim (the model
    cannot quietly reword its way into a new strategy);
  - every revision/drop/new is logged with its reason and date;
  - the message shows the unchanged-streak and the 30-day revision count, so
    flip-flopping is visible evidence of weakness.

After the overview, the day's top-10 idea list (the adviser) is sent as a
separate message.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

MAX_THESES = 5


def _today_sgt() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=8)).date().isoformat()


def _path(settings) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(settings.state_path)),
                        "strategy.json")


def load_strategy(settings) -> dict:
    try:
        with open(_path(settings)) as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {"theses": [], "market_outlook": "", "revisions": [],
                "last_overview": "", "created": _today_sgt()}


def save_strategy(settings, strat: dict) -> None:
    with open(_path(settings), "w") as fh:
        json.dump(strat, fh, indent=1)


# ---------------------------------------------------------------- evidence --
def _labels(settings) -> dict[str, str]:
    """symbol -> label and node_id -> label, from the knowledge graph file."""
    out: dict[str, str] = {}
    try:
        path = os.path.join(os.path.dirname(os.path.abspath(settings.state_path)),
                            "knowledge_graph.json")
        with open(path) as fh:
            for n in json.load(fh).get("nodes", []):
                out[n["id"]] = n.get("label", n["id"])
                if n.get("symbol"):
                    out[n["symbol"]] = n.get("label", n["symbol"])
    except (OSError, json.JSONDecodeError):
        pass
    return out


def top_ripples(brain_state: dict, labels: dict[str, str], k: int = 7) -> list[dict]:
    """The nodes rippling hardest right now, tagged bull/bear/steady."""
    acts = brain_state.get("activations") or {}
    rows = sorted(acts.items(), key=lambda kv: -abs(kv[1]))[:k]
    out = []
    for nid, v in rows:
        if abs(v) < 0.05:
            continue
        tag = "bull" if v > 0.15 else ("bear" if v < -0.15 else "steady")
        out.append({"node": nid, "label": labels.get(nid, nid), "value": round(v, 2), "tag": tag})
    return out


def _gather_evidence(settings, brain_state: dict, labels: dict[str, str]) -> dict:
    reg = brain_state.get("regime") or {}
    events = [e.get("summary", "")[:140] for e in (brain_state.get("events") or [])
              if not e.get("is_noise")][:8]
    ev = {
        "top_ripples": top_ripples(brain_state, labels),
        "regime": (reg.get("labels") or {}),
        "geopolitical_tension": reg.get("geopolitical_tension"),
        "crowd_emotion": reg.get("emotion_label"),
        "todays_signal_events": events,
    }
    try:
        from ai_investing.data.fundamentals import get_fundamentals, notable_extremes
        fund = get_fundamentals(settings, settings.stock_watchlist)
        ev["valuations"] = notable_extremes(fund, labels)
    except Exception:
        ev["valuations"] = {}
    try:
        from ai_investing.data import macro as macro_mod
        snap = macro_mod.get_snapshot(settings) or {}
        ev["macro_readings"] = {k: v for k, v in list(snap.items())[:12]
                                if isinstance(v, (int, float, str))}
    except Exception:
        pass
    try:
        from ai_investing.brain.bubble import bubble_scores
        ev["bubble_watch"] = bubble_scores(settings).get("clusters", [])
    except Exception:
        pass
    return ev


# --------------------------------------------------------------- challenge --
_PROMPT = """You are the long-horizon strategist of a trading system. Your job today is to
CHALLENGE the standing 6-month strategy against fresh evidence — NOT to rewrite it.

RULES (these are the point of your existence):
- A strategy that changes with the day's headlines is worthless. Headlines alone
  are NEVER a reason to revise. Revise a thesis ONLY if fundamental evidence
  (macro readings, valuations, financial health, a structural break) contradicts it.
- Default verdict is "kept". Be honest when evidence weakens a thesis, but weakening
  is not breaking.
- Shorting overvalued/bubble names is a valid thesis when valuations support it.
- Max {max_theses} theses. Plain language a beginner understands; no jargon.

STANDING STRATEGY (age: {age} days, unchanged for {streak} days):
{prev}

TODAY'S EVIDENCE:
{evidence}

TRADABLE SYMBOLS (pick thesis symbols ONLY from these):
{universe}

Return ONLY JSON:
{{"market_outlook": "2-3 plain sentences on the next 6 months",
  "theses": [
    {{"id": "keep the same id for existing theses, short-slug for new",
      "title": "short name",
      "stance": "long|short|avoid",
      "verdict": "kept|revised|new|dropped",
      "reason": "required unless kept: the FUNDAMENTAL evidence forcing the change",
      "thesis": "2-3 sentences: the idea and what grounds it",
      "assumptions": "1-2 sentences starting 'This assumes'",
      "symbols": ["1-3 tickers that best express this thesis"]}}
  ]}}"""


def challenge_strategy(settings, strat: dict, evidence: dict, llm=None) -> dict:
    """One daily challenge round. Stability is enforced HERE, not by the model."""
    today = _today_sgt()
    prev_theses = {t["id"]: t for t in strat.get("theses", [])}
    age = ((datetime.fromisoformat(today) -
            datetime.fromisoformat(strat.get("created") or today)).days)
    streak = strat.get("days_unchanged", 0)

    if llm is None:
        def llm(prompt):
            from ai_investing.data.news import _call_llm, llm_ready
            if not llm_ready(settings):
                return None
            return _call_llm(prompt, settings, max_tokens=1800, tier="smart", json_mode=True)

    prev_view = [{k: t.get(k) for k in ("id", "title", "stance", "thesis", "assumptions", "symbols")}
                 for t in strat.get("theses", [])] or "none yet — draft the initial strategy"
    labels = _labels(settings)
    universe = ", ".join(f"{s} ({labels.get(s, s)})"
                         for s in settings.stock_watchlist + settings.crypto_watchlist)
    out = llm(_PROMPT.format(max_theses=MAX_THESES, age=age, streak=streak,
                             prev=json.dumps(prev_view, indent=1),
                             evidence=json.dumps(evidence, indent=1),
                             universe=universe))
    if not out:
        strat["challenge_note"] = "challenge skipped — model unreachable; strategy stands"
        return strat
    try:
        d = json.loads(out[out.index("{"):out.rindex("}") + 1])
        proposed = d.get("theses") or []
        assert isinstance(proposed, list)
    except (ValueError, AssertionError):
        strat["challenge_note"] = "challenge skipped — unreadable model answer; strategy stands"
        return strat

    theses, changes = [], []
    seen: set[str] = set()
    for p in proposed[: MAX_THESES + 2]:
        pid = str(p.get("id", ""))[:40] or f"t{len(theses)}"
        verdict = p.get("verdict", "kept")
        if pid in seen:
            continue
        if verdict == "dropped":
            if pid in prev_theses:
                changes.append({"date": today, "id": pid, "kind": "dropped",
                                "reason": str(p.get("reason", ""))[:200]})
            continue
        if pid in prev_theses and verdict != "revised":
            # KEPT: previous wording survives verbatim — no silent rewrites
            t = dict(prev_theses[pid])
        else:
            valid = set(settings.stock_watchlist) | set(settings.crypto_watchlist)
            t = {"id": pid, "title": str(p.get("title", pid))[:80],
                 "stance": p.get("stance", "long"),
                 "thesis": str(p.get("thesis", ""))[:500],
                 "assumptions": str(p.get("assumptions", ""))[:300],
                 "symbols": [s for s in (p.get("symbols") or []) if s in valid][:3],
                 "born": prev_theses.get(pid, {}).get("born", today)}
            if pid in prev_theses:
                changes.append({"date": today, "id": pid, "kind": "revised",
                                "reason": str(p.get("reason", ""))[:200]})
            elif prev_theses:      # genuinely new (not part of the bootstrap draft)
                changes.append({"date": today, "id": pid, "kind": "new",
                                "reason": str(p.get("reason", ""))[:200]})
        t["last_challenged"] = today
        theses.append(t)
        seen.add(pid)
        if len(theses) >= MAX_THESES:
            break
    # anything the model silently omitted counts as dropped-without-reason: keep it
    for pid, t in prev_theses.items():
        if pid not in seen and len(theses) < MAX_THESES:
            theses.append(dict(t))
            seen.add(pid)

    strat["theses"] = theses
    strat["market_outlook"] = str(d.get("market_outlook", strat.get("market_outlook", "")))[:600]
    strat["revisions"] = (strat.get("revisions", []) + changes)[-60:]
    strat["days_unchanged"] = 0 if (changes or not prev_theses) else streak + 1
    strat["challenge_note"] = (
        "; ".join(f"{c['kind']} '{c['id']}': {c['reason'] or 'no reason given'}" for c in changes)
        if changes else f"all {len(theses)} theses challenged and held")
    if not strat.get("created"):
        strat["created"] = today
    return strat


# ----------------------------------------------------------------- message --
_TAG_EMOJI = {"bull": "🐂", "bear": "🐻", "steady": "➖"}
_STANCE = {"long": "🟩 BUY/HOLD", "short": "🟥 BET AGAINST", "avoid": "⛔ STAY AWAY"}


def compose_overview(strat: dict, evidence: dict, briefing: str,
                     bubble: str = "", track: dict | None = None,
                     learn_notes: list[str] | None = None) -> str:
    day = _today_sgt()
    lines = [f"🌅 *Daily overview — {day}*"]
    if briefing:
        lines.append(f"\n{briefing}")
    ripples = evidence.get("top_ripples") or []
    if ripples:
        lines.append("\n*What caught my attention* (strongest ripples in my map):")
        for r in ripples:
            lines.append(f"{_TAG_EMOJI[r['tag']]} {r['label']} ({r['value']:+.2f})")
    if bubble:
        lines.append(f"\n{bubble}")
    if track and track.get("total"):
        lines.append(f"\n📊 *Track record* (30d, calls ≥5 days old): "
                     f"{track['hits']}/{track['total']} right ({track['hit_rate']:.0%})"
                     + (f" · best: {track['best']}" if track.get("best") else "")
                     + (f" · worst: {track['worst']}" if track.get("worst") else ""))
    if learn_notes:
        lines.append("🧪 *Learned today:* " + "; ".join(learn_notes[:4]))
    rev30 = [c for c in strat.get("revisions", [])
             if c.get("date", "") >= (datetime.fromisoformat(day) - timedelta(days=30)).date().isoformat()]
    lines.append(f"\n*My 6-month strategy* — unchanged for {strat.get('days_unchanged', 0)} day(s), "
                 f"{len(rev30)} change(s) in 30 days:")
    if strat.get("market_outlook"):
        lines.append(f"_{strat['market_outlook']}_")
    for i, t in enumerate(strat.get("theses", []), 1):
        syms = f" [{', '.join(t['symbols'])}]" if t.get("symbols") else ""
        lines.append(f"\n*{i}. {_STANCE.get(t.get('stance'), t.get('stance'))} — {t.get('title')}*{syms}\n"
                     f"{t.get('thesis')}\n"
                     f"🤔 {t.get('assumptions')}")
    lines.append(f"\n⚖️ *Today's challenge:* {strat.get('challenge_note', '')}")
    return "\n".join(lines)


def compose_ideas(advice: dict, labels: dict[str, str]) -> str:
    trades = (advice or {}).get("trades") or []
    if not trades:
        return "🎯 *Today's ideas:* nothing clears the bar — sitting still IS a position."
    lines = ["🎯 *Today's top ideas* (opinions, not orders — anything real still "
             "comes to you for approval):"]
    for t in trades[:10]:
        word = "Buy lean" if t["direction"] == "long" else "Avoid / bet against"
        name = t.get("label") or labels.get(t["symbol"], t["symbol"])
        lines.append(f"\n*{t['rank']}. {word}: {name}* ({t['symbol']})\n"
                     f"   _{t.get('chain', '')}_")
    return "\n".join(lines)


# ------------------------------------------------------------------- entry --
def maybe_daily_overview(settings, brain_state: dict, briefing: str,
                         notifier, llm=None, track: dict | None = None,
                         learn_notes: list[str] | None = None) -> bool:
    """Runs at most once per SGT day. Returns True if the overview was sent."""
    strat = load_strategy(settings)
    if strat.get("last_overview") == _today_sgt():
        return False
    labels = _labels(settings)
    evidence = _gather_evidence(settings, brain_state, labels)
    strat = challenge_strategy(settings, strat, evidence, llm=llm)
    strat["last_overview"] = _today_sgt()
    save_strategy(settings, strat)
    try:
        from ai_investing.brain.bubble import bubble_line, bubble_scores
        bub = bubble_line(bubble_scores(settings), labels)
    except Exception:
        bub = ""
    notifier.send(compose_overview(strat, evidence, briefing, bub, track, learn_notes))
    notifier.send(compose_ideas(brain_state.get("advice") or {}, labels))
    print(f"  [strategist] daily overview sent — {strat.get('challenge_note', '')}")
    return True
