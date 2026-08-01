# Stage Analysis — Ted Zack (River Asset Management)

Source: Chart Fanatics podcast, second episode with Ted Zack (managed $50M+ at age 25, now $400M+ at
River Asset Management). Covers **Stage Analysis**, the price-cycle framework Ted learned directly from
Stan Weinstein (author of *Secrets for Profiting in Bull and Bear Markets*) while interning at Trader
Line and helping build Weinstein's own course. Digested in full; kept deliberately detailed — this
model's entire premise is that it is a *universal, asset-class-agnostic* framework, so the value is in
the specific transition mechanics and the many cross-asset worked examples that prove the claim, not
just the four-stage taxonomy itself.

Companion docs: [FABIO_VALENTINO_ORDERFLOW_MODEL.md](./FABIO_VALENTINO_ORDERFLOW_MODEL.md),
[GALA_TRADES_PRICE_ACTION_MODEL.md](./GALA_TRADES_PRICE_ACTION_MODEL.md),
[MARCO_TRADES_DA_VINCI_LIQUIDITY_MODEL.md](./MARCO_TRADES_DA_VINCI_LIQUIDITY_MODEL.md),
[STEVEN_DUX_SMALL_CAP_SHORT_MODEL.md](./STEVEN_DUX_SMALL_CAP_SHORT_MODEL.md). This is the odd one out
among the five: it is explicitly a **longer-term, asset-manager-level trend/regime framework** (weekly
chart, position-trader/investor time horizon), not an intraday or swing entry system — it's meant to
answer "what is the dominant trend and should I even be looking at this name," with entries and
management explicitly deferred to other tools/episodes. It is also the only one of the five built
around a named, published external methodology (Weinstein's) rather than the trader's own originated
system, and the only one explicitly stress-tested across five+ asset classes (equities, crypto,
commodities, fixed income, currencies) in the same sitting.

---

## 1. Core Philosophy

- **Base any trading system on timeless, universal principles — and cyclicality is repeatedly cited as
  the clearest example of such a principle.** Explicitly drawn as an analogy chain: the cell cycle
  (biology), the business cycle (boom/bust), the credit cycle (Fed tightening/loosening), the water
  cycle, and — the subject of this doc — the **price cycle**, all treated as instances of the same
  underlying phenomenon recurring across domains.
- **"The tape tells all" (Weinstein's own quote), but narrative/fundamental confluence is still valued.**
  Explicitly states one could trade purely off price/stage structure alone and that is legitimate. But
  for a professional asset manager managing client capital specifically, he layers on a fundamental/
  narrative "story" (catalyst, technological theme, earnings trajectory) on top of the stage read —
  partly for genuine added conviction/edge, and partly because **clients need an explainable narrative**,
  not just "trust the price." Explicitly frames this as a nuance most independent/retail traders don't
  need to bother with (they only need to convince themselves), but professionals managing others' money
  do.
- **Explicit, repeated disclaimer against predicting the future**: "it's impossible to predict the
  future, and anyone who says they can predict the future is just full of crap." Stage analysis is framed
  instead as giving *probabilistic expectations* based on historical cyclical recurrence — if price
  behavior doesn't align with the stage-implied expectation, that's treated as a signal to re-evaluate the
  analysis, not as proof the framework is broken.
- **Human emotional cycle (euphoria → complacency → fear → depression → hope → optimism → euphoria) is
  explicitly named as the underlying psychological engine driving the stages** — particularly relevant to
  Stage 1 (worst news, most negative sentiment, at the literal price bottom) and Stage 3 (best news, most
  positive sentiment, at the literal price top), discussed further in Sections 3 and 5.
- **Confluence, not any single signal, is the stated goal**: "not all charts are built equally" — two
  stocks with an identical stage-two technical setup are explicitly expected to perform differently
  depending on secondary factors (strength of sector/theme, quality of fundamentals, presence of a real
  catalyst) — stage analysis identifies *alignment with the dominant trend*, not trade quality in
  isolation.

---

## 2. The Tool: Three (Effectively Four) Moving Averages, Weekly Chart

- **10-week, 30-week, and 40-week simple moving averages (SMA)** are the primary reference lines — he
  states he personally also often plots a **20-week SMA** as a secondary/intermediate reference (used
  specifically for a shorter-term trend-confirmation crossover check, see Section 7), but the core
  stage-classification logic is built around the 10/30/40-week trio.
- **Simple moving averages specifically, not exponential** — explicit stated preference, "I use simple."
- **Weekly timeframe is the default/primary chart** for identifying which of the four stages a name is
  currently in — explicitly described as the higher-level, longer-term regime read, with actual entries
  deferred to the daily chart (and this specific episode explicitly does not cover entry mechanics in
  depth — see Section 10 gap notes).
- **Core classification heuristic, usable even without precisely reading the moving averages**: examine
  raw price structure (higher highs/higher lows = uptrend characteristic; lower highs/lower lows =
  downtrend characteristic) and the **slope** of that structure — but the moving averages exist
  specifically to **smooth/normalize** this raw structure and make the stage-boundary transitions
  objectively legible rather than subjectively eyeballed.
- **Bullish alignment** (definitional for Stage 2): 10-week above the 30-week, which is above the
  40-week, and price trading above all three, with all three sloping upward.
- **Bearish alignment** (definitional for Stage 4): 10-week below the 30-week, which is below the
  40-week, and price trading below all three, with all three sloping downward. Explicitly notes that
  having 10 < 40 alone is *not* sufficient for full bearish alignment — the 10 must also be below the 30
  specifically, and there is often a multi-week lag between the two conditions being met (worked example
  in Section 8.1: 10 crossed below 30 several weeks before it crossed below 40).

---

## 3. Stage 4 — Downtrend (introduced first, deliberately, as the easiest entry point to the full cycle)

- **Price structure**: lower highs, lower lows.
- **Moving average structure**: price below all three (10/30/40-week); the averages themselves are
  bearishly stacked (10 below 30, 30 below 40) and all sloping downward.
- **Actionable stance**: for a long-term/position trader or asset manager, this is a **short-only stage**
  (or, for most practical purposes given his client-facing constraints, simply an avoid-longs stage — he
  notes he personally cannot short client accounts, only personal capital, and discusses shorts only in
  that limited personal-account context).
- **Severity/risk framing**: repeatedly emphasized as the stage capable of doing the most portfolio
  damage — concrete cited drawdowns from stage-four episodes across the worked examples run from **~66%
  to ~78%** peak-to-trough (ARK/RK ETF), **~76%** (Tesla, trillion-dollar company down to the
  $200-300B range), and **~78%** (E.L.F. Beauty) — used explicitly to justify why avoiding stage four
  altogether is treated as more important than trying to time shorts within it for most of the strategy's
  practical application.

---

## 4. Stage 1 — Basing / Bottoming

- **Trigger condition for the stage-4-to-stage-1 transition**: the **rate of change of the downtrend
  starts flattening** — the steep 45°+ decline angle begins to level out, price starts oscillating rather
  than making clean new lows.
- **Key mechanical tell, explicitly named as the single clearest visual signal**: "the moving averages
  start slicing through price and price oscillates up and down [above and below them]." Concretely: the
  10-week catches up to price first (fastest-reacting average), then the 30-week starts catching up and
  cutting through price, then the 40-week (slowest) also starts catching up — culminating in the
  averages visually **converging/compressing together** while price whips back and forth through all of
  them.
- **Psychological/institutional-flow interpretation**: this is read as **selling pressure exhausting**
  and institutional accumulation quietly beginning — even though (and this is explicitly emphasized as
  the counterintuitive, important part) **the news and sentiment at this point are typically at their
  worst**. Named real examples: Bitcoin's basing period coincided with the FTX collapse and the
  Silvergate/regional-bank failures — objectively terrible headline news — but price had already stopped
  making new lows, which is the tell that matters more than the headlines.
- **Explicit trap warning**: "if you try to anticipate and buy too early, you can get really chopped up
  and take a lot of unnecessary losses" — Stage 1 is explicitly classified (alongside Stage 3) as an
  **avoid stage for new entries**, not a stage to trade during, precisely because of this whipsaw
  characteristic. (Existing short positions from a prior Stage 4 would be where *scaling out/covering*
  activity happens during Stage 1 — see Section 9.)
- **Duration is highly variable and explicitly not fixed**: cited real examples range from **~6 weeks**
  (a short Stage 1, Abercrombie & Fitch's second base) up to **over 2 years** (ARK Innovation ETF, and
  separately ARKG genomics ETF basing for **~3.5 years**) — explicitly stated there is no reliable typical
  duration to anchor expectations on.
- **Institutional narrative interpretation of *why* accumulation restarts here**: possible drivers cited
  include anticipation of improving earnings/sales, sector-specific tailwinds (e.g. anticipated rate cuts
  benefiting homebuilders), or a specific news catalyst (explicitly cross-referenced to a separate Chart
  Fanatics episode on "episodic pivots," described as the mechanism that frequently *triggers* the
  Stage-4-to-Stage-1 transition — not detailed further in this transcript, treated as a companion concept
  to look up separately).

---

## 5. Stage 2 — Uptrend

- **Confirmed once**: 10-week crosses and holds above the 30-week and 40-week, price is trading above all
  three, and the averages are bullishly aligned (10 > 30 > 40) and sloping upward.
- **Actionable stance**: this is the **primary "should be looking to go long / hold longs" stage** for
  swing and position traders — explicitly the stage this entire framework exists to help identify and
  stay aligned with.
- **Internal structure while still healthy**: price makes higher highs and higher lows; the 10-week
  acts as dynamic support that price "surfs"; the 30-week and 40-week trail further below (since they're
  slower-reacting) but continue rising in parallel; periodic multi-week consolidations ("bases") form
  along the way as the 10-week catches back up to price, representing — same institutional-accumulation
  logic as Stage 1, but now happening *within* an already-established uptrend — a "proper supply and
  demand digestion" of the stock, with weaker/shorter-term hands (day traders, short-term swing traders)
  being shaken out and institutions absorbing that supply. Explicitly notes these consolidation lows can
  include shakeouts/undercuts specifically designed (from the institutional side) to flush out remaining
  weak hands before the next leg up.
- **A named favorite sub-setup, flagged but explicitly NOT covered in depth in this episode**: the **"first
  multi-month base"** — the first extended (multi-week to multi-month) consolidation that forms directly
  above the 10/20-week moving averages after the *initial* big linear leg out of the Stage 1 base into
  Stage 2. Described as one of his favorite setups; a live/current example (an unnamed rare-earth ETF
  position, described as a "Turbo" portfolio holding) was shown as illustration, complete with an
  explicit shakeout-and-reclaim pattern at the base's low before tightening up on the right side — but
  full entry/management rules for this specific sub-setup are deferred to a hypothetical future episode.
- **"Wyckoff"-style alternate/earlier entry variant also name-dropped without full elaboration**: buying
  the **first consolidation directly above the 40-week moving average**, following the initial move out
  of Stage 1 — described as one of several distinct nuanced entry philosophies compatible with the same
  underlying stage framework (also cross-referenced, not detailed).
- **Modern-market caveat, explicitly flagged as a change from historical behavior**: in "the 80s, 90s," a
  healthy Stage 2 uptrend (his examples: Abercrombie & Fitch, ARK Innovation ETF in their strongest legs)
  could run almost perfectly linearly above the 10-week with minimal drawback, offering few or no
  low-risk re-entry opportunities along the way. **In modern markets, he states Stage 2 uptrends much more
  commonly mean-revert back toward the 20/30-week averages** mid-trend — and because of this, his firm
  explicitly does **not** typically hold a single position through an entire Stage 2 from start to finish;
  instead they rotate capital into whichever name is *currently* breaking out of a fresh base, to avoid
  sitting through what can now be rapid 50%+ intra-uptrend drawdowns.

---

## 6. Stage 3 — Topping / Distribution

- **Structurally the mirror image of Stage 1**, both in mechanics and in the counterintuitive sentiment
  signal: **the best news and most positive sentiment cluster right at the top**, same as the worst news
  clusters at the Stage-1 bottom. Concretely worse than merely "good news stops working" — the transcript
  specifically calls out that sometimes it's genuinely *great* earnings/guidance that nonetheless triggers
  or accompanies the top, because "markets are a discounting mechanism" — institutions are pricing in
  expectations 6-12 months forward, not reacting to the trailing print itself.
- **Mechanical tell — same convergence pattern as Stage 1, applied in reverse**: after a large Stage-2
  move, price attempts a fresh breakout/new high and **fails** (a "failed breakout") — often specifically
  around a news/earnings event. The 10-week starts catching up to price from below (price stalling), then
  the 30-week, then the 40-week; price begins chopping between the averages ("wide and loose"); the
  averages compress/converge.
- **"Rate of change" concept, explicitly elaborated as the deeper conceptual tell (credits Stanley
  Druckenmiller's own similar framing, discussed on a separate podcast episode)**: visualized as
  tangent-line steepness against the price curve — a flattening rate of change (tangent line approaching
  horizontal) after a large move is the topping signal, structurally identical to the flattening-rate-of-
  change signal used to identify Stage 1 forming out of Stage 4, just mirrored at the top of a move
  instead of the bottom.
- **Three named example patterns for how a Stage-3 failed breakout can manifest around a news event**,
  offered as a taxonomy of what to watch for:
  1. Good news arrives, price barely reacts and essentially holds/tests existing resistance without a
     meaningful new move ("fails to make any sort of worse [sic, likely 'further'] meaningful move").
  2. Good news arrives, price *does* make fresh all-time highs on the news — but then fails/reverses
     shortly after ("this thing's probably done").
  3. Good news arrives, causes only a short-lived rally that fails quickly.
  - A real example of pattern-type reasoning (Abercrombie & Fitch) is referenced as a name he personally
    shorted on exactly this kind of signal.
- **Actionable stance**: same as Stage 1 — an **avoid-new-entries stage**. For existing longs carried
  from Stage 2, this is explicitly where **scaling out of the position** happens (see Section 9), not
  where fresh long entries are taken.
- **Duration**: also variable, cited examples running from a "quick" transition to "multiple months."

---

## 7. Fractal Nature Across Timeframes

- **Explicitly confirmed to be fractal — "100%."** The same 4-stage structure and moving-average logic
  can be applied on the **daily chart** (using 10/20-day-equivalent periods, or explicitly mentions daily
  10/20/50/200-day SMAs as one concrete variant used for a specific nuance trade, see Section 8.2) to
  identify shorter/faster "swing cycles," and hypothesizes even shorter application (e.g. hourly) for
  day traders, though he explicitly states he personally isn't a day trader and can't speak with
  authority to that use case.
- **His own firm's primary operating cadence**: weekly chart for identifying the dominant longer-term
  trend/stage, then **drop to the daily chart specifically for entries** (entry mechanics not covered in
  this episode).
- **Explicit tradeoff acknowledged between timeframes**: higher timeframes are described as visually
  "cleaner" (less noise) but require more patience to wait for stage transitions to actually develop and
  more discipline to hold/manage a position across that longer duration; lower timeframes require the
  same repetition-based pattern training to be applied fresh at that timeframe's own typical noise level
  and typical base/cycle durations — i.e., fractal applicability does **not** mean the weekly-chart
  intuition transfers directly to a 5-minute chart without separately building pattern-recognition reps
  at that specific timeframe.

---

## 8. Nuance Cases (explicitly flagged as such — real market behavior deviating from the clean textbook
sequence)

### 8.1 Good/bad news that contradicts the apparent price direction is a meaningful tell on its own

- Worked example (Abercrombie & Fitch): a name that appeared to be re-entering Stage 4 gapped down **on
  better-than-expected earnings** — explicitly flagged as a strong, distinct signal in its own right
  (not just "ignore the news because price rules") — a stock failing to rally, or actively selling off, on
  genuinely good news is itself informative about underlying institutional positioning, separate from the
  moving-average mechanics. This was the specific week he shorted the name personally.
- A separate instance of the same name later showed the **opposite** version of this tell: what looked
  like a fresh breakdown into Stage 4 (moving averages slicing through price, looking "messy") instead
  reversed into a **100% move off the lows** on a combination of a strong earnings report and a
  macro catalyst (Fed rate-cut environment) — explicitly presented as a paired example proving the same
  "watch how price reacts to news, not just the news itself" principle applies symmetrically at both
  extremes.

### 8.2 Ethereum — Stage-4 mean-reversion trade using a *daily*-chart variant

- A distinct, separately-named setup (attributed to Stan Weinstein, referred to as trading a
  "Stage 4-B-minus" condition): normally Stage 4 is avoided entirely, **except** when price becomes
  "extremely, extremely stressed" (i.e., unusually far extended below the 30/40-week averages) and then
  forms a **tight base specifically around the 10-week average** — this specific combination is
  described as tradeable as a **mean-reversion play back toward the 30/40-week averages**, still capable
  of capturing a substantial move despite technically occurring inside an overall downtrend stage.
- Concretely illustrated via Ethereum: the weekly chart didn't clearly show the base structure, so he
  switched to the **daily chart using 10/20/50/200-day SMAs** specifically to see a "super, super tight"
  shelf base that had formed just above the 10/20/50-day averages, entered there, and captured a
  reversion move up into the 200-day moving average.

### 8.3 Failed Stage 1 → Stage 2 breakouts (Moderna)

- Explicit worked example of a Stage 1 base that broke out into what looked like a clean, valid Stage 2
  ("a great buy... in hindsight it might not work, but from a stage analysis perspective, this is a great
  buy") — and then failed, dropping back into Stage 4, **an additional ~80% decline from that valid-
  looking breakout point** (on top of an already-realized ~75% decline from the prior all-time high to
  that breakout point).
- Explicit lesson drawn: **a technically valid stage-analysis signal is not a guarantee** — this is
  presented as the direct justification for why his firm trades this framework on a comparatively
  short/managed time horizon (with active stop-losses) rather than holding through an entire nominal
  Stage 2 unconditionally: "if we bought this, if we go on a daily chart, we'll definitely be out and
  we'll try it again if there's some other time."
- Contrast case immediately following in the same name: a **later**, cleaner Stage 1 breakout (flat base,
  clean bullish alignment across 10/20/30/40-week, and specifically accompanied by a clear
  forward-revenue-guidance catalyst) is presented as visually and structurally higher quality than the
  earlier failed attempt — explicitly attributed to that earlier instance having "more noise" (the
  whipsawing between Stage 4/Stage 1 multiple times beforehand) versus a genuinely clean single-pass
  sequence (his comparison examples of clean sequences: ARK Innovation ETF, Abercrombie & Fitch, the
  semiconductor ETF SOXX, Rocket Lab, E.L.F. Beauty).

### 8.4 Multiple failed Stage 1→2 attempts before an eventual real breakout (RGTI, quantum computing)

- Shown as a **live, in-real-time-narrated example**: a Stage 1 base attempted to break into Stage 2
  **three separate times**, with the first two attempts failing back into chop/Stage 3-like oscillation,
  before the third attempt was sustained by a specific news catalyst (Google's "Willow" quantum chip
  announcement).
- Explicit lesson: as long as risk is managed consistently on each individual attempt (accepting
  potential losses or breakevens on the failed first/second attempts), a trader following the system
  through to a successful third attempt can still capture a large move (his stated range for these
  eventual successful breakouts: **20-100%+**) — "which can make all the difference on a yearly P&L."

### 8.5 Volume as a secondary confirming/informing factor

- **On breakouts from a Stage 1 base**: higher volume on the breakout is explicitly stated to increase
  the probability the resulting Stage 2 move sustains, versus a low-volume breakout being more likely to
  fail.
- **On breakdowns into Stage 4**: explicitly asymmetric — **high selling volume is NOT required** for a
  valid/sustained breakdown; a stock can "fall on its own weight" purely from an absence of buyers, even
  without heavy active selling. States this asymmetry directly: "it doesn't have to be a lot of sellers,
  it can still collapse."

---

## 9. Position Management Framing (stage-conditional, explicitly distinguished from entries)

- **Stage 1 and Stage 3 are explicitly labeled "avoid stages"** for fresh entries — this is where
  whipsaw/chop risk is highest and where institutions are respectively accumulating (Stage 1) or
  distributing (Stage 3) — retail/smaller participants attempting to front-run either process are
  explicitly expected to get "chopped up."
- **Stage 2 and Stage 4 are the stages where positions are actually held/managed** — but the *transition
  points* are explicitly where the actual management activity concentrates:
  - **Scaling out of longs happens specifically as a name transitions out of Stage 2 into Stage 3**
    (not held blindly through the entire nominal Stage 2 duration, per the modern-market mean-reversion
    caveat in Section 5).
  - **Symmetrically, scaling into (or covering) shorts happens as a name transitions out of Stage 4 into
    Stage 1** — mirrored logic on the short side.
- **Jesse Livermore's "first eighth / last eighth" principle, quoted directly and applied explicitly to
  the stage framework**: "forget the first eighth of a move and the last eighth — they're often the two
  most expensive eighths of the move." Explicitly mapped onto the stages: the **first eighth corresponds
  to the Stage 1 basing region** (where trying to anticipate the breakout too early produces exactly the
  chop/whipsaw losses described above), and the **last eighth corresponds to the Stage 3 topping region**
  (same chop risk, mirrored). The actionable takeaway stated directly: aim to capture the "meat" — the
  well-established Stage 2 (or Stage 4, short side) — rather than trying to perfectly time the absolute
  bottom or absolute top.
- **Explicit acknowledgment this is an ideal, not a realistic guarantee**: "the reality of, was it getting
  in at the absolute bottom, getting out at the absolute top — obviously it's not possible... a lot of
  people will hold out, hold out, hold out, probably get blinded by what the P&L looks like, and then not
  actually manage or execute accordingly" — i.e., the framework's main practical risk isn't
  misidentifying stages, it's the emotional failure to act on a stage transition once correctly
  identified (a discipline/execution problem, not an analysis problem).
- **Mark Minervini's "50-80 rule," cited directly and used as an explicit risk-avoidance rationale**:
  when a market-leading stock completes its bull-market run and tops, there is stated to be a "50% chance
  it drops 80%, and an 80% chance it drops 50%" — used as the explicit justification for why avoiding
  Stage 4 entirely (rather than trying to time a bottom within it) is the firm's default posture,
  reinforced by the specific realized drawdown figures cited in Section 3.

---

## 10. Contrarian Positioning — Explicit Caution Against Being Contrarian Too Early

- Raised specifically in the context of a currently-live, still-developing situation (gold's multi-year
  Stage 2 uptrend, described at time of recording as beginning to show parabolic/vertical characteristics
  reminiscent of historical blow-off tops).
- **Explicit framework for deciding when contrarian positioning is/isn't warranted, credited to Stanley
  Druckenmiller**: contrarianism-for-its-own-sake is described as overrated, because "a lot of the money
  is made with the crowd" and the crowd is correct a large fraction of the time — and paradoxically, the
  bubble/euphoria phase specifically is cited as one of the phases capable of producing the largest gains
  in the shortest time, meaning premature contrarian positioning against a still-live euphoric move can be
  extremely costly, not just early.
- **Michael Burry's "Big Short" trade used as the explicit cautionary counter-example**: correct thesis,
  correct research, but the position still could have been liquidated before being proven right, because
  the market/crowd was able to remain on its existing path far longer than the fundamental thesis alone
  would have predicted — survived only because of a specific structural feature of his position (locked
  investor capital / inability for investors to redeem, discussed as the reason he personally didn't get
  forced out despite investor pressure to unwind).
- **Practical markers offered for identifying when a euphoric/parabolic move is genuinely reaching its
  late, riskier stage** (distinct from ordinary Stage 2 continuation), cited in the live gold/silver
  discussion:
  - Increasingly extreme/omnipresent media coverage and price-target speculation (cites a specific
    example of a $250,000 Bitcoin price target being floated in the same period).
  - Retail behavior signals — e.g. people physically lining up to buy physical gold, clients proactively
    asking about buying gold/silver unprompted.
  - Multiple large weekly gap moves in immediate succession (illustrated via the historical 1970s silver
    chart, where extreme weekly gapping preceded the eventual blow-off top) — explicitly distinguished
    from the comparatively "controlled" gapping seen in the current (at time of recording) gold/silver
    move, used as a stated reason he was not yet ready to call a top on the live position.
  - Structural/market-plumbing stress signals — e.g. brokerages raising margin requirements across the
    board on a commodity, cited as a real concurrent signal during the live silver discussion, explicitly
    described as something that "does not happen unless that euphoria and that move [is] happening."
- **Explicit stance: watch for these signals, but they inform *heightened attentiveness*, not an
  automatic trade** — he explicitly declines to call a top on the live gold/silver example during the
  recording, framing the decision as still open pending further confirmation of the described euphoria
  markers.

---

## 11. Log vs. Arithmetic Chart Scaling (a stated, deliberate technical choice)

- **Explicitly uses log-scale charts on longer (weekly) timeframes specifically to correctly compare
  percentage moves across very different price levels** — worked explanation: a move from $10 to $20 (a
  100% move) should visually read the same as a move from $100 to $200 (also a 100% move); on an
  arithmetic-scale chart, the higher-priced move would appear far larger in absolute chart distance even
  though the percentage magnitude is identical, which visually exaggerates apparent parabolic-ness at
  higher price levels and can mislead stage/topping judgments.
- Directly demonstrated on the 1970s silver chart, where he explicitly draws a sequence of increasingly
  steep tangent lines against the log-scale price curve to illustrate the Stage-3 "rate of change"
  concept concretely (Section 6) — flattening-to-vertical tangent slope as the visual proxy for
  unsustainable acceleration.
- **Explicit added observation**: assets that complete a genuinely parabolic (rather than merely strong
  linear) Stage 2 move are noted to often **top and reverse faster** than assets with a more linear
  uptrend — cited concrete example: 1970s silver made a ~150% move in ~10 weeks, then dropped ~72% in
  ~16 weeks (a fast, violent Stage 4 immediately following the parabolic blow-off).

---

## 12. Screening / Practical Workflow (explicitly stated to be manual, not automated)

- **Primary tool named: DeepView** (a charting/scanning platform) — uses basic price and average-volume
  filters, plus DeepView's built-in **relative/absolute strength ratings**, to generate momentum scan
  lists that, in his own stated experience, are mostly already-Stage-2 names by construction (so the
  scanner is used more as a first-pass momentum filter than as an explicit stage classifier).
- **Explicitly stated to rely primarily on manual visual pattern recognition ("I like to use my eyes
  more")** rather than an automated stage-classification system for the actual stage judgment itself.
- **Daily workflow described**: records a daily video (market open) covering cross-asset correlation
  across stocks, bonds, crypto, and other asset classes; separately reviews ETF lists (sector ETFs, thematic
  ETFs) not to screen names *out*, but specifically to build a qualitative read on **which sectors/themes
  are currently in which stage in aggregate** (e.g., "are homebuilders in stage four right now, or is tech
  in stage two").
- **DeepView's aggregate stage-distribution feature, used as a market-breadth/regime gauge**: the
  platform can plot the count of names across its entire universe currently classified into each of the
  four stages; watching this distribution shift (e.g., a rising share of names migrating into Stage 3/4)
  is used as a top-down signal for overall market health/risk appetite, independent of any single name's
  individual setup.
- **Explicit claim of pattern-recognition fluency from repetition**: states he can now visually classify
  a chart's stage "in a second," attributing this purely to the volume of historical repetition (having
  reviewed what he describes as hundreds of thousands of charts over time) — directly analogous to the
  "training the eyes" concept described in the Marco Trades companion doc, though arrived at
  independently and for a different (regime-classification rather than entry-trigger) purpose.

---

## 13. Cross-Asset Validation (as explicitly demonstrated live, preserved for calibration)

Explicitly framed as proof the framework is genuinely universal, not equity-specific — worked through
live across every major asset class in a single sitting:

- **Equities**: ARK Innovation ETF (textbook full 4-stage cycle, ~1-year Stage 2 move, ~2-year-plus
  Stage 1 base after), Abercrombie & Fitch (two full cycles shown, including the good-news-gap-down
  Stage 4 nuance from Section 8.1), semiconductor ETF SOXX, ARK Genomics ETF (ARKG, ~3.5-year Stage 1
  base still in progress at time of recording, an actual current firm holding — explicit disclosure
  given), E.L.F. Beauty, Nvidia (Stage 3/4/1/2 cycle explicitly tied to the ChatGPT launch catalyst),
  Super Micro Computer (SMCI, explicitly framed as a less durable/differentiated theme — "racks aren't
  proprietary" — versus Nvidia's GPU moat), Tesla (2019 catalyst-driven ~2,500% Stage 2 move, ~76%
  eventual Stage 4 drawdown), IonQ and Rigetti (RGTI) quantum-computing names (the latter shown as a
  live, real-time-narrated three-attempts-before-breakout example per Section 8.4), Rocket Lab, Planet
  Labs, Moderna (the failed-then-successful breakout pair from Section 8.3), and a current/live
  unnamed rare-earth-elements ETF position (the "first multi-month base" illustration from Section 5).
- **Crypto**: Bitcoin (multiple full cycles across its history, explicitly noted to currently be in Stage
  4 building a "downside continuation base" at time of recording, contrasted against contemporaneous
  $250K price-target speculation as a specific example of separating narrative from confirmed price
  structure — see Section 10), Ethereum (including the daily-chart Stage-4-mean-reversion nuance trade
  from Section 8.2).
- **Commodities**: Gold (both a 1970s stagflation-era full cycle and the current multi-year Stage 2 move,
  explicitly described as one of the best cup-with-handle base structures he's seen, a ~10-year base),
  Silver (the 1970s parabolic blow-off used for the log-chart/rate-of-change illustration in Section 11,
  plus live commentary on the contemporaneous 2025-era move), Cocoa futures (a supply-shock-driven Stage 2
  explicitly attributed to a crop fungus/disease event in African cocoa farms), Orange Juice futures
  (similarly attributed to a citrus tree disease event), Coffee futures, and Uranium (spot uranium and
  two related miner ETFs — URNM, URA — presented as an explicitly live/current, AI-power-demand-driven
  setup, described as a "bonus" example not originally planned for the episode).
- **Fixed income**: US 10-Year Note futures (full cycle including the 2020-2023 Stage 4, tied explicitly
  to the 2022 inflation shock) — used to make a broader point about **traditional "60/40" pie-chart
  portfolio construction failing in 2022**, since bonds fell alongside stocks rather than providing the
  expected offsetting ballast; explicitly demonstrated that a simple stage-analysis read of the bond chart
  (or, equivalently, its inverse relationship to the 10-year Treasury yield) would have flagged this risk
  in advance of the simultaneous-drawdown outcome that hurt many near-retirement clients under
  conventional advisory models.
- **Currencies**: US Dollar Index (DXY) futures — full cycle tied explicitly to 2020-2022 Fed policy
  (QE-driven Stage 4 decline, then rate-hike-driven Stage 2 rally into 2022), noted to be showing early
  Stage 1/potential-Stage-4 characteristics again as of the live recording date.

---

## 14. Gaps — not fully specified in source (need decisions if codifying)

- **Entry mechanics are explicitly and deliberately out of scope for this episode.** Stage analysis is
  presented purely as a **regime/trend-alignment filter** — "what is the direction of the longer trend,
  and do I have that wind behind me" — not as a complete entry/exit system. The referenced companion
  concepts (episodic pivots, the first multi-month base setup, the Wyckoff-style first-consolidation-
  above-the-40-week entry) are all explicitly named but explicitly deferred, with no rules given here.
  Any implementation would need one of those (or an independent entry system) layered on top of the
  stage classification to actually trigger trades.
- **No precise numeric definition given for "flattening rate of change"** — described consistently via
  visual/tangent-line analogy rather than a formal slope-threshold or moving-average-slope-derivative
  calculation. Would need a concrete formalization (e.g., a rolling-window slope of the 10-week SMA
  crossing below some threshold, or a normalized ROC indicator with a stated lookback and threshold) to
  automate the Stage 1↔2 or Stage 3↔4 transition timing precisely — as presented, it's a trained-eye
  judgment call.
- **No explicit stop-loss placement rule given** — stop-losses are referenced as existing and as the
  explicit reason failed setups (Moderna, the earlier RGTI attempts) get exited rather than held through
  further drawdown, but no specific placement logic (e.g., below the base low, below the 30-week, a fixed
  percentage) is stated anywhere in this transcript.
- **No explicit position-sizing rule given** — unlike the Steven Dux and Fabio Valentino docs (which both
  give explicit percentage-of-account or percentage-of-float sizing rules), this transcript contains no
  comparable stated sizing methodology.
- **The DeepView relative/absolute strength scoring methodology underlying the momentum scans (Section
  12) is referenced but not defined** — it's used as a pre-filter to surface likely-Stage-2 candidates,
  but the platform's internal calculation isn't explained, and no alternative formula is offered for
  reproducing it independently.
- **"First multi-month base" and "Wyckoff-style first consolidation above the 40-week" sub-setups
  (Section 5) are named but explicitly not detailed** — flagged directly in-transcript as material for a
  hypothetical future episode; would need independent research to formalize if desired.

---

## 15. Rules-Layer Sketch (for engine integration)

Suggested pipeline order, mirroring the structure used for the other four strategy docs — with the
explicit caveat that, per Section 14, this framework alone only answers "what regime is this asset in,"
not "trade now" — it's meant to compose with an entry/exit system, not replace one.

1. **Reference average computation** — compute 10-week, 20-week (secondary/confirming), 30-week, and
   40-week simple moving averages on the weekly chart for each candidate instrument, across all asset
   classes the engine covers (equities, crypto, commodities, rates, FX) — the framework's core claim is
   this generalizes uniformly.
2. **Stage classification** — classify each instrument into one of the four stages based on (a) price
   position relative to all three/four averages, (b) the pairwise ordering of the averages themselves
   (bullish-aligned 10>30>40 vs. bearish-aligned 10<30<40 vs. converged/crossing), and (c) a
   rate-of-change proxy on price and/or the 10-week average (needs formalization per Section 14) to
   distinguish "clean Stage 2/4" from "Stage 1/3 convergence chop."
3. **Regime gate for new entries** — restrict new long entries to instruments currently classified Stage
   2 (or freshly transitioning 1→2 with bullish-aligned averages); restrict new short entries
   (personal/prop capital only, per the client-account constraint noted in Section 3) to Stage 4 (or
   freshly transitioning 3→4). Explicitly suppress new entries for instruments in Stage 1 or Stage 3
   given the framework's own "avoid stage" classification.
4. **News/catalyst cross-check** — where available, flag divergences between price reaction and
   contemporaneous news sentiment (good news + no follow-through or a down move = bearish tell; bad news
   + price refusing to make new lows = bullish tell) per Section 8.1, as a secondary confirming/
   disconfirming signal layered on top of the pure price/average classification.
5. **Volume-confirmation layer** — weight Stage 1→2 breakout signals by relative breakout volume
   (higher = higher expected follow-through probability per Section 8.5); do NOT require elevated volume
   to validate a Stage 2→4 breakdown signal, given the stated asymmetry.
6. **Position management triggers, stage-transition-based rather than fixed-R/time-based** — trigger
   scale-out logic for existing longs specifically on a Stage 2→3 transition signal (not on a fixed
   profit target), and trigger scale-in/cover logic for existing shorts on a Stage 4→1 transition signal —
   mirrors the "first eighth / last eighth" avoidance principle from Section 9.
7. **Drawdown/risk-budget overlay** — given the stated realized Stage-4 drawdown range (~66-78%+ across
   worked examples) and Minervini's 50-80 rule cited as explicit justification, apply a hard portfolio-
   level exposure cap or automatic de-risking trigger for any position that re-enters Stage 4
   classification, rather than relying on discretionary judgment alone to force the exit.
8. **Fractal/multi-timeframe generalization** — allow the same classification pipeline to run
   independently at multiple timeframes (daily, weekly, and optionally intraday) per instrument, per
   Section 7 — but do NOT assume parameters (base durations, typical drawdown magnitudes, typical stage
   lengths) transfer directly between timeframes; each timeframe likely needs its own empirically-tuned
   expectations, consistent with the "separate reps needed per timeframe" caveat.
9. **Breadth/regime overlay (portfolio-level, not per-instrument)** — track the aggregate distribution of
   the engine's tracked universe across the four stages over time (mirroring DeepView's stage-count
   feature, Section 12) as a top-down market-health signal, independent of any individual instrument's
   setup quality.
10. **Explicit non-goal**: this layer alone does not generate entries/exits/sizes — it is a **filter and
    context layer** meant to gate and inform whichever entry/exit system (from this doc set or elsewhere)
    is actually used to execute, consistent with how the source material itself explicitly scopes stage
    analysis.
