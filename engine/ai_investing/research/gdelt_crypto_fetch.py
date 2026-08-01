"""Crypto-focused GDELT historical backfill (Tier-1 crypto news history).

Fetches one day at a time from the GDELT 2.0 doc API for the digestion window
(2023-07-01 onward), crypto query, English sources, and appends day-records to
data/news_archive_gdelt_crypto.jsonl in the live-archive schema. Resumable:
days already in the file are skipped. Never deletes anything (retention rule).

Usage:  python3 -m ai_investing.research.gdelt_crypto_fetch
"""
from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
OUT = DATA_DIR / "news_archive_gdelt_crypto.jsonl"
START = date(2023, 7, 1)

QUERY = ('(bitcoin OR ethereum OR stablecoin OR "crypto exchange" OR binance OR '
         'coinbase OR "SEC crypto" OR "crypto regulation" OR "crypto ETF" OR '
         '"crypto hack" OR blockchain) sourcelang:english')
API = "https://api.gdeltproject.org/api/v2/doc/doc"


def covered() -> set[str]:
    days = set()
    if OUT.exists():
        for line in OUT.open():
            try:
                days.add(json.loads(line)["date"])
            except (json.JSONDecodeError, KeyError):
                pass
    return days


def fetch_day(d: date) -> list[dict] | None:
    qs = urllib.parse.urlencode({
        "query": QUERY, "mode": "artlist", "format": "json", "maxrecords": 75,
        "startdatetime": d.strftime("%Y%m%d000000"),
        "enddatetime": d.strftime("%Y%m%d235959"), "sort": "hybridrel"})
    req = urllib.request.Request(f"{API}?{qs}", headers={"User-Agent": "ai-investing/1.0"})
    arts = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=40) as resp:
                arts = json.loads(resp.read().decode("utf-8", "ignore")).get("articles", [])
            break
        except urllib.error.HTTPError as exc:
            if exc.code == 429:              # rate-limited: back off hard, retry same day
                time.sleep(45 * (attempt + 1))
                continue
            print(f"{d}: HTTP {exc.code} — skipping this run", flush=True)
            return None
        except Exception as exc:
            print(f"{d}: {exc} — skipping this run", flush=True)
            return None
    if arts is None:
        print(f"{d}: still rate-limited after retries — skipping this run", flush=True)
        return None
    heads, seen = [], set()
    for a in arts:
        title = (a.get("title") or "").strip()
        if not title or title[:70].lower() in seen:
            continue
        seen.add(title[:70].lower())
        ts = a.get("seendate", "")           # 20240805T074500Z
        iso = ""
        try:
            iso = datetime.strptime(ts, "%Y%m%dT%H%M%SZ").replace(
                tzinfo=timezone.utc).isoformat(timespec="seconds")
        except ValueError:
            pass
        heads.append({"title": title, "summary": "", "ts": iso,
                      "source": a.get("domain", "gdelt"), "url": a.get("url", "")})
    return heads


def run() -> int:
    done = covered()
    today = datetime.now(timezone.utc).date()
    todo = []
    d = START
    while d < today:
        if d.isoformat() not in done:
            todo.append(d)
        d += timedelta(days=1)
    todo.reverse()   # newest first: even a throttled partial pass banks the most current news
    print(f"gdelt crypto backfill: {len(done)} days covered, {len(todo)} to fetch (newest first)", flush=True)
    fetched = 0
    with OUT.open("a") as fh:
        for d in todo:
            heads = fetch_day(d)
            time.sleep(10.0)                 # GDELT free tier is touchy — go slow, this is a marathon
            if heads is None:
                continue
            fh.write(json.dumps({"date": d.isoformat(), "headlines": heads}) + "\n")
            fh.flush()
            fetched += 1
            if fetched % 50 == 0:
                print(f"{fetched}/{len(todo)} days (latest {d}, {len(heads)} heads)", flush=True)
    print(f"gdelt crypto backfill DONE — {fetched} new days this run", flush=True)
    return 0


if __name__ == "__main__":
    if "--loop" in sys.argv:
        # patient mode: repeated resumable passes with long rests until gapless
        while True:
            run()
            today = datetime.now(timezone.utc).date()
            remaining = sum(1 for i in range((today - START).days)
                            if (START + timedelta(days=i)).isoformat() not in covered())
            print(f"pass complete — {remaining} days still missing", flush=True)
            if remaining == 0:
                print("archive GAPLESS — exiting", flush=True)
                break
            time.sleep(900)                  # 15 min rest between passes
    else:
        sys.exit(run())
