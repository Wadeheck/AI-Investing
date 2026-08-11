# Verifying a nightly-rest cycle

Checklist for confirming that prodesk's nightly power cycle
(`nightly-rest.timer`, 05:00 → `rtcwake -m off -s 9000` → 07:30 wake) completed
cleanly and that everything scheduled around it either ran or caught up.

Run it the morning after any change to `nightly-rest.timer`, to
`apt-daily-upgrade`'s schedule, to the unattended-upgrades reboot policy, or to
any timer that fires between 04:00 and 09:00.

**First cycle to verify: the morning of 2026-08-12.** Everything below was put
in place on 2026-08-11 and has never run end to end. The `rtcwake` *mechanism*
was proven with a 240-second test (powered off 17:50:53, returned 17:55:07), and
the RTC timebase is correct (`RTC in local TZ: no`, `rtcwake` assumes UTC — they
agree), but the full 2.5-hour cycle has not happened yet.

---

## A. Did prodesk wake at all?

```bash
ssh prodesk 'uptime -s; journalctl --list-boots --no-pager | tail -3'
```

Expect a boot at **~07:30**, and the previous boot ending **~05:00**.

**If prodesk is unreachable, it did not wake — this is the failure mode that
matters most.** Nothing on prodesk can report it; the signal is the stale-backup
Telegram alert from thinkcentre at ~08:17 (section C). Recovery is the physical
power button, then check in this order: whether the kernel changed overnight
(`ssh prodesk 'uname -r'` vs the pre-cycle 7.0.0-29-generic), then
`sudo rtcwake -m no -s 300` to confirm the alarm still arms, then firmware/PSU.
prodesk is deliberately **not** kernel-pinned, so an unattended kernel upgrade
applying at the 05:00 poweroff is the first hypothesis worth testing.

## B. Did the update reboot fold into the poweroff?

`Automatic-Reboot` is `"false"`; the 05:00 poweroff is meant to *be* the update
reboot, with `apt-daily-upgrade` moved to 22:30 to feed it.

```bash
ssh prodesk '
  systemctl status apt-daily-upgrade.service --no-pager | head -5
  grep -iE "Reboot scheduled|All upgrades installed" /var/log/unattended-upgrades/unattended-upgrades.log | tail -3
  echo "running: $(uname -r)  newest: $(ls -1 /boot/vmlinuz-* | sed "s|.*/vmlinuz-||" | sort -V | tail -1)"
  ls /var/run/reboot-required 2>/dev/null || echo "no reboot pending"'
```

- The upgrade should have run at **~22:31**, not as a post-wake catch-up.
- **No "Reboot scheduled" line.** If one appears, `Automatic-Reboot` is being
  overridden — check for stray files in `/etc/apt/apt.conf.d/` (backups do not
  belong there; the pre-change copy was moved to `/var/backups/apt-conf/`).
- `running` should equal `newest`. If they differ, a kernel was installed and
  the poweroff did not apply it — investigate before the next cycle.

## C. Did the backup alert stay quiet? (runs on **thinkcentre**)

From 05:00–06:00 thinkcentre is awake and syncing to a prodesk that is already
off, so ~12 `frigate-sync` runs fail **by design**. The alert must absorb this.

```bash
ssh thinkcentre '
  journalctl -u frigate-sync.service --since "05:00" --until "06:05" --no-pager | grep -c "Failed"
  journalctl -u telegram-backup-alert.service --since "05:00" --no-pager | tail -5
  ls -la ~/.local/state/frigate-sync/'
```

- **No Telegram message between 05:00 and 08:15.** This is the headline check —
  a false alert here is exactly the noise this was built to remove.
- `telegram-backup-alert.service` will have *run* (via `OnFailure=`) and exited
  silently. That is correct: it is invoked but suppressed.
- **`last-alert` must not exist.** Its presence means an alert was actually
  sent — the quiet window did not hold.
- After the 08:00 thinkcentre wake, `frigate-sync` should succeed again and
  refresh `last-success`.

If an alert *did* fire, check `QUIET_START`/`QUIET_END` in
`telegram-notify/backup-alert.sh` against both hosts' current `nightly-rest`
times — that coupling is the usual cause.

## D. Did the data pulls catch up rather than vanish?

The point of moving these off cron. `refresh_crypto_live` is the one that was
actually losing runs (05:11, 06:11, 07:11 all fall inside the window).

```bash
ssh prodesk '
  grep "crypto live refresh" ~/Projects/AI-Investing/data/crypto_refresh_cron.log | tail -6
  tail -3 ~/Projects/AI-Investing/data/market_refresh_cron.log
  systemctl --user list-timers --no-pager | grep -E "crypto-live|market-refresh|accumulate"'
```

- **crypto-live: exactly ONE catch-up run shortly after the 07:30 wake**, then
  the normal 08:11 tick. Not three. systemd coalesces missed occurrences, which
  is correct for these idempotent overwrite-style refreshes — three replayed
  runs would mean `Persistent=` is behaving unexpectedly.
- **market-refresh: ran at 07:53**, ahead of the 09:20 digest. This one has only
  23 minutes of clearance after the wake; if the wake ever slips past 07:53 the
  `Persistent=` catch-up is what saves the day's market numbers.
- **accumulate**: 04:17 then 08:17, both outside the window — unaffected.

## E. Did the supervised long-runners come back?

```bash
ssh prodesk '
  systemctl --user is-active ai-investing ai-investing-chat ai-investing-dashboard ai-investing-gdelt
  systemctl --user show ai-investing-gdelt.service -p ActiveEnterTimestamp -p NRestarts --value
  wc -l < ~/Projects/AI-Investing/data/news_archive_gdelt_crypto.jsonl'
```

- engine / chat / dashboard active within ~30s of boot (`Linger=yes`).
- **GDELT active, started ~07:40** (`OnBootSec=10min`). This is the whole reason
  it was made a unit: as a hand-started process it died at the 2026-08-08 04:30
  reboot and stayed dead for three days.
- Archive line count **> 304** (its value on 2026-08-11 21:00). Progress is slow
  by design — `--gentle` plus GDELT's rate limiter is roughly one day per
  5–15 min, so expect single-digit growth per cycle, not a jump. The log only
  prints every 50 days, so the line count is the real progress signal.
