#!/usr/bin/env python3
"""Stage all pending crypto news/content into dated day-files for the Sonnet
crypto-backfill digestion campaign.

Sources merged per calendar date (UTC) into days/YYYY-MM-DD.jsonl:
  - ../../news_archive_gdelt_crypto.jsonl  (GDELT crypto sweep — grows as the
    crawler fills; RE-RUN THIS SCRIPT to refresh staging as new days land)
  - ../../crypto_history/wublockchain_substack.json (1,500 curated posts)
  - ../../crypto_history/binance_listings.json / upbit_listings.json
    (exchange listing announcements — primary-source events)

Idempotent: rebuilds days/ from scratch each run (staging is derived data;
the raw archives above are the retention-rule originals).
"""
import json
import os
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.abspath(os.path.join(BASE, "..", ".."))
DAYS = os.path.join(BASE, "days")
os.makedirs(DAYS, exist_ok=True)

by_date: dict[str, list] = {}

def add(date, title, summary, ts, source, url=""):
    if not date or len(date) != 10 or not title:
        return
    by_date.setdefault(date, []).append(
        {"title": title.strip(), "summary": (summary or "").strip(),
         "ts": ts or f"{date}T12:00:00+00:00", "source": source, "url": url})

# GDELT sweep (already day-structured, headline ts included)
try:
    for line in open(os.path.join(DATA, "news_archive_gdelt_crypto.jsonl")):
        r = json.loads(line)
        for h in r.get("headlines", []):
            add(r["date"], h.get("title", ""), h.get("summary", ""),
                h.get("ts", ""), h.get("source", "gdelt"), h.get("url", ""))
except FileNotFoundError:
    pass

# Curated-X browser captures (see docs/data-pipeline/X_BROWSER_CAPTURE.md) — day-records
try:
    for line in open(os.path.join(DATA, "news_archive_x.jsonl")):
        r = json.loads(line)
        for h in r.get("headlines", []):
            add(r.get("date", ""), h.get("title", ""), h.get("summary", ""),
                h.get("ts", ""), h.get("source", "x.com"), h.get("url", ""))
except FileNotFoundError:
    pass

# Wu Blockchain substack archive (title + subtitle, dated)
try:
    for p in json.load(open(os.path.join(DATA, "crypto_history", "wublockchain_substack.json"))):
        add(p.get("date", ""), p.get("title", ""), p.get("subtitle", ""),
            f"{p.get('date','')}T12:00:00+00:00", "wublock.substack.com", p.get("url", ""))
except FileNotFoundError:
    pass

# Exchange listing announcements (primary-source, ms-epoch timestamps)
for fn, src in [("binance_listings.json", "binance.com/announcements"),
                ("upbit_listings.json", "upbit.com/notices")]:
    try:
        for a in json.load(open(os.path.join(DATA, "crypto_history", fn))):
            ts = a.get("ts")
            if not ts or not a.get("title"):
                continue
            if isinstance(ts, (int, float)):
                dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
            else:
                try:
                    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                except ValueError:
                    continue
            add(dt.date().isoformat(), a["title"], "",
                dt.isoformat(timespec="seconds"), src)
    except FileNotFoundError:
        pass

# rebuild days/ from scratch (derived data)
for f in os.listdir(DAYS):
    os.remove(os.path.join(DAYS, f))
n_heads = 0
for d in sorted(by_date):
    heads = sorted(by_date[d], key=lambda h: h["ts"])
    n_heads += len(heads)
    with open(os.path.join(DAYS, f"{d}.jsonl"), "w") as fh:
        for h in heads:
            fh.write(json.dumps(h, ensure_ascii=False) + "\n")
print(f"staged {len(by_date)} day-files, {n_heads} dated items -> {DAYS}")
if by_date:
    ds = sorted(by_date)
    print(f"range: {ds[0]} -> {ds[-1]}")
