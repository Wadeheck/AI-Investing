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

As of 2026-08-04 both adapters **authenticate** for the first time —
Longbridge against a *paper* account (`ac: lb_papertrading`) and Gemini against a
deliberately *empty*, separate account. Read-only, reporting cash and zero
positions. It proves credentials, transport and the balance call; it proves
**nothing** about placing, filling, or cancelling an order, and an empty account
cannot prove it. See §5.1.

## 2. Where it stands today

```
GRAPH    321 nodes, 690 edges          (seed v25)
BRAIN    5,042 articles, 1,766 events tagged   (57 now from the X capture)
TAGGER   2% unsigned across 1,474 recent events     (was 57%)
TESTS    24 suites, all green
COMMITS  134

BOOKS            equity      cash     pos   at cost
  📈 trading   $ 99,997    $ 99,997     0     -     (flat after §4.7; re-entering)
  🏛 investing $ 99,913    $105,356     8     6
  ⚡ sleeve    $100,437    $100,437     0     0     (+$437 realised, see below)
  ₿ crypto     $100,000    $100,000     0     0     (bear mode, deliberately flat)
  ------------------------------------------------
  TOTAL        $400,347   on $400,000 staked  (+0.09%)
```

Read **equity**, not cash. Three of these books hold shorts, whose sale proceeds
sit in cash while the shares are still owed — which is why cash exceeds equity in
the investing book, and why cash is never the portfolio's value. Conflating the
two caused §4.4, and valuing a short at a zero price caused §4.7.

**"at cost" is the honest caveat on the numbers above.** It counts positions
marked at cost basis because no live price is available. As of this writing the
feed is returning `0.0` for all 88 symbols (throttled — see §4.11), so 6 of the
investing book's 8 positions are held at their entry price. That book's equity is
therefore *"no worse than cost"*, not a true mark. It is reported this way
deliberately: the alternative — dropping unpriced positions out of equity — is
precisely the bug in §4.10.

**First realised P&L in the system's history**, and it came from the event sleeve:
three positions closed on its 2-day clock, all profitable — 9988.HK **+$326**,
0700.HK **+$105**, 3690.HK **+$6**. Total **+$437**. Every other number in the
table above is still unrealised or untraded, so this is the only line that has
been settled by the market rather than by a mark.

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
   the balance call. They prove nothing about placing an order, and an empty
   account **cannot** prove it — order validation needs a funded balance, however
   small.

   Still unverified on both legs: order placement, fill semantics, partial fills,
   cancellation, rejects, and the symbol-format assumptions in the HK/US routing.
   Paper stock accounts additionally do not support OTC or pre/post-market
   trading, so those cannot be validated this way at all.

   **Cost of getting here:** `CRYPTO_SANDBOX` is now `false`, which removes one of
   the two independent barriers in front of live crypto. `LIVE_TRADING=false` and
   the `get_broker()` choke point are what remain. That is an acceptable trade only
   because the account behind the key is empty and separate; it would not have been
   against the account in §4.13.
2. **The learning spine has never run.** 0 settled claims; neither
   `expectations.jsonl` nor `learning_state.json` exists on disk. Its behaviour is
   test-verified, not observed. Note the event sleeve's three profitable exits did
   **not** settle through it — the sleeve keeps its own journal, so the first
   realised P&L in the system taught the learner nothing.
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
