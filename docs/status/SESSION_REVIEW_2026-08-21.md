# Session review — 2026-08-21: the brain review, and the 24 commits it turned into

*Companion to [`BRAIN_REVIEW_2026-08-21.md`](BRAIN_REVIEW_2026-08-21.md), which
is the ANALYSIS. This is the WORK RECORD: what was changed, what proves it, and
what is deliberately still open.*

**Register entries opened today:** §4.37 – §4.47 in
[`STATE_OF_THE_SYSTEM.md`](STATE_OF_THE_SYSTEM.md) §4.
**The live open list is §4A there, not here.** This document is history the
moment it is written; §4A is the thing to keep current.

---

## 0. The one-paragraph version

The review began as "is the brain modelled correctly, and is there enough data
to update it". The answer to the second question turned out to gate the first:
**the measurement layer was counting one standing view 65 times**, so every
performance number the brain had ever published about itself — including the
numbers two prior reviews argued over — was computed on 44,195 rows that carry
**636 observations**. Fixing the counting unit invalidated the evidence base,
which forced re-examination of every consumer that read it, which is how a
review became 24 commits.

**Defects found and fixed: 11 (§4.37 – §4.47).** Three of them were found only
because an earlier one taught us where to look. **Four false alarms** are
recorded too, at equal length, because a review that only records its hits is
not a measurement.

```
                      START OF DAY (e327d65)   END OF DAY (4df3b2a)
§4A open rows             19                       17
test files                54                       62
tests                     one runner only          645, BOTH runners, BOTH machines
commits                   280                      304
```

**Do not read 19 → 17 as "we fixed two."** Most of the eleven were found and
closed the same day and never reached §4A at all; meanwhile the day *added*
rows, because measuring things honestly turns unknowns into known open items.
A defect register that only shrinks is a register nobody is looking at.

---

## 1. What was actually wrong — the eleven

Ordered by what they cost, not by when they were found.

### 1.1 The measurement layer counted one view 65 times — §4.37

The scorecard graded a standing view once per symbol **per day it remained
open**. On the live record that is 44,195 rows against **636 real
(symbol, day) observations — 69.5× replication**.

This was not a reporting nit. `update_reliability` stepped its EMA once per
row at α=0.12, so a symbol carried **0.88^65 = 0.00026** of yesterday. The
per-symbol reliability weight had, in effect, **no memory at all** and was
pinned at its bounds.

- **Fix.** `advice_outcomes` gained `issue_date` and `is_primary`;
  `_backfill_primary()` labelled the existing record; counting is now per
  (day, symbol) and `update_reliability` skips non-primary rows.
- **Downstream.** Every consumer had to be re-checked. `adviser_gate`'s
  `min_n` came **down** 500 → 80, because 500 *rows* was never 500
  observations, and `n_effective = n / HORIZON` now states what a sample is
  worth.
- **Proof.** `test_scorecard_counting_unit.py` (194 lines).
- **Reliability is healthy now:** 122 symbols, **0 pinned at a bound**.

### 1.2 The calibrator was three days from halving six real relationships — §4.47

The natural reading of "zero verdicts in 26 days" is *needs more data*.
Measured, the opposite: at `MIN_N = 20` it was **~3 days out**, with 56
relationships about to cross, 14 gradable at once, and **6 about to be halved**
— `arm->semis` (t = −2.97), `xlf->us_financials` (−2.85),
`tsla->ev_supply_chain` (−3.42) — on what is really **four independent
observations**, because the samples are daily readings of a 5-day forward
return.

Same pseudo-replication defect as §4.37, in a second module, found only because
§4.37 taught us to look.

- **Decision (yours, on an explained choice):** `MIN_N` 20 → **60** for causal
  edges; `MIN_N_DEMOTE_MEMBERSHIP` = **120** for structural transmissions.
- **The reasoning is asymmetric priors, and I corrected my own framing.**
  Not "definitions cannot be wrong" — a `member_of` weight is genuinely
  empirical, it says *how much* of a sector move reaches a member. The
  asymmetry is where the prior comes from: an `influences` edge is somebody's
  **guess**; a membership's prior comes from what the thing **is**.
- **What did NOT change:** `gain` is still pinned at its 2.0 clamp.

### 1.3 The expectation calibrator was correcting backwards — §4.45

`calibration_gain()` read `abs(EMA(signed ratio))`. Wins and losses cancelled,
the live signed EMA sat at **−0.274**, and the gain therefore **shrank** an
expectation the same data said was **~14× too small**.

Underneath it, `RATIO_CLIP = ±3.0` had flattened **15 of 19** settled claims —
median |true ratio| **14.4**, max **106** — so the evidence that would have
exposed the inversion was destroyed before it was stored. §4A had this filed as
*"one freak outcome (USO)"* and as an observability nit.

- **Fix.** Two averages: signed for drift detection (`status()` needs the sign),
  `abs_ratio` for magnitude (`MAG_CLIP = 50`). `ratio_true` / `ratio_clipped`
  journalled.
- **And made to take effect immediately.** `scripts/backfill_abs_ratio.py`
  seeds `abs_ratio` from the settled record by **median** — not mean, because
  one 106× observation must not set the correction, which is what `RATIO_CLIP`
  existed to prevent. Without it the fix self-corrects over about a week of
  running backwards.
- **Consequence worth knowing:** the sleeve's much-quoted **32:1** risk/reward
  rests on this broken `expected_move`. The honest figure is nearer **2:1** —
  which does not make the sleeve safe, it means that number was measuring a
  broken expectation rather than a strategy.

### 1.4 The crypto book could not afford its own mandate — §4.41

Both trade gates used a hardcoded **$500** floor, tuned when the book was
$10,000 (5%). The book moved to a $5,000 testnet basis, making $500 a **10%**
minimum trade — larger than the rebalance the gate was being asked to perform.
The book sat at **100% cash for a day**, which looked like a bear-mode design
decision and was arithmetic deadlock.

- **Fix.** `MIN_TRADE_USD = 100.0` with `min_trade_usd(equity, target)` scaling
  off the book, `CHURN_FRAC` / `REBALANCE_FRAC` replacing the constants,
  `_reconcile_held()`, and explicit logging of `hodl_below_floor`,
  `hodl_no_cash`, `buy_unfilled` — a book that declines to trade now says why.
- **Live now:** 3 positions, and an `ETH/USD` hodl buy at 11:05Z today.

### 1.5 40% of the strategist's capacity bought nothing — §4.42

Of 99 decisions, 13 cleared the confidence floor and **12 were shorts**, which
neither paper venue permits. That is not a blocked market view; it is 40% of
thesis capacity spent on positions that cannot open.

- **Fix.** `stock_shorts_available()` + a downgrade **at ingestion**: an
  unexecutable short becomes `avoid`, so the slot goes to something tradable.
  Also `apply_adviser_gate` now zeroes a negative tilt on a short rather than
  deepening it.

### 1.6 The main book could not value a margined leg — §4.36 (closed today)

Equity read **−$4,265** on a book that was flat. This had been *managed* by a
startup refusal rather than fixed.

- **Fix, not a guard.** `Portfolio.venue_equity` override: the routed book is
  `stock cash + marked stock positions + the crypto venue's OWN equity` —
  correct at any leverage, in either direction. Proven against the two
  configurations the guard existed to refuse (2× overstates by $2,900+; a short
  understates by $11,000+) and byte-identical at 1× long-only.
- **`exposure()` deliberately unchanged:** margin distorts equity, not notional.

### 1.7 A `0.0` price meant "no data" — §4A (closed today)

Removed **at the source**, not contained at 44 consumers: the runner omits a
symbol with no bar, so absence arrives as `None`. The point is not tidiness —
`0.0 * 100 shares` is a plausible-looking $0; `None * 100` **raises**.

**The trap this nearly shipped with:** `DataGuard.check` iterates
`prices.items()`, so omitting keys would have made a **total feed outage
silent** — §4.7 with the opposite sign. The guard now also flags anything
present in `bars_by_key` and missing from `prices`.

### 1.8 A node called `none` was the 17th most connected in the graph — §4.38

An LLM non-answer had become an entity and was propagating impulses. And the
self-wiring rate was **88.5 edges/week** against a spec of ≤1.

- **Fix.** `is_non_entity()` shape filter, `prune_non_entities()`,
  `orphan_nodes()`, and a **6/day proposal budget** with `budget_deferred`.
- **Bounded, not resolved** — see §4A. Nothing can grade an LLM edge, and the
  review queue built in §4.22 still reports `reviewed & kept: 0`.

### 1.9 Emotion calibration was measuring drift, not emotion — §4.44 family

No control group, so a "panic rebound" coefficient was measuring the market,
not the panic.

- **Fix.** `_welch(group, rest)`; a measured-contradicted factor returns
  **0.0** rather than a plausible number. Live: `panic_rebound` coef **0.0**
  (`measured-contradicted`, t = −0.37), `euphoria_fade` −0.193.
- Source learning likewise now grades on **excess** return against a benchmark,
  not absolute — `hit` without a benchmark was §4.6's original mistake.

### 1.10 The suite was green two ways and only one was checked — §4.40, §4.46

Two separate defects, and the second was worse.

- **§4.40:** 8 red under `pytest`. Causes: `main()` reading `sys.argv` behind
  its caller (**fixed across all 17 scripts**, not just the tested one), and a
  shared temp directory that locks sqlite when every test shares one process.
- **§4.46, found by deploying §4.40:** the same commit was **640 green here and
  17 red on the ProDesk**. The tests were reading the machine's live `.env` —
  `cb.START_CASH` was 4,999.89 on the box and 10,000 here. §4.19 was supposed
  to have automated this away, and its reasoning was right; the automation had
  a hole in the one runner nobody used. `PYTEST_CURRENT_TEST` is set when a
  test **starts**, but `config.py` is imported at **collection**, so at the
  moment that matters it is always unset.
- **Lesson.** An automated detector is only as good as the *moment* it runs.

### 1.11 The digester's node reference could drift again — §4.34 extended

§4.34 fixed the instance (12 missing nodes) and left the mechanism. The brief is
injected verbatim as the digester's system prompt and says *"Tag ONLY these
ids"*, so drift is what the digester **believes** — and the directions are not
symmetric: a missing node **cannot be tagged at all**, so every story about it
lands nowhere.

- **Fix.** `scripts/brief_node_audit.py` + `test_brief_node_reference.py` make
  the comparison a standing check. Current: **140/140, exact by type.**
- Golden set re-run live: SEEN 100%, UNSIGNED 4%, **USABLE 54%** vs a 48%
  baseline — no regression.

---

## 2. The four things I got wrong

Recorded at the same length as the fixes, because a review that only lists its
hits is not a measurement. Three of the four had the same shape: **I read a
number from the wrong place and did not check what wrote it.**

| I claimed | Actually | How it was caught |
|---|---|---|
| **81% of assets are unreachable** | **2 of 258.** I had ignored `EDGE_FLOW` reverse traversal — `member_of` and `owns` propagate backwards. | Re-measured before publishing. |
| **Two books are frozen, 0 buys, 0 positions** (§4.43) | **24 buys, 11 positions.** I read `state.json.broker.positions`, which is empty **by construction** for a routed book — its positions live in the `BookLedger`. | The book had fills in `journal.db`. `brain_audit.py` had inherited my error and was fixed too; it now names `positions_source` on every book. |
| **The event sleeve's exits are broken** | Working. The exits were **resting pre-market** — submitted 00:07 UTC, US opens 13:30. The cap I saw was the double-sell guard doing its job. | Checked the timestamps against market hours. |
| **`qty < 1 share` is a live leak** | Fixed **8 days earlier** in `baa6de0`. | `git log`. |

A fifth, smaller: `label_agrees: false` in my own audit was my check comparing
distinct-symbol-days-among-gradable against all-labelled. The labelling was
correct. It now reports `true`.

**What all of these cost:** nothing, because they were caught before acting.
What they would have cost is the point — "the sleeve's exits are broken" is one
step from disabling a working exit path.

---

## 3. Mutation testing, and why it earned its place

Every test written today had the bug **put back** to confirm the test goes red.
**Seven did not, first time round.** That is a ~20% false-green rate on tests
written by someone deliberately trying to write good ones.

| The test | Why it passed with the bug reintroduced |
|---|---|
| Outage handling | Asserted the **outcome**, not the representation it was meant to pin. |
| Alert delivery | **Stubbed the very method** it was testing. |
| Held-position desync | Called the helper directly, not the **wiring**. |
| Small-book sizing | Assigned `broker.cash`; `PaperBroker` keeps cash in **`_cash`**, so it created a new attribute and the case was vacuous. |
| Runner decisions | Positions opened at $100 basis against ~$250 synthetic prices took **+149%** and sold immediately. |
| `.env` guard (§4.46) | Called `_running_under_test()` at **run** time, when the env var is set — passed with the fix reverted. |
| Calibrator bar (§4.47) | Lowering `MIN_N` back to 20 **broke nothing** — every fixture supplies plenty of dates. |

The last one is the most instructive, because the test was not merely weak — it
would have let someone **silently undo a decision you made**. The fix was to
assert the decision in the unit that matters:

```python
assert MIN_N // HORIZON >= 12          # not "20 samples" — 12 real observations
assert structural_bar >= 2 * causal    # structure needs more than a guess
```

**Standing rule, now in [`design/AUDITING.md`](../design/AUDITING.md):** a test
written for a defect is not done until the defect has been reintroduced and the
test has been seen to fail.

---

## 4. What was built so this is repeatable

The review found things that were *findable all along*. The gap was
instrumentation, so the second half of the day went into instruments rather
than fixes.

| Instrument | What it answers | Run it |
|---|---|---|
| **`scripts/brain_audit.py`** | Every number in the review, against today. 8 sections, `--json`, `--section`, `--snapshot` for a diffable memory. | Before writing **or believing** any review. |
| **`scripts/cue_check.py`** | Which §4B cues have fired. Runs on a timer and notifies only on a **state change** — the cues that are arithmetic no longer depend on someone remembering. | `ai-investing-cue-check.timer` |
| **`scripts/brief_node_audit.py`** | Has the digester's node reference drifted from the graph it teaches? | Any seed bump. |
| **`scripts/backfill_abs_ratio.py`** | One-time: seed `abs_ratio` from the settled record so §4.45 takes effect now instead of in a week. | Done. Idempotent. |
| **`docs/design/AUDITING.md`** | The five traps, **what each one cost this project**, how to read each audit section, how to write a review. | Before the next review. |

The rule that document exists to state:
**facts may change without evidence; weights may not.**

One detector needed fixing before it was trustworthy: `brief_node_audit`
initially matched every backticked word in §7 and reported a JSON field
(`equilibrium`) and an edge type (`supplies`) as stale node ids. *A drift
detector that cries wolf gets ignored, which is worse than not having one.*

---

## 5. What is live right now

From `brain_audit.py` on the ProDesk, **2026-08-21T14:15Z**, at HEAD `4df3b2a`.
These are measured, not recalled.

```
GRAPH        609 nodes · 1,125 edges (802 curated + 323 LLM) · 469 assets
RESOLUTION   202 distinct signatures / 469 assets = 43.1%
             205 inert · 104 duplicate a peer · 31 orphan LLM nodes
COUNTING     44,195 rows -> 636 observations (69.5x) · 574 gradable
             label_agrees: true
LEARNING     formula   fitted:false, outcomes 0        (deliberate hold)
             edges     0/0/343 verdicts, gain 2.0 SATURATED
             reliability 122 symbols, 0 pinned         (was pinned; §4.37)
             emotion   panic_rebound 0.0 measured-contradicted, control group: yes
             gate      adviser_long n=90 hit 62.2% / 15d — needs 30d
BOOKS        trading 9,981.99 (11 pos) · investing 9,817.74 (3)
             sleeve 11,355.73 (0, flat between events) · crypto 5,007.99 (3)
             crypto-event 4,805.29 (1)
ORDERS       39 filled (24 buys) · 7 pending · 34 rejected
TESTS        62 files / 645 passed, both runners, both machines
```

**Read `basis` when it appears.** All five books currently report
`basis: (undeclared)` — the wiring is in place at every mark site, but a mark is
written **once a day** and the last one predates the deploy. That is filed in
§4A as *unverified in production*, which is a different claim from *fixed*, and
this project has been burned by that difference before.

---

## 6. What to expect from this, honestly

You pushed back that this has to *"translate to being better at making money,
otherwise this brain is as good as a kid's brain."* That is the right test, so
here is the honest split.

**Directly moves money:**
- The crypto book can transact again (§4.41) — it was frozen at 100% cash.
- 40% of thesis capacity redirected to positions that can actually open (§4.42).
- The routed book's equity is correct under margin (§4.36) — the circuit breaker
  acts on that number, and it was reading −$4,265 on a flat book.

**Prevents losing money:**
- A total feed outage stays loud (§1.7) — §4.7 flattened a healthy book once.
- Six relationships not halved on three weeks of data (§4.47).
- Expectations no longer corrected in the wrong direction (§4.45).

**Neither, and worth saying plainly:** the graph's *judgement* is unchanged. No
weight was hand-tuned, the formula still runs on priors, and 205 assets are
still inert to every macro shock. What changed is that the brain can now **grade
itself honestly** — and every learning loop it has was reading the corrupted
grades. **This is the precondition for improvement, not the improvement.** The
loops now measure correctly and need running time.

**The single largest open risk to returns** is not on the fixed list: `gain` is
saturated in **two** modules, so the model under-predicts move magnitude and
both corrections are capped below what the evidence asks for. That is a sizing
decision on 19 settled claims, and 19 is not enough to size on.

---

## 7. What is next

Only one item left is fixable purely in code. The rest are **decisions**,
**waits**, or **curation** — and saying which is which is the point of this
section.

### 7.1 Code — do this next

| Item | Why it is next |
|---|---|
| **`shadow.json` NaN-cash arithmetic test** | §4A. The test must be written **before** the A/B shadow baseline is reactivated, not after — a baseline that can hold `NaN` cash is a comparison that silently means nothing. |

### 7.2 Decisions — yours, and each needs a number, not a preference

| Decision | What it turns on |
|---|---|
| **Raise the two gain ceilings** (§4.45, §4.47) | 19 settled claims say the model under-predicts magnitude ~14×; both corrections cap at 2–3×. Suggested cue: **50 settled claims**, or `abs_ratio` going flat. |
| **Place the `O39.SI` order** | The only qualifying long, blocked because the live slice is USD-only. Not data-gated — it is one small real order during SGT hours, proving submit → fill → stop → exit, exactly as `F` proved the US leg. |
| **Non-USD live trading** | Same gate as above; do it in that order, and after the price-sentinel work that is already done. |
| **The self-wiring BAR** (not the budget) | The 6/day budget caps the rate; nothing caps the *quality*. 323 LLM edges, **all 323 unreviewed**, and the calibrator cannot reach them. |

### 7.3 Waits — with the cue that ends the wait

| Waiting on | Cue |
|---|---|
| **Formula refit** (§4.28) | Deliberate hold. Refitting now would fit θ on a 26-day single-regime sample whose measurement layer was **only just corrected**. Wait for clean observations, then let the Deflated-Sharpe gate decide. |
| **First edge verdicts** (§4.47) | ~2 months. Read the **first batch by hand** — a bar chosen by reasoning is still a bar nobody has watched fire. |
| **Adviser gate eligibility** | n=90, hit 62.2%, **15 days** of the 30 required. Self-checking on a timer; nothing to remember. |
| **Sleeve's true risk/reward** | Re-derive from `ratio_true`, **not** `expected_move` — that is what made it look like 32:1. Cue: first 10% stop-out, or 15 completed cycles. |
| **`602035` rejects** | Instrumented; the next occurrence will say why. The obvious diagnosis (§4.23 tick snapping) is **ruled out**. |
| **Declared book basis** | The next daily mark. If it lands without `basis`, that is a live defect, not a timing artefact. |

### 7.4 Curation — real work, no cleverness available

- **205 inert assets.** Wire the real companies, delete the news-copy
  vocabulary (`kenya`, `warner_bros`). They inflate every "the graph knows
  about N companies" claim, and a tradable among them is scored on the formula
  leg alone.
- **104 assets that duplicate a peer.** The graph tells apart 202 objects and
  holds 469.
- **323 unreviewed LLM edges**, via `review_edges.py` — a queue built in §4.22
  and never used once, on any edge, ever.
- **New-company discovery** still needs a periodic manual sweep; re-run
  `graph_gap_scan.py` first each time to check whether it has started catching
  real names on its own.

---

## 8. The three lessons worth carrying

1. **A number reused by two consumers will eventually be right for one and
   wrong for the other, and the wrong one fails silently because the field
   still looks populated.** §4.45's signed-vs-magnitude ratio; §4.6's `hit`
   before it got a benchmark.

2. **"It has produced no output" and "it is not ready to produce output" are
   different diagnoses with opposite fixes.** §4.47's calibrator looked dormant
   and was three days from speaking confidently on four observations. Only
   measurement tells them apart.

3. **A test is not evidence until you have watched it fail.** Seven of today's
   passed with the bug put back — including one that would have let someone
   silently reverse a decision you had just made.

---

## 9. Follow-up pass — the register drifted again, hours after closing it

This section exists because of exactly the failure §0 warned about: §4A had
drifted from live state again, inside the same commit that claimed to have
fixed drift. Found while fact-checking a draft summary paragraph before it
went anywhere, not by a scheduled review — which is itself the finding worth
keeping: **drift-checking has to happen at the moment a number is about to be
reused, not on a calendar.**

### 9.1 What was wrong

Three things, all inside `STATE_OF_THE_SYSTEM.md`, none of them in this
document (§5's figures were already correct):

1. **§4A had stale figures that §2 of the same file already had right.**
   §2 was refreshed from a live `brain_audit.py` run late in the day (per its
   own rule); §4A's inert-asset and self-wiring rows were not carried forward
   with it, and still read **198 inert / 462 assets / 317 unreviewed LLM
   edges** — the numbers from *before* the day's later self-wiring growth,
   not the **205 / 469 / 323** that §2 (and this document's §5) already had.
2. **The §4 failure-register index table still contradicted §4A.** Row 4.40
   read "❌ Filed, not fixed — see §4A" after §4A itself had already marked
   4.40 CLOSED — the identical pattern that opened this whole review (§0: "the
   last five commits each edited one §4A row and opened no register entry").
   4.46 and 4.47 had no index row at all.
3. **The venue-stop row's position count had aged out from under it.** It
   read "13 positions... ten names in the trading book plus the sleeve's
   three." The sleeve has since gone fully flat (0 positions — it runs flat
   between events, not frozen, and §2 already said so); the number was true
   of the 2026-08-21 check that produced it and not of anything after.

### 9.2 How this was checked

Per §4's own rule — not hand-derived:

```
$ ssh prodesk 'cd ~/Projects/AI-Investing && .venv/bin/python scripts/brain_audit.py'
GRAPH   inert_assets: 205, assets_duplicating_a_peer: 104,
        llm_edges: 323, unreviewed_llm_edges: 323
LEARNING edge_calibration: gain: 2.0, gain_saturated: true
BOOKS   trading 11 pos, investing 3, sleeve 0, crypto 3, crypto_event 1
```

`gain: 2.0, gain_saturated: true` is worth flagging on its own: it confirms
against production, not just against `calibration.py`'s bound, that the
2.0 clamp claimed throughout §1.2 and §6 is still actually binding today.

§4A's open-row count was verified by counting the table directly rather than
trusting either the committed figure or a later draft: **17 open rows**,
unchanged — matching this document's own `19 → 17`, not a "24 → 16" figure
that appeared in an early draft of a follow-on summary and had no commit
behind it. Nothing closed between `4df3b2a` and now; there was no basis for a
different count.

### 9.3 Fixes applied

Two commits, both documentation-only, both deployed to the ProDesk
(`git pull` fast-forwarded cleanly, no conflict):

| Commit | What it did |
|---|---|
| `c1aa11d` | §4A's inert-asset and self-wiring rows updated to 205/469/323, sourced to the `brain_audit.py` run above. §4 index table: row 4.40 flipped to closed; 4.46 and 4.47 rows added. |
| `228ddb4` | Venue-stop row's "13 positions... the sleeve's three" rescoped to the check that produced it, rather than left reading as a current count — the trading book's 11 is what's still live. |

No code changed. No defect count changed — this was register hygiene, not a
fix, and is filed here rather than as a new §4.4x entry for that reason.

### 9.4 What's next

Unchanged from §7 — this pass corrected drift, it did not close or open
anything. The 17 open rows, the one code item (`shadow.json`'s arithmetic
test), the four decisions, the six waits, and the curation backlog are all
exactly as §7 lists them. The one addition: whoever writes the next
"still open, N → M" summary should pull §4A's row count directly (or read
this section) rather than recall it — that is the specific mistake this pass
exists to record.
