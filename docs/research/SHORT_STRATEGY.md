# Bear-Profit Short Sleeve — design spec (v1, 2026-07-30)

**Objective**: make bearish periods *profitable*, not merely survivable, while
never violating the standing mandate (capital preservation first; no position
loses >10% unstopped; book maxDD ≤ 25%).

**Status**: designed and backtested on 11.5y of real BTC/ETH/SOL data
(2015-01 → 2026-07) under the anti-cheat protocol: parameters tuned only on
train (2015→2021-05), verified on holdout (2021-05→2024-04, containing the
full 2022 winter), final 20% window evaluated once, untouched. Shorts were
charged 15 bps/side plus a deliberately pessimistic 10%/yr funding cost.
Replay scripts: session scratchpad `crypto_short_replay.py` (promote into
`engine/ai_investing/research/` when adopted).

## 1. The sleeve (BTC-only, crypto book)

Four stacked rules — each one exists because the variants without it failed:

| # | Rule | Why |
|---|---|---|
| 1 | **Regime lock** — short ONLY while BTC < its 200-day MA | every unlocked variant was destroyed in bulls; shorting a bull is the fastest way to die |
| 2 | **Entry = fade the bear-market rally** — within the bear regime, enter short after a bounce of +10% over ~10 days | rallies inside confirmed downtrends historically fail; enters at a good price with defined risk. Shorting breakdowns/negative momentum instead tested strictly worse (you sell the low, then get squeezed) |
| 3 | **Squeeze stop** — cover when price rises 10% above the low since entry; cover IMMEDIATELY on regime flip (BTC reclaims the 200d MA) | crypto squeezes are violent; an unstopped short is more dangerous than any long. The 10% stop keeps the sleeve inside the per-position loss rule |
| 4 | **Size cap = 30% of the book** | at 50% size the 2018 short profit doubled but standalone maxDD hit −44% — fails survival. 30% is what passes the 25% screen combined |

The sleeve runs alongside the long model (60% gated BTC/ETH core + 40%
momentum tactical, 200d gate + 10%-off-20d-high crash brake + 25% vol
target). Long gates and short regime are mutually exclusive by construction
(both key off the 200d MA), so the book is never long and short BTC at once.

## 2. Evidence (all costs on; holdout/final never touched during tuning)

Standalone sleeve (30% size): **2018 winter +22%, 2022 winter +19%**, covid
crash 0% (no bounce formed to fade — fast crashes are the crash-brake's job,
not the short's). Full-cycle standalone ≈ break-even: the sleeve is not a
year-round strategy, it is bear-season insurance that pays out in winters.

Combined book vs long-only:

| | Long-only | Long + short sleeve |
|---|---|---|
| Train | +48.6%/yr, maxDD −19% | +47.6%/yr, maxDD −24.8% |
| Holdout (unseen) | +33.9%/yr | +31.4%/yr |
| 2018 winter | −3.5% | **+11.6%** |
| Covid crash | −7.5% | −7.5% |
| 2022 winter | −16.4% | **−13.5%** |
| 2020-21 bull | +331% | +251% |
| Final (untouched) | −0.6%/yr, maxDD −26.8% | −4.1%/yr, maxDD −29.0% |

Honest framing: bear profitability costs ~2.5 pts/yr out-of-sample plus some
bull upside. It is insurance with a premium, not free money. Known limits:
sample of two slow bears; crash-type bears not catchable by fading; live
funding often *pays* shorts in winters (our 10%/yr charge is pessimistic —
live may beat the replay); squeeze gaps and exchange risk cut the other way.

## 3. Stocks-side equivalent (tested, weaker)

A mild SPY short (−30%) below the 150/200-day MA reduced bear losses but
never turned 2018Q4/covid/2022 positive after costs, and price-only sector
momentum that WAS positive in 2022 (+5%) died in the covid crash. Conclusion:
price-only stock shorting buys smaller losses, not profits. Bear-market
*profit* on the stock book should come from the news web (event-driven
shorts on confirmed bad news inside a bear regime) — blocked on the data
below, and R8 short-bias already exists in the trainer to gate it honestly.

## 4. What adoption needs

1. **Nothing more, data-wise, for the price-based sleeve** — signals are
   daily closes of BTC. Implementation = a strategy-side sleeve in the
   engine plus exchange capability for shorts (perps or margin on the live
   venue; sandbox first), with funding PnL journaled per the cost model.
2. **The news-driven upgrade** (better entries than price fades, and the
   only evidenced route to stock-side bear profit) needs the project data
   directory copied from the machine where the pipeline ran — see
   `data/digest_v2/README.md`. Then re-run trainer rounds with shorts
   enabled (`R8`/`R21` families) against the Sonnet digest (`--v2`).
3. Before live: paper-trade the sleeve through at least one real
   regime-flip; verify funding assumptions against the venue's actual rates.
