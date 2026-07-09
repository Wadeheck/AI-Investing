"""CLI entrypoint.

    cd engine
    python -m ai_investing.main --once          # one evaluation pass (great first run)
    python -m ai_investing.main                 # autonomous loop (fully automated)
    python -m ai_investing.main --briefing      # just the global world briefing
    python -m ai_investing.main --once --no-news # offline: skip news/LLM, price signals only
"""
from __future__ import annotations

import argparse

from ai_investing.config import settings
from ai_investing.data import news as news_mod
from ai_investing.learning.store import ParamStore
from ai_investing.runner import Runner


def _banner() -> None:
    mode = "LIVE — REAL MONEY" if settings.live else "PAPER (simulated)"
    print("=" * 68)
    print(f"  AI-Investing engine   |   mode: {mode}")
    print(f"  data: {settings.data_provider}   stocks: {settings.stock_broker}   "
          f"crypto: {settings.crypto_exchange}")
    print(f"  watchlist: {', '.join(settings.stock_watchlist + settings.crypto_watchlist)}")
    if settings.live:
        print("  !! LIVE trading is ON. Orders will hit a real broker.")
    print("=" * 68)


def _check_broker() -> None:
    """Read-only validation of live broker legs (crypto via ccxt, stocks via SDK)."""
    from ai_investing.brokers import _make_crypto_broker, _make_stock_broker
    print(f"Checking live brokers — stocks: {settings.stock_broker}, crypto: {settings.crypto_exchange}")
    for label, make in (("stocks", _make_stock_broker), ("crypto", _make_crypto_broker)):
        try:
            broker = make(settings)
            info = broker.validate() if hasattr(broker, "validate") else {"broker": broker.name}
            print(f"  [ok]   {label}: {info}")
        except Exception as exc:
            print(f"  [FAIL] {label}: {type(exc).__name__}: {exc}")
    print("\nThis was read-only. Trade tiny against sandbox/SIMULATE before LIVE_TRADING=true.")


def _test_alert() -> None:
    from ai_investing.alerts import get_notifier
    n = get_notifier(settings)
    if not n.enabled:
        print("Telegram not configured — set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env.")
        return
    ok = n.send("✅ *AI-Investing* test alert — your Telegram alerts are working.")
    print("Sent." if ok else "Send failed — check the token / chat id.")


def _show_altdata() -> None:
    from ai_investing.data import altdata
    from ai_investing.models import Asset, AssetClass
    assets = ([Asset(s, AssetClass.STOCK) for s in settings.stock_watchlist]
              + [Asset(s, AssetClass.CRYPTO, exchange=settings.crypto_exchange)
                 for s in settings.crypto_watchlist])
    print(f"Alt-data (ALTDATA_ENABLED={settings.altdata.enabled}; this command probes regardless):")
    for a in assets:
        agg = altdata.aggregate(altdata.collect(settings, a.symbol, a.asset_class.value))
        status = agg["detail"] if agg["available"] else "unavailable (missing key / no network / no data)"
        print(f"  {a.symbol:<10} intensity {agg['intensity']:.2f}  bullish {agg['bullish']:+.2f}  {status}")


def _watchdog() -> None:
    """Dead-man's switch: alert (and optionally flatten) if the engine's heartbeat is stale."""
    from ai_investing.alerts import get_notifier
    from ai_investing.safety import age_seconds, is_stale, read_heartbeat
    hb = read_heartbeat(settings.heartbeat_path)
    if hb is None:
        print("No heartbeat found — has the engine run?")
        return
    age = age_seconds(hb) or 0.0
    print(f"heartbeat: age {age:.0f}s  equity ${hb.get('equity', 0):,.0f}  "
          f"halted {hb.get('halted')}  cycle {hb.get('cycle')}")
    if not is_stale(hb, settings.safety.heartbeat_stale_seconds):
        print("OK — engine is alive.")
        return
    print(f"STALE (> {settings.safety.heartbeat_stale_seconds}s) — engine may be down.")
    get_notifier(settings).send(f"🚨 AI-Investing heartbeat STALE ({age:.0f}s) — engine may be down.")
    if settings.safety.flatten_on_stall and settings.live:
        from ai_investing.brokers import get_broker
        from ai_investing.models import Order, Side
        broker = get_broker(settings)
        positions = broker.get_positions()
        if positions:
            print(f"flatten_on_stall — closing {len(positions)} positions (market).")
            for _, pos in list(positions.items()):
                side = Side.SELL if pos.qty > 0 else Side.BUY
                broker.submit(Order(pos.asset, side, abs(pos.qty), reason="watchdog-flatten"), pos.avg_price)


def _breaker(reset: bool) -> None:
    from ai_investing.safety import CircuitBreaker
    cb = CircuitBreaker(settings.safety, settings.risk.max_daily_drawdown, settings.breaker_path)
    if reset:
        cb.reset()
        print("Circuit breaker reset — halt cleared.")
    print("Breaker state:", cb.status())


def main() -> None:
    parser = argparse.ArgumentParser(description="Autonomous AI investing engine (paper-first).")
    parser.add_argument("--once", action="store_true", help="run a single cycle and exit")
    parser.add_argument("--briefing", action="store_true", help="print the global briefing and exit")
    parser.add_argument("--no-news", action="store_true", help="skip news/LLM; price signals only")
    parser.add_argument("--formula", action="store_true", help="print the current decision formula and exit")
    parser.add_argument("--check-broker", action="store_true",
                        help="read-only: validate live broker credentials/connectivity, no trading")
    parser.add_argument("--test-alert", action="store_true", help="send a test Telegram alert and exit")
    parser.add_argument("--altdata", action="store_true", help="fetch alt-data for the watchlist and exit")
    parser.add_argument("--watchdog", action="store_true", help="dead-man's switch: check heartbeat, alert/flatten if stale")
    parser.add_argument("--breaker-status", action="store_true", help="print the circuit-breaker state and exit")
    parser.add_argument("--breaker-reset", action="store_true", help="clear a latched circuit-breaker halt and exit")
    args = parser.parse_args()

    if args.briefing:
        print(news_mod.global_briefing(settings))
        return

    if args.check_broker:
        _check_broker()
        return

    if args.test_alert:
        _test_alert()
        return

    if args.altdata:
        _show_altdata()
        return

    if args.watchdog:
        _watchdog()
        return

    if args.breaker_status or args.breaker_reset:
        _breaker(reset=args.breaker_reset)
        return

    if args.formula:
        model = ParamStore(settings.params_path).load_model()
        print(model.describe())
        print(f"\n(To curate it: python3 -m ai_investing.backtest.main --optimize --save)")
        return

    _banner()
    runner = Runner(settings, use_news=not args.no_news)
    if args.once:
        runner.run_cycle()
        runner.journal.close()
    else:
        runner.run_forever()


if __name__ == "__main__":
    main()
