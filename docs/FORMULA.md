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
| `consensus` | mean of the four signal features |
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
- `θ` = the 7 feature weights (the heart of the model).
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
2. **Search** hyperparameters for the best Sharpe on the *next, unseen* slice.
3. **Champion/challenger:** adopt the new formula only if it beats the incumbent
   averaged across windows. This is the anti-overfitting gate.

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
