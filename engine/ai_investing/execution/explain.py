"""Plain-language explanations for entry proposals.

The engine's internal rationale strings are jargon (E[r], momentum, θ·φ).
This module turns a proposed entry into something a beginner can act on:
what the company is, the insight that led here, the assumptions being
made, and the exit plan. The local LLM (free) writes the prose when it's
up; a deterministic template covers for it when it isn't.
"""
from __future__ import annotations

import json
import os
import re

# signal name -> (bullish phrasing, bearish phrasing)
SIGNAL_PLAIN = {
    "momentum": ("its price has been climbing steadily in recent weeks",
                 "its price has been falling steadily in recent weeks"),
    "mean_reversion": ("its price looks unusually cheap compared to its own recent range",
                       "its price looks stretched compared to its own recent range"),
    "sentiment": ("recent news coverage reads positive for it",
                  "recent news coverage reads negative for it"),
    "political_hype": ("the hype detector sees no pump behind the move",
                       "the hype detector suspects the move is hype, not substance"),
    "macro_linkage": ("world events are flowing in its favor through the knowledge graph",
                      "world events are flowing against it through the knowledge graph"),
}

_DRIVER_RE = re.compile(r"([a-z_]+)([+-]\d+(?:\.\d+)?)")


def _graph_lookup(settings, symbol: str) -> tuple[str, str]:
    """(label, market) for a symbol from the knowledge graph, else (symbol, '')."""
    try:
        path = os.path.join(os.path.dirname(os.path.abspath(settings.state_path)),
                            "knowledge_graph.json")
        with open(path) as fh:
            for n in json.load(fh).get("nodes", []):
                if n.get("symbol") == symbol:
                    return n.get("label", symbol), n.get("market", "")
    except (OSError, json.JSONDecodeError):
        pass
    return symbol, ""


def _drivers_plain(reason: str, buying: bool) -> list[str]:
    """Translate 'momentum+1.00, mean_reversion+0.53' into beginner sentences."""
    out = []
    for name, val in _DRIVER_RE.findall(reason or ""):
        if name not in SIGNAL_PLAIN:
            continue
        v = float(val)
        if abs(v) < 0.15:
            continue
        out.append((abs(v), SIGNAL_PLAIN[name][0 if v > 0 else 1]))
    out.sort(reverse=True)
    return [p for _, p in out[:3]]


def _advice_chain(settings, symbol: str) -> str:
    """The brain's causal chain for this symbol, if it made the advice list."""
    try:
        with open(settings.brain.advice_path) as fh:
            for t in json.load(fh).get("trades", []):
                if t.get("symbol") == symbol and "→" in t.get("chain", ""):
                    return t["chain"]
    except (OSError, json.JSONDecodeError, AttributeError):
        pass
    return ""


def _recent_signals(settings) -> list[str]:
    try:
        with open(settings.brain.state_path) as fh:
            evs = json.load(fh).get("events", [])
        return [e.get("summary", "")[:120] for e in evs if not e.get("is_noise")][:4]
    except (OSError, json.JSONDecodeError, AttributeError):
        return []


def _plan_text(side: str, stop_pct: float | None, take_pct: float | None) -> str:
    stop = f"{stop_pct:.0%}" if stop_pct else "8%"
    take = f"{take_pct:.0%}" if take_pct else "25%"
    action = "sells" if side == "buy" else "buys back"
    return (f"No fixed holding period — typically days to weeks, kept while the reasons hold. "
            f"It {action} automatically if the price moves ~{stop} against us (safety stop) "
            f"or ~{take} in our favor (take profit), and exits early if the signals reverse. "
            f"You can also close it any time by blocking the symbol.")


def explain_entry(settings, symbol: str, side: str, qty: float, price: float,
                  reason: str, equity: float,
                  stop_pct: float | None = None, take_pct: float | None = None) -> dict:
    """Beginner-readable {label, market, notional, pct, why, assumptions, plan}."""
    label, market = _graph_lookup(settings, symbol)
    notional = abs(qty) * price
    pct = notional / equity if equity > 0 else 0.0
    buying = side == "buy"
    drivers = _drivers_plain(reason, buying)
    chain = _advice_chain(settings, symbol)
    plan = _plan_text(side, stop_pct, take_pct)

    why, assumptions = _llm_prose(settings, label, market, symbol, side, drivers, chain,
                                  _recent_signals(settings))
    if not why:   # offline fallback: honest, template-built
        why = "; ".join(drivers) if drivers else "the engine's combined signals lean this way"
        if chain:
            why += f". The world-events brain adds: {chain}"
        why = why[0].upper() + why[1:] + "."
    if not assumptions:
        assumptions = ("The recent price trend and news picture stay roughly as they are; "
                       "no company-specific surprises.")
    return {"label": label, "market": market, "notional": round(notional, 2),
            "pct": round(pct, 4), "why": why[:600], "assumptions": assumptions[:400],
            "plan": plan}


def _llm_prose(settings, label, market, symbol, side, drivers, chain, events) -> tuple[str, str]:
    try:
        from ai_investing.data.news import _call_llm, llm_ready
        if not llm_ready(settings):
            return "", ""
        prompt = f"""You explain one proposed {'purchase' if side == 'buy' else 'short/sale'} to a complete beginner
(no finance background). Be concrete and honest. NEVER use these words: momentum,
mean reversion, macro, linkage, model, E[r], conviction, alpha, signal.

The company/asset: {label} ({symbol}{', ' + market if market else ''}).
What our system noticed (already in plain words): {'; '.join(drivers) or 'mixed but positive overall'}.
{'Cause-and-effect chain from world events: ' + chain if chain else ''}
{'Recent real news the system judged relevant: ' + ' | '.join(events) if events else ''}

Return ONLY a JSON object:
{{"what": "one short sentence: what this company/asset actually does",
  "why": "2-3 short sentences: the story of why our system wants this trade now",
  "assumptions": "1-2 short sentences starting with 'This bet assumes'"}}"""
        out = _call_llm(prompt, settings, max_tokens=400, tier="fast", json_mode=True)
        if not out:
            return "", ""
        d = json.loads(out[out.index("{"):out.rindex("}") + 1])
        what = str(d.get("what", "")).strip()
        why = str(d.get("why", "")).strip()
        if what:
            why = f"{what} {why}".strip()
        return why, str(d.get("assumptions", "")).strip()
    except Exception:
        return "", ""
