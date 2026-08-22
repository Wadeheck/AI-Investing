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

*Rewritten 2026-08-05; numbers refreshed 2026-08-21 from the live ProDesk state
via `scripts/brain_audit.py`. **Do not hand-edit these figures** — re-run the
audit and paste. The previous set had drifted by 182 nodes and 323 edges before
anyone noticed.*

```
GRAPH    604 nodes, 1,122 edges = 802 curated + 320 LLM-proposed  (seed v39)
                                        464 of the nodes are assets.
                                        STOCK_WATCHLIST and CRYPTO_WATCHLIST are
                                        DERIVED from these — 258 tradable stock
                                        symbols (up from ~80 hand-maintained,
                                        §4.25) and 17 crypto (§4.26).
                                        LLM wiring is 28.5% of the graph and now
                                        capped at 6 new edges/day (§4.38).
RESOLUTION  202 distinct response signatures across 464 assets = 43.5%.
                                        200 assets are inert to every macro
                                        shock; 104 are an exact duplicate of a
                                        peer. The graph tells apart fewer
                                        objects than it holds — §4.39.
BRAIN    45,991 articles, 36,376 events tagged
TAGGER   0% unsigned across recent events              (was 57%)
TESTS    65 files / 682 tests, green under BOTH runners (the project's own
         `python3 tests/test_x.py` and `pytest engine/tests/`), on both
         machines, and under random ordering — see §4.40 and §4.46
COMMITS  304

BOOKS — restarted at USD 10,000 on 2026-08-05, by request; marks below are
        live from the audit run of 2026-08-21T14:15Z
  📈 trading      LIVE, routed to a Longbridge PAPER account
                  equity 9,981.99   cash 4,176.21   11 positions   41.8% idle
  🏛 investing    paper
                  equity 9,817.74   cash 5,645.47    3 positions   57.5% idle
  ⚡ sleeve       paper
                  equity 11,355.73  cash 11,355.73   0 positions  100% idle
                  (flat between events, not frozen — +1,146.21 realised)
  ₿ crypto       Binance Futures TESTNET, basis changed 2026-08-20
                  equity 5,007.99    3 positions.  Cash is COLLATERAL, so
                  "idle %" is meaningless on this book and the audit prints null.
  ₿ crypto-event Binance Futures TESTNET
                  equity 4,805.29    1 position
  ORDER FLOW      39 filled (24 buys) · 7 pending · 34 rejected
                  The rejected count is NOT all one fault — see §5.3 and the
                  `602035` row in §4A.

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

**The live book is no longer idle, and the paragraph that used to sit here was
wrong by 2026-08-21.** It read *"the live book is currently idle"* on the strength
of `state.json.broker.positions` being empty — which is empty **by construction**
for a routed book, whose positions live in the `BookLedger` (`live_book.json`). The
book had 24 filled buys and 11 open positions while that sentence stood. §4.43
records the mistake; `brain_audit.py` now names its `positions_source` on every
book so the same misreading cannot be repeated silently.

What WAS true, and is now fixed, is the cause underneath it: of 99 decisions only
13 cleared the confidence floor and **12 of those were shorts**, which neither
paper venue permits (§4.15). That was not a market view being blocked — it was 40%
of the strategist's thesis capacity being spent on positions that cannot open.
§4.42 downgrades an unexecutable short to `avoid` at ingestion, so the capacity
goes to something tradable. The single qualifying long, `O39.SI`, is still excluded
because the live slice is USD-only until non-USD is validated (§4A).

Read **equity**, not cash. A short's sale proceeds sit in cash while the shares
are still owed, so cash is never a book's value. Conflating the two caused §4.4,
and valuing a short at a zero price caused §4.7. (Moot in the 📈 book today —
shorting is off, because neither paper venue permits it.)

**The learning spine has run: 19 settled claims** as of 2026-08-21, up from the
single `event:USO` row that first proved the instrument worked. Nineteen is still
not a track record, but it is now enough to have found a defect no single row
could: **15 of the 19 were clipped at ±3.0**, median |realised/expected| **14.4**,
max **106**. `expected_move` is systematically one to two orders of magnitude too
small, and the calibrator that exists to correct it was reading a signed average
and therefore correcting **backwards**. See §4.45 — and note that the sleeve's
much-quoted 32:1 risk/reward rests on the same broken `expected_move`, so that
figure is closer to 2:1 and was measuring an expectation, not a strategy.

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

| Book | Horizon | Mandate | US stocks execute on |
|---|---|---|---|
| 📈 trading | days–weeks | field conviction, long/short | the shared Longbridge account |
| 🏛 investing | ~6 months | thesis-driven | the shared Longbridge account |
| ⚡ event sleeve | 2 days | fresh shocks only, long-only, unlevered | the shared Longbridge account |
| ₿ crypto | 24/7 | own bear-exit logic, HODL core + tactical | local sim (Longbridge is stock-only) |

**`SHARED_STOCK_ACCOUNT=true` since 2026-08-16.** All three stock books now
place real orders against the one Longbridge demo account (`LBPT10097995`,
`lb_papertrading` channel — still not funded money) instead of each pretending
against its own simulator. That simulator is how the sleeve "bought" 15.82
shares of NVDA on a Sunday. Each book keeps its own `BookLedger`, sees and sells
only what it has claimed, and reconciles against the account every cycle.

Three consequences, all deliberate: **stock shorts are off** for every book (at
the venue, opening a short and selling another book's shares are the same
order); **venue-side resting stops are skipped** (a stop firing hours later
cannot be attributed to a book); **non-USD listings stay simulated** (`PRX.AS`,
`*.HK` — Longbridge symbols only round-trip for `.US`). Read
[`design/SHARED_ACCOUNT.md`](../design/SHARED_ACCOUNT.md) before changing any of
it.

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
§4.15–4.21 are the autonomy session. §4.22 is the self-wiring review.
**§4.37–4.40 are the 2026-08-21 structural review** — the measurement layer, the
graph's resolution, and self-wiring's missing control. §4A is the live list of
what is still broken — read that one first if something is wrong now.

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
| 4.24 | The graph had no way to learn a company exists until a human noticed | ✅ `lists_on` digester path + `graph_gap_scan.py`; still needs a periodic manual sweep (§4A) |
| 4.25 | The graph and the tradable universe (`STOCK_WATCHLIST`) had silently drifted apart | ✅ `tradable_stock_symbols()`; watchlist now derives from the graph |
| 4.26 | 9 graph nodes had zero edges; `CRYPTO_WATCHLIST` had the same drift as §4.25 | ✅ all nodes wired; `tradable_crypto_symbols()` added; deployed + verified on the ProDesk |
| 4.37 | The scorecard counted one standing view 65 times; two reviews drew opposite conclusions from it | ✅ `is_primary` counting unit; both sides of the adviser gate; the reliability EMA |
| 4.38 | A node called `none` was the graph's 17th most connected node | ✅ refused by shape; 14 found and pruned with tombstones; self-wiring capped at 6/day |
| 4.39 | The graph resolves 202 objects and holds 462 | ⚠️ **Partial** — conviction discounted by 1/√(group); differentiating wiring is still open curation work |
| 4.40 | The suite is green under the project runner and red under pytest | ✅ Both runners green, 62 files / 645 tests, under random ordering too |
| 4.41 | The crypto book could not afford its own mandate; 100% cash for a day, silently | ✅ Trade floors derived from the book, never hardcoded; unfilled buys logged; `held` reconciled |
| 4.42 | 40% of the strategist's thesis capacity spent on shorts the venue refuses | ✅ The rule follows execution; ingestion downgrades short → avoid |
| 4.43 | I read two trading books as frozen that were trading normally | ✅ The audit reads the authoritative source per book |
| 4.44 | Three tests written to close a defect passed with the bug put back | ✅ Mutation-tested; all now fail on re-introduction |
| 4.45 | The expectation calibrator shrank an expectation that was 14x too small | ✅ Signed average for drift, magnitude average for the gain; true ratio journalled |
| 4.46 | The suite was green here and 17 red on the ProDesk, under the same commit | ✅ `.env` detection now fires at collection time (`sys.modules` check), not test-start |
| 4.47 | The calibrator was three days from halving six relationships on four observations | ✅ `MIN_N` 20→60 for causal edges, 120 to demote a membership; deliberate, not yet graded (§4A) |
| 4.48 | §4.40's own fix killed the X capture channel, and its own guard blessed it | ✅ Real `main(argv=None)`; guards now check the name is BOUND and that every argparse script still starts |
| 4.49 | A number that is not valid JSON survived every restart, in every state file | ✅ `allow_nan=False` on write, non-finite refused on read, and the 0.0 price sentinel removed from the shadow path too |
| 4.50 | A cleanup rule I wrote deleted Procter & Gamble from the live graph | ✅ `&` survives normalisation as `and`; node and edge restored; every `is_non_entity` caller must pass a type |
| 4.51 | "The model under-predicts by 14x" was noise; and every equity claim was sized off one 2% constant | ✅ Gains NOT raised, with the noise floor now audited beside the ratio; `_shock_assets` enriched so vol is the asset's own |
| 4.52 | The basis cue fired negative: the runner's own equity journal was the fifth path | ✅ `stock_journal.jsonl` marks now declare `basis` + `basis_changed`, seeded from the file |
| 4.53 | The reach table used to justify a first live order was noise, ranked | ✅ `n_independent` + computed `significant` on every row; the "best where it cannot trade" finding retired |
| 4.54 | The defect rate tracked how hard someone looked | ✅ `defect_sweep.py` asks the four questions that found 13 of 17, mechanically |
| 4.55 | First order on an unproven path — decided | ✅ NO on the trade (1 independent observation); path validation kept as a separate, minimal test |
| 4.56 | The P&L was the last layer still counting tickers instead of decisions | ✅ `brain_audit --section pnl` reports per-fill AND per-basket; all four books: edge not demonstrated |

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

### 4.26 Nine graph nodes with zero edges, and the same watchlist drift on the crypto side *(2026-08-14)*

**Found by the user asking for a general audit** ("make sure all the nodes...
are wired properly") rather than a specific symptom — §4.25 fixed the
graph↔watchlist split for the *whole* stock universe, but nobody had checked
whether every individual node inside that universe was actually reachable.

- **What — nine orphan asset nodes.** All 116 SG/HK/CN nodes from §4.24/§4.25
  have a graph *id*, but 9 of them (China Mobile, Swire Pacific, Techtronic,
  Lenovo, COSCO Shipping, Midea, China Yangtze Power, Wilmar, FactSet) had
  **zero edges** — no `member_of`, `influences`, `owns`, or `regulated_by`
  anything. They were tradable (§4.25 made them so) but invisible to
  `propagate()` and `centrality()`: a headline could shock the whole graph and
  never reach them, and they could never influence anything else either.
  Graph-listed is not the same property as graph-*wired*, and nothing had
  measured the second one.
- **Fix.** Wired each with specific, checkable business relationships rather
  than a generic sector placeholder: Swire's ~45% stake in Cathay Pacific
  (already a graph node, `owns`), Midea's KUKA robotics acquisition
  (`member_of robotics`), COSCO into `freight_logistics` alongside UPS/FedEx,
  `regulated_by china_government` edges for the four SOEs (China Mobile,
  COSCO, China Yangtze Power — SASAC/NDRC-controlled), Wilmar as the Asian
  ADM/Bunge (`member_of food_processing`, weight 0.85 matching that
  precedent), FactSet correlated (not membered) into `us_financials` since it
  sells data subscriptions rather than banking. Verified after: 0 orphan
  nodes, 0 dangling edge references, 0 duplicate edges across the full
  420-node graph — this is now a checkable invariant, not a one-time sweep.
- **Same audit, crypto side: the §4.25 fix had a twin nobody had built.**
  `CRYPTO_WATCHLIST` was still a hardcoded `BTC/USD,ETH/USD,SOL/USD` in
  `config.py`'s default and in this box's `.env` — dating to seed v21
  (2026-07-31), where the commit message explicitly called it *"pending
  crypto news depth"*, a deliberate but temporary restriction. `adviser.py`'s
  own comments (dated 2026-08-04) showed a 13-coin watchlist had already been
  scored live since then, so the gate the v21 pin was waiting on had already
  been exercised — the pin had just never been lifted. Added
  `brain.seed.tradable_crypto_symbols()` (mirrors `tradable_stock_symbols()`
  exactly) and wired `config.py`'s `crypto_watchlist` default to it.
- **Two real bugs the audit turned up along the way.** `ARB` and `TAO`'s
  seeded symbols were `ARB11841/USD` and `TAO22974/USD` — CoinGecko-style
  numeric disambiguator IDs that had leaked into the symbol field at seed v21
  and would have made ccxt's `fetch_ohlcv` fail for both, silently, the
  moment either was ever actually watched. Nothing had caught this because
  nothing had watched them until this fix. Corrected to plain `ARB/USD` /
  `TAO/USD`.
- **Asked directly whether crypto coverage was "competent" for GPU-compute/AI
  narratives** — checked, not assumed: RENDER/TAO/FET/AKT are wired to
  `ai_capex_cycle`/`ai_datacenter`, and three of those four edges already
  carry real calibration verdicts from a 7k-event corpus (2026-08-02): AKT's
  link is **supported** (n=66, hit 54%, t=+2.1); TAO's and FET's membership in
  the generic `crypto_majors` bucket is **contradicted** (n=29, t≈-2.0,
  "AI-token beta runs on its own narrative, not the majors' tide") — a
  wrong-but-plausible assumption the calibrator had already caught and
  downweighted before this session touched it. One real gap found by web
  search: **io.net** (IO), a decentralized GPU-compute network in the same
  niche as Akash/Render (Binance/Coinbase-listed, ~2,700 verified GPUs across
  138 countries as of Aug 2026), had no graph node. Added, wired the same way
  as Akash, and explicitly labeled `"no calibration run yet... weight is a
  prior, not measured"` rather than borrowing Akash's supported verdict for
  an unrelated token. Bumped `SEED_VERSION` 34 → 37 across the three fixes.
- **Deployed and verified, not just merged — and the deploy found a fourth
  bug the dev box could not have shown.** This ThinkPad's `.env` (a stale
  local copy) still had the old 3-coin pin, so testing the fallback here
  looked clean. The ProDesk's real `.env` did not: it carried its own
  hand-verified 13-symbol list (`BTC,ETH,SOL,LINK,LTC,BCH,AVAX,DOGE,XRP,DOT,
  UNI,AAVE,ATOM`) with a comment noting `ADA` had been excluded for having no
  bars on Gemini, the box's actual `CRYPTO_EXCHANGE`. Blindly switching
  ProDesk to the graph-derived fallback would have been a regression dressed
  as a fix: it would have silently dropped 6 real, currently-scored coins
  (none of which have graph nodes) while adding 4 that don't exist on
  Gemini at all. Checked directly on the ProDesk with a live `ccxt.gemini()`
  probe before changing anything: of the 8 graph-curated candidates, INJ,
  ARB, FET and HYPE are listed with real bars; RENDER, TAO, AKT and the new
  IO are not. Applied the verified union instead of the fallback — kept all
  13 working coins, added the 4 confirmed-listed graph ones — 17 total,
  written explicitly into `.env` rather than left to the code default, with
  the Gemini-availability finding recorded inline so it isn't rediscovered
  the hard way. Confirmed with the user before writing to the live box's
  `.env` (the harness's own auto-mode classifier blocked the first attempt,
  correctly, as a production-config write). Full 24-suite test run on the
  ProDesk's real `.venv` passed before any restart; one restart (not
  repeated — see §4.25's own warning about refetch storms); `daily_status.py`
  after showed all channels current and the paper engine already cycled.
  Confirmed in `data/knowledge_graph.json` on the ProDesk itself: `seed_version:
  37`, `io_net` present, `arb`/`tao` symbols fixed — the merge is live, not
  pending next boot.
- **Lesson.** §4.25 asked "is everything in the graph buyable?" and fixed
  the stock half. This session asked the two questions §4.25 didn't:
  "is everything *reachable*?" (no — 9 nodes) and "did the *other* watchlist
  have the same drift?" (yes, plus its own local variant nobody had
  documented — the ProDesk's hand list, right for reasons the graph
  default couldn't see). A fallback that's correct in general can still be
  wrong on a specific box; checking the box directly is what caught it, not
  re-deriving the fallback more carefully.

### 4.27 The sleeve spent its book once per cycle while orders queued *(2026-08-17)*

The night after the shared-account cutover, the ⚡ sleeve accumulated **ten live
buy orders worth $33,946 against a $7,612 book** — 4.46x, on a sleeve whose
docstring says LONG ONLY AND UNLEVERED, against a three-position limit,
including exact duplicates (NVDA ×2, AMD ×2), all queued to fill together at the
opening bell. A reproduction of twenty cycles against a closed market produces
**sixty** orders. They were cancelled at the venue before the market opened.

**Cause.** Longbridge answers anything submitted outside US market hours with
`NotReported` — queued, not filled, not rejected. That is honestly PENDING, and
everything downstream was written against fills: `get_cash()` returned the
ledger (which does not move until a fill), the slot count read positions, and
both re-entry guards were fill-gated. So every cycle saw a full book, three free
slots, and a symbol it had not "acted on".

**The general shape, and the reason it is worth a register entry.** *Submitted*
and *filled* are different states, and every guard in this engine had been
written when they could not be. The simulator filled instantly for the whole of
the project's life, so "do I hold this?" and "have I acted on this?" were the
same question — and the day a real venue could say "not yet", every guard that
conflated them failed at once, in the same direction, silently. The fix is not
one check but a rule: **cash committed to a live order is not cash, and a symbol
with an order in flight has been acted on.** The trading book reached the same
door by a different route (`size_orders` computes `delta = target − current
notional` from positions), and its exit path was worse — a re-fired exit while
the first sat queued would have sold the same shares twice, taking the account
short or straight through another book's position.

Three smaller ones from the same night: a queued order was journalled as
`rejected`, which reads as "the sleeve declined this shock" when it had money
riding on it; the stuck-order warning fired on every poll rather than once,
writing **209 journal lines about nine orders in one evening** (§4.16 again —
the noise hides the diagnosis); and recording the intent at submission created
the mirror hazard, so a Day order that simply expired would have barred its
symbol for good, now released as an invariant rather than an event handler.

### 4.28 The formula has never learned anything *(2026-08-17)*

`outcomes` held **zero rows after sixteen days live and thirty-one filled
orders**. RLS updates: 0. θ is still the hand-set priors it shipped with. Every
cycle header has said `θv1 (learned from 0 trades)` the whole time, and it reads
as a version string rather than as an alarm.

Two causes, and only one is a defect.

**The book has closed almost nothing**, which is a strategy fact — see §5's entry
on reach. Driven through a full open/close by hand, the loop emits a sample
correctly, so nothing is broken in it.

**`OutcomeTracker._open` was memory-only.** The map from an open position back to
the feature vector that opened it was rebuilt empty in every `Runner`
constructor and written nowhere. The ProDesk powers off 05:00–07:30 SGT nightly
and the trading book holds for days to weeks, so a position was re-registered
each morning with *that morning's* φ. When it finally closed, the learner would
have been handed **(today's φ, a two-week return)**.

That is not a lost sample, which is merely slow. It is a wrong one — it teaches
the model that this morning's features caused a move decided on a fortnight ago,
and the RLS has no way to tell. The only reason no damage was done is that
nothing has closed yet: the defect and the starvation were hiding each other.
Now persisted to `data/open_claims.json`, written every cycle *before* the
`LEARN_ONLINE` gate, so switching online learning on later does not start from
an empty ledger.

### 4.29 A stale docstring cost the book half its universe *(2026-08-17)*

`_live_universe()` restricted the live book to USD listings, so **78% of the
engine's strongest convictions pointed at names it had decided were
unreachable** and the trading book sat on two positions and 4% deployment. Two
reasons were given, in a docstring on `LongbridgeBroker.get_positions`, and both
were false when probed against the account:

- *"`cost_price` arrives in the LISTING currency"* — it did, and it was already
  converted, by the `fx.to_usd` call **three lines below the warning**. Somebody
  fixed the code and left the comment.
- *"Longbridge's symbol format only round-trips cleanly for `.US`"* — it
  round-trips fine. The **watchlist** speaks Yahoo (`D05.SI`, `600519.SS`) and
  Longbridge speaks its own dialect (`D05.SG`, `600519.SH`). An unknown string
  comes back as an **empty list**, not an error, so every "can we trade this?"
  answered no and the no was recorded as a fact about the venue.

Translated, the venue resolves **116 of the 126** non-USD names, and the account
holds SGD 1,000,000 and HKD 1,000,000 to trade them with. Ten have no Longbridge
symbol in any spelling and are genuinely out of reach.

**A stale warning is worse than no warning, because no warning gets
investigated.** This one supplied a plausible answer to a question nobody then
asked for a fortnight — and I repeated it as fact before testing it.

What was actually missing: the suffix map (`brokers/symbols.py`, defined once and
inverted so the two directions cannot drift), board lots (`brokers/lots.py` —
`risk._quantize_whole_shares` had carried *"KNOWN GAP: HK board lots are not
modelled"* since it was written), and converting prices back out of USD. Ticks
needed nothing: the HKEX spread table and SGX bid sizes were already there,
waiting for a caller. Universe went 132 → **248** symbols.

### 4.30 The first Hong Kong fill was booked at seven times its price *(2026-08-17)*

Within minutes of widening the reach, 100 shares of `3690.HK` filled at
HKD 8,870 — about **USD 1,129** — and went into a USD ledger at a cost basis of
**8,870**. The book's cash fell by seven times what it had spent, equity read
**$2,256 against a true $10,000**, and the daily notional cap, the drawdown
breaker and the learning spine's realised return all inherited it.

`executed_price` arrives in the listing currency. In the same session I had
converted every price going **out** — limits, stops, take-profits — and missed
the one coming **back in**. Now converted in `fetch_fill`, which is the only
place it can be: both fill paths run through it (`confirm_or_pend` for a
synchronous fill, `resolve_pending` for a late one), so either caller doing it
would leave the other wrong. Same rule as `cost_price`: **money crossing this
adapter is converted at the crossing, never after.**

The live ledger was repaired by re-booking the mark, using what the account
actually holds as ground truth rather than inferring which bases were corrupt —
the first repair script I wrote would have double-converted the investing book's
simulated HK theses and destroyed their cost basis.

### 4.31 Simulated holdings were reconciled against the account *(2026-08-17)*

The investing book's `2331.HK` and `2097.HK` were filled by the local simulator
back when Hong Kong was unreachable. The moment it became reachable,
`reconcile_claims` compared 734 simulated shares against an account holding
none, called it drift, and **halted live trading**.

Simulated-ness is a fact about how a position was **filled**, not about what its
market is today. It is now recorded as one and persisted (`sim_keys`). A book can
legitimately hold both kinds at once and always could — `PRX.AS` has no
Longbridge symbol and never will, so the investing book simulates it forever.

### 4.32 §4.31 fixed the check; the order path had the same gap *(2026-08-17)*

`reconcile_claims` learned to exclude `sim_keys` in §4.31, which stopped the
false halt. It did not touch `BookBroker.submit()`, which still decided where
to route an order purely from "is this symbol reachable **today**" — the same
question, asked in the one place where getting it wrong is not a false alarm
but a real order. The investing book's `2331.HK` (734.67 sh) and `2097.HK`
(52.07 sh) are still live long theses, both still `sim_keys`, both now on a
reachable symbol: the day either thesis is dropped or trips its 10% stop,
`daily_manage()`'s automatic exit would have submitted a SELL for shares
Longbridge was never given — rejected at best, an unaccounted-for short at
worst, and either way a position that could never actually close, since the
same exit condition re-fires every day it stays open.

Found on review, not by the failure happening — both theses are currently
in-the-money on their stop, so this had not fired yet. `submit()` now checks
`sim_keys` itself: a SELL closing a position filled locally closes locally,
whatever the venue says about the symbol today. A BUY opening a genuinely new
claim is unaffected. See `docs/design/SHARED_ACCOUNT.md` → "The exit-routing
gap" for the fix and its two regression tests. No position was touched — Mixue
and Li Ning are held exactly as they were before this entry.

### 4.33 A saturated node has no room left to say "still getting worse" *(2026-08-18)*

Not a defect in running code — found while digesting a routine news item (a
30-year Treasury yield hitting a 19-year high) and asking why the read felt
undersized. `macro_linkage` (`signals/macro_linkage.py`) reads a node's
*current* activation level, which `field.py` hard-clamps to `[-1, 1]`.
`bond_stress` and `us_gov_debt` were both sitting at 0.97–0.99 — against the
ceiling. A node that crossed that level yesterday and one that has sat there
for weeks are numerically identical to a level-only reader: both just read
"near max," and a maxed node has no headroom left to register the story
getting worse. Only *duration* can still say anything once level has
saturated, and nothing measured duration.

Added `regime_persistence` (`signals/regime_persistence.py`,
`brain/persistence.py`) as a new candidate feature, following the exact
dormant-candidate lifecycle `trend_zscore` established (`docs/design/FORMULA.md`
§7): computed every cycle, reaches the feature vector, excluded from
`consensus`, ships at `θ=0` — inert to every live decision until it earns a
weight through the same RLS/walk-forward gauntlet everything else does. It
answers the duration question from the real per-node activation history
`BrainStore.node_trend` already recorded every cycle (previously used only for
dashboard charts): consecutive same-sign days above a 0.85 threshold.

**Checked against live data immediately after deploying it, and it missed its
own motivating case.** TLT's only direct graph predecessor turned out to be
`us_10y_yield` (edge weight 0.9), whose own streak was just 2 days — the
actual multi-week story sat a second hop further back, through an edge the
first version didn't traverse. Widened the same day: a new
`KnowledgeGraph.predecessors()` (the inverse of the existing `_adjacency()`)
lets `driver_persistence_days()` walk up to 2 hops upstream, non-asset nodes
only, compounding edge weights and discounting every hop beyond the first by
the SAME per-hop decay constant (`settings.brain.decay`) `graph.propagate()`
already uses for the real ripple — so a 2-hop borrow is honestly discounted,
never treated as equally certain as a direct edge. Re-checked against live
data again after the widen: the arithmetic traced out correctly (verified
node-by-node against `brain.json` and the real graph edges), but it also
corrected an assumption made along the way — `bond_stress`'s own streak had
in fact reset to 2 days by the time of the second check, not the multi-week
run it looked like from casually reading its level. The feature is now doing
exactly what it was built to do: giving an honest number instead of a
plausible-sounding one.

Explicitly declined a request in the same session to hand-set a nonzero
weight for this feature "to save time." `brain/adviser_gate.py`'s own
docstring documents the reason: a prior hand-set `BLEND_WEIGHT` was killed
after backtesting showed its P&L-optimal value was 0.00. The two legitimate
paths (online RLS from closed trades; `backtest.main --optimize --save` on
demand) remain the only way this — or anything else in the formula — earns
influence over real capital. See `docs/design/FORMULA.md` §8 for the full
mechanism writeup and `tests/test_regime_persistence.py` for the 20 tests
covering both the base feature and the 2-hop widen.

### 4.34 The digester's own node reference had drifted 12 nodes behind the graph it describes *(2026-08-18)*

Found while writing up §4.33 above, not by a tagging failure being observed:
`docs/data-pipeline/SONNET_DIGEST_BRIEF.md` — the injected system prompt for
every digestion cycle — last had its node table updated at v1.5 (2026-08-02).
The graph kept growing underneath it. A direct diff (every live non-asset
node id against the brief's text) found **12 taggable nodes with zero
instructions**: six "monetary plumbing" factors (`cbdc_rollout`,
`em_dollarization`, `fx_intervention`, `monetary_fragmentation`,
`payment_rail_access`, `stablecoin_supply` — seeded 2026-08-12, v26, ten days
before the brief was last touched) and six regional themes
(`china_healthcare`, `china_property_stocks`, `macau_gaming`,
`sg_consumer_leisure`, `sg_industrials`, `sg_property`). The digester cannot
tag what it has never been told exists — a story squarely about, say, a
digital-ruble mandate or a Macau GGR print had no correct node to land on,
silently, with no error anywhere to notice.

Fixed by transcription, not authorship: each new row's definition is copied
from that node's own `equilibrium` field in `knowledge_graph.json` — the
same text a human already wrote when the node was seeded — not freshly
invented judgment calls about sign or scope. Header counts corrected
throughout (128→140 taggable nodes, 683→1,094 edges, 179→443 assets); see
the brief's own v1.6 changelog entry for the full list.

**Not yet done**: the brief's own rule (line 7–8) requires its 50-headline
golden-set audit (§15) to be re-run whenever this document changes, before
any output from it is fully trusted. That has not happened for v1.6. Low risk
individually (transcribed text, not new judgment), but the rule is unconditional
and applies regardless of how safe a given change looks.

### 4.35 A late fill halted all four books for 40 minutes after it had already resolved *(2026-08-19)*

Reported by the user pasting two Telegram alerts. `_reconcile_shared()`
caught a USO buy order mid-settlement — filled at the venue, not yet
reflected in the book's local ledger — and latched `_shared_drift`, which
halts every book (stocks *and* crypto, since the check runs before any book
acts) until an operator clears it by restarting. The very next cycle's
`resolve_pending()` picked up the fill six minutes later and the position
was correct from then on, but the latch is never re-evaluated once set, so
the engine kept refusing to trade for another ~40 minutes after the
disagreement it detected no longer existed. `Runner._reconcile()` already
re-baselines out exactly this class of late fill; `_reconcile_shared()` has
no equivalent, by design — reasonable for a genuine cross-book conflict,
wrong for a same-session pending-order race.

Verified directly against the live Longbridge account (not just the book's
own files) before doing anything, confirmed nothing was actually wrong, then
restarted `ai-investing.service` — the documented operator remedy — and
confirmed the fresh process resumed cleanly. No code changed. Full
timeline, the file-staleness artefact that made the halt look unresolved
longer than it was, and the still-open design gap:
`docs/design/SHARED_ACCOUNT.md` → "The USO late-fill halt (2026-08-19)".

### 4.36 Equity read -$4,265 on a book that was flat: the paper-broker valuation formula doesn't hold under real margin *(2026-08-20)*

Reported by the user: the crypto event sleeve (`crypto_event_sleeve.py`), live
on Binance Futures testnet since the day before, showed equity of -$4,265.44 in
the Telegram `/assets` line, next to cash of $340 and two open shorts whose own
per-position `pnl` fields were both *positive* — an internal contradiction that
was the actual tell, not the headline number itself.

Root cause: `_stamp_marks()`/`_equity()` (duplicated in `crypto_book.py` and
`crypto_event_sleeve.py`, canonical form in `models.py`'s `Portfolio.equity()`)
compute equity as `cash + sum(qty * price)`. That formula assumes opening a
short CREDITS cash with sale proceeds — true for `PaperBroker` and a real spot
short-sell, false for a margined futures short on `BinanceFuturesBroker`, which
LOCKS margin OUT of free cash instead. `get_cash()` returns only the free
balance, so the reconstruction was double-subtracting the position's notional:
once because free cash had already dropped by the margin locked to open it,
again via `qty * price` in the formula itself.

Verified directly against the live testnet account (not just the state file)
before touching code: real `totalMarginBalance` was $5,014.87 (+$16.85
unrealized) at the exact moment the state file read -$4,265.44 for the same
account — an ~$9,280 gap on a book that was, in fact, roughly flat.

Fixed in three passes, each verified against the live account after its own
restart, not just the diff:
1. `f00e477` — added `BrokerAdapter.get_equity()` (default `None`) and a
   `BinanceFuturesBroker` override reading Binance's own `totalMarginBalance`;
   both crypto sleeves use it when available instead of the `cash + qty*price`
   reconstruction.
2. `cadba0d` — fixing (1) surfaced a second symptom: `/assets`'
   "cash + invested = equity" line stopped reconciling, because `cash` was
   still `get_cash()`'s free-only figure and "invested" was still `qty*price`
   notional. `BinanceFuturesBroker.snapshot()` (display/state-file only, never
   fed back via `from_state()`) now reports wallet balance instead of
   free-only; `chat.py` derives "invested" as `equity - cash` instead of
   recomputing it, so the identity holds by construction for every book, not
   only paper ones.
3. `562e620` — (2)'s own fix had a bug: ccxt maps
   `balance['USDT']['total']` to Binance's `totalMarginBalance` (already
   equity-inclusive) for this account type, not free+used, so cash and equity
   briefly collapsed to the same number and "invested" read $0 instead of the
   real ~$15 unrealized P&L. Switched to reading `info.totalWalletBalance`
   explicitly, verified different from `totalMarginBalance` on the live
   account (4998.02 vs 5004.31 at the time of the fix).

Separately, not a code defect: `.env`'s `CRYPTO_START_CASH` /
`CRYPTO_EVENT_START_CASH` were still `10000` — a leftover paper-trading seed
from before both sleeves went live on 2026-08-20 funded with a real $4,999.89.
That made the Telegram delta report each crypto book as "down ~$5,000" on top
of the equity bug, purely from comparing today's real balance to a stale paper
number, and inflated the reported total-portfolio "$50,000 start" by the same
~$10,000. Corrected in the ProDesk's `.env` to `4999.89` (config only, does
not travel with `git pull`, no commit).

`pytest tests` (from `engine/`) run before and after each commit: 550 passed,
the same 8 pre-existing failures (`test_alert_storm.py`,
`test_bullshit_layer.py`) both before and after — confirmed identical on
unmodified `main` via `git stash`, so none of this caused or masked them.

**Follow-up review, same day.** The three fixes above were re-read against the
rest of the codebase before this entry was considered closed. All three hold,
but the sweep found the fix had been applied only where the bug had been
*observed*, and three more consequences of the same root cause were still live:

1. **The main trading book was never fixed at all** — only the two sleeves
   were. It routes crypto through the same `BinanceFuturesBroker`
   (`RoutingBroker`, live since `8a9bc63`) but values itself through
   `Portfolio.equity(prices)`, i.e. the exact `cash + qty * price`
   reconstruction §4.36 is about, and `RoutingBroker` never overrode
   `get_equity()`. It is *numerically* correct today only by coincidence: at
   `CRYPTO_FUTURES_LEVERAGE=1` the margin locked equals the notional added
   back, and `RISK_ALLOW_SHORT=false` keeps the leg long-only. Flip either env
   var — neither raises anything on its own — and the main book's equity is
   wrong in the §4.36 direction (a short double-subtracts its notional; 2x
   adds back half a notional that was never deducted), and that is the number
   the circuit breaker halts on (§4.7). `RoutingBroker` cannot simply call
   `get_equity()`: it needs one cash figure spanning two venues, and
   `get_equity()` returns a finished number with nowhere to blend in a
   marked-to-market stock leg. So it now **refuses to construct** outside the
   1x-long-only window that makes its formula true, with the reason in the
   exception. Structural limitation logged in §4A.
2. **`get_equity()` returned `0.0` on a malformed balance response** — a
   phantom zero written straight into a state file as this book's equity, the
   §4.7 signature and the same absent-vs-zero sentinel confusion §4A still
   lists as open for `prices[key] = 0.0`. It raises now; both call sites sit
   inside the runner's per-book `try/except`, so an unreadable balance skips
   that book's mark and leaves the last *good* equity on disk.
3. **`/assets` still hid a long-only margined book's exposure.** Deriving
   "invested" as `equity - cash` (`cadba0d`) makes that figure just unrealized
   P&L on a margined book, because `cash` is now wallet balance with the
   locked margin still inside it. The "at risk" clause that rescues the
   reading was gated on `shorts > 0`, so the ₿ crypto book — live, long-only —
   would have rendered a $4.6k open position as "cash $4,998 + $17 invested",
   i.e. as flat. Gated on gross differing from net now, the same test the
   portfolio footer already applied.

Also: none of §4.36 had a test. `engine/tests/test_margined_equity.py` now pins
all of it — the venue-equity read, wallet-vs-margin cash, the raise, the
long-only at-risk clause, and the routing refusal — against a stub balance blob
shaped like the real response, no network. `pytest tests`: 556 passed, the same
8 pre-existing failures.

### 4.37 The scorecard graded one standing view 65 times, and two reviews drew opposite conclusions from it *(2026-08-21)*

- **What.** `advice_log` is written EVERY CYCLE — ~126 rows/day at a ~10-minute
  cadence — and `scorecard.score_due()` grades every one of them. So a single
  standing view ("long NVDA today") was frozen, graded and counted **126 separate
  times**, against the same forward return, out of the same 5-day window. On the
  live database: **42,882 graded rows, 634 distinct (symbol, issue-day)
  observations — 67.6×.**
- **How found.** Not by a check. By re-deriving the scorecard's own headline
  table from scratch during a structural review and getting a different answer.
- **Scale, and it is the whole evidence base.** Every `n` in
  `SCORECARD_REVIEW_2026-08-12`, `SCORECARD_REVIEW_2026-08-15` and
  `data/adviser_gate.json` was inflated by this factor; every t-statistic by
  **√65 ≈ 8×**. The 08-12 review concluded *"the avoid/short side is inverted"*;
  the 08-15 review reversed that on the "full sample". Deduplicated, the
  reversal itself reverses — conviction `short_or_avoid` hits 0.383 against
  non-conviction's 0.493, which is the ORIGINAL finding, intact. It never went
  away; it was buried under 65× replication of four days of a rising tape.
- **The near-miss.** `adviser_gate.THRESH["min_n"] = 500` was the
  anti-overfitting guard on an AUTOMATED control that nudges live position
  sizing. At 65× it was a bar of **7.7 independent observations**, and
  `min_days: 30` — the only bar doing real work — was ~15 days from clearing.
- **The part that should have caught it.** This project had already solved the
  identical problem ONCE, on the other side of the same comparison:
  `adviser_gate._formula_short_stats` collapses 56,155 raw decision rows to 359
  symbol-days and documents the rule it chose. The adviser's own side never got
  the same treatment. §4.23 and §4.36 have the same shape — a fix applied where
  the bug was observed and nowhere else.
- **Fix.** `advice_outcomes` gains `issue_date` + `is_primary`. Every row is
  still written and auditable; exactly one per (day, symbol) — the FIRST call of
  that day — may be counted. Migration labels the existing rows in place, never
  deletes, and runs in 0.1s on the live 194MB database. Both sides of the gate
  now count observations; `min_n` 500 → 80 in the new unit.
- **Second-order.** `update_reliability` stepped once per outcome ROW. At 65
  rows/day and α=0.12 it retained `0.88^65 = 0.00026` of yesterday — a same-day
  step function, not an EMA. **56 of 122 live symbols sat pinned at a bound**,
  including `NVDA: r=0.506`, one step off the floor, halving the adviser's
  conviction on a name the sleeve trades profitably. Now one step per
  (symbol, day); `reliability.json` re-seeded to neutral, old file retired.
- **Lesson.** A ledger that never deletes is an audit trail, not a sample. The
  unit of account has to be declared somewhere, or every consumer invents its
  own — and two of them will disagree without either noticing.

### 4.38 A node called `none` was the 17th most connected node in the graph *(2026-08-21)*

- **What.** Asked for a counterparty the extractor sometimes has none to give
  and answers "none". `propose_node` created it. 23 LLM edges accumulated:
  `skhynix -owns-> none 0.24`, `tsmc 0.50`, `avgo 0.35`,
  `amazon_alphabet_microsoft` (itself a merged non-entity) `0.50`, `xrp 0.05`.
- **Why it mattered.** `owns` edges flow **rev** (`EDGE_FLOW`), so any shock
  landing on `none` flowed back out into TSMC at half strength. A junk collector
  wired as a transmission hub between semiconductors, megacap tech and XRP.
- **Scale.** A shape-based filter — not a blocklist, which catches `none` and
  misses `unnamed_acquirer` — found **14** such nodes carrying 37 edges:
  `6_unnamed_financial_institutions`, `unnamed_international_bank_syndicate`,
  `undisclosed_client`, `private_investors`, `multiple_banks`, two Bezos
  consortia, and the rest.
- **Fix.** `propose_node` refuses a non-answer by shape;
  `prune_non_entities()` removes those already admitted and tombstones every
  edge so the next digest cannot re-add it. Propagation is unchanged
  (`ai_capex_cycle` still reaches nvda 0.7581, tsmc 0.5858).
- **And the cause behind it.** Self-wiring was running at **88.5/week — 131 in
  7 days** — against `DIGESTION_SPEC` §A10's stated assumption of ≤1/week, with
  `reviewed & kept: 0`. The review queue built in §4.22 as the control surface
  for exactly this had never been used once, on any edge, ever. So there was no
  control surface. Review is a control on QUALITY and needs a human; a **budget**
  is a control on VOLUME and does not. 6/day, and budget-refused edges are
  deferred rather than tombstoned — nothing was judged wrong, only postponed.
- **Lesson.** "A human will review it" is a control only if a human ever does.
  Check the queue's throughput, not its existence.

### 4.39 The graph resolves 202 objects and holds 462 *(2026-08-21)*

- **What.** Probing the live graph with each origin node in turn and grouping
  assets by their response vector: **202 distinct signatures across 462 assets
  (43.7%)**. 198 assets are inert to every macro shock. 104 are an EXACT
  duplicate of a peer — `dbs/ocbc/uob`, `amat/lrcx/klac`, `crwd/panw/cibr`,
  `nio/xpeng/liauto/gotion/sanhua`, and 13 of 17 crypto alts.
- **Why.** Each hangs off the same single `member_of` edge into the same theme,
  so the path-sum BRAIN.md §4d describes has exactly one term and the "cluster"
  reduces to a sector lookup. The printed causal chain is true of the THEME and
  carries no per-name information.
- **What it cost.** `crwd` and `panw` have identical signatures. Over the same
  window PANW long hit 1.00 (+7.66%) and CRWD short_or_avoid hit 0.00 (+7.16%).
  Same graph read, opposite calls, opposite outcomes — the differentiation was
  a coin flip.
- **Fix (partial, and honest about it).** Field conviction scaled by
  `1/√(group size)` — the standard correlated-positions adjustment, same
  reasoning as the fragility dial's √HHI. A view held identically across N names
  is one view, not N. This does not make the graph smarter; it stops the
  adviser claiming a precision it does not have. **The real fix is
  differentiating wiring, and that is curation work, still open.**
- **What was deliberately NOT done.** FET/BCH/HYPE/ATOM were not added to
  `CONFIRMED_MISCALIBRATED`. Raw, `FET/USD` long is n=526 at hit 0.00 and looks
  damning; deduplicated it is **5 distinct days** (BCH 3, HYPE 2, ATOM 13 at
  p≫0.05). Acting on those would have repeated §4.37 the same day it was fixed.
  `UNI/USD` stays — 12 days, hit 0.17, binomial p=0.004.

### 4.40 The test suite is green two different ways, and only one of them is checked *(2026-08-21)*

- **What.** All 57 test files pass under the project's own runner
  (`python3 tests/test_x.py`, each file a fresh process via its `__main__`
  block). Under `pytest engine/tests/` in one process, **8 fail** — on a clean
  checkout, unrelated to any recent change.
- **Cause.** Cross-file state: several tests share a data directory and a
  module-level `tmp`, and `test_alert_storm.py` asserts against `sys.argv`,
  which under pytest contains pytest's own arguments.
- **Why it was filed before it was fixed.** The per-file runner is the project's
  actual convention and the one CI and the ProDesk use, so nothing was silently
  broken. But "all suites green" was stated in two places in this document and
  was only true of one runner — and the failing runner is the one a newcomer
  reaches for first.
- **FIXED, same day.** Two distinct causes, neither cosmetic:
  1. `watchdog.main()` called `parse_args()` with no argument, so it read
     `sys.argv` — which under pytest holds pytest's own flags, so argparse
     exited 2 and both tests driving it failed for a reason unrelated to the
     code under test. Fixed across **all 17 scripts** carrying the pattern
     (`main(argv=None)`), not just the one that happened to have a test,
     because it is the same defect as the hardcoded `data/` paths one layer up:
     *a function that reads global state its caller cannot set is neither
     testable nor configurable, and those are the same defect.* Production
     still calls `main()` and still reads `sys.argv`.
  2. Six tests in `test_bullshit_layer.py` failed
     `sqlite3.OperationalError: database is locked`. `_fresh_settings()`
     DELETED files inside one shared temp directory. Under the project runner
     that is harmless — each file is a fresh process, so any sqlite handle
     production code leaves open dies with it. Under pytest every file shares
     one process, those handles accumulate against the same path, and deleting
     the file underneath them locks it. Per-test directories fixed it. Note
     what this was NOT: the tests close all six connections they open. The leak
     is upstream, in production code other tests left open on the same path —
     which is exactly why a shared directory was the wrong shape.
- **Guarded so it cannot quietly return.** An AST check refuses any new script
  that parses `sys.argv` behind its caller, mutation-tested by putting the
  pattern back.
- **Verified.** 62 files green under the project runner; **645 passed** under
  `pytest engine/tests/`, including three different random orderings, which is
  the stricter test.
- **And then it got worse before it got better — see §4.46.** Deploying this fix
  is what exposed a larger one: the same commit was green here and **17 red on
  the ProDesk**.

### 4.41 The crypto book could not afford its own mandate *(2026-08-21)*

- **What.** Both trade gates used a hardcoded $500 floor — `gap > max(500.0,
  0.02*eq)` for the HODL core, `if notional < 500` for the tactical sleeve —
  tuned on a $10,000 book, where $500 is 5%. On 2026-08-20 the book moved to a
  Binance Futures testnet account holding **$5,000**, and the core targets
  `HODL_FRAC/3` = 6.67% per major:

```
per-major target   0.20 x 4,999.89 / 3  =  $333.33
minimum trade      max(500, 2% of eq)   =  $500.00
333.33 > 500.00                         =  False
```

- **Effect.** The book could not buy the thing it is mandated to hold. It sat
  **100% cash for a day**, placed zero orders, and said nothing — a gate that
  never opens logs nothing. Break-even is **$7,500** of equity; below that the
  mandate is unreachable by construction.
- **How found.** Not by a check. By asking "why do four books place zero buys"
  and working each one back to its cause.
- **Family.** §4.14 — logic calibrated to a book size, surviving a change of
  book size. The declared-basis fix from that entry made the equity STEP
  legible; it did nothing about thresholds calibrated to the old size, which is
  the other half of the same hazard.
- **Fix.** `min_trade_usd(equity, target)`. Keeps both things a floor is
  legitimately for — venue/fee cost (absolute) and churn (relative) — and adds
  the guard that makes deadlock structurally impossible: **a rebalance
  threshold may never exceed a quarter of the target it is rebalancing
  toward.** `0.05 x equity` reproduces the old $500 exactly at the $10,000 book
  the constants were set on.
- **Two more, found alongside.** A skipped or unfilled buy left no trace at all
  (`if o.filled_qty:` with no `else`), which is why a frozen book looked
  identical to a quiet one — now logged once per symbol per day. And `held`
  still claimed BTC/ETH/SOL the venue does not have, carried across the broker
  migration, so every diagnostic lied about the book while it sat frozen; now
  reconciled against the venue, and never when the venue is unreadable (§4.7).
- **Verified live.** On deploy the book logged `held_reconciled` (dropping the
  three phantoms) and immediately bought BTC/ETH/SOL at $333.33 each — its full
  20% core, after a day frozen.
- **Lesson.** A book must always be able to reach its own mandate. Any
  threshold expressed as an absolute against a book whose size can change is a
  latent deadlock, and it will present as silence.

### 4.42 40% of the strategist's capacity was spent on positions that cannot open *(2026-08-21)*

- **What.** `strategist._PROMPT` stated *"Shorting overvalued/bubble names is a
  valid thesis when valuations support it"* — while `SHARED_STOCK_ACCOUNT`
  refuses every stock short at the venue (`brokers/shared.SHORTS_REFUSED`).
- **Scale.** Of 5 live theses (`MAX_THESES = 5`), **two were shorts**:
  `short-tech-bubble` → TSLA and `short-energy-stress` → JKS. Both had been
  re-submitted and rejected **every cycle since 2026-08-19**, and the investing
  book sat 57% cash. Two of five slots produced a daily rejection and never a
  position.
- **Fix.** The rule is now computed from what execution accepts
  (`stock_shorts_available`), and — because a prompt instruction is not a
  control — ingestion downgrades a stock `short` to `avoid` when shorts cannot
  execute. An `avoid` is not a watered-down short: it is the claim this system
  can act on, the claim the scorecard already grades correctly against a
  benchmark, and per `research/SHORT_STRATEGY.md` (shorts have failed six
  independent tests here) the better claim anyway. Crypto is untouched — the
  event sleeve genuinely can short perpetual futures.
- **Lesson.** An idea the system cannot express is not a cautious idea, it is a
  wasted slot. Constraints that live in the execution layer have to reach the
  layer that generates ideas, or capacity leaks silently.

### 4.43 I read two books as frozen that were trading normally *(2026-08-21)*

Recorded because the measurement error was mine, in this session, while
investigating §4.41 — and because the instrument had inherited it.

- **What.** The trading book was reported as "0 buys, 0 positions". It had **24
  filled buys and ~$4,800 across ten names.** Two wrong sources:
  `stock_journal.jsonl` carries ONE DAILY EQUITY MARK by design
  (`runner._append_stock_journal`) and has never carried fills; and
  `state.json.broker.positions` is empty for the routed book because its
  holdings live in the `BookLedger` (`live_book.json`) — the shared Longbridge
  account holds the shares, the ledger records this book's claim on them.
- **Also wrong in the same pass:** `qty < 1 share` rejects were presented as a
  live leak. All 21 are on or before 2026-08-12, and commit `baa6de0` fixed the
  sub-share loop at 22:47 that same day. Zero since.
- **And a third, caught before shipping:** the first version of the corrected
  audit reported the crypto book as `idle 100%` minutes after it bought its
  entire mandate — on a 1x futures account a position is collateralised, not
  paid for, so wallet cash stays whole. §4.36's accounting trap in a new hat.
- **Fix.** `brain_audit.py`'s `books` section reads the authoritative source per
  book, takes order flow from `journal.db.orders`, and reports `idle_pct` as
  null for margined books.
- **And a fourth, an hour later, on the same investigation.** The event sleeve
  logged `sell capped at its own claim of 0 share(s)` for EWY/NVDA/TSM and 29
  `exit_unfilled` lines per symbol, which read as a broken exit path on the one
  book with a demonstrated edge. It was not. The venue genuinely held all three
  positions (TSM 8, NVDA 18, EWY 20), three clock exits were resting there
  `NotReported`, and the cap is the DOUBLE-SELL GUARD working exactly as
  designed — the shares are promised to an order that has not been answered, and
  selling them twice would take the account short or through another book's
  position. The exits were submitted 00:07 UTC against a US session that opens
  at 13:30. Nothing was wrong; it was pre-market.

  `exit_unfilled` now carries `waiting` / `promised_qty`, so "resting at the
  venue" is distinguishable from "genuinely failing" without an investigation.
- **Lesson.** An instrument that encodes the analyst's error is worse than no
  instrument, because it launders a guess into a number. Every "this book is
  doing nothing" claim needs the source named — and per-book state files are
  not interchangeable.

  The tally for this investigation is worth keeping honest: **five suspicions,
  two real defects** (§4.41, §4.42), one working-as-configured (the crypto event
  sleeve's shorts, on a flag set against the evidence), and **two false alarms
  of mine** — both resolved by going to the authoritative source rather than
  reasoning from a state file. The two real ones were found the same way.

### 4.44 Three new tests passed with the bug put back *(2026-08-21)*

- **What.** After closing §4.7's root cause, §4.35 and §4.41–4.42, I
  mutation-tested the new suites: re-introduce each bug, confirm the tests go
  red. **Three of eight did not.**
- **The three, and they are one pattern — testing the helper, not the wiring:**
  - `test_a_total_feed_outage_does_not_collapse_equity` asserted the OUTCOME,
    which `mark_price()` already guarantees at every consumer. Restoring the
    `0.0` sentinel left it green. It now also asserts the REPRESENTATION —
    that a missing bar produces no key — which is the thing the fix changed.
  - `test_the_re_check_never_re_alerts` stubbed `_reconcile_shared`, so it
    verified `quiet=True` was PASSED but never that it suppressed anything.
    Forcing the real method to alert unconditionally left it green.
  - `test_stale_held_metadata_is_reconciled` called `_reconcile_held` directly,
    so deleting the call site from `cycle()` left it green.
- **And one worse:** `test_a_smaller_book_can_still_reach_its_own_mandate` set
  `broker.cash`, but `PaperBroker` keeps cash in `_cash` — so the assignment
  created a new attribute, every small-book case ran at `START_CASH`, and the
  test that exists to prove §4.41 could not see §4.41. Fixtures now assert they
  took effect (`_assert_holding`, an explicit `get_cash()` check).
- **Same shape in the new runner suite:** the first draft's positions opened at
  a $100 cost basis against synthetic prices near $250, so the first cycle took
  +149% profit and sold everything — leaving the outage tests with nothing to
  value. Green, and vacuous.
- **Lesson.** A green test is evidence only if it can go red. This project's
  register is full of checks that passed while the thing they checked was
  broken (§4.3's liveness check that matched itself, §4.6's scorecard that
  never ran, §4.16's 27 green suites); a test that cannot fail is the same
  defect in the place you would least look for it. **Mutation-test anything
  written to close a register entry.**

### 4.45 The expectation calibrator was correcting backwards *(2026-08-21)*

- **What.** `calibration_gain()` scales `expected_move` toward reality. It read
  `abs(b["ratio"])`, where `ratio` is an EMA of the SIGNED ratio of realised to
  expected. Wins and losses therefore cancelled: on the live record the signed
  EMA sat at **−0.274**, so `abs()` gave 0.27 and the gain SHRANK an expectation
  that the same data said was ~14× too small.
- **Why it hid.** One field served two consumers with opposite requirements.
  `status()`'s drift detection needs the SIGN (has the policy moved away from
  its long run?). `calibration_gain()` needs the MAGNITUDE (how far off are we?).
  Sharing one number satisfied the first and inverted the second.
- **Compounded by `RATIO_CLIP`.** At ±3.0, **15 of 19** settled claims were
  clipped — median |true ratio| 14.4, max 106. So the evidence that would have
  revealed the inversion was itself flattened before it was stored. §4A had this
  filed as "one freak outcome (USO)" and as a minor observability nit.
- **The numbers, since they are the argument:**

```
symbol      expected   realised   TRUE ratio   recorded
000660.KS    0.00107    0.11380       106.4       3.0
AMD          0.00106    0.06497        61.3       3.0
BTC/USD      0.00100   -0.05126       -51.3      -3.0
USO          0.00308   -0.10057       -32.7      -3.0
MP           0.00210    0.06679        31.8       3.0
```

- **Fix.** `ratio_true`/`ratio_clipped` journalled; `RATIO_CLIP` keeps bounding
  the score, which is what it was for. `_update` keeps a second average,
  `abs_ratio` (EMA of |true ratio|, bounded by `MAG_CLIP = 50`), and the gain
  reads that. Old buckets fall back to the signed reading rather than reverting
  to a neutral 1.0 and discarding what they had learned.
- **What it did NOT fix.** `GAIN_BOUNDS[1] = 3.0` now binds: the correction pins
  at 3× while a ~7× residual remains, still visible in `abs_ratio` and pinned by
  a test. Two saturated clamps in series became one. Raising it is a sizing
  decision on 19 observations and is left open deliberately.
- **Consequence worth chasing (§4A, sleeve row).** The event sleeve's "32:1
  risk/reward" is computed from `expected_move`. If that is ~14× too small, the
  true ratio is nearer 2:1 — the headline figure may have been measuring a
  broken expectation rather than a broken strategy.
- **SUPERSEDED IN PART, 2026-08-22 — see §4.51.** The direction fix here is
  sound and stands. The INFERENCE drawn from the 14.4 does not: measured against
  a noise floor of 15.5 with a 52.6% hit rate, that ratio is what pure
  volatility produces, so it is not evidence that `expected_move` is too small
  and not grounds for raising `gain`. Read this entry's numbers with §4.51's
  control beside them.
- **Lesson.** A number reused by two consumers will eventually be right for one
  and wrong for the other, and the wrong one fails silently because the field
  still looks populated. Same shape as §4.6's `hit` before it got a benchmark.

### 4.46 The suite was green here and 17 red on the ProDesk, under the same commit *(2026-08-21)*

- **What.** Deploying §4.40's pytest fix surfaced a bigger one. Same commit,
  same code: **640 passed** on the laptop, **17 FAILED** on the ProDesk. Exactly
  the "green here, red there" that §4.21 exists to prevent.
- **Cause.** The tests were reading the machine's live `.env`. `cb.START_CASH`
  was **4,999.89** on the box (its `.env` sets the crypto book to the testnet
  balance, §4.14) and **10,000** on the laptop, and the crypto and investor
  suites assert against it. So the suite was not testing the code — it was
  testing the machine.
- **Why it hid, and this is the interesting part.** §4.19 was supposed to have
  closed this: *"a test process no longer loads `.env` at all, detected
  automatically."* The reasoning was right — what had failed three separate
  times before was *remembering* to pin values by hand, so automating the
  detection was the correct fix. But the automation had a hole in the one runner
  nobody used:
  - `PYTEST_CURRENT_TEST` is set when a test **starts**. `config.py` is imported
    at **collection** time, before any test starts, so at the exact moment that
    matters the variable is always unset.
  - The argv fallback looks for `pytest` / `py.test` / `test_*` in
    `sys.argv[0]`. Under `python -m pytest`, `argv[0]` is the module's
    `__main__.py`, which is none of those.

  So `.env` loaded during collection and every module-level constant captured
  whatever was ambient on that machine.
- **Fix.** `if "pytest" in sys.modules: return True` — true from the moment
  pytest is imported, which is before collection, and true however it was
  invoked.
- **The guard test needed two attempts, and that is the lesson.** The first
  version called `_running_under_test()` at test **run** time, when
  `PYTEST_CURRENT_TEST` is already set — so it passed with the fix reverted and
  proved nothing. It now **simulates collection time** (env var unset, `argv[0]`
  not test-shaped) and is verified by mutation: removing the `sys.modules` check
  turns it red. It no-ops under the project's own runner, where pytest genuinely
  is not loaded and there is nothing to simulate.
- **Lesson.** An automated detector is only as good as the *moment* it runs. A
  check that fires after the value it protects has already been captured is not
  a check. This is the third defect today whose first test passed with the bug
  put back — see §4.44.

### 4.47 The calibrator was three days from halving six relationships on four observations *(2026-08-21)*

- **What.** The edge calibrator had issued zero verdicts in 26 days (§4A), and
  the natural reading was "it needs more data". Measured, the opposite was true:
  at `MIN_N = 20` it was **~3 days from its first verdicts**, with **56
  relationships about to cross the bar, 14 gradable immediately, and 6 about to
  be HALVED.**
- **Why 20 was not 20.** The samples are daily readings of a **5-day forward
  return**, so consecutive samples overlap almost entirely. Twenty of them carry
  about **four independent observations** — three weeks of one market. This is
  §4.37's pseudo-replication defect, in a second module, found only because
  §4.37 taught us to look.
- **The demotion list is the argument.** These are not marginal calls; each
  would have had its weight cut in half:

```
arm  -> semis            t = -2.97
xlf  -> us_financials    t = -2.85
tsla -> ev_supply_chain  t = -3.42
```

- **Decision (the user's, on an explained choice): protect structure, raise the
  bar for the rest.**

```
MIN_N                        20 -> 60     causal `influences` edges, ~12 independent obs
MIN_N_DEMOTE_MEMBERSHIP            120     structural `member_of` transmissions
```

- **The reasoning is asymmetric PRIORS**, and I corrected my own framing while
  implementing it. *"Definitions cannot be wrong"* is too strong: a `member_of`
  weight does not assert **that** ARM is a semiconductor company, it asserts
  **how much** of a semis move reaches ARM — which is genuinely empirical and
  genuinely testable. The real asymmetry is **where the prior comes from**. An
  `influences` edge is somebody's guess about a mechanism and is owed little
  deference. A membership's prior comes from what the thing **is**, and four
  independent observations cannot overturn structure. *ARM lagging semis for
  three weeks is a fact about three weeks.*
- **Promotion of a membership stays at the ordinary bar.** Strengthening a
  structurally grounded prior is the safe direction; only demotion needs the
  higher bar.
- **Reports now carry `n_independent` and `structural`,** so no reader has to
  re-derive what a sample is worth. That is §4.37's lesson applied at the point
  of publication rather than at the point of reading.
- **Four mutations checked; the fourth is why this entry exists.** Putting
  `MIN_N` back to 20 **broke nothing**, because every fixture supplies plenty of
  dates — so the tests would have let someone silently undo the decision. The
  decision is now asserted in the unit that matters:

```python
assert MIN_N // HORIZON >= 12          # not "20 samples" — 12 real observations
assert structural_bar >= 2 * causal    # structure needs more than a guess
```

- **Effect.** First verdicts now land in **~2 months instead of ~3 days**, on
  deliberate grounds rather than by accident. Nothing gets halved on three weeks
  of one market.
- **NOT fixed by this.** `gain` remains pinned at its **2.0 clamp**, so the
  magnitude correction is still saturated — the same saturation §4.45 found in
  the learning spine, where the direction was fixed and the ceiling left as a
  sizing decision. Two clamps, one story: the model under-predicts magnitude and
  both corrections are capped below what the evidence asks for.
- **Lesson.** "It has produced no output" and "it is not ready to produce
  output" are different diagnoses with opposite fixes, and only measurement
  tells them apart. The dangerous version of this module was not the silent one
  — it was the one three days from speaking confidently.

### 4.48 The fix for §4.40 killed the X capture channel, and its own guard blessed it *(2026-08-21)*

- **What.** §4.40 rewrote `parse_args()` -> `parse_args(argv)` across 17
  scripts. Sixteen had a `main(argv=None)` for that name to come from.
  `x_auto_capture.py` parsed its arguments at module level, inside
  `if __name__ == "__main__":`, so the rewrite left it naming something that
  does not exist:

```
NameError: name 'argv' is not defined
```

- **Cost.** The X harvest died in ~50ms on every timer firing from the deploy
  (18:50) until it was found (23:10) — **two scheduled runs, one channel dark**.
  Found by running `systemctl --user list-units` while checking something else,
  not by any test and not by the watchdog.
- **Why the guard did not catch it, which is the real defect.**
  `test_no_script_main_reads_sys_argv_behind_its_caller` checks for
  `parse_args()` **with no argument**. The broken script calls
  `parse_args(argv)` — *exactly the shape the guard was written to enforce*. It
  passed for the whole outage. **A guard that checks the shape of a fix without
  checking that the result still runs will bless a broken script, which is
  worse than having no guard: it is a green light on red.**
- **Fix.** `x_auto_capture.py` gets a real `main(argv=None)` like the other 16,
  plus two new guards, both mutation-tested against the exact bug that shipped:
  1. `test_every_parse_args_argument_is_actually_bound` — any NAME passed to
     `parse_args` must be a parameter of the function it sits in. A
     module-level call has no enclosing function and so no way to be given one.
  2. `test_every_argparse_script_still_starts` — every script that builds an
     `ArgumentParser` must survive `--help`. Shallow on purpose; it is the one
     check that would have caught this in the commit that broke it.
- **And the smoke test needed a fix of its own before it was safe.** The first
  version ran `--help` against all 32 scripts and hung on `accumulate_once.py`,
  which has no argparse and so read `--help` as *"go and do the real thing"* —
  it started fetching feeds. **A test that executes production scripts to find
  out whether they parse is a worse defect than the one it checks for.**
  Restricted to the 17 argparse scripts, which is exactly the population the
  refactor touched.
- **Lesson.** A blanket refactor across N files needs a check that the N files
  still RUN, not only that they no longer match the old pattern. Two AST guards
  and 645 passing tests did not notice a script that could not start.

### 4.49 A number that is not valid JSON survived every restart, in every state file *(2026-08-21)*

- **What.** §4A carried *"`shadow.json` held `NaN` cash"* as a small dormant row
  about one file. It was neither small nor about one file.
- **The mechanism.** `NaN` and `Infinity` are **not valid JSON**. Python's
  encoder emits them anyway and its decoder reads them back, so a non-finite
  number entering **any** state file round-trips forever:

```
>>> json.loads(json.dumps({"cash": float("nan")}))
{'cash': nan}          # not an error. not a warning. every restart, forever.
```

- **And it is invisible to every guard, because a guard is a comparison.** NaN
  compares false to everything. `if cash < 0: halt` does not fire. `max(0, cash)`
  returns NaN. The circuit breaker, the drift latch and the data guard would all
  have passed a book whose cash was NaN — they are all comparisons.
  **Permanent and silent is the worst pair a corruption can have.**
- **Scope.** `atomic.write_json` backs **28 call sites** — every book's state,
  the learning ledger, the calibration reports. The row said "shadow book".
- **Fix, in three layers, because any one of them alone would have prevented the
  incident and all three must fail to repeat it:**

| Layer | What it does |
|---|---|
| **WRITE** | `write_json(..., allow_nan=False)`. Serialisation already happened *before* the file is touched, so a refusal leaves the previous good state on disk — the property the docstring already promised, now applied to the one class of value slipping through it. |
| **READ** | `read_json` refuses the three non-finite tokens via `parse_constant`. Without this the writer's fix does nothing for the file already on disk, and the corruption outlives the fix. |
| **SOURCE** | `_shadow_fill` used `prices.get(key, 0.0)` — the identical sentinel §4A removed from the LIVE path and left here. It now drops an unpriced order. `_load_shadow` reads through `atomic.read_json` and rebuilds rather than inheriting a non-finite cash. |

- **Checked before changing anything:** all 99 live state files scanned on the
  box. The only `NaN`/`Infinity` hits are inside scraped news TEXT, not values —
  so turning the writer strict could not break a legitimate write today.
- **Four mutations verified**, one per layer.
- **This is the fourth instance today of the same meta-defect** — §4.14, §4.23,
  §4.36 and now §4A's own sentinel row: **a defect fixed where it was observed
  and nowhere else.** The 0.0 price sentinel was removed from the live path this
  morning and left standing in the shadow path eight hours later, in the same
  file.
- **Lesson.** When a row names one file, ask what WROTE it. The shadow book was
  where the symptom appeared; `json.dumps` was where the defect lived.

### 4.50 I deleted Procter & Gamble with a rule I wrote an hour earlier *(2026-08-21)*

- **Context.** §4A's curation backlog — *"wire the real companies, delete the
  vocabulary"* — had produced nothing in weeks because it was a sentence, not a
  process. Reading the 31 unwired nodes showed two distinct problems needing
  opposite fixes: a SHAPE defect (`amazon_alphabet_microsoft` — three companies
  in one node; `uk_domestic_chip_startups` — a category) and an AGE defect
  (`databricks`, `skanska` — real companies met once and never wired).
- **What I shipped, and what it cost.** The shape rule read a double underscore
  as *"two entities joined by a separator"*. Applied to the live graph it pruned
  6 nodes and 4 edges — five of them correct, and one **Procter & Gamble**, whose
  real `-> thorne` edge was tombstoned with it.
- **Cause.** `propose_node` normalised with `re.sub(r"[^a-z0-9_]", "", ...)`,
  which **deletes** `&`. The character that distinguishes a company from a pair
  was gone before any rule could look at the id:

```
Procter & Gamble                  ->  procter__gamble          ONE company
Johnson & Johnson                 ->  johnson__johnson         ONE company
Fenway Sports Group / Liverpool   ->  fenway_sports__liverpool TWO
Datacenter / HFT infrastructure   ->  datacenter__hft_infra    TWO
```

  The rule read all four as separators and was right about exactly one.
- **Fix, and where it belongs.** No downstream rule could have got this right,
  so it goes where the information still exists: `&` becomes ` and ` **before**
  punctuation is stripped. P&G normalises to `procter_and_gamble`, and a
  surviving `__` once again really does come from a separator — which makes the
  rule that reads it sound rather than lucky. The node and its edge were
  restored on the live box and the wrong tombstone removed.
- **Why the dry run missed it.** I previewed the collection against
  `orphan_nodes()` — the UNWIRED list — and P&G was **wired**. The prune reached
  further than the preview I had checked. *A dry run that samples a different
  population than the operation is not a dry run.*
- **And I had written the warning myself, two commits earlier.** The test file
  says: *"a false positive here refuses a real company permanently"* — my
  reasoning for declining a `_and_` rule. I then shipped a different rule with
  the identical failure mode.
- **A third caller of the same function, found while fixing this.**
  `is_non_entity(nid)` defaults to `"asset"`, and the seed's THEME nodes are
  categories (`uk_banks`, `sg_banks`, `china_property_stocks`) — correct for a
  theme, junk for an asset. Every type-blind caller reported three curated nodes
  as placeholders: the hygiene guard caught it, `brain_audit.py` printed them,
  and `review_edges.py` would have offered them for pruning. Now an AST guard
  refuses any caller outside `graph.py` that omits the type.
- **Lesson.** **A cleanup rule is a destructive operation and deserves the
  scrutiny of one.** Both halves of this failed the standard I would apply to a
  trade: the preview measured a different set than the action, and the rule was
  written against ids whose distinguishing information had already been thrown
  away upstream.

### 4.51 The "model under-predicts by 14x" was noise, and the decision not to act on it *(2026-08-22)*

- **The decision asked for.** Whether to raise the two saturated gain ceilings
  (§4.45, §4.47). The user delegated it. **The answer is no, and it is now
  proven rather than judged.**
- **What §4.45 concluded, and why it was wrong.** It measured median
  |realised/expected| = **14.4** over 19 settled claims and read that as
  *"`expected_move` is one to two orders of magnitude too small"*. That reading
  makes raising the gain look obviously correct. The missing piece is the
  control — what the ratio would be with **no signal at all**:

```
median |realised / expected|             14.4
median  own-5d-volatility / expected     15.5   <-- what PURE NOISE produces
directional hit rate                      0.526  (n=19 — a coin flip)
```

- **They are indistinguishable.** `expected_move` is the move **attributable to
  the event**; `realized_move` is the asset's **total** move over five days,
  which its own volatility dominates. Their ratio measures signal-to-noise, not
  calibration error.
- **Why raising the gain would have been actively harmful.** No gain can drive
  that ratio to 1.0 — only an asset that does nothing except what the event told
  it to. Reaching 1.0 at the live impact (~0.06) needs a gain above 13, at which
  point every `expected_move` claims the model predicts the asset's **entire
  five-day range**. That figure feeds position sizing, the sleeve's risk/reward
  and stop distances. It would have inflated all three on a 52.6% hit rate.
- **The honest lever is the other one.** The ratio falls when the event explains
  MORE of the move — bigger `impact`, which is a **graph-wiring** question — not
  when the gain is turned up. That points back at the 200 inert assets and 320
  unreviewed edges, which is unglamorous and correct.
- **A second defect, visible in the same table.** All **17 equity claims** carry
  `vol_daily = 0.0200` **exactly**; only BTC (0.0194) and ETH (0.0409) differ,
  because the crypto path computes its own. `brain/core.py` builds two dicts
  from one graph read — `_shock_assets` (the fresh shock the event sleeve
  trades) and `asset_impacts` (the accumulated field) — and `enrich_with_scale`
  ran on the second only. So the sleeve's `row.get("vol_daily") or 0.02` fell
  through to the literal on **every claim it has ever opened**: JPM (~1.2%
  daily) and MP (~5%) sized off one constant. Fixed by enriching both.
  **Fifth instance of one-of-two-paths-fixed** — §4.14, §4.23, §4.36, §4.49.
- **Made permanent, not just recorded.** `brain_audit.py` now reports the
  observed ratio, the noise floor, the hit rate and the conclusion **together**;
  a test refuses to let the observed ratio be published without its control.
  That guard exists because mutation testing showed blanking the noise figure
  broke nothing — the audit could have gone back to printing 14.4 alone, which
  is the reading this entry exists to kill.
- **What is NOT claimed.** That the expectation is well calibrated. n=19 with a
  coin-flip hit rate supports no claim in either direction. What is claimed is
  narrower and sufficient: **the 14x is not evidence for raising the gain**, and
  the ceilings stay until there is evidence that is about the gain.
- **Lesson.** A ratio without its null is not a measurement. §4.6 needed a
  benchmark before `hit` meant anything; §4.44 needed a control group before
  "panic rebound" did; this needed a noise floor. Three times now the same
  correction: **compared with what?**

### 4.52 The basis cue fired negative, and it was right to *(2026-08-22)*

- **The cue.** §4A carried the declared book basis as *"wired but not yet
  observed in production"*, with the cue **"the next daily mark"** and an
  explicit instruction: *if a mark lands without `basis`, treat that as a live
  defect, not a timing artefact.*
- **It landed without one.** First mark after the deploy:

```
stock_journal.jsonl   ... "event": "mark", "equity": 10001.71 ...      no basis
invest_journal.jsonl  ... "event": "mark", "basis": "BookBroker:book"  DECLARED
```

- **What made it a real gap rather than a timing artefact** was the second line.
  The investing book declared its basis on the *same cycle*, so the mixin
  demonstrably works — which meant the missing one was a path, not a delay.
- **Cause.** `BookBasisMixin` was applied to the four per-book strategies.
  `stock_journal.jsonl` is written by the **runner**, not by a book, and is a
  fifth journal nobody counted. It is also the one that matters most: the
  watchdog and `daily_status.py` read that curve. The runner already had
  `_book_basis()` and was already feeding it to `CircuitBreaker.ensure_basis` —
  it simply never went into the row.
- **Sixth instance of one-of-N-paths-fixed**, after §4.14, §4.23, §4.36, §4.49,
  §4.51. §4.14's own fix was for the runner's breaker; the mixin later covered
  the four books; between them, the runner's own *journal* was the seam.
- **Fix.** The mark now carries `basis`, plus `basis_changed` on the row where
  it moves — which is the load-bearing half: it turns a −50% step in the curve
  from something to explain into something already explained, at the exact row
  where it happened. The previous basis is seeded **from the file**, not from
  memory, for the reason the day-seeding block immediately above it already
  gives about itself: the nightly poweroff makes restarts a daily event here,
  and an in-memory value forgets. An unreadable basis degrades to `"unknown"`
  rather than raising — the record is never worth failing a cycle over.
- **Three mutations verified.**
- **Lesson, and it is about the cue rather than the code.** This is the first
  time a §4B cue has fired **negative** and been believed. The temptation was to
  read "no basis yet" as "the daily mark has not run", which was true the
  evening before and false the morning after. **A cue is only worth writing if
  its negative answer is written down too** — that row said in advance what a
  missing field would mean, so there was nothing left to argue about.

### 4.53 The table used to justify a first live order was noise, ranked *(2026-08-22)*

- **Context.** Asked to decide, as a trader would, whether to place the first
  order on an unproven market path (`O39.SI` — OCBC, 7 symbol-days, hit 0.86).
  Before deciding I checked what the sample was worth. It is worth nothing, and
  neither is the rest of the table.
- **The counting unit, again.** `reach` reported raw **symbol-days** as `n`.
  These are daily readings of a **5-day forward return**, so consecutive rows
  overlap almost entirely and the independent count is `n / HORIZON`:

```
market  raw n   hit    n_ind   p       significant
KS          9   0.889      2   0.250   False
SI          8   0.875      2   0.250   False
HK         16   0.562      3   0.500   False
US         51   0.529     10   0.623   False
```

  **Not one row is distinguishable from a coin flip.** Every entry in
  `correct_but_never_held` — including `O39.SI` — has **n_independent = 1**.
- **What this retires.** The finding that *"the brain's accuracy ranks INVERSELY
  with its ability to place the order — best in Korea and Tokyo, both
  unreachable, worst in the US, its only open market"*. That is a headline of
  `BRAIN_REVIEW_2026-08-21` §5.1, it is quoted in §4A's non-USD row, and it was
  the argument for going live on a new venue. It is **noise, ranked** — the
  markets with the highest hit rates are simply the ones with the fewest
  observations, which is what small samples do.
- **Third module with the same defect.** §4.37 fixed pseudo-replication in the
  scorecard; §4.47 fixed it in the calibrator. This section — **the one actually
  used to decide which market to trade** — was the seam between them. Seventh
  instance of one-of-N-paths-fixed, and the first that was about to move money.
- **The bar, in the unit a reader will have.** A 0.86 hit rate needs **8
  independent observations** to clear p<0.05 — which is **40 consecutive
  symbol-days**. `O39.SI` has 7.
- **Fix.** Every row now carries `n_independent`, `p_value` and a computed
  `significant` verdict, and `hit` is not published without them. Mutation
  testing caught two weak guards on the way: a hardcoded `significant: False`
  passed the first version, and removing the market-level `/ horizon` passed the
  second because the symbol-level division kept it green — the same
  one-of-N-paths shape inside the test for one-of-N-paths.
- **Lesson.** The most dangerous number in this system is a high hit rate on a
  small sample, because it is indistinguishable from skill precisely where the
  temptation to act is greatest. **Report `n_independent` beside every rate, at
  the point of publication.** Three modules, three times, same fix.

### 4.54 Making the defect rate not depend on who is looking *(2026-08-22)*

- **The problem, stated honestly.** This review found **17 defects
  (§4.37–§4.53)** in a system with 645 passing tests, and **two of them were
  introduced during the review itself** (§4.48, §4.50). The uncomfortable read
  is that the defect rate tracks how hard someone looks — which makes quality a
  function of who is on shift and how alert they are that day. That is not a
  property you want in something that trades unattended.
- **But 17 defects were not 17 insights.** Sorted by the QUESTION that surfaced
  each, they collapse:

```
Q1  "what is the unit of observation?"    §4.37 §4.47 §4.53        3
Q2  "compared with what?"                 §4.6  §4.44 §4.51        3
Q3  "where else does this pattern live?"  §4.14 §4.23 §4.36 §4.49
                                          §4.51 §4.52 §4.53        7  <-- biggest
Q4  "who else reads this field?"          §4.45                    1
Q5  "has this test ever actually failed?" §4.44 §4.48 (+8 vacuous)  2
Q6  "what does the NEGATIVE answer mean?" §4.52                    1
```

  **13 of 17 came from four questions a script can ask.** So `scripts/defect_sweep.py`
  asks them, every time, instead of relying on someone thinking to.
- **It earned its place on the first run**, by finding that **§4.51's own fix was
  one-of-N again**: `vols.get(sym, 0.02)` — the same 2% default — in three more
  sites (`adviser.py`, `calibration.py` ×2) that I had not touched.
- **And then measurement said those three are dormant, which is the other half
  of the discipline.** All **281** asset symbols have a real vol, so that
  default never fires today. §4.51's instance was live for a different reason —
  the *dict was never enriched*, not that `vols` was empty. Same literal,
  different root cause. **The sweep asks; it does not convict.** Reporting the
  three as defects would have been the §4.43 mistake (reading two healthy books
  as frozen) with a tool attached.
- **Design decisions that make it usable rather than ignorable:**
  - **Clusters only, never lone sites.** A one-off fallback is usually correct;
    the question is never *"is this line wrong"* but *"did you get all of them"*.
  - **A module that demonstrably did the thinking is not flagged.**
    `adviser_gate.py` publishes `{n, hit, days}` with no `n_independent`, which
    looks exactly like §4.53 — but it sets `min_n = 80` *"knowing the effective
    sample is ~1/5 of min_n"* and publishes `effective_n_divisor`. The first
    version flagged it. That suppression took the rate check from 21 findings
    to 9, all real.
  - **Every line of output is a QUESTION, not a verdict**, and the footer says
    so. A clean sweep means these four questions have no obvious answers left —
    not that the code is correct.
- **Lesson.** The answer to *"the well is not dry"* is not to look harder, which
  does not scale and does not survive a bad day. It is to notice that the
  finding questions repeat, and to make the repeatable ones cost nothing to ask.

### 4.55 The first order on an unproven path: DECIDED, and the answer is no *(2026-08-22)*

- **The decision, delegated.** Whether to place `O39.SI` (OCBC) — the single
  qualifying long, blocked only because the live slice is USD-only.
- **DECISION: do not place it.** Not as caution, and not on venue risk. On the
  evidence, which does not exist.
- **The number the case rested on:** 7 symbol-days, hit 0.86, +1.98% average
  excess. Read raw, `p ≈ 0.06` and nearly interesting. Read in the unit that
  exists — daily readings of a 5-day forward return —it is **1 independent
  observation**, and one observation of a coin is a coin. §4.53 has the full
  table; **no market in it is distinguishable from chance.**
- **The bar, stated so it can be met:** a 0.86 hit rate needs **8 independent
  observations** for p<0.05 — **40 consecutive symbol-days.** `O39.SI` has 7.
  That is roughly two months of the symbol staying in conviction. It is a
  reachable bar, not a refusal.
- **The two questions that were being conflated, and this is the substance of
  the decision.** *"Place the O39.SI order"* and *"validate non-USD execution"*
  are different objectives, and merging them is how a path test gets sized like
  a trade and a trade gets justified by a path test:

| | Sized by | Instrument chosen for | Success is |
|---|---|---|---|
| **A trade** | edge × conviction | the signal | P&L over many repetitions |
| **A path validation** | the minimum that proves the mechanics | lot/tick clarity and liquidity | submit → fill → stop → exit, observed |

- **So: no trade, and the path validation is still worth doing** — separately,
  deliberately minimal, on an instrument chosen for operational clarity rather
  than because a thin signal liked it, in SGT hours, watched. The venue layer is
  where this system's defects actually live (§4.23 tick snapping, §4.30 a HK
  fill booked at 7× price, the unexplained `602035` rejects), so proving it has
  real value — just not value that a 1-observation signal should be used to
  justify.
- **A Buffett check, since it was asked for.** OCBC is a real business. You
  would buy it on price-to-book, credit quality, the deposit franchise and the
  Singapore rate cycle. The model has a view on none of those; it has seven days
  of a momentum-flavoured score. *"Risk comes from not knowing what you are
  doing"* — and the honest statement here is that the model does not yet know
  anything about this name.
- **Lesson.** The most dangerous number in this system is a high hit rate on a
  small sample, because it is most persuasive exactly where the sample is
  thinnest and the temptation to act is greatest. The defence is structural, not
  personal: **`n_independent` beside every rate, at the point of publication.**

### 4.56 Has any of this made money? Counted properly: not demonstrably *(2026-08-22)*

- **The question the system exists to answer**, asked for the first time with
  the counting discipline the rest of the audit now uses.
- **The record, as anyone would quote it:** the event sleeve is **+$1,146 over
  16 fills, t=2.19, p=0.028 — significant.**
- **The record, counted as bets:** the sleeve enters and exits a **basket**.
  Those fills land on **6 distinct days**, three names at a time, and the names
  inside a basket are correlated — `NVDA, AMD, 000660.KS` is one semis bet
  wearing three tickers.

```
                    n      t       p       significant
per_fill           16   2.19   0.028   YES
per_basket          6   1.64   0.101   no
```

  **Identical money. Only the unit changed.**
- **And six is generous.** Grouped by theme the six baskets are **three bets** —
  energy (lost), solar/materials (won), semis (won across four consecutive
  baskets). At n=3 nothing can be significant, ever.
- **All four books, same verdict: edge not demonstrated.**

```
event_sleeve   +$1,146   per_fill sig=YES   per_basket sig=no
crypto            +$33   per_fill sig=no    per_basket sig=no
investing         -$72   per_fill sig=no    per_basket sig=no
crypto_event     -$266   per_fill sig=YES   per_basket sig=no
```

- **`crypto_event` is the sharpest illustration, and it cuts the other way.**
  Per-fill it is *significantly **losing*** (t=-2.63, p=0.009) — on **three
  fills across two baskets**. Acting on that number would shut down a book on
  two observations. **The per-fill figure lies in both directions**, which is
  why both are printed, always.
- **Neither figure is benchmarked**, and that is the second half of the honest
  answer. The winning baskets are semis and solar during a period when those ran.
  A long book in a rising sector makes money without skill — §4.6's lesson,
  still unfixed at the book level. So "edge not demonstrated" is if anything
  generous.
- **Fourth module with the same defect**: §4.37 (scorecard), §4.47 (calibrator),
  §4.53 (reach), and now the P&L itself. Each time, **the thing being counted
  was not the thing that varies independently.**
- **What this does NOT say.** That the system loses money, or that the sleeve is
  broken. +$1,146 is real money and the direction is encouraging. It says only
  that **26 days and three thematic bets cannot distinguish this from luck**, and
  that anyone quoting the 16-fill t-statistic is quoting a number that counts
  tickers instead of decisions.
- **Lesson.** Every measurement layer in this system was inflated the same way,
  and the P&L was the last one still flattering itself. The instrument that
  reports it now refuses to publish either unit alone, because **the gap between
  them is the finding.**

## 4A. Open defects — known, NOT fixed

The register above is history. This is the live list, and it is the honest answer
to "how are you keeping track". Until 2026-08-05 the answer was *commit messages*,
and the register had drifted **13 commits** behind reality.

| Open | Detail | Risk today |
|---|---|---|
| **Self-wiring is bounded but still ungraded, and the review queue has never been used** | §4.38, 2026-08-21. The RATE is fixed: a 6/day budget replaced an unbounded stream that had reached **88.5/week — 131 in 7 days**, against §A10's stated ≤1/week. What is NOT fixed: nothing can grade an LLM edge (`calibration.py` skips non-seed edges, and none terminates on a tradable symbol so it could not score them anyway), and `review_edges.py` reports **`reviewed & kept: 0`** — the queue built in §4.22 as the control surface has never been used once, on any edge, ever. Current (re-measured 2026-08-22 via `brain_audit.py`): **320 LLM edges, 28.5% of the graph, all 320 unreviewed.** | Bounded, not resolved. At 6/day LLM wiring can still reach parity with the 802 curated edges in ~9 months, and the only thing standing between a bad inference and the live field is the 0.6 confidence cap. Deciding the proposal BAR (as opposed to the budget) is still a judgement about how much self-wiring is wanted. |
| **Non-USD live trading is off** | The FX conversion and HK symbol padding are written and unit-tested. One HK order has now filled (§5); SG, SH and SZ have never had one sent. | **Re-measured 2026-08-21 in the deduplicated unit (§4.37) — the earlier figures on this row were 65× inflated and have been replaced.** Conviction-long hit-rate by market: **KS 0.889 (n=9, +7.4%)**, **T 0.750 (n=4, +4.2%)**, **SI 0.875 (n=8, +1.9%)**, HK 0.562 (n=16), **US 0.551 (n=49, +1.2%)**. The brain's accuracy ranks INVERSELY with its ability to place the order — best in Korea and Tokyo, both unreachable; worst in the US, its only open market. `O39.SI` (7 days, hit 0.86) clears a binomial bar and has never been ordered. Re-run with `scripts/brain_audit.py --section reach`. |
| **No position has a venue stop — and that is now mostly by design, not the 2026-08-05 mystery** | Re-checked 2026-08-21: the account's resting orders are LO/MO only, **zero protective orders**, across all 13 positions at the time of that check. Most of that is deliberate — `SHARED_STOCK_ACCOUNT` skips venue-side stops because a stop firing hours later cannot be attributed to a book (see `design/SHARED_ACCOUNT.md`). The original entry was about one unexplained `place_stop` failure for AAPL on 2026-08-05; that specific mystery is now moot, because the shared-account design superseded the code path. The REAL open item is the consequence, which the old framing understated. | Every position relies on the engine's cycle stop, which only fires when a cycle runs — precisely what an overnight gap defeats. This was bounded when it was one $307 share; it now covers the trading book's 11 positions (the sleeve's three from that check have since exited — it runs flat between events, not frozen; §2). Not a bug to patch: it is the price of the shared account, and the mitigation is either per-book sub-accounts or accepting gap risk explicitly. |
| ~~The adviser predicts well; the books do not trade it~~ | **AUTOMATED 2026-08-15** (`brain/adviser_gate.py` + `scripts/adviser_gate_check.py`, daily timer `ai-investing-adviser-gate.timer`). This used to require a human to notice the §4B cue fired and manually decide whether to wire adviser conviction into position sizing. It no longer does: a daily job measures both sides itself (adviser long-side hit-rate vs. formula-engine short/avoid hit-rate, both n≥500 over 30+ days) and writes `data/adviser_gate.json`; `runner.py` reads that cached verdict every cycle and, only once it says `eligible: true`, applies a small BOUNDED nudge (`BLEND_WEIGHT=0.25`, capped at ±1.0 target weight, never an override) via `apply_adviser_gate()`. Checked against real production data on deploy day: **not yet eligible** — adviser n=1,361/hit 0.558/10 days (needs >0.60, 30+ days); formula-engine short n=359/hit 0.415/11 days (needs <0.35, n≥500, 30+ days) — so today it changes nothing, and won't until the evidence, not a person, says so. (Corrected same-day: the first version of this measurement graded formula "short" on the literal "will fall" claim instead of the "avoid"/excess-vs-benchmark rule it should use — same category error the 08-04 fix already corrected for the adviser's own `short_or_avoid` label, see row 6 in the failure register above. Caught before deploy; numbers here are post-fix.) | None today — inert by construction until its own measured thresholds clear, the same anti-overfitting posture as the walk-forward Deflated-Sharpe gate. |
| ~~`UNI/USD` long was a confirmed defect~~ | **CLOSED 2026-08-15.** n=1,096, hit-rate 6.3%, avg excess −7.1%, worsening not improving — see SCORECARD_REVIEW_2026-08-15. Root cause: no graph node, so none of the causal-chain haircuts (crowding, priced-in, integrity, froth) ever applied. `brain/adviser.py`'s `CONFIRMED_MISCALIBRATED` set now zeroes its score before ranking; deployed and verified on the ProDesk (98a58a6). **Cue to remove the override**: once UNI has a real graph node AND `calibration.py` has scored its edges at n≥60 (`MIN_N`, raised from 20 by §4.47) — see the cues table below. | — |
| ~~The investing book's drawdown was only half explained~~ | **PARTIALLY CLOSED 2026-08-15.** JKS and INTC shorts (n>250, 0.0 hit rate both) were closed on the live book — realised −$29.77 and −$17.37. PDD and PRX.AS investigated and found NOT a bug: both are ~10-day-old theses in a book with an explicit 6-month horizon and a 10% hard stop; PDD is −6.0%, PRX.AS −7.2%, neither near the stop. **Cue to revisit PRX.AS specifically**: if it crosses −8.5% (1.5pp from the 10% stop), or if `strat.theses` drops it (auto-exits on its own, see investor.py `daily_manage`). | Two of four flagged positions closed; the other two are ordinary thesis noise, not a defect. |
| ~~A fourth announce-the-state instance~~ | **CLOSED §4.17.** All 24 alert sites swept and classified; the fourth (news/context error) is fixed. | — |
| ~~Tests inherit the ambient `.env`~~ | **CLOSED §4.19.** A test process no longer loads `.env` at all, detected automatically. | — |
| ~~7 live-path loaders hardcode `data/`~~ | **CLOSED 2026-08-21 — all seven in one pass, as §4B asked.** The diagnosis in this row was slightly off: they did not ignore `settings`, they took it and used it correctly. The defect was the FALLBACK — a path built from `__file__` that walks up to the repo's real data directory, so a caller that forgot to pass `settings` silently read live production data instead of failing. That is §4.21 exactly. `data/paths.py` now derives the default from `Settings()`, which honours `STATE_PATH`, so the fallback is configurable rather than absent — several of these are legitimately called from scripts with nothing to pass. `__file__` is gone from all seven; `test_data_path_isolation.py`'s allowlist is now **empty** and the guard absolute. Two tests cover the half an AST check cannot see: that the fallback lands where the caller chose, and that explicit `settings` still wins. | — |
| ~~`prices[key] = 0.0` still means "no data"~~ | **CLOSED 2026-08-21 — removed at the source, not contained at the consumers.** The runner now builds `prices` by OMITTING a symbol with no bar (`{k: b[-1].close for k, b in bars_by_key.items() if b}`), so an absent price arrives as `None`: falsy for the `if not px: continue` decision guards, already handled by `mark_price(None, fallback)` for valuation, and — the point — **impossible to multiply by a quantity**. 0.0 * 100 shares is a plausible-looking $0; `None * 100` raises. Safe because all 44 readers of that dict use `.get()` (verified). THE TRAP THIS ALMOST SHIPPED WITH: `DataGuard.check` iterates `prices.items()`, so omitting keys would have made a blanket feed outage **silent** — the same failure as §4.7 with the opposite sign. The guard now also flags anything present in `bars_by_key` (what the cycle expected) and missing from `prices`. Seven cases in `test_price_absence.py`, including "a total outage is still LOUD". | — |
| ~~The main book's equity formula can't value a margined leg~~ | **CLOSED 2026-08-21 — fixed, not guarded.** `Portfolio.equity()` now accepts a per-venue equity override (`venue_equity`), exactly as this row said the real fix would be. The routed book values itself as `stock cash + marked stock positions + the crypto venue's OWN equity`, which is correct at ANY leverage and in EITHER direction. Proven in `test_margined_equity.py` against the two configurations the guard existed to refuse: at 2x the old formula overstates by $2,900+, on a short it understates by $11,000+ (the -$4,265 signature), and the blend is exact in both — while agreeing byte-for-byte at 1x long-only, where the old formula was already right. `exposure()` is deliberately NOT reduced by the override: margin distorts equity, not notional. The startup refusal REMAINS, narrowed to the case it is still needed for — a venue that cannot be read at construction, where the book does fall back to the reconstruction. | — |
| **The formula has never learned anything, and now it is deliberate** | §4.28 recorded `journal.db.outcomes = 0 rows` on 2026-08-17; still 0 on 08-21. θ is bit-identical to the hand-set prior, `fitted: false`, RLS `n=8` with zero movement, and `params` holds 20 identical rows all from 2026-08-04. So BOTH loops in FORMULA.md §4 — ridge walk-forward curation and online RLS — have produced no weight change in the engine's entire life. The saved feature vector is also STALE: 8 features, missing `trend_zscore` (added 08-15) and `regime_persistence` (added 08-18), because the file has not been written since before they existed. | **Deliberate as of 2026-08-21, not merely unfixed.** Re-running `--optimize --save` now would fit θ on a 26-day, single-regime sample whose measurement layer was only just corrected (§4.37) — that is how you get a confidently wrong model. The right sequence is: let clean observations accumulate, THEN re-curate and let the Deflated-Sharpe gate decide. The cost of waiting is that the engine keeps running on priors, which it has done from the start. |
| **The edge calibrator has issued 0 verdicts — now DELIBERATELY, and the bar is set** (§4.47) | 2026-08-21. It was ~3 days from its first verdicts at `MIN_N = 20`, which sounds adequate until you notice the samples are daily readings of a 5-day forward return: 20 of them carry **~4 independent observations**. 56 relationships were about to cross, 14 would have been graded at once, and 6 HALVED — including `arm->semis`, `xlf->us_financials` and `tsla->ev_supply_chain`. **Decision taken:** `MIN_N` 20 -> 60 for causal `influences` edges (~12 independent observations), and a separate `MIN_N_DEMOTE_MEMBERSHIP = 120` before a structural `member_of` transmission may be demoted. The reasoning is asymmetric priors, not "definitions cannot be wrong": an `influences` edge is someone's guess about a mechanism, while a membership's prior comes from what a thing IS — its weight is still empirical (how much of a sector move reaches the member) but four independent observations cannot overturn structure. Promotion of a membership stays at the ordinary bar; strengthening a structurally grounded prior is the safe direction. Reports now carry `n_independent` and `structural` so no reader re-derives either. | First verdicts now land in ~2 months rather than ~3 days, deliberately. **The `gain` ceiling is now a DECIDED hold, not a pending one (§4.51).** It sits at its 2.0 clamp, and it stays there: the 14x that looked like grounds for raising it is indistinguishable from the noise floor (observed 14.4 vs 15.5 for pure volatility, hit rate 0.526). No gain can close that gap, and one large enough to try would make every `expected_move` claim the asset's whole five-day range. Re-open only on evidence that is ABOUT the gain — `brain_audit.py --section learning` prints the ratio beside its control. |
| **200 assets are inert to every macro shock** | §4.39, §4.50. The placeholder nodes are gone and the curation now has a MECHANISM rather than a sentence (shape refusal + a 30-day collector for vocabulary that never became wiring), but 200 of 464 asset nodes still respond to none of the 81 origin shocks — overwhelmingly LLM-added entity nodes harvested from news copy (`boeing`, `chevron`, `blackrock`, `warner_bros`, `kenya`). They are graph vocabulary that was never wired into the causal field. | Inert nodes are harmless in propagation — they transmit nothing — but they inflate every "the graph knows about N companies" claim, and a tradable among them is scored on the formula leg alone with no causal chain. Triage is curation work: wire the real companies, delete the vocabulary. |
| **10 live orders rejected `602035`, cause unknown — and the obvious diagnosis is wrong** | On 2026-08-20 three `1024.HK` orders went out at HK$34.05, HK$34.15 and HK$34.10; the first two were rejected `602035 Wrong bid size` and the third filled. All three are legal multiples of the HK$0.05 spread `tick_size()` correctly returns for a HK$34 name, and all three were snapped correctly on the way out. **So this is NOT §4.23 recurring**, and snapping harder would fix nothing. | Unknown cause on a live order path, bounded by the orders being small and by two of three attempts eventually filling. Rather than ship a change that would look like a fix and do nothing, the rejection now carries the tick, the venue reference price and the symbol — the same instrumentation lesson §4.23 taught after eight lost orders, one level deeper. **Next occurrence will say why.** |
| ~~The suite is green under the project runner and red under pytest~~ (§4.40) | **CLOSED 2026-08-21. Both runners now green: 62 files under `python3 tests/test_x.py`, **645 passed under `pytest engine/tests/`** — and under three random orderings, which is the stricter test.** Two distinct causes, neither cosmetic. (1) `watchdog.main()` called `parse_args()` with no argument, so it read `sys.argv` — which under pytest holds pytest's own flags, exiting 2. Fixed across **all 17 scripts** that had the pattern (`main(argv=None)`), because it is the same defect as the hardcoded data paths one layer up: a function reading global state its caller cannot set is neither testable nor configurable. (2) Six tests in `test_bullshit_layer.py` hit `sqlite3.OperationalError: database is locked` — `_fresh_settings()` DELETED files in one shared directory, and under a single process the sqlite handles production code leaves open accumulate against that path. Per-test directories, the same fix as `test_runner_decisions.py`. Both guarded: an AST check refuses any new script that parses `sys.argv` behind its caller. | — |
| **θ has been reset to v1** | Done, with the old file in `data/retired/`. The `journal.db` params rows from the crash loop remain — duplicates of identical θ under rising versions. | Historical noise in the params history only. |
| ~~Main-loop coverage is one smoke test~~ | **CLOSED 2026-08-21.** `test_runner_decisions.py` drives a real `Runner` and asserts what the cycle CONCLUDES, not merely that it runs: a total feed outage does not collapse equity and places no orders (§4.7), an outage is still reported (the regression the price-key fix could have shipped), a flagged symbol is excluded from decisions but still valued (§4.5), equity is stable across cycles and reconciles with cash+holdings (§4.10/§4.36), a drift latch halts the next cycle and can clear itself (§4.35), and no position is grown past the weight cap. Plus `test_price_absence.py`, `test_shared_drift_latch.py`, `test_strategist_stance.py`. **Every one was mutation-tested** — the bug is re-introduced and the suite must go red. Three did not, first time round, and were strengthened; see §4.44. | — |
| **The sleeve's risk/reward is inverted — and the 32:1 may be a measurement artefact** | `expected_move` ≈ 0.3–0.5% against a 10% hard stop, roughly 32:1 on the model's own numbers. **New evidence 2026-08-21 (§4.45):** those numbers are the problem. Median |true ratio| of realised to expected is **14.4** across 19 settled claims, so the honest expected move is nearer 4–7% and the true ratio nearer 2:1 than 32:1. That does not make the sleeve safe — it means the headline figure was measuring a broken expectation, not a broken strategy. | Unchanged in practice until more settled claims accumulate: 19 is not enough to re-size on, and the gain ceiling (above) still caps the correction at 3×. **Revisit the 32:1 claim at the same cue as before** (first 10% stop-out, or 15 completed cycles) — but re-derive it from `ratio_true` rather than from `expected_move`. |
| **One dangling claim in the ledger** | The discarded USO claim from defect 4 can never be settled. It stays in `expectations.jsonl` as a permanently open row. | Minor; one unresolved row in the corpus. |
| ~~`RATIO_CLIP` hides severity beyond 3×~~ | **CLOSED 2026-08-21 — and it was hiding far more than severity, plus a second defect underneath.** This row said "one clipped observation (USO)". Measured: **15 of 19 settled claims were clipped (79%)**, median |true ratio| **14.4**, max **106** (`000660.KS`: expected 0.11%, realised 11.4%) — `expected_move` is systematically one to two ORDERS OF MAGNITUDE too small and every observation saying so was recorded as "3.0". Now `ratio_true` and `ratio_clipped` are journalled; `RATIO_CLIP` still bounds the SCORE, which is its legitimate job. **The defect underneath:** `calibration_gain` read `abs(EMA(signed ratio))`, so +3 and −3 cancelled — the live signed EMA sat at **−0.274**, telling the model to SHRINK the expectation 4× when the evidence demanded growing it ~14×. It was correcting backwards. `_update` now keeps two averages: signed for drift detection (`status()`, which needs the sign) and magnitude for the gain. Verified to converge rather than run away, and bounded. | **The ceiling now binds instead:** with the direction fixed, `GAIN_BOUNDS[1] = 3.0` pins and a ~7× residual error remains uncorrected — visible in `abs_ratio`, and pinned by a test so it cannot be absorbed silently. Two saturated clamps in series became one. Whether to raise the ceiling is a SIZING decision on 19 observations, deliberately not taken here. |
| ~~Crypto coverage is 6, not 10~~ | **CLOSED 2026-08-21 — it was stale arithmetic, as the row itself suspected.** Re-measured against the current 17-coin watchlist: **16 of 17 scored**, and the single `no_view` is `UNI/USD`, which is deliberate (`CONFIRMED_MISCALIBRATED`, §4A above). The 6/13 figure predated §4.26's widening and was never recounted. | — |
| **Three new dormant candidates, none influencing a live decision yet** | (1) `signals/trend_zscore.py`, added 2026-08-15 — an EMA/stdev z-score trend filter, added to the formula's feature vector at weight 0 after its own r/algotrading-inspired backtest and a real walk-forward run both failed to clear the Deflated Sharpe bar (0.001 vs 0.60 needed). See `docs/design/FORMULA.md` §7. (2) `research/crypto_signals.py`'s `positioning_crowding_z`, added 2026-08-15 — Binance long/short account-ratio crowding, covering all 17 watchlist coins (funding rate only ever covered 3). Computed and cached every cycle so it starts accumulating real days now, but gated out of brain resting levels by `CRYPTO_POSITIONING_ENABLED` (default false) — Binance retains only 30 days server-side, so there is no deep history to backtest this one against yet. (3) `signals/regime_persistence.py`, added 2026-08-18 (§4.33) — days-sustained-saturation on an asset's origin node, with a 2-hop graph look-through. Explicitly declined to hand-set its weight when asked to, same reasoning as `trend_zscore`'s own history. See `docs/design/FORMULA.md` §8. | None today — all three are inert by construction (weight 0 / flag off). Risk is only in *when* to flip them on without repeating the "trust an unvalidated backtest" mistake all three were built to avoid. |
| **`SONNET_DIGEST_BRIEF.md`'s golden-set audit — NARROWED, not closed** (§4.34) | 2026-08-21. The actual v1.6 risk was transcription: 12 node definitions copied by hand from `knowledge_graph.json`. That is now **verified clean and pinned** — a new drift check (`scripts/brief_node_audit.py`, `test_brief_node_reference.py`) compares §7 against the graph and reports **140/140 with exact agreement on every type** (68 factors, 57 themes, 9 commodities, 2 sectors, 4 actors), so §4.34's fix held. The 50-item golden set was also re-run against the LIVE tagger: SEEN 100%, UNSIGNED 4%, SIGN 65%, ORIGIN 66%, **USABLE 54%** — above its recorded 48% baseline, so no regression. **What is still NOT done:** re-scoring the Sonnet CORPUS DIGESTER itself, which is what §15 actually asks for and needs an Anthropic key the box does not have (`ANTHROPIC_API_KEY` is blank on both machines — the LLM calls run on BytePlus). | Much smaller than filed. The transcription risk is measured and now cannot silently recur; the tagger that runs every cycle is measured and has not regressed. The residue is that the digester's own 100%-on-golden claim is from before v1.6 and cannot be re-verified without a key. |
| **New-company discovery still has a manual step** (§4.24) | The `lists_on` digester path and `graph_gap_scan.py` cover the two automatable layers, but the news archives are too thin/generic right now for the gap-scan's frequency heuristic to catch China/HK-specific names on its own — CXMT was the one real hit out of ~180 candidates at loose thresholds, and Hengrui/Haitian/Sanhua/JCET were found by neither tool, only by directly searching "biggest HK/CN IPOs" and checking each result against the graph. **Recommendation: keep doing that sweep periodically by hand** (monthly, or whenever a market-moving China/HK/SG headline seems suspiciously absent from the graph) until the archives have enough volume for the gap-scan to plausibly take over — re-run `graph_gap_scan.py` first each time to check whether it's started catching real names on its own, since that's the signal the manual step is no longer needed. | Until archive volume grows, coverage gaps in fast-moving sectors (semiconductors, robotics, anything with a hot IPO pipeline) will keep recurring silently between sweeps. |
| **The 258-symbol watchlist is pushing one LLM endpoint toward its free daily cap** (§4.25) | `vgxfw` hit 40% of its 5M free daily tokens by mid-afternoon on the first day the graph-derived watchlist went live, projected to ~102% by day end. Rotation onto other endpoints is automatic and fails open, so nothing breaks — but if every endpoint in a chain crosses its free tier, calls start costing a small real amount silently. Still climbing as of §4.26's deploy: 50.4% a few hours into that day, before the +4 crypto symbols added any further load — worth actually checking whether it settles or keeps trending, not just noting it again. | Cost, not correctness. Watch `daily_status.py` for a few more days to see if usage settles as caches warm up, or keeps trending toward the cap. |
| ~~The leaked Gemini key~~ | **CLOSED 2026-08-05 — the user revoked it at Gemini.** `.env.example` deleted, docs redacted, and every tracked file now scanned. | — |
| **Git history still contains the revoked string** | `git filter-repo`/BFG could purge it, at the cost of rewriting every commit hash and breaking any clone. Unnecessary now the key is dead. | None. A revoked key is just a string. |
| ~~The declared book basis has not appeared in a live mark~~ | **FIXED 2026-08-22, one live confirmation still outstanding — see the §4B cue. The cue fired NEGATIVE and was right (§4.52).** The investing book declared `"basis": "BookBroker:book"` on the first mark after deploy, proving the mixin works; `stock_journal.jsonl` did not, because it is written by the **runner**, not by a book — a fifth journal nobody counted, and the one the watchdog and `daily_status.py` actually read. Now declared there too, with `basis_changed` on the row where it moves and the previous value seeded from the file rather than memory (the nightly poweroff makes restarts a daily event). Three mutations verified. **What is NOT yet true:** the runner's own mark has not been observed carrying it — today's was written before the fix and it writes one per day. Tested is not observed, which is the exact distinction that created this entry. | Low, and self-resolving on 2026-08-23. |
| ~~`shadow.json` held `NaN` cash~~ | **CLOSED 2026-08-21 — and the root cause was not in the shadow book.** `NaN`/`Infinity` are **not valid JSON**, but Python's encoder emits them and its decoder reads them back, so one non-finite number entering ANY state file **persisted across every restart forever** — and silently, because NaN compares false to everything, so `if cash < 0: halt` never fires. Three layers now, each mutation-tested on its own: **WRITE** — `atomic.write_json(allow_nan=False)` refuses it, and because serialisation happens before the file is touched the previous good state survives (verified, not assumed). **READ** — `atomic.read_json` refuses the three non-finite tokens, so a file written by an older build cannot re-admit what the writer now refuses to create. **SOURCE** — `_shadow_fill` used `prices.get(key, 0.0)`, the same sentinel §4A removed from the LIVE path and left here; it now drops an unpriced order. `_load_shadow` also rebuilds rather than inheriting a non-finite cash. Scanned the live box first: **no state file currently holds one**. `test_shadow_arithmetic.py`, 8 cases. | — |
| ~~`_reconcile_shared()` can latch on a fill that resolves itself~~ (§4.35) | **CLOSED 2026-08-21.** The latch is now re-tested from live data every cycle instead of being cleared only by an operator restart. A drift caused by a pending order mid-settlement clears itself once `resolve_pending()` catches up, and the engine resumes on its own — which is what cost a ~40-minute four-book outage on 2026-08-19. A REAL ownership disagreement keeps failing the re-check and keeps the engine halted, with no timeout and no retry budget, because that is the one thing this check exists to prevent. The re-check is `quiet`: it never re-journals or re-alerts, so a genuinely halted book does not become §4.20's fifteen-pages-in-ninety-minutes. Four cases pinned in `test_shared_drift_latch.py`. | The second half of §4.35 remains: while genuinely halted the book's state file stops being written, so file-based checks (`daily_status.py`, `watchdog.py`) can still report a stale claim. Much smaller now that self-resolving halts end by themselves. |

## 4B. Cues — when each open item in §4A is actually ready to act on

Added 2026-08-15, after a milestone review closed two items and left the rest
open. *"Needs more data"* by itself is not a plan — it never says how much,
or what to check, so an item can sit open indefinitely without anyone being
able to tell whether it's still waiting or just forgotten. Every row below
names a number, a date, or an event to watch for, and where to check it.
When a cue fires, that is the signal to re-open the item — not to act
automatically, since several of these are judgement calls, not bugs.

| Open item | Cue to revisit | Where to check |
|---|---|---|
| Runner's own mark not yet SEEN carrying `basis` (§4.52) | **2026-08-23's mark**, and nothing sooner: the runner writes one mark per SGT day and today's (`day: 2026-08-22`) was already written before the fix deployed. The code is tested and mutation-verified; it has not yet been OBSERVED. That is the same distinction §4.52 itself was created by, so it gets its own cue rather than an assumption. If the 08-23 mark lands without `basis`, the fix does not work and the register entry is wrong. | `tail -1 data/stock_journal.jsonl` — expect `"basis": "live:10000"` (or `paper`). |
| ~~Declared book basis not yet seen live~~ | **FIRED 2026-08-22, and the answer was NO — §4.52.** The mark landed without `basis`, which this row had said in advance would mean a live defect rather than a delay. It was: the runner's own journal was a fifth path the mixin never covered. Kept here as the first §4B cue to fire negative and be believed — **a cue is only worth writing if its negative answer is written down too.** | — |
| Edge calibrator's first verdicts (§4.47) | `MIN_N = 60` at roughly one scoreable day per edge per activation puts the first verdicts about **2 months out (~mid-October 2026)**. When they arrive, read the FIRST batch by hand before trusting the next — a bar chosen on reasoning is still a bar nobody has watched fire. Check `structural` and `n_independent` are populated on every verdict. | `data/edge_calibration.json` → `supported` / `contradicted` leaving 0; `brain_audit.py --section learning`. |
| The two saturated gain clamps (§4.45, §4.47, §4.51) | **Decided 2026-08-22: hold, and the old cue was wrong.** Waiting for 50 settled claims would not have helped — more samples of a signal-to-noise ratio give a better estimate of the NOISE, not a reason to raise the gain. The cue that would actually matter is the ratio falling **below** its noise floor while the hit rate rises, which is a graph-wiring outcome, not a sample-size one. | `data/expectations.jsonl` (count `state: settled`); `data/learning_state.json` → `abs_ratio`; `edge_calibration.json` → `gain`, `gain_saturated`. |
| ~~Digester edges 35× spec~~ | **NOW SELF-CHECKING** (2026-08-21). `scripts/cue_check.py` + `ai-investing-cue-check.timer` measure LLM edges against the CURRENT curated count daily and notify only on a state change — the cue is no longer dated against a 656 that has since moved, and no longer depends on someone remembering. It had already fired unnoticed at 354 before this was built. | `data/cue_state.json`; Telegram on any flip. |
| Non-USD live trading off | Not data-gated — this is a deliberate action, not a wait. The cue is choosing to run it: place one small real HK or SG order (e.g. `D05.SI` or `2899.HK`) during HKT/SGT market hours and verify submit → fill → stop → exit, the same proof §5.1 already did for US via `F`. | `docs/status/OPERATIONS.md` → the live-order verification steps used for the US leg; repeat for one non-USD symbol. |
| Live AAPL position, no venue stop | Fires on its own: the next time a stop-loss placement is attempted for this position, the reason is now journalled (`!! NO VENUE STOP` if it fails again). If the same failure recurs with a tick-legal price, escalate — that would rule out §4.23 a second time and point at something else. | `journal.db orders`, `reason` column, next attempt. |
| ~~Adviser predicts well; books don't trade it~~ | **No longer a "revisit" row — self-checking.** `ai-investing-adviser-gate.timer` re-measures this exact threshold daily and flips `data/adviser_gate.json`'s `eligible` flag itself; `runner.py` picks up the change on its own next cycle. Nothing for a human to watch for anymore. | `data/adviser_gate.json` (`eligible`, and the measured numbers behind it); Telegram alerts on any flip. |
| 7 live-path loaders hardcode `data/` | Next time any of the 7 named modules is touched for an unrelated reason, or `test_data_path_isolation.py`'s pinned list would need to grow to admit an 8th — fix all 7 in one pass then, rather than let the count grow. | `test_data_path_isolation.py`'s pinned list. |
| Main book can't value a margined leg | Fires on its own, loudly: the engine refuses to start the moment `CRYPTO_FUTURES_LEVERAGE` leaves 1 or `RISK_ALLOW_SHORT` becomes true while the crypto leg is Binance Futures. Do NOT relax the check to get moving — that is exactly the -$4,265 report coming back on the book the circuit breaker acts on. Teach `Portfolio.equity()` a per-venue equity override instead. | `RoutingBroker._check_equity_is_reconstructable`, and the refusal text in the service log on restart. |
| `prices[key] = 0.0` sentinel | Not data-gated — schedule as a deliberate one-PR task. **Do it before the non-USD trading gate above is lifted**: a new market multiplies the number of price consumers this sentinel can reach. | `mark_price()` call sites, `git grep "= 0.0"` in `runner.py`. |
| Main-loop coverage is one smoke test | Same trigger as the sentinel above — **before** the non-USD gate lifts or a new broker adapter (moomoo) goes live. A hot-path change with only a smoke test is exactly how §4.16 shipped a crash loop. | `test_runner_cycle.py` — add scenario coverage before either expansion. |
| Sleeve's 32:1 risk/reward | **NOW SELF-CHECKING.** Same two triggers — the first 10% stop-out on any leg, or 15 completed cycles — counted daily by `cue_check.py` instead of by hand. Status 2026-08-21: **16 clock exits, 0 stop-outs, +$1,146.21 realised**. The asymmetry is still completely untested; a good run is not evidence about the tail. | `data/cue_state.json` → `sleeve_risk_reward`; Telegram on the first stop-out. |
| `RATIO_CLIP` hides severity beyond 3× | Revisit if a **second** freak outcome (`|ratio| > 3`) occurs. One clipped observation (USO) is a design choice protecting against a single freak input; a second starts to matter for whether the calibration gain is seeing the real tail. | `expectations.jsonl`, any row with `ratio_clipped: true`. |
| Crypto coverage 6/13 is stale | This isn't a "more data" wait — it's just stale arithmetic since §4.26 widened the watchlist 13→17. Re-run the same `no_view` count against the current 17 the next time anyone checks. | `advice()`'s `no_view` list, filtered to `/` symbols. |
| `trend_zscore` dormant candidate | Re-run `python3 -m ai_investing.backtest.main --optimize --save` periodically (no timer wired for this one, see `docs/design/FORMULA.md` §7 Path B) as real crypto history accumulates past the ~1yr Gemini/ccxt window this was first tested on; flip to trusted only if a future run's Deflated Sharpe clears `settings.learning.min_dsr` (0.60). Path A (online RLS) needs no action — it graduates the weight on its own if the feature turns out predictive. | `data/formula.json` weights, `trend_zscore` entry; `docs/design/FORMULA.md` §7. |
| `positioning_crowding_z` dormant candidate | Data-gated, not judgement-gated: revisit once `research/crypto_signals.py`'s cached `positioning` series has **≥30 real accumulated days per symbol** (started 2026-08-15, so **~2026-09-14**) — enough for the z-score itself to mean something beyond noise. At that point, run the same walk-forward comparison `trend_zscore` got before flipping `CRYPTO_POSITIONING_ENABLED=true`. | `data/crypto_signals.json` → `positioning.<SYM>` day count. |
| `regime_persistence` dormant candidate | Same two paths as `trend_zscore`. Path A (online RLS) needs no action — it graduates the weight on its own once trades close and `outcomes` starts filling (0 rows as of §4.28, still the last measurement). Path B: re-run `python3 -m ai_investing.backtest.main --optimize --save` on demand for an immediate evidenced answer instead of waiting on live P&L; flip to trusted only if Deflated Sharpe clears `settings.learning.min_dsr` (0.60). | `data/formula.json` weights, `regime_persistence` entry; `docs/design/FORMULA.md` §8. |
| `SONNET_DIGEST_BRIEF.md` golden-set audit not re-run since v1.6 | Not data-gated — a deliberate action, before the next material change to the brief compounds on top of an unverified one. Run the §15 golden-set audit (50 hand-tagged examples) against v1.6, including the 12 newly-added nodes specifically. | `docs/data-pipeline/SONNET_DIGEST_BRIEF.md` §15; the brief's own v1.6 changelog entry names what changed. |
| New-company discovery's manual step | **Monthly**, next due **~2026-09-14** (one month after the §4.26 sweep), or immediately if a market-moving China/HK/SG headline seems suspiciously absent from the graph. Re-run `graph_gap_scan.py` first each time — if it starts catching real names on its own, the manual step can retire. | `scripts/graph_gap_scan.py`, then manual "biggest HK/CN IPOs" search as a cross-check. |
| LLM endpoint nearing its free daily cap | If `vgxfw` closes **3 consecutive days above 90%** of its projected daily use, that's the trigger to either trim per-cycle scoring frequency or add a second paid endpoint to the chain. | `daily_status.py` → "LLM free allowance" line, checked daily. |
| ~~`shadow.json` NaN cash~~ | **CUE DISCHARGED 2026-08-21.** The test the cue asked for exists (`test_shadow_arithmetic.py`) and the defect is fixed at the source rather than in the shadow book — so the A/B baseline can be reactivated without the precondition this row was holding it against. | — |
| CRWV avoid/short call | The `ai_circularity → crwv` edge needs **n≥60** realised-return observations (raised from 20 by §4.47 — it is a causal `influences` edge, so it takes the causal bar) following an `ai_circularity` activation before `calibration.py` can issue a verdict (`MIN_N = 20`) — currently below that. Re-run the calibrator periodically; a "contradicted" verdict there would be the trigger to demote the edge the same way TAO/FET's `crypto_majors` membership already was. | `python3 -m ai_investing.brain.calibration`, look for an `ai_circularity`→`crwv` row. |
| `UNI/USD`'s override (now zeroed in code) | Remove `CONFIRMED_MISCALIBRATED` once **both** hold: (a) UNI has a real graph node, and (b) `calibration.py` has scored its edges at n≥60 (`MIN_N`, raised from 20 by §4.47). Removing it before either is true would just re-admit the same miscalibrated formula-only score. | `brain/adviser.py`, `data/knowledge_graph.json` for a `uni`/`uniswap` node, then the calibration report. |
| PRX.AS (investing book, not a bug today) | Revisit if it crosses **−8.5%** (1.5pp from the 10% hard stop), or when `investor.py`'s `daily_manage` drops it from `strat.theses` on its own — whichever comes first. | `data/invest_state.json` position P&L; `data/invest_journal.jsonl` for an automatic exit. |

**The two regime-diversity cues that cut across several rows above** (from
SCORECARD_REVIEW_2026-08-15 §8–9), spelled out with numbers rather than left
as "needs more data":

- **A genuine down-week for US equities**, defined as a 5-trading-day
  cumulative SPY return **≤ −3%**. Still has not happened: the deepest
  5-day draw since go-live is **−1.77%** (2026-08-21). SPY drifted +0.64%
  to 08-15 and has fallen −0.77% since. This is the cue for the long/short
  conviction asymmetry in SCORECARD_REVIEW §3.
- **Per-symbol reliability weights** — now **17 distinct issuance days** and
  **634 observations** (2026-08-21; checked daily by `cue_check.py`, fires at
  20). Two things changed under this cue and both matter: the weights were
  re-seeded to neutral on 2026-08-21 because the estimator was broken (§4.37),
  so the clock on *learned* trust restarted; and "observations" now means
  (symbol, day), not rows — the earlier count was 65× this.
- **Cross-book correlation for rebalancing**, dated from the 2026-08-05
  reset: a loose read is possible from **~2026-10-05** (2 months), sizing
  capital allocation on it is safe from **~2027-04-05** (8 months).

**How to check any of this without trusting the numbers above:**

```bash
python3 scripts/brain_audit.py           # every measurement in §4.37–4.39
python3 scripts/cue_check.py             # which §4B cues have fired
python3 scripts/review_edges.py --hygiene # placeholder + unwired graph nodes
```

The first is the important one. Every figure in §2 and §4.37–4.39 came from it,
and it exists precisely so that the next review does not have to re-derive them
by hand and get a different answer — which is how §4.37 was found.

## 5. What is unverified or uncertain

**Ranked by how much I would worry.**

0. **The trading book's reach was doubled on 2026-08-17 — and the widened half
   is unproven.** It was 132 USD symbols; it is now **248**, after §4.29 found
   that the restriction rested on a stale docstring rather than on the venue.
   Hong Kong, Singapore, Shanghai and Shenzhen are now tradable, on an account
   holding SGD 1,000,000 and HKD 1,000,000 for exactly that.

   What is proven: one HK order placed, lot-sized to 100 shares, filled. What is
   not: SG, SH and SZ have never had an order sent; board lots come from a cache
   fetched once at start-up and nothing re-validates them; and the two defects
   that surfaced within minutes of the first HK fill (§4.30, §4.31) are the kind
   that only appear on contact. **Watch the first order into each new market
   individually.**

   The shadow A/B is still not a controlled comparison — the formula-only book
   trades all 275 names while the real one trades 248 — so `input_value` in
   `state.json` (currently −$105.11, framed as the cost of the user's input)
   still partly measures the venue restriction. Ten names are genuinely
   unreachable (Korea, Tokyo, Taiwan, Frankfurt, Paris, Amsterdam) and 17 crypto
   are blocked on an unfunded exchange account, so the gap can be closed but not
   to zero.

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

   **Re-verified 2026-08-17**, ahead of a real-money transition review. The
   IP-allowlist failure this section describes is exactly the kind of thing
   that silently breaks between checks (a home IP rotates, a key expires), so
   a stale "it worked once" is worth re-confirming before trusting it going
   into a bigger decision. `--check-broker` still passes both legs
   (`stocks: cash $990,894.8, positions 7` on the Longbridge paper account;
   `crypto: cash $0.0, positions 0` on the segregated Gemini production
   account, unchanged). Beyond the existing check, also confirmed: all 17
   watchlist crypto symbols resolve in Gemini's production market list with
   live lot-size/precision metadata (`load_markets()`), and live tickers
   return current prices for a spot-check (BTC/ETH/SOL) — i.e. everything the
   sizer would need to size a crypto order is reachable. **Still not
   verified**: the crypto ORDER path itself (the Ford buy/sell/stop/take-profit
   round-trip above proved this for Longbridge; nothing equivalent has ever
   been run against Gemini, sandbox or production) — the sandbox key remains a Gemini master-key
   (rejected by ccxt's signer, see above) and the account is deliberately
   unfunded, so proving a real fill needs a funding decision this review did
   not make on the user's behalf.
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
`docs/status/SCORECARD_REVIEW_2026-08-15.md` (most recent — is the brain's edge
real or beta, per-book P&L pulled apart from its benchmark, updated missed
opportunities) and its predecessor `SCORECARD_REVIEW_2026-08-12.md`.

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
