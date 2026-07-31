"""Learned source reliability: every feed earns (or loses) its trust with evidence.

The static SOURCE_TRUST table in events.py is a prior, and priors rot. This
module closes the loop the same way the scorecard closes it for symbols and
calibration closes it for edges:

  1. SCORE — once an event is ~5 days old, replay its impulse through the graph,
     take the strongest asset impacts it predicted, and compare their direction
     against the realized move (price_history). Frozen into event_outcomes.
  2. LEARN — aggregate outcomes per source into a shrunk hit-rate
     (hits + 5·0.5)/(n + 5), mapped to a learned trust in [0.25, 0.95]. A feed
     whose stories keep pointing the right way earns weight; one that keeps
     crying wolf loses it. events.source_trust() blends 50/50 with the static
     prior once a source has >= MIN_N decided outcomes.
  3. DOOM DISCOUNT — fear sells, so fear stories are systematically oversupplied.
     Per source, compare the realized |move| after its fear/panic events against
     the realized |move| after everyone's. A source whose doom never moves
     markets gets its fear-event impulses damped (fear-monger discount, applied
     at extraction) — its cheerful stories are unaffected.

Everything runs from data already collected; no new API calls.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone

HORIZON_DAYS = 5
DEADBAND = 0.003
MIN_N = 10                 # decided outcomes before learned trust is blended in
TOP_ASSETS = 2             # strongest predicted assets scored per event
BATCH = 200
DOOM_MIN_N = 6
SHRINK = 5                 # pseudo-observations at 50% pulling small samples to neutral

_SCHEMA = """
CREATE TABLE IF NOT EXISTS event_outcomes (
  event_id INTEGER NOT NULL, symbol TEXT NOT NULL,
  impact_sign INTEGER NOT NULL, realized_ret REAL,
  hit INTEGER,                       -- 1 hit / 0 miss / NULL deadband
  emotion TEXT, source TEXT, polarity REAL, is_noise INTEGER,
  scored_at TEXT NOT NULL,
  PRIMARY KEY (event_id, symbol));
"""


def _trust_path(settings) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(settings.brain.db_path)),
                        "learned_trust.json")


def _price_at(conn, symbol: str, date: str, at_or_after: bool = True) -> float | None:
    q = ("SELECT price FROM price_history WHERE symbol=? AND date>=? ORDER BY date ASC LIMIT 1"
         if at_or_after else
         "SELECT price FROM price_history WHERE symbol=? AND date<=? ORDER BY date DESC LIMIT 1")
    row = conn.execute(q, (symbol, date)).fetchone()
    return row[0] if row else None


def score_events(settings, graph, horizon: int = HORIZON_DAYS, batch: int = BATCH) -> int:
    """Score every unscored event at least `horizon` days old; returns rows added.
    Noise events are scored too — knowing whether ignoring them was RIGHT is
    how the noise filter itself stays honest."""
    try:
        conn = sqlite3.connect(settings.brain.db_path)
        conn.executescript(_SCHEMA)
    except sqlite3.Error:
        return 0
    cutoff = (datetime.now(timezone.utc) - timedelta(days=horizon)).isoformat()
    rows = conn.execute(
        "SELECT id, ts, source, nodes, polarity, magnitude, is_noise, emotion, impulse "
        "FROM events WHERE ts <= ? AND id NOT IN (SELECT DISTINCT event_id FROM event_outcomes) "
        "ORDER BY id LIMIT ?", (cutoff, batch)).fetchall()
    added = 0
    now = datetime.now(timezone.utc).isoformat()
    for eid, ts, source, nodes_json, polarity, magnitude, is_noise, emotion, impulse in rows:
        try:
            nodes = json.loads(nodes_json or "[]")
        except json.JSONDecodeError:
            nodes = []
        pulse = impulse if impulse else (polarity or 0.0) * (magnitude or 0.0) * 0.5
        placeholder = False
        if not nodes or abs(pulse) < 0.02:
            placeholder = True             # unscoreable — record so it's not retried
        scored_syms: list[tuple[str, int, float | None, int | None]] = []
        if not placeholder:
            impacts, _, _ = graph.propagate({n: pulse for n in nodes if n in graph.nodes})
            assets = sorted(graph.asset_impacts(impacts).items(),
                            key=lambda kv: -abs(kv[1]["impact"]))[:TOP_ASSETS]
            d0 = str(ts)[:10]
            d1 = (datetime.fromisoformat(d0) + timedelta(days=horizon)).date().isoformat()
            for sym, row in assets:
                p0 = _price_at(conn, sym, d0)
                p1 = _price_at(conn, sym, d1)
                if not p0 or not p1:
                    continue
                ret = p1 / p0 - 1.0
                sign = 1 if row["impact"] > 0 else -1
                hit = None
                if abs(ret) >= DEADBAND:
                    hit = 1 if sign * ret > 0 else 0
                scored_syms.append((sym, sign, round(ret, 5), hit))
        if not scored_syms:
            scored_syms = [("_NONE", 0, None, None)]   # placeholder row = done
        for sym, sign, ret, hit in scored_syms:
            conn.execute("INSERT OR IGNORE INTO event_outcomes VALUES(?,?,?,?,?,?,?,?,?,?)",
                         (eid, sym, sign, ret, hit, emotion or "", source or "",
                          polarity or 0.0, int(bool(is_noise)), now))
            added += 1
    conn.commit()
    conn.close()
    return added


def learn(settings) -> dict:
    """Aggregate outcomes into per-source learned trust + doom discount; persist."""
    try:
        conn = sqlite3.connect(settings.brain.db_path)
        conn.executescript(_SCHEMA)
        rows = conn.execute(
            "SELECT source, hit, realized_ret, emotion, polarity, is_noise "
            "FROM event_outcomes WHERE symbol != '_NONE'").fetchall()
        conn.close()
    except sqlite3.Error:
        return {}
    per: dict[str, dict] = {}
    all_moves: list[float] = []
    for source, hit, ret, emotion, polarity, is_noise in rows:
        s = per.setdefault(source or "?", {"n": 0, "hits": 0, "doom_moves": []})
        if hit is not None and not is_noise:
            s["n"] += 1
            s["hits"] += hit
        if ret is not None:
            all_moves.append(abs(ret))
            if emotion in ("fear", "panic") and (polarity or 0.0) < 0:
                s["doom_moves"].append(abs(ret))
    overall = (sum(all_moves) / len(all_moves)) if all_moves else 0.0
    out: dict[str, dict] = {}
    for source, s in per.items():
        rate = (s["hits"] + SHRINK * 0.5) / (s["n"] + SHRINK)
        entry = {"n": s["n"], "hit_rate": round(s["hits"] / s["n"], 3) if s["n"] else None,
                 "trust": round(0.25 + 0.7 * rate, 3)}
        if len(s["doom_moves"]) >= DOOM_MIN_N and overall > 1e-9:
            ratio = (sum(s["doom_moves"]) / len(s["doom_moves"])) / overall
            entry["doom_discount"] = round(max(0.5, min(1.0, ratio)), 3)
        out[source] = entry
    try:
        with open(_trust_path(settings), "w") as fh:
            json.dump({"generated": datetime.now(timezone.utc).isoformat(),
                       "sources": out}, fh, indent=1)
    except OSError:
        pass
    return out


def learned_map(settings) -> dict[str, dict]:
    """{source: {n, trust, doom_discount?}} — {} until learning has data."""
    try:
        with open(_trust_path(settings)) as fh:
            return json.load(fh).get("sources", {})
    except (OSError, json.JSONDecodeError):
        return {}
