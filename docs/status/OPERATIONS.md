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

### Lingering — done

`sudo loginctl enable-linger eugene` is **on** on the ProDesk (2026-08-04).
Without it, user services stop the moment the SSH session ends, so on a headless
box it is not optional.

## Daily driving

Run these **on the ProDesk** — `ssh -i ~/.ssh/prodesk_ed25519 eugene@100.64.113.103`
first, and use `.venv/bin/python`, not the system `python3`.

```bash
systemctl --user status ai-investing          # is it alive
journalctl --user -u ai-investing -f          # live logs
systemctl --user restart ai-investing         # after a code change — ONCE, see below
.venv/bin/python scripts/daily_status.py      # full health, 17 channels
.venv/bin/python scripts/watchdog.py --test   # prove alerts still reach you
.venv/bin/python scripts/backup.py --list     # what snapshots exist
.venv/bin/python scripts/breaker.py           # is the book halted, and should it be
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

## When the next LIVE order goes out — what to check *(added 2026-08-11)*

Live entries are rare: **nine attempts in the project's life, eight rejected**
(§4.23 — limit prices sent off-tick, fixed and proven against the venue on
2026-08-10). The fix has been verified with a probe but **has never been
exercised by the engine's own order path**, so the next real order is the test.
Nothing needs doing in the meantime; this is what to look at when it happens.

```bash
# 1. did it get filled, and what did we actually send?
cd ~/Projects/AI-Investing && .venv/bin/python -c "
import sqlite3; c=sqlite3.connect('data/journal.db')
for r in c.execute('SELECT ts,symbol,side,status,req_qty,submitted_qty,'
                   'submitted_price,order_type,limit_price,price,reason '
                   'FROM orders WHERE live=1 ORDER BY ts DESC LIMIT 5'):
    print(r)"
```

**1. `submitted_price` must be on a legal tick.** This column is new (§4.23); it
is the number that was missing for five days. For a US name it must have **at
most two decimals**. A third decimal means `snap_to_tick` has a gap — capture the
row before anything overwrites it.

**2. `status` should be `filled`, not `rejected`.** If it is rejected, read
`reason`. `code=602035 "Wrong bid size"` means the tick fix did not hold. Any
*other* code is a new failure and should be treated as unknown, not assumed
related — that assumption is what cost five days last time.

**3. Then check the STOP actually rested.** This is the one that matters most,
and the one currently known to be broken:

```bash
.venv/bin/python -c "
import os,sys; sys.path.insert(0,'engine'); import ai_investing.config
from longport.openapi import Config, TradeContext
t=TradeContext(Config.from_apikey(app_key=os.environ['LONGPORT_APP_KEY'],
  app_secret=os.environ['LONGPORT_APP_SECRET'],
  access_token=os.environ['LONGPORT_ACCESS_TOKEN']))
for o in t.today_orders():
    print(o.symbol, o.side, o.order_type, o.quantity, o.price, o.status)"
```

You want a resting `MIT` (stop) and usually a `LIT` (take-profit) alongside the
fill. **As of 2026-08-11 the live AAPL position has neither** — `place_stop`
failed on 2026-08-05, the runner recorded only `exchange_stop_unsupported` with
no reason, and the explanation went to stdout and died in a log rotation. The
stop price that day (282.38) was tick-legal, so **that failure was something
else and its cause is still unknown**. Both paths now snap to the tick and the
runner now journals the reason and prints `!! NO VENUE STOP`, so the next
failure will say why. Look for that line.

**4. The engine log** shows `STOP-SET <sym> @ $X (-Y%, resting at the venue)` on
success. Its absence after a fill is the tell.

> Grep `exchange_stop_unsupported` in `journal.db events` for the history. An open
> position with no venue stop is a risk state, not a footnote: the engine's own
> cycle stop still applies, but it only fires when a cycle runs, which is exactly
> the protection an overnight gap defeats.

## What will actually message you

Every alert must answer *"what do I do about this?"*. Anything that does not is
noise, and noise is not harmless — three separate times it has buried a real
diagnosis (STATE §4.7, §4.15/11, §4.16).

| You get a message when | You do NOT get one when |
|---|---|
| A book halts (🛑 breaker) — **once**, on the latching cycle | ...on the 100 cycles it stays halted |
| A symbol **starts** or **stops** being data-flagged | ...on every cycle in between |
| The engine starts after being **down >15 min** | ...on a deploy restart or a quick bounce |
| A trade fills above `ALERT_MIN_NOTIONAL` | ...for decisions it merely considered |
| The watchdog sees a crash loop, a stall, or a dead channel | |
| `needs_you.py` has a decision that is genuinely yours | |

**If you get a burst of identical messages, that is a bug — report it.** It means
something is announcing a *state* instead of an *event*, and it has happened three
times. The engine's own start message was the third, and it took the user pointing
at eighteen of them.

**Silence is a report.** A healthy engine restarting says nothing on purpose. To
check it is alive, don't wait for a message — ask:

```bash
systemctl --user show ai-investing -p ActiveState -p NRestarts
.venv/bin/python scripts/daily_status.py | tail -5
```

`NRestarts` climbing on its own is the crash-loop signature. `0` is what you want.

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

## Where it runs — DONE, 2026-08-04

**The books live on the ProDesk, not the ThinkStation.** Everything below
assumes that.

| | |
|---|---|
| Host | `eugene-HP-ProDesk-400-G6` — 12 cores, 14 GB, always on |
| Reach | `ssh -i ~/.ssh/prodesk_ed25519 eugene@100.64.113.103` (Tailscale) |
| Repo | `~/Projects/AI-Investing`, venv at `.venv/` |
| Supervised | engine, chat bot, **dashboard** (new — was unsupervised anywhere before), watchdog / backup / logrotate / digest / needs-you timers |
| Crons | the 3 data pulls (RSS accumulate, market refresh, crypto refresh) |
| Linger | **on** — survives SSH logout and reboot |
| Dashboard | `http://100.64.113.103:4300` |

### If SSH says "Tailscale SSH requires an additional check"

Seen 2026-08-05. **Nothing is down** — the engine does not use SSH, and the box stays
reachable (`tailscale status` shows `active; direct`, ping answers). What has expired
is the *interactive login authorization*, not the machine.

The tailnet's SSH rule uses `"action": "check"`, which forces a browser re-auth every
`checkPeriod` — **12 hours by default**. It is a deliberate Tailscale feature: a stolen
laptop cannot hold a shell open forever. A key does not bypass it; Tailscale SSH
intercepts port 22 before any key is considered, so `prodesk_ed25519` gets the same
prompt.

| | |
|---|---|
| **Unblock now** | Open the `https://login.tailscale.com/a/…` URL the SSH client prints, approve, re-run the command |
| **Stop it recurring** | Admin console → Access Controls → change the SSH rule's `"action": "check"` to `"action": "accept"` |
| **Keep the check, lengthen it** | Leave `"check"` and set `"checkPeriod": "720h"` (30 days) |

`accept` still requires tailnet membership and an authorized device; it removes only
the periodic browser step. That is the right trade for a headless box that must be
reachable at any hour — a security control that locks *you* out of a machine you need
during an incident has a cost, and it is not zero.

**The residual risk is Tailscale itself.** If the tailnet is unreachable there is no
remote path in at all — `ufw` scopes every ALLOW rule to `tailscale0`. Recovery is
physical or via the LAN. Acceptable for a home machine; worth knowing before it
matters.

The ThinkStation is now a **dev box only**: its engine, chat and timers are
stopped and disabled and its crontab is cleared, so nothing here writes to the
books. The repo, `.env` and `data/` are still present for development — which
means `data/` here is a **stale snapshot**, not the live record. Never reason
about the portfolio from the ThinkStation's `data/`; ask the ProDesk.

`LOCAL_LLM_URL` is empty, so no GPU or Ollama is needed.

### Migration recipe (kept, in case it is ever needed again)

1. `git clone`, restore `.env` (gitignored — copy it manually).
2. `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`
3. Copy `data/` across, or restore the newest `data/backups/state-*.tar.gz`.
4. Copy `~/.config/systemd/user/ai-investing*` and `systemctl --user daemon-reload`.
5. `sudo loginctl enable-linger <user>`
6. `systemctl --user enable --now` the units and timers.
7. Re-add the three data crons (`crontab -l` on the old box).
8. `python3 scripts/watchdog.py --test` — if the Telegram message does not
   arrive, nothing else here is trustworthy.
9. **Stop and disable everything on the old box, and clear its crontab.** Two
   hosts running one set of books is the worst outcome of a migration; it is
   silent and it corrupts the forward record.

---

## Developing against it over SSH

The box is headless and the engine is live on it, so the loop is: **edit and
test here, deploy by pulling there.** Never edit source on the ProDesk — a
change that exists only on the trading box is a change with no history.

```bash
PD="ssh -i ~/.ssh/prodesk_ed25519 eugene@100.64.113.103"

# 1. develop on the ThinkStation, run the suites locally, commit, push
# 2. deploy
$PD 'cd ~/Projects/AI-Investing && git pull --ff-only'
# 3. prove it on the box that matters BEFORE restarting anything
$PD 'cd ~/Projects/AI-Investing && for t in engine/tests/test_*.py; do
       .venv/bin/python "$t" >/dev/null 2>&1 || echo "FAIL $t"; done; echo done'
# 4. only then
$PD 'systemctl --user restart ai-investing'
# 5. and confirm
$PD 'cd ~/Projects/AI-Investing && .venv/bin/python scripts/daily_status.py | tail -20'
```

There is no test runner script — each `engine/tests/test_*.py` is a standalone
program that exits non-zero on failure. The loop above is the runner. 24 suites,
~40s on the ProDesk.

**`git pull` on the ProDesk needs a forwarded agent.** The box deliberately
holds **no GitHub key** — one less credential on the machine that trades. It has
`~/.ssh/config` mapping the `github-eugene` host alias to github.com, and
nothing else. So any command that talks to GitHub must be run over `ssh -A`,
with the key loaded in the ThinkStation's agent:

```bash
ssh-add -l | grep eug.law.ys        # the GitHub key must be listed
ssh -A -i ~/.ssh/prodesk_ed25519 eugene@100.64.113.103 \
    'cd ~/Projects/AI-Investing && git pull --ff-only'
```

Without `-A` this fails with *"Please make sure you have the correct access
rights"* — which reads like a permissions problem on GitHub and is not.

### Two rules that come from actual incidents

- **Do not restart to verify.** Restarting the engine refetches all ~88 symbols
  at once; four restarts in twenty minutes is what throttled the price feed on
  2026-08-04 (§4.11). One restart, then read the logs.
- **Read-only diagnosis is free — use it.** `daily_status.py`, `breaker.py`,
  `needs_you.py --show` and `backup.py --list` all run against the live state
  without touching it, and answer nearly every question worth asking.

---

## Security posture of the 24/7 box

*Audited 2026-08-04, the day it became always-on. Reachable means reachable by
someone who is not you.*

### What is already right

Worth stating, because the list below is all problems and the baseline is good.

| | |
|---|---|
| SSH | keys only — `PasswordAuthentication no`, `KbdInteractiveAuthentication no`, `PermitRootLogin no` |
| Firewall | `ufw` active, `DEFAULT_INPUT_POLICY=DROP`, and every ALLOW rule is scoped **`on tailscale0`**. `sshd` binds `0.0.0.0:22` but nothing off the tailnet can reach it. |
| Exposure | listening sockets are :22, :4300 (dashboard), :631 and :53 on loopback only |
| Secrets | `.env` is `0600`, and **no template is tracked at all** — `.env.example` held a real exchange key and secret for months (STATE §4.18) and was deleted 2026-08-05. Generate one with `python3 scripts/env_template.py`. |
| Money | `LIVE_TRADING=false`, and `brokers/get_broker()` is a **single choke point** — it returns `PaperBroker` unless the flag is set, so a missing SDK or a stray key cannot route a real order |
| Telegram | the chat bot checks `sender != self.chat_id` on **both** the message and the inline-button paths before acting. Verified in `alerts/chat.py`, not just claimed in its docstring. |
| Patching | `unattended-upgrades` enabled |
| Key | `~/.ssh/prodesk_ed25519` is passphrase-protected, so the file alone is not access |
| Data dirs | `data/` and the repo root tightened to `750`, `data/backups/` to `700` |

### Broker credentials — resolved 2026-08-04

Both broker credentials on the box now point at **accounts that hold nothing of
yours**: Longbridge at a paper account, Gemini at a separate empty account
(`account-` scoped, Trading only, no withdraw/deposit-address rights, IP-locked
to the home address). `--check-broker` returns `[ok]` on both.

The Gemini key that reached the real holdings — 19 currencies — was replaced, not
merely removed from `.env`. **Removing a secret from a file does not revoke it;
revoke it at the provider**, or every copy that ever existed stays valid.

`CRYPTO_SANDBOX` is now `false`, so `LIVE_TRADING=false` and the `get_broker()`
choke point are the only barriers left in front of live crypto. Acceptable
because the account is empty and segregated. It would not be otherwise.

Longport tokens expire **90 days** from issue — the current paper one dies around
**2026-11-02** — and refreshing invalidates the old token, which is also how you
revoke one.

### For history: what the original audit found here

`.env` holds **production** credentials — `LONGPORT_ACCESS_TOKEN`,
`LONGPORT_APP_KEY`, `LONGPORT_APP_SECRET`, and `CRYPTO_API_KEY` /
`_SECRET` / `_PASSWORD` — on a machine that trades nothing but paper and has
never validated a broker adapter. `STOCK_BROKER=longbridge` is already set, so
the only thing between those keys and a real order is one boolean.

Nothing reads them today. That is the point: **the risk is entirely unearned.**
Keep them off the box until the sandbox validation that gates live trading has
actually happened, and the worst outcome of a compromise drops from "someone
trades my brokerage account" to "someone reads a paper portfolio."

If they must stay, scope them at the provider — trade-only, **withdrawals
disabled**, IP-allowlisted. An exchange key that can withdraw is a different
category of object from one that can only trade.

### Passwordless sudo

`sudo -n true` succeeds, so anyone holding the SSH key — including an agent
being helpful — has uncontested root. Nothing here needs root at runtime:
lingering is already enabled, the units are `--user`, and the firewall is set.
Requiring a password for `sudo` costs one prompt on the rare occasions it is
needed and removes root from the blast radius of a stolen laptop.

### The dashboard gate that could not be switched on

`dashboard/middleware.ts` implements Basic Auth, gated on `DASHBOARD_USER` /
`DASHBOARD_PASSWORD`, and both are empty — so the dashboard serves the full book
to anyone on the tailnet. That much was known.

What was not: **setting them in the repo-root `.env` would have done nothing.**
Next.js loads `.env` from `dashboard/`, there is no `.env` there, and the systemd
unit passed no environment at all. The variables would have stayed `undefined`,
`middleware` would have returned `NextResponse.next()`, and the dashboard would
have looked protected while being open — the project's signature failure, a
safeguard that reports success and does nothing.

Fixed by giving the unit `EnvironmentFile=-%h/.config/ai-investing/dashboard.env`
— a separate file, so a Node process is not handed every broker and LLM key to
serve two strings. To close the gate:

```bash
mkdir -p ~/.config/ai-investing
printf 'DASHBOARD_USER=eugene\nDASHBOARD_PASSWORD=<pick one>\n' \
  > ~/.config/ai-investing/dashboard.env
chmod 600 ~/.config/ai-investing/dashboard.env
systemctl --user restart ai-investing-dashboard
curl -si localhost:4300 | head -1        # must be 401, not 200
```

That last line is not optional. It is the only thing that distinguishes this
from the state it was just in.

### The live book: trading a slice of a big account

The 📈 trading book routes to the Longbridge **paper** account as of 2026-08-04,
bounded to **$10,000** by `LIVE_CAPITAL_BASE`. The other three books are
untouched and still simulated — `LIVE_TRADING` only switches `self.broker`.

```
LIVE_TRADING=true
LIVE_CAPITAL_BASE=10000            # the slice; 0 = the whole account
SAFETY_MAX_NOTIONAL_PER_DAY=10000  # one full turnover a day, no more
TRADE_APPROVAL=true                # entries still come to you on Telegram
```

Why the slice exists: the account holds USD 1,000,000, and every risk limit here
is a *fraction of equity*. Attached raw, `RISK_MAX_POSITION_WEIGHT=0.15` means a
$150,000 position and the daily breaker sits at −$50,000 — the whole stake could
be lost several times over without a breaker firing. With the slice, the limits
mean what they say:

| | |
|---|---|
| max single position | **$1,500** |
| max gross exposure | **$10,000** |
| daily breaker halts at | **−$500** |
| hard per-position loss cap | **$150** |

Tradable universe is **48 USD-listed stocks** of the 85 in the watchlist. The 37
non-USD listings are excluded because `cost_price` arrives in the listing currency
while prices here are USD-normalised; crypto is excluded because the segregated
Gemini account is empty.

**Autonomous since 2026-08-04.** `TRADE_APPROVAL=false` — the engine enters and
exits without asking. Stop-losses and take-profits **rest at the broker**
(`EXECUTION_STOP_AT_EXCHANGE=true`, `MIT` for stops, `LIT` for take-profits), so
they fire on an overnight gap or while the engine is down. Verified live on the
paper account: submit → confirmed fill → stop and TP resting → cancel → exit.

### What the bot asks you (inference consultation)

Autonomy left a gap: with `TRADE_APPROVAL=false` the bot stopped asking anything
about its *reasoning*, and the per-trade prompt it replaced was the wrong
question anyway — by the time you see "buy NVDA for $4,200", the only honest
answer is whether you trust the sizing formula. The judgement you can actually
add is upstream, on the **leap** from news to meaning.

So the one unprompted question is now:

```
🧠 Do you agree with this read?
📰 What I saw:      2-3 headlines
🔍 My read:         the inference it drew
🤔 Resting on:      the assumption that inference needs
                    [👍 agree] [😐 not sure] [👎 disagree]
```

A tap is a **weight, not a veto**, and it lands on the next cycle — it scales
the impulse that reading sends into the graph, so node activations, asset
impacts, conviction and position size all move with it.

| tap | effect |
|---|---|
| 👍 agree | ×1.30 — positions resting on the read size up (risk limits still cap) |
| 😐 not sure | ×0.85 — real scepticism, not silence |
| 👎 disagree | ×0.45, and it may only be outvoted by fresh evidence past `max(0.60, 1.5 × the disputed conviction)` — **and you are told when that happens** |
| 👎 again | blocked outright for the TTL; no override at any conviction |
| no answer | ×1.00 — silence is neither consent nor dissent |

Opposite-signed news on a damped node is **never** damped: that is the evidence
that should change your mind, and silencing it would be the worst failure here.

`/inferences` (or ⚖️ my reads) shows what's open, what you've weighted, and your
running record. Unanswered reads join the `needs_you.py` digest — unlike a dead
trade proposal they are live work, since they steer at full weight until you
weigh in. Every ask, tap and override appends to `data/inference_log.jsonl`.

Knobs: `CONSULT_ENABLED`, `CONSULT_ASK_BAR` (0.20 — measured: ~2.6 asks per active day; 0.25 → ~1.9, 0.15 → ~3.9), `CONSULT_MAX_ASKS` (2 per
cycle — a hard cap, flooding you is the failure mode being fixed),
`CONSULT_TTL_HOURS` (72).

**Not calibrated yet.** `consult.trust_factor()` is the hook for learning how
much your taps are worth from the log; it returns 1.0 (or an operator override in
`data/inference_trust.json`) until a price-based grader exists. It is deliberately
not faked: grading your objection against the brain's own field — which your
objection already damped — is circular and would read as learning while
manufacturing agreement with itself.

Legacy per-trade approval still exists behind `TRADE_APPROVAL=true` (`/pending`),
but is off the button menu.

All four books were reset to **USD 10,000** on 2026-08-05 (`STARTING_CASH`,
`INVEST_STARTING_CASH`, `EVENT_START_CASH`, `CRYPTO_START_CASH`). Retired state is
in `data/retired/`; the brain, journal and learning ledger were kept.

**Expect few or no fills for now, and it is not a fault.** 12 of the 13 decisions
clearing the confidence floor are shorts, which the venue refuses, and the single
qualifying long is non-USD, which the live slice excludes. Check with:

```bash
grep -E "not tradable in the live slice|FILLED|PENDING" data/engine.log | tail
```

**Shorting is off in live, because neither paper venue supports it.** Checked
2026-08-04 rather than assumed:

- **Longbridge** — shorting requires a margin account ("Integrated A/C"); cash
  accounts cannot. `estimate_max_purchase_quantity` (the call Longbridge's own
  docs name for short capacity) returns `margin_max_qty=0` on the **Sell** side
  for AAPL and MSFT while the **Buy** side returns 4001 and 2490. The account also
  reports `init_margin=0`, `maintenance_margin=0`, `risk_level=0` — it behaves as
  a cash account.
- **moomoo** — documented outright: short selling in paper trading is available
  for options and futures, **not for stocks**. It would also mean running the
  OpenD gateway 24/7 on a headless box, which is a real operational cost for no
  gain here.

So `RISK_ALLOW_SHORT=false` in live. Note the consequence: the 📈 book previously
held shorts (twelve of them, until §4.7 flattened it), so the live book is a
strictly long-only version of the same policy and its record is not directly
comparable to the paper history before it. `docs/research/SHORT_STRATEGY.md`
already reports shorts failing six independent tests here, so little is lost —
but it is a policy change forced by the venue, not a choice.

Also confirmed while looking: Longbridge does **not** support resetting demo
funds ("please contact customer service"), which is why the slice is enforced in
the engine rather than by shrinking the account.

**Changing `LIVE_CAPITAL_BASE` re-bases the breaker's marks** and resets the
per-day counters — announced on Telegram and in the log. That is deliberate: the
marks describe a book, and you just changed the book. It does **not** clear a
latched halt.

To go back to pure paper: set `LIVE_TRADING=false` and restart. `paper_state.json`
was never deleted, so the old $99,997 book is still there. The breaker re-bases
back on the next cycle.

Watch it with:
```bash
grep -E "=== cycle|LIVE BOOK|BREAKER|no new positions" data/engine.log | tail -20
```

**If it stops opening positions, read that grep before anything else.** It logs
its own reason every cycle — `max notional/day reached`, `max trades/day`, a
halt — and a book that had spent its notional budget sat idle for nine hours
because nobody looked (§4.14).

### Backups exist on exactly one disk

`scripts/backup.py` writes to `data/backups/` and nowhere else — no rsync, no
remote, no cloud. Since nothing here is real money, the **forward record is the
most valuable thing on the machine**, and it has no second copy. It is also the
one asset that cannot be regenerated: re-running the engine does not reproduce a
paper trading history.

`scripts/pull_backup.sh` copies the sealed snapshots to whatever machine you run
it from and verifies the newest one reads as a tar. It **pulls** rather than
pushes on purpose — the ProDesk holds no credential to the archive, so anything
that compromises it cannot delete the copies. Run it when you SSH in; it is
manual because the SSH key has a passphrase and stripping that to satisfy a cron
would be a worse trade.

### Known and accepted

- **Tailscale is the whole perimeter.** Any device on the tailnet reaches
  everything. Tailscale ACLs would segment this; not configured.
- **The dashboard binds `*:4300`**, not the Tailscale address. `ufw` makes this
  moot today, but the bind is one firewall mistake away from being the exposure.
- **`ssh -A` agent forwarding** during deploys lets a compromised ProDesk use
  your forwarded GitHub key for as long as the session is open. Acceptable for
  short deploy commands; do not leave such a session idle.
