# State of the system

*Honest engineering status as of 2026-08-05. Written to be read by someone who
has not been watching — including a future me. Where something is unproven it
says so; where a number is soft it says why.*

---

## 1. What this is

An autonomous trading engine for stocks and crypto. A knowledge graph (the
"brain") turns news into causal impulses; four independent policies ("books")
trade off that shared world model; a learning spine grades every trade against
what it predicted and reallocates capital toward demonstrated skill.

**No real money is at risk, but `LIVE_TRADING` is now `true`.** Since 2026-08-04
the 📈 book places actual orders through the Longbridge API — into a **paper
account** (`ac: lb_papertrading`), bounded to a $10,000 slice. The other three
books are simulated. The distinction matters both ways: real orders now exercise
the real broker path (§5.1), and nothing in this document is evidence the system
makes money with real money.

Both broker adapters authenticate, and the stock order path is verified end to end
— submit, confirmed fill, venue-resting stop and take-profit, cancel, exit. The
Gemini leg reaches a deliberately **empty**, segregated account, so it proves
connectivity and nothing more. See §5.1 for exactly what remains unproven.

## 2. Where it stands today

*Rewritten 2026-08-05. The books were deliberately reset — see §4.15.*

```
GRAPH    419 nodes, 780 curated edges  (seed v34, 2026-08-14, 279 of the nodes
                                        are assets. STOCK_WATCHLIST is now
                                        DERIVED from these — 258 tradable
                                        symbols, up from ~80 hand-maintained —
                                        see §4.25. Was 372/796 at seed v25, but
                                        that count included LLM-added edges;
                                        those are per-instance and not
                                        re-measured here, see §4.22/§4A)
BRAIN    6,326 articles, 2,380 events tagged
TAGGER   0% unsigned across recent events              (was 57%)
TESTS    36 suites, all green (local AND on the ProDesk AND in CI)
COMMITS  186

BOOKS — all four restarted at USD 10,000 on 2026-08-05, by request
  📈 trading   LIVE, routed to a Longbridge PAPER account, $10,000 slice
  🏛 investing paper, $10,000
  ⚡ sleeve    paper, $10,000
  ₿ crypto     paper, $10,000  (bear mode: 100% cash by design)

AUTONOMY   TRADE_APPROVAL=false — all FOUR books enter and exit unattended (§4.17)
YOUR SAY   the bot asks about its READ of the news, not its orders — 👍😐👎 on
           the inference + assumption, which weights the impulse the next cycle
           (brain/consult.py, /inferences, OPERATIONS "What the bot asks you")
EXITS      stop-loss + take-profit rest AT the broker (MIT / LIT), verified live
```

**The forward record before the reset**, so it is not lost by being overwritten:
trading $99,997 · investing $99,602 (8 positions) · sleeve $93,704 · crypto
$100,000. The sleeve's history is the only one with realised trades: **+$437**
from three clean exits, then **−$6,734** on USO — of which roughly half was caused
by the double-buy bug in §4.15. Retired state is in `data/retired/`, and the
brain, journal, reliability weights and learning ledger were all **kept**:
resetting books is not erasing what the model learned.

**The live book is currently idle, and not because of a bug.** Of 99 decisions,
13 clear the confidence floor and **12 of them are shorts** — which neither paper
venue permits (§4.15). The single qualifying long is `O39.SI`, excluded because the
live slice is USD-only until non-USD is validated. A uniformly bearish model that
cannot short has nothing to execute. Graded predictions still accumulate, which is
why the scorecard work in §4.15 matters more than the fills.

Read **equity**, not cash. A short's sale proceeds sit in cash while the shares
are still owed, so cash is never a book's value. Conflating the two caused §4.4,
and valuing a short at a zero price caused §4.7. (Moot in the 📈 book today —
shorting is off, because neither paper venue permits it.)

**The learning spine has run.** It has **1 settled claim**, and it is worth reading
because it is the first evidence rather than design: `event:USO`, expected **+0.31%**,
realised **−10.06%**, score −1.0. That single row exposed two spine defects and one
strategy problem, all in §4.15 and §4A. One claim is not a track record; it is
proof the instrument works.

**Every number above is USD.** SGD was considered and rejected: `BASE_CURRENCY`
has never been exercised as anything but USD, and every `RISK_`/`SAFETY_` threshold
is denominated in it, so switching would silently redenominate the whole safety
layer on an untested path.

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

**Index.** §4.1–4.6 predate 2026-08-04. §4.7–4.14 are the phantom-valuation day.
§4.15–4.21 are the autonomy session. §4.22 is the self-wiring review. §4A is the live
list of what is still broken — read that one first if something is wrong now.

| § | Defect | Root-caused? |
|---|---|---|
| 4.7 | A feed outage faked a 13.8% crash and flattened a healthy book | Contained — `mark_price` at every consumer; the `0.0` sentinel remains (§4A) |
| 4.10 | The same phantom existed in all four books | ✅ one shared valuation rule |
| 4.11 | The last-good-bar cache did not survive a restart, then cached NaN | ✅ persisted + validated on save, load and serve |
| 4.13 | The engine would have liquidated holdings it never opened | ✅ `foreign_positions`, gating both exit paths |
| 4.14 | A change of book size read as a 90% crash | ✅ declared basis, never inferred |
| 4.15 | `submit()` reported fills it never confirmed | ✅ **after §4.19** — was one adapter of three |
| 4.16 | I shipped a crash loop into the one path with no test | ✅ cycle test + static attribute guard |
| 4.17 | The investing book was never autonomous | ✅ one shared `_open()` for both routes |
| 4.18 | A live API key and secret were committed to the repo | ✅ file deleted, every tracked file scanned |
| 4.19 | Three fixes that were not root fixes | ✅ contract, backstop, and test isolation |
| 4.20 | 15 false pages in 90 min; the rate limit had never worked | ✅ keyed on identity; shape-aware backstop; rate-based projection |
| 4.21 | A test's verdict depended on the live crypto market | ✅ history follows `settings`; 7 read-only loaders remain in §4A |
| 4.22 | The "proposed graph edges" ask counted the trade audit log | ✅ repointed at llm edges, with review, tombstones and a rate; the 35×-spec proposal rate is now §4A |
| 4.23 | 8 of 9 live orders rejected — limit prices sent off-tick | ✅ `snap_to_tick`, proven against the venue; the submitted price is now journalled |

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

### 4.10 The phantom valuation existed in all four books *(2026-08-04)*

§4.7's fix was incomplete, and the question *"what is the portfolio now?"* is what
exposed it. `Portfolio.equity` was guarded. The three other books each
re-implement valuation, and each was wrong in the same direction.

- **The `_stamp_marks` form.** All three read
  `if px > 0: mv += qty * px` — which **omits an unpriced position from equity
  entirely**. An unpriced short reads as a debt that vanished; an unpriced long as
  an asset that vanished. Worse than §4.7's zero-valuation, because the position
  disappears rather than being marked wrong.
- **The original hole, twice more.** `investor._equity` and `crypto_book`'s
  `tact_val` used a dict-default (`prices.get(sym, p.avg_price)` /
  `prices.get(sym, 0.0)`) covering only a *missing* symbol, while a present `0.0`
  or `NaN` sailed straight through.
- **It produced a real misreport, which I gave the user.** The investing book
  showed equity **$83,125** against $105,356 cash — apparently −16.9%, and I
  reported it as such. Valuing every position (6 of 8 at cost, their prices being
  unavailable) puts it at **$99,913**. The portfolio was never down 4%; it is
  **$400,347 on $400,000 staked**. A valuation bug does not just mislead the
  engine, it misleads the report *about* the engine.
- **Fix.** One shared rule, `models.mark_price(raw, fallback)`: non-finite,
  non-positive or unparseable means *no price*, fall back to cost basis. Applied
  to all four valuation paths. Books now persist `stale_marks` and a per-position
  `stale_mark` flag so a reader can tell a mark from a placeholder.
- **Deliberately NOT changed.** Trading-decision guards (`if px <= 0: continue`)
  stay exactly as they are. Refusing to **act** on a bad price is correct;
  refusing to **count** a position is not. That distinction is the whole bug.
- **Lesson.** Four implementations of one rule is four chances to get it wrong,
  and they were written months apart by the same reasoning that failed each time.
  When the same concept appears in N places, the defect rate is N, not 1.

### 4.11 The cache that absorbs feed failures did not survive a restart *(2026-08-04)*

- **What.** `LastGoodBarCache` exists specifically so a blanket feed failure
  serves stale prices instead of zeros (§4.5). Its `_cache` was **in-memory
  only**, so every restart emptied it — and a restart is precisely when the
  throttle fires, because a cold start refetches all ~88 symbols at once. The
  safety net was absent exactly when it was needed.
- **Observed live.** While verifying the §4.10 fix, the feed returned `0.0` for
  **all 88 symbols, stocks and crypto**. My own repeated restarts that day are
  what triggered the throttle, and the cache had nothing to serve because each
  process was new.
- **Second gap in the same class.** Only the *stock* leg was wrapped. The crypto
  leg had no cache at all, so a ccxt outage put zeros straight into the books —
  identical failure, different provider.
- **Fix.** The cache persists to disk (last 120 bars/symbol, atomic write, aged
  out at 6h, written at most once per cycle), and both legs are wrapped with
  separate files so one leg's staleness cannot masquerade as the other's.
- **Why the incident was survivable this time.** The §4.7 and §4.10 fixes were
  already in: guard-filtered valuation plus cost-basis fallback meant a total
  feed blackout read as "no change" and marked 6 positions at cost, instead of
  faking a collapse. The defect that caused the morning's near-disaster was the
  reason the afternoon's identical outage was uneventful.
- **Then my own fix was wrong, in the session's signature way.** The new cache
  treated *non-empty* as *good*. yfinance returns rows whose values are `NaN`
  (incomplete session, partial response), the list was truthy, so the cache stored
  them — and reported itself healthy. `data/last_good_bars_stock.json` held **85
  symbols of which 51 had a NaN last close**, and would have served them for six
  hours: the fallback built to keep bad prices out had become a bad-price store.
  Valuation still held (`mark_price` rejects NaN), so nothing broke — which is
  exactly why it would have gone unnoticed.
- **Fix, at both ends.** `LastGoodBarCache._usable()` validates the last close on
  the way in, on the way to disk, and on load (a file written by an older build
  must not be trusted just because it parses). And `YFinanceDataProvider` now
  drops non-finite rows **at the boundary** — the one place a single check covers
  the guard, the breaker, the cache and every book at once. Poisoned cache files
  were deleted; they rebuild from the next good fetch.
- **Lesson.** A fallback that has never been exercised in the condition it exists
  for is an assumption, not a safeguard. Test the safety net under the failure it
  was built for — including process death, not just provider death. And **"I got
  data back" is not "I got usable data back"**: NaN is the most dangerous value in
  this codebase, because it fails every comparison silently instead of loudly.

### 4.12 Earlier failures, same shape

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

**My own mistakes, recorded because they distort measurements rather than
crash:** the audit script's `--model` flag also overrode the *local* model name,
so one run measured the keyword fallback instead of the model under test (8%
recall, meaningless); a test appended below a file's `__main__` block never ran
at all; a `sed` replacement matched the string `Restart=always` inside a *comment*
and put a `[Service]` directive in the unit's `[Unit]` section; I reported the
investing book as down 16.9% when the figure was an artefact of the very bug I
was fixing (§4.10); and my repeated service restarts while verifying fixes are
what throttled the price feed (§4.11).

**The pattern in the last one is worth naming.** Restarting to verify a fix is
itself an action with consequences. Four restarts in twenty minutes triggered a
provider rate limit, which then looked like a new failure. Verification is not
free and not side-effect-free.

### 4.13 The engine would have liquidated holdings it never opened *(2026-08-04)*

Found while validating the Gemini adapter, not by a failure — nothing broke,
because `LIVE_TRADING=false` meant the path could not run. It is recorded here
because it was armed and waiting for the day that flag changed.

- **What.** `CcxtBroker.get_positions()` turns **every non-zero balance** into a
  `Position`. Pointed at a real Gemini account it reported **19 currencies**
  (BTC, ETH, USDC, USDT, GALA, ANKR, AMP, FET, GRT, SUSHI, IMX, OXT, REN, SNX,
  FIL, MIR, SLP, SGD, USD) against a `CRYPTO_WATCHLIST` of three symbols. The
  engine would have believed it owned all of them.
- **Why it was dangerous.** Two paths act on positions without asking where they
  came from:
  - the **de-focus exit** (`runner.py`, step 2b) sells anything
    `user_views.is_allowed()` rejects, with `guard_slippage=False` and **no price
    required**. `is_allowed` returns `not focus or symbol in focus` — so setting a
    focus list, an ordinary-looking preference like *"focus on BTC and ETH"*,
    market-sells every other holding in the account under
    `reason="user blocked"`. Seventeen positions, one config line.
  - **stop losses** run on every position, and the adapter has no cost basis to
    give them — it substitutes the **last price** (`live.py:61`), so each stop
    would be measured against a fabricated entry.
- **Why it never fired.** `data/user_views.json` does not exist, so `focus` is
  empty and everything is allowed. The stop path was safe for a *different*
  reason: foreign symbols have no price (prices are built from the watchlist) and
  `stop_orders` skips falsy prices. That is an accident, not a guarantee — the
  same accident that made §4.7 survivable until it wasn't.
- **Fix.** `runner.foreign_positions()` — a named function, not an inline
  comprehension — and both exit paths gated on it, with a printed report of what
  was left alone. Refusing to act can strand a position if a held symbol is
  removed from the watchlist; that is the better of the two failures, and it is
  reported rather than silent. `test_the_engine_never_trades_a_position_it_did_not_open`
  covers the function *and* asserts both call sites still exist, verified by
  removing the gate and watching the test fail.
- **Lesson.** A paper broker only ever holds what the engine opened, so for the
  entire life of the project "every position in the portfolio is mine" was true
  and never had to be stated. A live adapter changes the meaning of
  `get_positions()` without changing its signature. **When an interface starts
  describing someone else's world, every assumption built on it needs re-reading**
  — and the assumptions that hurt are the ones nobody wrote down because they
  were free.

### 4.14 A change of book read as a 90% crash *(2026-08-04)*

Caused by me, while enabling the $10,000 live slice. Included because the shape
is the most repeated one in this register.

- **What.** `LIVE_CAPITAL_BASE=10000` switched the 📈 book from a $100k paper
  broker to a $10,000 slice of the Longbridge paper account. The breaker's marks
  still described the old book, so the first honest reading — $10,000 — measured
  as **`inception drawdown 90.0% >= 25%`** and latched within one cycle.
- **Why it is §4.7 again.** There, a price stopped being a valuation. Here,
  `day_start_equity` stopped describing the same book. Both are one mistake:
  **comparing two numbers that no longer refer to the same thing.** The breaker
  was not wrong; its inputs had quietly changed meaning underneath it.
- **Damage.** None, and only by luck: the book was empty, so "flatten everything"
  had nothing to sell. With positions open it would have market-sold the lot on a
  fiction. That is the second time in one day that an empty book is the only
  reason a phantom did no harm.
- **Fix.** `CircuitBreaker.ensure_basis()` re-bases the marks when the book's
  **declared** identity changes — `"paper"` → `"live:10000"`. Declared, never
  inferred: *"equity moved a lot, so it must be a new book"* is precisely how a
  safety system is taught to explain away a real crash. A latched halt is **not**
  cleared by a basis change, so changing book size cannot launder a halt.
- **And a second finding, from reading the log properly.** Per-day counters *are*
  reset on a re-base, because they belong to the book that spent them — and that
  matters more than it sounds. The breaker was carrying **$28,195 of
  `notional_today`** spent by §4.7's phantom flatten, against a $20,000 daily cap.
  The trading book had therefore been **unable to open a single position for nine
  hours**, printing `(no new positions — max notional/day $20,000 reached)` every
  five minutes into a log nobody was reading. I had told the user the book was
  "flat and would re-enter when signals fire". It could not have.
- **Lesson.** Two of them. **A reason logged is not a reason known** — the engine
  explained itself correctly, on every cycle, to no one; this is `daily_status.py`
  printing to an empty terminal all over again, and it is the exact failure mode
  §4.3 was supposed to have ended. And: **when you change what a number means,
  every stored comparison against it is now wrong** — including the ones inside
  the safety layer that exist to protect you.

### 4.15 Going autonomous: eleven more defects *(2026-08-04 → 08-05)*

The session that turned approval off, pointed the 📈 book at a real broker, and put
stop-losses at the venue. Everything here was found by trying to *use* a path
rather than by reading it — which is the only reason any of it surfaced.

**The one that mattered most.** `LongbridgeBroker.submit()` reported every accepted
order as fully filled, at the price it had merely hoped for:

```python
order.filled_qty = float(qty)
order.filled_price = order.limit_price if is_limit else price
order.status = OrderStatus.FILLED
```

`submit_order` only **acknowledges**; it does not fill. So a rejection would have
been booked as a fill, a partial as complete, a resting limit as done, and every
P&L and slippage number computed from a price that was never traded — while the
ledger, the breaker and the learning spine all read from that book. Demonstrated
by accident: a validation order passed `price=0.0` and the adapter reported
*"filled 1.0 @ $0.00"*. After the fix the same call reports the real **$13.99**,
queried from `order_detail`. Fills are now confirmed, never assumed; an unmapped
status is never optimistically booked.

| # | Defect | Why it survived |
|---|---|---|
| 1 | **The sleeve's re-entry guard never worked.** `sym in self.broker.get_positions()` compared `"USO"` against keys like `"stock:USO"` — always False. USO was bought twice, $66,958 into a book that sizes 33% positions. Its 10% stop then lost **−$6,734** instead of ~−$3,367. | The exit path nine lines above used `pos.asset.symbol` correctly. Exits worked; entries doubled. |
| 2 | **CI had never passed.** Added 2026-07-24 pinning Python 3.11 while `requirements.lock.txt` pins `numpy==2.5.1` (requires ≥3.12). `pip` died in ~12s on **136 consecutive commits**. | It emailed every time. Nobody acted. Now matched to the 3.14 production runs. |
| 3 | **`longbridge` was pinned; `longport` is imported.** Two real PyPI packages, same version line, different top-level names — so the adapter was unconstructable in any environment since it was written. | `--check-broker` had never been run, and the failure reads as "SDK missing". |
| 4 | **The spine silently discarded claims.** `open` is keyed `policy:symbol` and assigned unconditionally, so the second USO claim replaced the first, which was never settled and remains a dangling `open` row forever. | The corpus is append-only, so corruption looks like data. |
| 5 | **A stop-out scored the same as a scratch.** Direction and conviction drove the score; severity did not enter it. For a system whose hard rule is a max loss per position, that is a blind spot exactly where it matters. | The score was inside its documented bounds, so nothing looked wrong. |
| 6 | **`avoid` was graded as if it predicted a fall.** Hence `short_or_avoid` scoring 0.182 across 77 calls while averaging **+3.6%** — a rising tape marking every correct avoid as a miss. The unexplained 0.404 hit rate was a category error, not a skill deficit. | One blended number that mixed two different questions. |
| 7 | **Crypto had never received a single graded call.** The universe was whatever the causal graph named, and only BTC/ETH/SOL have nodes. All 13 coins had live scores and lost every seat to stocks in one global top-10. | "Considered 95" looked like broad coverage. |
| 8 | **`INVEST_STARTING_CASH` did not exist.** `investor.py` read it via `getattr(settings, "invest_starting_cash", 100000.0)`, so the fallback fired every run and that book's size was unconfigurable. | A `getattr` with a default is indistinguishable from a working setting until someone changes it. |
| 9 | **The notifier dropped messages silently.** One attempt, `return False`, no log. The boot-time "started" alert is the first outbound request after a reboot, when DNS lags — so the single most valuable message was the most likely to be lost. Observed: the 21:19 boot delivered nothing while the restarts either side both did. | Every other safeguard reports through this component. |
| 10 | **`daily_status` reported the wrong book.** It read `paper_state.json`, frozen since the live switch, and printed `$99,997 · 0 positions` as the state of things while the live $10,000 book was absent entirely. | On the one line a person actually glances at. |
| 11 | **The data-guard alert announced a state, not an event** — an identical Telegram every ~7 minutes for as long as a symbol stayed flagged. And the scorecard snapshotted the **raw** feed, so a guard-rejected stale close was stamped with today's date. 2800.HK is the HK/CN benchmark, so that silently froze the market return for every HK and CN call. | §4.7's lesson applied in one place and not swept for elsewhere. |

**Also fixed, not defects:** `.gitignore` covered `.env` and `.env.local` only, while
a full credential copy sat untracked and unignored in the trading box's working
tree; venue-resting stops (`MIT`) and take-profits (`LIT`) implemented and verified
live; position costs converted out of the listing currency and HK symbols padded
(`700.HK` → `0700.HK`) so the engine stops mistaking its own holdings for someone
else's.

- **Lesson.** Nine of these eleven were in code that had **never been executed
  once** — an unrun broker adapter, an unrun CI job, an unrun scoring branch, an
  unrun config setting. This codebase's defects are not concentrated in hard logic;
  they are concentrated in **paths nobody had walked**. Reading them found nothing
  for weeks. Running them found eleven in a day.
- **Second lesson.** Three of my own fixes were wrong on the first attempt — the
  spine's severity term inverted the conviction contract, its duplicate check ran
  after the write it was meant to prevent, and a config test passed on the dev box
  while failing on the ProDesk. All three were caught by tests, not by review. A
  fix is a hypothesis until something executes it.

### 4.16 I shipped a crash loop, and 27 green suites let me *(2026-08-05)*

Reported by the user, not by a check: eighteen `AI-Investing started (LIVE) — θv1
… θv18` messages in thirteen minutes, and *"its confusing to me as the end user
to receive this kind of messages"*.

- **What.** `AttributeError: 'Runner' object has no attribute '_flagged_symbols'`
  on line 297 of the hot path. The engine exited every cycle; systemd restarted it;
  it did that **18 times**. The books were untouched — it died before placing
  anything — but the engine was effectively down for 13 minutes while appearing to
  start successfully over and over.
- **How I caused it.** The patch script that added the `__init__` line asserted on
  a *later* edit in the same script, failed that assertion, and exited **before
  writing the file**. I then "verified" with `grep -n "_flagged_symbols"`, saw
  three hits, and shipped. All three were *uses*; none was the initialisation.
- **Why the tests did not catch it.** Nothing in this repository had ever
  constructed a `Runner` and called `run_cycle()`. Every suite tested a component.
  **The main loop — the only code that runs in production every five minutes — had
  zero coverage.** So an `AttributeError` in it shipped green, twice: locally and
  on the box.
- **Fix.** The missing initialiser, plus `test_runner_cycle.py`, which runs a real
  cycle against synthetic data with every path redirected to a scratch directory,
  runs a **second** cycle (state written at the end of one and read at the start of
  the next is exactly where this class of bug lives), and asserts the alert
  behaviour through a counting notifier. Confirmed by deleting the initialiser and
  watching it reproduce.

**Two more bugs the noise exposed**, both worse than the crash:

- **The engine announced every restart.** A deploy bounce is not news, and here it
  produced eighteen identical alerts that **buried the one message that mattered**
  — the watchdog's `restarted 10x since last check — crash loop, not a blip`. The
  noise did not merely annoy; it hid the diagnosis. Now it alerts only after being
  down more than 15 minutes, judged from the heartbeat, and says how long. A
  healthy restart is silent, because silence is the correct report for "nothing
  happened".
- **θ version was counting restarts, not learning.** `store.save()` incremented
  `model.version` unconditionally and is called from `run_forever()`'s `finally`,
  so every process exit advanced it — θv1 to θv21 in twenty minutes with **zero
  trades learned from**, every number sent to the user and appended to the params
  history as though the formula had matured. The version exists precisely so you can
  watch θ mature; counting restarts makes it worse than useless, because it looks
  like learning. Now it moves only when the weights actually differ from disk.

- **Lesson.** §4.15 said nine of eleven defects were in code that had never been
  executed. Within the hour I proved the point against myself by shipping a
  reference to something that did not exist, into the one path with no test — and
  my verification was a `grep` that confirmed the wrong thing. **A grep proves a
  string is present, never that the code works.** The only check that would have
  caught this is the one that runs it.
- **Second lesson, for the user's benefit rather than mine.** Every alert this
  system sends should answer *"what do I do about this?"*. "Started" answers
  nothing. Three of the four noise incidents in this register are the same mistake
  — announcing a state instead of an event — and each one buried something real.

### 4.17 The book that never went autonomous *(2026-08-05)*

Found by sweeping every `notifier.send()` in the codebase — the sweep I had twice
listed as outstanding and twice not done.

- **What.** The 🏛 investing book had **no `trade_approval` check at all**. It
  executed only on a proposal the user had tapped `approved`. So when
  `TRADE_APPROVAL` was set to `false`, three books went autonomous and this one
  silently kept waiting for taps that were never coming — unable to open a
  position, while still sending "approval needed" messages.
- **How it survived.** I traced only the 📈 book's path when flipping the flag, then
  told the user autonomy was on. It was on for three books out of four.
- **Fix.** Honour the setting, and route both the approved path and the autonomous
  path through one `_open()` helper. The dry-powder reserve rule was duplicated
  across them and would have been duplicated again — which is precisely how the
  sleeve's entry and exit paths came to disagree about symbol keys for the life of
  the project (§4.15/1).
- **One more alert instance.** A news/context failure alerted **every cycle**, so a
  provider outage meant ~12 identical messages an hour. That is the fourth
  announce-the-state bug. The rest of the 24 alert sites check out: the strategist
  is gated to once per SGT day, bear-mode fires on the transition, reconcile-drift
  self-clears by rebaselining, and the watchdog has its own rate limit.
- **A static guard, and the rule took two attempts.** The obvious rule — *assigned
  somewhere in the class* — does **not** catch §4.16: `_flagged_symbols` is assigned
  at the END of the very method that reads it at the start, so it looks assigned and
  still crashes on the first pass. The rule that matches the failure is *read by any
  method ⇒ assigned in `__init__`*, with `getattr(self, x, default)` exempt. Zero
  offenders across the package, verified by deleting the initialiser and watching it
  name the exact attribute.
- **Lesson.** Sweeping is not the same as fixing the instance in front of you. Three
  of these four alert bugs were found by a user complaining; the fourth was found in
  ten minutes once I actually enumerated the sites. **When a bug has a shape, grep
  for the shape.** I wrote that lesson down twice before acting on it.

### 4.18 A live API key and secret were committed to the repo *(found 2026-08-05)*

The most serious finding of the session, and it surfaced by accident. The user
questioned an open item I had labelled *"Gemini master key not revoked"* — asking,
correctly, whether the master key was the sandbox one. It is:
`CRYPTO_SANDBOX_API_KEY` (a `master-` key). My label was wrong. Checking where the key I
*actually* meant still existed turned up something worse.

- **What.** `.env.example` lines 50–51 contained the **real Gemini production API key
  and its secret** — the production `CRYPTO_API_KEY` / its secret
  — for the account holding roughly $5.6k of stablecoins plus BTC, ETH and fourteen
  alts. Present since the brain commit (`ea0816e`), tracked, pushed, and preserved
  in git history across 8 committed versions of the file.
- **Why it was invisible.** `.env.example` *looks* like a template. Nobody reads the
  values in a template. `.gitignore` correctly excludes every `.env` variant — and I
  explicitly **allow-listed `.env.example`** earlier the same day while fixing a
  different leak risk, without reading it.
- **How badly I misjudged it.** An hour earlier I told the user this item was "one
  click, and the only one with real-money exposure", then, tracing it, said the
  exposure was "one chat transcript". Both were wrong in opposite directions. The
  full credential pair was in the repository the whole time.
- **Fix.** The user's call, and the right one: **`.env.example` is deleted, not
  sanitised.** A tracked template invites a real value into a published location, and
  that is what happened. The configuration surface is now GENERATED —
  `scripts/env_template.py` prints all 150 variables with their defaults from
  `config.py`, **every line commented out**, so it documents everything and sets
  nothing. `setup.sh` generates `.env` at 0600 instead of copying.
- **The replacement is the scanner I said should have existed.**
  `test_no_tracked_secrets.py` sweeps every *git-tracked* file for credential-shaped
  values — vendor prefixes (`account-`, `master-`, `sk-`, `ghp_`, `AKIA`, Telegram
  bot tokens, PEM blocks, Longport JWTs) and any opaque value assigned to a
  `*SECRET*`/`*TOKEN*`/`*PASSWORD*`/`*API_KEY*` name. Tracked only, because an
  untracked secret is a local risk while a tracked one is published. Verified against
  the exact pair that leaked.
- **Three bugs in my own fix, all found by running it.** The scanner flagged the
  credential prefix I had quoted in *this very section*, so the docs are redacted
  rather than allow-listed — an exception becomes a habit. Its regex used `\s*`
  around the separator, which matches a newline, so an empty assignment swallowed
  the following line and reported it as that variable's value. And the generated
  template broke the engine outright: `APPROVAL_TTL_HOURS=` makes `float("")` raise,
  so an empty assignment is worse than an absent one — which is why every line is
  commented rather than blank.
- **What the fix does NOT do.** Sanitising a file does not unpublish it. The
  credential remains in git history and in any clone or fork. **Only revocation at
  Gemini removes the exposure**, which is why that is the user's action and not a
  code change.
- **Lesson.** I audited this repository's security on 2026-08-04 and reported the
  baseline as solid: `.env` at 0600, nothing secret tracked, `git ls-files` checked
  for credential-shaped filenames. I checked the **names** of tracked files and never
  the **contents** of the one file designed to look harmless. A secret scanner would
  have found this in seconds; my by-hand audit found the file and approved it.
- **Second lesson.** This came from the user pushing back on a claim of mine. Three
  of the last four findings arrived that way. Being corrected is the cheapest audit
  in this project, and it only works if the pushback is followed rather than
  answered.

### 4.19 The root-cause audit: three fixes that were not root fixes *(2026-08-05)*

Asked to make sure the fixes were root-level, I audited them instead of assuming.
Three were not, and each had the same shape: **I fixed the instance I could see and
left the mechanism that produces more of them.**

**1. The fill fabrication was fixed in ONE of three adapters.** §4.15 fixed
`LongbridgeBroker`. Reviewing the others afterwards:

| Adapter | Before |
|---|---|
| `MoomooBroker` | `filled_qty = float(qty); filled_price = limit_px; status = FILLED` on any successful `place_order` — **identical fabrication**, both quantity and price invented |
| `CcxtBroker` | `filled or order.qty` and `average or price` — invented a full fill and the caller's mark whenever the exchange did not report |

Three adapters, three degrees of the same assumption, because **each wrote its own
ending to `submit()`**. Root fix: the contract now lives once. `BrokerAdapter` states
it explicitly, `confirm_or_pend()` implements it, and each adapter supplies only a
`fetch_fill()` hook. Where a venue query is not implemented — moomoo, which needs the
OpenD gateway and cannot be tested here — the answer is **PENDING**, not a guess. The
engine handles pending: no position, no P&L, re-decide next cycle. It cannot handle a
fabricated fill, because the ledger, the breaker and the spine read the price as fact.
`test_fill_contract.py` holds this for all three, including a structural check that a
future adapter cannot write its own ending again.

**2. Four alert storms were fixed four times.** Breaker, data guard, engine-start,
news error — each at its call site, and a fifth would eventually be written. Root fix:
`TelegramNotifier` now suppresses byte-identical messages inside a 30-minute window,
counts what it dropped, and **prints that a caller is announcing a state so the real
bug still gets fixed**. Keyed on exact text, because every storm was byte-identical
while real alerts carry changing detail. Monotonic clock, so a clock adjustment cannot
unblock a storm. This is a backstop, not the design — but the user will not receive
eighteen copies of anything again because one caller forgot.

> **Falsified the next morning — see §4.20.** "Every storm was byte-identical" was
> true of the four storms I had seen and of no future one. The very next storm ticked
> a token count and passed all fifteen messages through. The backstop now keys on the
> message's *shape* as well as its exact text. Generalising from the instances you
> happen to have is the same error this section was written to correct.

**3. Three tests inheriting the operator's config were pinned one at a time.**
`config.py` calls `_load_dotenv` at **import** time, so importing it pulled the live
`.env` into every test process — and the same test then went green on the dev box and
red on the ProDesk, because the two machines are configured differently. Pinning the
value in each test is the symptom. Root fix: a test process does not load `.env` at
all, detected automatically from `sys.argv[0]` and `PYTEST_CURRENT_TEST` rather than by
an opt-in flag — **because what failed three times was remembering**. Verified both
directions: a script under `tests/` sees defaults, the engine still reads the file.

- **Known and NOT fixed at the root, deliberately.** The runner still encodes "no
  bars" as `prices[key] = 0.0` — a sentinel that means *absent* but reads as *free*,
  and the direct cause of §4.7. `mark_price()` defends every consumer, which is a
  strong perimeter, but the honest root fix is to omit the key. That is a wide change
  to every price consumer, and it is in §4A rather than pretended away.
- **Lesson.** A fix is root-level only if it makes the next instance impossible or
  loud. Fixing the instance in front of you feels identical from the inside and is
  measurably different: the sleeve's entry/exit key mismatch, four alert storms, three
  adapters and three env-dependent tests were all one mechanism each, met four, three
  and three times. **When a bug has a shape, the fix belongs where the shape is
  defined.**

---

### 4.20 Fifteen pages in ninety minutes, for a condition that was not real *(2026-08-05)*

**What the user saw.** Between 09:35 and 13:03 SGT, `AI-Investing needs attention`
arrived every sixteen minutes — fifteen times — each reporting the LLM free allowance
as STALE, each with a slightly higher token count, the projection falling steadily
from **262% to 130%** as it went. The user asked what it was about. It was three
separate bugs, any one of which alone would have produced the storm.

**Bug one: the rate limit had never once worked.** `watchdog.py` was written on day
one with the rule *"a broken thing stays broken for hours; re-sending every fifteen
minutes trains you to ignore the channel"* and a `RENOTIFY_S = 6h` guard to enforce
it. The guard keyed on the **rendered sentence**:

```python
fresh = [i for i in issues if now - float(sent_at.get(i, 0)) > RENOTIFY_S]
```

Every issue string in this system carries a live number — token counts, restart
counts, free-disk percentage. `…vgxfw=1011k(20.2%)` and `…vgxfw=1041k(20.8%)` are the
same issue, and were two different keys. **A rate limit whose key contains the thing
that changes is not a rate limit**, and this one had been dead in every commit since
it was written, invisibly, because nothing had yet failed for longer than one run.

*Root fix.* The identity of a check is the check, not the sentence it prints.
`daily_status.py` now declares a stable key per check and emits `--json`; the watchdog
consumes that instead of scraping stdout for lines starting with `STALE`. Every check
returns `(key, detail)` — rate limiting keys on the first, the user reads the second.
The same latent bug was in the disk and crash-loop checks and is fixed with it.

**Bug two: yesterday's backstop did not hold, one day later.** §4.19 added identical-
message suppression to the notifier and this file recorded the reasoning: *"the storms
were all byte-identical."* That was true of the four storms I had seen and false of the
next one. Fifteen messages, no two byte-equal, straight through.

*Root fix.* The notifier now keys two ways: exact text (suppressed immediately) and
**shape** — the text with every number replaced by `#` — allowed through three times
per window, then suppressed. The allowance is the whole trade-off: two fills of one
symbol at different prices differ only in their numbers and must survive, while one
sentence with a ticking number four times in thirty minutes is not four events.

**Bug three: the alert was false.** The projection was `used × 24 ÷ hours_elapsed` —
a line through the origin, which assumes the day's tokens arrive at a steady rate.
They do not. The nightly digest crons spend most of the allowance in the ninety
minutes after 00:00 UTC, and dividing a burst by a small `elapsed_h` manufactures an
emergency. At 01:51 UTC it read 262%; by 05:03 it read 130% while actual use had risen
only 20.2% → 27.4%. The endpoint was on course for **roughly half** the cap. Every one
of the fifteen alerts was wrong, and the decay from 262 to 130 was the estimator
correcting itself in public.

*Root fix.* `_record_usage` now keeps per-hour buckets, and the projection extrapolates
from the **last four hours** rather than from midnight: a burst that has stopped stops
counting, a burn that is ongoing still projects over. The basis is printed with the
number so a surprising figure can be traced. A genuine sustained overrun still pages —
that is a test, not an assurance.

**Also fixed in passing.** `daily_status.py` hardcoded `cap = 5_000_000` while the
engine read `LLM_DAILY_FREE_TOKENS`. Setting that env var would have moved the
rotation threshold and left the alert measuring the old one. One definition now.

**Cost of the false alarm: nil, and that is the danger.** There was never any risk to
the books — `_over_free_budget` independently rotates an endpoint away at 90% actual
use, and that logic was correct throughout. The damage was entirely to the channel.
Fifteen wrong pages in one morning is how a user learns to swipe the alert away, and
the next one may not be wrong.

**Lesson.** Two of these three were *safeguards that had never fired correctly* —
the rate limit had been broken since it was written, and the backstop was defeated the
day after it was added. Code that only runs during a failure is code that has never
run. §4.15 said the same thing about an unexecuted broker adapter; **a guard is not
verified until something has actually been guarded against**, and a test that stages
the real storm is the cheapest way to make that happen before the user does.

`engine/tests/test_alert_storm.py` — 16 tests, staging the actual 2026-08-05 message
sequence against all three layers.

---

### 4.21 A test whose result depended on the crypto market *(2026-08-05)*

**Found by deploying.** `f1af4a9` passed all 33 suites on the dev box. On the ProDesk,
`test_crypto_book.py` failed: *"winter must register as bear evidence"*. Same commit,
same Python, same lockfile.

`bear_evidence()` needs `BEAR_K = 2` of four signals. The test supplies one — synthetic
bars deep below their 100-day mean. The other three come from `_hist()`, which built a
path to the repo's **real** `data/crypto_history/` out of `__file__` and ignored
`settings` completely:

| Machine | Real-data signals | Total | Result |
|---|---|---|---|
| ThinkStation (stale snapshot) | `1 — stablecoin supply draining` | 2 | pass |
| ProDesk (live data) | `0` | 1 | **fail** |

So the test redirected `state_path` into a temp directory, took care to isolate itself,
and then read the live crypto market anyway. **Its verdict was a function of the actual
stablecoin supply.** It was not machine-dependent so much as *market*-dependent: it
could have flipped on either box on any day, and the day it flipped it would have looked
like the deploy broke something.

**Root fix.** `_hist()` now resolves its directory from `settings.state_path`, exactly
as `crypto_state.json` already did five lines below it. Production is unchanged — the
state file lives in `data/`, so the history resolves to `data/crypto_history/` as before
— and a test pointing `state_path` at a temp directory now genuinely gets nothing. The
bear test writes the second signal it needs as a fixture: **a test for "two signals
fire" must supply two signals.**

**The wider shape.** A sweep found 25 modules building a data path from `__file__`.
Seventeen are `research/` offline tools with no caller to configure — genuinely fine.
Seven are live-path reference loaders (fundamentals, comps, ownership, estimates,
calendars, value scanner, scalp) which are read-only and decide no trade; they are in
§4A, not swept in one risky change. `test_data_path_isolation.py` pins that list so it
can shrink and never grow, and fails on any new live-path module that joins.

**Lesson.** This is §4.19's test-isolation defect wearing different clothes. That fix
stopped a test process loading `.env`; it could not stop a module reaching past its
settings to a hardcoded directory. **The mechanism was never "`.env` leaks" — it was
"a component reads state its caller cannot control", and configuration was only the
first place it surfaced.** A component that reads from a path its caller cannot set is
neither testable nor configurable; those are one defect, and the untestable half is how
you find out.

Also worth stating plainly: the previous commit's *"33 suites green"* was true and
insufficient. Green on one machine says nothing about a suite that reads that machine's
data. **Running it somewhere else is a real test.**


### 4.22 The ask that pointed at the wrong file for its whole life *(2026-08-10)*

**Found by the user asking what the digest actually wanted from them** — *"isn't this
app supposed to be automated? even if it asks me, what am I supposed to do? I don't
think I can just reply via Telegram."* All three doubts were correct.

- **What.** `needs_you.py`'s third ask counted lines in `data/proposal_log.jsonl` and
  called them *"proposed graph edges awaiting review"*. That file is the append-only
  **trade** audit (`execution/approvals.py`), written once per proposal with
  `status: "pending"` frozen at write time and no `reviewed` key, ever. So the filter
  `'"reviewed"' not in l` matched **every line**, the count was "trades ever proposed"
  and could only grow, and the suggested action — review that file — was impossible:
  there is nothing in it to review. All 35 it was nagging about were dead trade
  proposals, expired between Aug 3 and Aug 6.
- **Wrong from birth.** The commit that introduced it (`262b437`, 2026-08-03)
  announced *"23 proposed graph edges awaiting review"* — exactly that day's
  trade-proposal line count. A plausible number is the easiest kind of wrong to keep:
  nothing about "23" invited a second look, and none of the three reviews it survived
  opened the file.
- **The real population was never watched.** LLM-proposed edges live in
  `knowledge_graph.json` with `provenance: "llm"`, applied automatically at capped
  confidence per `DIGESTION_SPEC.md` §A10. At the time of the fix: **140 of 796 edges
  (18%) were self-added, none reviewed, none reviewable.** The L0 calibrator skips
  them (`calibration.py`, `provenance != "seed"` → skip) and — the part that makes
  this structural — **could not score them even if extended**: `_score_pair` needs the
  destination to carry a tradable symbol, and *zero* of the 140 do. They wire factors
  to private hubs and to each other. The cap was the entire control surface.
- **And the design's premise had quietly failed.** §A10 argues *"a bad proposal is
  damped by the cap, not blocked by a queue"* — sound at the rate it assumes in the
  next breath, *"Rare: expect ≤1 per week"*. Measured: **96 in the last 7 days, 35/week
  over 28 days — 35× the spec.** Nothing was measuring it, so nothing noticed that the
  argument for auto-applying had stopped holding. This is §4.20's shape, not §4.1's:
  not a component returning the wrong answer, but a *threshold reasoned from an
  assumption instead of from the data*, exactly as `ASK_BAR` was two days earlier.
- **Fixes.** The ask now reads llm edges from the graph and reports the **rate**
  alongside the backlog, because a backlog says work is waiting while a rate says
  whether the design still holds. `scripts/review_edges.py` is the review §A10
  promised and never built (`--show`, `--stats`, `--json`, `--keep`, `--reject`,
  `--batch`, `--contested`). Rejection writes a **tombstone** into the graph, because
  `propose_edge` dedupes only against edges that currently exist — without one, the
  next similar headline walks a rejected edge straight back in and the reviewer works
  forever.
- **Two hazards found while building it, both worse than the original bug.**
  1. **Review would have evaporated.** The engine loads the graph once at `Brain`
     construction and rewrites the whole file whenever it adds an edge
     (`core.py::_persist`). Any decision written out-of-band would have been reverted
     by a process that never knew about it — and would have *looked* like it worked.
     `save()` now reconciles with the file it is about to overwrite. Safe to merge
     blindly because review state is monotone: a keep or reject is never withdrawn by
     the engine, only ever added by a human. Where both sides touched one tombstone,
     `suppressed` takes the **max, not the sum** — both counts descend from a common
     ancestor, so adding them would double-count shared history and manufacture a
     contested rejection nobody argued for.
  2. **A status check that creates what it measures.** `KnowledgeGraph.load` seeds a
     fresh graph when the file is absent — right for the engine, wrong for a reporter.
     A mistyped `BRAIN_GRAPH_PATH` would have had the digest write a brand-new graph
     and then truthfully report zero edges pending: **a clean bill of health
     manufactured by the act of checking.** Both scripts now refuse.
- **A rejection is never silent.** Each suppressed re-proposal is counted on the
  tombstone and surfaced by `--contested`, because an edge the world keeps proposing
  is evidence the rejection may have been wrong. Burying that would be the fifth
  instance of this project's most repeated mistake — rendering a verdict nothing will
  ever grade (§4.1, §4.6, `80bb6ad`, `f4da048`).
- **Lesson.** §4.16 said *a grep proves a string is present, never that the code
  works.* This is the counterpart for data: **a count proves a file has lines, never
  that they are the lines you meant.** The check ran green for a week, produced a
  number that moved, and measured something that did not exist. Every digest it sent
  was evidence the system was working.
- **Second lesson.** The user asked what they were supposed to *do* about an alert. No
  automated check had that question, and it is the one that found the bug. §4.16 already
  wrote the rule — *every alert should answer "what do I do about this?"* — and this ask
  had shipped without an answer for a week, because the rule was applied to the alert's
  wording and never to whether the action it named was possible.

### 4.23 Eight live orders were lost to a third decimal *(2026-08-10)*

**Found by the user asking a question no check asks** — *"you sure you have gathered
enough data and insight to make the improvement?"* — after an earlier trace had
proposed this fix on circumstantial evidence. The challenge was correct: the
evidence was suggestive, and the change was to a live money path.

- **What.** `brokers/live.py` submitted `round(order.limit_price, 3)`. US equities
  trade on a **$0.01** tick, so a third decimal is an illegal price and Longbridge
  rejects it outright with `code=602035`, *"Wrong bid size, please change the price"*.
  A limit order was therefore legal only when its third decimal happened to be
  zero — about **one attempt in ten**.
- **Scale.** Every live order the engine has ever placed: **nine attempts,
  eight rejected, one filled.** Between 2026-08-05 and 08-10 the live book holds
  a single AAPL share, and that fill was not the system working — it was the tenth
  roll of a ten-sided die. The most recent loss was USO on 08-10, hours before the
  cause was found.
- **Why it survived.** The rejections *looked* explained. The journal recorded
  quantities like `1.3192` against an error saying "Wrong bid **size**", which reads
  as an obvious fractional-share problem — and `submit()` already does
  `qty = int(order.qty)`, so all nine attempts sent exactly **1 share**. Quantity was
  never the difference. The journal was recording the *request* quantity in the same
  column as the *fill* quantity, and the plausible reading of a real error message
  pointed at the wrong cause for five days.
- **Why it could not be diagnosed.** `record_order` stored the **fill** price
  (`0.0` on a reject) and nothing about the request. **The submitted price — the one
  number that identifies this — existed nowhere.** A rejected order you cannot
  reconstruct is an order you cannot learn from.
- **Settled by asking the venue, not by reasoning.** `scripts/probe_tick_size.py`
  sent orders identical in symbol, side, quantity and second, differing only in the
  third decimal:

  ```
  AAPL.US BUY 1 @ 276.09   -> ACCEPTED
  AAPL.US BUY 1 @ 276.093  -> REJECTED 602035
  AAPL.US BUY 1 @ 276.09   -> ACCEPTED   (276.093 through snap_to_tick)
  ```

  The third is the fix answering the same venue that rejected the second. All rested
  10% below market so none could fill, all were cancelled, and the account still held
  exactly the one share it started with.
- **Fix.** `snap_to_tick()` rounds onto the instrument's real grid: a penny for US
  (a hundredth of a cent under $1, where a penny would be a 2.5% jump), the HKEX
  spread table for HK, SGX minimum bid sizes for SG, and a penny for anything
  unrecognised — deliberately the **coarser** default, because too coarse shifts a
  price by one tick while too fine is what cost eight orders. A buy rounds down and
  a sell rounds up, so snapping can only ever make an order *less* likely to fill,
  never quietly raise what we agreed to pay. `Order` now carries
  `submitted_price`/`submitted_qty`, stamped by the **adapter** before the API call
  so the exception path records the request too, and `journal.orders` gains
  `req_qty`, `submitted_qty`, `submitted_price`, `order_type`, `limit_price`.
- **Lesson.** §4.15 said nine of eleven defects were in code that had never been
  executed. This one had been executed nine times and *still* hid, because the error
  message was plausible enough to stop the search. **A real error message pointing at
  the wrong cause is worse than no message**, and the only way through it was to stop
  theorising and ask the venue a question with one variable in it.
- **Second lesson.** The probe took minutes and the wrong theory had stood for five
  days. Where a live counterparty can be asked directly, ask it — and build the
  asking into the repo (`probe_tick_size.py` refuses any channel but
  `lb_papertrading`, does nothing without `--send`, cancels in a `finally`, and
  re-lists open orders afterwards) so the next venue-side puzzle is cheap too.

### 4.24 The graph had no way to learn a company exists until a human noticed *(2026-08-13)*

**Found by the user asking a direct question — "how are you feeling about the
brain, does it know about Unitree?"** — and then, when the answer was no,
refusing to accept "I'll add it" as the fix: *"it has to have foresight as
well, it cannot be lagging behind."* Right call: the miss was not a missing
node, it was a missing mechanism.

- **What.** The graph grows two ways, and neither has any notion of "a
  promising company is all over the headlines." `brain/seed.py` is
  hand-curated — it only knows what a human remembered to type in, and my own
  sweep (§ this session) was built from static knowledge with a Jan-2026
  cutoff, so it simply didn't know Unitree Robotics' STAR Market IPO was
  imminent. `brain/deals.py`'s auto-discovery (the only automated path to a
  new node) only fires for a **bilateral** deal (`invests_in`/`supplies`/
  `acquires`) **≥ $1B in one stated transaction**. An IPO has no natural
  counterparty for that model, and a hot startup's funding rounds are
  routinely well under $1B individually even when the company is enormous
  news — so neither path had any chance of catching it.
- **Scale of the miss, once actually checked.** Unitree Robotics (STAR Market
  IPO, priced 2026-08-06, ~$9B valuation, first pure-play humanoid-robot maker
  on a mainland exchange) was missing. So was **ChangXin Memory Technologies
  (CXMT)** — not a niche miss: it debuted 2026-07-27 up 466% and became **the
  single most valuable mainland-China-listed company, surpassing ICBC**, and
  it sat undiscovered for over two weeks. A follow-up manual sweep (not the
  automated gap-scan below — see the "how this was actually found" note)
  turned up four more already-real, already-material gaps in one pass:
  Hengrui Pharmaceuticals (1276.HK, $1.3B HK listing, top-10 global IPO of
  2025), Haitian Flavouring & Food (3288.HK, $1.3B), Sanhua Intelligent
  Controls (2050.HK, $1.2B, Tesla thermal-management supplier), and JCET
  Group (600584.SS) — the last one not even a recent IPO, just a world #3
  chip-packaging company that had apparently never been added at all.
- **Fix, three layers, because no single one is sufficient alone:**
  1. **`brain/deals.py` gained a `lists_on` deal kind** (`brain/events.py`
     prompt extended to match). The digester now records IPOs as a
     single-party event — company, exchange, listing valuation, ticker if
     stated — material on the **listing valuation**, not a bilateral deal
     size. `propose_node()` (`graph.py`) now creates a **real tradable node**
     (symbol + market) when a ticker is known, distinct from the pre-existing
     symbol-less "(private)" hub it creates for unresolved deal counterparties.
     Verified against synthetic events (correct creation above the $1B bar,
     correct drop below it, correct fallback + `needs_symbol` flag when no
     ticker is stated) — **not yet verified against a live LLM call**, since
     this session has no path to exercise the production digester.
  2. **`scripts/graph_gap_scan.py`** (new): mines the news archives/caches
     independently of the digester, extracts candidate entity names, and
     reports ones the graph's alias index can't resolve, gated on ≥3 distinct
     headline mentions across ≥2 distinct source domains to hold back
     sentence-fragment noise. This is what actually found CXMT on its first
     run. Wired into `needs_you.py`'s existing twice-daily digest (item 5) —
     no new systemd timer — so it degrades the same way every other check in
     that file does: a broken scan reports itself instead of going quiet.
  3. **Neither of the above found Hengrui/Haitian/Sanhua/JCET.** Those came
     from a third thing that is *not* a script: me actively searching "biggest
     HK IPOs 2025/2026" and cross-checking each hit against the graph, because
     the local news archive (174 headlines, only wired up for about a week —
     see the four-channel commit just before this work started) was too thin
     and too generically-international for the gap-scan's frequency heuristic
     to have anything to bite on for China/HK names specifically. This is the
     honest gap the fix above does not close, and §4A records it as such
     rather than claiming automation finished the job.
- **Deploying it to the ProDesk immediately found what the dev sandbox
  couldn't.** `git pull --ff-only` + the documented test-then-restart loop
  (`OPERATIONS.md` → *Developing against it over SSH*) went cleanly and the
  engine restarted with seed v32 merged in (382 assets on disk once the
  ProDesk's own 112 self-discovered private hubs were folded in). But
  `needs_you.py --show` on the real box crashed the new check outright:
  `TypeError: can't compare offset-naive and offset-aware datetimes` — some
  feeds publish naive timestamps the 174-headline dev sample never contained.
  Fixed by normalizing naive timestamps to UTC instead of raising. Worse:
  once it ran, the candidate list was **~1,800 entries deep, top hits
  Reuters/Hormuz/Al Jazeera/United States** — three rounds of stoplist
  tuning against the real corpus kept surfacing new noise (Colombia, Texas,
  Tehran, "There", "According") no matter how large the list got. The actual
  cause: `news_archive_{guardian,gdelt_crypto,wiki}.jsonl` are historical
  **macro-regime backfills** (267MB+ of general world news, built to
  train/replay the digester's macro reads — see `research/guardian_fetch.py`,
  `gdelt_crypto_fetch.py`), not company news, and at that size they drown out
  the live feeds this tool actually needs by orders of magnitude. Excluding
  those three archives fixed it at the source: ~700 candidates, **top hits
  Coldcard/Glassnode/FactSet/Starlink/Kalshi/Hyperliquid/Polymarket** — real,
  previously-unresolved names, not noise. None of this was visible from the
  dev sandbox; the 174-headline sample was too small to contain a naive
  timestamp or to be dominated by a 267MB archive it didn't have a copy of.
- **Lesson.** A hand-curated seed file plus a narrow bilateral-deal trigger
  looks like coverage until you ask it the one question it was never built to
  answer: *what's new?* Foresight is a different property from breadth, and
  building more of the graph (this session added 84 assets across three
  passes, §2) does nothing for it — only a mechanism that watches for **change
  over time** does, and until §4.24's fixes had shipped, no such mechanism
  existed anywhere in the codebase.
- **Second lesson.** `OPERATIONS.md`'s deploy loop insists on *proving it on
  the box that matters before restarting anything* — this is why: a script
  that ran clean against a 174-headline dev sample crashed immediately and
  then produced 1,800 lines of noise against the ProDesk's real 280MB+
  archive, and neither failure mode was reachable any other way. A dev
  sandbox with thin data cannot validate a tool whose entire job is behaving
  correctly at real data volume.
- **First real end-to-end run, seed v33.** With the gap-scan actually usable,
  its top-7 candidates (Coldcard, Glassnode, FactSet, Starlink, Kalshi,
  Hyperliquid, Polymarket) went through the same verify-before-add discipline
  as the CXMT batch. Added: **SpaceX** (SPCX, listed 2026-06-12 — the
  largest IPO in history, now above Tesla by market cap; "Starlink" in
  headlines was this, not a separate listing), **FactSet** (FDS, an
  established NYSE company that had simply never been added), **Hyperliquid**
  (HYPE/USD, live on every major exchange plus a spot ETF). Rejected: Kalshi,
  Polymarket, Glassnode — confirmed still private. **Coldcard/Coinkite hit a
  real hallucination**: the first search claimed it trades as "COIN" — false;
  a second, independent check showed that's a conflation with Coinbase's
  actual ticker (already a graph node, which is almost certainly what the
  first search pattern-matched on). Caught only because verification here
  means *confirm from a second source*, not *accept the first answer* — the
  exact failure mode this whole discipline exists to catch, now with a
  concrete instance of catching it.

### 4.25 The graph and the tradable universe had silently drifted apart *(2026-08-14)*

**Found by the user asking the obvious follow-up to §4.24: "then how do people
trade stocks in Singapore, HK and China now, as long as Longbridge allows
it?"** — and refusing to accept "the graph knows about them" as an answer,
correctly pushing until the actual mechanism was checked: *"my expectation is
that any stock that has potential as a signal should be bought... everything
should be buyable isn't it?"*

- **What.** Two things in this codebase look related but are not wired
  together: the **graph** (`brain/seed.py`, what the brain can reason about)
  and **`STOCK_WATCHLIST`** (`config.py`, the literal finite list the engine
  will place orders for). Adding a node to the graph never added it to the
  watchlist — that always required a second, manual `.env` edit, and it
  mostly never happened. Measured: of the **116 SG/HK/CN asset nodes** added
  across §4.24 and the prior sessions, only **29 were on the live
  watchlist** — 87 were graph-only, buyable by nobody, brain included. The
  same split exists for the US side; it just wasn't asked about first.
- **Fix.** `brain/seed.py` gained `tradable_stock_symbols()` — every
  `SEED_NODES` asset with a resolved symbol, sorted, CRYPTO excluded (that
  goes through `crypto_watchlist`/ccxt on a different symbol format).
  `config.py`'s `stock_watchlist` now falls back to this instead of a
  hardcoded 4-symbol default when `STOCK_WATCHLIST` is unset. Deliberately
  scoped to `SEED_NODES` (human-verified before merge, per §4.24's
  discipline) and not the live persisted graph, so an LLM-proposed node with
  an unverified symbol cannot become tradable with real capital before a
  human reviews it via the `lists_on`/`needs_you.py` path. `spy` was added
  as a graph node in the same pass — it was the one symbol already on the
  production watchlist with no corresponding graph node at all, and would
  otherwise have been silently dropped by the new default. Bumped
  `SEED_VERSION` to 34.
- **Deployed and verified, not just merged.** Full suite ran on the ProDesk's
  real `.venv` before touching anything (338 passed; the 8 failures in
  `test_alert_storm.py`/`test_bullshit_layer.py` were confirmed identical on
  the prior commit — pre-existing, unrelated). The production `STOCK_WATCHLIST`
  line in `.env` was commented out (backed up first) so the new graph-derived
  default takes over; engine restarted clean, 0 crash-loop. Checked on the
  box, not assumed: `stock_watchlist` now resolves to **258 symbols** (up
  from ~80), confirmed `C6L.SI` (SIA), `688836.SS` (Unitree) and `SPCX`
  (SpaceX) all present. Then checked one level deeper than "it's configured"
  — pulled real fundamentals for four of the newly-added names: SIA,
  SpaceX and BYD (`1211.HK`) all returned genuine data (PE, price/book,
  debt/equity); Unitree returned only a timestamp, no fields — the data
  provider (yfinance) simply hasn't indexed a STAR Market IPO from six weeks
  ago yet. Real, known limitation, not a bug: some very fresh listings will
  be tradable via Longbridge with gappy fundamentals until the provider
  catches up.
- **Malaysia, investigated and closed out.** The user asked whether Longbridge
  or moomoo could reach Bursa Malaysia. Longbridge: confirmed no (US/HK/CN/SG
  only, per their own docs). moomoo: has a `MoomooBroker` adapter already in
  `brokers/live.py`, unused (`STOCK_BROKER=longbridge` on ProDesk), and
  investigating it end-to-end (downloading OpenD, running it headless on
  ProDesk, hitting a graphic-CAPTCHA the console UI can't render, then
  logging in successfully via the GUI AppImage on a local machine instead)
  surfaced the real answer: **the account is with Moomoo Financial SG, and
  its own account-management screen states "you have activated all the
  trading permissions" — Malaysia is not among them, because Bursa Malaysia
  access is a separate legal entity (Moomoo Securities Malaysia Sdn Bhd),** not
  a togglable permission on an SG account. Not fixable from this codebase;
  parked by user decision rather than left as an open bug. `~/moomoo_OpenD/`
  is left in place on the ProDesk, unused, in case a genuine Malaysia account
  is opened later.
- **Side effect worth watching, not yet a problem.** The 3× larger watchlist
  means more fundamentals lookups and news-tagging per cycle. `daily_status.py`
  flagged the `vgxfw` LLM endpoint at 40% of its 5M free daily token budget,
  projected to ~102% by day end — the first day this has happened. The
  provider-rotation logic (`data/news.py`, `_over_free_budget`) fails open
  onto the next endpoint in the chain rather than blocking, so nothing breaks
  today; if every endpoint in a chain crosses its free tier the calls simply
  start costing a small real amount rather than failing. Worth checking
  `daily_status.py` over the next few days to see if usage settles or keeps
  trending toward the cap.
- **Lesson.** §4.24 fixed *whether the brain can learn a company exists*.
  This was the other half of the same sentence — *whether knowing about it
  does anything* — and it was broken the entire time §4.24 was being fixed,
  invisibly, because "the graph has the node" reads as done if nobody asks
  the next question. The user asking "then anything should be buyable,
  isn't it?" is what actually closed the loop; the gap would not have been
  found by more graph curation.

## 4A. Open defects — known, NOT fixed

The register above is history. This is the live list, and it is the honest answer
to "how are you keeping track". Until 2026-08-05 the answer was *commit messages*,
and the register had drifted **13 commits** behind reality.

| Open | Detail | Risk today |
|---|---|---|
| **The digester proposes edges 35× faster than the spec assumes** | `DIGESTION_SPEC.md` §A10 justifies applying llm edges automatically because *"a bad proposal is damped by the cap"* and *"Rare: expect ≤1 per week"*. Actual: 96 in 7 days, 35/week over 28. §4.22 built the measurement and the review, which is the symptom; the cause is the digester's proposal bar, and setting it is a judgement about how much self-wiring is wanted — not a bug to be quietly patched. **Unreviewed backlog: 140.** | LLM wiring is 18% of the graph and grows ~35/week against a fixed 656 curated edges. Nothing can grade these (`calibration.py` skips non-seed edges, and none terminates on a tradable symbol so it could not score them anyway), so the cap and human review are the whole control surface. Left as it is, self-added wiring outnumbers curated wiring inside a year. |
| **Non-USD live trading is off** | The FX conversion and HK symbol padding are written and unit-tested, but no HK/SGX order has ever been placed. The universe stays USD-only until one is, during those market hours. | **Now measured.** Of 33 distinct conviction-long calls (hit 0.742, avg +2.37% over 5d), 21 were never held in any book, averaging +3.01%. The largest were `2899.HK` (+10.6%, +10.0%, +8.5%) and `O39.SI` (+6.0%, +6.0%, +5.2%, +4.1%) — all correct, all blocked by this rule. |
| **The live position has no venue stop, and nobody knows why** | `place_stop` failed for AAPL on 2026-08-05; the runner recorded only `exchange_stop_unsupported` with no reason and the exception died in a log rotation. The stop price (282.38) was tick-legal, so §4.23 does **not** explain it. Both protective paths now snap to the tick and the reason is journalled + printed as `!! NO VENUE STOP`, so the next attempt will say why — but the current position is still unprotected at the venue. | The one live position relies on the engine's cycle stop, which only fires when a cycle runs — precisely what an overnight gap defeats. Bounded today by the position being a single $307 share. See OPERATIONS → *When the next LIVE order goes out*. |
| **The adviser predicts well; the books do not trade it** | Graded calls come from the brain's adviser (`brain/store.py`, `advice_log`); the books trade the formula engine's decisions (`runner.py`, `journal.db decisions`). They are separate systems and they disagree — `GLD` was a conviction long at +7.2% while the trading book scored it short/flat all week. Deduped: **long calls hit 0.672 (n=102), short/avoid hit 0.260 (n=129) with the tape +3.20% against them.** | The 0.404 headline blends a genuinely skilled long model with an actively anti-predictive short model, and the accurate signal is not the one wired to the money. A judgement call, not a bug — which is why it is here and not fixed. |
| ~~A fourth announce-the-state instance~~ | **CLOSED §4.17.** All 24 alert sites swept and classified; the fourth (news/context error) is fixed. | — |
| ~~Tests inherit the ambient `.env`~~ | **CLOSED §4.19.** A test process no longer loads `.env` at all, detected automatically. | — |
| **7 live-path loaders hardcode `data/`** | `data/{calendar_events,comps,estimates,fundamentals_history,ownership,value_scanner}.py` and `scalp/live.py` build their path from `__file__`, so no caller or test can redirect them (§4.21). All are read-only reference loaders that decide no trade, which is why they were not swept in one change. | A test touching them reads live data and can flip with the market — the §4.21 failure mode. `test_data_path_isolation.py` pins the list so it cannot grow. |
| **`prices[key] = 0.0` still means "no data"** | The runner encodes a missing bar as zero — a sentinel that means *absent* and reads as *free*. It caused §4.7 and is currently contained by `mark_price()` at every consumer rather than removed at the source. The root fix is to omit the key, which touches every price consumer. | Contained, not gone. A new consumer that forgets `mark_price` reopens §4.7. |
| **θ has been reset to v1** | Done, with the old file in `data/retired/`. The `journal.db` params rows from the crash loop remain — duplicates of identical θ under rising versions. | Historical noise in the params history only. |
| **Main-loop coverage is one smoke test** | `test_runner_cycle.py` proves a cycle executes; it does not verify what the cycle DECIDES. Everything between "runs" and "correct" is still uncovered. | The largest untested surface in the repo. |
| **The sleeve's risk/reward is inverted** | `expected_move` ≈ 0.3–0.5% against a 10% hard stop — roughly 32:1 on the model's own numbers, needing ~97% accuracy to break even. Left deliberately (see §5) to let the record prove it. | Structural losses in the ⚡ book. |
| **One dangling claim in the ledger** | The discarded USO claim from defect 4 can never be settled. It stays in `expectations.jsonl` as a permanently open row. | Minor; one unresolved row in the corpus. |
| **`RATIO_CLIP` hides severity beyond 3×** | The true USO ratio was −32.6, recorded as −3.0. Deliberate (one freak outcome must not rewrite the model) but it means the calibration gain cannot see how far off it really was. | Slow expectation calibration. |
| **Crypto coverage is 6, not 10** | 7 of 13 coins score under `MIN_SCORE` and are reported in `no_view` rather than given a manufactured direction. | Fewer learning data points than requested. |
| **New-company discovery still has a manual step** (§4.24) | The `lists_on` digester path and `graph_gap_scan.py` cover the two automatable layers, but the news archives are too thin/generic right now for the gap-scan's frequency heuristic to catch China/HK-specific names on its own — CXMT was the one real hit out of ~180 candidates at loose thresholds, and Hengrui/Haitian/Sanhua/JCET were found by neither tool, only by directly searching "biggest HK/CN IPOs" and checking each result against the graph. **Recommendation: keep doing that sweep periodically by hand** (monthly, or whenever a market-moving China/HK/SG headline seems suspiciously absent from the graph) until the archives have enough volume for the gap-scan to plausibly take over — re-run `graph_gap_scan.py` first each time to check whether it's started catching real names on its own, since that's the signal the manual step is no longer needed. | Until archive volume grows, coverage gaps in fast-moving sectors (semiconductors, robotics, anything with a hot IPO pipeline) will keep recurring silently between sweeps. |
| **The 258-symbol watchlist is pushing one LLM endpoint toward its free daily cap** (§4.25) | `vgxfw` hit 40% of its 5M free daily tokens by mid-afternoon on the first day the graph-derived watchlist went live, projected to ~102% by day end. Rotation onto other endpoints is automatic and fails open, so nothing breaks — but if every endpoint in a chain crosses its free tier, calls start costing a small real amount silently. | Cost, not correctness. Watch `daily_status.py` for a few more days to see if usage settles as caches warm up, or keeps trending toward the cap. |
| ~~The leaked Gemini key~~ | **CLOSED 2026-08-05 — the user revoked it at Gemini.** `.env.example` deleted, docs redacted, and every tracked file now scanned. | — |
| **Git history still contains the revoked string** | `git filter-repo`/BFG could purge it, at the cost of rewriting every commit hash and breaking any clone. Unnecessary now the key is dead. | None. A revoked key is just a string. |
| **`shadow.json` held `NaN` cash** | Retired in the reset, so it rebuilds clean — but nothing prevents it recurring, and no test covers the shadow book's arithmetic. | The A/B baseline can silently corrupt again. |

## 5. What is unverified or uncertain

**Ranked by how much I would worry.**

1. **No live-money validation, ever.** Broker adapters have never touched a
   funded account. Slippage, partial fills, rejects, borrow availability for
   shorts — all unmodelled beyond assumptions.

   Partially advanced 2026-08-04: `--check-broker` now returns `[ok] stocks` on a
   Longbridge **paper** account. Note what that cost to discover — the check had
   never been run, and it failed with `ModuleNotFoundError: No module named
   'longport'` because `requirements.txt` pinned the `longbridge` PyPI package
   while `brokers/live.py` imports `longport.openapi`. Two real packages, same
   version line, different top-level names. **The adapter could never have
   constructed, in any environment, since it was written.** An untested code path
   is not "probably fine"; this one was unrunnable and nothing said so.

   Still unverified even on paper: order placement, fill semantics, cancellation,
   rejects, and the symbol-format assumptions in the HK/US routing. Paper accounts
   also do not support OTC or pre/post-market trading, so those cannot be
   validated this way at all.

   Crypto now returns `[ok]` too, so as of 2026-08-04 **both legs authenticate
   for the first time**:

   ```
   [ok]  stocks: {'broker': 'longbridge',  'cash': 14144300.0, 'positions': 0}   # paper acct
   [ok]  crypto: {'broker': 'ccxt:gemini', 'cash': 0.0,        'positions': 0}   # empty acct
   ```

   Two false trails were worth the walk. The first `[FAIL]` said
   `gemini sign() requires an account-key, master-keys are not-supported` — but
   the production key was never being tried: `CRYPTO_SANDBOX=true` makes the
   adapter read `CRYPTO_SANDBOX_API_*` instead (`live.py:33`), and *that* was the
   master key. The second, once pointed at the right credential, was
   `ApiKey fails IP Filtering Check` — a stale entry in Gemini's allowlist, the
   home IP having rotated. Neither error named the variable or the address at
   fault, which is why both cost a round trip to diagnose.

   **Read those two zeros carefully.** The stock leg is a *paper* account and the
   crypto leg is an *empty* one, deliberately segregated from the user's real
   holdings after §4.13. They prove credentials, transport, IP allowlisting and
   the balance call — nothing about placing an order.

   **The ORDER PATH is now verified too, on 2026-08-04, end to end:**

   ```
   BUY  1 F  -> filled 1.0 @ $13.99   (real price from order_detail, not the mark)
        stop rested   MIT -8%    id 1269301574736326656
        take-profit   LIT +25%   id 1269301575151562752   both cancelled cleanly
   SELL 2 F  -> filled 2.0 @ $14.005  entry $14.00  realised +$0.01
   ```

   Submission, fill confirmation, venue-resting exits, cancellation and the exit
   path all exercised against the live API. That test is what exposed the fill
   fabrication in §4.15 — the same call reported `$0.00` before the fix.

   **Still unverified:** anything against a FUNDED account (slippage on size,
   partial fills, borrow); non-USD order placement (HK/SGX — code written, no fill
   ever placed); OTC and pre/post-market, which paper accounts do not support at
   all; and whether a venue-resting stop actually TRIGGERS, since none has been
   touched by price yet. Placing a stop is not the same as having one fire.

   **Cost of getting here:** `CRYPTO_SANDBOX=false` and `LIVE_TRADING=true` between
   them have removed both of the independent barriers that used to sit in front of
   live routing. What remains is that the accounts themselves hold nothing of value
   — a broker paper account and an empty segregated exchange account — plus a
   $10,000 slice ceiling. **The safety now comes from the accounts, not from the
   flags.** That is a real reduction in defence-in-depth and it is the reason the
   Gemini key had to be segregated first.
2. **The learning spine has run exactly once.** As of 2026-08-05:
   1 settled claim, 2 open, both `expectations.jsonl` and `learning_state.json` now
   on disk. The one settlement (`event:USO`, expected +0.31%, realised −10.06%) was
   enough to expose two defects in the spine itself and one in the sleeve's
   risk/reward — see §4.15. So its behaviour is now *observed*, on a sample of one,
   which is a different kind of unverified from before but still unverified. Note
   the sleeve's three earlier profitable exits did **not** settle through it: they
   predate the wiring, so the first realised profits taught the learner nothing.
3. **The lockbox is burned.** It was spent on the two-book configuration; the
   current four-policy system has no clean out-of-sample exam. My recommendation
   — not yet accepted — is to treat the forward paper record as the real test
   and stop tuning against history.
4. **How much of the current portfolio value is a real mark is unknown while the
   feed is throttled.** 6 of 8 investing positions are held at cost (§4.11). The
   figure is "no worse than cost" — honest, but not a valuation. It becomes a true
   mark only once the feed recovers and `stale_marks` reads 0.
5. **The equity marks were repaired against the journal, not recovered.**
   `scripts/breaker.py --repair-marks` rebuilt `peak_equity` ($100,142) and
   `day_start_equity` ($99,997) from trusted journal rows after §4.7. That is a
   *reconstruction*: the true peak may have fallen between recorded cycles, and
   the day's real opening mark was overwritten by the phantom before any honest
   cycle ran. The repair deliberately errs low, so it can never manufacture
   headroom the book did not have — but the marks are inferred, not observed.
6. **The twelve positions closed by the phantom halt are gone.** Nothing reopened
   them; the engine re-decides from current signals, which is correct, but the
   forward record now contains twelve exits no strategy chose. They cannot
   corrupt the learning spine for two independent reasons — they fall inside a
   journalled outage window (`gap_affected`), and the spine has never opened a
   claim at all. Checked, not assumed. The second reason is the load-bearing one
   today and disappears the moment the spine starts working, so the gap window is
   what must hold long-term.
7. **The golden set is 50 items and has been tuned against three times.** The
   66% ORIGIN figure is a *relative* comparison between models, not an unbiased
   estimate. Inspecting the failures showed ~4 of 7 were defensible alternative
   nodes rather than errors, so true accuracy is higher than the metric — but an
   alternative node still propagates differently from the calibrated one.
   Run-to-run variance is 2–4 points, so gaps smaller than that are noise.
8. **Backtest-to-live gap.** All strategy validation is walk-forward on
   historical data with modelled costs. Real crypto 24/7 microstructure, exchange
   outages and funding dynamics are approximations.
9. **Shorts.** Six independent rejections in testing; the investing book still
   holds short positions from an earlier configuration. Not obviously consistent,
   and worth revisiting. Note that shorts are what turned §4.7 and §4.10 from
   cosmetic bugs into a liquidation: an unpriced short reads as a debt forgiven.
10. **`$25/day` target.** Never demonstrated. No book has produced a verified
    profitable forward record. The only realised P&L to date is the sleeve's
    **+$437** across three trades — real, but far too small a sample to mean
    anything.
11. **Advice hit-rate is 0.404 over 30 days** — below a coin flip for directional
    calls, on 170 graded outcomes. This is the first honest reading the system has
    ever produced (see §4.6); it was 0.689 while contaminated. Whether 0.404
    reflects genuine skill deficit or a scoring definition that mixes `long` with
    `short_or_avoid` has **not** been investigated yet.
12. **The X capture's contribution is unmeasured.** It now reaches the brain
    (§4.9) and 57 events are tagged from it, but no scored outcome yet attributes
    anything to that channel. Its per-handle trust values are priors, not measured
    precision.

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
- **GDELT crawler paused** at 303/1,136 days, by request.
- **Human-review backlog, offline half** — the corpus digester's own
  `proposed_edges` and integrity flags, listed in `data/digest_v2/STATUS.md`:
  **8 proposed edges, 39 integrity patterns, 2 graph contradictions, 70 alias
  suggestions.** These were never applied to the graph, so unlike the live
  backlog in §4A they steer nothing while they wait — which is why
  `needs_you.py` deliberately does *not* nag about them. Reviewing inert
  proposals is the mistake `5fd6087` fixed for dead trade proposals.

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
was invisible; a captured feed was written and never read.

So the standing rule is: **measure the thing that decides, not the thing that
is easy to measure** — and when a component has no audit, assume it is the
broken one, because that is where every one of these has been found.

Three corollaries earned on 2026-08-04, each from a defect that had already been
"fixed" once:

1. **A safeguard is only as good as the number it reads.** The circuit breaker
   worked perfectly — on a fabricated equity. Guard what the marks are made of,
   not just what is done with them. A mark taken from a bad valuation is permanent
   damage, because every honest reading afterwards is measured against a fiction.
2. **One rule implemented in N places is N chances to be wrong.** The
   zero-price hole existed in all four books; fixing one and declaring victory is
   how a fix becomes a false sense of coverage. Find the other implementations
   before writing the commit message.
3. **A fallback never exercised under its own failure mode is an assumption.**
   `LastGoodBarCache` was written for a blanket feed outage and could not survive
   the restart that usually accompanies one. Test the net under the fall.
4. **NaN is the most dangerous value here.** It caused three separate failures in
   one day: it walked past the circuit breaker (§4.7), it was stored as a good
   price by the cache (§4.11), and it defeats every `<= 0` guard in the codebase
   because it fails comparisons silently rather than loudly. Reject it at the
   boundary where data enters, not at each of the places it can hurt.

And the uncomfortable one: **verification is not free.** Restarting the service
four times to confirm fixes is what throttled the price feed and produced the
next incident.
