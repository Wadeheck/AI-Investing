# The daily news loop — runbook

*Created 2026-08-01, updated 2026-08-03. The loop that keeps the brain
current. Data pulls, process lifecycle and health all run under systemd
(see [`docs/status/OPERATIONS.md`](../status/OPERATIONS.md));
the digestion routine is session-bound — RE-ARM IT when starting a fresh
session, see §3.*

## 1. Always-on data pulls (systemd user timers)

Moved off cron 2026-08-11 — see "Why timers, not cron" below. Units live in
`deploy/systemd/`; log filenames keep their `_cron` suffix so history and
`logrotate.conf`'s `data/*.log` glob stay continuous.

- `ai-investing-accumulate.timer` (`*-*-* 00/4:17:00`) —
  `scripts/accumulate_once.py`: pulls all ~44 RSS/alt feeds into
  `data/news_archive_live.jsonl` + the brain store. Log:
  `data/accumulate_cron.log`.
- `ai-investing-market-refresh.timer` (`*-*-* 07:53:00`) —
  `scripts/refresh_market_data.py`: ALL signal/indicator numbers, daily —
  stablecoin supply (DefiLlama), Fear&Greed, BTC/ETH ETF flows (Farside),
  DVOL (Deribit), CFTC COT, Guardian archive top-up. Free sources only, no
  keys. Log: `data/market_refresh_cron.log`.
- `ai-investing-crypto-live.timer` (`*-*-* *:11:00`) —
  `scripts/refresh_crypto_live.py`: HOURLY crypto inputs (funding rates,
  Fear&Greed, on-chain activity, Binance long/short ratio + open interest).
  Crypto trades 24/7, so these cannot sit on the equity clock. Log:
  `data/crypto_refresh_cron.log`.

All three are `Persistent=true` and gated on
`ExecStartPre=scripts/wait_online.sh`, which blocks until DNS resolves. The
gate is not decorative: systemd starts the *user* manager ~5s before
`network-online.target` (measured at the 2026-08-11 boot: user@1000 at
boot+6.3s, network-online at boot+11.1s), and these scripts catch their own
per-source exceptions and still exit 0 — so a catch-up run firing into that
hole would be recorded as a success and consume the catch-up, leaving the
data stale until the next tick.
- The GDELT crypto crawler (`gdelt_crypto_fetch --loop`) is long-running and
  resumable; restart it in any session if dead:
  `cd engine && python3 -m ai_investing.research.gdelt_crypto_fetch --loop`
  (single instance only — it appends to one file).

## 2. Daily AI routine (once per day, after ~08:30 SGT)

RULE: gather from EVERY source (news text + signal/indicator numbers + X),
then assign digestion to a Sonnet subagent via the Claude Code Agent tool
(model: sonnet). NO external AI APIs, ever.

**Step 0 — one command tells you what's due:**
```
python3 scripts/daily_status.py      # exit 1 if anything is STALE
```
It checks RSS freshness, market numbers, X capture age, GDELT state,
yesterday's digest, impulse currency, engine/book state, and the crypto
wave-digestion backlog trigger. Do only what it flags.

1. **News text**: `scripts/accumulate_once.py`; verify the 07:53 numbers
   refresh ran (else run `scripts/refresh_market_data.py`).
2. **X capture — DAILY, via Claude in Chrome** (`docs/data-pipeline/X_BROWSER_CAPTURE.md`):
   rule 1 first (ONE session ever; skip if `news_archive_x.jsonl` was
   modified in the last 15 min). Then, per profile in the roster: navigate
   to `x.com/<handle>`, wait ~3s, run the drain harvester (§2 — small
   scrolls, self-terminating on 8 dry steps), read `window.__cap` in slices,
   move on. Feed the collected rows straight to the ingester:
   ```
   python3 scripts/x_capture_ingest.py harvest.json --note "daily <date>"
   ```
   It handles dedup by status id, promo/ad filtering, exact timestamps
   (snowflake fallback), title/summary split, and append-only day-records —
   the browser session only has to harvest.
3. Build YESTERDAY's (UTC) day-input from ALL live sources
   (`news_archive_live.jsonl` + `news_archive_x.jsonl` +
   `news_archive_gdelt_crypto.jsonl` + `news_archive_guardian.jsonl`),
   title-deduped, plus the trailing ledger extract (~55 entries).
4. ONE Sonnet agent digests the complete day per
   `docs/data-pipeline/SONNET_DIGEST_BRIEF.md` → `data/digest_v2/events/<date>.json`
   (overwrites any partial-day file; mark `"redigest": "full-day"`).
5. `python3 data/digest_v2/_merge_amendments.py` — rebuilds ledger +
   `news_impulses_v2.jsonl`. THIS is the step that updates the brain's food.
6. Re-run `scripts/daily_status.py` — everything should read OK.
7. Watch the wave trigger: >250 undigested GDELT days ⇒ schedule an
   amendment wave (`data/digest_v2/crypto_backfill/README.md`).

## 2b. Recovery after a shutdown (automatic)

Nothing needs remembering. Cron does not catch up on jobs missed while the
machine was off, and crypto trades through the gap — so recovery is built in:

- **systemd owns the engine** (2026-08-03). `ai-investing.service` runs
  `scripts/startup_heal.py` as `ExecStartPre`, then the engine, with
  `Restart=always` — so it recovers from a crash, not just a reboot. The old
  `@reboot scripts/boot_start.sh` cron entry was REMOVED: two supervisors
  racing to start the engine risks two engines writing one set of books.
  See [`docs/status/OPERATIONS.md`](../status/OPERATIONS.md).
- Timers use `Persistent=true`, so a job missed while the machine was off runs
  on the next boot instead of being skipped — which plain cron does not do.
- **Self-heal** measures the downtime from the heartbeat, refreshes whatever
  went stale (crypto signals first — they rot fastest), writes a `gap` entry
  into `data/crypto_journal.jsonl` recording the blind window honestly, and
  prints the healed status.
- **Books persist** (`paper_state`, `crypto_state`, `event_state`,
  `invest_state`) and every holding is re-judged on the first cycle back —
  hard stops evaluated FIRST, against current prices.
- **Singleton guard**: both `run.sh` and `boot_start.sh` refuse to start a
  second engine. Two engines on one set of books would corrupt the record.

## 3. Re-arming after a session restart

The AI routine is scheduled via the session's CronCreate (dies with the
session, 7-day cap). In a new session say: "re-arm the daily loop per
docs/data-pipeline/DAILY_LOOP.md" — the assistant recreates the 08:43 job with the §2
steps as the prompt.

## Hard boundaries

- The loop NEVER trains, NEVER touches the lockbox, NEVER trades.
- Digestion is Sonnet's; merging/plumbing is code; nothing is deleted
  (retention rule).
