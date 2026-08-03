"""Guardian Open Platform historical backfill: market-grade headlines for
every calendar day of the replay window, to fill/replace the wiki-thin days.

Design (lessons from the GDELT scars in docs/archive/TRAINING_RECORD.md):
  - RESUMABLE: skips days already recorded; safe to re-run any time.
  - HONEST: a throttled/failed request is NEVER recorded as a quiet news day —
    only HTTP-200 status:ok responses are written.
  - POLITE: 1 call per day-date (page-size 200 covers a full day), >=1.2s
    between calls; exits gracefully (code 2) when the daily quota runs out.

Free tier: 500 calls/day, 60/min. The ~1,120-day window completes in ~3 runs;
wrap in a retry loop (see __main__) to ride through the quota resets.

Output: data/news_archive_guardian.jsonl — {"date", "headlines": [{"title",
"source", "section", "summary"}]} — same shape the digester already reads
(title + source), with section/summary as extra signal for the tagging AI.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
OUT = DATA_DIR / "news_archive_guardian.jsonl"

API = "https://content.guardianapis.com/search"
SECTIONS = "business|world|technology|politics|environment|us-news|money"
START = date(2023, 7, 1)          # matches the 3y price/replay window
CALL_GAP = 1.2                    # seconds between calls (limit: 60/min)


def log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc):%H:%M:%S}] {msg}", flush=True)


def api_key() -> str:
    from ai_investing.config import settings
    key = settings.brain.guardian_api_key
    if not key:
        log("GUARDIAN_API_KEY is not set — aborting")
        sys.exit(1)
    return key


def covered_days() -> set[str]:
    days = set()
    if OUT.exists():
        for line in OUT.open():
            try:
                days.add(json.loads(line)["date"])
            except (json.JSONDecodeError, KeyError):
                pass
    return days


def fetch_day(key: str, d: str, page: int = 1) -> tuple[dict | None, int]:
    """One API call. Returns (parsed response body | None, remaining daily quota)."""
    qs = urllib.parse.urlencode({
        "api-key": key, "from-date": d, "to-date": d, "section": SECTIONS,
        "page-size": 200, "page": page, "order-by": "newest",
        "show-fields": "trailText,bodyText",
    })
    req = urllib.request.Request(f"{API}?{qs}", headers={"User-Agent": "ai-investing/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            remaining = int(resp.headers.get("x-ratelimit-remaining-day", "1"))
            body = json.loads(resp.read().decode())
            return body.get("response"), remaining
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            return None, 0
        log(f"{d}: HTTP {exc.code} — skipping this run (never recorded as empty)")
        return None, 1
    except Exception as exc:
        log(f"{d}: {exc} — skipping this run")
        return None, 1


def run() -> int:
    key = api_key()
    done = covered_days()
    today = datetime.now(timezone.utc).date()
    todo = []
    d = START
    while d < today:                       # exclude today: the day isn't over
        ds = d.isoformat()
        if ds not in done:
            todo.append(ds)
        d += timedelta(days=1)
    log(f"guardian backfill: {len(done)} days covered, {len(todo)} to fetch")
    if not todo:
        log("archive complete ✅")
        return 0

    fetched = 0
    with OUT.open("a") as fh:
        for ds in todo:
            r, remaining = fetch_day(key, ds)
            if remaining <= 0:
                log(f"daily quota exhausted after {fetched} new days — resume later")
                return 2
            if r is None or r.get("status") != "ok":
                time.sleep(CALL_GAP)
                continue
            results = list(r.get("results", []))
            pages = int(r.get("pages", 1))
            for p in range(2, min(pages, 3) + 1):   # >200 items/day is rare
                time.sleep(CALL_GAP)
                r2, remaining = fetch_day(key, ds, page=p)
                if remaining <= 0:
                    log(f"quota exhausted mid-day {ds} — day NOT recorded, resume later")
                    return 2
                if r2 and r2.get("status") == "ok":
                    results += r2.get("results", [])
            heads = [{
                "title": x.get("webTitle", ""),
                "source": "theguardian.com",
                "section": x.get("sectionId", ""),
                # full publication timestamp (UTC): needed so cross-timezone
                # replays know whether news landed before or after each
                # market's close on its date
                "ts": x.get("webPublicationDate", ""),
                "summary": (x.get("fields") or {}).get("trailText", ""),
                # first ~3000 chars: expectations context + disambiguation live
                # in the opening paragraphs; digester escalates to this only
                # for low-confidence or high-magnitude events
                "body": (x.get("fields") or {}).get("bodyText", "")[:3000],
            } for x in results if x.get("webTitle")]
            fh.write(json.dumps({"date": ds, "headlines": heads}) + "\n")
            fh.flush()
            fetched += 1
            if fetched % 50 == 0:
                log(f"{fetched} days fetched this run (latest {ds}, "
                    f"{len(heads)} headlines, quota left ~{remaining})")
            time.sleep(CALL_GAP)
    log(f"backfill COMPLETE ✅ — fetched {fetched} new days this run")
    return 0


if __name__ == "__main__":
    if "--loop" in sys.argv:
        # ride through daily quota resets: retry hourly until complete
        while True:
            rc = run()
            if rc == 0:
                break
            log("sleeping 1h before retrying (quota reset pending)")
            time.sleep(3600)
    else:
        sys.exit(run())
