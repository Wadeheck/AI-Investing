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
