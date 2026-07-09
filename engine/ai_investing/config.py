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


@dataclass
class Settings:
    live: bool = field(default_factory=lambda: _get_bool("LIVE_TRADING", False))
    base_currency: str = field(default_factory=lambda: _get("BASE_CURRENCY", "USD"))
    starting_cash: float = field(default_factory=lambda: _get_float("STARTING_CASH", 100_000.0))
    stock_watchlist: list[str] = field(default_factory=lambda: _get_list("STOCK_WATCHLIST", ["AAPL", "NVDA", "TSLA", "MSFT"]))
    crypto_watchlist: list[str] = field(default_factory=lambda: _get_list("CRYPTO_WATCHLIST", ["BTC/USD", "ETH/USD", "SOL/USD"]))
    data_provider: str = field(default_factory=lambda: _get("DATA_PROVIDER", "synthetic"))
    crypto_exchange: str = field(default_factory=lambda: _get("CRYPTO_EXCHANGE", "coinbase"))
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


settings = Settings()
