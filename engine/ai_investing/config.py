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
        val = val.strip()
        if val and val[0] in "\"'":
            quote = val[0]
            end = val.find(quote, 1)
            val = val[1:end] if end != -1 else val[1:]
        else:
            hash_idx = val.find(" #")
            if hash_idx != -1:
                val = val[:hash_idx].strip()
        os.environ.setdefault(key.strip(), val)


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
    # HARD RULE (user): no single position may lose more than this — caps every
    # stop (flat or ATR-scaled) in every book. Not advisory.
    max_loss_per_position: float = field(default_factory=lambda: _get_float("RISK_MAX_LOSS_PER_POSITION", 0.10))
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
    # structural theme-cluster cap: max gross exposure to ONE graph cluster
    # (AI-capex, china-consumer, ...) as a fraction of equity. Correlation is
    # backward-looking; this limits the BET even when tickers look uncorrelated.
    max_cluster_exposure: float = field(default_factory=lambda: _get_float("RISK_MAX_CLUSTER_EXPOSURE", 0.35))
    # scheduled-event throttle for NEW entries (earnings window / FOMC days)
    event_derisk: bool = field(default_factory=lambda: _get_bool("RISK_EVENT_DERISK", True))
    earnings_window_days: int = field(default_factory=lambda: _get_int("RISK_EARNINGS_WINDOW_DAYS", 2))
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
class BrainConfig:
    """The macro & relationship intelligence layer (see docs/BRAIN.md)."""
    enabled: bool = field(default_factory=lambda: _get_bool("BRAIN_ENABLED", True))
    graph_path: str = field(default_factory=lambda: _get("BRAIN_GRAPH_PATH", str(PROJECT_ROOT / "data" / "knowledge_graph.json")))
    regime_path: str = field(default_factory=lambda: _get("BRAIN_REGIME_PATH", str(PROJECT_ROOT / "data" / "macro_regime.json")))
    scenarios_path: str = field(default_factory=lambda: _get("BRAIN_SCENARIOS_PATH", str(PROJECT_ROOT / "data" / "scenarios.json")))
    state_path: str = field(default_factory=lambda: _get("BRAIN_STATE_PATH", str(PROJECT_ROOT / "data" / "brain.json")))
    macro_cache_path: str = field(default_factory=lambda: _get("BRAIN_MACRO_CACHE_PATH", str(PROJECT_ROOT / "data" / "macro_cache.json")))
    field_path: str = field(default_factory=lambda: _get("BRAIN_FIELD_PATH", str(PROJECT_ROOT / "data" / "field_state.json")))
    fred_api_key: str = field(default_factory=lambda: _get("FRED_API_KEY", ""))
    # historical news archives (free registration) — fill the wiki-thin days
    guardian_api_key: str = field(default_factory=lambda: _get("GUARDIAN_API_KEY", ""))
    nyt_api_key: str = field(default_factory=lambda: _get("NYT_API_KEY", ""))
    db_path: str = field(default_factory=lambda: _get("BRAIN_DB_PATH", str(PROJECT_ROOT / "data" / "brain.db")))
    feed_cache_path: str = field(default_factory=lambda: _get("BRAIN_FEED_CACHE_PATH", str(PROJECT_ROOT / "data" / "feed_cache.json")))
    advice_path: str = field(default_factory=lambda: _get("BRAIN_ADVICE_PATH", str(PROJECT_ROOT / "data" / "advice.json")))
    sentiment_cache_path: str = field(default_factory=lambda: _get("BRAIN_SENTIMENT_CACHE_PATH", str(PROJECT_ROOT / "data" / "sentiment_cache.json")))
    advise_top_n: int = field(default_factory=lambda: _get_int("BRAIN_ADVISE_TOP_N", 10))
    # quality floor, not a quota: ideas below this conviction are never advised;
    # an empty list ("cash is a position") is legitimate output
    advise_min_conviction: float = field(default_factory=lambda: _get_float("BRAIN_ADVISE_MIN_CONVICTION", 0.10))
    credibility_threshold: float = field(default_factory=lambda: _get_float("BRAIN_CREDIBILITY_THRESHOLD", 0.35))
    max_hops: int = field(default_factory=lambda: _get_int("BRAIN_MAX_HOPS", 3))
    decay: float = field(default_factory=lambda: _get_float("BRAIN_DECAY", 0.6))


@dataclass
class SafetyConfig:
    # circuit breakers (drawdown halts)
    max_trailing_drawdown: float = field(default_factory=lambda: _get_float("SAFETY_MAX_TRAILING_DD", 0.15))
    max_inception_drawdown: float = field(default_factory=lambda: _get_float("SAFETY_MAX_INCEPTION_DD", 0.25))
    # monthly high-water mark (user's ratchet): a month that ends higher locks
    # that equity as the new base; falling this far below the locked base
    # blocks new positions until recovery
    hwm_drawdown_limit: float = field(default_factory=lambda: _get_float("SAFETY_HWM_DD", 0.10))
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
    deepseek_api_key: str = field(default_factory=lambda: _get("DEEPSEEK_API_KEY", ""))
    deepseek_model: str = field(default_factory=lambda: _get("DEEPSEEK_MODEL", "deepseek-chat"))
    # Local open-source LLM (Ollama / OpenAI-compatible). FREE — preferred when up.
    local_llm_url: str = field(default_factory=lambda: _get("LOCAL_LLM_URL", "http://localhost:11434"))
    local_llm_model: str = field(default_factory=lambda: _get("LOCAL_LLM_MODEL", "qwen3.6:27b"))          # smart tier
    local_llm_model_fast: str = field(default_factory=lambda: _get("LOCAL_LLM_MODEL_FAST", "qwen3:8b"))   # per-cycle volume
    llm_prefer_local: bool = field(default_factory=lambda: _get_bool("LLM_PREFER_LOCAL", True))
    byteplus_api_key: str = field(default_factory=lambda: _get("BYTEPLUS_API_KEY", ""))
    byteplus_model_smart: str = field(default_factory=lambda: _get("BYTEPLUS_LLM_SMART", "seed-2-0-pro-260328"))
    byteplus_model_fast: str = field(default_factory=lambda: _get("BYTEPLUS_LLM_FAST", "seed-2-0-mini-260428"))
    # Failover chains of authorized access points, tried in order. This is what
    # lets the local GPU be retired: one endpoint dying no longer means the brain
    # stops reading, because two more answer the same call. Each carries its own
    # free daily allowance, so the chain is also a budget overflow path.
    byteplus_chain_fast: list[str] = field(
        default_factory=lambda: _get_list("BYTEPLUS_CHAIN_FAST", []))
    byteplus_chain_smart: list[str] = field(
        default_factory=lambda: _get_list("BYTEPLUS_CHAIN_SMART", []))
    # Free tokens/day per authorized endpoint. Crossing it starts costing money
    # silently, so usage is metered and surfaced in scripts/daily_status.py.
    llm_daily_free_tokens: int = field(
        default_factory=lambda: _get_int("LLM_DAILY_FREE_TOKENS", 5_000_000))
    news_rss: list[str] = field(default_factory=lambda: _get_list("NEWS_RSS", [
        # global markets / macro
        "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
        "https://feeds.a.dj.com/rss/RSSWorldNews.xml",
        "http://feeds.bbci.co.uk/news/business/rss.xml",
        "https://feeds.marketwatch.com/marketwatch/topstories/",
        "https://www.theguardian.com/uk/business/rss",
        "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100727362",
        # Asia: China / HK / Japan / Korea / SG / India
        "https://www.scmp.com/rss/91/feed",
        "https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml&category=6936",
        "https://www.japantimes.co.jp/feed/",
        "https://www.koreaherald.com/rss/newsAll",
        "https://www.globaltimes.cn/rss/outbrain.xml",
        "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
        # Asia expansion (probed working 2026-07-30): KR/JP/CN/ID/TH/VN/IN/SG
        "https://en.yna.co.kr/RSS/news.xml",                      # Yonhap (KR)
        "https://www.kedglobal.com/rss",                          # Korea Economic Daily (KR)
        "https://asia.nikkei.com/rss/feed/nar",                   # Nikkei Asia (JP/pan-Asia)
        "https://mainichi.jp/rss/etc/english_latest.rss",         # Mainichi EN (JP)
        "http://www.xinhuanet.com/english/rss/businessrss.xml",   # Xinhua business (CN)
        "https://www.chinadaily.com.cn/rss/bizchina_rss.xml",     # China Daily biz (CN)
        "https://en.antaranews.com/rss/news.xml",                 # Antara (ID)
        "https://voi.id/en/rss",                                  # VOI (ID)
        "https://www.bangkokpost.com/rss/data/business.xml",      # Bangkok Post biz (TH)
        "https://e.vnexpress.net/rss/business.rss",               # VnExpress biz (VN)
        "https://www.livemint.com/rss/markets",                   # Mint markets (IN)
        "https://www.thehindubusinessline.com/markets/feeder/default.rss",  # Hindu BusinessLine (IN)
        "https://www.straitstimes.com/news/business/rss.xml",     # Straits Times biz (SG)
        # Taiwan + native-language sources (probed working 2026-07-31; zh-language
        # headlines are matched via CJK aliases offline and read natively by the LLM)
        "https://news.ltn.com.tw/rss/business.xml",               # Liberty Times biz (TW, zh)
        "https://news.cnyes.com/rss/v1/news/category/tw_stock",   # cnyes TW stocks (TW, zh)
        "https://technews.tw/feed/",                              # TechNews (TW, zh — semis)
        "https://www.taipeitimes.com/xml/index.rss",              # Taipei Times (TW, en)
        "https://feeds.feedburner.com/rsscna/finance",            # CNA finance (TW, zh)
        "https://rthk.hk/rthk/news/rss/e_expressnews_efinance.xml",  # RTHK finance (HK, en)
        "https://rthk.hk/rthk/news/rss/c_expressnews_cfinance.xml",  # RTHK finance (HK, zh)
        "https://36kr.com/feed",                                  # 36kr (CN, zh — tech)
        # official / central banks
        "https://www.federalreserve.gov/feeds/press_all.xml",
        "https://www.boj.or.jp/en/rss/whatsnew.xml",
        "https://www.ecb.europa.eu/rss/press.html",
        "https://www.bankofengland.co.uk/rss/news",   # BoE — feeds the boe_rate/uk_* nodes (seed v12)
        # crypto + energy + commodities
        "https://www.coindesk.com/arc/outboundfeeds/rss/",
        # crypto expansion (probed working 2026-07-31): institutional/regulatory
        # depth + zh-language crypto wire (same early-Asia edge as the TW feeds)
        "https://www.theblock.co/rss.xml",                        # The Block (institutional/reg)
        "https://decrypt.co/feed",                                # Decrypt (broad crypto)
        "https://wublockchain.substack.com/feed",                 # Wu Blockchain (CN mining/exchange/reg)
        # fast crypto-native tier — these break hours ahead of the wires, and
        # they also carry the pump material; trust is scored low in
        # brain/events.py SOURCE_TRUST so the chorus signature can use them
        "https://www.dlnews.com/arc/outboundfeeds/rss/",          # DL News (DeFi/investigative)
        "https://protos.com/feed/",                               # Protos (skeptical, scam-focused)
        "https://cointelegraph.com/rss",                          # Cointelegraph (fast, hype-prone)
        "https://bitcoinmagazine.com/feed",                       # Bitcoin Magazine (BTC-native)
        "https://cryptobriefing.com/feed/",                       # Crypto Briefing (fast, low trust)
        "https://ambcrypto.com/feed/",                            # AMBCrypto (altcoin chatter/pumps)
        "https://rss.panewslab.com/zh/tvsq/rss",                  # PANews (CN, zh crypto wire)
        "https://oilprice.com/rss/main",
        "https://www.mining.com/feed/",
    ]))
    db_path: str = field(default_factory=lambda: _get("DB_PATH", str(PROJECT_ROOT / "data" / "journal.db")))
    state_path: str = field(default_factory=lambda: _get("STATE_PATH", str(PROJECT_ROOT / "data" / "state.json")))
    # human-in-the-loop: new entries wait for your Telegram approval
    trade_approval: bool = field(default_factory=lambda: _get_bool("TRADE_APPROVAL", False))
    approval_ttl_hours: float = field(default_factory=lambda: float(_get("APPROVAL_TTL_HOURS", "12")))
    proposals_path: str = field(default_factory=lambda: _get("PROPOSALS_PATH", str(PROJECT_ROOT / "data" / "proposals.json")))
    params_path: str = field(default_factory=lambda: _get("PARAMS_PATH", str(PROJECT_ROOT / "data" / "formula.json")))
    risk: RiskConfig = field(default_factory=RiskConfig)
    learning: LearningConfig = field(default_factory=LearningConfig)
    cost: CostConfig = field(default_factory=CostConfig)
    regime: RegimeConfig = field(default_factory=RegimeConfig)
    alerts: AlertConfig = field(default_factory=AlertConfig)
    altdata: AltDataConfig = field(default_factory=AltDataConfig)
    brain: BrainConfig = field(default_factory=BrainConfig)
    safety: SafetyConfig = field(default_factory=SafetyConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    breaker_path: str = field(default_factory=lambda: _get("BREAKER_PATH", str(PROJECT_ROOT / "data" / "breaker.json")))
    heartbeat_path: str = field(default_factory=lambda: _get("HEARTBEAT_PATH", str(PROJECT_ROOT / "data" / "heartbeat.json")))
    user_views_path: str = field(default_factory=lambda: _get("USER_VIEWS_PATH", str(PROJECT_ROOT / "data" / "views.json")))

    @property
    def llm_available(self) -> bool:
        """True if any LLM provider is configured (news sentiment/briefing feature)."""
        return bool(self.anthropic_api_key or self.byteplus_api_key or self.deepseek_api_key)


settings = Settings()
