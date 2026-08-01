# Scalp model — synthesis of the six trader docs (2026-08-01)

Six docs digested critically by parallel readers: FABIO_VALENTINO_ORDERFLOW,
GALA_TRADES_PRICE_ACTION, MARCO_TRADES_DA_VINCI_LIQUIDITY,
STEVEN_DUX_SMALL_CAP_SHORT, TED_ZACK_STAGE_ANALYSIS, JEFF_HOLDEN_SMB_MOMENTUM.

## Verdict in one paragraph

None of the six is adoptable as written: every one leans on discretion at the
decisive moment ("respects the level", "aggression", grade A+ vs B), none
publishes a win rate or sample, and all are survivor narratives. What they DO
supply, consistently, is (a) a set of mechanical, testable primitives that are
fully computable from FREE Binance data, and (b) risk-management scaffolding
that is more robust than their signals. The fee math is the ruling constraint:
at 1-minute scale, structural stops (3–15 bps) are SMALLER than round-trip
costs, so any literal port is fee-negative before the edge question is asked.
The module below therefore trades 5-minute structure, enters with resting
LIMIT orders (maker), enforces a minimum stop distance of 5× round-trip cost,
and uses the docs' order-flow reads as VETOES (fewer trades) rather than
triggers (more trades).

## What went where

### Into the daily engine (candidate trainer rounds / features, NOT yet wired)
- MA-stack score 50/150/200d with an ABSTAIN state + universe breadth histogram (Ted)
- Volume asymmetry: breakouts need volume, breakdowns don't (Ted)
- Confirmed-level filter (two pivots agree within 0.25·ATR) + sweep-and-reclaim
  daily bar + pre-trade R:R ≥ 3 gate (Marco)
- Value-area regime gate + prior-period POC as target (Fabio)
- Green-run dollar-volume escalation counter with reset-on-red — refines
  political_hype's fade timing; reset-and-continue runs are NOT exhausted (Dux)
- Grade-conditioned sizing vs a DAILY stop budget + precondition-encoding
  ("this rule only fires when X") instead of global parameter drift (Jeff)

### Into the scalp module (engine/ai_investing/scalp/, crypto perps, paper)
- S1 sweep-reversion: confirmed 5m level + 1m wick sweep + body reclaim →
  limit at the level, stop past the wick (ATR-floored), target 2R (Marco+Gala)
- S2 break-and-retest: 5m body close through a confirmed level, retest body
  holds → enter, stop at cluster extreme, target 2R (Gala)
- S3 exhaustion fade: ≥3 escalating dollar-volume green 1h bars + stretched
  24h return → fade on first 5m close back through EMA9; reset-on-red rule
  vetoes fading healthy runs (Dux, long-exit first, short only in paper)
- S4 momentum continuation: higher-low + consolidation break + volume
  expansion + BTC-alignment gate; exit = trail on first 5m CLOSE below EMA9
  (Jeff). BTC-alignment enables the aggressive variant only.
- Vetoes from order flow (Fabio, free via taker-buy volume + trade counts):
  CVD divergence, absorption (big delta with no follow-through), first-drive
  rule (second test required), value-area gate per strategy family.
- Risk scaffold: 0.25% risk/trade, 2% daily loss halt, structural stops with
  a floor of 5× round-trip cost, ≤1h time stop, per-day trade cap, post-stop
  no-reentry at the same level.

### Rejected outright
- Anything requiring the wick-tight stops the docs brag about (fee-dominated)
- Session/open-anchored rules (no cash open in crypto), options premium rules
- Dux's short-side microcap machinery (borrow reality; engine is long-biased)
- 30/20-contract magic constants, Bookmap/L2 history (not free), all
  "trained-eye" filters
- 1-minute execution: 5m bars only; 1m used solely to detect sweep wicks

## Fees modeled (Binance USDT-perp public schedule)
maker 2 bps, taker 5 bps, slippage 2 bps on stop fills. Entries and targets
are resting limits (maker); stops pay taker+slip. Round trip ≈ 9 bps worst
case → minimum stop distance 45 bps.

## Pre-committed kill rule (before looking at results)
A strategy family ships only if, on the UNSEEN 30% holdout: net > 0 after
fees AND daily Sharpe ≥ 0.5 AND it survives the taker-only fee scenario
without flipping sign catastrophically. Families that fail are reported
honestly and disabled in the live loop (visible on the dashboard, not traded).
