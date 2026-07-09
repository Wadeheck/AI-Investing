"""Startup config validation — catches the fat-fingered .env that would otherwise
lose you money (bad limits, LIVE with no caps, disabled costs). Returns (errors,
warnings); the runner refuses to start LIVE with errors."""
from __future__ import annotations


def validate_settings(settings) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    r = settings.risk
    sf = settings.safety

    if settings.starting_cash <= 0:
        errors.append("STARTING_CASH must be > 0")
    if not (0 < r.max_position_weight <= 1):
        errors.append(f"RISK_MAX_POSITION_WEIGHT out of range: {r.max_position_weight}")
    if not (0 < r.max_gross_exposure <= 5):
        warnings.append(f"RISK_MAX_GROSS_EXPOSURE unusual: {r.max_gross_exposure}")

    for name, v in [("RISK_STOP_LOSS", r.per_trade_stop_loss),
                    ("RISK_MAX_DAILY_DRAWDOWN", r.max_daily_drawdown),
                    ("SAFETY_MAX_TRAILING_DD", sf.max_trailing_drawdown),
                    ("SAFETY_MAX_INCEPTION_DD", sf.max_inception_drawdown)]:
        if not (0 < v < 1):
            warnings.append(f"{name} looks off: {v}")

    if r.max_daily_drawdown > sf.max_trailing_drawdown:
        warnings.append("daily drawdown limit exceeds trailing limit — daily breaker may never bind")
    if not settings.cost.enabled:
        warnings.append("COST model disabled — results will be optimistic vs. live")

    if settings.live:
        if sf.max_notional_per_day <= 0:
            warnings.append("LIVE with no SAFETY_MAX_NOTIONAL_PER_DAY cap — strongly recommended to set one")
        if settings.stock_broker == "paper" and settings.stock_watchlist:
            warnings.append("LIVE but STOCK_BROKER=paper — stock trades will NOT be real")
        if r.allow_short:
            warnings.append("shorting enabled in LIVE — confirm the venue/account supports it")

    return errors, warnings
