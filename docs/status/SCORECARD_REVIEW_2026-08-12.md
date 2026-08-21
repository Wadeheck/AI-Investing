# Scorecard review — first 8 days live (2026-08-04 → 2026-08-12)

> ## ⚠️ SUPERSEDED ON ARITHMETIC — read this first
>
> Every `n`, hit-rate and t-statistic below is computed from `advice_outcomes`
> ROWS. On 2026-08-21 that table was found to hold **~65 rows per real
> observation**: `advice_log` is written every cycle, so one standing view was
> frozen and graded ~126 times a day against the same forward return
> (STATE_OF_THE_SYSTEM §4.37). Sample sizes here are inflated ~65×, and every
> t-statistic by ~√65 ≈ 8×.
>
> **What that changes.** Findings quoted at n in the hundreds or thousands are
> typically 3–15 distinct observations. Deduplicated, the direction×conviction
> table reverses back to the 08-12 reading, and the "confirmed working on
> samples too large to be luck now" list shrinks to two symbols.
>
> **What survives.** The method, the per-book P&L pulled apart from its
> benchmark, the missed-opportunity framing, and most qualitative conclusions —
> the long side works better than the short side; the event sleeve is the
> strongest and most fragile result; the flagship book is absence rather than
> skill. Those were right. The arithmetic under them was not.
>
> Current numbers: `python3 scripts/brain_audit.py`. Method:
> [`../design/AUDITING.md`](../design/AUDITING.md). Superseding review:
> [`BRAIN_REVIEW_2026-08-21.md`](BRAIN_REVIEW_2026-08-21.md).

First post-mortem of the live books since the 2026-08-04 reset. Source: the
scorecard's own frozen record on the ProDesk (`data/brain.db`,
`advice_outcomes` + `event_outcomes`), not a re-simulation. Nothing was
rewritten to produce this; the scorecard never deletes.

## Read the sample size before the findings

    outcomes since go-live   9,677
    distinct symbols            62
    advice runs                688
    DISTINCT DAYS                4

Those 9,677 rows are NOT 9,677 independent observations. The cycle re-issues
standing calls every few minutes, so `MP: 543 avoid calls` is one standing
opinion re-stamped 543 times across four days, graded against one overlapping
5-day window. Effective independent sample is closer to **62 symbols over one
market week** — and one week is one regime.

Everything below is therefore a *hypothesis with a named confound*, not an
established defect. It is enough to act on cheaply (trim, hedge, watch). It is
not enough to re-fit the formula on.

## Finding 1 — the long side works; the avoid/short side is inverted

Graded on EXCESS return vs benchmark, so a generally rising tape is already
netted out (this grading was fixed 2026-08-04; see `brain/scorecard.py`).

| direction | conviction | n | hit | avg excess |
|---|---|---|---|---|
| long | **1** | 515 | **0.661** | **+2.08%** |
| long | 0 | 2,149 | 0.572 | +0.09% |
| avoid | 0 | 2,415 | 0.482 | +0.01% |
| avoid | **1** | 4,128 | **0.401** | **+1.50%** |
| short_or_avoid | 0 | 234 | 0.349 | +1.91% |
| short_or_avoid | 1 | 236 | 0.352 | +1.93% |

Conviction is **informative on the long side and inverted on the short side**.
High-conviction longs hit 66% and beat their benchmark by 2.1%. High-conviction
avoids hit 40%, and the things they told us to avoid beat their benchmark by
1.5%. Non-conviction avoids are merely neutral — so the damage is concentrated
exactly where the brain is *most* certain.

The same asymmetry appears independently in the event sleeve:

| event impact_sign | n | hit |
|---|---|---|
| +1 | 987 | **0.761** |
| −1 | 379 | **0.343** |

Two separate subsystems, same shape: this engine reads *what goes up* well and
reads *what goes down* backwards.

### The confound, stated plainly
Aug 4–12 was a rising tape. Excess-vs-benchmark controls for market direction
but NOT for beta. If the brain systematically tags high-beta and
expensive-looking names as "avoid", then one strong up-week reproduces this
table exactly, with no real defect. Distinguishing the two needs a down-week in
the sample. **Do not conclude the short logic is broken yet — conclude it is
unvalidated and currently expensive.**

## Finding 2 — the biggest missed opportunities

Told to avoid or short; outperformed anyway.

| symbol | call | n | excess | hit |
|---|---|---|---|---|
| **MP** | avoid | 543 | **+8.9%** | **0.00** |
| ALB | short_or_avoid | 10 | +7.9% | 0.00 |
| MP | short_or_avoid | 26 | +7.7% | 0.00 |
| PANW | avoid | 33 | +7.1% | 0.00 |
| 2317.TW | short_or_avoid | 19 | +6.8% | 0.00 |
| **JKS** | short_or_avoid | 48 | **+6.0%** | **0.00** |
| ASML | avoid | 69 | +4.1% | 0.00 |
| **JKS** | avoid | 629 | +4.1% | 0.30 |
| ATOM/USD | avoid | 636 | +3.5% | 0.04 |

**MP is the single largest miss** — never once right across 543 gradings.
Rare-earth/critical-minerals strength was visible in the tape and the graph
called it down every cycle for eight days.

**JKS is the one that costs real money right now**: the investing book holds a
live SHORT expressing an overvaluation thesis, and that exact call has been
graded wrong 677 times with zero hits on the short-form. This is the clearest
single action item in this document.

## Finding 3 — what the brain got right

| symbol | n | excess | hit |
|---|---|---|---|
| 2899.HK (Zijin) | 25 | +10.6% | 1.00 |
| GLD | 46 | +5.1% | 1.00 |
| SOL/USD | 133 | +4.7% | 1.00 |
| O39.SI (OCBC) | 209 | +4.2% | 1.00 |

Gold, copper, crypto majors, SG banks — the *macro-linkage* longs, which is
precisely what the knowledge graph is built to do. The graph's causal wiring is
earning its keep on the side it was designed for.

Worst long: UNI/USD (n=636, −2.4%, hit 0.12).

## Finding 4 — the stock book learned nothing because it never traded

`trades_learned = 0`. The adaptive formula has never been fitted from a single
real trade. The scorecard above is grading *advice*, not *fills*. Eight days of
advice is not eight days of trading experience, and the execution bugs mean the
two have never been connected.

## Actions

1. **Do not re-fit anything on this sample.** 4 distinct days, 62 symbols, one
   regime. The learner needs a down-week before the short-side asymmetry can be
   called real.
2. **Review the live JKS and TSLA shorts.** They are the live expression of the
   worst-scoring signal class, and JKS has never once graded a hit. This is a
   position decision, not a code change.
3. **Cap conviction on the short side** until it has a validated record —
   conviction currently makes the avoid side *worse*, not better. A one-line
   asymmetric multiplier would do it, but only after (1).
4. **Fix the stock book's execution bugs.** Until fills happen, `trades_learned`
   stays 0 and none of this becomes real learning.
5. **Fix the per-book equity journals — they already exist but are unreliable.**
   Each book is supposed to write one `mark` line a day (`_log("mark", ...)`).
   Over the 8 days since go-live: crypto 12 lines, event 9, **invest 3**, and
   the **stock book has no journal at all**. The invest book logged twice on
   2026-08-10 and not at all on 2026-08-12, so its `last_mark_day` gate is
   leaking in both directions. This is why the rebalancing analysis had to
   reconstruct equity from 9 `.tar.gz` snapshots and still got only 6 usable
   return observations. Nothing downstream — correlation, rebalancing, per-book
   Sharpe — can be measured until this is a reliable one-line-per-day record.

## When is there enough to learn from?

- Short-side asymmetry, confirmed or dismissed: needs a **down-week**, not more
  days of the same tape.
- Per-symbol reliability weights: already updating, but on 4 days of overlapping
  windows — treat as provisional.
- Cross-book correlation for rebalancing: ~2 months for a loose read, ~8 months
  to size on.
