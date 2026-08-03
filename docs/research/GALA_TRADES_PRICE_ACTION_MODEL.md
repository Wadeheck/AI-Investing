# Price-Action + Level Model — Gala Trades (Kamjan)

Source: Chart Fanatics podcast, live options trading breakdown with Gala Trades (options trader,
$5M+ career profits, live brokerage logins for transparency). Full session digested: whiteboard
strategy explanation → historical trade replays/journaling → live pre-market prep → live trade
executed on Tesla during NY session. Kept detailed and literal — meant to be codifiable, not prose.

Companion doc: [FABIO_VALENTINO_ORDERFLOW_MODEL.md](./FABIO_VALENTINO_ORDERFLOW_MODEL.md) (order-flow
futures scalping). This model is price-action + level based, traded on **equity options**, and is
explicitly simpler/more discretionary-light than the order-flow model — worth comparing where they
agree (level-based entries, 2R/partial-scaling discipline, "no plan = no trade") and where they diverge
(no order-flow/tape reading here at all; levels come from swing structure, not volume profile).

---

## 1. Core Philosophy

- **Rejects "trend = two parallel channel lines."** Price can travel above/below any drawn channel and
  still be trending. Instead, trend is defined purely by **sequence of highs and lows**: uptrend = higher
  highs + higher lows (even if choppy/inconsistent in between); downtrend = lower highs + lower lows.
- **Trend has exactly one use**: it picks which side of the option chain to trade (uptrend → calls only;
  downtrend → puts only). Nothing more sophisticated is layered onto it. "I'm just trying to keep it as
  simple as it is with everything."
- **Levels are the actual edge**, not the trend itself — trend only filters direction; levels generate
  the entries.
- Self-imposed operating constraint: **trades only ~1 hour/day** (execution window), with roughly 1 hour
  of pre-market prep and 1 hour of post-market journaling. This directly drove the choice of the hourly
  timeframe for structure (matches his realistic holding-period horizon) — a deliberate lifestyle/time
  constraint that shaped the whole system, not a purely technical choice.

---

## 2. Trend Identification

- **Timeframe: hourly, always**, for both trend and level identification. Never uses daily/4H even
  though he acknowledges those are popular — chose hourly specifically because most of his trades run
  within a ~1 hour duration, so the analysis timeframe matches the trade's actual life span.
- Identify pivot points (swing highs/lows) on the hourly chart. If lows are getting higher and highs are
  getting higher (even inconsistently) → uptrend → look for calls only. Mirror for downtrend/puts.
- If the trend is unclear/choppy/indeterminate on the hourly → **skip the name entirely**, no trade
  either direction.

---

## 3. Level Identification (the core mechanic)

- Levels are drawn at **pivot points** on the hourly chart — places where price visibly turned.
- **Critical refinement: ignore the wick, use the candle body/open.** Specifically, the level is drawn
  at **the open price of the candle following a reversal candle** (e.g. if a red candle is followed by a
  green reversal candle, the level = the open of that green candle), not at the wick extreme. He
  considers where the candle *opened* more diagnostic than the wick extent.
- **Opening-price levels get their own category**: the day's opening price is marked as its own
  distinct level type (see confidence tiering below).
- **Confidence tiering by color** (this determines position sizing):
  - **Solid/primary color (e.g. purple)** — standard pivot-point levels — **5/5 confidence**.
  - **Opening-price-derived levels** — a different color (e.g. blue) — **3/5 confidence**.
  - **Invalidated levels** (price has since pierced through) are not deleted immediately — kept as a
    **dashed line**, meaning "still has some relevance but weaker" — **~2.5/5 confidence**.
  - Position size is scaled to this confidence score, not just to the setup quality.
- **Level invalidation rule**: if a candle pierces cleanly through a level, that level is invalidated for
  fresh trend-following use (downgrade to dashed/2.5-confidence) and, if enough new pivots have formed,
  it's deleted and levels are re-drawn "from scratch" for that name.
- Practicing this on ~10 names per day maximum (his full pre-market watchlist size) — deliberately
  capped, not scanning an unlimited universe.

---

## 4. Pre-Market Routine (exact sequence, done before every session)

1. **Re-mark levels on the hourly** for every name on the watchlist — delete/downgrade anything
   invalidated since the prior session, mark new pivots.
2. **Identify trend direction** on the hourly for each name (calls-only or puts-only per name).
3. **Check where pre-market price sits relative to the two nearest levels** (closer to the level above,
   or the level below) — this determines which of the three setups (break-retest / bounce / rejection)
   is the live candidate for that name today.
4. **Filter/skip names on vibe as much as structure**: explicitly skips any chart that "looks weird,"
   has anomalous wicks he suspects are dark-pool prints or data bugs, or where the trend is ambiguous —
   "if I don't know, I just skip it." This is a stated deliberate low-confidence filter, not just
   structural invalidation.
5. **Skip names moving against the broader indices** (SPY/QQQ) even if the individual setup looks good —
   stated preference to avoid trading against the tape/market direction.
6. **Write the plan down and post it somewhere persistent** (his Discord) specifically so it's not
   forgotten/rationalized-away once the session gets emotionally live.
7. **Check the economic calendar** (uses econ-style calendar sites) for scheduled releases (CPI, FOMC,
   Powell speaking, etc.) in the trading window — if something market-moving is scheduled, that's a
   factor in whether/how aggressively to engage.
8. **Reduce active chart count** right before open (e.g. from a 10-name watchlist down to ~4 charts
   actively displayed) purely for execution focus.
9. **Do not trade extended hours.** Pre-market/post-market price action is compressed into being treated
   as if it were a *single candle* on the hourly structure — i.e., all pre-market movement between close
   and open is functionally one candle's worth of information, not a series of tradeable candles.
10. **Wait out the market open.** Never trades into the open — historically shrank this filter over his
    career from skipping the first 30 minutes → 15 → 10 → now just the **first 5-minute candle**
    (waiting for it to fully close before considering any entry), because the open candle carries
    outsized volatility/wick risk. States he's even considering tightening this further to ~2 minutes.

---

## 5. The Three Setups (+ trend continuation)

All entries execute on the **2-minute or 5-minute timeframe**, with **5-minute given preference** when
the two disagree — "the 5-minute is going to dictate more conviction for me." If 5-min looks bad but
2-min looks good, he does not take it; if both agree, that's the strongest case.

### 5.1 Break and Retest (primary/default setup)

- Price closes a candle (on the working timeframe) **beyond** the level — a "breaking candle."
- Wait for a **retest candle**: ideally one with a **small wick that dips slightly below/beyond the
  level, but a candle body that closes back on the correct side of the level.** This is explicitly
  called his "perfect entry" pattern — it shows the level was tested and rejected quickly ("bought up
  very quickly"), giving both a tight stop reference and confirmation of level significance.
- Multiple retest candles are acceptable (not just one) — as long as the wicks stay in a tight cluster
  near the level and bodies hold the correct side, more retests are fine; take the **lowest wick point
  across all retest candles** as the stop-loss reference, not just the last one.
- **Must wait for close-and-hold, not just a touch.** A level break with no confirmed hold (price breaks,
  fails to get accepted, continues through) is explicitly not a trade — "I'm going to be waiting for the
  price to break and hold... it's important to wait for the reaction."
- Entry is placed as close to the level as possible specifically so the stop can be kept tight.

### 5.2 Bounce (calls-only variant — used when pre-market price sits ABOVE the level of interest)

- Used when pre-market price is closer to the level from above and the (up)trend calls for calls, so the
  play is a retracement down into the level rather than a breakout through it.
- Look for **2–3 candles (5-minute preferred)** where the **wick dips below the level but the body stays
  above it** — repeated small failed pushes by sellers. He frames this explicitly as a battle-exhaustion
  model: each attempted seller push is weaker than the last (visualized as shrinking arrows) until
  sellers are "exhausted" and only resting buyers remain, at which point price pushes up.
- Stop = lowest wick point of the cluster.
- Progressive stop management as it develops in your favor: shift the stop toward the open of the most
  recent trending candle with each new candle, to preserve a defined "wiggle room" buffer rather than
  moving it to breakeven immediately.

### 5.3 Rejection (puts-only mirror of the bounce)

- Same battle-exhaustion logic in reverse: price approaches a level from below, buyers repeatedly try to
  push through (shrinking-intensity pushes visualized the same way) and fail, sellers take control, price
  reverses down to make a lower low.
- Wick structure mirrors the bounce: **wicks pushing above the level, bodies staying below it.**
- Stop = highest wick point of the cluster.
- **Entry quality directly determines whether you can hold to target**: a poor entry (far from the
  level) makes reaching 2R much harder than a tight entry at the level — explicitly stated as the reason
  he prioritizes entry precision over taking a trade at all: "good entry or no entry."
- When there's a large gap to the next major level (bigger potential move available), he'll accept a
  wider stop / earlier entry to capture more of the move — an explicit tradeoff of win-rate for R:R when
  room to the next structural level is large, mirrored from the order-flow model's own R:R-vs-hit-rate
  framing.

### 5.4 Trend Continuation

- Not a fourth distinct setup in his own final count — folded into all three above. Defined simply as
  "trading from low to high" (uptrend) or high to low (downtrend), applicable on any timeframe depending
  on which swing you're trading. The lower-timeframe candle patterns (break-retest/bounce/rejection)
  are still what triggers the actual entry; trend continuation is just the directional label for "the
  biggest move in the trend."

---

## 6. Entry Confirmation Nuances

- **Optimal wick size is a real filter, not just direction.** A wick that's "not too big, not too tiny"
  is ideal. Wicks that are too small/fast (price barely dips and snaps back — a "hammer" reversal that
  happens too quickly) mean there was no real opportunity window to get filled — these are explicitly
  named as unactionable even though they're structurally "correct."
- **Options-specific stop-loss framing**: because option premium doesn't move linearly with underlying
  price, he pre-assigns an approximate **percentage-of-premium stop** (typically ~5–8%, occasionally
  drifting to ~10% if held too long) rather than a fixed dollar/tick amount, and reasons in terms of "if
  I'm risking 8 cents [of premium], I want at least twice that [16 cents] as target" — i.e. a minimum 2:1
  on the option premium itself as a floor, separate from the underlying's own R-multiple structure.
- **Two-attempt rule per setup, hard cap.** If stopped out once on a level/pattern, he allows himself a
  **second entry** on the same setup if the pattern is still forming validly. A **third entry on the same
  setup is explicitly defined as overtrading** and is a hard rule violation regardless of how good it
  looks. Explicitly notes this has a luck component — whether you happen to look at the chart on
  candle #1 (about to stop you out) vs. candle #3 (a visibly better-formed setup) is partly chance, and
  he accepts that rather than trying to eliminate it.
- **Daily trade-count ceiling**: caps himself at **2–3 trades/day**; **4+ is defined as overtrading** in
  his current regime. Notes he used to run 8–9 trades/day successfully in 2023 but attributes that to
  easier market conditions at the time — the cap is not a fixed universal constant, it's been tightened
  as conditions/his own discipline evolved. Framed explicitly as choosing quality/focus over quantity.
- **Off-plan trades are allowed but structurally penalized.** If a name wasn't on the pre-market
  watchlist but a very clean setup appears intraday (strong level reaction, clear pattern), he will take
  it — but **always with reduced position size**, specifically as a self-imposed cost for breaking his
  own process discipline (both to limit downside and to avoid "rewarding" rule-breaking behavior).
- **"No plan left = no trade" rule.** If every name on the watchlist gets invalidated intraday (levels
  broken without giving a retest, or setups failing to form) and nothing new presents a clean off-plan
  setup, the correct action is to **do nothing and end the day flat** — explicitly framed as itself a
  form of trading success, not a failure: "the disciplined way of how to deal with [a lack of
  opportunity] is also success."
- **Never hold into unknown overnight catalysts.** Explicitly rejects the "what if it pops tomorrow"
  rationalization for holding through a stop as "the dumbest thing" — day trading means operating on
  what's happening now, not speculating on overnight news.
- **Post-loss re-entry at the same technical price is explicitly refused.** Once a trade is closed
  (whether win or loss), if price later returns to that same entry zone, he does **not** re-enter — "if
  I've done the trade, then it's a done deal... none of my business." A prior close (even a stopped-out
  break-retest) is treated as invalidating that specific instance of the setup going forward, distinct
  from the "2-attempt" rule which applies to *not-yet-closed-out* sequential attempts within the same
  session.

---

## 7. Position/Trade Management

- **Standard target: 2R** (occasionally content with 1.5R). Explicitly rejects reaching for 10R/5R
  "home run" trades as a primary goal — his stated view is that **home-run trades, in aggregate over a
  year, contribute a smaller share of total profit than consistent 1.5–2R base hits.** Anything above 2R
  is labeled "exceptional," not expected.
- **Scaling out is condition-dependent, not fixed-percentage:**
  - **Default/good mental state**: trim ~50% of the position at/near 2R, let the remainder run with the
    stop actively trailed upward so the runner locks in profit even if eventually stopped.
  - **After a prior loss same day (capital-preservation mode)**: trims far more aggressively — up to
    80%, occasionally the full 100% — explicitly to reduce stress and protect capital rather than to
    maximize the specific trade's expectancy.
  - **"Feeling adventurous" (rare)**: trims as little as ~20–30%, letting most of the position ride —
    self-described as an infrequent habit he's actively trying to move away from in favor of more
    conservative defaults.
  - **Candle-color momentum as a trim-size input**: if a position is running with consecutive
    same-direction candles and no opposing candles (e.g. all-green while long), that's used as a live
    signal to reduce the size of the first trim (hold more), since sustained one-directional candles
    indicate strong momentum worth giving more room.
- **Stop trailing methodology**: shift the stop with "every trending candle" — not to the exact new
  candle's extreme, but generally to that candle's open, to preserve a defined wiggle-room buffer rather
  than choking the trade too tightly. After a partial trim, the stop is explicitly raised to a level
  where **even a full stop-out on the remaining size still leaves the trade net profitable overall**
  (locking in a blended-profitable outcome, not just breakeven).
- **Deliberately avoids over-optimizing the last small runner**: even with only ~10% of the original size
  left running (a psychologically "free roll" position), he still sometimes closes it early rather than
  holding to a further target — cites simple exhaustion/fatigue from active management as a legitimate
  reason to close, separate from any technical signal.
- **Time-boxing a trade regardless of technical signal**: if a position with a runner has been open
  **more than ~1 hour** with no clear reversal signal either way, he will close it purely on elapsed time,
  citing that holding longer increases options-decay (theta) exposure disproportionately to the marginal
  edge of waiting for a "perfect" exit. This originally arose from a personal-schedule constraint (late
  session hours in his time zone) and then hardened into a standing discipline rule independent of the
  original reason.
- **"Once in a position, don't watch the P&L — watch the chart."** Explicitly disables/hides the live
  P&L number during open trades because watching it in real time creates pressure to (a) take profit
  early out of fear of giving it back, or (b) close a loser slightly before the actual stop level to
  "cheat" a smaller loss than planned — both are treated as process violations regardless of whether they
  happen to work out.
- **Order-execution practicalities**: normally executes from mobile (faster) rather than desktop; keeps
  the closing/market order pre-staged and ready the moment a level is approached so execution is a single
  tap once the trigger candle confirms.
- **Position sizing note (context-dependent, not systematic)**: reduces size specifically when trading
  outside his normal setup (e.g. a studio/podcast recording instead of his 3-monitor home office) — an
  explicit acknowledgment that execution environment itself is a risk factor to size around, separate
  from setup quality or confidence-tier.

---

## 8. Supplementary Tool: Bookmap (order-flow overlay, used sparingly)

- **Used only occasionally**, specifically on **index-correlated names (SPY/QQQ) and futures (ES/NQ)**
  — not used on single stocks like Tesla, where he judges the order book to be less informationally
  useful for his purposes.
- **Custom configuration**: color-filters the heatmap so only large ("thick") resting order layers show
  in a distinct color (yellow in his setup) — small/irrelevant liquidity is suppressed visually.
- **Explicit role: confirmation only, never the core signal.** "I use bookmap as just a confirmation
  tool, not as a core strategy." The underlying price-action/level plan stays the primary driver; bookmap
  is used to add or subtract conviction on setups that are already structurally present, and can justify
  taking a level-based entry slightly earlier than the candle-pattern would normally allow if a thick
  resting wall coincides exactly with his charted level.
- **Reading example given**: aggressive orders ("green bubble") hitting a large resting sell wall without
  breaking it, followed by price stalling and then reversing away from the wall = used as confirmation to
  fade the level (take the rejection trade) rather than wait for a slower price-only confirmation
  sequence.

---

## 9. Journaling Process (post-trade, done same day)

Explicitly ranked as **the most important part of the routine** — more time is spent on prep +
journaling combined than on the actual trade execution itself.

Fields/checks logged per trade (via TradeZella, but the checklist generalizes):

1. **Entry price, stop-loss price, target price** and the resulting **R risked in dollar terms.**
2. **Actual partial-exit sizes and prices** (not just the final blended result) — tracks each individual
   scale-out separately since stop-shifting after partials changes the effective risk on the remaining
   position (e.g. explicitly recalculates that dollar risk dropped from $700 to $500 after a partial
   trim + stop shift, and logs that changed-risk number, not just the original).
3. **Setup tag** (break-retest / bounce / rejection / trend-continuation) — used for later performance
   segmentation by setup type.
4. **Was the trade on the pre-market plan or not?** — logged as a distinct binary flag; explicitly states
   this is the single most important review question, more important than win/loss.
5. **Mistake tagging**, from a recurring checklist he applies to every trade, including at minimum:
   - Bad entry (not tight enough to the level)
   - Off-plan / unplanned trade
   - Early exit (closed before target/stop for no technical reason)
   - Decay exposure (held long enough that theta became a meaningful factor)
   - Missed opportunity / left too much on the table by trimming early
6. **Star rating (out of 5)**, assigned holistically based on how many of the ideal-execution criteria
   were met (clean entry at the level + no early rejection off the entry + full checklist adherence) —
   NOT based on the dollar outcome of the trade. States a trade can be highly profitable and still be
   rated a mediocre 3.5/5 if execution deviated from the ideal process, and vice versa.
7. **Process checklist ("Gala rules") ticked individually per trade**: waited for the first 5-minute
   candle to close before acting; used a real level; used a valid candle pattern; checked relative
   strength vs. the broader index; stop was appropriately tight; consistent (non-oversized) position
   sizing; trade was on the pre-market plan; bookmap used where applicable (or explicitly N/A'd if not
   relevant to that name).
8. **Explicitly separates outcome from process in the closing evaluation**: "it doesn't matter how much
   we made or lost. The important thing is just to do things right... if you do things right, results
   will not wait." Journaling is oriented entirely around process adherence, with P&L treated as a lagging
   confirmation rather than the primary metric being reviewed.

---

## 10. Illustrative Live Trade (worked example, for calibrating the above rules)

Walked live on-air, useful as a concrete instantiation of the whole pipeline:

- **Pre-market**: Tesla identified as one of 5 candidates (all calls-only that day, no puts names) for a
  break-and-retest of a level near $420.68, based on hourly uptrend + proximity of pre-market price to
  that level.
- **Open**: first 5-minute candle skipped by rule. Several other watchlist names (AMD, Palantir) either
  invalidated quickly or failed to develop; Tesla remained the only structurally valid setup as the
  broader indices (SPY/QQQ) were initially weak — noted explicitly as a caution (avoid trading against
  the tape) but Tesla showed **relative strength** (green while SPY was red), which was treated as a
  positive discriminating factor for proceeding despite the weak tape.
- **Entry**: filled at $5.75 (option price) — acknowledged in real time as **not a perfect entry** (price
  was ~4 cents past the ideal level-touch price when filled); flagged this exact slippage as a "bad
  entry" mistake in the post-trade journal, explicitly quantifying how much of the eventual profit was
  left on the table by not waiting the extra few cents for a cleaner fill.
- **Management**: trimmed 10 of 16 contracts near the target level (~$426.34 area) → banked $1,500 locked
  vs. $500 still running on the remainder; stop shifted immediately after that partial to lock in a net
  profitable outcome regardless of what happened to the runner; trimmed 2 more shortly after; final 4
  contracts stopped out on a rejection candle after price failed to close above the level on the
  5-minute despite a strong-looking push (explicit real-time example of why *closed* candle confirmation
  matters more than intra-candle price action, however bullish it looks mid-formation).
- **Result**: ~$1,200 net profit in ~7–8 minutes on reduced (10k) position size versus his typical
  40–50k size (deliberately smaller because trading from an unfamiliar studio setup, not his normal
  3-monitor home office) — used explicitly to illustrate that realistic sizing would have scaled this to
  roughly $5,000–6,000 on a normal-size position.
- **Journal outcome**: rated **~3.5/5 stars** — process was sound (waited for the open candle, used a
  real level, checked relative strength, sized consistently, was on the pre-market plan) but docked for
  the imperfect entry price and for the setup lacking his single cleanest pattern signature (wick fully
  below the level with body cleanly above, rather than the messier multi-wick cluster actually seen).

---

## 11. Explicit Meta-Point (stated directly, worth preserving verbatim in spirit)

"Just because the market moves doesn't mean there's a trade." The system is built to produce **no
signal** on most days for most names, and doing nothing when nothing qualifies is treated as equally
valid an outcome as a winning trade — this is presented as the actual hardest and most important
discipline in the whole model, more so than any individual entry rule.

---

## 12. Gaps — not fully specified in source (need decisions if codifying)

- **Exact pivot-detection algorithm** for hourly highs/lows isn't formalized — "pivot point" is applied
  by eye; would need a formal swing-detection method (e.g. N-bar fractal, ZigZag threshold) to automate
  level placement, plus a rule for the "use candle open, not wick" refinement.
- **Confidence-tier position sizing isn't quantified** beyond the 5 / 3 / 2.5 relative labels — no stated
  formula for how confidence score maps to actual contract/dollar size.
- **"Looks weird, I skip it" is an admitted pure-discretion filter** with no structural definition given
  — likely the hardest part of this model to encode without a proxy (e.g. abnormal single-print wick
  size relative to recent ATR, or an anomaly-detection heuristic on that single flagged Nvidia-style
  candle).
- **Trade-count cap (2-3/day) is stated as currently-in-force but explicitly non-permanent** (was 8-9/day
  in 2023 under different market conditions) — if codified, should be a tunable parameter tied to a
  regime/volatility proxy rather than a hardcoded constant.
- **Options strike-selection logic is only loosely specified**: prefers the strike where the underlying
  price sits within the steepest delta-sensitivity range relative to the target move, and generally uses
  the **nearest weekly expiration** except on names with same-week multiple expirations (e.g. Tesla's
  Mon/Wed/Fri cycle) where he deliberately avoids the very nearest (0-DTE-style) expiration as "dangerous"
  volatility and defaults to the **standard Friday expiration** instead — but no precise delta/theta
  threshold is given for strike choice.

---

## 13. Rules-Layer Sketch (for engine integration)

Suggested pipeline order if implementing as a filter stack, mirroring the structure used for the
order-flow model:

1. **Trend filter** — hourly higher-highs/higher-lows (or inverse) → sets long-only / short-only bias
   per instrument; ambiguous trend → exclude instrument for the session.
2. **Level detection** — hourly pivot points, placed at reversal-candle open rather than wick extreme;
   tag each level with a confidence tier (fresh pivot / opening-price-derived / invalidated-but-dashed).
3. **Pre-market proximity check** — which of the two nearest levels price sits closer to → selects
   candidate setup type (break-retest vs. bounce vs. rejection) per instrument for the day's plan.
4. **Market-open cooldown** — suppress all entries until the first post-open 5-minute candle has closed.
5. **Pattern-confirmation gate** — full-body candle close beyond the level (break-retest), or a
   multi-candle wick-below/body-above cluster (bounce) / wick-above/body-below cluster (rejection);
   require agreement between 2-min and 5-min timeframes, weighting 5-min as authoritative on conflict.
6. **Relative-strength check** — instrument's intraday direction vs. SPY/QQQ; penalize or exclude setups
   counter to the broader tape.
7. **Entry/stop placement** — entry as close to the level as the confirmation candle allows; stop at the
   confirming cluster's extreme wick; percentage-of-premium risk cap (~5-8%) as an options-specific
   sanity check layered on top of the underlying-based stop.
8. **Position/target management** — default 2R target with ~50% scale-out, trailing stop by
   candle-open increments, dynamic scale-out percentage conditioned on same-day P&L state
   (preservation mode after a loss, momentum-following mode on strong same-direction candle streaks).
9. **Session/attempt caps** — max 2 attempts per individual setup instance; max 2-3 total trades per day;
   both enforced as hard gates independent of how attractive a further signal looks.
10. **Journal/tag layer** — log plan-adherence flag, mistake tags, and a process-based star rating
    separate from raw P&L, to support the "grade the process, not the outcome" review loop.
