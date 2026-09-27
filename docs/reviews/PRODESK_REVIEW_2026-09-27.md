# Prodesk trading review — 27 September 2026

Review and implementation instructions only. No trading code, model, configuration, service, order, or remote file was changed.

**Decision:** do not promote an NN or increase capital from the current leaderboard. The highest-value work is to repair realized-profit accounting and the common evaluation contract, contain the losing crypto event strategy, and reduce the number of independently maintained model pipelines. Retain the small NN as a control; retain NNv5 as a research hypothesis; quarantine the current NNv4 artifact; make NNv3 the first candidate for retirement after a fair comparison. NNv2 is a feature store, not a competing trading network.

This is a path toward better net profits, not evidence that any proposed strategy will earn them. Several measurement defects prevent a defensible estimate of current alpha.

## Evidence and scope

Connected by SSH over Tailscale to `eugene@100.64.113.103`, hostname `eugene-HP-ProDesk-400-G6-Desktop-Mini-PC`, repository `/home/eugene/Projects/AI-Investing`. Initial inspection began around 14:28 SGT. Remote HEAD was `4774d2e`, with modified runner/retraining files and untracked NNv5 source. The review used those live files, not an assumption that HEAD described the deployment.

Read the live systemd status, recent logs, model artifacts, primary decisions, settled outcomes, strategy journals, caches, graph, configuration allowlist, and read-only SQLite schema. Ran the existing `brain_audit.py --json` at low CPU priority with bytecode writes disabled. Copied selected records locally and did the large scans here. No training, broker calls, restarts, updates, or database writes were initiated. No unrelated Prodesk applications were inspected or changed.

The dashboard service was running; an unauthenticated local HTTP request returned 401. I did not authenticate into or visually inspect the dashboard. The trading evidence came from its underlying live records and source. The file copy was taken while the engine ran, so it is a closely timed collection, not a transactionally atomic snapshot. Model decision files parsed without malformed lines or duplicate primary keys in the copied records.

Retained evidence:

- [Live audit output](evidence-2026-09-27/brain-audit.json).
- [NN record summary](evidence-2026-09-27/nn-record-summary.json).
- [Host provenance and source hashes](evidence-2026-09-27/manifest.json).

Figures below distinguish *reported audit results*, *direct record counts*, *confirmed code defects*, and *recommendations*. Existing audit statistics are not automatically trustworthy merely because the audit runs.

## 1. What is running, and what is good

The engine, dashboard, and chat service were active. Host load was about 1 on a 12-core machine, with approximately 8.7 GB available memory. The latest engine cycle completed and evaluated 275 instruments in each active NN lane. There was no evidence of immediate host resource distress during inspection.

The production process is configured `LIVE_TRADING=true`, Longbridge for stocks, shared stock accounting enabled, `CRYPTO_SANDBOX=true`, and crypto book/event routing enabled. The Longbridge adapter defaults to enforcing the `lb_papertrading` account channel, and I found no explicit channel override in the configuration check. **The label LIVE means broker-routed operation here; it does not establish funded-account performance.** I did not independently query the broker account channel or account statements. The NN books are isolated paper simulations.

Keep these strengths:

1. Isolated NN books and guarded inference prevent a research candidate from automatically taking over broker execution.
2. Primary decision deduplication works in the sampled records. The brain audit found 101,734 advice outcomes but 1,738 primary observations, and its independently checked primary count agreed. Each copied NN stream had zero duplicate primary keys.
3. The adviser gate is still closed when evidence is weak. Its high-conviction long record is 127/263, or 48.3%, against a 60% eligibility requirement. Lowering the bar would not improve the strategy.
4. Delayed-order reservation protects against double-selling shared-account holdings. The current “sell capped at its own claim of 0” messages coincide with outstanding sell orders. These are not, by themselves, proof of missing holdings or broken exits.
5. The project retains rejected models and diagnostic records. The legacy NN's latest shadow optimization reported raw walk-forward Sharpe 1.82 but DSR 0.253 and was not adopted. Refusal is valuable when the apparent edge does not survive the selection test.
6. Point-in-time snapshots exist. They are more useful for future news-model research than manufacturing historical news features from today's graph.

These are operational strengths. None alone demonstrates trading alpha.

## 2. Profitability: the current answer is incomplete

### Current book marks

| Book | Reported equity | Cash/collateral | Positions | Interpretation |
|---|---:|---:|---:|---|
| Core trading | $9,629.40 | $3,709.74 | 12 | Accounting basis is undeclared in the audit; reconcile before computing return |
| Investing | $9,295.11 | $4,917.21 | 4 | About 53% idle cash; repeated minimum-lot rejections |
| Stock event sleeve | $11,039.38 | $1,218.98 | 3 | Positive mark, but contains migration adjustment and incomplete trade-level performance history |
| Crypto | $5,616.69 | $4,980.73 | 3 | Futures collateral is not uninvested cash; historical balances changed |
| Crypto event | $3,691.07 | $3,691.07 | 0 | Flat at inspection; losing recorded trade history |

Do not divide all these numbers by $10,000 or sum them into a total investment return. They have different funding, migration, collateral, and accounting histories.

### What the profit audit reports—and where it fails

| Book | Audit's realized P&L | Audit baskets | Audit benchmark result | Review conclusion |
|---|---:|---:|---|---|
| Stock event | +$1,177.09 | 7 | +2.29% mean basket excess; p=0.0686 | Encouraging historical subset, not a complete current track record |
| Crypto | +$33.32 | 3 | Too few baskets | Insufficient, and trade-level sales record is old |
| Investing | −$399.24 | 6 | 0/7 fills benchmarked | Incomplete attribution, no demonstrated edge |
| Crypto event | −$1,193.97 | 27 | −2.21% mean basket excess; nominal p=0.0179 | Strong candidate for containment; benchmark test itself needs repair |

**The most consequential accounting finding:** the stock event journal has no structured `sell` row after 24 August, but contains **39 messages describing delayed sell fills**, including MP on 24 September and Alibaba/JPM on 25 September. `brain_audit.pnl_significance()` requires a top-level symbol and P&L. A text-only `pending` message describing a late fill supplies neither. The aggregate book ledger changes, while the trade-level audit misses these closes.

The event state's ledger reports realized $229.92, fees $95.91, and adjustment $1,096.18. These are different accounting components from the historical +$1,177.09 journal sum. They cannot be spliced together without reconstructing migrations and fills. The audit's apparently persistent “seven baskets” is therefore not simply a strategy waiting for more trades.

The investing journal's last structured sale is 3 September; the crypto journal's is 15 August. Those timestamps are completeness warnings, not proof that each strategy stopped trading. Core trading has no trade-level P&L section in this audit output at all.

**Crypto event losses are real within the recorded simulation/testnet history:** 28 exits associated with negative shocks lost $517.09, 14 associated with positive shocks lost $459.25, and one unclassified exit lost $217.63. Win rates were 35.7% and 28.6% respectively. Shock sign is a direction proxy, not a replacement for reconstructing actual fills. Both sides deserve scrutiny; simply disabling shorts would not have removed all the loss.

Do not repeat the audit's “significantly underperforms” label without qualification. It subtracts the long BTC benchmark return from `ret` even when a trade's return is already signed for a short. A short-relative benchmark should use the same side/exposure, or a fitted factor exposure. It also groups bets by exit day, which neither separates unrelated trades on one day nor joins a shared thesis exited on different days. Its nominal p=0.0179 does not clear a simple four-book Bonferroni threshold of 0.0125. The negative dollars justify a capital-containment decision without pretending that the present p-value proves structural negative alpha.

**Recommendation:** at implementation time, make the crypto event lane shadow-only for new risk while preserving its records. Leave any existing exit protection intact. At inspection it was flat. Restore allocation only after execution-level reconstruction and a fresh forward test. Do not invert its signals on the strength of these losses.

## 3. Neural networks compared

The equity marks below come from the same recent engine logs and assume each lane's stated $10,000 seed. Percentage changes are descriptive since-start marks, **not comparable risk-adjusted returns**: inception dates, model changes, permitted markets, exposures, costs, and fill realism differ.

| Lane | Actual role / size | Decision history | Reported paper equity | Approx. change from seed | Decision |
|---|---|---|---:|---:|---|
| Legacy NN shadow | 10→4→1 MLP, 49 parameters | 22 Aug–27 Sep; 10,168 primaries / 37 dates | $10,586 | +5.86% | Keep as cheap nonlinear control; no promotion |
| NNv2 | Point-in-time snapshot store, not a live network | About 1 GB of snapshots | N/A | N/A | Keep the data; rename and compact the store |
| NNv3 | 10→8→1 MLP, 97 parameters | 28 Aug–27 Sep; 8,518 primaries / 31 dates | $9,591 | −4.09% | First retirement candidate after common-cost comparison |
| NNv4 | 18→12→6→3 multi-head MLP, 327 parameters | Same 31 dates and 8,518 primaries | $9,863 | −1.37% | Quarantine current artifact; repair or retire |
| NNv5 | Linear baseline plus 241-parameter residual MLP | 19–27 Sep; 2,473 primaries / 9 dates | $10,006 | +0.06% | Keep as the main research hypothesis, not the winner |
| Linear brain | Incumbent formula plus learning machinery | 8,518 primary records / 31 dates in new ledger | Core book above is not a matched shadow | N/A | Retain as control and add a genuinely matched paper book |

NNv3 and NNv4 each have 6,870 settled rows over **25 issuance dates**. Their stored non-flat directional hit rates are 49.56% and 49.69%; the linear ledger's is 50.61% across its slightly longer settled period. On the common 6,870 rows, the linear hit rate is 50.67%. These are descriptive; correlated symbols and overlapping outcomes make them much less informative than the row counts suggest.

An exploratory, equal-date-weighted signed-excess diagnostic on the common rows is −0.253% for NNv3, +0.310% for NNv4, and +0.107% for linear, assigning zero to FLAT. It ignores costs, portfolio constraints, unequal prediction timestamps, and the settlement defects below. It is **not portfolio P&L or a promotion test**. It does show why hit rate alone is inadequate: NNv4's upside/downside magnitudes differ despite a near-coin-flip hit rate.

### Legacy NN shadow

Its positive equity mark and small parameter count warrant keeping it as a benchmark. Its latest candidate DSR is 0.253, so it has not earned promotion. Weekly artifact replacements also mean its since-start book is a changing policy, not one fixed model's test.

The legacy report has a separate horizon bug: `scripts/nn_shadow_report.py::_price_lookup()` selects the first price date strictly after the decision day. `nn_shadow.grade()` waits five days before grading, but passes the original day to the lookup. It therefore waits five days to grade approximately the next available day's move, rather than measuring the advertised five-day return. It also grades absolute moves, unlike the newer relative-return ledger.

### NNv3

The artifact is dated 28 August, with recorded DSR 0.556 across three windows. It uses the same ten-feature family as the small NN with greater capacity. Current paper loss and the negative common-row diagnostic provide no reason to add complexity or capital.

Retirement is a portfolio-of-research decision, not a claim that 31 days statistically disproves neural networks. Keep its artifacts and outcome history. Once the common evaluator exists, require incremental net utility or useful diversification to justify continued inference. Otherwise archive the lane and remove its scheduling/UI maintenance burden.

### NNv4: confirmed implementation defects

1. **Training/inference feature mismatch.** `build_nn4_samples()` defines realized volatility as daily volatility × √horizon. `build_nn4_features()` uses daily volatility. `vol_change` consequently differs too. For a five-bar horizon, the volatility scale differs by √5, about 2.236. The live inputs do not follow the fitted feature contract.
2. **Different targets in supposedly related heads.** `positive` labels are computed from absolute forward returns before the return targets are demeaned by the cross-sectional median. The probability head is not trained to predict positive excess return as documented.
3. **Costs are inconsistent.** NNv4 submits at `mid` directly to `PaperBroker`; NNv3/NNv5 apply a cost model. PaperBroker itself simply debits/credits quantity × supplied price. NNv4's apparent loss is measured on a more favorable execution basis.
4. **Relative strength is not relative.** `relative_strength` is assigned the same 20-day return as `return_20d`, duplicating a feature instead of subtracting a benchmark.
5. **Weak validation signal.** The stored validation report has correlations −0.0149, +0.0096, +0.0135 and directional hit rates 47.28%, 49.33%, 50.85%. This report predates the promoted artifact, so it is supporting context, not a certified final-artifact test.
6. **Probability compression.** Latest probabilities occupy 0.54653–0.55169. The saved calibration slope is 0.05. Against recorded excess outcomes, descriptive Brier score is 0.25276 versus 0.25 for a constant 50% forecast. Because the probability target is mismatched, this primarily confirms that the advertised excess-probability interpretation is unsafe.
7. **OOD is frequent, not proof of sound uncertainty.** Latest OOD multipliers are below 0.5 for 85/275 names, including zero for 13. Feature-unit mismatch must be eliminated before interpreting those flags economically.
8. **Selection and calibration share validation data.** Early stopping and Platt fitting use the same validation slice. Candidate replacement compares new validation loss with an old artifact's historical loss, not both models on the same fresh window.

The score `expected_return × probability / risk` also needs an economic justification. If expected return is already an unconditional mean, multiplying by a probability of a positive outcome can double-count directional information. For negative returns, probability-of-positive is the wrong side's confidence measure. Test calibrated expected net return directly; use risk estimates as sizing constraints or a variance penalty. Do not retain the composite score just because it sounds prudent.

### NNv5: useful question, unreliable current experiment

The residual question—does nonlinear modeling add net value to a simple baseline?—is the best-scoped research question in this lineup. Evidence is much too young: only four settled issuance dates.

Confirmed defects:

- `OutcomeLedger.settle()` chooses `nn3`, then `nn4`, then `brain`; it never reads `nn5`. **792/1,100 settled rows have a target weight different from their NNv5 primary decision.** The current ledger is substantially grading the comparator under the NNv5 lane name. Correcting direction from original primaries gives about 43.5% non-flat hits on those four dates, still not useful evidence of stable performance.
- CPU training uses `fit_nn`, whose `val_loss` is MSE. It compares that to `mean(y²)/2`, a half-MSE zero-residual baseline. A candidate must roughly halve baseline squared error, rather than merely improve it. The GPU path uses Huber loss. Rejections on every inspected day from 20–27 September cannot be interpreted as a clean repeated negative experiment.
- The accepted residual is validated before the deployed 0.5 gate and residual clipping. Promotion must score the actual deployed predictor, including those transformations.
- The artifact freezes a serialized linear baseline. Persist a baseline hash and evaluate against the current incumbent explicitly. Version numbers alone are not enough; the inspected v0/v2 formulas have equivalent semantic prior weights despite different feature orders, so I do not claim demonstrated current baseline drift.
- Its 13,970 training rows are only 55 aligned time indices across 254 stocks. The final 20% contains roughly 11 indices, before considering calendar alignment. That is not a large independent validation sample for a 241-parameter model.

## 4. Shared problems that matter more than network size

### A. Dates are aligned by array position

`backtest/engine.py::_aligned()` truncates every asset to the shortest length and joins by array index. It does not join on timestamp. NNv3, NNv4, and NNv5 training paths use this function.

In the current 254-stock NNv5 cache, all retained arrays have 120 bars, yet position 0 spans **31 March–13 April** across markets; position 60 spans **29 June–6 July**. The last index spans 23–25 September. Thus a “same-date” cross-section or purge boundary can combine different actual dates. Crypto's seven-day week makes positional alignment still more problematic when mixed with equities.

`nn_v2.align_on_common_dates()` already demonstrates a date-aware alternative, but a global intersection across every exchange would throw away valid observations. Build per-market calendars and as-of joins with availability timestamps instead. Cross-sectional training must name its universe and decision cutoff explicitly.

### B. Five days has several meanings

Training uses five bars. New outcome ledgers use a five-calendar-day SGT cutoff and the first available current price when settlement runs. They store neither an authoritative price-source timestamp nor an exact scheduled exit mark. Delayed data, outages, weekends, and markets in different time zones therefore change the economic horizon. The benchmark is a cross-sectional **median**, despite comments describing equal weighting. It mixes available peers and can change composition.

Define stock horizons in exchange sessions, crypto horizons in elapsed time, and benchmark timestamps identically. Reconstruct labels from immutable price history. A delayed worker must produce the same outcome as an on-time worker. Store missing labels as missing; never silently extend the investment period or grade against zero when the benchmark is unavailable.

### C. Statistical independence is still overstated

`n/5` is a rough overlap heuristic, not an exact effective sample size or a valid universal binomial correction. Rounding hits into a synthetic smaller binomial sample does not model cross-asset correlation, event clusters, market regimes, or unequal windows. Twenty-five dates of 275 correlated assets are not 1,374 independent bets.

Use actual daily net portfolio returns for the capital decision. Resample contiguous date blocks with all assets together; group event attribution by origin event/thesis and exposure overlap. Report sensitivity to block length. For calibration/ranking, weight dates equally and report date-clustered uncertainty. Compare candidates on paired dates and frozen common opportunity sets.

Keep an experiment register, including failed variants and daily selection attempts. The Deflated Sharpe Ratio addresses selection bias and non-normal returns; it does not repair timestamps, costs, leakage, or missing trades. See [Bailey and López de Prado, The Deflated Sharpe Ratio](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf).

### D. Executable universe and decisions disagree

The NN paper books hold instruments from markets not established as executable by the current stock route, and permit quantities such as 0.93 of a Korean share or small odd lots. All NNs can journal SHORT predictions while their paper broker inherits `allow_short=false`. A SHORT forecast then often means liquidation/avoidance, not an opened short trade.

Keep separate forecast-quality and portfolio-quality reports. Evaluate both a common executable universe and a broader research universe, clearly labeled. Enforce actual board lots, minimum notional, currency, market hours, borrow availability, and trade eligibility before portfolio construction. The investing journal's repeated 2020.HK rejection—one board lot costing about $1,815.54 while the desired order is smaller—is an allocation-design issue, not a signal discovery problem.

### E. Training has less information than live inference

Historical sample builders evaluate signals with an empty context. Current live inference has news, macro, and graph context. Features such as sentiment can be constant or absent in training and variable live. This is a distribution-contract problem even when there is no lookahead.

Initially separate a market-only model from a point-in-time news/event residual model. Add missingness indicators and source timestamps. Do not fill historical rows using today's graph or retrospectively digested news whose original availability is unknown.

## 5. The brain, macro view, and microstructure

### Graph and learning

The live graph has 806 nodes, 1,287 edges, and 658 asset nodes. Only 207 distinct tested propagation signatures remain: resolution 31.5%. **389 assets (59.1%) are inert** to the probed origins; another 104 duplicate a peer's response. Of 452 LLM-proposed edges, all 452 are unreviewed. There are 130 orphan LLM nodes. Calibration scored 363 relationships but classified zero as supported or contradicted.

Expansion has outpaced evidence. Adding another NN on top of indistinguishable inputs will not automatically create differentiated stock selection. Freeze automatic production admission of new economic influence edges during implementation; continue collecting candidates in quarantine. Prioritize coverage of executable assets and economically distinct exposures. Use full-graph versus curated-only versus market-only ablations before deciding whether graph complexity earns its cost.

The formula is still marked `fitted=false`; the audit reports ten RLS samples and eleven outcome rows. A moving learner state is not evidence that online learning improves decisions. First check whether delayed closes bypass the learning pipeline as well as the profit audit. Do not lower sample requirements or force a refit to make a dashboard look active.

### Macro should condition risk and expected returns, not issue an untested story

The internal snapshot labels conditions risk-on, tightening, strengthening dollar, heating inflation, and high geopolitical tension. Those are **the system's stored interpretations**, not externally verified current macro facts. It also stores `tnx=5.184` and `us10y=0.518`; the provider code unconditionally divides TNX by ten. Verify the vendor's actual units with dated authoritative data before consuming that field. Percentage changes used elsewhere may survive a scale error, so do not infer that every regime output is wrong from this one discrepancy.

Implement a small, testable macro conditioning set:

- Growth and inflation changes, real/nominal rate changes, credit spreads, dollar trend, volatility and market breadth.
- For crypto: BTC trend and beta, funding, basis, liquidity, open interest, liquidation pressure, stablecoin flows, and venue-specific data quality.
- Use vintage-aware release timestamps for economic data. Treat revisions as new information, not as if known at the original date.
- Fit modest regime interactions or risk multipliers with shrinkage; retain an unconditional baseline. Avoid many narrative regimes with a few trades each.

Scenario tests should ask what happens under rising yields plus rising oil, disinflation with improving breadth, a credit/liquidity shock, and crypto deleveraging. Measure portfolio losses and factor concentrations under those scenarios. PANW and CRWD are related cybersecurity exposures, not two independent event bets; several semiconductor longs can be one AI-capex exposure.

For company/event selection, concentrate on source-verified earnings surprises, guidance revisions, financing changes, regulatory decisions, and new information relative to price expectations. Deduplicate syndicated stories, measure first-seen time and post-publication drift, and test whether trading at realistic arrival times still leaves positive net returns. Cached integrity flags include plausible entity-matching contamination—for example, an ARM flag cites a generic crypto Ponzi headline. Audit source-to-entity evidence before allowing such flags to drive exposure.

### Execution may dominate a small predicted edge

Treat gross predictability and realizable profit separately. Daily-bar signals should not incur repeated intraday turnover merely because the engine runs every nine minutes. Add no-trade bands and a pretrade comparison of expected benefit against spread, fees, impact, funding, borrow, and operational uncertainty. Research on dynamic trading explicitly incorporates costs and signal persistence into how quickly positions should move toward targets; this supports testing partial adjustment rather than trading every score update. See [Gârleanu and Pedersen, Dynamic Trading with Predictable Returns and Transaction Costs](https://www.nber.org/papers/w15205.pdf).

The 05:00–07:30 SGT rest window also needs a trading-specific assessment. It leaves crypto unmonitored locally and, depending on US daylight saving, overlaps or follows the US close. Do not change the host-wide schedule as part of this review. An implementer should use venue-native protection or a separately approved trading-only monitor, or ensure vulnerable exposure is not held through the gap. Backtests must reproduce the actual availability and order-session rules.

## 6. Implementation work orders

These are instructions for a later implementation session. Sequence is deliberate; do not start model expansion before the measurement gates pass. Estimates are engineering work ranges, not promises of a statistically mature strategy on a calendar deadline.

### P0 — Accounting and evidence repair, approximately 3–5 engineering days

**Work order 1: one execution ledger.** Touch `brokers/shared.py`, book ledger code, journal persistence, event/investing runners, and `scripts/brain_audit.py`.

- Emit a structured fill event for synchronous, asynchronous, and partial executions through the same path. Include broker execution/order IDs, book, symbol, signed quantity, currency, executed price, fees, funding, FX rate, decision/event/model IDs, and exchange timestamp.
- Handle cumulative partial-fill updates correctly: incremental notional must be derived from cumulative quantity and cumulative average price, rather than assigning the latest cumulative average price to every incremental fill.
- Deduplicate by execution identity; rebuild positions, lots, realized P&L, unrealized P&L, and strategy outcomes from executions. Separate transfers, deposits, withdrawals, migration adjustments, and trading returns.
- Backfill from broker execution history and available local records into a new ledger version. Do not invent exact fill economics from rounded text logs; mark unreconstructable periods incomplete.
- Produce a daily reconciliation: starting NAV + external flows + realized + change in unrealized − costs = ending NAV, with explicit FX treatment.
- Link completed lots to learning labels. A late fill must settle exactly once in P&L and learning.

**Acceptance:** every inspected delayed sell appears once in the new ledger; partial-fill replay and duplicate notifications leave economics unchanged; strategy totals reconcile to account statements/ledger within documented currency rounding; all five books appear in the report or have an explicit completeness failure. Never “fix” reconciliation with an unexplained adjustment.

**Work order 2: a versioned outcome schema.** Touch `learning/outcome_ledger.py`, all NN live writers, linear evidence writer, and legacy report.

- Replace key-order guessing with explicit `model_id` and `prediction` fields; fail loudly on missing payloads. Record comparator separately.
- Store decision timestamp, feature cutoff, entry-price timestamp, scheduled horizon, exit-price timestamp, benchmark identity/version, model artifact hash, feature schema, and eligibility.
- Fix NNv5 extraction and legacy lookup; implement exchange-session-aware horizons and deterministic historical settlement.
- Version repaired outcomes. Retain old records for audit; never silently rewrite contaminated evidence or train on unrepaired rows.

**Acceptance:** 100% of reconstructed NNv5 prediction fields match frozen primary decisions; delayed versus on-time settlement is identical; weekends, holidays, missing quotes, halted symbols, and incomplete lines have explicit tested behavior. Distinguish same-day replicas from independent forecast origins.

**Work order 3: establish operational guardrails.** Snapshot the dirty deployment into a reviewable branch/artifact without losing its existing changes. Record account environment explicitly. Recommend shadow-only new crypto-event risk and freeze NN promotion until P0/P1 pass. Changes must affect only AI-Investing; retain existing exits and recovery behavior.

### P1 — A fair experiment, approximately 5–10 engineering days

**Work order 4: one feature/calendar contract.** Touch `backtest/engine.py`, feature extraction, `nn_v2` date helpers, NN sample builders, data adapters.

- Remove positional alignment from every research path. Join by actual available timestamps within explicit market cohorts; support asynchronous markets without forward-looking fills.
- Share the same feature builder between train, replay, and live. Fix NNv4 volatility units, return target, and relative strength.
- Define adjusted-versus-unadjusted prices and corporate-action handling; preserve delisted assets where historical selection claims require them. Restrict conclusions when historical universe coverage is incomplete.
- Keep a market-only baseline and a separately identified point-in-time contextual model.

**Acceptance:** the same historical decision input produces the same features in training and replay; future bars/news cannot change past features; actual label exit timestamps lie wholly before the next validation block. Tests include US/HK/JP/crypto calendar differences.

**Work order 5: a common simulator and comparator.** Touch NN live execution adapters, costs/risk modules, and reporting.

- Give linear, small NN, NNv3, corrected NNv4, and NNv5 identical capital, eligibility, timing, lots, costs, risk budget, and order-priority rules.
- Preserve separate forecast diagnostics, so a useful avoid signal is not penalized for failing to open an illegal short.
- Use cash, a low-cost investable benchmark, a simple momentum strategy, and regularized linear forecasting as controls. Match beta/exposure for alpha attribution; keep cash and absolute net performance visible too.
- Persist daily NAV, gross/net exposure, turnover, factor/sector concentration, implementation shortfall, and rejected-order reasons.
- Reconstruct costs from current execution data where available; test base and doubled-cost assumptions. Include FX, futures funding, and borrow when applicable.

**Acceptance:** identical predictions produce identical simulated positions and net NAV across lanes. Every cost has a single owner and cannot be omitted or double-counted. NNv4 has no special mid-price fill path. Common-period results can be reproduced from immutable inputs.

**Work order 6: fix training/promotion mechanics.** Touch `nn_v5.py`, `nn_v4.py`, candidate runners, walk-forward evaluation.

- Evaluate candidate and incumbent on the *same* windows with the *same* loss, including deployed gate/clipping and transaction costs.
- Use separate chronological train, early-stop/tuning, probability-calibration, and final test periods where data permits; otherwise explicitly state that the data is insufficient and simplify the model.
- Fix CPU/GPU loss parity. Evaluate the returned predictor directly instead of trusting a backend's differently defined `val_loss`.
- Register all seeds/architectures/thresholds and previous attempts. Do not keep reopening a supposedly untouched test set each day.
- Persist immutable model IDs, baseline hashes, dataset fingerprints, training cutoff, and deployment times. Rejected candidates remain available for research provenance.

**Acceptance:** identical predictions have identical promotion scores regardless of backend; an old incumbent is rescored on the candidate's window; an intentionally leaked feature fails the validation checks; the selected artifact reproduces its reported deployed-policy score.

### P2 — Profit-oriented simplification, approximately 2–4 further weeks of research

**Work order 7: restructure the research lineup.** Keep one shared evaluator and at most two active neural challengers initially: the small NN control and NNv5 residual. Archive NNv3 if it fails the frozen paired utility/diversification test. Quarantine NNv4's current artifact; give its corrected architecture one preregistered experiment only if the extra heads have a clear measurable role. Retain NNv2 snapshots as a data service.

For retirement, define a minimum useful improvement before testing: expected net annual dollars must exceed incremental data/compute/maintenance costs at intended capital, under the same risk budget. If a candidate's upper confidence bound falls below that improvement and it adds no stable diversification, retire it. With inconclusive data, a cheaper model can still be chosen for operational simplicity; label that as a cost decision, not statistical rejection.

Archive artifacts, code version, manifests, and results before removing scheduler hooks or UI lanes. Delete redundant execution/training implementations only after dependency searches and replay checks. Do not delete the unique point-in-time history or losing experiments.

**Work order 8: controlled graph/event research.** Compare market-only, curated-graph, full-graph, and novelty-filtered event models on the same dated opportunity set. Freeze weights during each forward block. Admit new edges only with provenance, economic mechanism, as-of time, and either measurable downstream utility or an explicit unproven status. Establish a review budget tied to executable asset coverage, not node count.

**Work order 9: portfolio construction and trade friction.** Use expected net return with uncertainty shrinkage. A practical research objective is:

`maximize μᵀw − λ wᵀΣw − estimated_cost(w − previous_w)`

subject to actual capital, long/short permissions, gross/net limits, sector/factor/event concentration, board lots, liquidity, and stress-loss limits. Estimate covariance conservatively. Choose λ and limits from the capital risk budget before the final test. Do not introduce full Kelly sizing on these small samples.

Test no-trade bands, staggered/partial rebalances, venue-aware order timing, and minimum expected benefit after costs. For small accounts, explicitly solve whether a position is executable at a whole lot before ranking it into the portfolio. Report rejected opportunities and the realized cost of each trade, not just turnover.

### P3 — Forward evidence and allocation decision

After repair, collect a new, clearly separated forward record. Thirty calendar days of a five-day strategy is roughly a handful of nonoverlapping temporal windows, even with hundreds of tickers. Sixty or ninety days is a scheduled review, not automatic evidence sufficiency.

Use paired daily net portfolio returns as the primary comparison. Report net profit, maximum drawdown, expected shortfall, turnover, exposure, benchmark-relative return, and a block-bootstrap interval for candidate-minus-control. Resample dates jointly across symbols. Report calibration/ranking by market and regime as diagnostics, avoiding post-hoc selection of the winning slice.

Proposed capital-promotion gate:

1. P0/P1 correctness and reconciliation checks pass; no unknown accounting basis or unresolved critical defect.
2. Positive cost-adjusted out-of-sample utility relative to the best simple control on a frozen executable universe; positive economics survive doubled-cost stress.
3. A prespecified paired uncertainty test supports incremental value after experiment-family correction. Use DSR with a complete trial count as a supporting check, not a sole gate.
4. Drawdown and tail loss are within a risk budget specified before evaluation; results do not depend on a single event cluster or inaccessible market.
5. Only then consider a small, separately authorized funded pilot with live slippage/reconciliation monitoring and predetermined stop/rollback conditions. Capital grows with replicated evidence, not model complexity.

## 7. Operational efficiency without disturbing Prodesk

The four copied NN decision journals total about 1.8 GB uncompressed, in addition to about 1 GB of NNv2 snapshots. NNv3/4/5 repeatedly scan historical files to determine today's primaries and settle outcomes; the shared settlement code loads full journals into memory. This has not caused observed resource exhaustion, but growth will raise latency and recovery costs.

In implementation, replace repeated whole-file scans with an indexed append-only store, a primary-key constraint, and a pending-outcome queue. Archive replicas by date and keep compact daily/model/asset summaries. Preserve enough detail to reconstruct decisions and debug execution. Separate research workers from the trading loop with bounded queues and resource limits; do not change other Prodesk services or the host-wide power schedule.

Retrain when sufficient new labeled information arrives or a defined drift trigger fires. The NNv5 job currently spends about a minute daily on a 55-index training panel and rejects candidates through a mismatched loss gate. More frequent training is not more learning.

## Final recommendation

The best immediate profit decision is to stop treating incomplete performance numbers as an allocation signal. Preserve the isolation and primary logging that already work, contain the losing crypto-event experiment, and make every model face the same executable, cost-adjusted test. Spend research capacity on the small NN control and a repaired residual challenger. Retire complexity that cannot show incremental value after that test.

The stock event concept deserves renewed evaluation because its historical subset is encouraging. It does not yet deserve a larger allocation: its recent delayed fills must first enter the performance and learning ledgers. The current NNv4 artifact should not be used to decide capital, and NNv5's tiny positive book mark should not be described as success. No implementation was performed in this review.
