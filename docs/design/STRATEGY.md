# The Strategy — Definitive Current State

*Written 2026-07-29, after the v2.4 convergence. This is the single
authoritative snapshot: what the strategy IS, how it decides, how it was
tested, what survived, what died, and how much to trust it. The
chronological history lives in TRAINING_RECORD.md; the news-digestion
program in DIGESTION_SPEC.md / SONNET_DIGEST_BRIEF.md; the math internals
in FORMULA.md.*

---

## 1. The thesis

News and hard data flow into a **knowledge web** — 85 concept nodes
(macro factors, commodities, industry themes, sectors, state actors)
wired by 344 signed edges to 88 tradeable assets across US/HK/CN/SG/JP/
KR/TW/EU equities, ETFs, and BTC/ETH/SOL. Shocks tagged to their ORIGIN
node ripple outward (3 hops, 0.5 decay/hop, per-node-type half-life
decay); the accumulated "field" at each asset is the conviction signal.
The web — not any single indicator — decides.

## 2. What feeds the web, daily

| Input | Mechanism |
|---|---|
| News events | LLM-digested to origin nodes with polarity/magnitude/confidence; code adds credibility (source trust, corroboration, hype penalty); impulse = polarity × magnitude × credibility × confidence |
| Price pulses | ≥1% daily moves shock the asset's own node |
| Headline emotion | fear/greed balance pulses the risk node (gain 0.4) |
| Influential figures | Powell/Trump/Xi/OPEC mentions amplify their policy nodes (gain 0.16) |
| **VIX** | >5% moves pulse the risk node with real vol data (w 0.3) |
| **DXY / USDJPY** | >0.3% moves anchor `usd_strength` / `yen_carry` (w 0.72) |
| Crypto fear/greed index | contrarian extremes on crypto nodes (w 0.20) |
| BTC on-chain activity | active-address trend (w 0.24) |
| Valuation + macro anchors | stretched multiples and FRED series as standing pulls |

Asset conviction: `score = 1.5 × field_impact + 0.48 × price_formula
+ 0.4 × web/tape-agreement`, entry bar |score| ≥ 0.22, with per-symbol
learned reliability (trust EMA 0.5–1.5× from that symbol's own closed
trades) reweighting the field term.

## 3. The three books (user mandates, 2026-07-28)

**Stock CORE — the long game (50% of stock capital).** ~12 equal-weight
names, re-picked every 21 trading days by slow conviction (30-day EMA of
field impact + 200-day trend quality). Holds through dips: NO 10% cap,
NO ratchet lockout. Exits only on thesis break (falls out of the top-2N
ranking) or a 29% disaster stop. *This sleeve exists because forcing
long-term theses through short-term risk rules was measurably the stock
book's biggest self-inflicted wound.*

**Stock TACTICAL — the fast game (50%).** Web-conviction entries filled
at next-day's open; trailing stops (6.7×ATR ratchet behind the peak —
no fixed profit cap, initial risk ≤10%); shorts allowed in risk-off
regimes (entry bar halved), paying 2–4%/yr borrow. Governed by the 10%
hard rule and the monthly high-water-mark ratchet (10% under the locked
base → no new entries until recovery).

**CRYPTO — the skeptical book.** 20% HODL core (pinned by mandate,
unsearchable; 10% stop; halved in winter = BTC under its 100d average;
re-entered on recovery). Fast tactical sleeve capped at 70% of the book:
enters on strong field impulses, exits on a 3-day clock / signal flip /
10% weekend-aware stop. Remainder cash. Long-only (shorts tested and
rejected — see §7).

**Global preservation (inviolable):** every adoption during training must
keep the CONTINUOUS train+holdout path of BOTH books inside a 25% max
drawdown — enforced as a structural veto, not a report line.

## 4. The evidence protocol (how anything gets believed)

- **Physics**: per-market commissions/taxes/spreads (HK stamp duty, KR/TW
  taxes, crypto taker fees) + sqrt market impact off real ADV; FX-correct
  USD prices for ~30 non-USD names; entries at next open (no same-bar
  fills); stops as resting intraday orders that gap through at the open;
  crypto stops check weekends; shorts accrue borrow; **no free leverage**
  (HODL hard-capped at 95% of cash).
- **Windows**: train 55% (tuning) / holdout 25% (blind adoption gate) /
  **lockbox 20% — never touched, spent once at deployment freeze**.
- **Gates per candidate**: better on train → non-degrading on holdout →
  continuous-path drawdown veto. Rejections logged, never hidden.
- **Benchmarks in every report**: SPY, QQQ, 60/40, BTC-hodl — beat those
  or it isn't alpha.

## 5. Honest current numbers (continuous train+holdout, v2.4 physics)

| | Strategy | Benchmark |
|---|---|---|
| Stocks | **+35.0%/yr, maxDD −13%** | SPY +21%, −19% |
| Crypto | +38.6%/yr, maxDD −18% *(±10pt vintage sensitivity — see §8)* | BTC hodl ~+69%, −32% |
| Preservation | passed with margin | — |

Original targets: stocks 50%/yr (not hit), crypto 3×/yr (not hit — and
mathematically out of reach under the 20%-HODL mandate; accepted trade),
preservation (hit, structurally).

## 6. What was tested AND ADOPTED (the survivors, with why)

| Feature | Why it survived |
|---|---|
| News → node impulses | THE foundational edge: price-only replay was +5%/−62%dd; news transformed it |
| Emotion factor (0.4) | adopted in every era, repeatedly re-validated |
| Influential figures (0.16) | consistent small OOS gain |
| Crypto winter gate + HODL trim | halved crypto drawdowns for modest return cost |
| BTC on-chain trend (0.24) | survived every physics upgrade |
| Crypto fear/greed (0.20) | rejected under fantasy physics, ADOPTED under honest costs |
| **Trailing exits (6.7×ATR)** | rejected under v1's free fills; under real costs the run's biggest OOS gain — cut losers, let winners run |
| Per-symbol learned reliability | trust earned from each symbol's own record |
| Bear-market shorting (stocks, 0.5) | survived even after borrow fees were charged |
| Web/tape agreement (0.4) | first adopted v2.3 — web and price action confirming each other |
| **VIX / DXY / USDJPY anchors** | real data behind the three most systemic nodes |
| **Two-sleeve stock book (core 0.5)** | the single largest improvement of the project: +4.8% → +35–40%/yr; long-game money freed from short-game rules |
| Fast-crypto rhythm (3-day clock) | the searched implementation of the skeptical mandate |

## 7. What was tested AND REJECTED (the graveyard, with why it matters)

| Candidate | Fate |
|---|---|
| Parameter re-sweeps (every era) | rejected by holdout dozens of times — "looked good in training only" |
| Manipulation discount | never survived |
| Field momentum alone (w_fmom) | adopted once, refined away to 0 — no durable OOS value |
| Funding-rate crowding | rejected in every era |
| F&G at v1 weights | rejected until physics were honest — *the sim decides what works* |
| **Crowd positioning (OI, top-trader L/S, taker flow)** | **rejected at every weight tried** — at daily granularity with real costs, the perp-scalper "special data" carries no edge for us |
| **Crypto tactical shorts** | rejected — bled in bull windows; bear insurance not worth the OOS cost (revisit if regime changes) |
| Free leverage (crypto_hodl → 1.19) | *not a strategy — a sim bug the optimizer found and exploited; now impossible* |
| Boundary-riding drawdowns | the preservation veto ended the pattern of "returns up, DD pinned at limit" |

## 8. Confidence assessment (what to trust)

- **Trust most — the measurement machinery.** Every "gain" since v2 came
  from *removing* flattery: fills → costs → FX → weekends → borrow →
  leverage → continuous-path preservation. Direction of travel: honest.
- **Trust well — replicated structure.** Two-sleeve stocks, trailing
  exits, big-HODL-was-the-return-engine, churn-caps-crypto: these held
  across independent runs under progressively harsher physics.
- **Trust cautiously — stock direction** (beats SPY at ~⅔ its drawdown):
  consistent, but the 2026-picked universe (survivorship) flatters the
  core sleeve most, and repeated runs have partially worn the holdout.
- **Trust least — point estimates.** Crypto CAGR moved 14 points from a
  one-day window shift with identical parameters. Error bars are wide.
- **Unspent referees**: the Sonnet-digested signal (in progress), the
  sealed lockbox (spend ONCE at freeze), and 8–12 weeks of paper-live —
  the only test no simulator can flatter.

## 9. The road from here

1. **Sonnet digestion** of the complete 1,123-day Guardian archive
   (v1.2 rules; 40 done) → validation harness → the trainer re-runs on
   the new signal (this is the only known lever left for the stock
   ceiling — tuning is exhausted, per three consecutive convergences).
2. Event-study **magnitude calibration**; novelty-weighted impulses;
   learned edge re-weighting (all holdout-gated; DIGESTION_SPEC §B).
3. A/B: new-signal challenger vs this incumbent, same windows.
4. **Freeze** (risk-reviewed config) → run `--lockbox` ONCE → deploy
   **paper-live** with the scorecard reconciling live hit-rates against
   replay expectations.
5. Real capital only after paper-live agrees — small, personal, scaled
   by live evidence. Node-map revision (UK/wind gaps logged by the
   digester) happens once, after digestion, with the full gap list.
