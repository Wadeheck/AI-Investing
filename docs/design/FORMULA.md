# The Decision Formula & Learning Engine

This is the mathematical core: a parametric decision formula whose weights are
**curated offline** and **matured online**, designed to win on long-run risk-adjusted
terms rather than react to individual trades.

## 1. Features φ

For each asset at time `t` the signals produce a feature vector (see
`learning/features.py`). Every feature is *directional* so that `θ·φ` reads as a
predicted return:

| feature | definition |
|---|---|
| `bias` | 1 (intercept / baseline drift) |
| `momentum` | momentum signal score × confidence |
| `mean_reversion` | mean-reversion score × confidence |
| `sentiment` | news sentiment score × confidence |
| `political_hype` | hype-fade score × confidence (negative on detected pumps) |
| `macro_linkage` | brain: graph-propagated macro impact × confidence |
| `trend_zscore` | EMA/stdev z-score trend filter × confidence — **candidate, see §7** |
| `consensus` | mean of the five signal features *above `trend_zscore`* (bias/mom_lowvol excluded; `trend_zscore` deliberately excluded too, see §7) |
| `mom_lowvol` | `momentum × 1/(1+vol_regime)` — regime interaction |

## 2. The formula (`learning/formula.py`)

```
raw(t)        = θ · φ(t)                         ≈ predicted forward return
conviction(t) = tanh( gain · raw(t) )            ∈ (−1, 1)
target_wt(t)  = deadzone(conviction, τ) · size_scale
              = sign(conv) · max(0, |conv|−τ)/(1−τ) · size_scale
```

`target_wt` is then multiplied by `RISK_MAX_POSITION_WEIGHT` and clamped by the risk
layer. **Decision variables:**
- `θ` = the 9 feature weights (the heart of the model).
- hyperparameters `{gain, entry_threshold τ, size_scale, stop_loss, take_profit}`.

## 3. Objective — what "wins long-run" means (`learning/objective.py`)

```
J(θ) = Sharpe(returns(θ)) − λ_turn · turnover − λ_reg · ‖θ − θ_prior‖²
```

Risk-adjusted (Sharpe/Sortino), penalized for churn, and regularized toward a prior so
the formula moves smoothly. The optimizer maximizes **out-of-sample** Sharpe, never
last-trade P&L.

## 4. Two learning loops

### (a) Offline curation — walk-forward (`backtest/walkforward.py`)
For each expanding window:
1. Fit `θ` by **ridge regression** on `(φ_t, forward_return_t)` from the *training*
   slice: `θ = argmin ‖Xθ − y‖² + reg‖θ‖²`.
2. **Search** hyperparameters for the best Sharpe on the *next, unseen* slice, after an
   **embargo gap** (= label horizon) so the h-day forward-return label can't leak across
   the train/validation boundary.
3. **Champion/challenger + Deflated Sharpe:** the winner is the best of many trials, so
   its Sharpe is biased upward. Deflate it by the trial count (Bailey & López de Prado)
   and adopt **only if** it beats the incumbent *and* the Deflated Sharpe clears a
   threshold — i.e. the probability the true Sharpe is positive survives the
   multiple-testing bias. This is the real anti-overfitting gate. The backtest that scores
   each candidate also charges **transaction costs** (`execution/costs.py`), so the search
   can't win by churning.

### (b) Online maturation — Recursive Least Squares (`learning/online.py`)
Each closed trade yields a sample `(φ, y)` with `y` = realized signed return. RLS
updates `θ`:
```
k   = Pφ / (μ + φᵀPφ)                 # Kalman gain
θ  ← θ + k·(y − θᵀφ)                   # nudge toward realized outcome
P  ← (P − k·φᵀP) / μ                   # μ = forgetting factor (<1)
```
Three safeguards make it *curate, not react*:
- **forgetting factor μ** — tracks regime, never fully forgets;
- **confident prior `P₀`** — early trades can't swing θ;
- **trust region** — caps ‖Δθ‖ per update, so no single trade jerks the formula.

`θ` from RLS lives in the same units as the ridge fit, so the two loops compose: the
walk-forward run curates a strong starting `θ`, and RLS matures it from live P&L.

## 5. Auditability
Every version of `θ` is written to `data/formula.json` (with RLS state) and logged to
the `params` table; every learning sample lands in the `outcomes` table. You can
reconstruct exactly how and why the formula evolved.

## 6. Honest caveats
- Backtest Sharpe on the bundled **synthetic** data is *not* a profit forecast —
  random-walk data can yield spurious high Sharpe on short folds. Point real data at it
  (`DATA_PROVIDER=yfinance`/`ccxt`) to curate a genuine formula.
- Features that are always zero in a given dataset (e.g. `sentiment` with no news feed)
  correctly receive zero weight.
- Walk-forward reduces but never eliminates overfitting. Re-curate periodically; trust
  the out-of-sample gate over in-sample returns.

## 7. Candidate features: the dormant-to-active lifecycle

`trend_zscore` (`signals/trend_zscore.py`, added 2026-08-15) is the first feature added
in this "dormant candidate" state, and sets the pattern for any future one. Origin: a
widely-shared r/algotrading post claiming 65.92% CAGR / 26.79% max DD from an EMA(65)/
stdev(65) z-score trend state machine on BTC since 2014. Independent replication on real
BTC-USD daily data reproduced the CAGR in the right ballpark (51–67% across a 25-cell
threshold grid) but **not** the drawdown claim (actual: 51–78%, never once under 50%),
and the strategy lost to plain buy-and-hold over just the last 4 years (13.5% vs 27.1%
CAGR) — the edge was concentrated in a handful of early-Bitcoin trend rides, not a
repeatable property. A first walk-forward run through this project's own gauntlet
(real Gemini OHLCV via ccxt, real transaction costs, embargoed OOS windows) confirmed
that verdict on live data: Deflated Sharpe 0.001 against a 0.60 bar. **Rejected as
"trust it blindly," not disproven as an idea** — the underlying hypothesis (a
volatility-normalized distance-from-trend, read as trend *confirmation* rather than
`mean_reversion`'s mirror-image "fade the extreme") is different enough from every
existing signal to be worth letting it keep auditioning on more data, at zero cost or
risk while it does.

**Mechanically dormant, not administratively excluded.** It runs every cycle like any
other signal and its value reaches `φ` (`learning/features.py`), but starts at
`θ_trend_zscore = 0` (`learning/formula.py:_DEFAULT_WEIGHTS`) and is deliberately kept
**out of `consensus`** — folding an unvalidated feature into an already-weighted
aggregate would let it influence conviction through the back door even at weight 0.
`0 × anything = 0`: it cannot move `raw(t)`, and therefore cannot move a single trade,
until one of the two paths below gives it a nonzero weight. See
`tests/test_trend_zscore.py` for a proof of each claim in this section (feature reaches
`φ` but not `consensus`; an old saved formula migrates it in at weight 0; RLS can move
its weight away from 0 given genuinely predictive data).

**Path A — online RLS (automatic, continuous, already running for every feature).**
Every closed trade feeds `(φ, realized_return)` through `learning/online.py`. If
`trend_zscore` is genuinely predictive of realized returns on the assets it fires for,
its weight drifts away from 0 on its own — no manual step. The trust region
(`RLSLearner.trust_region`) caps how far any single trade can move it, and the
confident prior means the first handful of trades can't swing it either; it has to earn
the move gradually, the same as every other feature already does.

**Path B — offline walk-forward re-curation (manual/discrete, the harder gate).**
```bash
cd engine
python3 -m ai_investing.backtest.main --optimize --save
```
Re-fits `θ` by ridge regression + hyperparameter search on current data and **only
overwrites the saved formula if the challenger beats the incumbent's Sharpe AND its
Deflated Sharpe clears `settings.learning.min_dsr` (0.60)**. This is available any time
by hand; unlike the causal-graph research pipeline (`scripts/research_retest.py`, run
monthly by `deploy/systemd/ai-investing-retest.timer`), there is currently **no
periodic timer for this formula-level re-curation** — re-run it by hand, or ask for a
timer mirroring that pattern if continuous re-checking is wanted.

**Status as of 2026-08-15:** uncommitted locally, weight 0, not deployed — the engine
running in production has never evaluated this feature. Once committed and deployed it
starts computing, logging, and (via Path A) quietly earning trust or not; it stays
inert to every actual decision until it does.
