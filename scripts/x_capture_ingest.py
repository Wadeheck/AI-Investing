#!/usr/bin/env python3
"""Ingest a browser X-capture harvest into data/news_archive_x.jsonl.

The browser session (docs/data-pipeline/X_BROWSER_CAPTURE.md) runs the in-page harvester and
gets back rows of {u, t, x} — status-url, ISO datetime, text. This script does
everything after that, so the AI session only has to paste the harvest:

  - drops anything whose status id is already in the archive (the dedup
    contract — never capture a tweet twice)
  - drops ads/promo/empty rows
  - derives the exact UTC timestamp (uses the harvested `t`; falls back to the
    snowflake id, which encodes creation time to the millisecond)
  - splits the post text into title (first line, cleaned) + summary (rest)
  - writes append-only day-records grouped by UTC date, sorted by ts

Usage:
    python3 scripts/x_capture_ingest.py harvest.json  [--note "session 3"]
    cat harvest.json | python3 scripts/x_capture_ingest.py -
"""
import json
import os
import re
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARCHIVE = os.path.join(ROOT, "data", "news_archive_x.jsonl")

PROMO = re.compile(r"\b(subscribe|giveaway|link in bio|use code|referral|"
                   r"sign up now|join our telegram|our substack)\b", re.I)
NOISE_PREFIX = re.compile(r"^\s*(JUST IN:|BREAKING:|NEW:|SCOOP:)\s*", re.I)


def seen_ids() -> set:
    ids = set()
    if os.path.exists(ARCHIVE):
        for line in open(ARCHIVE):
            try:
                for h in json.loads(line).get("headlines", []):
                    u = h.get("url", "")
                    if "/status/" in u:
                        ids.add(u.rsplit("/", 1)[-1])
            except (json.JSONDecodeError, KeyError):
                continue
    return ids


def snowflake_ts(sid: str):
    try:
        return datetime.fromtimestamp(((int(sid) >> 22) + 1288834974657) / 1000,
                                      tz=timezone.utc)
    except (ValueError, OverflowError):
        return None


def main() -> int:
    src = sys.argv[1] if len(sys.argv) > 1 else "-"
    note = ""
    if "--note" in sys.argv:
        note = sys.argv[sys.argv.index("--note") + 1]
    raw = sys.stdin.read() if src == "-" else open(src).read()
    rows = json.loads(raw)
    if isinstance(rows, dict):
        rows = rows.get("rows") or rows.get("posts") or []

    known = seen_ids()
    now = datetime.now(timezone.utc)
    by_date, skipped = {}, {"dupe": 0, "promo": 0, "empty": 0}
    for r in rows:
        u = (r.get("u") or r.get("url") or "").strip()
        if "/status/" not in u:
            skipped["empty"] += 1
            continue
        sid = u.rsplit("/", 1)[-1]
        handle = u.strip("/").split("/")[0]
        if sid in known:
            skipped["dupe"] += 1
            continue
        text = (r.get("x") or r.get("text") or "").strip()
        if not text:
            skipped["empty"] += 1
            continue
        if PROMO.search(text) and len(text) < 220:
            skipped["promo"] += 1
            continue
        ts = None
        if r.get("t"):
            try:
                ts = datetime.fromisoformat(str(r["t"]).replace("Z", "+00:00"))
            except ValueError:
                ts = None
        ts = ts or snowflake_ts(sid)
        if ts is None:
            skipped["empty"] += 1
            continue
        clean = NOISE_PREFIX.sub("", text.replace("\n", " ")).strip()
        title = clean[:180]
        summary = clean[180:600] if len(clean) > 180 else ""
        known.add(sid)
        by_date.setdefault(ts.date().isoformat(), []).append({
            "title": title, "summary": summary,
            "published": ts.strftime("%a, %d %b %Y %H:%M:%S GMT"),
            "ts": ts.isoformat(timespec="seconds"),
            "source": f"x.com/{handle}",
            "url": f"https://x.com/{handle}/status/{sid}"})

    n = 0
    with open(ARCHIVE, "a") as fh:
        for d, heads in sorted(by_date.items()):
            heads.sort(key=lambda h: h["ts"])
            n += len(heads)
            fh.write(json.dumps({"date": d, "ts": now.isoformat(timespec="seconds"),
                                 "capture": note or "browser session",
                                 "headlines": heads}, ensure_ascii=False) + "\n")
    print(f"ingested {n} new posts across {len(by_date)} dates "
          f"(skipped: {skipped['dupe']} dupes, {skipped['promo']} promo, "
          f"{skipped['empty']} empty)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
