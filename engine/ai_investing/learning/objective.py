"""Performance metrics and the long-run objective J(θ) the optimizer maximizes.

The objective is risk-adjusted (Sharpe-based), penalizes churn, and regularizes θ
toward a prior so the formula matures smoothly instead of chasing recent trades.
"""
from __future__ import annotations

import math


def mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def std(xs: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))


def sharpe(returns: list[float], periods_per_year: int = 252) -> float:
    sd = std(returns)
    if sd == 0.0:
        return 0.0
    return (mean(returns) / sd) * math.sqrt(periods_per_year)


def sortino(returns: list[float], periods_per_year: int = 252) -> float:
    downside = [min(0.0, r) for r in returns]
    dd = math.sqrt(mean([d * d for d in downside]))
    if dd == 0.0:
        return 0.0
    return (mean(returns) / dd) * math.sqrt(periods_per_year)


def max_drawdown(equity_curve: list[float]) -> float:
    peak = -float("inf")
    mdd = 0.0
    for e in equity_curve:
        peak = max(peak, e)
        if peak > 0:
            mdd = max(mdd, (peak - e) / peak)
    return mdd


def cagr(equity_curve: list[float], periods_per_year: int = 252) -> float:
    if len(equity_curve) < 2 or equity_curve[0] <= 0:
        return 0.0
    years = (len(equity_curve) - 1) / periods_per_year
    if years <= 0:
        return 0.0
    return (equity_curve[-1] / equity_curve[0]) ** (1 / years) - 1


def expectancy(trade_returns: list[float]) -> float:
    return mean(trade_returns)


def metrics(equity_curve: list[float], returns: list[float],
            trade_returns: list[float] | None = None) -> dict:
    return {
        "sharpe": round(sharpe(returns), 3),
        "sortino": round(sortino(returns), 3),
        "cagr": round(cagr(equity_curve), 4),
        "max_drawdown": round(max_drawdown(equity_curve), 4),
        "total_return": round((equity_curve[-1] / equity_curve[0] - 1) if len(equity_curve) > 1 and equity_curve[0] else 0.0, 4),
        "n_trades": len(trade_returns or []),
        "expectancy": round(expectancy(trade_returns or []), 5),
        "final_equity": round(equity_curve[-1], 2) if equity_curve else 0.0,
    }


def objective_score(returns: list[float], turnover: float, theta: list[float],
                    theta_prior: list[float], lambda_turnover: float = 0.05,
                    lambda_reg: float = 0.10) -> float:
    """J(θ) = Sharpe − λ_turn · turnover − λ_reg · ‖θ − θ_prior‖²."""
    reg = sum((a - b) ** 2 for a, b in zip(theta, theta_prior))
    return sharpe(returns) - lambda_turnover * turnover - lambda_reg * reg


# --- statistical significance (Bailey & López de Prado) --------------------
def _norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _norm_ppf(p: float) -> float:
    """Inverse standard-normal CDF (Acklam's approximation)."""
    if p <= 0:
        return -float("inf")
    if p >= 1:
        return float("inf")
    a = [-3.969683028665376e1, 2.209460984245205e2, -2.759285104469687e2,
         1.383577518672690e2, -3.066479806614716e1, 2.506628277459239e0]
    b = [-5.447609879822406e1, 1.615858368580409e2, -1.556989798598866e2,
         6.680131188771972e1, -1.328068155288572e1]
    c = [-7.784894002430293e-3, -3.223964580411365e-1, -2.400758277161838e0,
         -2.549732539343734e0, 4.374664141464968e0, 2.938163982698783e0]
    d = [7.784695709041462e-3, 3.224671290700398e-1, 2.445134137142996e0, 3.754408661907416e0]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p <= phigh:
        q = p - 0.5
        r = q * q
        return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
               (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
    q = math.sqrt(-2 * math.log(1 - p))
    return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
           ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)


def _moment(returns: list[float], k: int) -> float:
    n = len(returns)
    if n < 2:
        return 0.0
    m = mean(returns)
    sd = std(returns)
    if sd == 0:
        return 0.0
    return sum(((r - m) / sd) ** k for r in returns) / n


def probabilistic_sharpe_ratio(returns: list[float], sr_benchmark: float = 0.0) -> float:
    """Prob. that the true (per-observation) Sharpe exceeds sr_benchmark, given skew/kurtosis."""
    n = len(returns)
    if n < 3:
        return 0.0
    sd = std(returns)
    if sd == 0:
        return 0.0
    sr = mean(returns) / sd            # per-observation Sharpe
    skew, kurt = _moment(returns, 3), _moment(returns, 4)
    denom = math.sqrt(max(1e-12, 1 - skew * sr + ((kurt - 1) / 4) * sr * sr))
    return _norm_cdf((sr - sr_benchmark) * math.sqrt(n - 1) / denom)


def deflated_sharpe_ratio(returns: list[float], n_trials: int,
                          sr_trials_std: float | None = None) -> float:
    """PSR against the Sharpe you'd expect from the BEST of `n_trials` random strategies —
    i.e. how much of the result survives the multiple-testing (selection) bias."""
    n = len(returns)
    if n < 3:
        return 0.0
    if n_trials <= 1:
        return probabilistic_sharpe_ratio(returns, 0.0)
    if not sr_trials_std or sr_trials_std <= 0:
        sr_trials_std = 1.0 / math.sqrt(n - 1)   # SR sampling std under the null
    gamma = 0.5772156649015329
    z1 = _norm_ppf(1 - 1.0 / n_trials)
    z2 = _norm_ppf(1 - 1.0 / (n_trials * math.e))
    sr_star = sr_trials_std * ((1 - gamma) * z1 + gamma * z2)
    return probabilistic_sharpe_ratio(returns, sr_star)
