"""SQLite journal: every decision, order, and equity snapshot is recorded so the
system is fully auditable ("why did it buy?") and the dashboard has data to read.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone

from ai_investing.models import Decision, Order


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Journal:
    def __init__(self, db_path: str):
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT, symbol TEXT, direction TEXT, score REAL,
                confidence REAL, rationale TEXT, signals TEXT
            );
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT, symbol TEXT, side TEXT, qty REAL, price REAL,
                status TEXT, reason TEXT, live INTEGER, client_order_id TEXT
            );
            CREATE TABLE IF NOT EXISTS equity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT, equity REAL, cash REAL, positions INTEGER
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT, kind TEXT, detail TEXT
            );
            CREATE TABLE IF NOT EXISTS params (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT, version INTEGER, weights TEXT, hyper TEXT, metrics TEXT
            );
            CREATE TABLE IF NOT EXISTS outcomes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT, symbol TEXT, realized_return REAL, features TEXT, pred_error REAL
            );
            """
        )
        self.conn.commit()
        # Backfill columns on pre-existing databases. Each ALTER is attempted
        # separately: they were added at different times, so a database that has
        # some and not others must still get the rest (one combined try/except
        # would stop at the first column that already exists).
        for ddl in ("ALTER TABLE orders ADD COLUMN client_order_id TEXT",
                    "ALTER TABLE orders ADD COLUMN req_qty REAL",
                    "ALTER TABLE orders ADD COLUMN submitted_qty REAL",
                    "ALTER TABLE orders ADD COLUMN submitted_price REAL",
                    "ALTER TABLE orders ADD COLUMN order_type TEXT",
                    "ALTER TABLE orders ADD COLUMN limit_price REAL"):
            try:
                self.conn.execute(ddl)
                self.conn.commit()
            except sqlite3.OperationalError:
                pass

    def record_decision(self, d: Decision) -> None:
        self.conn.execute(
            "INSERT INTO decisions (ts,symbol,direction,score,confidence,rationale,signals) "
            "VALUES (?,?,?,?,?,?,?)",
            (_now(), d.asset.symbol, d.direction.value, d.score, d.confidence, d.rationale,
             json.dumps([{"name": s.name, "score": s.score, "confidence": s.confidence,
                          "rationale": s.rationale} for s in d.signals])),
        )
        self.conn.commit()

    def record_order(self, o: Order, live: bool) -> None:
        """Record the REQUEST as well as the outcome.

        `qty`/`price` keep their old meaning (filled, falling back to requested)
        so every existing reader is unaffected. The new columns are what a
        rejection needs and never had: what was asked for, what the adapter
        actually sent, and in what form. Without them a rejected order says only
        that the venue refused something — 8 live orders were lost to
        "Wrong bid size, please change the price" and the submitted price, the
        one number that would have identified the cause, existed nowhere."""
        self.conn.execute(
            "INSERT INTO orders (ts,symbol,side,qty,price,status,reason,live,client_order_id,"
            " req_qty,submitted_qty,submitted_price,order_type,limit_price) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (_now(), o.asset.symbol, o.side.value, o.filled_qty or o.qty,
             o.filled_price or 0.0, o.status.value, o.reason, int(live), o.client_order_id,
             o.qty, o.submitted_qty, o.submitted_price,
             (o.order_type.value if o.order_type is not None else None), o.limit_price),
        )
        self.conn.commit()

    def record_equity(self, equity: float, cash: float, n_positions: int) -> None:
        self.conn.execute("INSERT INTO equity (ts,equity,cash,positions) VALUES (?,?,?,?)",
                          (_now(), equity, cash, n_positions))
        self.conn.commit()

    def record_event(self, kind: str, detail: str) -> None:
        self.conn.execute("INSERT INTO events (ts,kind,detail) VALUES (?,?,?)", (_now(), kind, detail))
        self.conn.commit()

    def record_params(self, model, metrics: dict) -> None:
        hyper = {"gain": model.gain, "entry_threshold": model.entry_threshold,
                 "size_scale": model.size_scale, "stop_loss": model.stop_loss,
                 "take_profit": model.take_profit}
        weights = dict(zip(model.feature_names, model.weights))
        self.conn.execute(
            "INSERT INTO params (ts,version,weights,hyper,metrics) VALUES (?,?,?,?,?)",
            (_now(), model.version, json.dumps(weights), json.dumps(hyper), json.dumps(metrics)),
        )
        self.conn.commit()

    def record_outcome(self, symbol: str, realized_return: float, features: dict,
                       pred_error: float) -> None:
        self.conn.execute(
            "INSERT INTO outcomes (ts,symbol,realized_return,features,pred_error) VALUES (?,?,?,?,?)",
            (_now(), symbol, realized_return, json.dumps(features), pred_error),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
