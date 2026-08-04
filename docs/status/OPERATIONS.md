# Running this unattended

*For a headless mini PC reachable only over SSH. Written 2026-08-03, after a
session in which an 11.9h silent outage, a corrupted-unit portfolio, and a
whole-book price blackout were all found by accident rather than by alarm.*

---

## The principle

Every failure this project has actually had shared one property: **the system
knew, and nobody was told.** `daily_status.py` computed the truth and printed
it to a terminal no one was watching. The engine died and stayed dead because
nothing was watching either. The live tagger discarded 57% of the news for
months with every check green.

So the hardening is not "add more checks". It is: *make the checks act.*

## What supervises what

```
systemd --user
├── ai-investing.service            engine     Restart=always, RestartSec=20
├── ai-investing-chat.service       Telegram   Restart=always  (own lifecycle!)
├── ai-investing-watchdog.timer     every 15m  alerts to Telegram on failure
├── ai-investing-backup.timer       daily      snapshot books + brain.db
└── ai-investing-logrotate.timer    weekly     keeps the disk from filling
```

`Restart=always` with `StartLimitBurst=0` means it never gives up retrying. A
supervisor that stops after N attempts reintroduces exactly the silent outage
it was added to prevent.

`Persistent=true` on the timers matters more than it looks: **cron does not run
jobs it missed while the machine was off**, which is why a powered-down night
used to mean a skipped health check. systemd fires them on the next boot.

The old `@reboot boot_start.sh` cron entry was **removed**. Two supervisors
racing to start the engine risks two engines writing one set of books.

### One-time step, needs your sudo

User services stop when you log out unless lingering is on. For a headless box:

```bash
sudo loginctl enable-linger eugene
```

Without this, everything above dies the moment your SSH session ends.

## Daily driving

```bash
systemctl --user status ai-investing          # is it alive
journalctl --user -u ai-investing -f          # live logs
systemctl --user restart ai-investing         # after a code change
python3 scripts/daily_status.py               # full health, 14 channels
python3 scripts/watchdog.py --test            # prove alerts still reach you
python3 scripts/backup.py --list              # what snapshots exist
python3 scripts/breaker.py                    # is the book halted, and should it be
```

### If you get a 🛑 CIRCUIT BREAKER alert

The engine halts and stays halted — deliberately. You now get the alert **once**,
on the cycle that latches, not every five minutes (see STATE §4.7).

```bash
python3 scripts/breaker.py                    # status + cross-check vs the journal
python3 scripts/breaker.py --repair-marks     # only if it reports POISONED MARKS
python3 scripts/breaker.py --clear            # release, once you agree it was spurious
```

Read the cross-check before deciding anything. It compares the stored marks
against every trustworthy equity row in `journal.db`, and reports `MARKS ARE
POISONED` when a mark sits above the highest equity the book ever honestly
recorded. That is the signature of a halt triggered by a data fault rather than a
loss — and it must be repaired *before* clearing, because the poisoned mark
survives the halt and will re-trip it, eventually on the trailing horizon, which
needs a manual reset.

Clearing does **not** reopen the closed positions. The engine re-decides from
current signals, which is the right behaviour: reinstating positions the strategy
did not choose today would be fabricating a decision.

**After editing `chat.py` you must restart the chat service separately.** It is
its own process and does not restart with the engine — that is how it spent a
day serving a stale portfolio format from memory.

**Never edit a running `.sh` script.** bash reads scripts incrementally;
shifting the bytes under a running shell caused a whole-stack crash and the
11.9h outage. Edit, then restart.

**Do not restart repeatedly to verify a fix.** Each cold start refetches all ~88
symbols at once, and four restarts inside twenty minutes was enough to trip
yfinance's rate limit — turning a verification step into the next incident
(STATE §4.11). Batch your changes, restart once, then read `data/engine.log`.

### If prices go to zero across the board

```bash
grep "DATA GUARD" data/engine.log | tail -1        # how many symbols, and which
python3 -c "import json;print(len(json.load(open('data/last_good_bars_stock.json'))['symbols']))"
python3 scripts/breaker.py                         # confirm it did NOT halt
```

A blanket zero is the provider throttling, not 88 simultaneous delistings. What
*should* happen now, and what to confirm:

- `LastGoodBarCache` serves the last good bars from disk (both legs, aged out at
  6h). It survives a restart as of 2026-08-04; before that it did not.
- Valuation falls back to **cost basis**, so equity reads "no change" rather than
  a collapse, and books record `stale_marks` plus a per-position `stale_mark`.
- The breaker **refuses** an unreadable equity: gate shut, no flatten.
- Decisions and stops skip flagged symbols entirely.

So the correct response is usually **nothing**. Do not restart — that makes it
worse. Wait for the limit to reset; the books hold at cost until it does. Only
investigate if the breaker halted, or if `stale_marks` stays non-zero for hours
after the guard stops flagging.

## What is protected, and what is not

| Failure | Response |
|---|---|
| Process crashes | systemd restarts in ~20s |
| Machine reboots / power cut | services auto-start, `startup_heal.py` refreshes stale data and journals the gap |
| Power cut *mid-write* | atomic writes: temp file + fsync + `os.replace`, so a crash loses the newest write, never the file |
| Feed throttled (all symbols empty) | `LastGoodBarCache` serves last good bars; stops never see a fabricated 0 |
| Guard-flagged bad price | withheld from the stop path — an unfired stop is recoverable, a phantom liquidation is not |
| One LLM endpoint dies | fails over across three authorized access points |
| Anything unhealthy > 15 min | Telegram alert, rate-limited to one per issue per 6h, with a recovery message |
| Disk filling | weekly rotation + watchdog alerts below 10% free |
| Bad data written correctly | daily snapshot, 21 days retained |

**Not protected — know these:**

- **All three LLM endpoints are one provider.** A BytePlus or network outage
  takes all three; the tagger degrades to keyword matching (dumber, not blind).
- **Backups sit on the same disk.** They survive corruption and bad writes, not
  a dead SSD. Copy `data/backups/` off the box if that matters.
- **One machine, no failover.** Hardware death is downtime until you intervene.
- **Alert delivery depends on Telegram + network.** If the box loses
  connectivity entirely it cannot tell you it is unreachable. A dead-man's
  switch (external service expecting a periodic ping) would close this; not
  built.

## Moving to the mini PC

1. `git clone`, restore `.env` (it is gitignored — copy it manually).
2. `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`
3. Copy `data/` across, or restore the newest `data/backups/state-*.tar.gz`.
4. Copy `~/.config/systemd/user/ai-investing*` and
   `systemctl --user daemon-reload`.
5. `sudo loginctl enable-linger <user>`
6. `systemctl --user enable --now ai-investing ai-investing-chat
   ai-investing-watchdog.timer ai-investing-backup.timer
   ai-investing-logrotate.timer`
7. Re-add the three data crons (`crontab -l` on the old box).
8. `python3 scripts/watchdog.py --test` — if the Telegram message does not
   arrive, nothing else here is trustworthy.

`LOCAL_LLM_URL` is empty, so no GPU or Ollama is needed on the new box.
