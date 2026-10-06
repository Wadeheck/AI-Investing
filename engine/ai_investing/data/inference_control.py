"""Persistent task-level inference cache, cooldowns and measurements.

No prompts/credentials are logged. Successful JSON calls can be reused for an
identical input; failures get a short cooldown, never a successful cache entry.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time


class DeferredInference:
    """False-y result returned when a request was persisted for later."""

    def __init__(self, key: str):
        self.key = key

    def __bool__(self) -> bool:
        return False

    def __str__(self) -> str:
        return ""


class InferenceControl:
    def __init__(self, settings):
        root = os.path.dirname(os.path.abspath(settings.state_path))
        os.makedirs(root, exist_ok=True)
        self.db = sqlite3.connect(os.path.join(root, "inference_control.sqlite3"), timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA busy_timeout=30000")
        self.db.execute("PRAGMA journal_mode=WAL")
        queue_hours = int(getattr(settings, "llm_queue_cache_hours", 48))
        self.cache_ttl_seconds = (max(1, queue_hours) if self.queue_enabled(settings) else 6) * 3600
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS cache(key TEXT PRIMARY KEY, expires REAL, response TEXT);
          CREATE TABLE IF NOT EXISTS gates(task TEXT PRIMARY KEY, until REAL);
          CREATE TABLE IF NOT EXISTS calls(ts REAL, task TEXT, status TEXT,
            input_chars INTEGER, output_chars INTEGER, seconds REAL);
          CREATE INDEX IF NOT EXISTS calls_ts ON calls(ts);
          CREATE TABLE IF NOT EXISTS pending_news(id TEXT PRIMARY KEY, first_seen REAL, payload TEXT);
          CREATE TABLE IF NOT EXISTS llm_queue(
            key TEXT PRIMARY KEY,
            task TEXT NOT NULL,
            fingerprint TEXT NOT NULL,
            prompt TEXT NOT NULL,
            max_tokens INTEGER NOT NULL,
            tier TEXT NOT NULL,
            json_mode INTEGER NOT NULL DEFAULT 0,
            created REAL NOT NULL,
            available_at REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0,
            lease_until REAL,
            last_error TEXT,
            completed REAL
          );
          CREATE INDEX IF NOT EXISTS llm_queue_ready
            ON llm_queue(status, available_at, tier, created);
        """)
        self.db.commit()

    @staticmethod
    def request_key(task, fingerprint, prompt) -> str:
        return hashlib.sha256(
            json.dumps([task, fingerprint, prompt], sort_keys=True).encode()
        ).hexdigest()

    @staticmethod
    def queue_enabled(settings) -> bool:
        return bool(getattr(settings, "llm_queue_enabled", False))

    def claim(self, task, interval, now=None):
        now = time.time() if now is None else now
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            row = self.db.execute("SELECT until FROM gates WHERE task=?", (task,)).fetchone()
            if row and row[0] > now:
                return False
            self.db.execute("INSERT OR REPLACE INTO gates VALUES(?,?)", (task, now + interval))
        return True

    def record(self, task, status, chars=0, output=0, seconds=0):
        with self.db:
            self.db.execute("INSERT INTO calls VALUES(?,?,?,?,?,?)",
                            (time.time(), task, status, chars, output, seconds))
            self.db.execute("DELETE FROM calls WHERE ts<?", (time.time() - 30 * 86400,))

    def enqueue(self, task, fingerprint, prompt, max_tokens, tier, json_mode=False):
        """Persist one idempotent request without contacting any provider."""
        key = self.request_key(task, fingerprint, prompt)
        now = time.time()
        with self.db:
            self.db.execute(
                """INSERT INTO llm_queue
                   (key,task,fingerprint,prompt,max_tokens,tier,json_mode,created,available_at)
                   VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(key) DO NOTHING""",
                (key, task, json.dumps(fingerprint, sort_keys=True), prompt,
                 int(max_tokens), tier, int(bool(json_mode)), now, now))
            self.db.execute(
                """UPDATE llm_queue SET status='pending', available_at=?, attempts=0,
                       lease_until=NULL, last_error=NULL, completed=NULL
                   WHERE key=? AND status IN ('done','failed')""", (now, key))
        return DeferredInference(key)

    def call(self, task, fingerprint, prompt, callback, json_mode=False,
             max_tokens=1500, tier="fast", settings=None):
        key = self.request_key(task, fingerprint, prompt)
        now = time.time()
        with self.db:
            self.db.execute("DELETE FROM cache WHERE expires<?", (now,))
        cached = self.db.execute("SELECT response FROM cache WHERE key=?", (key,)).fetchone()
        if cached:
            self.record(task, "cache_hit", len(prompt))
            return cached[0]
        if settings is not None and self.queue_enabled(settings):
            result = self.enqueue(task, fingerprint, prompt, max_tokens, tier, json_mode)
            self.record(task, "queued", len(prompt))
            return result
        # Across processes, identical requests in flight or recently failed do
        # not start another provider chain. A crash releases after ten minutes.
        if not self.claim("request:" + key, 600, now):
            self.record(task, "duplicate_or_failure_cooldown", len(prompt))
            return None
        started = time.monotonic()
        try:
            response = callback()
        except Exception:
            self.record(task, "error", len(prompt), seconds=time.monotonic() - started)
            raise
        valid = bool(response)
        if valid and json_mode:
            from ai_investing.data.news import _extract_json
            valid = isinstance(_extract_json(response), dict)
        with self.db:
            if valid:
                self.db.execute("INSERT OR REPLACE INTO cache VALUES(?,?,?)",
                                (key, now + self.cache_ttl_seconds, response))
                self.db.execute("DELETE FROM gates WHERE task=?", ("request:" + key,))
            self.db.execute("DELETE FROM gates WHERE until<?", (now - 86400,))
        self.record(task, "inferred" if valid else "failed", len(prompt), len(response or ""), time.monotonic() - started)
        return response if valid else None

    def _claim_next(self, lease_seconds=900):
        """Claim the next request, recovering jobs interrupted by a power loss."""
        now = time.time()
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            self.db.execute(
                "UPDATE llm_queue SET status='pending', lease_until=NULL "
                "WHERE status='running' AND lease_until<?", (now,))
            row = self.db.execute(
                """SELECT * FROM llm_queue
                   WHERE status='pending' AND available_at<=?
                   ORDER BY CASE tier WHEN 'fast' THEN 0 WHEN 'smart' THEN 1 ELSE 2 END,
                            created, key LIMIT 1""", (now,)).fetchone()
            if row is None:
                return None
            lease = now + max(60, int(lease_seconds))
            self.db.execute(
                """UPDATE llm_queue SET status='running', attempts=attempts+1,
                        lease_until=? WHERE key=?""", (lease, row["key"]))
            claimed = dict(row)
            claimed["attempts"] = int(row["attempts"] or 0) + 1
            return claimed

    def _finish_job(self, job, response, json_mode, error=None):
        now = time.time()
        key = job["key"]
        task = job["task"]
        valid = bool(response)
        if valid and json_mode:
            from ai_investing.data.news import _extract_json
            valid = isinstance(_extract_json(response), dict)
        with self.db:
            if valid:
                self.db.execute(
                    "INSERT OR REPLACE INTO cache VALUES(?,?,?)",
                    (key, now + self.cache_ttl_seconds, response))
                self.db.execute(
                    "UPDATE llm_queue SET status='done', lease_until=NULL, completed=?, "
                    "last_error=NULL WHERE key=?", (now, key))
                self.db.execute("DELETE FROM gates WHERE task=?", ("request:" + key,))
            else:
                attempts = int(job.get("attempts") or 1)
                # Back off inside the current drain and leave a bounded retry for
                # the next scheduled window. No task is lost on a timeout.
                delay = min(3600, 30 * (2 ** min(attempts - 1, 6)))
                self.db.execute(
                    "UPDATE llm_queue SET status='pending', available_at=?, lease_until=NULL, "
                    "last_error=? WHERE key=?",
                    (now + delay, str(error or "empty response")[:500], key))
        self.record(task, "inferred" if valid else "failed",
                    len(job["prompt"]), len(response or ""))
        return valid

    def drain(self, callback, lease_seconds=900, max_jobs=0):
        """Drain queued requests serially; callback receives one job dict."""
        done = failed = 0
        while not max_jobs or done + failed < max_jobs:
            job = self._claim_next(lease_seconds)
            if job is None:
                break
            try:
                response = callback(job)
                if self._finish_job(job, response, bool(job["json_mode"])):
                    done += 1
                else:
                    failed += 1
            except Exception as exc:  # one bad task must not stop the drain
                self._finish_job(job, None, bool(job["json_mode"]), error=exc)
                failed += 1
        return {"done": done, "failed": failed, "remaining": self.pending_count()}

    def pending_count(self):
        return int(self.db.execute(
            "SELECT count(*) FROM llm_queue WHERE status IN ('pending','running')"
        ).fetchone()[0])

    def queue_status(self):
        return [dict(row) for row in self.db.execute(
            "SELECT task,tier,status,count(*) AS count FROM llm_queue "
            "GROUP BY task,tier,status ORDER BY tier,task,status"
        )]

    def close(self):
        self.db.close()


def pending_headlines(settings, headlines, consumed=False):
    """Preserve deferred bodies even when they leave the RSS headline window."""
    from ai_investing.brain.store import article_id
    control = InferenceControl(settings)
    try:
        with control.db:
            for h in headlines:
                identity = article_id(h.get('title', ''), h.get('source', ''))
                if consumed:
                    control.db.execute('DELETE FROM pending_news WHERE id=?', (identity,))
                else:
                    control.db.execute('INSERT OR IGNORE INTO pending_news VALUES(?,?,?)',
                        (identity, time.time(), json.dumps(h)))
        return [json.loads(r[0]) for r in control.db.execute(
            'SELECT payload FROM pending_news ORDER BY first_seen,id')]
    finally:
        control.close()


def extraction_due(settings, curated=False):
    """Numeric brain cycles keep running while feed extraction is batched."""
    if curated:
        return True
    control = InferenceControl(settings)
    try:
        interval = max(0, float(os.getenv("LLM_FEED_INTERVAL_SECONDS", "1200")))
        # A completed queue drain only fills the inference cache; the live brain
        # still has to consume the durable headline rows. When immediate mode is
        # active, let that consumer catch up at the engine cadence rather than
        # leaving a multi-day backlog behind a normal 20-minute gate. The batch
        # size remains capped by Brain.think(), and extraction is still claimed
        # by SQLite, so this is serial bounded catch-up, not a request burst.
        if not control.queue_enabled(settings):
            try:
                backlog = int(control.db.execute(
                    "SELECT count(*) FROM pending_news").fetchone()[0])
                threshold = max(1, int(float(os.getenv(
                    "LLM_BACKLOG_CATCHUP_THRESHOLD", "120"))))
                catchup = max(1.0, float(os.getenv(
                    "LLM_BACKLOG_INTERVAL_SECONDS", "300")))
                if backlog >= threshold:
                    interval = min(interval, catchup)
            except (sqlite3.Error, TypeError, ValueError):
                pass
        due = control.claim("feed_extraction", interval)
        if not due:
            control.record("feed_extraction", "deferred")
        return due
    finally:
        control.close()
