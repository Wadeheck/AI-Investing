# Small-Cap Short Models — Steven Dux

Source: Chart Fanatics podcast, second episode with Steven Dux ($27K → $50M+ career, verified prop/live
track record, 2025 alone reportedly included a ~$7M and a ~$10M single trade). Covers three related but
distinct short-side small-cap strategies: **Gap Up Short**, **Bounce Short**, and **First Red Day**.
Digested in full; kept deliberately detailed — this trader's entire edge is explicitly built from ~10
years of hand-tracked statistics on precise numeric filters (market cap, float, volume, dollar-block
size), so the numbers themselves are the content, not supporting color.

Companion docs: [FABIO_VALENTINO_ORDERFLOW_MODEL.md](./FABIO_VALENTINO_ORDERFLOW_MODEL.md),
[GALA_TRADES_PRICE_ACTION_MODEL.md](./GALA_TRADES_PRICE_ACTION_MODEL.md),
[MARCO_TRADES_DA_VINCI_LIQUIDITY_MODEL.md](./MARCO_TRADES_DA_VINCI_LIQUIDITY_MODEL.md). This is the
most explicitly **statistics-first / short-only / small-cap-equity-specific** model of the four — built
entirely around supply/demand exhaustion and crowd psychology in illiquid names, not order flow or
liquidity-sweep pattern recognition. It's also the only one of the four with an explicit, stated
research methodology (10 years of manual spreadsheet tracking) rather than purely discretionary pattern
recognition.

---

## 1. Core Philosophy

- **Every strategy must be built on a mechanism that is either logically/statistically grounded or
  psychologically grounded (ideally both).** Explicit stated design principle: "make sure that whenever
  you are designing a strategy, it's fundamentally tied to either" logic/statistics or human psychology —
  a criterion that "doesn't make logically or psychologically sense" is flagged as a strategy unlikely to
  work, regardless of how well it backtests superficially.
- **All three strategies are explicitly short-only and small-cap-only.** Explicitly states "shorting has
  to be very precise or you are taking a huge amount of risk and potentially lose more than 100%" —
  short-selling's asymmetric risk profile (uncapped loss, capped gain) is treated as the reason precision
  and statistical filtering matter more here than they might for a long strategy.
- **Statistics are self-tracked by hand, not automated.** ~10 years of manually logging every relevant
  trade/setup into spreadsheets (market cap, float, push percentage, volume-on-day, sector) — explicitly
  not a scanner/software-automated process. The stated payoff of this manual tracking: for each strategy
  he can state (a) how many times per year it occurs, (b) win rate, (c) average reward (fade %), which
  lets him simulate expected annual P&L in advance.
- **Explicit stated psychological benefit of pre-simulating expected annual results**: "it eliminates
  your emotion from being FOMO" — because you already know your statistically expected win rate and
  reward per setup type, you're not tempted to chase or deviate mid-year; the standard is "am I on track
  with the simulated result," not "did I just miss a big move."
- **Every setup class requires a plausible human-psychology mechanism**, not just a numeric coincidence
  — e.g. Bounce Short is explicitly grounded in "people trapped at a price for months, given a chance to
  exit near breakeven, sell immediately" behavior, not merely "price often reverses at old resistance."

---

## 2. Universal Filters (apply to all three strategies unless noted)

- **Initial market cap: $1M–$100M** (First Red Day is the one exception — see Section 5, its market cap
  ceiling can extend to ~$200M, occasionally further case-by-case).
- **Float: $1M–$50M shares**, with explicit internal sub-bands used to calibrate expectations:
  - **1M–2M shares = very low float**
  - **2M–5M shares = mid float**
  - **5M–10M shares = large float**
  - **10M–20M+ = these setups occur much less often in this band** ("we don't run into these type of
    play that much") — the strategies still technically work here but are lower-frequency.
  - Float **above ~50M shares is explicitly stated as untradable ~99% of the time** for these models.
- **Volume banding** (used to judge liquidity/crowding, distinct from float): tracked in bands of
  1–10M, 10–20M, 20–40M as generally tradable; **pre-market volume exceeding 50M is an explicit red
  flag** — because the typical pre-market-to-full-day volume ratio runs **~1:5 to 1:10**, 50M pre-market
  implies an estimated ~250M–500M full-day volume, which against a sub-$100M market cap creates a crowd
  so large it becomes "very difficult" to trade the short reliably (too many uncoordinated participants/
  "a lot of algos playing games").
- **Session timing**: the large majority of daily volume concentrates **9:30–11:30am** (roughly
  30–35% of the entire day's volume trades before 11:00am specifically). After ~11:00am volume
  meaningfully dries up. Practical implication stated: if a name is still in mass consolidation by then,
  an afternoon short becomes viable specifically because volume has thinned and any crack triggers a
  chain reaction among traders now stuck at the top.
- **Sector exclusions — hard rule, all three strategies**:
  - **Biotech**: explicitly measured to reduce win rate by **~20–30%** based on his own tracked sample
    (~300–500 biotech tickers traded, net profit only ~$1–2M across that entire sample despite the
    volume of trades) — states he now deletes every biotech name from his scanner on sight without
    further analysis, calling the mental energy required "just not worth it."
  - **Energy sector**: also explicitly excluded, no further elaboration given beyond "make sure to avoid
    that sector as well."
  - **Chinese stocks**: excluded specifically due to **halt/liquidity risk** — cites personal experience
    of tickers with intraday volume under ~30M getting halted with thin level-2 depth, then reopening
    50–100%+ against the position with no ability to exit. Explicitly states he has personally taken this
    kind of loss "maybe five" times in his career (2–3 catastrophic, ~20–30 more moderate ~100%-of-
    position losses from the same failure mode) — the exclusion is drawn directly from realized losses,
    not theoretical caution.
- **Extension filter**: avoid names that are already extremely overextended (e.g., moved 1000%+ from
  origin) — the stated soft threshold is that moves in the **~200–500% range are the ones actually worth
  targeting**; beyond that the risk/reward calculus degrades (though not a hard exclusion the way the
  sector rules are — "maybe that's something to consider" language, i.e. case-by-case).

---

## 3. Strategy 1 — Gap Up Short

### Definition / Setup

A stock gaps up significantly at the open — commonly 70–1000%+ — and the strategy is built around
shorting the eventual failure/breakdown of that gap-driven spike, once specific volume and consolidation
conditions confirm.

### Precise Criteria

- **Gap size threshold: must be above 100%** at the open to qualify at all.
- After the open, expect an initial spike, then **consolidation**. The consolidation period itself
  becomes the reference structure — this is where sizing begins, not at the initial spike.
- **Volume-versus-float banding drives expected push % and dictates entry/sizing timing**:
  - **Float 1M–2M (very low float)**: expect the largest push percentage, tracked average **~30–35%**
    push from open before the stock tends to consolidate. Approach: **wait for ~1 hour of consolidation**,
    then begin sizing in; add to a **full position specifically when the stock shows its first
    weakness/breakdown** off that consolidation (roughly the 10:00–11:00am window). Stop-loss sits above
    the high of that consolidation range.
  - **Float 5M–10M**: expect a smaller push, tracked average **~20–25%**. Approach: **wait until ~11:00am**,
    take a **partial position**, then add to full size once momentum visibly shifts (a **~3–5% crack**
    off highs). Same stop-loss logic (above the consolidation).
- **Average fade/reward once triggered: ~26% decline from the intraday high** (this is the general
  average cited across the strategy, used for R:R math) — practically targeted a bit conservatively at
  ~24–25% to build in a margin of safety.
- **Resulting typical risk:reward: roughly 1:3.5–1:4** (a ~7% average risk against a ~24–26% average
  reward).
- **Volume-estimate confirmation gate, applied before taking any entry**: pre-market volume is used to
  project full-day volume (via the ~1:5–1:10 ratio referenced above); by ~11:00am, actual traded volume
  should represent roughly **~30% of the projected full-day estimate** for the setup to be considered
  "on track" and tradeable. All criteria — float band, push %, consolidation, and this volume-tracking
  check — must line up together; a partial match is explicitly not sufficient to take the entry.
- **Crowding exclusion, specific numeric rule**: if pre-market volume alone exceeds ~50M shares, this
  strategy specifically is deemed largely untradable for that name that session (see Section 2) — the
  crowd is too large and unpredictable for the consolidation-breakdown logic to hold. Worked example
  given (a real ticker, "BIRD"): traded ~70M shares pre-market and squeezed straight through what would
  otherwise have been the consolidation/short zone — cited explicitly as a "this is one of the examples
  you do not want to use gap up short" case.
- **Float-conditional variants for lower-float names, more granular**:
  - **Float under ~2M ("nanofloat")**: if volume rotates the float **more than ~15 times**, treat as
    dangerously crowded regardless of the standard float-band expectations; in this case, wait for an
    explicit signal — specifically a **~50% pullback from the top followed by a bounce** — before
    entering, rather than shorting the initial breakdown directly.
  - **Float ~3M–5M**: size in, but not full size, against the pre-market high.
  - **Float ~7M–8M (higher end of the workable range)**: can size more aggressively against the
    pre-market high — cited at **~50–60% of full intended position size** directly at that level, since
    higher float reduces squeeze/crowding risk somewhat.
- **Frequency / win rate / reward, as tracked over ~10 years (after excluding biotech/energy/China)**:
  **~50–70 occurrences per year**, **win rate ~75%+**, **average reward ~26%** fade from the intraday
  high once triggered.

---

## 4. Strategy 2 — Bounce Short

### Definition / Setup and Psychological Mechanism

Explicitly grounded in a specific crowd-psychology mechanism, distinct from Gap Up Short's pure
supply/demand-crowding logic:

1. Look back at the **1-year chart** for a stock that had one large historical volume spike (e.g. ~30M
   shares on a single day) that pushed price to some level (e.g. from ~$1 to ~$5), then **dropped and
   stayed flat for an extended period (ideally ~2 months)**. This creates a large cohort of traders
   trapped near that high price, sitting on losses, who have been waiting to get out near breakeven.
2. **The new gap-up event (a fresh 100%+ gap, e.g. from $2 to $4.50) brings price back up toward that old
   trapped-supply price** ($5 in the example). Because so many holders are simultaneously near breakeven
   for the first time in months, **the human-psychology default is to sell immediately** to lock in the
   escape — this creates concentrated, correlated selling pressure exactly at that old resistance price,
   which the trade is built to short into and ride down.
3. Explicit quote on the mechanism: "majority [of trapped holders'] first reaction by human psychology is
   to sell... so once you sell you create a selling pressure and I'm... writing your [sic, "riding the"]
   selling pressure all the way down."

### Precise Criteria

- **Price floor: must be above $3.** Explicitly stated to apply to all three strategies in this doc, but
  specifically re-emphasized here — below $3 "becomes very difficult" and statistically degrades the
  edge.
- **Market cap ceiling for this strategy specifically: under $200M.**
- **Float ceiling for this strategy specifically: under $50M.**
- **Minimum single-day historical volume spike to qualify the trapped-supply zone: 100M+ volume on the
  reference day** (the day that created the trapped cohort), landing near a specific consolidated price.
- **"Dollar block" calculation — the central quantitative tool for this strategy**:
  - Rather than summing all historical volume indiscriminately, isolate specifically the volume that
    transacted **at/near the consolidated trapped price** (e.g. use a 30-min or 1-hour chart to identify
    how many of the total shares actually traded in the ~$5 zone, as opposed to volume that occurred
    while price was still below $5 on the way up).
  - **Dollar block = (shares traded at that consolidated price) × (consolidated price)** — e.g. 25–28M
    shares × $5 ≈ **$110M–$140M**.
  - **Stated ideal threshold: dollar block should be ≥ $150M** for the setup to be considered high-
    quality (values around $130M–$140M are workable but sub-ideal).
- **Volume-ratio confirmation, the entry-quality gate**:
  - Use pre-market volume × ~10 to estimate the day's total volume (same ratio heuristic as Gap Up
    Short), e.g. 3M pre-market → ~30M estimated day volume.
  - **Explicitly adjust this raw estimate downward, because the strategy anticipates its own selling
    pressure suppressing buy-side participation**: if the stock is expected to open and immediately drop
    15–20% (the trapped-holder selling), prospective buyers who would otherwise have driven volume are
    deterred — the raw volume estimate should be **cut by roughly 50–80%** to reflect this (e.g. 30M raw
    estimate → ~10–15M realistic estimate).
  - **Compute the ratio of (adjusted day-volume estimate) : (trapped dollar-block volume, e.g. 25M
    shares)** — this ratio is the primary sizing signal:
    - **~1:1 ratio → reduce size.**
    - **~2:1 ratio → increase size.**
    - **Ratios as extreme as 10:1 have been observed** — cited example: a GME-style setup with a ~10:1
      ratio that "instant crashes 50%" at the open, on which he personally made **~$1.5M in ~15 minutes**
      (an early-career trade, cited as the extreme upper bound of what this setup can produce, not a
      typical outcome).
  - Explicit framing: **the ratio is a direct proxy for how much "emotional"/forced selling volume the
    market can realistically absorb** — a bigger ratio means more conviction because it implies a faster,
    more violent ("max pain") move once triggered.
- **Position-sizing hard caps, specific to this strategy**: **do not exceed 10% of the float, and do not
  exceed 1% of the day's volume** — explicitly stated as a lesson learned from personal experience at
  larger account size: oversizing beyond these thresholds risks breaking the underlying supply/demand
  mechanism the strategy depends on (you become a large enough participant that you're effectively
  trading against/disrupting your own edge). At larger size, explicitly states the need to **cover
  gradually along the way down rather than holding the full position to the close**, specifically to
  "give the supply back" to the market rather than absorbing all of it himself.
- **Entry timing/sizing rule**: the closer the entry can be placed to the actual historical consolidation
  price itself, the larger the size that can be taken — because proximity to the well-defined
  consolidation reference directly reduces risk (tighter, more defensible stop placement).
- **Two named sub-variants, with different win-rate/fade profiles**:
  - **Type 1 — "gapped-in-close" variant**: stock gaps up directly into the old consolidated price with
    relatively low pre-market volume (e.g. 3–5M) already traded before market open. **Higher win rate**
    than Type 2. Fade pattern: **tends to go straight down** once triggered, with an average fade of
    **~75% of the full move's range** (measured from the very top of the range).
  - **Type 2 — "parabolic climb" variant**: stock did not move materially in pre-market, then builds
    volume from the open and climbs parabolically up toward (and slightly through, potentially even
    taking out) the old high before reversing. **Lower win rate than Type 1.** Fade pattern: tends to show
    a **bounce first, then fade**, with an average fade of only **~50% of the range** (roughly half of
    Type 1's typical fade) — explicitly, the maximum expected reward is smaller for this variant.
- **Frequency / win rate, as tracked**: **~30 occurrences per year**, **win rate ~80–85%** — notably
  higher win rate than Gap Up Short, attributed to the added psychological-mechanism confirmation layer
  (trapped-holder selling) on top of the pure volume/float filtering.

---

## 5. Strategy 3 — First Red Day

### Definition / Setup

Shorting the first red/down day after a sustained **multi-day parabolic run** — explicitly stated to be
governed by much stricter criteria than the commonly-known retail version of "first red day," because
"if you don't avoid [the failure modes], the first red day will become [your] first losing day." The
explicit tradeoff acknowledged: this setup offers by far the largest position-size/dollar-profit ceiling
of the three strategies (uncapped, since it isn't governed by the float/volume percentage caps used in
Bounce Short), but is also the hardest to time correctly and carries the largest tail risk if mistimed
(a short into continued parabolic upside can produce >100% losses).

### Precise Criteria

- **Market cap ceiling: this strategy's exception to the universal $100M cap — extends up to ~$200M
  typically**, occasionally beyond case-by-case (cites CRCL as an example of a much larger-cap instance
  that still fit the pattern logic, discussed further below).
- **Adjusted market cap for stocks that have already run**: explicitly notes that "initial" market cap
  must be back-calculated by dividing the *current* market cap by the cumulative move multiple — e.g. a
  stock currently at $600M market cap that has moved from $1 to $10 (10x) has an **initial market cap of
  $60M**, which is the number actually used against the $200M-ish ceiling, not the current inflated
  figure.
- **Multi-day run structure requirement — three named sub-conditions, ALL required together**:
  1. **Parabolic price action** — price trend visibly accelerating, not just steadily rising.
  2. **Consecutive green days with volume increasing day-over-day** (either matching or exceeding the
     prior day) — **minimum 3 consecutive green days**, with **no red or flat day breaking the sequence**
     (a red/flat day in the middle **resets the counter to zero**; the 3-day count must restart from
     scratch afterward). Explicit rationale: this pattern specifically reflects sustained, escalating
     retail emotional chasing day after day — a broken sequence indicates the emotional momentum has
     already released/reset, invalidating the setup's premise even if price is technically still near
     highs.
  3. **Minimum cumulative range/gain requirement, contingent on how many days the run has taken**:
     - **3+ consecutive green days → minimum 300% total range** from the initial breakout point.
     - **Exception: a 2-day run is acceptable only if the cumulative range is ≥ 1000%** (explicitly far
       higher bar for a shorter run) — cited his own DWAC trade as a real example of this 2-day/1000%+
       variant.
  4. (Implicit 4th check, stated separately but functionally part of qualification): **the actual dollar
     volume traded (price × shares) on the latest green day must exceed the prior day's dollar volume**,
     even in cases where raw share volume appears to be declining — i.e. the qualifying "volume increase"
     criterion is properly measured in **dollar-traded terms**, not raw share count, since a declining
     share count at meaningfully higher prices can still represent rising dollar volume.
- **Multi-day runners with red days "reset and continue" are explicitly flagged as a different, larger
  opportunity class**: a stock that shows repeated reset-and-continue cycles (three days up, one red
  reset day, three more days up, etc.) is noted to often run to substantially larger absolute gains (his
  example: $2 to $28, "still got room to go up to maybe in the hundreds") precisely *because* the red
  days function as periodic emotional/positional rebalancing that lets the run continue further than a
  single uninterrupted 3-day burst would — this is presented as a reason such tickers should NOT be
  shorted as a First Red Day candidate on an early reset, since the reset itself is evidence the move
  isn't over.
- **Long-term chart-shape preference**: multi-day runners that emerge from a chart that had been in a
  sustained long-term downtrend (rather than one that had been basing/flat) are noted to statistically
  tend to run further before the eventual reversal — an added qualitative filter layered on top of the
  numeric criteria.

### The "Dollar Block Ceiling" — Predicting *When* the Top Occurs

This is presented as the strategy's core innovation for solving the hardest problem in the setup: timing
entry precisely enough to avoid getting caught shorting into continued upside (explicitly described as
his original motivating question: "how to really precisely capture the top").

- **Method**: bucket historical multi-day-runner samples by **initial market cap band**, and for each
  band, calculate the **dollar amount transacted at the point where the run historically topped out and
  reversed** (essentially the same dollar-block concept as Bounce Short, but applied prospectively/
  predictively rather than to a single historical consolidation).
- **Stated empirical finding, from "hundreds of samples"**: names within the same initial-market-cap band
  consistently top out at **similar dollar-traded totals**, even though their per-share prices differ —
  i.e. the ceiling is a function of *aggregate dollar volume the retail/momentum crowd can pour in*, not
  of price level itself.
- **Approximate stated bands** (illustrative, not exact universal constants — presented as his own
  tracked rules of thumb):
  - **Initial market cap ~$100M → tops out around ~$3B in cumulative dollar volume traded.**
  - **Initial market cap ~$200M → tops out around ~$5B–$10B in cumulative dollar volume traded.**
  - **True IPO-scale names (e.g. cites CRCL, 2025) with an initial market cap around $3–3.5B → dollar
    block ceiling scales up to roughly $30B.**
- **Practical use, day-by-day during the run**: each morning, use the pre-market-volume × ~10 heuristic
  (same ratio method as the other two strategies) to project that day's likely cumulative dollar volume,
  and compare it against the band's known historical ceiling. If the projected total for the day falls
  well short of the ceiling, **explicitly do not engage that day** ("turn off the computer") — the
  reversal is not statistically likely to occur yet. Only actively watch/trade the session once the
  day's projected cumulative dollar volume is approaching the historical ceiling for that market-cap
  band.
- **Explicit stated purpose of this method**: prevents the common failure pattern of "taking losses on
  the way up and making profit on the way down" (i.e. net-neutralizing an otherwise-good setup by
  repeatedly shorting too early during the still-active parabolic phase) — the dollar-block ceiling is
  specifically what lets him skip the early days of a run entirely rather than nibbling at premature
  shorts.
- **Explicit reward-side asymmetry acknowledged**: even on a "massive crash," the maximum realistic
  reward on a First Red Day short is **~50%** (bounded, since the stock is being shorted near its top,
  not compared against a much larger prior range) — versus the essentially uncapped upside risk the
  position carries if timing is wrong. This asymmetry is the stated reason precise timing (via the
  dollar-block method) matters more here than in the other two strategies.

### Entry Mechanics

- **Do not short aggressively on the day the dollar-block ceiling is first approached.** Momentum
  "doesn't likely to shift" while volume is still extremely high — cites having been caught by a fakeout/
  continuation in this exact situation previously.
- **Staged entry, explicit fractional rule**: on the day the ceiling is approached/reached, take only
  **~1/4 of the intended full position** at that point (at/near the highs). This partial serves primarily
  to **improve average entry price** — because, per the tracked statistics, a clean bounce/retest at the
  open essentially never actually occurs in his sample, so waiting for a "perfect" bounce-based entry to
  size in more heavily is not realistic for this specific setup (contrast with Bounce Short, where waiting
  for the bounce specifically *is* the core mechanic).
- **Second/main entry on the following day** ("the second day tells you the stock is going to drop"),
  justified by the same volume-ratio logic used in Bounce Short: pre-market volume on this second day is
  expected to be dramatically lower than the prior (topping) day's volume — worked example: prior day
  traded ~200M total volume, next-day pre-market trades only ~5–7M, producing an estimated **~3:1 to 4:1
  ratio** against the prior day's volume, which is read as high-confidence confirmation that demand cannot
  compete with the prior day's resistance-zone supply. **Enter the remaining ~3/4 of the position** at/
  near this point.
- **Stop-loss placement**: above the consolidation/resistance zone (not above the exact spike wick if one
  occurred) — same logic as Gap Up Short and Bounce Short's stop placement.
- **Stated realized risk range for the trade once triggered**: typical intraday range on the trigger day
  runs **~10–15%**, with a **win rate as high as ~90%** on properly-qualified setups — explicit stance
  that this favorable risk:reward-vs-win-rate combination justifies sizing up aggressively even on setups
  that fail to reach full resistance before breaking down ("I have seen some tickers that push into the
  resistance but still fail. So the winning percentage is extremely high. It's worth the risk").
- **Frequency**: **~5–10 occurrences per year** — by far the rarest of the three setups, but explicitly
  the one with **no stated position-size ceiling** (contrast Bounce Short's hard 10%-of-float/1%-of-
  volume caps) — this is the setup responsible for his largest single-trade outcomes (cites a real ~$7M
  realized trade, discusses that with different sizing/liquidity constraints it could theoretically have
  reached ~$12–13M, but at that size the position itself begins moving the ticker, forcing him to
  eat an extra ~5-6% of slippage/loss on unwind even on an otherwise-correct trade — an explicit,
  concrete statement of size-based execution decay at the top of his own trading scale).

---

## 6. Cross-Strategy Comparison Table (as stated)

| | Gap Up Short | Bounce Short | First Red Day |
|---|---|---|---|
| Market cap | $1M–$100M | Under $200M | Under ~$200M (occasionally beyond, e.g. CRCL) |
| Float | $1M–$50M | Under $50M | Not explicitly float-capped |
| Min. price | >$3 | >$3 | >$3 (implied, universal rule) |
| Frequency/year | ~50–70 | ~30 | ~5–10 |
| Win rate | ~75%+ | ~80–85% | up to ~90% |
| Avg. reward/fade | ~26% | ~50–75% of range (variant-dependent) | ~50% max (bounded) |
| Position-size cap | Implicit via float/volume bands | Hard: ≤10% float, ≤1% day volume | No stated ceiling |
| Typical max realized size (personal) | ~$1M–$1.2M | ~$1M–$1.2M | Millions to tens of millions |

(GME/AMC-style hyper-hyped tickers are explicitly called out as a rare exception class occurring only
~2–3 times/year, capable of exceeding the "typical" size/reward figures above by a wide margin — the
~$1.5M/15-minute GME-style trade under Bounce Short is this exception, not the strategy's norm.)

---

## 7. General Risk/Sizing Principles (stated across all three)

- **Size scales with statistical conviction signals, not just conventional confidence**: explicitly
  described sizing up when the Bounce Short volume ratio is higher (2:1 → size up; 10:1 → size way up),
  and sizing down when a name only barely clears a threshold (e.g. price at $2.80–2.90 barely above the
  $3 floor → reduce size specifically because it "barely touches the criteria").
- **All criteria must align simultaneously; partial matches are not traded.** Stated explicitly for Gap
  Up Short ("all the criteria has to line up together for me to take an entry") but the same logic is
  implicit across all three — no single strong factor (e.g. a great dollar-block ratio) overrides a
  disqualifying filter elsewhere (e.g. wrong sector, price under $3, float out of band).
- **Execution/slippage decay at large size is explicitly acknowledged as a real, load-bearing constraint**
  on strategy design, not just a footnote — the described need to unwind Bounce Short positions gradually
  rather than at the close once size grows large, and the explicit ~5-6% extra loss on unwinding an
  oversized First Red Day position, both directly shaped how the sizing caps in Sections 4 and 5 were
  derived.
- **Testing before belief**: explicit closing advice — "if you want to be consistent profitable, test the
  strategy by yourself first" — presented as a general principle for adopting any of these three models,
  not specific encouragement tied to one of them.

---

## 8. Gaps — not fully specified in source (need decisions if codifying)

- **The pre-market-to-full-day volume ratio (~1:5 to 1:10) is stated as a general heuristic** without a
  specified method for picking where in that range to land for a given name/day — likely needs to be
  fit empirically per market-cap/float band if automated, rather than treated as a single constant.
- **"Dollar block" calculation requires manually isolating volume traded specifically at/near the
  reference consolidation price** (via 30-min/1-hour chart inspection) — no formal algorithmic definition
  of the price-band width to use when bucketing volume into "at this consolidated price" vs. "volume that
  occurred elsewhere on the way up/down" is given.
- **First Red Day's dollar-block-ceiling bands (~$3B / ~$5-10B / ~$30B by market-cap tier) are presented
  as his own empirically-derived rules of thumb from hundreds of samples**, not a formula — if codified,
  these specific figures would need periodic re-validation against fresh data rather than being treated
  as permanent constants, and the market-cap-tier boundaries themselves aren't given precise numeric
  edges beyond the three illustrative examples.
- **Sector exclusion list (biotech, energy, Chinese stocks) is stated as empirically derived from his own
  trading history**, with quantified biotech win-rate degradation (~20-30%) but no equivalent quantified
  figure given for energy or Chinese-stock exclusion beyond the halt/liquidity anecdotes — would need a
  formal sector classification/exclusion list and, ideally, independent re-validation of these specific
  degradation figures.
- **No explicit stated per-trade or daily percentage-of-account risk cap** comparable to the other three
  models' explicit numbers (e.g. Fabio's 0.25-0.5%/2% daily, Gala's 5-8% premium risk) — sizing here is
  discussed entirely in terms of float/volume percentage caps (Bounce Short) or fractional-entry staging
  (First Red Day, the 1/4-then-3/4 split), not in terms of overall account risk percentage.
- **"First weakness/breakdown" (Gap Up Short) and "momentum visibly shifts" (also Gap Up Short, 5-10M
  float variant) are qualitative triggers** without a specific candle-close or percentage-decline
  definition — analogous to the confirmation-candle gates formalized in the Gala Trades and Marco Trades
  docs, but left undefined here.

---

## 9. Rules-Layer Sketch (for engine integration)

Suggested pipeline order, mirroring the structure used for the other three strategy docs:

1. **Universal eligibility filter** — market cap $1M-$100M (or up to ~$200M for First Red Day, using
   back-calculated *initial* market cap for names that have already run), float $1M-$50M (strategy-
   specific sub-caps per Section 6 table), price > $3, sector not in {biotech, energy, China-domiciled}.
2. **Crowding/volume-projection gate** — project full-day volume from pre-market volume via the ~1:5-1:10
   ratio heuristic (tune empirically per band); reject names with pre-market volume > ~50M shares for Gap
   Up Short specifically; for Bounce Short/First Red Day, adjust the raw projection downward (~50-80%) to
   account for the strategy's own anticipated selling pressure suppressing buy-side volume.
3. **Strategy-specific pattern detection**:
   - *Gap Up Short*: gap ≥100% at open → consolidation forms → first breakdown off consolidation.
   - *Bounce Short*: 1-year lookback for a ≥100M-share historical spike day → compute dollar block at
     that consolidated price (target ≥$150M) → fresh 100%+ gap approaching that old price → classify as
     Type 1 (gap-in-close, low pre-market volume) or Type 2 (parabolic climb from open).
   - *First Red Day*: ≥3 consecutive green days (or 2 days if cumulative range ≥1000%) with day-over-day
     increasing dollar volume and no red/flat reset day → cumulative range ≥300% (3-day case) → compare
     day's projected dollar volume against the market-cap-tier dollar-block ceiling to gate entry timing.
4. **Volume-ratio sizing signal** — compute (adjusted day-volume estimate) : (reference dollar-block or
   prior-day volume) ratio; map to a sizing scale (~1:1 reduce, ~2:1 increase, extreme ratios up to ~10:1
   = maximum conviction), subject to hard caps (≤10% float, ≤1% day volume for Bounce Short; float/volume
   band-implied caps for Gap Up Short; fractional 1/4-then-3/4 staged entry for First Red Day).
5. **Entry trigger** — strategy-specific: first breakdown off consolidation (Gap Up Short); price
   reaching/testing the old consolidated price with confirming volume ratio (Bounce Short); staged
   1/4-position at ceiling-approach day, 3/4-position on the following lower-volume confirmation day
   (First Red Day).
6. **Stop-loss placement** — above the consolidation/resistance zone in all three strategies (not above
   an isolated spike wick).
7. **Target/exit** — average fade ~26% (Gap Up Short), ~50-75% of range depending on sub-variant (Bounce
   Short), ~50% max bounded reward with gradual cover at size (First Red Day); scale exit method to
   position size (unwind gradually rather than holding to close once position is large relative to the
   name's liquidity).
8. **Expected-value logging layer** — track occurrences/year, win rate, and average reward per strategy
   type against the stated baselines (Section 6) to support the "simulate expected annual P&L in advance"
   discipline described in Section 1 as the model's core psychological anchor.
