"""News accumulator: crawl cheap, remember locally, digest later.

Pulls every configured RSS feed (conditional GET) plus the alt-feeds (SEC
EDGAR 8-K, StockTwits sentiment, Hacker News), dedupes through the brain's
article store (data/brain.db), and appends only NEVER-SEEN headlines to the
permanent archive `data/news_archive_live.jsonl`.

The archive is append-only ({"date", "ts", "headlines": [...]} per run; a
day = the union of its lines) and is the future digestion input for this
machine — the same role news_archive_guardian.jsonl plays on the pipeline
machine. Per the project retention rule it is never deleted or rewritten.

Usage:
  python -m ai_investing.research.accumulate --once
  python -m ai_investing.research.accumulate --loop 900     # every 15 min
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ai_investing.brain.store import BrainStore          # noqa: E402
from ai_investing.config import Settings                 # noqa: E402
from ai_investing.data import altfeeds                   # noqa: E402
from ai_investing.data.news import fetch_headlines       # noqa: E402

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
ARCHIVE = DATA_DIR / "news_archive_live.jsonl"


def log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def run_once(settings: Settings, store: BrainStore) -> int:
    heads = fetch_headlines(settings)
    n_rss = len(heads)
    heads += altfeeds.fetch_all(settings)
    fresh, seen_before = store.filter_new(heads)
    n_bodies = 0
    if fresh:
        # full-article bodies for NEVER-SEEN stories only (crawl once, keep
        # forever): this is what the digester's escalation pass, the deals
        # extractor and the integrity scanner actually read
        try:
            from ai_investing.data.article_body import attach_bodies
            n_bodies = attach_bodies(fresh, limit=60)
        except Exception:
            pass
        DATA_DIR.mkdir(exist_ok=True)
        now = datetime.now(timezone.utc)
        clean = [{k: v for k, v in h.items() if k != "_article_id"} for h in fresh]
        with ARCHIVE.open("a") as fh:
            fh.write(json.dumps({"date": now.date().isoformat(),
                                 "ts": now.isoformat(timespec="seconds"),
                                 "headlines": clean}) + "\n")
        # Archived = this pipeline's terminal stage: mark so the next poll
        # doesn't re-append the same stories. (Later batch digestion reads the
        # ARCHIVE, not the store, so nothing is lost by marking here.)
        store.mark_digested(fresh)
    log(f"pulled {len(heads)} ({n_rss} rss + {len(heads) - n_rss} alt) | "
        f"new {len(fresh)} | bodies {n_bodies} | seen-before {seen_before} | "
        f"store {store.stats().get('articles', '?')} articles")
    return len(fresh)


def main() -> None:
    settings = Settings()
    store = BrainStore(settings.brain.db_path)
    if "--loop" in sys.argv:
        every = int(sys.argv[sys.argv.index("--loop") + 1])
        log(f"accumulating every {every}s into {ARCHIVE} — ctrl-c to stop")
        while True:
            try:
                run_once(settings, store)
            except Exception as exc:                     # never die on one bad cycle
                log(f"cycle error (continuing): {type(exc).__name__}: {exc}")
            time.sleep(every)
    else:
        run_once(settings, store)


if __name__ == "__main__":
    main()
