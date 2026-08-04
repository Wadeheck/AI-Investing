# State of the system

*Honest engineering status as of 2026-08-04. Written to be read by someone who
has not been watching — including a future me. Where something is unproven it
says so; where a number is soft it says why.*

---

## 1. What this is

An autonomous trading engine for stocks and crypto. A knowledge graph (the
"brain") turns news into causal impulses; four independent policies ("books")
trade off that shared world model; a learning spine grades every trade against
what it predicted and reallocates capital toward demonstrated skill.

**Everything is paper.** `LIVE_TRADING=false`. No broker adapter has ever been
pointed at a funded account. Nothing in this document should be read as
evidence the system makes money with real money.

## 2. Where it stands today

```
GRAPH    321 nodes, 690 edges          (seed v25)
BRAIN    4,923 articles, 1,672 events tagged
TAGGER   2% unsigned across 1,380 recent events     (was 57%)
TESTS    24 suites, all green
COMMITS  131

BOOKS            equity      cash        positions
  trading      $ 99,997    $ 99,997         0   (flat after §4.7; re-entering)
  investing    $ 83,125    $105,356         8
  event sleeve $100,479    $ 87,671         3
  crypto       $100,000    $100,000         0   (bear mode, deliberately flat)
  ----------------------------------------
  TOTAL        $383,601
```

Read **equity**, not cash. Three of these books hold shorts, whose sale proceeds
sit in cash while the shares are still owed — which is why cash exceeds equity in
the investing book, and why cash is never the portfolio's value. Conflating the
two caused §4.4, and valuing a short at a zero price caused §4.7.

**The learning spine has 0 settled claims.** It is armed and tested but has
never actually adjusted anything, because no trade has closed through it yet.
Every claim about how the system "learns" is therefore a claim about design,
not about observed behaviour.

## 3. Architecture in one page

**The brain** (`engine/ai_investing/brain/`) — news → structured events →
impulses on *origin* nodes only → multi-hop propagation with decay → per-asset
impacts. Events tag where a shock *lands* (`oil_supply`), never what it will
affect (airlines); the graph derives the rest. Regime-gated edges, crisis
correlation convergence, τ-delayed edges, per-type half-lives.

**Four books, one brain:**

| Book | Horizon | Mandate |
|---|---|---|
| 📈 trading | days–weeks | field conviction, long/short |
| 🏛 investing | ~6 months | thesis-driven |
| ⚡ event sleeve | 2 days | fresh shocks only, long-only, unlevered |
| ₿ crypto | 24/7 | own bear-exit logic, HODL core + tactical |

**The learning spine** (`docs/design/LEARNING.md`) — Beta posteriors over directional
skill, conditioned on regime; sizing shrunk by sample count; weekly capital
reallocation with floors, ceilings and a rate limit; drift and regime-break
detection. The rule that matters: *the fast loop adjusts sizing and
expectations; only the offline gauntlet may change structure.*

**Two taggers, and this distinction has caused real damage:**
- **Corpus digester** — Sonnet, offline, builds the training corpus. Audited,
  scores 100% on the golden set.
- **Live tagger** — cloud model, in-engine, every cycle. *Was never audited at
  all* until 2026-08-03. See §4.1.

## 4. Failure register

The through-line: **almost every failure here was silent, and passed its health
checks while failing.** Not crashes — wrong answers delivered confidently.

### 4.1 The live tagger discarded 57% of the news *(2026-08-03)*

- **What.** `impulse = polarity × magnitude × credibility`. The local
  `qwen3:8b` returned polarity `0` when unsure, and `0` deletes the event.
- **How found.** Not by a check — by the user asking whether the brain knew
  about a Bitcoin/Hormuz story. Investigating that led to counting.
- **Scale.** 57% of live events contributed literally nothing. The Sonnet
  corpus, by contrast, had 0% zero-polarity. The graph was calibrated on a
  fully-signed world and fed a half-mute one.
- **Fix.** Built `scripts/audit_live_tagger.py` first — the same 50 golden
  items the corpus digester is held to. Then: batches of 10 (recall collapses
  at 25), zero banned with escalation to a second model, and the sign asked for
  **in words** ("more credit stress") rather than as a number.
- **Why words.** Asked for a number the model reported *sentiment* — grim
  headline, negative sign — inverting every stress-type node, since debt,
  spreads and tension all *rise* in a crisis. Sign accuracy 54% → 73%.

```
                        SEEN  UNSIGNED  SIGN  ORIGIN  USABLE
  qwen3:8b  as found     52%     52%     71%    24%     --
  qwen3:8b  after fixes 100%      4%     73%    44%    38%
  DeepSeek-V3.2 (live)   94%      8%     65%    62%    48%
  Sonnet (corpus)         --      0%      --   100%     --
```

- **Lesson.** Two components did the same job; one was audited and one was not.
  The unaudited one was the one in production.

### 4.2 No currency conversion anywhere *(2026-08-03)*

- **What.** Every non-USD holding recorded at its **local** price and summed
  into a USD book. SK Hynix at 1,591,000 KRW read as **$1,591,000 a share**.
- **How found.** The user looked at the Telegram portfolio and asked "is this
  correct?" It was visibly absurd — a $1.59M share price — and nobody had
  looked.
- **Scale.** $9,038 of $16,027 net exposure misstated. Because equity, sizing,
  drawdown and every risk limit derive from those numbers, **all of them were
  wrong together**. `brokers/routing.py` had it filed as "a known v1 caveat".
- **Worst case.** The event sleeve believed it had $3,333 left when it held
  **$87,671** — it had "spent" $84,338 on HK names really costing $10,662, and
  had stopped trading for lack of money it already had.
- **Fix.** `data/fx.py` + conversion at the **data layer**, so bars arrive in
  USD and everything downstream reasons in one unit. Fixing it at the display
  layer would have left the trading maths equally wrong but harder to see.
  Existing positions **restated, not reset** (`scripts/migrate_fx_positions.py`).
- **Lesson.** A caveat written in a docstring is not a mitigation.

### 4.3 An 11.9-hour silent outage *(2026-08-02)*

- **What.** The engine was dead for 11.9h. Every status check said it was fine.
- **Root cause, two layers.** `pgrep -f "ai_investing.main"` matched *its own
  command line* and the chat bot, so the check could never report "down". The
  engine had died because a running `run.sh` was edited — bash reads scripts
  incrementally, so shifting the bytes crashed the stack.
- **Fix then.** `scripts/engine_pid.sh` reading `/proc/<pid>/cmdline`, excluding
  the caller and `--chat`; `daily_status` fails on a >1h stall.
- **Fix now.** systemd `Restart=always`. Nothing restarted a dead process
  before — `boot_start.sh` only ran `@reboot`, so a crash without a reboot
  stayed dead. Verified by `kill -9`: back in under 45s.
- **Lesson.** A liveness check that can match itself is not a liveness check.
  The same trap bit again during this session (`pkill -f` killed its own shell).

### 4.4 The portfolio reported 2 of 4 books *(2026-08-03)*

$103,333 of capital simply absent from the Telegram view, hiding the event
sleeve's paralysis (§4.2). Fixed; all four report with a total line. **An idle
book is information; silence is not.**

### 4.5 Guard-flagged prices reached the stop logic *(2026-08-03)*

- **What.** A yfinance rate-limit returned "possibly delisted" for *every*
  symbol, so the whole book marked at price 0. `DataGuard` correctly flagged it
  and the runner correctly excluded flagged symbols from **decisions** — but
  never from **stops**.
- **Why nothing blew up.** `stop_orders` opens with `if not px: continue`, and
  `0.0` is falsy. An accident of representation, not a safeguard: a *stale but
  positive* tick is truthy and would have liquidated the book at a fabricated
  loss.
- **Fix.** Stops read a filtered dict; `LastGoodBarCache` serves last-good bars
  on a blanket feed failure. An unfired stop is recoverable; a phantom
  liquidation is not.

### 4.6 The scorecard had never run — and then graded an accounting artefact *(2026-08-03)*

- **What.** `SELECT id, ts, advice FROM advice_log`, but the table is declared
  `(ts, advice)` — no `id`. Every cycle raised `OperationalError`, was swallowed
  by the caller's `except`, and printed to a log nobody reads.
- **Scale.** 195 advice lists logged since 2026-07-26, **0 ever graded**.
  `update_reliability` had never run. Found only because the mark-to-market
  work put a fresh eye on the engine log.
- **Then it got worse.** Fixed (`rowid AS id`), it immediately graded the FX
  migration as real: 1211.HK "fell" from 94.15 to 12.19 overnight — a unit
  change, not a move. **72 of 170 outcomes (42%) were FX artefacts**, crediting
  `short_or_avoid` calls with wins they never earned.
- **Consequence.** The reported 30-day hit-rate was **0.689**. After restating
  price history in USD and re-scoring, it is **0.404**. Twenty-eight points of
  the brain's self-assessed skill were an accounting error — and the same
  phantom crash had been pulsed into the graph as a genuine price shock via
  `day_moves`.
- **Fix.** `scripts/migrate_fx_history.py` restates pre-cutover history in USD
  and clears contaminated outcomes for honest re-scoring.
- **Lesson.** A unit change is indistinguishable from a price move to anything
  reading the series. Any migration that alters recorded values must ask *who
  else reads this history* — the same discipline as excluding outage-tainted
  trades from the learning spine.

### 4.7 A feed outage faked a 13.8% crash and flattened a healthy book *(2026-08-04)*

The most expensive failure so far, and the closest to a real-money disaster.

- **What.** At 02:30 UTC, on the first cycle after an overnight gap, every price
  came back `0.0`. The trading book held twelve **shorts**, so cash was inflated
  by the sale proceeds ($116,027) while the shares were still owed. With every
  position valued at zero, `equity` collapsed to exactly `cash`: **$116,027
  reported against a true $99,997.** That reading became both `day_start_equity`
  and the all-time `peak_equity`. At 02:43 prices returned, equity read honestly
  at $99,997, and the circuit breaker measured a **13.8% daily drawdown** against
  a number that never happened. It flattened all twelve positions and latched.
- **Root cause.** `Portfolio.equity` fell back to cost basis only for a *missing*
  key. The runner builds prices as `close if bars else 0.0`, so an outage writes
  a **present-but-worthless** price, and `0.0` sailed through as a valuation. A
  short priced at zero looks like a debt that has been forgiven.
- **The silent precursor.** For five cycles the previous afternoon, equity was
  recorded as `None`/NaN. NaN loses every comparison, so it did not trip the
  breaker — it walked *past* it, overwriting the marks on the way. Hours of
  unvalued book passed every safety check without a word.
- **Why it stayed invisible for 9 hours.** A latched breaker returns
  `flatten=True` on *every* cycle, and the runner alerted on each one — an
  identical Telegram message every five minutes all night. The signal was there;
  it had been made unreadable by repetition. The user's report was *"I keep
  receiving circuit breaker news from telegram"*, not *"the engine halted"*.
- **What it actually cost.** Almost nothing in P&L: the flatten executed at real
  prices in the same cycle the feed recovered, so equity went $100,142 (true
  peak) → $99,997, about **$3** plus a day of a flat, halted book. Pure luck. Had
  prices returned one cycle later, it would have liquidated twelve positions at
  zero.
- **The landmine underneath.** Clearing the *daily* halt would not have fixed it.
  `peak_equity` was still $116,027, so the book was permanently measured as 13.8%
  underwater — **1.2 points from a latched, manual-reset-only trailing halt.**
- **Fixes.**
  - `Portfolio._px` treats any non-finite or non-positive price as *no price* and
    falls back to cost basis, so an outage reads as "no change" — the honest
    reading of "we cannot see the price".
  - `CircuitBreaker.check` refuses an unreadable equity outright: gate shut, **no
    flatten** (an absent valuation is not evidence of a loss), marks untouched.
  - Equity is now valued from `safe_prices` — the same guard-filtered dict that
    already protected the stops (§4.5). Valuation needed it *more*, and earlier.
  - `BreakerDecision.announce` is true only on the latching cycle. Alert on the
    event, never on the state.
  - `scripts/breaker.py` — inspect, cross-check the marks against the journal,
    repair, clear. It reconstructs trustworthy marks by discarding rows where
    `positions > 0` and `equity == cash` to the cent (the phantom signature).
  - Three regression tests in `test_safety.py`.
- **Lesson.** Every threshold in the safety layer is a comparison against a
  *stored mark*. A mark taken from a bad valuation is not a transient error, it
  is permanent damage — every honest reading afterwards is measured against a
  fiction. Guard what the marks are made of, and never let a safety mechanism
  act on a number it cannot vouch for.

### 4.8 Three defects found while fixing 4.7 *(2026-08-04)*

Each was independently capable of causing a later incident.

- **Closing a short left a tombstone.** Buying a short back to flat goes through
  the BUY branch, which never removed the emptied position — only SELL did. After
  the flatten the book persisted *"10 positions"* while holding none. Benign for
  equity (`get_positions` filters them), but a flat book whose equity equals its
  cash is exactly the phantom signature above — the tombstones would have made
  the new repair tool discard a *good* mark. Fixed at the source, plus a test.
- **The self-heal blocked trading behind up to 15 minutes of network calls.**
  `startup_heal.py` ran as `ExecStartPre` with systemd's default 90s
  `TimeoutStartSec`. It timed out and killed the start **four times in a row**,
  turning "some data is stale" into eight extra minutes of *no engine at all*.
  Only step 1 (journalling the outage window, so the learning spine excludes
  trades spanning it) must finish before trading; the refreshes now hand off to a
  detached process. **A safety net must never be able to outweigh the thing it
  protects.**
- **Automated digestion stopped one step short.** `digest_day.py` wrote
  `events/2026-08-03.json` but nothing re-ran `_merge_amendments.py`, which
  *derives* `news_impulses_v2.jsonl` from it. The training corpus silently ended a
  day before the corpus it is built from. `digest_day.py` now derives impulses as
  its final step. Automating a pipeline means automating *all* of it.

### 4.9 The X capture was a write-only channel *(2026-08-04)*

The daily manual harvest never reached the brain that trades.

- **What.** `x_capture_ingest.py` wrote `news_archive_x.jsonl`; `daily_status.py`
  and `needs_you.py` watched its age; **nothing ever read it.** `fetch_headlines`
  polls `settings.news_rss` only. The capture flowed exclusively to the offline
  corpus (`events_amend_crypto` → `news_impulses_v2.jsonl` → `train_web`), so it
  shaped *future retraining* while contributing nothing to the decisions being
  made that day.
- **Measured, not assumed.** Of 36 X headlines captured for 2026-08-03/04,
  exactly **one** appeared in `brain.db` — and that one arrived via an RSS crypto
  feed carrying the same story, not from the capture.
- **The tell.** `SOURCE_TRUST` in `brain/events.py` has per-handle values written
  for these exact sources, under a comment naming
  `news_archive_x.jsonl`: Farside 0.80, glassnode/zachxbt/EleanorTerrett 0.70,
  TheBlockCo 0.65. The plumbing was designed and never connected. The highest
  per-source trust in the table belonged to a channel the brain could not read.
- **Why it mattered more than most.** This is the *only* hand-curated channel, it
  cannot self-heal (no API, by instruction), it costs the user a browser session
  every day, and it carries what the wires do not — ETF net flows, on-chain
  analysts, regulatory reporters.
- **Second defect, found while fixing the first.** Feeding X as one more feed
  among ~40 put it *behind* the round-robin, past the brain's 30-fresh-headlines
  per-cycle LLM cost gate. All 60 posts registered in `brain.db` as `digested=0`
  and were never tagged — **registered but starved, which looks accounted for in
  the table.** X now goes ahead of the wires: hand-curated, low-volume, highest
  trust, and self-limiting (once digested, posts are skipped forever).
- **Verified after the fix.** 60 articles ingested; ETF flows tagged to
  `crypto_liquidity` with correct signs (+$14.1M inflow positive, −$7.8M outflow
  negative); the Coldcard exploit to `custody_risk`; Bessent's Fed request to
  `yen_carry` + `fed_rate`.
- **New health row.** `X capture -> brain` reports digested/total and events
  tagged. The old row measured only the *file's* age — a fresh archive read as
  healthy while nothing reached the brain, the identical mistake to reporting the
  4-hourly RSS archive's age instead of the brain's lag (§4.3).
- **Lesson.** Freshness of a deposit is not evidence of arrival. Every channel
  needs a check on the far end, at the thing that actually consumes it.

### 4.10 Earlier failures, same shape

| Failure | Consequence | Found by |
|---|---|---|
| Merge script ignored the `events` key | ~900 of 927 crypto events silently dropped | investigating weak crypto results |
| Expectation-ledger counter double-incremented then halved | `n` pinned at 1 — **learning would have silently never activated** | reading the code while redesigning |
| Digest brief listed 9 fewer nodes than the seed | those nodes could never be tagged | building the golden set |
| Event-sleeve threshold set at 0.12 "by intuition" | above the p99 of the actual shock distribution (p90 = 0.051) | measuring the distribution |
| Flat 25bps limit band | **every** HK fill rejected — band equalled HK's own frictions | asking why HK never traded |
| Alts leaked into the stock universe | impossible stock damage in R27 | result too strange to believe |
| Idle third book gamed the objective | zero-trade book *raised* the score by lowering average drawdown | suspicious improvement |
| Budget renormalisation broke its own ceiling | 0.5263 allocated against a 0.50 cap | contract test |
| `_call_byteplus` ignored `json_mode` | cloud path would answer in prose → silent keyword fallback | switching providers |

**Two of my own mistakes this session, recorded because they distort
measurements rather than crash:** the audit script's `--model` flag also
overrode the *local* model name, so one run measured the keyword fallback
instead of the model under test (8% recall, meaningless); and a test appended
below a file's `__main__` block never ran at all.

## 5. What is unverified or uncertain

**Ranked by how much I would worry.**

1. **No live-money validation, ever.** Broker adapters have never touched a
   funded account. Slippage, partial fills, rejects, borrow availability for
   shorts — all unmodelled beyond assumptions.
2. **The learning spine has never run.** 0 settled claims. Its behaviour is
   test-verified, not observed.
3. **The lockbox is burned.** It was spent on the two-book configuration; the
   current four-policy system has no clean out-of-sample exam. My recommendation
   — not yet accepted — is to treat the forward paper record as the real test
   and stop tuning against history.
4. **The golden set is 50 items and has been tuned against three times.** The
   66% ORIGIN figure is a *relative* comparison between models, not an unbiased
   estimate. Inspecting the failures showed ~4 of 7 were defensible alternative
   nodes rather than errors, so true accuracy is higher than the metric — but
   an alternative node still propagates differently from the calibrated one.
   Run-to-run variance is 2–4 points, so gaps smaller than that are noise.
5. **Backtest-to-live gap.** All strategy validation is walk-forward on
   historical data with modelled costs. Real crypto 24/7 microstructure,
   exchange outages and funding dynamics are approximations.
6. **Shorts.** Six independent rejections in testing; the investing book still
   holds short positions from an earlier configuration. Not obviously
   consistent, and worth revisiting.
7. **`$25/day` target.** Never demonstrated. No book has produced a verified
   profitable forward record.
8. **Advice hit-rate is 0.404 over 30 days** — below a coin flip for
   directional calls, on 170 graded outcomes. This is the first honest reading
   the system has ever produced (see §4.6); it was 0.689 while contaminated.
   Whether 0.404 reflects genuine skill deficit or a scoring definition that
   mixes `long` with `short_or_avoid` has **not** been investigated yet.

9. **The equity marks were repaired against the journal, not recovered.**
   `scripts/breaker.py --repair-marks` rebuilt `peak_equity` ($100,142) and
   `day_start_equity` ($99,997) from the trusted journal rows after §4.7. That is
   a *reconstruction*: the true peak may have fallen between recorded cycles, and
   the day's real opening mark was overwritten by the phantom before any honest
   cycle ran. The repair deliberately errs low, so it can never manufacture
   headroom the book did not have — but the marks are inferred, not observed.
10. **The twelve positions closed by the phantom halt are gone.** Nothing
    reopened them; the engine re-decides from current signals, which is correct
    but means the forward record contains twelve exits that no strategy chose.
    They cannot corrupt the learning spine, for two independent reasons: they
    fall inside a journalled outage window (`gap_affected`), and the spine has
    never opened a claim at all — neither `expectations.jsonl` nor
    `learning_state.json` exists on disk. Checked, not assumed. The second reason
    is the load-bearing one today, and it disappears the moment the spine starts
    working, so the gap window is what must hold long-term.

## 6. Known limitations, deliberately not fixed

- **All three LLM endpoints are one provider (BytePlus).** A provider or
  network outage takes all three; the tagger degrades to keyword matching —
  dumber, not blind.
- **Backups sit on the same disk** as the data they protect. Survives
  corruption and bad writes, not a dead SSD.
- **Single machine, no failover.** Hardware death is downtime.
- **The box cannot report that it is unreachable.** If it loses connectivity,
  alerts go with it. A dead-man's switch would close this; not built.
- **Daily bars for stocks.** Crypto is marked to live spot for stops and
  valuation, but stock signals and stops run on daily closes.
- **GDELT crawler paused** at 268/1,127 days, by request.
- **Human-review backlog** — proposed edges and integrity flags in
  `data/digest_v2/STATUS.md`.

## 7. Operating it

See **`docs/status/OPERATIONS.md`** for the runbook: systemd units, the watchdog,
backups, the mini-PC migration, and the one command (`loginctl enable-linger`)
without which none of the supervision survives a logout.

Related: `docs/design/LEARNING.md` (the learning design and its reward contract),
`docs/design/BRAIN.md` (graph semantics), `docs/data-pipeline/SONNET_DIGEST_BRIEF.md` (corpus
tagging spec), `docs/data-pipeline/DAILY_LOOP.md` (data cadence).

## 8. The one thing to remember

Every serious defect in this project was **silent**. Nothing crashed. The
checks were green. A model returned `0` instead of an answer; a price was in
the wrong currency; a process was dead while a check said it was alive; a book
was invisible.

So the standing rule is: **measure the thing that decides, not the thing that
is easy to measure** — and when a component has no audit, assume it is the
broken one, because that is where every one of these has been found.
