"""Configuration loaded from environment / .env (no third-party deps)."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path


def _running_under_test() -> bool:
    """Is this process a test run?

    A TEST MUST NOT INHERIT THE OPERATOR'S CONFIG. `_load_dotenv` runs at import
    time, so importing config.py pulled the live `.env` into every test process —
    and three separate tests then passed on the dev box and failed on the ProDesk, or
    the reverse, because the two machines are configured differently
    (test_live_capital, test_scorecard_benchmark, test_execution; STATE §4.17).

    Each was fixed by pinning the value in the test. That is the symptom. This is the
    cause, and it is detected automatically rather than by an opt-in flag, because
    what actually failed three times was *remembering*.

    A test that genuinely wants the real file opens it directly — as the benchmark
    and watchlist coverage checks do — which is unaffected by this.
    """
    if os.environ.get("AI_INVESTING_LOAD_DOTENV") == "1":
        return False                       # explicit override, for a deliberate case
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return True
    argv0 = Path(sys.argv[0]).resolve() if sys.argv and sys.argv[0] else None
    if argv0 is not None:
        if argv0.parent.name == "tests" or argv0.name.startswith("test_"):
            return True
        if argv0.name in ("pytest", "py.test"):
            return True
    return False


def _load_dotenv(path: Path) -> None:
    """Tiny .env loader. Real environment variables always win."""
    if not path.exists():
        return
    if _running_under_test():
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


def _default_stock_watchlist() -> list[str]:
    """Fallback when STOCK_WATCHLIST is unset: every symbol the graph knows.

    Keeps "what the brain can reason about" and "what it can buy" from
    drifting apart — see brain.seed.tradable_stock_symbols for why.
    """
    from ai_investing.brain.seed import tradable_stock_symbols
    return tradable_stock_symbols()


def _default_crypto_watchlist() -> list[str]:
    """Fallback when CRYPTO_WATCHLIST is unset: every coin the graph knows.

    Same drift fix as _default_stock_watchlist, applied to crypto — see
    brain.seed.tradable_crypto_symbols for why the btc/eth/sol-only pin it
    replaces was safe to lift.
    """
    from ai_investing.brain.seed import tradable_crypto_symbols
    return tradable_crypto_symbols()


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
    etherscan_api_key: str = field(default_factory=lambda: _get("ETHERSCAN_API_KEY", ""))
    reddit_user_agent: str = field(default_factory=lambda: _get("REDDIT_USER_AGENT", "ai-investing/0.1 (research)"))
    # Binance long/short account ratio crowding signal (research/crypto_signals.py
    # positioning_crowding_z). Computed and cached every cycle regardless; this
    # flag only gates whether it's blended into brain resting levels. Off by
    # default -- dormant until it has accumulated enough real days to trust
    # (Binance only retains 30 days server-side, so there's no deep backtest to
    # gate this on; see docs/status/STATE_OF_THE_SYSTEM.md §4A/4B). 2026-08-15.
    positioning_enabled: bool = field(default_factory=lambda: _get_bool("CRYPTO_POSITIONING_ENABLED", False))


@dataclass
class BrainConfig:
    """The macro & relationship intelligence layer (see docs/design/BRAIN.md)."""
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
    # NewsData.io (free tier: 200 credits/day, 1 credit/request, ~12h delayed).
    # Polled as a SECONDARY live channel in data/news.py: on its own cooldown
    # (independent of the engine's 5-min poll cycle, which would blow the daily
    # credit budget in under an hour) and merged into the live headline pool
    # only where it isn't already covered by the primary wires/X capture.
    newsdata_api_key: str = field(default_factory=lambda: _get("NEWSDATA_API_KEY", ""))
    newsdata_poll_minutes: int = field(default_factory=lambda: _get_int("NEWSDATA_POLL_MINUTES", 30))
    # World News API (free tier: 50 points/day, ~1-1.2 points/request regardless
    # of batch size, 1 req/s, 1 month history, no front-pages endpoint -- search
    # only). Far thinner budget than NewsData, so the default cooldown is long;
    # also a SECONDARY channel, see data/news.py _worldnews_headlines.
    worldnews_api_key: str = field(default_factory=lambda: _get("WORLDNEWS_API_KEY", ""))
    worldnews_poll_minutes: int = field(default_factory=lambda: _get_int("WORLDNEWS_POLL_MINUTES", 90))
    db_path: str = field(default_factory=lambda: _get("BRAIN_DB_PATH", str(PROJECT_ROOT / "data" / "brain.db")))
    feed_cache_path: str = field(default_factory=lambda: _get("BRAIN_FEED_CACHE_PATH", str(PROJECT_ROOT / "data" / "feed_cache.json")))
    advice_path: str = field(default_factory=lambda: _get("BRAIN_ADVICE_PATH", str(PROJECT_ROOT / "data" / "advice.json")))
    sentiment_cache_path: str = field(default_factory=lambda: _get("BRAIN_SENTIMENT_CACHE_PATH", str(PROJECT_ROOT / "data" / "sentiment_cache.json")))
    advise_top_n: int = field(default_factory=lambda: _get_int("BRAIN_ADVISE_TOP_N", 10))
    # quality floor, not a quota: ideas below this conviction are never advised;
    # an empty list ("cash is a position") is legitimate output
    advise_min_conviction: float = field(default_factory=lambda: _get_float("BRAIN_ADVISE_MIN_CONVICTION", 0.10))
    credibility_threshold: float = field(default_factory=lambda: _get_float("BRAIN_CREDIBILITY_THRESHOLD", 0.35))
    # inference consultation (brain/consult.py): the bot asks you to judge its
    # READ of the news, not its orders. Raise the bar or drop the cap to be
    # asked less; set the cap to 0 to switch the channel off entirely.
    consult_enabled: bool = field(default_factory=lambda: _get_bool("CONSULT_ENABLED", True))
    # 0.20 measured against the real impulse distribution, not guessed — see the
    # ASK_BAR note in brain/consult.py. ~2.6 asks per active day; raise to be
    # asked less (0.25 -> ~1.9/day), lower to be asked more (0.15 -> ~3.9/day).
    consult_ask_bar: float = field(default_factory=lambda: _get_float("CONSULT_ASK_BAR", 0.20))
    consult_max_asks: int = field(default_factory=lambda: _get_int("CONSULT_MAX_ASKS", 2))
    consult_ttl_hours: float = field(default_factory=lambda: _get_float("CONSULT_TTL_HOURS", 72))
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
    # The 🏛 investing book's seed capital. investor.py has always read this via
    # `getattr(settings, "invest_starting_cash", 100000.0)` — and the attribute did
    # not exist, so the fallback fired every time and that book's size was
    # unconfigurable in practice. The sleeve and crypto books take
    # EVENT_START_CASH / CRYPTO_START_CASH; this is the missing third.
    invest_starting_cash: float = field(
        default_factory=lambda: _get_float("INVEST_STARTING_CASH", 100_000.0))
    # How much of a LIVE account this engine may treat as its own book, in
    # BASE_CURRENCY. 0 = off, meaning the whole account (the old behaviour).
    #
    # Every risk limit here is a FRACTION OF EQUITY, and with a live adapter
    # attached, equity is whatever the account holds. A Longbridge paper account
    # with USD 1M in it turns RISK_MAX_POSITION_WEIGHT=0.15 into a $150,000
    # position and puts the 5% daily breaker at -$50,000 — so losing a $10,000
    # stake in full registers as a 1% drawdown and trips nothing. The percentages
    # are only meaningful when the denominator is the money actually at risk.
    #
    # Set this and the engine keeps its own ledger over a slice of the account:
    # sizing, exposure, stops and every breaker measure against the slice, while
    # orders still route to the real venue. See execution/capital.py.
    live_capital_base: float = field(default_factory=lambda: _get_float("LIVE_CAPITAL_BASE", 0.0))
    # Route the sleeve's and the investing book's STOCK orders through the same
    # real account the trading book already uses, instead of each book pretending
    # against its own simulator. Off by default, and off is byte-for-byte the old
    # behaviour — this can be deployed long before it is switched on.
    #
    # There is no second account to give them: Longbridge's dashboard only toggles
    # between the one demo account and the real funded one. A funded account will
    # be exactly one account too, so "several books, one account" has to be solved
    # regardless; solving it against the demo account is the cheap version.
    #
    # Turning it on has three visible consequences, all deliberate:
    #   - stock orders are whole-share and can be refused for want of real cash;
    #   - stock SHORTS stop working (a short is indistinguishable from selling
    #     another book's shares — see brokers/shared.py). Crypto shorts are fine;
    #   - every book's stock positions become claims that must reconcile against
    #     the account each cycle, and a mismatch halts live trading.
    # It also requires LIVE_CAPITAL_BASE > 0; preflight refuses to start otherwise.
    shared_stock_account: bool = field(
        default_factory=lambda: _get_bool("SHARED_STOCK_ACCOUNT", False))
    stock_watchlist: list[str] = field(default_factory=lambda: _get_list("STOCK_WATCHLIST", _default_stock_watchlist()))
    crypto_watchlist: list[str] = field(default_factory=lambda: _get_list("CRYPTO_WATCHLIST", _default_crypto_watchlist()))
    data_provider: str = field(default_factory=lambda: _get("DATA_PROVIDER", "synthetic"))
    crypto_exchange: str = field(default_factory=lambda: _get("CRYPTO_EXCHANGE", "coinbase"))
    crypto_sandbox: bool = field(default_factory=lambda: _get_bool("CRYPTO_SANDBOX", False))
    # The ₿ crypto sleeve (strategy/crypto_book.py) always traded against an
    # in-memory PaperBroker, independent of LIVE_TRADING -- a deliberate
    # separation, not an oversight (its mandate calls itself "the live
    # implementation of ... what was tested", but "live" there meant live
    # DECISIONS, not a live order path). This is the one flag that puts a real
    # venue behind it: BinanceFuturesBroker, and only against the testnet
    # (it refuses to construct unless CRYPTO_SANDBOX=true). Off by default;
    # every existing deployment (incl. the ProDesk) keeps the old behaviour
    # until this is set AND BINANCE_FUTURES_TESTNET_API_KEY/SECRET are set —
    # a name deliberately distinct from CRYPTO_SANDBOX_API_KEY/SECRET above,
    # which CcxtBroker already uses for a different exchange's sandbox.
    crypto_book_live: bool = field(default_factory=lambda: _get_bool("CRYPTO_BOOK_LIVE", False))
    # Same idea, for the fast-execution/shock-reaction crypto strategy
    # (strategy/crypto_event_sleeve.py) — it stays on a local PaperBroker
    # until this is set. Uses its own BinanceFuturesBroker instance with
    # long_only=False, since this strategy can short (CRYPTO_EVENT_SHORT,
    # still off by default — this flag only arms the venue, not the trade).
    # Must point at a SEPARATE testnet account/key from CRYPTO_BOOK_LIVE's
    # BINANCE_FUTURES_TESTNET_API_KEY/SECRET (below) — one shared account
    # would let the two strategies' positions in the same coin net together
    # on the exchange, corrupting both books' own P&L tracking, which each
    # assumes it fully owns whatever position exists for a symbol it holds.
    crypto_event_live: bool = field(default_factory=lambda: _get_bool("CRYPTO_EVENT_LIVE", False))
    crypto_event_binance_api_key: str = field(
        default_factory=lambda: _get("CRYPTO_EVENT_BINANCE_TESTNET_API_KEY", ""))
    crypto_event_binance_api_secret: str = field(
        default_factory=lambda: _get("CRYPTO_EVENT_BINANCE_TESTNET_API_SECRET", ""))
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
        # WSJ's two feeds sat here from the initial commit and never delivered a
        # single fresh article: feeds.a.dj.com froze in Jan 2025, long before it
        # was subscribed (2026-08-16). FT is the same tier and already carries
        # SOURCE_TRUST 0.9, matching what wsj/dj.com had.
        "https://www.ft.com/rss/home",
        "https://feeds.content.dowjones.io/public/rss/mw_topstories",
        "http://feeds.bbci.co.uk/news/business/rss.xml",
        "https://feeds.marketwatch.com/marketwatch/topstories/",
        "https://www.theguardian.com/uk/business/rss",
        "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100727362",
        # Asia: China / HK / Japan / Korea / SG / India
        "https://www.scmp.com/rss/91/feed",
        "https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml&category=6936",  # CNA Business
        "https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml&category=6511",  # CNA Asia
        "https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml&category=10416", # CNA Singapore
        "https://www.japantimes.co.jp/feed/",
        "https://www.koreaherald.com/rss/newsAll",
        "https://www.scmp.com/rss/4/feed",       # SCMP China desk
        # State media, restored deliberately at LOW trust (0.45, "reads like
        # advocacy") for the official policy line. The earlier 11-day lag was not
        # CGTN being dead — it was the wrong section: /business.xml is neglected,
        # while /china.xml and /world.xml are current (0-1d, probed 2026-08-16).
        "https://www.cgtn.com/subscribe/rss/section/china.xml",   # CGTN China
        "https://www.cgtn.com/subscribe/rss/section/world.xml",   # CGTN World
        "https://www.scmp.com/rss/92/feed",      # SCMP China business/economy
        "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
        # Asia expansion (probed working 2026-07-30): KR/JP/CN/ID/TH/VN/IN/SG
        "https://en.yna.co.kr/RSS/news.xml",                      # Yonhap (KR)
        "https://www.koreatimes.co.kr/www/rss/rss.xml",           # Korea Times (KR)
        "https://asia.nikkei.com/rss/feed/nar",                   # Nikkei Asia (JP/pan-Asia)
        "https://mainichi.jp/rss/etc/english_latest.rss",         # Mainichi EN (JP)
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
        # 36kr is the only one of these that ever worked (257 articles,
        # 2026-07-31 to 08-05) before it swapped its feed for an HTML page.
        "https://technode.com/feed/",                             # TechNode (CN tech, en)
        "https://www.cnbeta.com.tw/backend.php",                  # cnBeta (CN, zh — tech)
        "https://www.ifanr.com/feed",                             # ifanr (CN, zh — consumer tech)
        # official / central banks
        "https://www.federalreserve.gov/feeds/press_all.xml",
        "https://www.boj.or.jp/en/rss/whatsnew.xml",
        "https://www.ecb.europa.eu/rss/press.html",
        "https://www.bankofengland.co.uk/rss/news",   # BoE — feeds the boe_rate/uk_* nodes (seed v12)
        # RBI is the only Asian central bank with a working public feed: PBoC,
        # HKMA, MAS, BoK, BIS and IMF were all probed 2026-08-16 and none serves
        # discoverable RSS. India is a large slice of this watchlist's news, so
        # the primary source is worth having on its own.
        "https://www.rbi.org.in/pressreleases_rss.xml",           # Reserve Bank of India
        # China's State Council publishing its own decisions — a PRIMARY source,
        # not state media commentary, and the closest thing to a PBoC/NBS feed
        # that actually exists. Chinese-language, read natively by the LLM.
        "https://www.gov.cn/pushinfo/v150203/rss.xml",            # PRC State Council (zh)
        # crypto + energy + commodities
        "https://www.coindesk.com/arc/outboundfeeds/rss/",
        # crypto expansion (probed working 2026-07-31): institutional/regulatory
        # depth + zh-language crypto wire (same early-Asia edge as the TW feeds)
        "https://www.theblock.co/rss.xml",                        # The Block (institutional/reg)
        "https://decrypt.co/feed",                                # Decrypt (broad crypto)
        # Wu Blockchain's substack feed froze in Jan 2021; the channel is fully
        # covered by the x.com/WuBlockchain capture (98 posts/7d), which the
        # existing "wublock" SOURCE_TRUST key already matches.
        # fast crypto-native tier — these break hours ahead of the wires, and
        # they also carry the pump material; trust is scored low in
        # brain/events.py SOURCE_TRUST so the chorus signature can use them
        # DL News SHUT DOWN — its feed still serves, and the newest item in it is
        # literally headlined "DL News is closing" (5 May 2026). Replaced with two
        # tested peers for the same DeFi/institutional-investigative slot.
        "https://thedefiant.io/api/feed",                         # The Defiant (DeFi/investigative)
        "https://blockworks.co/feed",                             # Blockworks (institutional)
        "https://protos.com/feed/",                               # Protos (skeptical, scam-focused)
        "https://cointelegraph.com/rss",                          # Cointelegraph (fast, hype-prone)
        "https://bitcoinmagazine.com/feed",                       # Bitcoin Magazine (BTC-native)
        "https://cryptobriefing.com/feed/",                       # Crypto Briefing (fast, low trust)
        "https://ambcrypto.com/feed/",                            # AMBCrypto (altcoin chatter/pumps)
        "https://rss.panewslab.com/zh/tvsq/rss",                  # PANews (CN, zh crypto wire)
        "https://oilprice.com/rss/main",
        # mining.com hard-403s our reader UA (an explicit "no bots" — not routed
        # around). Trade press replaces it; its syndicated stories still arrive
        # via NewsData, which is why the mining.com trust key stays.
        "https://www.northernminer.com/feed/",
        "https://www.mining-technology.com/feed/",
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
