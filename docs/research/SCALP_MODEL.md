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

## 2026-08-19 rebuild re-test — also killed, all families, all cost scenarios

The 2026-08-01 backtest above killed S1–S4 on 5m structure. A rebuild was
written 2026-08-12 (`engine/ai_investing/research/scalp_lab.py`) diagnosing
why: the 45bps stop floor ate 20% of every trade's risk budget on majors
whose 5m ATR is ~8bps, so the sweep was retesting one repeated trade, and the
only family with gross edge (S2_retest) turned out to hold for hours, not
minutes. The fix — 15m structure, stops wide enough that fees are a rounding
error, 12 symbols × 240d instead of 3×60d, config picked on TRAIN only before
a single holdout look — was written and never run. It sat for a week with no
verdict.

Prompted by the question "does the crypto event sleeve have real ammo for
fast trading" (see `crypto_event_sleeve.py`'s module docstring), it was run
to completion: 240d of 1m Binance klines pulled for all 12 symbols
(`data/scalp_history_wide/`, gitignored — regenerate with
`scalp_fetch_data.py 240 scalp_history_wide <SYMS>`), then
`scalp_lab.py --build` across all three cost scenarios.

```
                    binance_perp (2/5/2bps)   repo_crypto (15/15/0bps)   gemini_real (25/35/5bps)
breakout            holdR -0.199 t -8.08       holdR -0.313 t -10.35      holdR -0.525 t -17.01
  net -42.3% Sharpe -3.85  0% syms+            net -53.6% Sharpe -6.81    net -76.6% Sharpe -12.56  0% syms+
retest              holdR -0.174 t -2.16       holdR -0.268 t -3.79       holdR -0.471 t -6.52
  net -20.3% Sharpe -3.57  17% syms+           net -24.9% Sharpe -5.22    net -39.1% Sharpe -8.64
revert              holdR +0.194 t +1.65       holdR +0.264 t +2.32       holdR -0.006 t -0.05
  net +3.2%  Sharpe +1.67  67% syms+ (t<2.0)   net +5.1% Sharpe +2.44 (clears t)   net -2.2% Sharpe -1.43

cross-sectional momentum (12-symbol panel, best of 90 train-selected configs):
  holdout net -11.6%, Sharpe -3.66 — killed at Gemini's real cost schedule.
```

**All killed, at every cost scenario.** `breakout` and `retest` trigger on
volatility spikes, exactly where slippage is worst — they get WORSE at real
costs than idealized ones (breakout: -42% -> -77% going from binance_perp to
gemini_real). `revert` (mean-reversion) is the only family with any real
signal — it clears the t-stat gate under repo_crypto's assumed 15bps flat
fee — but flips negative the moment it meets this account's actual Gemini
ActiveTrader schedule, and the sample is thin (67 holdout trades). No family
clears the pre-committed gate anywhere; none was promoted past this file.

**Conclusion.** This is the same result the 2026-08-01 backtest found, this
time on 4x the sample and the venue's real fee schedule, and it agrees with
`crypto_event_sleeve.py`'s independent finding on the shorts question: at
this venue's costs, a faster clock does not create edge, it just pays more
fees per unit of opportunity (`scalp_lab.cost_vs_move()` has the arithmetic).
The crypto event sleeve's 1-day hold, news-shock-driven design was left
unchanged — there is no validated intraday signal to feed it. `scalp.live`
(the paper forward-test loop) was not restarted; its verdicts source
(`data/scalp_backtest.json`) still reflects the original 2026-08-01 run and
should be regenerated from `scalp_lab_report_*.json` before anyone points a
live loop at these families again. Reports:
`data/scalp_lab_report_{binance_perp,repo_crypto,gemini_real}.json` on the
ProDesk (gitignored, not in this repo).
