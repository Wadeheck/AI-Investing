"""NYT Archive backfill: market-grade historical headlines without Guardian.

The NYT Archive API (free key: https://developer.nytimes.com) returns EVERY
article for a given month in one call — the cheapest historical backfill that
exists. We keep Business/Economy/Technology/World desks, one line per day in
the same {"date", "headlines": [...]} schema as the other archives, appended
to data/news_archive_nyt.jsonl (append-only, resumable by month, never
rewritten).

Usage:
  NYT_API_KEY=... python -m ai_investing.research.nyt_fetch 2017-01 2026-07
Rate limit: 500 req/day, 5 req/min — one request per MONTH, so a decade is
~120 requests, minutes of work.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
OUT = DATA_DIR / "news_archive_nyt.jsonl"
DESKS = {"business", "financial", "economy", "technology", "foreign", "world",
         "washington", "climate", "energy"}


def months(start: str, end: str) -> list[tuple[int, int]]:
    (y0, m0), (y1, m1) = (map(int, start.split("-")), map(int, end.split("-")))
    out, y, m = [], y0, m0
    while (y, m) <= (y1, m1):
        out.append((y, m))
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def done_months() -> set[str]:
    done = set()
    if OUT.exists():
        for line in OUT.open():
            try:
                done.add(json.loads(line)["date"][:7])
            except (json.JSONDecodeError, KeyError):
                pass
    return done


def fetch_month(y: int, m: int, key: str) -> dict[str, list[dict]]:
    url = f"https://api.nytimes.com/svc/archive/v1/{y}/{m}.json?api-key={key}"
    req = urllib.request.Request(url, headers={"User-Agent": "ai-investing-research/0.1"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        docs = json.loads(resp.read().decode())["response"]["docs"]
    by_day: dict[str, list[dict]] = defaultdict(list)
    for d in docs:
        desk = (d.get("news_desk") or d.get("section_name") or "").lower()
        if desk and not any(k in desk for k in DESKS):
            continue
        title = (d.get("headline", {}) or {}).get("main", "").strip()
        if not title:
            continue
        day = (d.get("pub_date") or "")[:10]
        if day:
            by_day[day].append({"title": title[:200],
                                "summary": (d.get("abstract") or "")[:300],
                                "published": d.get("pub_date", ""),
                                "source": "nytimes.com"})
    return by_day


def main() -> None:
    key = os.environ.get("NYT_API_KEY", "")
    if not key:
        print("NYT_API_KEY not set — register free at developer.nytimes.com, "
              "add to .env, re-run. Skipping gracefully.")
        return
    start, end = (sys.argv[1:3] + ["2017-01", "2026-07"][len(sys.argv) - 1:])[:2]
    todo = [(y, m) for (y, m) in months(start, end)
            if f"{y:04d}-{m:02d}" not in done_months()]
    print(f"[nyt] {len(todo)} months to fetch")
    DATA_DIR.mkdir(exist_ok=True)
    with OUT.open("a") as fh:
        for y, m in todo:
            try:
                by_day = fetch_month(y, m, key)
            except Exception as exc:
                print(f"[nyt] {y}-{m:02d} failed ({exc}) — stopping; re-run to resume")
                return
            for day in sorted(by_day):
                fh.write(json.dumps({"date": day, "headlines": by_day[day]}) + "\n")
            fh.flush()
            print(f"[nyt] {y}-{m:02d}: {sum(len(v) for v in by_day.values())} headlines "
                  f"over {len(by_day)} days")
            time.sleep(13)          # 5 req/min limit
    print("[nyt] complete")


if __name__ == "__main__":
    main()
