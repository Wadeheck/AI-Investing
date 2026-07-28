# Training Record — The Web Learns to Trade

*Covering 2026-07-26 → 2026-07-28. Every number here survived the anti-cheat
protocol or is labeled as the failure it was. Latest state: see
`data/web_training.json` (config), `data/web_training_history.jsonl` (every
cycle ever run), `data/web_training_report.md` (latest cycle report).*

---

## 1. The mandate (user's rules, in force everywhere)

1. **Capital preservation first, growth second.**
2. **Hard rule: no single trade or investment may lose more than 10%** —
   `RISK_MAX_LOSS_PER_POSITION=0.10` caps every stop in every book, live and
   simulated (commit `86c55c7`).
3. **Monthly high-water-mark ratchet** — a month that closes higher locks that
   equity as the new base; falling 10% below it blocks new entries until
   recovery (`5ba3a90`).
4. **Targets:** stocks ~50%/yr; crypto ~3×/yr as HODL core + daily tactical.
5. **The nodes and web are the sole source of truth** — every factor must live
   *in* the graph (valuation anchors, price pulses, news impulses, crypto
   signals as node anchors); proposals must cite web support (`d804b27`).
6. **No cheating** — no tweak may be justified by a single backtest. Made
   structural: parameters tune only on the TRAIN window (first ~2/3 of 3
   years); adoption requires the untouched HOLDOUT window (final ~1/3) to
   agree. Rejections are logged, not hidden.

## 2. The data (all free)

| Dataset | Source | Coverage |
|---|---|---|
| Prices, 86 assets (US/HK/CN/SG/JP/KR/TW/EU + BTC/ETH/SOL) | yfinance | 3y daily |
| Historical news → node impulses | GDELT archive + Wikipedia Current Events fallback, digested by local qwen3:8b through the SAME event extractor the live brain uses | 782/785 trading days |
| Funding rates (BTC/ETH/SOL, leverage crowding) | Binance (keyless) | 1,169 days |
| Crypto Fear & Greed | alternative.me | full history (8y) |
| On-chain activity (BTC active addresses) | blockchain.info | 1,164 days |
| Macro anchors (CPI, rates, debt/GDP, M2…) | FRED | live |
| Fundamentals (P/E, P/B, ROE, margins, debt) | yfinance | weekly cache |

Pipeline battle scars worth remembering: GDELT hard-throttles (~1 req/10s,
long bans) — failures must never be recorded as "quiet news days"; Wikipedia
filled 500+ days working backward while GDELT was banned; the digester needed
retry-on-zero-events because a failed LLM call is indistinguishable from a
quiet day; PC suspend froze everything for 9h (now `systemd-inhibit` blocked).

## 3. How the strategy evolved (chronological)

### Stage 0 — price-only replay (the humbling baseline)
Mechanical core only (price pulses through the web + momentum/mean-reversion),
2023-07 → 2026-07, all proposals auto-accepted, costs on:
**trading book +5% total with −62% maxDD; SPY +70%.** Verdict: no edge in the
mechanical core — confirmed independently by the walk-forward optimizer's
Deflated Sharpe gate refusing its own best formula (DSR 0.176 < 0.6).

### Stage 1 — news enters the web
Backdated news digested into node impulses transformed the same machinery:
baseline jumped to **stocks +17.6%/yr (Sharpe 1.11), crypto +94%/yr** on the
train window — before any tuning. The web's thesis (news → ripples → assets)
carries the signal; prices alone don't.

### Stage 2 — the user's rules reshape behavior (cycle 1, full ruleset)
10% stops + HWM ratchet: **crypto drawdown −54% → −19% while CAGR doubled**
(21% → 40%) — stopped riding winters, re-entered on recovery. Preservation
target met for the first time and **never violated in any cycle since**.

### Stage 3 — factor families, holdout-gated
Adopted (survived out-of-sample):
- **Emotion factor** (headline fear/greed pulses the risk node), gain 0.4
- **Influential figures** (Powell/Trump/Xi/OPEC amplify their nodes), refined
  0.2 → 0.32 → 0.48 with holdout approval each step
- **Regime gate era-1** (deep risk-off cuts gross) — later superseded by
  crypto-specific gates
- **Crypto mix** (HODL 40% / tactical 60%, tactical gain 1.2)
- **Crypto winter gate** (BTC < 100d average → tactical off, HODL trimmed)
- **On-chain adoption trend** (BTC active addresses), weight 0.4

Rejected by the holdout, repeatedly ("looked good in training only — that
would be cheating"): parameter re-sweeps (R1, every cycle), manipulation
discount (R3), crypto-mix retunes (R6), field-momentum + web/tape agreement
(R9), funding-rate crowding (R11), F&G extremes (R12 — likely redundant with
the winter gate already adopted).

### Stage 4 — convergence and the ceiling (cycles 3-7)
Seven consecutive cycles plateaued at stock +21.9%, crypto +37.3%. The loop
self-terminated honestly: *"search converged at this function structure — the
remaining gap needs NEW factor families."*

**Ceiling diagnosis:** exits. Fixed 6-9×ATR take-profit caps every winner at
roughly +12-18% while the hard rule cuts losers at 10%; at a ~40% win rate
that asymmetry arithmetically bounds CAGR near the observed plateau.

### Stage 5 — structural exit rebuild (running now)
- **R14 trailing exits**: no fixed cap; the stop ratchets behind the peak
  (initial risk still ≤10% per the hard rule). Cut losers fast, let winners run.
- **R15 learned reliability**: per-symbol trust EMA (0.5-1.5×) earned from
  that symbol's own closed trades reweights its field term — trailing data
  only, no lookahead.

## 4. Cycle ledger (full-period metrics per cycle)

| Cycle (UTC) | Stocks CAGR / Sharpe / maxDD | Crypto CAGR / Sharpe / maxDD | Preservation |
|---|---|---|---|
| 07-27 14:17 #1 | +17.2% / 1.00 / −15% | +40.1% / 1.49 / −19% | ✅ |
| 14:27 #2 | +3.2% / 0.28 / −20% *(data shifted mid-cycle)* | +38.3% / 1.44 / −19% | ✅ |
| 14:39 #3 | +23.8% / 1.05 / −19% | +37.3% / 1.40 / −21% | ✅ |
| 14:49 #4 | +24.0% / 1.05 / −19% | +40.7% / 1.50 / −19% | ✅ |
| 15:05 #1′ *(full news + crypto signals)* | +18.7% / 0.92 / −20% | +40.6% / 1.50 / −19% | ✅ |
| 15:17 #2′ | +21.8% / 1.05 / −19% | +37.3% / 1.43 / −21% | ✅ |
| 15:29–16:12 #3′–#7′ | +21.9% / ~1.06 / −19% (plateau) | +37.3% / 1.43 / −21% | ✅ |
| 22:20 → | **R14/R15 era — running** | | |

## 5. The current strategy (incumbent config, plain language)

**Conviction function (per asset, daily):**
`score = 1.4 × web_field_impact + 0.48 × price_formula` — the web's voice
weighs ~3× the price signal. Entry requires |score| ≥ 0.22 (a high bar: only
strong, corroborated ripples trade). Propagation: 3 hops, 0.5 decay per hop.

**What feeds the web daily:** news events (LLM-tagged to origin nodes),
price pulses (≥1% moves shock their own node and ripple to neighbors),
valuation anchors (stretched multiples = standing downward pull), macro
anchors (FRED), headline emotion (gain 0.4) on the risk node, influential-
figure amplification (0.48), BTC on-chain trend (0.4), crypto funding/F&G
anchors (live, conservative fixed weights).

**Stock book:** max 12 positions, gross ≤ 100%, vol-targeted sizing, entries
only with web conviction; stops ≤10% always; monthly HWM ratchet blocks new
buying 10% under the locked base.

**Crypto book:** 40% HODL core + 60% tactical sleeve driven by field impact;
winter gate (BTC < 100d MA) turns the tactical sleeve off and trims the HODL
core to half (rebought on recovery); 10% stops throughout, HODL included
(re-entry above the 100d average).

**Current full-period results (3y replay, all rules):**

| Window | Stocks | Crypto |
|---|---|---|
| Train (2y) | +20.2% / Sharpe 0.91 / −19% | +75.1% / 2.12 / −16% |
| Holdout (1y) | **+57.7% / 2.20 / −7.8%** | −7.0% / −0.61 / −14% |
| Full 3y | +21.9% / 1.06 / −19% | +37.3% / 1.43 / −21% |
| Trades | 394, win rate 33%, 5-day precision 52% | |

Note the split: the stock strategy's holdout year actually *exceeds* the 50%
target with a tiny drawdown — but one good year is not proof; the full-period
number is the honest one. Crypto's negative holdout year (a sideways/down
crypto tape where the HODL core pays its keep-alive costs) is the current
weak spot.

## 6. Distance to targets

| Objective | Target | Current | Status |
|---|---|---|---|
| Preservation (dd ≤ 25% + 10% rule + HWM) | always | never violated | ✅ **achieved** |
| Stocks growth | 50%/yr | ~22%/yr (holdout yr: 58%) | ~44% of target |
| Crypto growth | 200%/yr | ~37%/yr | ~19% of target |

## 7. Known biases and honest caveats

- **LLM hindsight**: qwen tagging 2024 headlines knows what 2024 led to.
  Tagging is mechanical (origin node + sign) so the leak is bounded — but it
  flatters results. Discount accordingly.
- **Graph structural hindsight**: the node/edge seed was written in 2026 with
  knowledge of 2023-26 (AI-capex nodes, NVDA↔CoreWeave circularity, etc.).
- **FX simplification**: HKD/SGD/KRW prices treated 1:1 as USD — per-position
  % returns are right; cross-currency sizing is approximate.
- **Wiki news days** (~500 of 782) are thinner than market headlines.
- **Replay ≠ live**: fills at daily closes, no intraday gaps through stops.
- Therefore: **the forward paper test remains the only proof.** These replays
  guide the search; the scorecard grades the live (paper) engine's real calls.

## 8. Evidence protocol v2 (2026-07-28) — the replay stopped flattering us

The expert review found the replay's physics too kind, so the trainer was
rebuilt to be pessimistic enough to trust. **All numbers above this section
were measured under v1 physics and are NOT comparable to anything after.**

What changed in `research/train_web.py`:

1. **Real frictions.** The flat 5bps/side became per-market commissions +
   taxes + half-spread wired through `execution/costs.py` (sqrt market
   impact off real 20-day ADV). Measured per side: US ~4bps, HK ~25bps
   (stamp duty), SG ~20bps, crypto ~15bps.
2. **No same-bar fills.** Stock entries decided at day t's close fill at
   day t+1's open. Stops/takes are resting intraday orders triggered off
   high/low; a gap through the stop fills at the open — so the 10% rule is
   now a *target the sim can miss*, exactly as live trading can. Crypto hard
   stops are checked daily (was every 5 days), gap-aware.
3. **Benchmarks in every report.** SPY, QQQ, 60/40, BTC buy-and-hold beside
   every window — alpha must beat doing nothing.
4. **Lockbox.** Windows moved from 66/34 to train 55% / holdout 25% /
   **lockbox 20%** (currently ≈ 2025-12 → today). No adoption decision ever
   sees the lockbox; `--lockbox` evaluates it manually, ONCE, when freezing
   a strategy for deployment. Honesty note: rounds adopted before this date
   saw that data through the old holdout, so the lockbox is only fully clean
   for decisions made after v2.

**First honest measurement** (incumbent config, v2 physics, new windows):
stock train fell from +20%/yr to **+2.4%/yr (Sharpe 0.22) — below SPY's
+17.5%**; crypto train +49%/yr vs BTC hodl's +108%. Holdout: stock +17.0%
(Sharpe 0.84) vs SPY +28%, crypto +3.6%. Conclusion: most of the v1 edge
was execution-assumption artifact, not alpha. The incumbent was tuned under
v1 physics; the next training run re-tunes under v2 — treat everything
before then as unproven.

**v2 retraining (2026-07-28, 21 cycles, converged).** The search abandoned
the v1 parameters within one cycle, then in cycle 15 adopted the structural
family v1 physics had wrongly rejected: **R14 trailing exits** (holdout obj
−0.193 → −0.066, the run's biggest OOS gain), **R15 learned reliability**,
and **R8 bear-market shorting** (short_bias 0.65 — adopted on tolerance,
and the sim charges shorts NO borrow costs: re-verify before trusting).
Also newly in: crypto fear/greed (w_fng 0.18, rejected under v1). Converged
config (train+holdout, continuous, v2 physics): **stock +9.6%/yr, Sharpe
0.93, maxDD −7.1%** (SPY: +21.3%, −18.8%) and **crypto +63.7%/yr, Sharpe
1.68, maxDD −23.9%** (BTC hodl: +68.9%, −31.8%). Honest read: the stock
book is a drawdown-control product (⅓ of SPY's DD at ~45% of its return,
consistent ~15%/yr in each window fresh-start — the continuous gap is HWM
ratchet path-dependence); the crypto book ≈ hodl's return at 8pts less DD
and beats a flat BTC year +21% vs +6% on the holdout. Crypto's holdout-
window DD of −25.4% breaches the 25% screen within-window (the continuous
number passes). The lockbox remains UNSPENT. Next: Guardian re-digestion
(79,924 headlines archived, all 1,123 days) through docs/DIGESTION_SPEC.md,
then rounds R16–R25.

## 8b. v2.1/v2.2 (2026-07-28 afternoon): truer physics, the leverage bug, and the two-sleeve breakthrough

Physics upgrades v2.1: FX-correct USD prices for all ~30 non-USD names;
daily borrow fees on shorts (2–4%/yr); crypto stops see weekends;
hard-data anchors VIX/DXY/USDJPY as rounds R16/R17 (FX anchors adopted).
Two protocol holes found AND closed mid-run: (1) the refiner walked
`crypto_hodl` to 1.19 — free leverage via negative cash; now hard-capped at
95% of cash; (2) the 25% dd limit was only screened per fresh-start window
— the continuous path breached at −28%; now a structural **preservation
veto** on every adoption (both staged rounds and refiner).

**The two-sleeve stock book (user mandate update, 2026-07-28):** the 10%
hard cap + HWM ratchet now govern FAST capital only (tactical sleeve +
crypto). A long-term CORE sleeve (~12 names, monthly rebalance, slow-field
30d-EMA conviction + 200d trend, 30% disaster stop, no HWM lockout) holds
through dips. Adopted as R18 on first pass (holdout 0.243 vs 0.229) and
transformed the stock book: **+4.8% → +37.6%/yr at −17% dd** (SPY: +21%,
−19%). Caveat: universe survivorship (picked 2026) flatters a hold-through
sleeve more than anything else in the system — the Sonnet-digest A/B,
lockbox, and paper-live remain the referees.

**v2.2 converged (16 cycles):** stock +37.6%/−17%; crypto +88.1%/−28%
(breach, held from deepening by the veto). Step-down sweep of the crypto
sizing on the continuous path (`data/stepdown_sweep.json`):

| Variant | crypto_gain / hodl | Crypto | Stock |
|---|---|---|---|
| Unconstrained (record only) | 3.32 / 0.95 | +83.3% / −28.0% | +37.6% / −16.8% |
| **Mandate-compliant ≤25%** | 3.32 / 0.40 | **+71.2% / −23.3%, Sharpe 1.77** | +37.6% / −16.8% |
| **Live-margin ≤20%** (recommended) | 1.80 / 0.40 | +52.4% / −19.9%, Sharpe 1.64 | +37.6% / −16.8% |

The breach lived in the oversized HODL core, not the tactical sleeve: at
hodl 0.40 even the aggressive tactical gain stays compliant. Lockbox still
UNSPENT. Next: Sonnet digestion (in progress) → calibration → R19–R25 →
freeze one of the two compliant variants → lockbox once → paper-live.

## 8c. v2.3 (2026-07-28 evening, converged after 28 cycles): the full-mandate strategy

User mandate updates implemented: stocks = two-sleeve mix (core 30% won
the search); crypto = **20% HODL pinned** + fast tactical sleeve ≤70%
(take-profit + 3-day time-boxed holds, R19) + cash buffer. All three
hard-data anchors (VIX 0.3, FX 0.72, on-chain 0.24) plus fear/greed and
the R9 scoring upgrade (field momentum 0.6 + web/tape agreement 0.67 —
first-ever adoption) are in the converged config.

| Continuous train+holdout | Strategy | Benchmark |
|---|---|---|
| Stocks | **+38.2%/yr, Sharpe 1.73, −11.8% dd** | SPY +21.3%, −18.8% |
| Crypto | +24.9%/yr, Sharpe 1.38, −16.1% dd | BTC hodl +68.9%, −31.8% |

Window detail: stock train +48.2% (Sharpe 2.07) / holdout +28.7% (1.82,
matching SPY's +28.4% in its best year at −10.7% dd). Crypto holdout year
**−4.7%** — the fast-churn mandate pays round-trip costs in a flat tape;
that is the accepted price of the skeptical stance. Preservation: True
everywhere, with margin. 277 trades, 30% win rate.

This is the freeze candidate for paper-live. Lockbox still UNSPENT.
Survivorship caveat unchanged (2026-picked universe flatters the core
sleeve most); referees remain the Sonnet-digest A/B, the lockbox, and
the forward paper test.

## 9. Next levers (need the user)

1. **NYT Archive + Guardian API keys** (free registration) — market-grade
   historical headlines to replace the wiki-thin days.
2. **Crypto holdout-year fix** — the sideways-tape bleed suggests a cash-yield
   / stablecoin parking assumption and better re-entry logic.
3. **Structural book ideas not yet built**: pyramiding winners, weekly
   compounding rebalance, cross-book capital rotation.
4. **When paper-live accumulates ~4-8 weeks**: reconcile scorecard hit-rates
   against replay expectations; retire whatever reality contradicts.
