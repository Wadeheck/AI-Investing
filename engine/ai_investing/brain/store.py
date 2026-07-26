"""The brain's long-term memory: data/brain.db (SQLite, stdlib only).

The cost rule lives here: **digest once, remember forever.** Every article gets a
stable hash; only never-seen hashes reach an LLM. Digested events, per-cycle node
activations, and every advice list are kept locally so knowledge compounds on
this machine instead of being re-bought from an API.

Tables:
  articles     seen-hash dedupe (the LLM gate)         retention ~90 days
  events       digested structured events              retention ~1 year
  node_history field activation per node per cycle     kept (tiny)
  advice_log   every top-N list ever issued, frozen    kept (tiny)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone

_SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
  id TEXT PRIMARY KEY, title TEXT, source TEXT, published TEXT,
  first_seen TEXT, digested INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, summary TEXT, source TEXT,
  type TEXT, nodes TEXT, polarity REAL, magnitude REAL, credibility REAL,
  is_noise INTEGER, emotion TEXT, impulse REAL);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE TABLE IF NOT EXISTS node_history (
  ts TEXT, node TEXT, activation REAL);
CREATE INDEX IF NOT EXISTS idx_nh_node ON node_history(node, ts);
CREATE TABLE IF NOT EXISTS advice_log (
  ts TEXT, advice TEXT);
"""


def _norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", title.lower()).strip()


def article_id(title: str, source: str) -> str:
    return hashlib.sha1(f"{_norm_title(title)}|{source}".encode()).hexdigest()


class BrainStore:
    def __init__(self, path: str):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # -- the LLM gate ----------------------------------------------------------
    def filter_new(self, headlines: list[dict]) -> tuple[list[dict], int]:
        """Split headlines into to-digest vs already-digested. An article counts
        as 'seen' only once DIGESTED — registered-but-undigested rows (busy-cycle
        backlog, or a crash between register and digest) come back as fresh."""
        now = datetime.now(timezone.utc).isoformat()
        fresh, seen = [], 0
        done_ids = set()
        for h in headlines:
            aid = article_id(h.get("title", ""), h.get("source", ""))
            if aid in done_ids:
                continue          # duplicate story across feeds within this batch
            done_ids.add(aid)
            row = self.conn.execute("SELECT digested FROM articles WHERE id=?", (aid,)).fetchone()
            if row and row[0]:
                seen += 1
                continue
            if not row:
                self.conn.execute(
                    "INSERT OR IGNORE INTO articles(id,title,source,published,first_seen) "
                    "VALUES(?,?,?,?,?)",
                    (aid, h.get("title", ""), h.get("source", ""), h.get("published", ""), now))
            fresh.append({**h, "_article_id": aid})
        self.conn.commit()
        return fresh, seen

    def mark_digested(self, headlines: list[dict]) -> None:
        ids = [h.get("_article_id") for h in headlines if h.get("_article_id")]
        self.conn.executemany("UPDATE articles SET digested=1 WHERE id=?",
                              [(i,) for i in ids])
        self.conn.commit()

    # -- compounding knowledge ---------------------------------------------------
    def save_events(self, events: list[dict]) -> None:
        rows = [(e.get("ts", ""), e.get("summary", ""), e.get("source", ""),
                 e.get("type", ""), json.dumps(e.get("nodes", [])),
                 e.get("polarity", 0.0), e.get("magnitude", 0.0),
                 e.get("credibility", 0.0), int(bool(e.get("is_noise"))),
                 e.get("emotion", ""), e.get("impulse", 0.0)) for e in events]
        self.conn.executemany(
            "INSERT INTO events(ts,summary,source,type,nodes,polarity,magnitude,"
            "credibility,is_noise,emotion,impulse) VALUES(?,?,?,?,?,?,?,?,?,?,?)", rows)
        self.conn.commit()

    def recent_events(self, hours: float = 72.0, signal_only: bool = True) -> list[dict]:
        since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        q = "SELECT ts,summary,source,type,nodes,polarity,magnitude,credibility,is_noise,emotion,impulse " \
            "FROM events WHERE ts>=?" + (" AND is_noise=0" if signal_only else "") + " ORDER BY ts DESC"
        out = []
        for r in self.conn.execute(q, (since,)):
            out.append({"ts": r[0], "summary": r[1], "source": r[2], "type": r[3],
                        "nodes": json.loads(r[4] or "[]"), "polarity": r[5],
                        "magnitude": r[6], "credibility": r[7], "is_noise": bool(r[8]),
                        "emotion": r[9], "impulse": r[10]})
        return out

    def record_node_history(self, ts: str, activations: dict[str, float]) -> None:
        self.conn.executemany("INSERT INTO node_history(ts,node,activation) VALUES(?,?,?)",
                              [(ts, n, a) for n, a in activations.items()])
        self.conn.commit()

    def node_trend(self, node: str, days: int = 21) -> list[tuple[str, float]]:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        return list(self.conn.execute(
            "SELECT ts,activation FROM node_history WHERE node=? AND ts>=? ORDER BY ts",
            (node, since)))

    def log_advice(self, advice: dict) -> None:
        self.conn.execute("INSERT INTO advice_log(ts,advice) VALUES(?,?)",
                          (advice.get("ts", ""), json.dumps(advice)))
        self.conn.commit()

    # -- housekeeping -------------------------------------------------------------
    def prune(self, article_days: int = 90, event_days: int = 365) -> None:
        now = datetime.now(timezone.utc)
        self.conn.execute("DELETE FROM articles WHERE first_seen < ?",
                          ((now - timedelta(days=article_days)).isoformat(),))
        self.conn.execute("DELETE FROM events WHERE ts < ?",
                          ((now - timedelta(days=event_days)).isoformat(),))
        self.conn.commit()

    def stats(self) -> dict:
        g = lambda q: self.conn.execute(q).fetchone()[0]  # noqa: E731
        return {"articles": g("SELECT COUNT(*) FROM articles"),
                "digested": g("SELECT COUNT(*) FROM articles WHERE digested=1"),
                "events": g("SELECT COUNT(*) FROM events"),
                "noise_events": g("SELECT COUNT(*) FROM events WHERE is_noise=1"),
                "advice_issued": g("SELECT COUNT(*) FROM advice_log")}
