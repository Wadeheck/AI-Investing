# Upgrade Log — 2026-07-29/30 (seed v11 → v17)

One session, eleven layers. Everything below is implemented, wired into the
live engine, and covered by the test suite (**126 tests passing**). All
replays/backtests referenced follow the anti-cheat protocol (train 55% /
holdout 25% / untouched final 20%, real costs, hard maxDD screens).

**Standing caveat (repeat until resolved):** every coefficient added this
session (value/integrity/dividend/ownership/expectations anchor weights, DCF
parameters, circularity haircuts) is hand-set judgment, NOT holdout-validated
— the news-impulse data lives on the pipeline machine (`data/` is gitignored
and absent here; see `data/digest_v2/README.md`). When that data is copied
over, these must run through `research/train_web.py` as gated R-rounds
(`--v2` trains against the Sonnet digest into separate `*_v2` outputs).

## 1. Knowledge graph: seed v11 → v17 (283 nodes / 562 edges, 118 taggable)

- **v12** — all 16 `NODE_GRAPH_GAP_ANALYSIS.md` proposals: `political_stability`,
  `boe_rate`, `uk_banks`, `uk_growth`, `us_growth`, `uk_utilities`,
  `offshore_wind`, `freight_logistics`, `travel_leisure`, `telecom_equipment`,
  `commercial_aerospace`, `eurozone_political_risk`, `sanctioned_economy_stress`
  + 20 ADR assets. Scenario battery (15 documented historical events) caught
  3 mis-signed theme→risk_appetite edges in the original spec — fixed; 15/15 pass.
- **v13/v14 — bill-of-materials tiers**: `semi_equipment`, `semi_materials`,
  `advanced_packaging`, `hbm_memory`, `datacenter_power_gear`,
  `optical_networking`, `battery_materials`, `robot_components`,
  `consumer_hardware` (DJI is private → theme alias; Insta360 688775.SS is the
  buyable), `content_creation`, `agri_inputs`, `food_processing`,
  `medical_devices`, `life_science_tools` + ~50 assets (incl. previously
  missing GOOGL/META/AVGO). Verified nuance: a crop-price spike moves
  fertilizer makers UP and Tyson/Coca-Cola DOWN in one ripple.
- **v15** — `ai_servers` (SMCI/DELL/HPE, NVDA→SMCI supply edge).
- **v16 — the AI money circle**: ORCL + private non-tradable hubs
  (openai/anthropic/xai). `detect_circular_financing()` finds MULTI-PARTY
  round-trips in the money-flow digraph with a `severity` score (min leg
  strength). The NVDA→OpenAI→Oracle→NVDA triangle is detected live.
- **v17 — fraud mechanisms as nodes**: `financial_engineering` (2008
  repackaging, 180-day-delayed credit-crunch edge), `currency_peg_stress`
  (1997 Asia = Terra 2022), `market_intervention` (China-2015 props,
  90-day-delayed bearish edge), `financial_fraud`, `custody_risk` (FTX).

## 2. News-driven deal pipeline (scalable circularity — no per-company code)

Digester emits `deals` records (plain company names + kind + $size);
`brain/deals.py` resolves via alias index, auto-creates private-hub nodes for
material unknowns (≥$1B) via `propose_node()`, accrues materiality-weighted
llm-capped owns/supplies edges with corroboration bumps. Criterion test:
three ordinary headlines on a bare graph → OpenAI hub auto-created → triangle
detected. Circle participants carry severity-scaled valuation haircuts —
precisely BECAUSE circular revenue makes financial statements look good.

## 3. Fraud/manipulation detection (3 tiers, novel-fraud capable)

1. **Hardcoded patterns** (`brain/integrity.py`): auditor resignations,
   withdrawal halts, restatements, Ponzi, probes, "guaranteed returns" →
   per-asset DECAYING flags (45d half-life, `data/integrity_flags.json`).
2. **Adaptive LLM tier**: open-ended `integrity` field — any story where the
   honest version requires trusting fakeable numbers, by ANY mechanism.
3. **Mechanism-free math**: `smoothness_anomaly` (Madoff detector: implausible
   Sharpe + too-few down periods + sticky autocorrelation) and
   `accrual_red_flag` (NI growing while median FCF/NI < 0.5; banks exempt via
   revenue/assets < 0.12 financial-mode).
Flags OVERRIDE good numbers in anchors; adviser zeroes fresh longs at sev≥0.67.
Brief §11b carries the fraud playbook (each 2008/1997/2015/Enron/FTX mechanism
and its modern costume).

## 4. Fundamentals: multi-year history + dividends (data/fundamentals_history.py)

4–5 fiscal years per company (revenue, NI, FCF, debt, cash, assets, equity,
current debt, interest expense, EBIT, D&A, diluted shares) + 15y dividend
per-share history. Trajectory analytics: health score, revenue/FCF CAGR,
deleveraging, `cash_conversion`, `maturity_wall_risk`, `interest_coverage`,
`dilution_rate`, dividend verdicts (compounder/steady/recently_cut/at_risk
with pre-cut signatures). Monthly `--compile` refresh; `health_scores()`
feeds the brain's valuation anchors.

## 5. Undervaluation scanner (data/value_scanner.py)

Undervalued = intrinsic, not just cheap: conservative owner-earnings DCF
(damped/capped demonstrated growth, 10% hurdle) → margin of safety, OR raw
FCF yield — the better route wins; PLUS peer comps confirmation. Hard vetoes:
decaying trajectory, accrual flag, integrity flag (cheap+dishonest = trap);
currency-mismatch guard for ADR statements. Crypto value = Mayer multiple
< 0.8 + extreme fear + usage/price divergence ("nothing in the value zone"
is a valid output). Feeds positive resting anchors; trend gates still time entry.

## 6. The 7 investment-banker upgrades

1. **Structural cluster caps** (`strategy/clusters.py` + RiskManager):
   clusters named by driver factors — NVDA/SMCI/VRT/AMAT/ANET/TSM/AVGO all
   resolve to ONE bet (`ai_capex_cycle`); gross per cluster capped
   (RISK_MAX_CLUSTER_EXPOSURE, default 0.35).
2. **Event calendar** (`data/calendar_events.py`): earnings-window + FOMC-day
   throttle on NEW entries only. FOMC table is per-year — UPDATE each January.
3. **Expectations layer** (`data/estimates.py`): EPS revision momentum,
   surprise history, target gaps → anchor tilt.
4. **Ownership/flows** (`data/ownership.py`): TRUE open-market insider buys
   (transaction-text filtered — the provider's summary table counts grants as
   purchases; the fix collapsed ~40 false positives to 4 real clusters:
   NKE, TSM, U11.SI, BA) + short % of float (crowded ≥15%: LKNCY, CRWV,
   ENPH, SMCI, MP, GPRO as of 2026-07-30).
5. **Balance-sheet depth**: maturity wall, covenant-zone coverage, dilution
   tax / buyback bonus — all in health.
6. **Peer comps** (`data/comps.py`): EV/EBITDA z-scores per graph theme with
   currency guard; `relative_value_scores` into the scanner.
7. **Stress engine** (`brain/stress.py`): 8 canonical scenarios through
   `propagate()` every cycle into `state["stress"]` + CLI; with position
   weights → per-scenario book exposure + worst-scenario summary.

## 7. Data accumulation (this machine, Guardian-independent)

`research/accumulate.py` (--once/--loop): all RSS (40 feeds — 21 Asian
sources incl. NATIVE-language: Taiwan zh (Liberty Times, cnyes, TechNews,
CNA) + Taipei Times en, HK (RTHK en+zh), mainland zh (36kr) alongside
Xinhua/China Daily/Global Times en, Yonhap, KED, Nikkei Asia, Mainichi,
Antara, VOI, Bangkok Post, VnExpress, Mint, Hindu BusinessLine, Straits
Times). RSS 1.0/RDF parsing fixed (JP/TW sites); CJK alias matching added
(substring, no word boundaries) with zh aliases on core nodes (seed v18) —
a Chinese headline about Nvidia circular financing maps to
['ai_circularity','nvda'] with no LLM. + SEC EDGAR
8-K + StockTwits sentiment + Hacker News → dedup via brain.db → append-only
`data/news_archive_live.jsonl`. Backfill: GDELT (BACKFILL_START/END env,
verified to 2017) + `research/nyt_fetch.py` (needs free NYT_API_KEY).
**Gotcha fixed**: `.env` NEWS_RSS override had silently clamped the engine to
3 feeds — leave NEWS_RSS unset to get the full list.

## 8. Technical indicators (indicators.py)

Added MACD, Bollinger %B, stochastic, ADX, ROC, OBV, VWAP, Donchian,
realized vol, max drawdown, smoothness_anomaly — pure-python, unit-tested,
composable for derived indicators.

## 9. Strategy research (real data, 2014/2015 → 2026)

- **Crypto survival config** (`research/replay_crypto_survival.py`): 60%
  BTC/ETH core + 40% momentum tactical, 200d gate + 10%-off-20d-high brake +
  25% vol target → holdout +34%/yr at −23.5% DD vs BTC hodl +12% at −77%;
  bears 2018/covid/2022: −3.5%/−7.5%/−16.4%.
- **Bear-profit short sleeve** (`docs/SHORT_STRATEGY.md`,
  `replay_crypto_short.py`): regime-locked bear-rally fade, 30% cap, squeeze
  stops → 2018 +22%, 2022 +19% standalone; combined book turns 2018 positive
  (+11.6%) for ~2.5pts/yr premium.
- **Stocks price-only** (`replay_stock_trend.py`): trend gate + GLD/SHV
  defensive = drawdown control (bears −12/−18% vs SPY −19/−34%), NO alpha vs
  SPY — consistent with the training record: stock alpha requires the news web.

## 10. Fixes to pre-existing bugs

- `match_text` plural handling ("tariffs" now matches alias "tariff").
- Strategist valid-symbol set: watchlist ∪ all graph assets (was 4 names).
- Trainer: loud preflight on missing news data + `--v2` A/B mode with
  separate outputs; graph persistence extended to deal-derived changes.

## Operational quick reference

```
make setup / .venv already present
python -m ai_investing.research.accumulate --loop 900     # live news archive
python -m ai_investing.data.fundamentals_history --compile # monthly statements
python -m ai_investing.data.value_scanner [--crypto]       # undervalued report
python -m ai_investing.data.comps [theme]                  # peer comps tables
python -m ai_investing.brain.stress                        # stress report
python -m ai_investing.data.estimates / .ownership         # expectations/flows
BACKFILL_START=2017-01-01 → news_replay.fetch()            # GDELT history
```
