"""Per-node emotion field: WHERE the crowd is scared or greedy, not just whether.

The regime's fear/greed dials are global scalars — panic about NVDA and panic
about oil melt into one number, which makes localized capitulation (the most
tradeable emotional state there is) invisible. This module keeps a fear charge
and a greed charge PER NODE, fed by each cycle's digested events:

    charge += intensity x credibility_weight x emotion_weight   (saturating)

and decaying with a ~48h half-life like the activation field. Noise events
still feed the GREED channel at half weight — hype is noise to the causal
field but it is exactly the signal here (someone is spending money to excite
the crowd about this node). Fear from noise is ignored (fear-mongering spam
must not manufacture a capitulation reading).

Consumers: the contrarian composer (buy panic in clean names, fade euphoric
froth) and the dashboard. An asset inherits emotion from its themes at 0.7
weight — panic tagged on `china_tech` IS panic about Tencent.
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone

HALF_LIFE_HOURS = 48.0
MIN_CHARGE = 0.02
THEME_INHERIT = 0.7

# emotion -> (channel, weight): how strongly each tagged emotion charges a channel
EMOTION_CHANNEL = {
    "fear": ("fear", 1.0), "panic": ("fear", 1.3), "anger": ("fear", 0.7),
    "greed": ("greed", 1.0), "euphoria": ("greed", 1.3), "hope": ("greed", 0.6),
    "complacency": ("greed", 0.5),
}


def _path(settings) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(settings.brain.db_path)),
                        "emotion_field.json")


def _load(settings) -> dict:
    try:
        with open(_path(settings)) as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {"nodes": {}, "updated": ""}


def _decay(state: dict, now: datetime) -> None:
    if state.get("updated"):
        try:
            hours = max(0.0, (now - datetime.fromisoformat(state["updated"])).total_seconds()
                        / 3600.0)
        except ValueError:
            hours = 0.0
        k = math.pow(0.5, hours / HALF_LIFE_HOURS)
        out = {}
        for nid, ch in state.get("nodes", {}).items():
            fear, greed = ch.get("fear", 0.0) * k, ch.get("greed", 0.0) * k
            if max(fear, greed) >= MIN_CHARGE:
                out[nid] = {"fear": round(fear, 4), "greed": round(greed, 4)}
        state["nodes"] = out
    state["updated"] = now.isoformat()


def update(settings, events: list[dict], now: datetime | None = None) -> dict[str, dict]:
    """Decay the field, absorb this cycle's events, persist. Returns node emotions."""
    now = now or datetime.now(timezone.utc)
    state = _load(settings)
    _decay(state, now)
    nodes = state["nodes"]
    for ev in events or []:
        channel_w = EMOTION_CHANNEL.get(ev.get("emotion", ""))
        if not channel_w:
            continue
        channel, w = channel_w
        if ev.get("is_noise") and channel == "fear":
            continue                      # fear-mongering spam can't fake capitulation
        noise_damp = 0.5 if ev.get("is_noise") else 1.0
        cred = float(ev.get("credibility", 0.5) or 0.5)
        charge = (float(ev.get("emotion_intensity", 0.0) or 0.0) * w
                  * (0.4 + 0.6 * cred) * noise_damp)
        if charge < MIN_CHARGE:
            continue
        for nid in ev.get("nodes", []):
            ch = nodes.setdefault(nid, {"fear": 0.0, "greed": 0.0})
            ch[channel] = round(min(1.0, ch[channel] + charge * (1.0 - ch[channel])), 4)
    try:
        os.makedirs(os.path.dirname(_path(settings)), exist_ok=True)
        with open(_path(settings), "w") as fh:
            json.dump(state, fh, indent=1)
    except OSError:
        pass
    return nodes


def node_emotions(settings, now: datetime | None = None) -> dict[str, dict]:
    """Read-only view with decay applied (not persisted)."""
    state = _load(settings)
    _decay(state, now or datetime.now(timezone.utc))
    return state["nodes"]


def membership_parents(graph) -> dict[str, list[str]]:
    """{asset_id: [theme ids]} — build once per pass, not once per asset."""
    parents: dict[str, list[str]] = {}
    for e in graph.edges:
        if e.type == "member_of":
            parents.setdefault(e.src, []).append(e.dst)
    return parents


def asset_emotion(graph, emotions: dict[str, dict], asset_id: str,
                  parents: dict[str, list[str]] | None = None) -> dict[str, float]:
    """An asset's effective emotion: its own charge, or its themes' at 0.7 —
    panic tagged on the sector IS panic about the member. Pass a precomputed
    `parents` map (membership_parents) when calling in a loop."""
    own = emotions.get(asset_id, {})
    fear, greed = own.get("fear", 0.0), own.get("greed", 0.0)
    if parents is None:
        parents = membership_parents(graph)
    for pid in parents.get(asset_id, []):
        parent = emotions.get(pid, {})
        fear = max(fear, THEME_INHERIT * parent.get("fear", 0.0))
        greed = max(greed, THEME_INHERIT * parent.get("greed", 0.0))
    return {"fear": round(fear, 4), "greed": round(greed, 4)}
