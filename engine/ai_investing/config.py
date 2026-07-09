"""Configuration loaded from environment / .env (no third-party deps)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    """Tiny .env loader. Real environment variables always win."""
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def _get(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def _get_bool(name: str, default: bool = False) -> bool:
    return _get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _get_float(name: str, default: float) -> float:
    try:
        return float(_get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _get_int(name: str, default: int) -> int:
    try:
        return int(float(_get(name, str(default))))
    except (TypeError, ValueError):
        return default


def _get_list(name: str, default: list[str]) -> list[str]:
    raw = _get(name, "")
    return [s.strip() for s in raw.split(",") if s.strip()] if raw else list(default)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
_load_dotenv(PROJECT_ROOT / ".env")


@dataclass
class RiskConfig:
    max_position_weight: float = field(default_factory=lambda: _get_float("RISK_MAX_POSITION_WEIGHT", 0.15))
    max_gross_exposure: float = field(default_factory=lambda: _get_float("RISK_MAX_GROSS_EXPOSURE", 1.0))
    per_trade_stop_loss: float = field(default_factory=lambda: _get_float("RISK_STOP_LOSS", 0.08))
    take_profit: float = field(default_factory=lambda: _get_float("RISK_TAKE_PROFIT", 0.25))
    max_daily_drawdown: float = field(default_factory=lambda: _get_float("RISK_MAX_DAILY_DRAWDOWN", 0.05))
    min_confidence: float = field(default_factory=lambda: _get_float("RISK_MIN_CONFIDENCE", 0.35))
    max_open_positions: int = field(default_factory=lambda: _get_int("RISK_MAX_OPEN_POSITIONS", 12))
    allow_short: bool = field(default_factory=lambda: _get_bool("RISK_ALLOW_SHORT", False))
    # volatility targeting & ATR-based stops
    use_vol_target: bool = field(default_factory=lambda: _get_bool("RISK_USE_VOL_TARGET", True))
    target_position_vol: float = field(default_factory=lambda: _get_float("RISK_TARGET_POSITION_VOL", 0.02))
    use_atr_stops: bool = field(default_factory=lambda: _get_bool("RISK_USE_ATR_STOPS", True))
    atr_stop_mult: float = field(default_factory=lambda: _get_float("RISK_ATR_STOP_MULT", 3.0))
    atr_take_mult: float = field(default_factory=lambda: _get_float("RISK_ATR_TAKE_MULT", 6.0))
    # portfolio-level risk
    corr_penalty: float = field(default_factory=lambda: _get_float("RISK_CORR_PENALTY", 0.5))
    portfolio_vol_target: float = field(default_factory=lambda: _get_float("RISK_PORTFOLIO_VOL_TARGET", 0.02))
    dd_derisk_scale: float = field(default_factory=lambda: _get_float("RISK_DD_DERISK_SCALE", 2.0))
    dd_derisk_floor: float = field(default_factory=lambda: _get_float("RISK_DD_DERISK_FLOOR", 0.3))


@dataclass
class CostConfig:
    enabled: bool = field(default_factory=lambda: _get_bool("COST_ENABLED", True))
    commission_bps: float = field(default_factory=lambda: _get_float("COST_COMMISSION_BPS", 1.0))
    spread_bps: float = field(default_factory=lambda: _get_float("COST_SPREAD_BPS", 2.0))
    slippage_coef: float = field(default_factory=lambda: _get_float("COST_SLIPPAGE_COEF", 0.1))


@dataclass
class RegimeConfig:
    enabled: bool = field(default_factory=lambda: _get_bool("REGIME_ENABLED", True))
    high_vol: float = field(default_factory=lambda: _get_float("REGIME_HIGH_VOL", 0.04))
    ood_z: float = field(default_factory=lambda: _get_float("REGIME_OOD_Z", 4.0))
    min_mult: float = field(default_factory=lambda: _get_float("REGIME_MIN_MULT", 0.4))


@dataclass
class LearningConfig:
    enable_online: bool = field(default_factory=lambda: _get_bool("LEARN_ONLINE", True))
    forgetting_mu: float = field(default_factory=lambda: _get_float("LEARN_FORGETTING", 0.999))
    prior_confidence: float = field(default_factory=lambda: _get_float("LEARN_PRIOR_CONFIDENCE", 50.0))
    trust_region: float = field(default_factory=lambda: _get_float("LEARN_TRUST_REGION", 0.01))
    min_samples: int = field(default_factory=lambda: _get_int("LEARN_MIN_SAMPLES", 10))
    save_every: int = field(default_factory=lambda: _get_int("LEARN_SAVE_EVERY", 5))
    horizon: int = field(default_factory=lambda: _get_int("LEARN_HORIZON", 5))
    reg: float = field(default_factory=lambda: _get_float("LEARN_REG", 0.01))
    walkforward_windows: int = field(default_factory=lambda: _get_int("LEARN_WF_WINDOWS", 3))
    walkforward_search: int = field(default_factory=lambda: _get_int("LEARN_WF_SEARCH", 16))
    lambda_turnover: float = field(default_factory=lambda: _get_float("LEARN_LAMBDA_TURNOVER", 0.05))
    lambda_reg: float = field(default_factory=lambda: _get_float("LEARN_LAMBDA_REG", 0.10))
    embargo: int = field(default_factory=lambda: _get_int("LEARN_EMBARGO", 5))
    min_dsr: float = field(default_factory=lambda: _get_float("LEARN_MIN_DSR", 0.60))


@dataclass
class AlertConfig:
    telegram_bot_token: str = field(default_factory=lambda: _get("TELEGRAM_BOT_TOKEN", ""))
    telegram_chat_id: str = field(default_factory=lambda: _get("TELEGRAM_CHAT_ID", ""))
    on_trade: bool = field(default_factory=lambda: _get_bool("ALERT_ON_TRADE", True))
    on_error: bool = field(default_factory=lambda: _get_bool("ALERT_ON_ERROR", True))
    on_kill: bool = field(default_factory=lambda: _get_bool("ALERT_ON_KILL", True))
    min_notional: float = field(default_factory=lambda: _get_float("ALERT_MIN_NOTIONAL", 0.0))


@dataclass
class AltDataConfig:
    enabled: bool = field(default_factory=lambda: _get_bool("ALTDATA_ENABLED", False))
    polygon_api_key: str = field(default_factory=lambda: _get("POLYGON_API_KEY", ""))
    coingecko_api_key: str = field(default_factory=lambda: _get("COINGECKO_API_KEY", ""))
    reddit_user_agent: str = field(default_factory=lambda: _get("REDDIT_USER_AGENT", "ai-investing/0.1 (research)"))


@dataclass
class SafetyConfig:
    # circuit breakers (drawdown halts)
    max_trailing_drawdown: float = field(default_factory=lambda: _get_float("SAFETY_MAX_TRAILING_DD", 0.15))
    max_inception_drawdown: float = field(default_factory=lambda: _get_float("SAFETY_MAX_INCEPTION_DD", 0.25))
    # per-day hard caps
    max_trades_per_day: int = field(default_factory=lambda: _get_int("SAFETY_MAX_TRADES_PER_DAY", 50))
    max_notional_per_day: float = field(default_factory=lambda: _get_float("SAFETY_MAX_NOTIONAL_PER_DAY", 0.0))  # 0 = off
    # execution / data guards
    max_slippage_bps: float = field(default_factory=lambda: _get_float("SAFETY_MAX_SLIPPAGE_BPS", 50.0))
    max_price_jump: float = field(default_factory=lambda: _get_float("SAFETY_MAX_PRICE_JUMP", 0.5))
    max_bar_staleness_days: float = field(default_factory=lambda: _get_float("SAFETY_MAX_BAR_STALENESS_DAYS", 5.0))
    halt_on_data_anomaly: bool = field(default_factory=lambda: _get_bool("SAFETY_HALT_ON_DATA_ANOMALY", True))
    # dead-man's switch
    flatten_on_exit: bool = field(default_factory=lambda: _get_bool("SAFETY_FLATTEN_ON_EXIT", False))
    flatten_on_stall: bool = field(default_factory=lambda: _get_bool("SAFETY_FLATTEN_ON_STALL", False))
    heartbeat_stale_seconds: int = field(default_factory=lambda: _get_int("SAFETY_HEARTBEAT_STALE_SECONDS", 1800))


@dataclass
class ExecutionConfig:
    order_type: str = field(default_factory=lambda: _get("EXECUTION_ORDER_TYPE", "limit"))  # limit | market
    limit_band_bps: float = field(default_factory=lambda: _get_float("EXECUTION_LIMIT_BAND_BPS", 25.0))
    stop_at_exchange: bool = field(default_factory=lambda: _get_bool("EXECUTION_STOP_AT_EXCHANGE", False))


@dataclass
class Settings:
    live: bool = field(default_factory=lambda: _get_bool("LIVE_TRADING", False))
    base_currency: str = field(default_factory=lambda: _get("BASE_CURRENCY", "USD"))
    starting_cash: float = field(default_factory=lambda: _get_float("STARTING_CASH", 100_000.0))
    stock_watchlist: list[str] = field(default_factory=lambda: _get_list("STOCK_WATCHLIST", ["AAPL", "NVDA", "TSLA", "MSFT"]))
    crypto_watchlist: list[str] = field(default_factory=lambda: _get_list("CRYPTO_WATCHLIST", ["BTC/USD", "ETH/USD", "SOL/USD"]))
    data_provider: str = field(default_factory=lambda: _get("DATA_PROVIDER", "synthetic"))
    crypto_exchange: str = field(default_factory=lambda: _get("CRYPTO_EXCHANGE", "coinbase"))
    crypto_sandbox: bool = field(default_factory=lambda: _get_bool("CRYPTO_SANDBOX", False))
    data_timeframe: str = field(default_factory=lambda: _get("DATA_TIMEFRAME", "1d"))  # 1d | 1h | 15m | 5m ...
    stock_broker: str = field(default_factory=lambda: _get("STOCK_BROKER", "paper"))
    poll_seconds: int = field(default_factory=lambda: _get_int("POLL_SECONDS", 300))
    anthropic_api_key: str = field(default_factory=lambda: _get("ANTHROPIC_API_KEY", ""))
    anthropic_model: str = field(default_factory=lambda: _get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001"))
    news_rss: list[str] = field(default_factory=lambda: _get_list("NEWS_RSS", [
        "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
        "http://feeds.bbci.co.uk/news/business/rss.xml",
    ]))
    db_path: str = field(default_factory=lambda: _get("DB_PATH", str(PROJECT_ROOT / "data" / "journal.db")))
    state_path: str = field(default_factory=lambda: _get("STATE_PATH", str(PROJECT_ROOT / "data" / "state.json")))
    params_path: str = field(default_factory=lambda: _get("PARAMS_PATH", str(PROJECT_ROOT / "data" / "formula.json")))
    risk: RiskConfig = field(default_factory=RiskConfig)
    learning: LearningConfig = field(default_factory=LearningConfig)
    cost: CostConfig = field(default_factory=CostConfig)
    regime: RegimeConfig = field(default_factory=RegimeConfig)
    alerts: AlertConfig = field(default_factory=AlertConfig)
    altdata: AltDataConfig = field(default_factory=AltDataConfig)
    safety: SafetyConfig = field(default_factory=SafetyConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    breaker_path: str = field(default_factory=lambda: _get("BREAKER_PATH", str(PROJECT_ROOT / "data" / "breaker.json")))
    heartbeat_path: str = field(default_factory=lambda: _get("HEARTBEAT_PATH", str(PROJECT_ROOT / "data" / "heartbeat.json")))


settings = Settings()
