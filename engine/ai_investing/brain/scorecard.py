"""The scorecard: every recommendation is kept, cross-checked, and learned from.

Three jobs, run daily:

  1. SNAPSHOT — store today's prices (already fetched by the cycle, so free).
  2. SCORE — every advice list ever issued is frozen in advice_log; once a
     call is `horizon` days old, compare its direction against the realized
     price move and freeze the outcome in advice_outcomes. Nothing is ever
     deleted or rewritten — mistakes stay on the record.
  3. LEARN — outcomes update a per-symbol reliability weight r ∈ [0.5, 1.4]
     (EMA: hits push trust up, misses push it down). The adviser multiplies
     its field-driven conviction by r, so symbols where the brain's causal
     map keeps being wrong get listened to less — a real mathematical weight
     updated by evidence, not vibes.

The daily overview reports the running hit-rate and what was just learned,
so the learning is visible, not silent.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone

HORIZON_DAYS = 5           # a directional call is judged against the move over ~a week
DEADBAND = 0.003           # |move| under 0.3% is noise — excluded, not claimed
R_MIN, R_MAX, R_ALPHA = 0.5, 1.4, 0.12

_SCHEMA = """
CREATE TABLE IF NOT EXISTS price_history (
  date TEXT NOT NULL, symbol TEXT NOT NULL, price REAL NOT NULL,
  PRIMARY KEY (date, symbol));
CREATE TABLE IF NOT EXISTS advice_outcomes (
  advice_id INTEGER NOT NULL, symbol TEXT NOT NULL, direction TEXT NOT NULL,
  ts_issued TEXT NOT NULL, horizon_days INTEGER NOT NULL,
  realized_ret REAL, hit INTEGER,          -- 1 hit / 0 miss / NULL excluded (deadband)
  scored_at TEXT NOT NULL,
  PRIMARY KEY (advice_id, symbol));
"""


def _today_sgt() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=8)).date().isoformat()


class Scorecard:
    def __init__(self, settings):
        self.settings = settings
        data_dir = os.path.dirname(os.path.abspath(settings.state_path))
        self.conn = sqlite3.connect(os.path.join(data_dir, "brain.db"))
        self.conn.executescript(_SCHEMA)
        self.rel_path = os.path.join(data_dir, "reliability.json")

    def close(self) -> None:
        self.conn.close()

    # ------------------------------------------------------------- snapshot --
    def snapshot_prices(self, prices_by_symbol: dict[str, float]) -> None:
        d = _today_sgt()
        self.conn.executemany(
            "INSERT OR REPLACE INTO price_history(date,symbol,price) VALUES(?,?,?)",
            [(d, s, p) for s, p in prices_by_symbol.items() if p > 0])
        self.conn.commit()

    def _price_near(self, symbol: str, date: str, latest: bool = False) -> float | None:
        q = ("SELECT price FROM price_history WHERE symbol=? ORDER BY date DESC LIMIT 1"
             if latest else
             "SELECT price FROM price_history WHERE symbol=? AND date>=? ORDER BY date ASC LIMIT 1")
        row = self.conn.execute(q, (symbol,) if latest else (symbol, date)).fetchone()
        return row[0] if row else None

    # ---------------------------------------------------------------- score --
    def score_due(self, horizon_days: int = HORIZON_DAYS) -> list[dict]:
        """Score every advice call at least `horizon_days` old and not yet scored."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=horizon_days)).isoformat()
        rows = self.conn.execute(
            "SELECT id, ts, advice FROM advice_log WHERE ts <= ? ORDER BY id", (cutoff,)).fetchall()
        out: list[dict] = []
        now = datetime.now(timezone.utc).isoformat()
        for aid, ts, blob in rows:
            try:
                trades = (json.loads(blob) or {}).get("trades") or []
            except json.JSONDecodeError:
                continue
            issue_date = (datetime.fromisoformat(ts) + timedelta(hours=8)).date().isoformat()
            for t in trades:
                sym, direction = t.get("symbol"), t.get("direction")
                if not sym or not direction:
                    continue
                if self.conn.execute("SELECT 1 FROM advice_outcomes WHERE advice_id=? AND symbol=?",
                                     (aid, sym)).fetchone():
                    continue
                p0 = self._price_near(sym, issue_date)
                p1 = self._price_near(sym, issue_date, latest=True)
                if not p0 or not p1:
                    continue                      # price snapshots start today; old calls stay unscored
                ret = p1 / p0 - 1.0
                hit = None
                if abs(ret) >= DEADBAND:
                    hit = 1 if ((direction == "long") == (ret > 0)) else 0
                self.conn.execute(
                    "INSERT INTO advice_outcomes VALUES(?,?,?,?,?,?,?,?)",
                    (aid, sym, direction, ts, horizon_days, round(ret, 5), hit, now))
                out.append({"symbol": sym, "direction": direction, "ret": ret, "hit": hit})
        self.conn.commit()
        return out

    # ---------------------------------------------------------------- learn --
    def update_reliability(self, outcomes: list[dict]) -> list[str]:
        """EMA per-symbol trust from scored outcomes. Returns plain-language changes."""
        try:
            with open(self.rel_path) as fh:
                rel = json.load(fh)
        except (OSError, json.JSONDecodeError):
            rel = {}
        notes = []
        for o in outcomes:
            if o["hit"] is None:
                continue
            r = rel.get(o["symbol"], {}).get("r", 1.0)
            n = rel.get(o["symbol"], {}).get("n", 0)
            target = R_MAX if o["hit"] else R_MIN
            new_r = round(min(R_MAX, max(R_MIN, r + R_ALPHA * (target - r))), 3)
            rel[o["symbol"]] = {"r": new_r, "n": n + 1}
            if abs(new_r - r) >= 0.02:
                notes.append(f"{'raised' if new_r > r else 'trimmed'} trust in {o['symbol']} "
                             f"calls to ×{new_r:.2f} ({'hit' if o['hit'] else 'missed'} "
                             f"{o['ret']:+.1%})")
        if notes:
            try:
                with open(self.rel_path, "w") as fh:
                    json.dump(rel, fh, indent=1)
            except OSError:
                pass
        return notes

    # --------------------------------------------------------------- report --
    def track_record(self, days: int = 30) -> dict:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        rows = self.conn.execute(
            "SELECT symbol, direction, realized_ret, hit FROM advice_outcomes "
            "WHERE scored_at >= ? AND hit IS NOT NULL", (cutoff,)).fetchall()
        total = len(rows)
        hits = sum(r[3] for r in rows)
        worst = min(rows, key=lambda r: (r[2] if r[1] == "long" else -r[2]), default=None)
        best = max(rows, key=lambda r: (r[2] if r[1] == "long" else -r[2]), default=None)
        fmt = lambda r: f"{'long' if r[1] == 'long' else 'against'} {r[0]} ({r[2]:+.1%})"
        return {"total": total, "hits": hits,
                "hit_rate": round(hits / total, 3) if total else None,
                "best": fmt(best) if best else None,
                "worst": fmt(worst) if worst else None}


def reliability_weights(settings) -> dict[str, float]:
    """{symbol: r} for the adviser — 1.0 where nothing has been learned yet."""
    path = os.path.join(os.path.dirname(os.path.abspath(settings.state_path)),
                        "reliability.json")
    try:
        with open(path) as fh:
            return {s: v.get("r", 1.0) for s, v in json.load(fh).items()}
    except (OSError, json.JSONDecodeError):
        return {}
