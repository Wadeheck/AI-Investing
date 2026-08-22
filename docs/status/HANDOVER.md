# Handover — resume here

**Written 2026-08-22. HEAD `39384dd`, deployed and running on the ProDesk.**

This is the *resume-here* document. It is deliberately short and it points at
the detail rather than repeating it.

| If you want | Read |
|---|---|
| **What is broken right now** | [`STATE_OF_THE_SYSTEM.md`](STATE_OF_THE_SYSTEM.md) **§4A** — the live open list. §4 is history. |
| **When each open item is ready to act on** | Same file, **§4B** — every row names a number, a date, or an event. |
| **Why any of it was done** | [`BRAIN_REVIEW_2026-08-21.md`](BRAIN_REVIEW_2026-08-21.md) — the analysis. |
| **What was done, and what I got wrong** | [`SESSION_REVIEW_2026-08-21.md`](SESSION_REVIEW_2026-08-21.md) — the work record. §2 is the mistakes, §7 is the open split, §11 is the delegated decision. |
| **How to measure any of this yourself** | [`../design/AUDITING.md`](../design/AUDITING.md), then `scripts/brain_audit.py`. |

---

## 1. Deploy state — CURRENT, nothing pending

The ProDesk woke on schedule at **07:30 SGT on 2026-08-22**, pulled, and is
running **`2b24e58`**. Engine `active`, no failed units.

*(Historical note, because the correction is the useful part: the deploy was
left pending overnight when the box powered off mid-session. On the resume, one
prediction I had written here was wrong in wording — `brain_audit.py` showed as
`M` in `git status`, not clean. The content was byte-identical to the committed
version; it read as modified only because the box's HEAD predated that commit.
Verified by comparing sha256 on both sides before discarding the working copy.
**Compare the hash, do not trust the prediction.**)*

Both post-deploy checks were run, and **the second one failed, correctly** —
see §1.1.

```bash
# the routine health check, any time
ssh prodesk 'cd ~/Projects/AI-Investing && systemctl --user is-active ai-investing.service'
ssh prodesk 'cd ~/Projects/AI-Investing && .venv/bin/python scripts/brain_audit.py --section learning'
```

### 1.1 The basis cue fired NEGATIVE, and it was right — §4.52

The one open cue was: *does the next daily mark carry a `basis` field?* It did
not. That row had said in advance what a missing field would mean — **a live
defect, not a timing artefact** — so there was nothing to argue about.

```
stock_journal.jsonl   "event": "mark", "equity": 10001.71 ...      no basis
invest_journal.jsonl  "event": "mark", "basis": "BookBroker:book"  DECLARED
```

The second line is what made it real: the investing book declared its basis on
the **same cycle**, so the mixin demonstrably worked — the missing one was a
path, not a delay. `stock_journal.jsonl` is written by the **runner**, not by a
book: a fifth journal nobody counted, and the one the watchdog and
`daily_status.py` actually read.

Fixed, three mutations verified. **Sixth instance of one-of-N-paths-fixed.**

**One live confirmation is still outstanding, and I nearly skipped it.** The runner
writes one mark per SGT day, and today's (`day: 2026-08-22`) was written *before* the
fix deployed — so the next one is **2026-08-23**. I had already marked the row closed
before checking that. Tested is not observed, which is the exact distinction that
created §4.52 in the first place, so it now has its own §4B cue:

```bash
ssh prodesk 'tail -1 ~/Projects/AI-Investing/data/stock_journal.jsonl'
# expect "basis": "live:10000" — if it is absent, the fix does not work
```

**The transferable lesson is about the cue, not the code:** a cue is only worth
writing if its *negative* answer is written down too. "No basis yet" was true
the evening before and false the morning after, and only the pre-written
verdict told them apart.

---

## 1.5 THE HEADLINE, if you read nothing else — §4.56

**Counted properly, no book has demonstrated edge.**

The event sleeve is **+$1,146** and the number anyone would quote is
*16 fills, t=2.19, p=0.028 — significant*. But the sleeve enters and exits a
**basket**: those fills land on **6 days**, three correlated names at a time.
`NVDA, AMD, 000660.KS` is one semis bet wearing three tickers.

```
                    n      t       p       significant
per_fill           16   2.19   0.028   YES
per_basket          6   1.64   0.101   no      <-- identical money
```

Grouped by theme the six baskets are **three bets** — energy (lost),
solar/materials (won), semis (won four baskets running). At n=3 nothing can
ever be significant.

| book | realised | per_fill | per_basket |
|---|---|---|---|
| event_sleeve | **+$1,146** | sig | **not sig** |
| crypto | +$33 | not sig | not sig |
| investing | −$72 | not sig | not sig |
| crypto_event | −$266 | sig (LOSING) | **not sig** |

`crypto_event` is the sharpest case and it cuts the other way: per-fill it is
*significantly losing* on **three fills across two baskets**. Acting on that
would shut a book on two observations. **The per-fill figure lies in both
directions**, which is why `brain_audit --section pnl` prints both, always.

**This does not say the system loses money.** +$1,146 is real and the direction
is encouraging. It says 26 days and three thematic bets cannot separate it from
luck — and that anyone quoting the 16-fill t-statistic is counting tickers
instead of decisions.

### The benchmark, which was the next piece of work — and it is now done

§4.57 benchmarked the books, and §4.58 attacked the result on its weakest point.
**Benchmarking made the sleeve look BETTER, not worse** — raw P&L is noisier
because the market factor it carries swamps the residual:

```
event sleeve, 6 baskets      t       p        mean excess
raw P&L                    1.64   0.162
vs BROAD benchmark         2.18   0.081      +2.54%/basket
vs its own SECTOR          2.19   0.080      +2.26%/basket   <- 11/16 fills
```

**The edge is not semiconductor beta.** Measuring `NVDA`/`AMD`/`ASML`/`TSM`/
`000660.KS` against `XLK` instead of `SPY` moved the mean by 0.28pp and the
t-statistic not at all. That is the first number in this system to be attacked
on its weakest point and hold.

**Still not significant — and the bar is small: 8 baskets, of which there are
6.** Two more, roughly a fortnight. The yardstick is now correct *before* the
data arrives rather than after, which is why §4.58 was worth doing immediately
instead of at the cue.

---

## 2. What this session actually did

```
                     START (e327d65)      NOW (2b24e58)
register entries          §4.36               §4.58        (22 new)
§4A open rows              19                  15
test files                 54                  65
tests                  one runner only     707, BOTH runners, BOTH machines
```

**Twenty-two defects found and fixed (§4.37–§4.58).** Eleven of them were found only
because an earlier one taught us where to look. Four false alarms are recorded
at the same length as the fixes, because a review that records only its hits is
not a measurement.

**Two of the twenty-two I caused myself, during this session:**
- **§4.48** — my `parse_args(argv)` refactor killed the X capture channel for
  two hours, and the guard written in the same commit passed the whole time.
- **§4.50** — a cleanup rule I wrote deleted **Procter & Gamble** from the live
  graph. Restored.

Both are written up in full. They are the two most useful entries in the file.

### The recurring shapes, which matter more than any single fix

1. **One-of-N-paths-fixed — six times** (§4.14, §4.23, §4.36, §4.49, §4.51,
   §4.52). A defect gets fixed where it was *observed* and nowhere else. The
   0.0 price sentinel was removed from the live path in the morning and left
   standing in the shadow path, in the same file, eight hours later. **This is
   the single most productive question to ask of any fix in this codebase:
   where else does this pattern live?**
2. **A ratio without its null is not a measurement — three times** (§4.6 needed
   a benchmark, §4.44 a control group, §4.51 a noise floor). Same question
   every time: *compared with what?*
3. **A test is not evidence until you have watched it fail.** Eight tests this
   session passed with the bug reintroduced. Mutation testing is now the
   standing rule in `AUDITING.md`.

---

## 3. Decisions you delegated, and what I did with them

You gave me two calls. Recording both, because the reasoning is the part worth
keeping.

### 3.1 The gain ceilings — **DECIDED: hold. Do not raise.**

Full reasoning in [`SESSION_REVIEW_2026-08-21.md`](SESSION_REVIEW_2026-08-21.md)
§11 and register §4.51.

**The short version, and it reverses what I told you earlier in the session.**
I had called the saturated gains *"the single largest open risk to returns"* on
the strength of §4.45's finding that realised moves ran 14× the expectation.
Before acting I ran the control §4.45 never had:

```
median |realised / expected|             14.4
median  own-5d-volatility / expected     15.5   <-- what PURE NOISE produces
directional hit rate                      0.526  (n=19 — a coin flip)
```

Indistinguishable. `expected_move` is the move **attributable to the event**;
`realized_move` is the asset's **total** five-day move, which its own volatility
dominates. The ratio measures signal-to-noise, not calibration error.

Raising the gain to close it would need a gain above 13, at which point every
`expected_move` asserts the model predicts the asset's **entire five-day
range** — and that number feeds position sizing, the sleeve's risk/reward and
stop distances. It would have inflated all three on a 52.6% hit rate.

**This is now enforced, not just recorded.** `brain_audit.py` prints the ratio,
the noise floor, the hit rate and the conclusion together, and a test refuses to
let the ratio be published without its control.

**What would re-open it:** the observed ratio falling **below** its noise floor
while the hit rate rises. That is a graph-wiring outcome, not a sample-size one
— which is why the old cue ("revisit at 50 settled claims") was also wrong and
has been corrected.

### 3.2 `O39.SI` — **DECIDED: no. §4.55**

You handed this one over too. **Do not place it** — not on caution, and not on
venue risk. On the evidence, which does not exist.

The case rested on 7 symbol-days at hit 0.86. Raw that is p≈0.06 and nearly
interesting. In the unit that exists — daily readings of a 5-day forward return
— it is **1 independent observation**, and one observation of a coin is a coin.

**The bar, stated so it can be met:** a 0.86 hit rate needs **8 independent
observations** for p<0.05 = **40 consecutive symbol-days**. It has 7.

**§4.53 is the wider finding, and it retires a headline of my own review.** No
market in the reach table is distinguishable from chance — `KS 0.889 (n_ind=2)`,
`SI 0.875 (n_ind=2)`, `US 0.529 (n_ind=10)`. The claim that *"the brain is best
in the markets it cannot trade"* was **noise, ranked**: the best hit rates
belong to the markets with the fewest observations, which is what small samples
do.

**What was really being conflated**, and this is the substance:

| | Sized by | Instrument chosen for | Success is |
|---|---|---|---|
| **A trade** | edge × conviction | the signal | P&L over many repetitions |
| **A path validation** | the minimum that proves mechanics | lot/tick clarity, liquidity | submit → fill → stop → exit, observed |

Merging them is how a path test gets sized like a trade and a trade gets
justified by a path test.

**Still open, and still yours:** the SGX **path validation**, as a separate
deliberately-minimal test in SGT hours, watched. The venue layer is where this
system's defects actually live (§4.23 tick snapping, §4.30 a HK fill booked at
7× price, the unexplained `602035` rejects), so proving it has real value — just
not value a 1-observation signal should be used to justify.

### 3.3 Judgement calls I made inside the work, for the record

| Call | What I decided |
|---|---|
| Formula refit | **Hold.** Refitting on a 26-day single-regime sample whose measurement layer was only just corrected is how you get a confidently wrong model. |
| Orphan-node collection age | **30 days.** A node minted today may be wired tomorrow; one unwired for a month is vocabulary. Shorter would fight the digester and re-open §4.24 from the other side. |
| `_and_` as a non-entity marker | **Declined.** `larsen_and_toubro` is one company. Pinned by a test so nobody adds it later — and then I shipped a *different* rule with the same failure mode anyway (§4.50). |
| `allow_nan=False` on every state write | **Yes**, after scanning all 99 live state files to confirm nothing legitimately writes one. |
| Tombstones on collected orphans | **No.** A tombstone records a rejected *claim*; nothing was ever asserted about these nodes. |

---

## 4. What is outstanding — 16 open rows, by what they actually need

§4A is the authority. This is the same list grouped by *what kind of thing it
is*, because "still open" was hiding four different situations.

### 4.0 THE NEXT PIECE OF WORK — benchmark the books (§6)

Everything below is real. All of it is secondary to knowing whether the thing
works, and right now the honest answer is *"not demonstrably, and we cannot even
say how generous that verdict is."* See §6.

### 4.1 Needs a decision from you (2)

| Item | What it turns on |
|---|---|
| **`O39.SI` / non-USD trading** | §3.2 above. Not data-gated — one small order in SGT hours proves the path, exactly as `F` proved the US leg. |
| **The self-wiring BAR** (not the budget) | The 6/day budget caps the *rate*; nothing caps *quality*. 320 LLM edges, **all 320 unreviewed**, and the calibrator cannot reach them (none terminates on a tradable symbol). How much self-wiring do you actually want? |

### 4.2 Waiting, each with a cue that fires on its own (5)

| Waiting on | Cue |
|---|---|
| **First edge verdicts** (§4.47) | ~2 months, `MIN_N = 60`. **Read the first batch by hand** — a bar chosen by reasoning is still a bar nobody has watched fire. |
| **Formula refit** (§4.28) | Deliberate hold. Let clean observations accumulate, then let the Deflated-Sharpe gate decide. |
| **Adviser gate** | n=90, hit 62.2%, **15 of the 30 days** required. Self-checking on a timer. |
| **Sleeve's true risk/reward** | Re-derive from `ratio_true`, **not** `expected_move`. And note §4.51: the 32:1 was always a measurement artefact. |
| **`602035` rejects** | Instrumented. Next occurrence will say why. §4.23 tick-snapping is ruled out. |

### 4.3 Curation — real work, no cleverness available (3)

| Item | Note |
|---|---|
| **200 inert assets** | Now has a *mechanism* (shape refusal + 30-day collector), but the collector removes nothing until ~2026-09-04: all 31 unwired nodes are under 30 days old. This is **churn**, ~2/day, not an accumulation — which corrected my own framing. |
| **104 assets duplicating a peer** | The graph tells apart 202 objects and holds 464. |
| **320 unreviewed LLM edges** | `review_edges.py`. The queue was built in §4.22 and has **never been used once, on any edge, ever.** Unlike the node work, no rule substitutes for judgement here. |

### 4.4 Known and accepted, or low priority (5)

`θ` reset to v1 · three dormant candidate signals · the digest brief's golden
set (narrowed — needs an Anthropic key neither machine has) · new-company
discovery's manual sweep · the LLM endpoint free-tier cap · git history still
contains the revoked string · one dangling ledger claim · no venue stops (mostly
by design; the real item is gap risk on ~$4,800 across the trading book).

---

## 5. The honest summary of what changed

**What moves money:** the crypto book can transact again (§4.41, it was frozen
at 100% cash); 40% of thesis capacity redirected to positions that can actually
open (§4.42); the routed book's equity is correct under margin (§4.36) — the
circuit breaker acts on that number and it was reading −$4,265 on a flat book.

**What prevents losing money:** a total feed outage stays loud (§4A); six
relationships not halved on three weeks of data (§4.47); expectations no longer
corrected in the wrong direction (§4.45); **and the gain ceilings not raised on
a number that was noise (§4.51)** — which on the day may be the most valuable
single decision in this session, because it is the one that would have been
irreversible and invisible.

**What did NOT change, and say it plainly:** the graph's *judgement*. No weight
was hand-tuned, the formula still runs on priors, and 200 assets are still inert
to every macro shock. What changed is that **the brain can now grade itself
honestly** — and every learning loop it has was reading corrupted grades.

**That is the precondition for improvement, not the improvement.**

**And the thing that should make you trust it less, not more:** twenty defects
in one system that had 645 passing tests, two of them introduced by me during
the session itself.

That used to be where this paragraph stopped — "the defect rate is a function of
how hard anyone looks" — which is true and useless, because it makes quality
depend on who is on shift. **It is now partly fixed (§4.54).** The twenty were
not twenty insights: sorted by the QUESTION that surfaced each, **13 of 20 came
from four questions a script can ask**, and `scripts/defect_sweep.py` asks them.

It earned its place on the first run by finding that §4.51's own fix was
one-of-N *again*. Then measurement showed those particular siblings were
dormant — **the sweep asks, it does not convict.**

```bash
python3 scripts/defect_sweep.py          # the four questions, every time
python3 scripts/brain_audit.py           # every measurement, read-only
```

---

## 6. What is next — and for once the answer is "wait"

**The benchmark is done (§4.57, §4.58).** It was the right next thing and it has
been built, attacked, and deployed. See §1.5.

**The next step is two more baskets**, and there is no work that brings them
sooner. The bar is **8**, there are **6**, and at the observed effect size the
eighth clears p<0.05. That is roughly a fortnight of the event sleeve.

```bash
# the one number to watch
ssh prodesk 'cd ~/Projects/AI-Investing && \
  .venv/bin/python scripts/brain_audit.py --section pnl'
# read excess_over_benchmark.per_basket — NOT raw P&L, NOT per_fill
```

**This is a real change of posture.** For most of this session the answer to
"what next" was another defect. It is not now: the sleeve has a specific,
countable question with a date attached, the yardstick it will be judged by is
correct, and the remaining backlog improves a system whose central claim is
about to be settled either way.

### 6.1 If you want work in the meantime

**The self-wiring BAR** (§4A) — the highest-value open item and genuinely a
decision rather than a task. The 6/day budget caps the *rate* of LLM-proposed
edges; nothing caps *quality*. There are **320 LLM edges, all 320 unreviewed**,
and the calibrator cannot reach any of them (none terminates on a tradable
symbol, so `_score_pair` has no price series). The only thing between a bad
inference and the live field is a 0.6 confidence cap.

The question is not "review them" — it is **how much self-wiring do you want at
all**, given that nothing can grade it.

### 6.2 What NOT to do

- **Do not raise the gain ceilings** (§4.51). The 14× was noise. Settled.
- **Do not place `O39.SI` as a trade** (§4.55). One independent observation.
- **Do not refit the formula** (§4.28). A 26-day single-regime sample whose
  measurement layer was corrected days ago is how you get a confidently wrong
  model.
- **Do not size up on the sleeve** if the eighth basket clears p<0.05. One
  significant book among four tested is roughly what chance produces; the
  correct response to the cue firing is *keep measuring*, not *allocate*.

