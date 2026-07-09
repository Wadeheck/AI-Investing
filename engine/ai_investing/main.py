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


def main() -> None:
    parser = argparse.ArgumentParser(description="Autonomous AI investing engine (paper-first).")
    parser.add_argument("--once", action="store_true", help="run a single cycle and exit")
    parser.add_argument("--briefing", action="store_true", help="print the global briefing and exit")
    parser.add_argument("--no-news", action="store_true", help="skip news/LLM; price signals only")
    parser.add_argument("--formula", action="store_true", help="print the current decision formula and exit")
    parser.add_argument("--check-broker", action="store_true",
                        help="read-only: validate live broker credentials/connectivity, no trading")
    args = parser.parse_args()

    if args.briefing:
        print(news_mod.global_briefing(settings))
        return

    if args.check_broker:
        _check_broker()
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
