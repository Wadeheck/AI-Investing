# The "Da Vinci" Engineered-Liquidity Model — Marco Trades (Marco Asset)

Source: Chart Fanatics podcast, second episode with Marco Trades ("Marco Asset") — $500K+ in prop-firm
payouts, ~$800K views on the prior episode. This episode assumes the viewer already understands his
foundational liquidity concepts from a prior episode (referenced repeatedly but not restated in full
here — see gaps section at the end for what's missing as a result). Digested in full; kept deliberately
detailed rather than compressed, since the model's entire value proposition is precision of the specific
liquidity points used, not the general "liquidity" concept.

Companion docs: [FABIO_VALENTINO_ORDERFLOW_MODEL.md](./FABIO_VALENTINO_ORDERFLOW_MODEL.md) (futures
order-flow scalping), [GALA_TRADES_PRICE_ACTION_MODEL.md](./GALA_TRADES_PRICE_ACTION_MODEL.md) (options
price-action/levels). This model overlaps with both in spirit (liquidity/level-based entries, patience
over prediction, high R:R via tight stops) but is distinct: it is explicitly **pattern-of-liquidity**
based (ICT/SMC lineage — "engineered liquidity," "liquidity block," "internal" points), trades **any
asset class and any timeframe** (explicitly demonstrated across gold/XAU, NQ futures, and USDJPY forex/
CFD in the same episode), and is the most theoretically "simple" of the three by the trader's own
framing — "just horizontal lines... letting price communicate to us where liquidity is."

---

## 1. Core Philosophy

- **Never predict where liquidity is going to form. Let the market communicate it.** Explicitly and
  repeatedly rejects the common retail framing that "there is liquidity above every high and below every
  low" — calls this the amateur mistake that leaves traders paralyzed ("there's highs and highs and lows
  all over my chart, what do I do?"). Only specific, market-confirmed liquidity points are tradeable, not
  every swing point.
- **Confirmation rule for "this level matters": a high/low must *respect* (react off of) a matching
  prior high/low from the left of the chart.** I.e., if the current high stalls/reverses at approximately
  the same price as a previous high, that repetition is what marks the level as holding real resting
  liquidity — a single unconfirmed swing point is not enough on its own.
- **"If you don't see liquidity, you are the liquidity."** Stated as a direct, repeated maxim — if you
  can't identify a clear, confirmed liquidity point before entering, you are the retail order flow that
  the model is designed to trade against/off of.
- **Fractal across all timeframes and all asset classes.** The exact same pattern can play out on a
  daily chart over several days, or on a 1-minute chart within a few hours — and, critically, **the same
  underlying setup can be simultaneously present on multiple timeframes at once**, with the higher
  timeframe instance providing directional bias and a separate, independently-forming lower-timeframe
  instance of the identical pattern providing the actual entry trigger. This dual-timeframe stacking is
  presented as the model's signature "textbook" configuration, not just a theoretical possibility.
- **Not a pure pattern trade — always requires independent directional logic.** Explicitly warns against
  mechanically buying every time the bullish pattern shape appears: "you always need a reason, a logic
  for price to move" in that direction (e.g. still-intact higher-timeframe highs above, i.e., the broader
  structural bias must support the trade direction) — the engineered-liquidity pattern is a trigger, not
  a standalone thesis.

---

## 2. Definitions (precise terminology used throughout)

- **Liquidity (in this model's context)**: resting stop-orders/pending interest clustered just beyond a
  swing high (sell orders / short stops) or swing low (buy orders / long stops).
- **Engineered liquidity**: the *specific* high or low that has been confirmed — via repeated reaction/
  respect from a matching prior high or low — to be genuinely building resting counter-side orders. This
  is the single most important concept in the whole model. Definition, precisely: in a bullish scenario,
  after sweeping some liquidity to the downside (an old low), price rallies and, on the way up, prints a
  high that **respects** (matches/reacts at) a previous high to the left. This reaction is read as
  sellers actively entering there (not merely as "a resistance level") — the retracement that follows is
  their initiated selling pressure, which is exactly the liquidity the model wants engineered before it
  will look for the buy entry down at the (already-identified) target low.
- **Hard rule: "No engineered liquidity, no model."** If this specific reaction pattern isn't present,
  it is explicitly stated this is *not* a Da Vinci setup, regardless of how good other confluences look.
- **"Internal" points**: a high or low that respects/repeats a prior high or low **within the currently
  developing move**, i.e. a smaller-scale instance of the same respecting-behavior occurring inside the
  broader swing being tracked, used to refine/build the immediate pre-entry structure. Explicitly says
  not to overthink the terminology — "high respecting previous high" is the entire content of the word
  "internal," it isn't a separate independent concept.
- **Liquidity block**: a swing low (or high) that has *already* run/swept previous lows (or highs) to its
  left — meaning it does **not** hold fresh resting liquidity, because that liquidity has already been
  taken. Levels flagged as liquidity blocks are explicitly **not used** as engineered-liquidity references
  or as valid stop-placement anchors — treated as "already spent" structure.
- **Induced / trapped early buyers (or sellers)**: retail participants entering off an obvious/naive
  structural pattern (e.g. "high taken out, pullback, buy the retest") right before the model's actual
  directional move occurs — their presence and subsequent stop-out (getting run) is treated as *part of*
  the fuel logic for the eventual move, and their trapped positions are explicitly cited as a reason the
  move accelerates once it triggers.
- **Counter-bias trade**: a short-term trade taken in the opposite direction of the larger prevailing
  bias (e.g. a short pullback trade within a longer-term uptrend). Explicitly allowed, but must still
  satisfy the full engineered-liquidity criteria on its own — it's not exempted from the "always need a
  reason" rule just because it's a smaller, secondary trade.

---

## 3. The Model — Step-by-Step (Bullish Case; bearish is a pure mirror image)

1. **Identify a level of liquidity to the upside** — a high on the chart that you want price to
   eventually run to (the ultimate target). This target is *not yet* being traded — it's marked as the
   destination the whole setup is oriented toward.
2. **Confirm the market has already taken/grabbed something to the downside first** (an old low, or
   liquidity from an even-further left area) — this is the precondition that activates the bullish idea
   in the first place. Without this initial downside liquidity grab, there's no logical basis yet for
   expecting a move back up.
3. **Watch price travel up toward the identified upside liquidity target and print a high that respects
   a prior high to the left** — this reaction is the **engineered liquidity** confirmation (Step 1 core
   trigger). Mark this level explicitly (visually, e.g. with a distinct color/box) as "sellers entering
   the market here."
4. **Wait for price to retrace down off that engineered-liquidity high**, heading back toward the
   already-identified lower liquidity target (the level established in step 2, or a related lower-
   timeframe internal low near it).
5. **Do not over-refine the entry.** Explicitly rejects waiting for an additional imbalance/fair-value-
   gap fill inside the target low as unnecessary precision-seeking that causes missed entries: "in my
   opinion, unnecessary... typically when people over-refine you're going to start missing entries."
6. **Entry trigger: as soon as the identified low is taken/stabbed (swept) — enter immediately.** No
   further confirmation candle or pattern is required beyond the sweep itself, once the level has been
   correctly identified via the engineered-liquidity logic. Explicitly compared this against the
   over-refining approach as *the* differentiator that keeps this model both simple and effective.
7. **Stop-loss placement: just below the low being swept** (with a stated CFD-specific allowance for
   "breathing room," i.e. a small buffer beyond the exact wick, on CFD/forex instruments specifically —
   distinguished from a hard tick-at-the-wick placement).
8. **Target: back at the originally identified upside liquidity level** (the high established in step 1
   — "we're not guessing where to target... the market communicated that to us").
9. **Multiple internal/partial targets are acknowledged along the way** (nested engineered-liquidity
   highs that formed en route can serve as optional partial-profit checkpoints for traders uncomfortable
   holding full size to the final target), but the *default* recommended approach is to hold full
   position size through to the final marked target rather than habitually partial at small R multiples.

Bearish case is a literal mirror: liquidity-below target identified, price first takes out something
above (an old high) to activate the idea, price travels down and prints a low that respects a prior low
(engineered liquidity, buyers entering), price retraces up toward a resistance/target high, entry
triggers on that high being taken/stabbed, stop above the high, target at the downside liquidity level.

---

## 4. Multi-Timeframe / Fractal Application (explicit mechanic, not just a claim)

- **The exact same Da Vinci structure can be present simultaneously at two different timeframes on the
  same instrument** — described as the "textbook" ideal case: a higher-timeframe Da Vinci provides
  overall direction/bias, while an independently-forming lower-timeframe Da Vinci (sometimes all the way
  down to the 1-minute chart) provides the actual tradeable entry trigger within that higher-timeframe
  bias. This dual-confirmation stacking is presented as producing the model's largest R:R outcomes (the
  worked gold example below reached ~1:12).
- **Instrument/timeframe pairing is asset-class dependent, driven by contract/session mechanics, not
  discretion**:
  - **Futures** (must be flat before market close): entries are typically taken on the **1-minute to
    5-minute** chart, targeting **15-minute to 1-hour** level structure — deliberately kept lower-
    timeframe on both ends because the position cannot be held indefinitely.
  - **CFD/forex** (positions can be held across days without a forced close): entries and targets can
    both be pulled up to much higher timeframes — cites personally taking entries off the **1-hour/
    4-hour** chart for a still-valid 1:10 R:R trade, and holding a daily-timeframe Da Vinci setup that
    takes multiple days to fully play out, made possible specifically because CFD/forex has no equivalent
    to the futures same-day-close constraint.
- **No stated lower bound other than practicality**: explicitly states he doesn't go below the 1-minute
  chart ("not going to go into the seconds timeframe... unnecessary"), while also noting the same
  fractal pattern is visually present even at that resolution if you looked — treated as a deliberate
  cutoff for usability, not a structural limit of the model itself.

---

## 5. Entry Precision Nuance — the "Extreme vs. Conservative" Entry Tradeoff

- The single lowest swept wick along a cluster of internal liquidity points is the "extreme" (most
  aggressive) entry — gives the maximum possible R:R because the stop can sit tightest against the
  final/deepest point in the cluster.
- **A materially less aggressive/more conservative entry (using a higher wick in the same liquidity
  cluster, not the absolute lowest) still captures the large majority of the same trade's edge** — worked
  example given: the "extreme" entry produced ~1:12, while a clearly less-precise entry into the *same*
  underlying setup still produced ~1:5, in the same time window. Framed explicitly as reassurance that
  precision-perfectionism is not required to capture the model's edge — a moderately-executed entry on a
  correctly-identified setup still performs very well.
- Even the runner/remainder of a position sized as small as **~20% of original size** is explicitly
  called out as capable of independently producing profit "the same or half or more" of the entire
  original position's realized gain, purely because of how large the R:R multiples can run — used as the
  stated justification for why he **doesn't like habitual small-R partial-taking** (see Section 6).

---

## 6. Position/Trade Management

- **Minimum acceptable R:R for taking a trade at all: 1:3.** States plainly this is where he performs
  best and makes the most money — not a hard mechanical rule for everyone, explicitly acknowledges other
  traders are comfortable with lower R:R (e.g. cites 1:1.7 as "great" for some people), but states his own
  personal floor is 1:3 and he passes on setups that don't offer at least that, specifically choosing to
  wait for a lower-timeframe entry that improves the R:R rather than taking a worse-R:R higher-timeframe
  entry on the same directional idea.
- **Reasoning for why lower timeframes are needed for higher R:R, stated explicitly**: a large stop (from
  taking a higher-timeframe/lower-precision entry) mechanically compresses R:R even if the target is
  unchanged — so achieving a large R:R specifically requires dropping to a lower timeframe to tighten the
  entry/stop distance, not because the higher timeframe analysis itself is wrong.
- **Break-even rule, precisely defined**: move stop to breakeven **once price takes out an internal high
  (in a long) or internal low (in a short)** that the model interprets as confirming early buyers/sellers
  have been induced along the way — i.e., breakeven is triggered by a specific structural liquidity event
  within the trade, not by a fixed time or fixed R-multiple.
- **After breakeven, default behavior is to hold full remaining volume to the final target**, not to
  scale out at intermediate R levels. Explicitly states a personal shift in approach roughly 1.5 years
  prior: previously partialed more frequently at smaller R (e.g. 1:3), moved to holding fuller size to
  final targets, and states this specific change directly increased his profitability — framed as a
  learned/evolved discipline, not an inherent starting rule.
- **If partialing at all, keep it small: ~20-25% of position**, explicitly small enough that the runner
  remains the dominant portion of the trade's total risk/reward exposure.
- **Explicit philosophical stance against small-R habitual partials**: "I'm analyzing the chart for a
  reason... why not take advantage of that analysis" — i.e., if you've done the structural work to
  project a specific target level, partialing before reaching it is treated as wasting that analysis
  rather than as prudent risk management.
- **The model's central claimed edge: high R:R does NOT come at the cost of a correspondingly reduced win
  rate**, which he states is unusual (normally high R:R strategies trade off against lower hit rate).
  His explanation for why this specific model avoids that tradeoff: the R:R is high *because* of tight,
  well-placed stops from correct engineered-liquidity identification, not because of aggressively distant
  targets relative to a noisy entry — so win rate isn't structurally sacrificed the way it typically is
  when traders simply widen targets on an unrefined entry.

---

## 7. Invalidation / What To Do When the Setup Fails

- If price sweeps the identified low (or high) and the anticipated reversal does **not** materialize (the
  entry gets stopped), the correct response is explicitly **not** to abandon the directional bias
  outright. Instead: **wait for the engineered-liquidity sequence to re-form from scratch** — i.e., wait
  to again see early buyers/sellers induced and then trapped — before considering a fresh entry.
- **Being stopped out does not, on its own, invalidate the broader directional thesis** — explicitly
  frames a failed entry as "maybe we were early," not as proof the underlying bias was wrong, provided
  the original liquidity target (the level the whole setup was oriented toward) remains untaken/intact.
- **A common failure mode explicitly named**: entering purely because "the level was crossed" without
  confirming genuine liquidity is actually resting above/below it — described as producing "a pullback
  and a continuation" that stops the trade out, because the level break wasn't accompanied by an actual
  engineered-liquidity confirmation, just a naive structural break. This is presented as the single most
  common mistake to filter out with this model.

---

## 8. Risk Framing vs. Prop-Firm Norms

- Explicitly contrasts this model against typical prop-firm trading advice (commonly cited as needing to
  risk 2-3% per trade to hit profit targets fast, which raises blow-up risk). Because of the asymmetric
  R:R this model produces, he states a trader can instead risk as little as **0.5–0.75% per trade** and
  still reach the same $10,000-$20,000 payout targets, purely because the R:R multiple compensates for
  the smaller risk percentage — framed as a direct alternative to the "risk big, pass fast" prop-firm
  playbook rather than a complement to it.

---

## 9. Worked Examples (as walked through live, preserved for calibration)

### 9.1 Gold (XAU) — dual-timeframe stack, ~1:12 extreme / ~1:5 conservative

- Higher-timeframe (visible on the working chart, roughly hourly-scale) bullish bias established: old low
  swept, price rallies and engineers liquidity at a high that respects prior highs to the left.
- Because the resulting stop-loss level for a direct entry at that point was judged too large (a "low
  that doesn't hold liquidity" — i.e. a liquidity block, not a fresh engineered point) relative to the
  minimum-1:3 rule, he explicitly declined the higher-timeframe entry and dropped to the **1-minute**
  chart to find a tighter, independently-confirmed Da Vinci setup within the same directional idea.
- On the 1-minute chart: choppy consolidation price action is read entirely as further liquidity-
  building (a "red box" marked as the area not to trade from, itself another instance of engineered
  liquidity forming), followed by a final low sweep that triggers entry.
- **Result: entry ~10:00am EST, target hit same afternoon (~2-5 hours), ~1:12 R:R on the extreme entry
  point; ~1:5 R:R on a deliberately less-precise/more-conservative entry into the same setup.**

### 9.2 Gold — secondary example, multiple sequential Da Vinci instances

- Shows two back-to-back engineered-liquidity/entry cycles on the same directional move (~1:7.5 and ~1:7
  respectively), used specifically to demonstrate that **each entry is repeatable and systematic** — the
  same "low = stop reference, high = target" logic reapplies cleanly to each new instance as price
  progresses, rather than the model being a one-off pattern that only worked once on that chart.

### 9.3 NQ Futures — higher-timeframe-only version for less-active traders

- Explicitly framed as an example for traders who **cannot actively watch lower timeframes** — the
  higher-timeframe engineered-liquidity level and its corresponding low are identified, and a **limit
  order is placed directly at the liquidity point with a stop below it, requiring no further chart-
  watching** ("you don't even need to look at the chart"). Presented as a legitimate simplified variant
  of the model for less screen-time-intensive execution, not merely a hypothetical.
- Result cited: ~1:4 realized (partial-taken version) with additional highs available as further targets
  (engineered-liquidity highs formed en route serving as optional partial points, external highs beyond
  as the full-hold target).
- A second NQ instance in the same session showed a smaller, still-valid ~1:3.5 R:R outcome, explicitly
  used to illustrate that **not every instance produces an extreme R:R** — moderate outcomes are treated
  as normal and still "phenomenal," not as a lesser or failed application of the model.

### 9.4 USDJPY (forex/CFD) — bearish, higher-timeframe held across a multi-day window

- A short taken specifically off a higher-timeframe (limit order, filled overnight while asleep —
  explicitly noted as only feasible in the CFD/forex market due to the ability to hold positions without
  a same-day close requirement).
- Realized ~$6,600 already banked with **partial position still running toward further/higher-timeframe
  downside targets** at time of recording (potential additional ~$5,000, for a possible >$11,000 total on
  the single trade) — used as a live, in-progress illustration of the "hold most of the position, let a
  small remainder run to a further target" management style described in Section 6.

---

## 10. "Training the Eyes" — the stated learning method (explicit, not just a throwaway line)

Asked directly how a newcomer develops the pattern-recognition skill this model depends on, the answer
given is specifically **repetition and consistency of chart review**, not a shortcut or checklist: going
through many historical chart examples of the pattern repeatedly (exactly the exercise performed in this
episode) is described as the mechanism by which the pattern becomes visible in live/real-time conditions
later. Explicitly states that without this repetition, a trader will "struggle to identify these setups
in live conditions" even if they intellectually understand the rules — positioned as a distinct,
necessary skill-building phase separate from just learning the rule definitions above.

---

## 11. Gaps — not fully specified in source (need decisions if codifying)

- **This episode explicitly depends on a prior/companion episode** for the foundational definition of
  "liquidity" and how highs/lows are read as holding it in the first place — some baseline vocabulary
  (e.g. precisely what distinguishes a "respected" high from an arbitrary swing high beyond "it happened
  more than once nearby") is assumed as known rather than defined fresh here. If codifying, the
  respected-level detection logic needs a formal proximity/tolerance threshold (how close is "respecting"
  a prior high — exact price, a tick/pip band, a percentage?) that isn't quantified anywhere in this
  transcript.
- **"Over-refining" is explicitly rejected but no alternative confirmation trigger beyond the raw sweep
  is given** — the entry rule is essentially "enter the instant the level is touched/swept," with no
  candle-close or volume confirmation layered on top (contrast with both the Fabio Valentino and Gala
  Trades models, which both require some form of close-based or order-flow confirmation before entry).
  This is a deliberate, stated design choice ("you don't even need to look at the chart" for the
  limit-order NQ variant) rather than an omission, but it means false sweeps/liquidity blocks are the
  main stated failure mode (Section 7) with no secondary filter offered to reduce their frequency beyond
  "wait for it to re-engineer."
- **No explicit sizing formula** — position sizing is discussed only in terms of R-multiples and partial
  percentages (20-25%), with no stated dollar/percent-of-account risk figure comparable to the other two
  models' explicit numbers (e.g. Gala's 5-8% premium risk, Fabio's 0.25-0.5%/2% daily cap). Only the
  prop-firm comparison in Section 8 gives any concrete percentage (0.5-0.75%), and that's framed as an
  illustrative alternative rather than his own stated personal rule.
- **"Liquidity block" identification (a level that should be excluded) is qualitative** ("a low that has
  already spiked out previous lows") with no stated rule for how far back to look when checking whether a
  given low has already swept something, or how to distinguish a genuine liquidity block from a level
  that simply hasn't been tested yet.
- **Multi-timeframe stacking logic (Section 4) doesn't specify how to resolve conflicts** — e.g. no stated
  rule for what to do if the higher-timeframe Da Vinci bias and a lower-timeframe Da Vinci pattern point
  in opposite directions simultaneously; only the aligned/stacked case is demonstrated.

---

## 12. Rules-Layer Sketch (for engine integration)

Suggested pipeline order, mirroring the structure used for the other two strategy docs:

1. **Directional bias filter** — confirm an initial liquidity grab in the *opposite* direction from the
   intended trade has already occurred (an old low taken before looking for longs, an old high taken
   before looking for shorts) — this is the precondition gate before any engineered-liquidity search
   begins.
2. **Engineered-liquidity detection** — identify a high/low that *respects* a prior high/low to its left
   within some tolerance band (needs a concrete definition per Section 11's gap) as price travels toward
   a previously-marked target level; tag this as the "engineered liquidity" point and mark its
   corresponding retracement zone.
3. **Liquidity-block exclusion filter** — before using any candidate low/high as an entry/stop reference,
   confirm it has NOT already swept prior liquidity in the same direction; discard candidates that have
   (treat as already-spent structure).
4. **Multi-timeframe confirmation (optional but preferred)** — check whether the same engineered-
   liquidity/retracement structure is independently present on a lower timeframe within the higher-
   timeframe bias; if present, use the lower-timeframe instance for entry/stop precision while keeping
   the higher-timeframe instance's target as the profit objective.
5. **Entry trigger** — fire immediately on the sweep/stab of the identified low (long) or high (short);
   no additional close-confirmation required by this model's own stated rules (contrast with the other
   two docs' confirmation-candle gates if a stricter composite filter is desired).
6. **Stop placement** — just beyond the swept level, with an added buffer specifically for CFD/forex
   instruments (asset-class-conditional stop-widening).
7. **R:R gate** — compute stop distance vs. distance to the pre-identified target; reject/skip trades
   below a configurable minimum (his own stated floor: 1:3), even if all other criteria are satisfied —
   this gate exists specifically to force a timeframe drop-down (step 4) rather than accepting a
   low-R:R version of a structurally valid setup.
8. **Breakeven trigger** — move stop to entry once an internal high (long) / internal low (short) within
   the trade's own development is taken out, not on a fixed time or R-multiple basis.
9. **Exit/target** — default to holding full remaining size to the originally-marked engineered-liquidity
   target; optional small partial (20-25%) at nested internal highs/lows en route for traders wanting
   reduced variance, explicitly discouraged as a default per the model's own stated philosophy.
10. **Invalidation handling** — on stop-out, do not flip or abandon the directional bias while the
    original target level remains untaken; re-enter the detection loop from step 2 (wait for
    engineered liquidity to re-form) rather than re-entering on the same un-reconfirmed level.
