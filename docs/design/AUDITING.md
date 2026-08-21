# Auditing the brain

**Read this before writing any review, and before believing any number in one.**

This project has published two reviews that reached opposite conclusions from
the same data, three days apart, because both read a sample that was inflated
65-fold and neither checked. That is not a story about carelessness — both were
careful. It is a story about a measurement layer with no declared unit, where
every consumer invented its own and two of them disagreed without either
noticing.

So the discipline below is **executable**, not remembered:

```bash
python3 scripts/brain_audit.py                  # every measurement, read-only
python3 scripts/brain_audit.py --json           # machine-readable
python3 scripts/brain_audit.py --section graph  # one section
```

No market calls, no LLM, writes nothing the engine reads. Run it on the
ProDesk — `data/` on a dev box is a stale snapshot.

---

## 1. The five traps

Each of these produced a **wrong published conclusion in this project's own
history**. They are listed with the damage, because the abstract version is
easy to nod at and hard to apply.

### Trap 1 — Pseudo-replication: counting rows, not observations

`advice_log` is written every cycle (~126/day at a ~10-minute cadence) and the
scorecard grades every row of it. So one standing view — "long NVDA today" — was
frozen, graded and counted 126 separate times against the same forward return,
out of the same 5-day window.

```
advice_outcomes rows        42,882
distinct (symbol, day)         634
inflation                     67.6x
```

**Damage.** Every `n` in `SCORECARD_REVIEW_2026-08-12` and `..._08-15`, and in
`adviser_gate.json`, was inflated by this; every t-statistic by ~√65 ≈ 8×. The
08-12 review concluded the short side was inverted; 08-15 reversed it on the
"full sample"; deduplicated, the reversal itself reverses and 08-12 was right.
Worse, `adviser_gate.THRESH["min_n"] = 500` — the anti-overfitting guard on an
**automated** control that nudges live sizing — was a bar of 7.7 independent
observations, ~15 days from opening.

**The rule.** One observation per (symbol, calendar day). `advice_outcomes`
carries `is_primary` for exactly this; **any query computing a hit-rate must
filter on it.** The audit's `counting_unit` section checks that the label still
agrees with an independent count — if `label_agrees` goes false, some write path
is bypassing the rule.

**The subtlety worth keeping.** A symbol-day whose FIRST call fell inside the
deadband contributes no claim, and must **not** be back-filled from a later
re-issue that happened to land outside it. That is selection on the outcome.
(Re-issues of one day are graded at different moments against different "latest"
prices, so near the deadband boundary they genuinely disagree — the primary row
is graded once, deterministically.)

### Trap 2 — Overlapping windows: daily samples of a 5-day return

Consecutive daily observations of a 5-day forward return share four-fifths of
their window. They are deduplicated but still not independent.

**The rule.** Deflate the *sample size*, not a finished statistic:
`n_effective = n / HORIZON_DAYS`. It is correct for a binomial and easier to say
out loud — 12 daily observations are about 2 independent bets.

**Why it matters more than it sounds.** The single result the 2026-08-21 review
found surviving deduplication:

```
long / conviction=1   n=90  hit 0.622   p=0.026   n_eff=18   p_effective=0.481
```

Significant raw; a coin flip once the windows are counted. **The gap between `p`
and `p_effective` is the finding.** Quoting only the first is how this project
published two contradictory reviews.

### Trap 3 — No benchmark: grading a call against zero

A call graded on its absolute move measures the tape's drift, not the call.

**Damage, twice.** The advice scorecard graded `short_or_avoid` as a prediction
of a *fall* in a rising market, marking every correct avoid as a miss and
producing a blended 0.404 hit-rate that "sat unexplained in the docs for days"
(its own `_BENCH` comment). `event_outcomes` then repeated it exactly — graded
against zero until 2026-08-21.

**The rule.** `scorecard.benchmark_for()` is the single source of truth for
which yardstick a symbol is measured against — crypto against BTC, HK against
2800.HK, and never a benchmark against itself. Reuse it; do not re-derive it.

**Read the label, not the schema.** `emotion_calibration.json` reports
`return_basis`, and it will say `"absolute (excess column empty)"` while old
rows dominate. A column existing is not the data being market-relative.

### Trap 4 — No control group: testing a comparative claim against zero

"Panic overshoots" is a claim *relative to an ordinary event*. Tested against
zero it returns the sample's average forward return — which is why the first
version of `emotion_calibration.py` reported **+1.192% after panic and +1.118%
after euphoria**: the same answer, within noise, for opposite emotions, with
both coefficients clamped to their maximum of 1.0.

Against a control group (every other non-noise event, Welch's t):

```
panic_rebound   coef  0.000   lift −0.00038   t −0.24   measured-contradicted
euphoria_fade   coef −0.167   lift −0.00115   t −0.50   measured
```

Panic returns +1.192% against an ordinary event's +1.230%. **The rule:** a
comparative claim needs the thing it is being compared to, in the query.

### Trap 5 — The wrong test for a 0/1 outcome

`hit` is Bernoulli. A t-test on it degenerates exactly where the evidence is
strongest: a symbol that hit 12 of 12 has zero sample variance, so its t is
undefined and it drops **silently** out of any "what clears a bar" list. The
first draft of `brain_audit.py` did this and lost four of nine pairs, including
a perfect run.

**The rule.** Two-sided exact binomial against p=0.5. It handles a perfect run
natively, which is the case that matters most.

---

## 2. What the audit reports, and how to read it

| Section | The question it answers | The trap it guards |
|---|---|---|
| `counting_unit` | Is every statistic counting observations? | 1 |
| `directional` | Does conviction predict, by direction? | 1, 2, 5 |
| `symbols` | Which (symbol, call) pairs clear a real bar — **both ways** | 1, 2, 5 |
| `events` | The second, independent instrument | 3 |
| `graph` | How many objects can the graph tell apart? | — |
| `learning` | Is anything actually learning? | — |
| `reach` | Are the good calls in markets we can trade? | 1 |
| `books` | Equity, and the basis it belongs to | — |

Three readings that are easy to get wrong:

- **`symbols` prints winners and losers at the same bar, deliberately.** A track
  record that reports only its winners is a brochure. On 2026-08-21 the losing
  list was longer and mostly bearish calls — which was the finding.
- **`events` is independent of the advice record.** Two different measurements
  agreeing is the only reason to believe anything at this sample size. Read the
  `+1` vs `−1` asymmetry (0.671 vs 0.442), not the levels — the levels are
  graded against zero until the benchmark backfills.
- **`learning` reports `alive` per loop.** A loop that has never moved is not a
  slow loop. As of 2026-08-21: the formula's two loops are both dead by design
  hold, and the edge calibrator has issued 0 verdicts on 643 relationships.

---

## 3. Writing a review

1. **Run the audit first.** Every number in `STATE_OF_THE_SYSTEM` §2 and
   §4.37–4.39 came from it. Paste; do not hand-edit — the §2 figures had drifted
   182 nodes and 323 edges before anyone noticed.
2. **Quote `p_effective` alongside `p`.** Always both.
3. **Report what is significantly WRONG at the same bar as what is right.**
4. **Say which instrument.** "The advice record says X and the event record
   independently says X" is worth ten times "the brain is good".
5. **State what you did not do, and why.** The 2026-08-21 review's most useful
   paragraph is the one explaining why FET/BCH/HYPE/ATOM were *not* added to a
   blocklist — their raw records looked damning (`FET/USD` long n=526, hit 0.00)
   and deduplicated they were 5, 3, 2 and 13 days. Acting would have repeated
   Trap 1 the same day it was fixed.
6. **Prefer a mechanism to a symptom.** `UNI/USD` was root-caused as "no graph
   node"; the node existed. The real cause was that its node carried no
   information the other twelve alts didn't — which is a class, not a symbol.

---

## 4. Updating the brain

**What may change without evidence:** wiring that is a statement of fact
(a company exists, an index contains it, a supplier supplies), node metadata,
and anything in the measurement layer that makes a number *more* honest.

**What may not:** an edge weight, a feature weight, or a sizing coefficient.
Those change only through their own gate —

- **θ** through walk-forward + Deflated Sharpe (`FORMULA.md` §4), or online RLS.
  Never by hand. A dormant candidate feature enters at weight 0 and earns its
  way (§7, §8).
- **Edge confidence** through `brain/calibration.py`, applied in memory at load
  and never persisted, so re-loading cannot compound a discount.
- **Emotion coefficients** through `emotion_calibration.py` against a control.
- **Adviser sizing influence** through `adviser_gate.py`, which measures its own
  eligibility daily and flips itself.

The pattern behind all four: **a change of belief requires evidence that a
machine can re-check.** A human "this seems right" may add a fact; it may not
add a weight. `graph.Edge.reviewed_at` says this out loud — a human keeping an
LLM edge does not raise its confidence past the 0.6 cap, because review clears
the queue, never the bar.

**Before you widen anything, check whether it is already reaching.** 198 of 462
asset nodes are inert to every macro shock, and 104 more are exact duplicates of
a peer. Adding a node to a graph that cannot differentiate the ones it has is
motion, not progress. `--section graph` gives you the number.

---

## 5. When a cue fires

`scripts/cue_check.py` (daily timer) watches the §4B cues that need no judgement
to *evaluate*: LLM edges vs curated, the sleeve's stop-outs and cycles, distinct
issuance days, and the calibrator's first verdict. It notifies only on a state
change and it **never decides anything** — a fired cue is a prompt to make a
decision, not a decision.

Cues that need a person to evaluate are deliberately absent. A cue that needs
judgement is not improved by a cron job guessing.

This exists because the one cue never missed was the one that watched itself
(`adviser_gate_check.py`), while the LLM-edge cue had already fired unnoticed at
354 against a threshold of 328 — and at nearly triple the rate its own due-date
was calculated from.

---

## 6. The honest summary, as of 2026-08-21

- Fresh **positive** shocks are the one thing this brain reliably does, on two
  independent instruments plus $1,146 of realised P&L.
- Its **bearish** side is anti-predictive rather than weak, on three.
- **Nothing yet clears a conventional significance bar** once overlapping
  windows are accounted for. 26 days is 26 days.
- The design is not disproven. It is **unproven**, and those are different.

Related: [`../status/BRAIN_REVIEW_2026-08-21.md`](../status/BRAIN_REVIEW_2026-08-21.md)
(the review this discipline came out of), [`BRAIN.md`](BRAIN.md) §4h,
[`FORMULA.md`](FORMULA.md) §4(c), `STATE_OF_THE_SYSTEM` §4.37–4.40.
