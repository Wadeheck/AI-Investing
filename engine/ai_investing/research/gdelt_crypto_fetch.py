"""Crypto-focused GDELT historical backfill (Tier-1 crypto news history).

Fetches one day at a time from the GDELT 2.0 doc API for the digestion window
(2023-07-01 onward), crypto query, English sources, and appends day-records to
data/news_archive_gdelt_crypto.jsonl in the live-archive schema. Resumable:
days already in the file are skipped. Never deletes anything (retention rule).

Usage:  python3 -m ai_investing.research.gdelt_crypto_fetch
        --loop    repeated passes with rests until the archive is gapless
        --gentle  one fetch every 2-6 minutes (randomised), long cool-offs on
                  429s. ~4 min/day average: a full 864-day backlog is roughly
                  2.5 days of wall clock. The Aug-1 run at 10s/fetch got every
                  request from 2025-12 backwards refused; slower IS faster here.

The block outlasts one process: prodesk restarts this service every boot (the
nightly 05:00-07:30 rtcwake), which used to wipe the in-memory "consecutive
refusals" counter and let each new run hammer a still-hot IP for 5 more
refusals before backing off again — real progress only happened in the sliver
of each day before that wall was re-hit. COOLDOWN (data/gdelt_cooldown.json)
persists across restarts: a pass that ends in a refusal-storm escalates an
exponential, restart-surviving cool-off (45min doubling to an 8h cap) instead
of the old fixed 30-60min inter-pass rest; a pass with real progress resets it.
"""
from __future__ import annotations

import json
import random
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
OUT = DATA_DIR / "news_archive_gdelt_crypto.jsonl"
COOLDOWN_FILE = DATA_DIR / "gdelt_cooldown.json"
START = date(2023, 7, 1)
GENTLE = "--gentle" in sys.argv
COOLDOWN_BASE_SEC = 45 * 60
COOLDOWN_CAP_SEC = 8 * 60 * 60


def _pace() -> float:
    """Seconds to wait between day-fetches. Gentle: 2-6 min, randomised so we
    never look like a metronome to their limiter."""
    return random.uniform(120, 360) if GENTLE else 10.0


def _load_cooldown() -> dict:
    try:
        return json.loads(COOLDOWN_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {"until": None, "streak": 0}


def _save_cooldown(until: datetime | None, streak: int) -> None:
    COOLDOWN_FILE.write_text(json.dumps(
        {"until": until.isoformat() if until else None, "streak": streak}))


def _await_cooldown() -> None:
    state = _load_cooldown()
    until_raw = state.get("until")
    if not until_raw:
        return
    until = datetime.fromisoformat(until_raw)
    remaining = (until - datetime.now(timezone.utc)).total_seconds()
    if remaining > 0:
        print(f"cooldown from a prior refusal-storm (streak {state.get('streak', 0)}): "
              f"sleeping {remaining/60:.0f}min before the next pass", flush=True)
        time.sleep(remaining)

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
                time.sleep((300 if GENTLE else 45) * (attempt + 1))
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


def run() -> tuple[int, bool]:
    """Returns (days fetched, walled) — walled = the pass ended because the
    limiter refused 5 days in a row, not because todo ran out."""
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
    misses = 0   # consecutive failed days: the limiter is telling us to go away
    walled = False
    with OUT.open("a") as fh:
        for d in todo:
            heads = fetch_day(d)
            time.sleep(_pace())              # GDELT free tier is touchy — go slow, this is a marathon
            if heads is None:
                misses += 1
                if misses >= 5:
                    print(f"5 consecutive refusals — ending this pass to cool off", flush=True)
                    walled = True
                    break
                continue
            misses = 0
            fh.write(json.dumps({"date": d.isoformat(), "headlines": heads}) + "\n")
            fh.flush()
            fetched += 1
            if fetched % 50 == 0:
                print(f"{fetched}/{len(todo)} days (latest {d}, {len(heads)} heads)", flush=True)
    print(f"gdelt crypto backfill DONE — {fetched} new days this run", flush=True)
    return fetched, walled


if __name__ == "__main__":
    if "--loop" in sys.argv:
        # patient mode: repeated resumable passes with long rests until gapless
        while True:
            _await_cooldown()
            fetched, walled = run()
            today = datetime.now(timezone.utc).date()
            remaining = sum(1 for i in range((today - START).days)
                            if (START + timedelta(days=i)).isoformat() not in covered())
            print(f"pass complete — {remaining} days still missing", flush=True)
            if remaining == 0:
                _save_cooldown(None, 0)
                print("archive GAPLESS — exiting", flush=True)
                break
            if walled and fetched == 0:
                streak = _load_cooldown().get("streak", 0) + 1
                cooldown_sec = min(COOLDOWN_BASE_SEC * (2 ** (streak - 1)), COOLDOWN_CAP_SEC)
                until = datetime.now(timezone.utc) + timedelta(seconds=cooldown_sec)
                _save_cooldown(until, streak)
                print(f"refusal-storm with zero progress (streak {streak}) — cooling off "
                      f"{cooldown_sec/60:.0f}min, surviving restarts", flush=True)
            else:
                _save_cooldown(None, 0)   # real progress made: the wall is down, drop the streak
            time.sleep(random.uniform(1800, 3600) if GENTLE else 900)  # rest between passes
    else:
        sys.exit(run()[0])
