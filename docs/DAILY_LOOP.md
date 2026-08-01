# The daily news loop — runbook

*Created 2026-08-01. The loop that keeps the brain current. Mechanical parts
run from the system crontab; the AI part runs as a daily scheduled routine in
an active Claude session (session-bound — RE-ARM IT when starting a fresh
session, see §3).*

## 1. Always-on (system crontab, installed 2026-08-01)

- `17 */4 * * *` — `scripts/accumulate_once.py`: pulls all ~44 RSS/alt feeds
  into `data/news_archive_live.jsonl` + the brain store. Log:
  `data/accumulate_cron.log`.
- The GDELT crypto crawler (`gdelt_crypto_fetch --loop`) is long-running and
  resumable; restart it in any session if dead:
  `cd engine && python3 -m ai_investing.research.gdelt_crypto_fetch --loop`
  (single instance only — it appends to one file).

## 2. Daily AI routine (once per day, after ~08:30 SGT)

1. Fresh pull: `scripts/accumulate_once.py`.
2. Build YESTERDAY's (UTC) day-input from ALL live sources
   (`news_archive_live.jsonl` + `news_archive_x.jsonl` +
   `news_archive_gdelt_crypto.jsonl`), title-deduped, plus the trailing
   ledger extract (~55 entries).
3. ONE Sonnet agent digests the complete day per
   `docs/SONNET_DIGEST_BRIEF.md` → `data/digest_v2/events/<date>.json`
   (overwrites any partial-day file; mark `"redigest": "full-day"`).
4. `python3 data/digest_v2/_merge_amendments.py` — rebuilds ledger +
   `news_impulses_v2.jsonl`.
5. Optional: X capture per `docs/X_BROWSER_CAPTURE.md` (browser available,
   single-session rule).
6. Watch the wave-2 trigger: when GDELT days without a matching
   `events_amend_crypto/` file exceed ~250, schedule the amendment wave
   (`data/digest_v2/crypto_backfill/README.md`).

## 3. Re-arming after a session restart

The AI routine is scheduled via the session's CronCreate (dies with the
session, 7-day cap). In a new session say: "re-arm the daily loop per
docs/DAILY_LOOP.md" — the assistant recreates the 08:43 job with the §2
steps as the prompt.

## Hard boundaries

- The loop NEVER trains, NEVER touches the lockbox, NEVER trades.
- Digestion is Sonnet's; merging/plumbing is code; nothing is deleted
  (retention rule).
