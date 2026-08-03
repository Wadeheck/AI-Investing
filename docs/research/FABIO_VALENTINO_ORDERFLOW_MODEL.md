# Order-Flow Scalping Model — Fabio Valentino (Chart Fanatics)

Source: "This guy is the best scalper" — Chart Fanatics podcast, live NQ order-flow breakdown with
Fabio Valentino (top-3 world ranking, Robins Cup futures, ~500% 12-month return). Transcript digested
in full (3,462 lines) and distilled below. Kept detailed and literal on purpose — this is meant to be
turned into codifiable rules, not prose.

---

## 1. Core Philosophy: Auction Market Theory (AMT)

The market is not always trending — it's an auction oscillating between:

- **Balance**: efficient two-sided trading, market spends most of its time here.
- **Imbalance**: one side is aggressive, market is searching for a new balance point.

Most retail traders lose because they apply trend-following / market-structure concepts (break of
structure, change of character, supply/demand) **without first checking which state the market is in**.
Statistically, only ~30% of trend-following entries taken from inside a balanced/fair-value area work —
the rest get stopped out repeatedly until the market actually breaks out.

**Filtering entries by market state alone is claimed to improve win rate by 20–30%.**

He explicitly rejects calling this a "strategy" (a rigid rule-set) — he calls it a **model** (a framework
for reading market narrative), because markets are dynamic and adapt daily (news, volatility regime,
session). The 3-step process below is applied fresh each session, not mechanically pattern-matched.

---

## 2. The 3-Step Model

Applies to both trend and mean-reversion variants (Section 3).

### Step 1 — Market State (the gate)

Only trade once the market is confirmed **out of balance**. Determine via volume profile: is price at a
swing high/low with a clear breakout, or still inside a fair-value/consolidation range? If balance →
stand down. This is the #1 filter that keeps overtrading/gambling out.

### Step 2 — Location / Refinement

Plot the **volume profile of the swing/impulse leg** (point A → point B of the move) and find the
**Low Volume Node (LVN)** — the price band with the least transacted volume in that range. This is his
functional substitute for "fair value gap" / inefficiency, except defined by actual traded volume rather
than candle geometry.

### Step 3 — Execution / Trigger (Aggression)

Do not place a limit order at the LVN. Place a **price alert slightly before it**, then wait to visually
confirm a **large aggressive order** (a "big trade"/"bubble" on an order-flow platform) printing at that
zone. Entry trigger = a big aggressive order matching the trade direction firing at the refined level.
This converts the trade from "predicting" to "reading and reacting."

---

## 3. The Two Models

### Model 1 — Trend / Momentum Continuation ("aggressive" model)

- **Session**: New York only (NASDAQ/NQ, equities). Does NOT work well in the first hour of London —
  too many fakeouts/whipsaws there for a trend-following model.
- **Setup**: Market breaks out of balance (swing point breaks). Map the volume profile of the breakout
  leg → find the LVN.
- **Trigger**: Price retraces into the LVN and a large aggressive order (same direction as the breakout)
  fires at that level.
- **Stop**: Placed just beyond the aggression cluster (tight, not at the swing extreme) — keeps risk
  small relative to potential reward.
- **Target**: The previous balance area (prior session's Point of Control / value area) — "the market
  moves as a search for the next balance." Take the **full position** at target, not partial — ~70%
  chance of reversal beyond it, not worth holding for the extra 30%.
- **Timing rule**: Never hold overnight (extra futures margin, not worth it). Trade only in NY session
  with this model.
- **No-trade zone**: Never trade pre-market open — you see the "battle" (buy/sell bubbles) but can't yet
  tell who wins, since price is testing the dealing range before the real session direction sets
  (typically clear 15–20 min into the open).

### Model 2 — Mean Reversion ("counter" model)

- **Session**: London session, and also entire **compressed/choppy regimes** (e.g. summer months,
  late March–August, low-volatility periods) where trend-following gets chopped up. Statistically,
  London/consolidation periods favor mean reversion since indices bounce rather than trend.
- **Setup**: Identify a **consolidation/balanced market** — use either the prior day's full session
  profile (simple/default) or a manually-drawn profile around the specific compression zone (advanced,
  more precise).
- **Key rule — do NOT take the first breakout/spike out of the range.** Wait for it to fail and snap
  back inside balance. The first move = high fake-out risk; the retracement/second drive back into the
  range is the actual signal ("we never take the first drive").
- **Trigger**: Same as Model 1 — wait for confirming big-order aggression (buy-side bubbles at the low,
  sell-side at the high) before entering; don't front-run with price action alone.
- **Target**: The **Point of Control (POC)** — the price with the most volume transacted, i.e. the
  "fair" auction price. Objectively where the bulk of orders sit, hence the highest-probability magnet —
  NOT the opposite extreme of the range (a stated common beginner error).
- **Stop-loss anti-slippage trick**: place the stop **1–2 ticks beyond the actual high/low**, not exactly
  at it. Round levels and prior day/week highs/lows cluster resting stop orders and cause acceleration
  through them — sitting exactly at the obvious level gets run over with extra slippage.
- **Be wrong immediately**: if wrong, take the tiny stop right away rather than widening it hoping for a
  snap-back — framed as the single biggest account-killer for inexperienced traders.
- **Move to breakeven fast** (but conditionally, see Section 6) once a second confirming impulse fires in
  your favor.

---

## 4. Confirmation Rules (the actual entry gate)

The mechanical checks that separate "interesting" from "execute":

- **Full-body candle close required, never a wick/tap.** "If it closes inside, I'm not engaging." A
  level being touched or wicked through is NOT a signal — only a candle that opens and closes fully
  beyond the level counts. On a 1-min chart this means waiting for that minute to complete.
- **The confirmation bar rises with every failed test.** "Every time you reject, the setup gets weaker...
  so every time I get more demanding from my setup." Operationally: each failed test at a level should
  raise the bar for the next attempt (e.g. first test needs a close above the box; second failed test
  needs close above the box **plus** visible big-order absorption) — a decaying-confidence counter, not
  a fixed re-used threshold.
- **"Close above the box"** = the candle must close beyond the entire consolidation range boundary, not
  just beyond the immediate micro trigger level. Track two distinct lines: the micro-level (LVN/
  aggression cluster) and the macro box (the whole consolidation range).
- **Never enter on the first drive** — both models require the second touch/drive at a level.
- **Skip if volatility is opaque.** If big-order bubbles are so dense/frequent that price action becomes
  unreadable ("your market gets flooded... it's not visible the price"), treat that as a stay-out signal,
  not a strong one.
- **Skip impulses with zero retracement / low liquidity** — explicitly flagged as "impossible to
  execute"; don't backfit a trigger onto a move that never offered a re-entry structure.

---

## 5. Order-Flow / Big-Trade Filter — exact parameters

- **Threshold: ≥30 contracts on NQ (1-min or 5-min chart) during NY session. ≥20 contracts during
  London session.** Concrete, stated, session-dependent values.
- Below-threshold prints are rendered in a different color (yellow on his platform) = explicitly
  irrelevant, filtered out.
- **Bubble/marker size is rendered proportional to contract size** — used as a fast visual read instead
  of clicking into each print.
- **Executed market orders only** — resting limit orders are explicitly not used as a signal ("I never
  watch limits... they can cancel" — spoofing risk). Signal = trade prints/executions, not order-book
  depth.
- **Delta-by-price-level ("who's dominating")**: platform shows, per price level, whether buy or sell
  volume dominated. Check this before entering a breakout — if a level was already dominated by buyers
  on the way up, it's a worse level to buy (already "expensive," less fresh aggression left).
  Conversely, a level with a big sell delta that later breaks out upward = high-quality long trigger.

---

## 6. Volume Profile / LVN / POC — how it's built and read

- Profile is drawn from the **start to the end of the specific swing/impulse leg** being analyzed (point
  A to point B), not a fixed daily window, for the refined/advanced version. The simple version just
  uses the **prior full day's profile**.
- **LVN** = the price band with the least transacted volume within that plotted range — a valley in the
  horizontal volume histogram.
- **Value Area High / Value Area Low** = the boundaries of the profile — used as pivots to validate
  accumulation/distribution framing.
- **POC (Point of Control)** = the single price with maximum volume — primary reversion target for
  Model 2, and the reference for "expensive vs cheap" framing.
- Entry mechanic at an LVN: place a price alert slightly before/below it (never a resting limit order at
  the LVN itself), then manually trigger only after visually confirming a big aggressive print there.
- **Breakeven timing is conditional, not automatic on a fixed R-multiple.** Move to breakeven on the next
  confirming impulse/big print in your favor — but delay if there's a nearby LVN that could cause a fast
  wick/spike-out ("I will still not go risk-free too fast because I think we will test this level").
  Check for adjacent LVNs before auto-arming a breakeven stop.

---

## 7. CVD (Cumulative Volume Delta) — verification use

Plotted as a running line alongside price. Two checks:

1. **Confirmation**: CVD trending the same direction as price (e.g. price grinding up, CVD also
   climbing) = genuine aggressive-buyer pressure → safe to move stop to breakeven early, ahead of price
   structurally confirming.
2. **Divergence (warning)**: price makes a new high/print but CVD fails to make a new high alongside it
   = "there is something big here" — a caution flag the move isn't supported and may reverse. Used to
   avoid an otherwise-tempting continuation trade, or to take profit early on an existing one.

He names the underlying method **Volume Spread Analysis (VSA)** explicitly — the relationship between
price movement and the volume/delta producing it (e.g. "punching a wall": heavy sell volume printed but
price barely moves = absorption by resting buy-side limit orders, a bullish tell even though the tape
looks sell-dominated).

---

## 8. Absorption / No-Follow-Through — the core recurring tell

The single most repeated verification pattern in the whole transcript:

- **Aggressive orders print (big red or green bubble) at a level, but price does NOT move in that
  direction afterward** = absorption. The passive side (limit orders) is stronger there.
- Check both directions: sellers aggressive + no downside follow-through = bullish tell; buyers
  aggressive + no upside follow-through = bearish tell.
- The inverse — aggression AND matching price follow-through — is the "facilitated" case, treated as
  confirmation the move is real.
- **"Punch on the wall" / "lock-in" pattern**: overlapping opposing-color big-order clusters at nearly
  the same price (visually like two overlapping logos) = a genuine two-sided battle/contested level,
  worth marking as a decision point in either direction.

---

## 9. Stop-Loss Mechanics

- **Anti-slippage placement**: stop goes 1–2 ticks beyond the actual invalidation point (below the
  aggression cluster / below the low), not exactly at the round-number high/low, since those levels
  cluster resting stops and cause acceleration through them.
- **Stop is set at the level that invalidates the setup's logic, not a fixed tick distance.** If price
  closes back inside the box, the trade thesis is dead regardless of stop distance — "you cannot get
  stopped out for no reason."
- **Dollar-risk normalization via contract count, not stop distance.** If the natural stop implies only
  $280 risk on 1 contract but target risk is $500–600, he adds contracts to hit the intended dollar risk
  rather than widening the stop. Contract count is the sizing lever; stop distance is fixed by market
  structure.

---

## 10. Target Selection Hierarchy

1. **Highest win-rate target** = previous session's daily high/low or the prior balance area's POC —
   stated default, best statistical hit-rate.
2. Extending the target further (a further prior high, or trailing indefinitely) trades win-rate for
   R:R — explicit tradeoff, not a free upgrade. 1:2.5–1:5 is "common"; 1:10–1:20 only happens on days
   with outsized NASDAQ % range (2–3%+); reaching for 1:10 on a 0.25–0.5% range day is a mismatch
   ("not in tune with the market").
3. **Round numbers** (explicitly calls out 22,000 on NQ) are treated as natural accumulation/
   distribution magnets independent of the profile — a discrete feature worth flagging alongside
   volume-derived levels.

---

## 11. Multi-Week / Higher-Timeframe Pattern (distribution warning)

Named pattern: **4 consecutive weeks of price taking out the prior high without creating new value**
(i.e. not building a higher POC/value area behind it) = distribution signature, raises probability of a
swing-level collapse. A weekly-resolution overlay on top of the intraday model — implement as a separate,
lower-frequency feature (compare each week's high vs. whether value area actually advanced).

---

## 12. Session / Instrument Discipline

- **Single-instrument focus, deliberate**: tried NQ + Crude Oil simultaneously and called it too much
  cognitive load ("I was a therapist" — needed one). Assumption baked into the model: one instrument's
  order-flow read at a time, not a simultaneous portfolio-wide scan.
- **Session-conditional regime re-labeling mid-session**: not just "use Model 1 in NY" — he actively
  downgrades the day's regime based on live evidence (e.g. from trend-following to "just survive/
  breakeven" mode once price shows repeated compression/failed breakouts). Correct behavior in a
  degraded regime = lock in small profit and stop forcing trades, not keep firing the same setup at a
  lower hit-rate.
- Best window: **first 15–20 minutes of NY open** determines the day's real directional bias; avoid the
  5–10 minutes immediately pre-open (fake positioning/whipsaw).
- Monday and Friday are his statistically weakest days (lower profit factor, less "explosion").

---

## 13. Money Management — the compounding mechanic

- Realized intraday profit becomes the "stake" for subsequent same-day risk — never fresh account
  equity. E.g. after banking $250, he'll risk up to that $250 (sometimes 2x) on the next setup, never
  risking back into capital that predates that day's trading.
- **Daily hard stop: 2% max account loss**, a ceiling regardless of how many individual small stops that
  represents (cites taking 8–11 stop-losses in a day while staying inside 2% because each is sized tiny).
- **Per-trade risk**: 0.25% of account (personal account), up to 0.5% in prop/competition accounts,
  occasionally 1% only after >100% return cushion.
- Explicitly avoids letting large unrealized floating profit ride uncapped — cites floating +$28,000 and
  giving it all back (plus more) by refusing to lock in. Extracted rule: once a session profit target is
  hit, close/lock it rather than let a single reversal erase multiple days of edge.
- **Commission awareness**: at his volume (~600 executions/quarter) commissions alone can eat 10–20% of
  the account — sizing/frequency must account for this as a direct drag on edge.

---

## 14. Edge Decay

Rule-based price-action systems (e.g. "moving average + add on retest") decay when volatility regimes
shift (the swing length that used to trigger add-ons changes, causing a stop-out cluster even when
directionally right). He argues order flow doesn't decay the same way because it reads the market's
actual mechanics (real buyer/seller aggression) rather than a fixed geometric rule — the adaptation
required is in risk/trade management, not in re-deriving new pattern rules each regime change.

---

## 15. Pros / Cons (as stated)

**Cons**
1. Compression/chop days directly hurt Model 2's win rate — this is why both models run side by side, to
   smooth the equity curve.
2. High psychological stress at real position sizes (losing a "used to be a salary" amount in 2–3
   minutes).
3. Heavy time commitment — cannot be done part-time; requires full session presence for entries +
   active management (not "set and forget").

**Pros**
1. High trade frequency → faster drawdown recovery and a statistically robust sample (cites ~2,400
   executions/12 months vs ~30 for a long-term model — more attractive to allocators).
2. "No headache" — no prediction, only reaction to confirmed conditions.
3. Structurally resistant to revenge trading (entries require the full 3-step confluence; if conditions
   aren't present you can't chase).
4. Occasionally very high R:R (1:5 common, 1:10–20 on strong-trend days) when in sync with momentum.

---

## 16. Gaps — not fully specified in source (need decisions if codifying)

- **Volume-profile calculation window/method** isn't algorithmically defined — he draws it manually per
  swing. Need to pick a formal LVN-detection method (e.g. minimum-volume-bin threshold within the
  impulse's price range).
- **"Aggression" trigger is fundamentally a discretionary visual read of tape/prints**, beyond the
  20/30-contract filter. To automate, "no follow-through" needs a hard definition, e.g.: an X-contract
  print followed by less than Y ticks of favorable price movement within N subsequent bars.
- **No explicit look-back window for "the swing"** when drawing a profile — manual chart judgment in
  every example shown.

---

## 17. Rules-Layer Sketch (for engine integration)

Suggested pipeline order if implementing as a filter stack:

1. **Market-state filter** — balance vs imbalance (Step 1).
2. **LVN/POC detection** on the relevant swing leg (Step 2).
3. **Big-print filter** — ≥30 contracts (NY) / ≥20 contracts (London), executed market orders only.
4. **Absorption / no-follow-through check** — aggressive print + subsequent price non-response.
5. **Confirmation-candle gate** — full-body close beyond both the micro level and the macro
   consolidation box; confirmation bar increases with each prior failed test at that level.
6. **Dynamic stop** — placed at logical invalidation point, offset 1–2 ticks for slippage; contract
   count solved for target dollar risk, not stop distance.
7. **Target** — prior balance POC / prior session high-low first, tiered further targets trade win-rate
   for R:R explicitly.
8. **Session/regime layer** — NY = Model 1 default, London/compressed regimes = Model 2 default,
   live regime downgrade if repeated failed breakouts.
9. **Money-management layer** — 2% daily stop, 0.25–0.5% per-trade risk, profit-funds-further-risk
   compounding within the same day only.
