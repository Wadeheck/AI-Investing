# Technical-Rules Test Campaign (2026-07-29)

*One-day controlled experiment: can classic price-only technical systems —
tested under the project's honest physics — beat buy & hold, or deliver
capital preservation? Ten configurations tested. Every one failed. This
document is the permanent record so the question never needs re-litigating.*

**Where this fits:** complements the v2 lesson in STRATEGY.md §6 ("price-only
replay was +5%/−62%dd; news transformed it") with the mirror experiment:
instead of stripping news out of our engine, we built the best price-only
systems we could and watched them lose. The edge lives in the information
layer, not price geometry.

## Source material

User-provided course pages (photos): **Empower Advisory Stock Investment
Programme** (© 2013) — MACD 12/26/9 (crossovers, centreline, trend), 
stochastic %D vs 5-period smoothed %D with the 20/80 discipline rule,
Bollinger 20-period ±2σ (buy lower-band pierce / sell upper-band pierce),
candlestick reversal patterns (hammer, inverted hammer, hanging man, shooting
star, dragonfly/gravestone/long-legged doji, engulfing, piercing, dark cloud
50% rule, morning/evening star, harami) with prior-trend + confirmation
requirements, and gap support/resistance. All formulas implemented verbatim;
nothing tuned. The only rule NOT encoded: MACD divergence (book names it but
never defines it mechanically).

Plus a viral social-media thread ("Bruno Souza / Chinese girl's Claude Fable
bot": 15m mean reversion SPY+QQQ, 1h BTC volume breakouts, 4h gold/oil trend,
1% hard stop, vol sizing, correlation filters) — reconstructed with standard
definitions since the thread specifies none.

## Test physics (constant across all runs)

Long/flat (except the long/short run), fills at NEXT day's open after a
completed-bar signal, 5 bps/side, no leverage, 10-slot equal weight, stops as
resting intraday orders that gap through at the open. Universe: the project's
83–85 stock/ETF symbols (crypto excluded; 69 names survive to 10y). Windows:
3y (2023-07→2026-07) and 10y (2016-07→2026-07). Benchmarks: SPY B&H and
equal-weight-universe B&H over identical windows. Note the universe is
2026-picked, so the EW benchmark is survivorship-flattered — SPY is the fair
bar.

## Results

| # | Configuration | Window | CAGR | Sharpe | maxDD | Verdict vs SPY |
|---|---|---|---|---|---|---|
| 1 | MACD crossover alone | 3y | +22.7% | 0.90 | −26.2% | ~tie return, worse risk |
| 2 | MACD centreline alone | 3y | +1.9% | 0.20 | −30.4% | loses |
| 3 | Stochastic 20/80 alone | 3y | +7.7% | 0.43 | −21.3% | loses |
| 4 | Bollinger 20/2 alone | 3y | +3.4% | 0.26 | −27.2% | loses |
| 5 | Candle reversals (confirmed) | 3y | +6.5% | 0.38 | −24.3% | loses |
| 6 | Combined (MACD trend + all triggers) | 3y | +21.9% | 1.30 | −12.2% | ties SPY, better DD |
| 6 | — same, the honest window | 10y | +8.1% | 0.62 | −37.1% | **loses badly; −26% in 2022** |
| 6b | Combined + 3% hard stop | 10y | −1.8% | −0.09 | −44.6% | stop inside daily noise → churn |
| 7 | Tight confluence (BB pierce arms 5d → MACD cross) | 10y | +1.5% | 0.21 | −16.1% | fewer trades ≠ better trades + cash drag |
| 8 | Expert design: 30d pullback + candle trigger + pattern-low stop | 10y | +7.2% | 0.56 | −32.6% | 22% win rate: pattern stops inside noise |
| 9 | + preservation (breadth gate, 6% breaker, 5% annual loss budget) | 10y | +4.7% | 0.59 | −21.2% | loss cap works (worst yr −7%) but return ≈ T-bills |
| 10 | Long/short per-name rotation (shorts on bear candles, 3%/yr borrow) | 10y | −2.1% | −0.15 | −35.4% | shorts squeezed; lost ~5%/yr even in bull years |
| V | Viral bot reconstruction | mixed | — | — | — | BTC leg −24.5%/2y; oil leg −12% vs +67% B&H; 15m legs untestable beyond 3mo (data limit) |

SPY B&H: +21.0%/yr, −18.8% maxDD (3y); +15.2%/yr, −33.7% (10y).

## The five structural lessons

1. **Bull-window results are regime luck.** The combined system's 1.30
   Sharpe (3y) collapsed to 0.62 (10y) with identical rules. Always demand
   the window that contains 2018/2020/2022.
2. **Stops tighter than daily noise destroy dip-buying systems.** 3% fixed:
   win rate −8pts, CAGR −10pts, DD *deeper*. Pattern-low stops: 22% win
   rate. Same failure at 1% on 1h BTC (viral bot: −24.5%). Matches the
   project's own lesson that short-term risk rules on long theses were the
   stock book's biggest self-inflicted wound.
3. **Per-episode caps are not per-year caps.** Gate+breaker capped each
   episode at ~6% but chop years stacked three episodes (−21% in 2021). Only
   an annual loss budget (−5% YTD → flat till Jan 1) enforced the yearly
   cap, at the cost of reducing returns to ~T-bill level. Preservation and
   compounding trade off directly in price-only systems.
4. **Candle-geometry shorting fails even in bear years.** Stops above
   bear-rally highs are exactly where squeezes go; 21% win rate, bled in
   bull years too. Consistent with v2.4's finding: shorting survived the
   gate only when driven by web conviction, not price patterns.
5. **Tightening filters selects rarer setups, not better ones.** Win rate
   was flat as trade count fell 7×; idle capital did the rest.

## Conclusion

No assembly of MACD / moving averages / Bollinger / stochastic / candlestick
rules on daily bars beat holding the index under honest fills and costs — 
not the course's rules, not expert syntheses, not with preservation
overlays, not long/short. These indicators are transformations of the same
price series; on liquid daily bars that information is arbitraged below
transaction costs. The v2.4 engine (+35%/yr, −13% DD stocks) remains the
only strategy in this repo with evidence of edge, and its edge is the
information layer. Do not spend further effort on price-indicator systems.

**Only salvage worth a gated experiment:** the execution layer from #8
(pullback-to-average location + candle trigger + pattern-invalidation stop)
as fill timing for web-conviction tactical entries — information decides
what/why, structure decides when/where. Holdout-gated, like everything.

## Scripts (engine/ai_investing/research/)

`empower_backtest.py` (per-family, #1–5), `empower_combined.py` (#6/6b),
`empower_tight.py` (#7), `empower_expert.py` (#8), `empower_preserve.py`
(#9), `empower_longshort.py` (#10), `viral_bot_test.py` (V). All fetch OHLC
via yfinance at runtime; no stored data dependencies.
