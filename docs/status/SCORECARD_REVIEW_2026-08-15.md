# Milestone review — 11 days live, and was any of it skill?

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

*Second post-mortem since the 2026-08-04/05 reset, and the first with enough
regime diversity to ask the question the first review explicitly could not
answer. Source: the ProDesk's own `data/brain.db` (`advice_outcomes`,
`event_outcomes`), `data/journal.db`, and the four per-book journals
(`event_journal.jsonl`, `invest_journal.jsonl`, `crypto_journal.jsonl`,
`stock_journal.jsonl`), pulled live over SSH on 2026-08-15. Nothing here is
simulated or re-fit; the scorecard never deletes and neither does this
review.*

**What this document answers, specifically.** Not "did the books make money" —
whether the money made (or lost) came from the brain reading the field
correctly, or from riding a market that moved in its favour anyway. The two
look identical in a P&L number and require pulling the benchmark apart from
the call to tell apart. That is the whole method below.

---

## 1. The sample has grown up

    SCORECARD_REVIEW_2026-08-12   SCORECARD_REVIEW_2026-08-15
    9,677 outcomes                25,458 outcomes
    62 symbols                    116 symbols
    4 distinct issuance days      11 distinct issuance days
    1 market week                 spans 2026-07-26 → 2026-08-15

The 08-12 review's central caveat was *"one week is one regime — do not
conclude the short logic is broken yet."* Three more trading days in, that
caveat gets a partial answer in §3, and it is not the answer either direction
was expecting.

## 2. The market itself, over the window that matters

The books were reset to $10,000 each on 2026-08-04/05. Here is what their
reference markets actually did between then and now — not sampled, the real
closes:

| Benchmark | 2026-08-05 | 2026-08-15 | Return |
|---|---|---|---|
| SPY (US equities) | 771.43 | 776.34 | **+0.64%** |
| BTC/USD (crypto) | 64,424.02 | 63,059.09 | **−2.12%** |
| 2800.HK (HK/China) | 3.3658 | 3.2982 | **−2.01%** |
| GLD (gold) | 389.22 | 401.48 | **+3.15%** |

**This was not one rising tide.** US equities drifted up, crypto and
HK/China both fell over 2%, and gold ran hard. A book that merely held
beta in the wrong market lost money this fortnight; a book that held beta in
the right one made money without earning it. Both are visible below, in
different books.

## 3. Direction × conviction — the asymmetry is resolving, and not the way anyone assumed

    direction        conviction   n       hit     avg excess    (08-12 review, for comparison)
    long              1           1,255   0.520   +2.29%        was 0.661, n=515
    long              0           4,482   0.346   −1.51%        was 0.572, n=2,149
    avoid             1          10,329   0.602   +1.09%        was 0.401, n=4,128
    avoid             0           3,093   0.360   +1.54%        was 0.482, n=2,415
    short_or_avoid    1           2,692   0.515   +3.18%        was 0.352, n=236
    short_or_avoid    0           1,082   0.583   +0.89%        was 0.349, n=234

Read this against the 08-12 headline, which was **"the long side works; the
avoid/short side is inverted."** Seven more trading days of data move it the
other way on both counts: high-conviction **avoid** hit-rate rose from 40% to
60%, while high-conviction **long** hit-rate fell from 66% to 52%. Neither
number is settled — see the day-by-day table below — but the specific claim
"conviction is inverted on the short side" no longer holds on the full
sample. It held on four days of a rising tape, which is exactly the confound
the 08-12 review named and flagged as untested.

**Day by day, both sides are still noisy, not stable:**

    day          long hit   avoid hit
    08-01        0.74       —
    08-02        0.74       —
    08-03        0.63       —
    08-04        0.64       0.44
    08-05        0.81       0.54
    08-06        0.28       0.68
    08-07        0.14       0.65
    08-08        0.23       0.68
    08-09        0.11       0.56
    08-10        0.21       0.52

Long-side hit-rate did not degrade gently — it fell off a cliff after 08-05
(0.81 → 0.28 → 0.14 → 0.23 → 0.11 → 0.21) while avoid-side hit-rate held a
tighter, higher band (0.44–0.68). **The honest reading is that the long
model got confidently wrong for five straight days while the avoid model
stayed mediocre-but-stable** — the opposite of "shorts are broken." Whether
that is regime (the tape cooled after 08-05, consistent with §2's mixed
benchmarks) or a genuine long-side defect is not yet separable from six days
of data. Do not re-fit on this either.

## 4. What actually happened to real money — the part that separates skill from beta

This is the section the returns-only view cannot answer. Four books, each
started at $10,000 on the same reset, each with real per-trade journals now
(the 08-12 review's Action 5 — "fix the per-book equity journals" — is done;
all four write daily marks and every fill).

| Book | Equity now | Return | Its market | Market return | Verdict |
|---|---|---|---|---|---|
| 📈 trading | $10,000.43 | +0.00% | SPY | +0.64% | **Neither.** 95.7% cash, 2 positions. Not skill, not beta — absence. |
| 🏛 investing | $9,675.85 | **−3.24%** | mixed HK/US | −2.0% to +0.6% | **Negative alpha**, and traceable to named positions, not the tape. |
| ₿ crypto | $10,032.57 | +0.32% | BTC/USD | −2.12% | **Positive alpha**, small dollars, from timing not price appreciation. |
| ⚡ event sleeve | $11,096.18 | **+10.96%** | none (2-day, per-name) | — | **The strongest evidence of real edge in the system**, with a real caveat (§4.4). |
| **Blended** | **$40,805.03** | **+2.01%** | — | — | Net positive despite 2 of 4 reference markets falling. |

### 4.1 The trading book: still not a data point

Unchanged diagnosis from STATE_OF_THE_SYSTEM §2: 95.7% cash, one AAPL share
(§4.23's ten-sided-die fill) and one USO share. A flat book proves nothing
either way — it has barely traded. This return is not evidence of anything.

### 4.2 The investing book: −3.24%, and now provably not *only* the shorts

The book holds 7 positions. Unrealised P&L, per position:

    TSLA    short   −$62.11   (largest single loser)
    PRX.AS  long   −$102.24   (largest single loser)
    PDD     long    −$89.34
    JKS     short   −$29.77
    2331.HK long    −$26.55
    INTC    short   −$17.37
    2097.HK long     +$3.62

**Two things are true at once, and only one of them was previously
documented.** JKS and INTC are exactly the two shorts the scorecard's own
grading has independently flagged: JKS short_or_avoid now has **332 graded
calls and a 0.0 hit rate** (n up from 48 on 08-12); INTC short_or_avoid has
**252 graded calls, 0.0 hit rate, missed +10.7% it should have caught**. Two
independent measurements — the advice grader and the actual position P&L —
agree these two calls are wrong, which is stronger evidence than either alone.

But **PRX.AS and PDD are the two largest dollar losses in the book, and
neither is a short.** These are ordinary long-side thesis calls that have
simply not worked, and nothing in STATE_OF_THE_SYSTEM or the 08-12 review
names them. The −3.24% return is not "the short logic is broken" as a
complete explanation — it is roughly half named-and-corroborated short
misses, half undiagnosed long-side drag. **This is a new finding, not a
restatement of an old one**, and it belongs in the open-defects list, not
folded into the short-side story where it doesn't fit.

### 4.3 The crypto book: small, real, and not what it looks like

+0.32% while BTC fell 2.12% looks like stock-picking skill. It mostly is not.
The book has run five small tactical HODL round-trips since reset, each
sized at roughly 0.1–0.2% of the book, entering on a signal and bear-exiting
on the same rule (`winter: BTC < 100d MA` + a second confirming signal):

    cycle            realized pnl
    08-04 → 08-05    +$16.84
    08-07 → 08-09    +$20.93
    08-13 → 08-15    −$4.45  (open as of this review, net loss on exit)

Net **+$33.32** realized across three completed round-trips, against a
$10,000 book — genuinely tiny in dollars. What it demonstrates is not "picked
the right coin" (BTC/ETH/SOL all moved together, as they always do) but
**correctly timing exposure into a falling market** — in cash 5 of every 6
observed days, in the market only when the bear-exit rule said to be. That is
real, measured, and the right kind of skill for a bear-mode design to show.
It is just not the story the headline number implies at a glance.

### 4.4 The event sleeve: +10.96%, real, and the best-corroborated result in the system — with one asterisk

This is realized P&L, trade by trade, not a mark-to-market illusion:

    cycle                  legs                 realized pnl   result
    08-04 → 08-06   USO / XLE / 1398.HK        −$190.54       0 of 3 won
    08-06 → 08-08   MP / TAN / JKS             +$476.83       3 of 3 won
    08-10 → 08-12   ASML / TSM / NVDA           +$31.38       2 of 3 won
    08-12 → 08-14   NVDA / AMD / 000660.KS     +$556.45       3 of 3 won
    08-14 → open    NVDA / AMD / JPM           +$222 (unrealized)

**8 of 12 completed legs won (67%)**, and the realized total across four
completed cycles is **+$874.12** before the currently-open cycle's unrealized
gain. This is not one lucky trade: it is four independent 2-day windows,
different names each time, net positive in three of four. It is also
independently corroborated by a *different* measurement — `event_outcomes`
grades every fresh-shock event the brain tags, and impact_sign=+1 events have
hit 60–89% daily across this same window (§ STATE_OF_THE_SYSTEM's
`event_outcomes` table). Two separate systems, measuring two different
things (realized trade P&L vs. graded event predictions), point at the same
conclusion: **catching a fresh positive shock is the one thing this brain
reliably does well.**

Notably, one of the sleeve's winners was **JKS long, +7.8%**, the same
session the investing book was compounding losses on **JKS short**. Same
symbol, same brain, opposite conviction in two different books, and the long
call was right. That is not a contradiction to paper over — it is what
"four independent policies trade off one shared world model" is supposed to
produce when they disagree, and here the disagreement resolved in favour of
the book that was right. It also means "the brain doesn't understand JKS" is
the wrong frame; more precisely, **the short/avoid read on JKS is
specifically miscalibrated while the long read on the same name, from the
same underlying signals, was not.**

**The asterisk, and it is load-bearing.** STATE_OF_THE_SYSTEM §4A already
flags this book's risk/reward as structurally inverted: `expected_move`
≈0.3–0.5% against a 10% hard stop, roughly 32:1, needing ~97% accuracy to
break even on a bad leg. A good four-cycle run does not retire that
math — it means the bad leg has not landed yet. One stopped-out position
sized like these ($3,491 notional, a third of the book) at −10% is a
**−$349 loss, wiping out the entire 08-06→08-08 cycle's gain in one leg.**
The realized record above is genuinely encouraging and genuinely fragile at
the same time; both are true, and the second one is not new information —
it was already known and simply hasn't been asked to prove itself.

## 5. Missed opportunities — updated, and the leaderboard has changed

    symbol   call             n     avg excess   hit
    MP       avoid            956   +8.4%        0.00   (still the largest cumulative miss)
    CRWV     avoid            565   +10.0%        0.37   (new — not in the 08-12 review)
    CRWV     short_or_avoid   216   +11.2%        0.19   (new)
    INTC     short_or_avoid   252   +10.7%        0.00   (new, and live — see §4.2)
    ALB      short_or_avoid    95    +9.5%        0.00
    NVDA     short_or_avoid    83    +8.4%        0.01
    JKS      short_or_avoid   332    +6.5%        0.00   (live — see §4.2)

**CoreWeave (CRWV) is the single biggest new finding in this review.** It did
not appear in the 08-12 miss table at all — it has since accumulated 565
`avoid` gradings and 216 `short_or_avoid` gradings, both wrong the large
majority of the time, both missing double-digit excess returns. This is not
a one-off: the volume (781 combined gradings) means the graph has held a
confidently bearish read on this name for most of the two-week window while
it ran. Worth the same treatment MP already got — understanding *why* the
graph reads it bearish, not just noting that it's wrong.

**The other side of the ledger also has a new, harder-to-ignore entry.**
`UNI/USD` long: **n=1,096** (up from 636), hit-rate **6.3%** (down from
12%), avg excess **−7.1%** (worse than −2.4%). This is no longer a
hypothesis needing more data — it is the largest single sample in the
entire outcome table, wrong 94% of the time, and it has gotten *worse*, not
better, as more days accumulated. Every other finding in this review carries
a "needs more regime diversity" caveat; this one does not. **UNI/USD long is
a confirmed defect, not a suspected one, and belongs in STATE_OF_THE_SYSTEM
§4A rather than waiting for the next review to say so again.**

## 6. What is confirmed working, on samples too large to be luck now

    symbol      n     avg excess   hit
    2899.HK   255    +6.4%        0.73
    GLD       192    +6.0%        1.00
    O39.SI    287    +3.7%        1.00
    LINK/USD  179    +2.1%        0.84
    SOL/USD   170    +4.1%        1.00
    ETH/USD    75    +1.9%        1.00
    PANW       53    +7.7%        1.00

Gold, Zijin (copper/gold miner), a Singapore bank, crypto majors, a US
cybersecurity name — the same "macro-linkage longs" story the 08-12 review
told on samples of 25–209 now holds on samples of 53–287, several with a
perfect or near-perfect hit rate. **This is the part of the brain doing
exactly what it was designed to do**, and the larger samples make it a
meaningfully stronger claim than it was three days ago.

One correction worth naming plainly: **PANW appears in this review's winners
list as a `long` call (n=53, hit 1.00) and appeared in the 08-12 review's
*losers* list as an `avoid` call (n=33, hit 0.00, missed +7.1%).** The brain
changed its own read on the same name between the two reviews and the new
read was right. That is either adaptive correction working as intended, or a
system that flips its view often enough that the win is partly a coin landing
right — the sample (53 vs 33) is too small on either side to tell which, and
it is flagged here rather than quietly counted as a clean win.

## 7. The direct answer to "was the gain skill or the market rising"

**No, the blended +2.01% was not the market rising.** Two of the four
reference benchmarks fell over the same window (BTC −2.1%, HK −2.0%); one was
flat-to-up (SPY +0.64%); the brain's blended return exceeded all of them. But
that headline number is not evenly earned, and pulling it apart by book gives
a more honest, more specific picture than "the brain is good":

- **Real, corroborated, repeatable-so-far skill**: the event sleeve's
  fresh-shock catches (§4.4) and the macro-linkage long book (§6), each
  independently confirmed by two different measurements (realized P&L +
  graded advice, or graded advice + graded events).
- **Real but tiny skill**: crypto's bear-mode timing (§4.3) — correct
  direction, correct mechanism, dollar amounts too small to matter yet.
- **A named, corroborated skill deficit**: JKS and INTC shorts (§4.2),
  where advice-grading and live position P&L independently agree the model
  is wrong, plus a newly-discovered separate long-side drag (PDD, PRX.AS)
  that is not yet explained by anything in this project's failure register.
- **Absence, not skill or beta**: the flagship trading book, still
  structurally unable to act on 12 of its 13 confidence-clearing calls
  (§2 of STATE_OF_THE_SYSTEM — unchanged).
- **A confirmed, large-sample defect that graduated from hypothesis to
  fact this review**: UNI/USD long (§5).

The honest one-line summary: **the brain's causal/macro reasoning is earning
real, corroborated edge on longs and fresh-shock catches; its avoid/short
calibration is inconsistent rather than "inverted" as previously thought,
with at least two named, live, wrong short positions costing real money right
now; and the system's realised profit is concentrated almost entirely in the
smallest, most fragile book, sitting on top of a known 32:1 risk/reward ratio
that has not yet been tested by a losing leg.**

## 8. Actions

*Updated 2026-08-15, same day, after acting on the first four.*

1. ~~Review the JKS and INTC shorts in the investing book now~~ — **DONE.**
   Both closed on the live book: JKS realised −$29.77, INTC realised −$17.37.
   Journalled in `data/invest_journal.jsonl`.
2. ~~Investigate PDD and PRX.AS specifically~~ — **DONE, not a bug.** Both are
   ~10-day-old positions in a book with an explicit 6-month horizon and a 10%
   hard stop (PDD −6.0%, PRX.AS −7.2%, neither near the stop). Normal noise
   for this book's mandate, not an undiagnosed defect. **Cue to revisit
   PRX.AS**: crosses −8.5%, or `daily_manage` drops it from `strat.theses`
   on its own — see STATE_OF_THE_SYSTEM §4B.
3. ~~Move UNI/USD long from "unvalidated" to a stated defect~~ — **DONE, and
   fixed.** Root cause: no graph node, so none of the causal-chain haircuts
   ever corrected its formula-only score. `brain/adviser.py`'s
   `CONFIRMED_MISCALIBRATED` set now zeroes it before ranking; deployed and
   verified (commit `98a58a6`). **Cue to remove the override**: real graph
   node + `calibration.py` verdict at n≥20 — see STATE_OF_THE_SYSTEM §4B.
4. ~~CRWV deserves the same review MP already got~~ — **DONE.** Found the
   mechanism: a curated edge, `ai_circularity → crwv` (−0.5, "the financed
   party takes the direct hit" — the Nvidia/CoreWeave circular-financing
   thesis), plus a 40% circular-financing haircut. Deliberate, not stale —
   but never calibrated. **Cue**: `ai_circularity` needs n≥20 realised-return
   observations before `calibration.py` can issue a verdict on this edge.
5. **Do not treat the event sleeve's +10.96% as proof its risk/reward is
   fine.** The 32:1 asymmetry flagged in STATE_OF_THE_SYSTEM §4A is
   unrelated to whether the last four cycles happened to win. **Cue**:
   revisit at the first 10% stop-out on any leg (compare against the +$874.12
   realised so far), or at 15 completed cycles (currently 4) — whichever
   comes first.
6. **The long/short conviction asymmetry is still not settled** — it
   reversed direction between the two reviews on the same underlying
   mechanism. **Cue**: a genuine down-week for US equities, defined as a
   5-trading-day cumulative SPY return ≤ −3%. Nothing in the sample so far
   has had one — SPY has been flat-to-up throughout.

## 9. When is there enough to learn from — revisited, with dates

The 08-12 review set three bars. Status against each, with concrete cues
rather than "needs more data":

- **Short-side asymmetry, confirmed or dismissed**: cue is the SPY ≤ −3%
  down-week defined in Action 6 above. Crypto and HK/China *did* have a down
  window in this data and the avoid-side hit rate held up reasonably (§3) —
  one piece of the needed evidence, not all of it; US equities specifically
  still hasn't been tested.
- **Per-symbol reliability weights**: 11 distinct issuance days so far
  (started 2026-07-26). Treat as provisional until 20–30 distinct days —
  roughly **2026-09-04 to 2026-09-14** at the current pace.
- **Cross-book correlation for rebalancing**: dated from the 2026-08-05
  reset — a loose read from **~2026-10-05** (2 months), safe to size capital
  allocation on from **~2027-04-05** (8 months).
