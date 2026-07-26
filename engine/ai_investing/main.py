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


def _show_views() -> None:
    from ai_investing.strategy import UserViews
    v = UserViews.load(settings.user_views_path)
    print(f"stance:        {v.stance}   decisiveness: {v.decisiveness}   risk_appetite: {v.risk_appetite}")
    print(f"views:         {v.views or '(none)'}")
    print(f"blocklist:     {v.blocklist or '(none)'}")
    print(f"focus (only):  {v.focus or '(none)'}")


def _edit_views(args) -> None:
    """Set your input from the CLI (or edit the dashboard / data/views.json directly)."""
    from ai_investing.strategy import UserViews
    from ai_investing.strategy import user_views as uv_mod
    v = UserViews.load(settings.user_views_path)
    if args.stance:
        if args.stance.lower() not in uv_mod.STANCE_MULT:
            print(f"unknown stance '{args.stance}'; choose: {', '.join(uv_mod.STANCE_MULT)}")
            return
        v.stance = args.stance.lower()
    if args.decisiveness is not None:
        v.decisiveness = max(0.0, min(1.0, args.decisiveness))
    if args.risk_appetite is not None:
        v.risk_appetite = max(0.0, min(1.0, args.risk_appetite))
    for item in (args.view or []):
        sym, _, val = item.partition("=")
        try:
            v.views[sym.strip().upper()] = max(-1.0, min(1.0, float(val)))
        except ValueError:
            print(f"bad --view '{item}' (use SYM=VALUE, e.g. NVDA=0.8)")
    for sym in (args.block or []):
        if sym.upper() not in v.blocklist:
            v.blocklist.append(sym.upper())
    for sym in (args.unblock or []):
        if sym.upper() in v.blocklist:
            v.blocklist.remove(sym.upper())
    v.save(settings.user_views_path)
    print(f"Saved -> {settings.user_views_path}\n")
    _show_views()


def _compare() -> None:
    """Your portfolio (with your input) vs the formula-only portfolio."""
    import json
    try:
        with open(settings.state_path) as fh:
            c = json.load(fh).get("comparison")
    except (OSError, json.JSONDecodeError):
        c = None
    if not c:
        print("No comparison yet — run a cycle first (python3 -m ai_investing.main --once).")
        return
    you, formula, delta = c["your_equity"], c["formula_equity"], c["input_value"]
    verdict = "your input is AHEAD" if delta > 0 else ("your input is BEHIND" if delta < 0 else "even")
    print(f"You (with your input):   ${you:,.2f}")
    print(f"Formula-only (no input): ${formula:,.2f}")
    print(f"Value of your input:     ${delta:,.2f}   ({verdict})\n")
    rows = c.get("assets") or []
    if rows:
        print(f"  {'symbol':<10} {'your qty':>10} {'your P&L':>10} {'formula qty':>12} {'formula P&L':>12}")
        for a in rows:
            print(f"  {a['symbol']:<10} {a['your_qty']:>10.4f} {a['your_pnl']:>10.2f} "
                  f"{a['formula_qty']:>12.4f} {a['formula_pnl']:>12.2f}")


def _brain_status() -> None:
    from ai_investing.brain import Brain
    b = Brain(settings)
    r = b.regime.to_dict()
    print(f"Brain — {len(b.graph.nodes)} nodes, {len(b.graph.edges)} edges "
          f"({sum(1 for e in b.graph.edges if e.provenance == 'llm')} LLM-proposed)")
    labels = r.get("labels", {})
    print(f"  regime:  risk {labels.get('risk_appetite')}  rates {labels.get('rate_trajectory')}  "
          f"USD {labels.get('dollar_trend')}  inflation {labels.get('inflation_trend')}  "
          f"china {labels.get('china_stance')}")
    print(f"  tension: {r['geopolitical_tension']:.2f}   stability: {r['stability']:.2f}")
    print(f"  crowd:   {r['emotion_label']} (fear {r['fear']:.2f} / greed {r['greed']:.2f})")
    print(f"  mood:    {r['mood_label']} (confidence {r['mood_confidence']:.2f}, "
          f"caution {r['mood_caution']:.2f}) -> conviction x{b.regime.conviction_multiplier()}")
    print(f"  book:    fragility {r['fragility']:.2f} (exposure x concentration)")
    st = b.store.stats()
    print(f"  memory:  {st['articles']} articles seen ({st['digested']} digested once, never re-paid), "
          f"{st['events']} events, {st['advice_issued']} advice lists")
    from ai_investing.data.news import local_llm_available
    print(f"  llm:     local {settings.local_llm_model} "
          f"{'UP (free, preferred)' if local_llm_available(settings) else 'down'}"
          f"{' -> cloud fallback available' if settings.llm_available else ''}")
    if b.field.pending:
        print(f"  τ-queue: {len(b.field.pending)} delayed effect(s) in the pipe:")
        for p in b.field.pending[:5]:
            print(f"           {p['via']} -> {p['node']} {p['contribution']:+.2f} due {p['due'][:10]}")
    import json as _json
    try:
        with open(settings.brain.state_path) as fh:
            st = _json.load(fh)
        print(f"  last think: {st.get('ts', '?')} — {st.get('signal_events', 0)} signal / "
              f"{st.get('noise_events', 0)} noise events")
        top = list(st.get("impacts", {}).items())[:8]
        if top:
            print("  top impacts: " + "  ".join(f"{k} {v:+.2f}" for k, v in top))
        for sc in st.get("scenarios_fired", []):
            print(f"  FIRED: {sc['id']} — {sc['implication']}")
    except (OSError, _json.JSONDecodeError):
        print("  (no brain.json yet — run a cycle)")


def _brain_simulate(headline: str) -> None:
    """Prints PURE JSON — the dashboard's simulate endpoint parses this stdout."""
    import json as _json
    from ai_investing.brain import Brain
    print(_json.dumps(Brain(settings).simulate(headline)))


def _advise(notify: bool = False) -> None:
    """The 10 trades: rank the brain's current field into an explained list."""
    from datetime import datetime, timezone
    from ai_investing.brain import Brain
    from ai_investing.brain.adviser import advise
    b = Brain(settings)
    b.field.decay(datetime.now(timezone.utc))   # score today's field, not a stale one
    a = advise(settings, b, log=True)
    print(f"Adviser — {a['ts'][:16]}Z  mood: {a['mood']}  conviction x{a['conviction_multiplier']}"
          f"  ({a['regime_note']}; {a['considered']} assets considered)")
    if not a["trades"]:
        print("  No trades clear the bar right now — the field is quiet. That IS the advice.")
        return
    lines = []
    for t in a["trades"]:
        d = "LONG " if t["direction"] == "long" else "SHORT/AVOID"
        line = (f"  #{t['rank']:<2} {d} {t['symbol']:<10} [{t['market']}] "
                f"score {t['score']:+.3f}  wt≤{t['weight_suggestion']:.1%}\n"
                f"      why: {t['chain']}\n"
                f"      invalidated by: {t['invalidation']}")
        print(line)
        lines.append(f"#{t['rank']} {d} {t['symbol']} ({t['score']:+.2f}) — {t['chain']}")
    print("\n  (decision support, not orders — feed convictions into --view SYM=VAL;"
          "\n   the engine still trades through formula + risk + safety)")
    if notify:
        from ai_investing.alerts import get_notifier
        n = get_notifier(settings)
        if n.enabled:
            n.send("🧠 *Brain adviser*\n" + "\n".join(lines[:10]))
            print("  Sent to Telegram.")


def _brain_nodes() -> None:
    from ai_investing.brain import Brain
    b = Brain(settings)
    by_type: dict[str, list] = {}
    for n in b.graph.nodes.values():
        by_type.setdefault(n.type, []).append(n)
    for t in ("factor", "commodity", "actor", "theme", "sector", "asset"):
        for n in sorted(by_type.get(t, []), key=lambda x: x.id):
            extra = f"  [{n.market}] {n.symbol}" if n.symbol else ""
            eq = f"  — stable: {n.equilibrium}" if n.equilibrium else ""
            print(f"  {t:<10} {n.id:<24} {n.label}{extra}{eq}")


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
    parser.add_argument("--show-views", action="store_true", help="print your current views/stance and exit")
    parser.add_argument("--stance", help="set risk stance: aggressive|normal|cautious|defensive|cash")
    parser.add_argument("--decisiveness", type=float, help="how much your views override the model (0..1)")
    parser.add_argument("--risk-appetite", type=float, dest="risk_appetite",
                        help="your risk appetite 0..1 (scales position sizing, within safety caps)")
    parser.add_argument("--view", action="append", metavar="SYM=VAL", help="set a per-asset view, e.g. NVDA=0.8 (repeatable)")
    parser.add_argument("--block", action="append", metavar="SYM", help="never trade SYM (repeatable)")
    parser.add_argument("--unblock", action="append", metavar="SYM", help="remove SYM from the blocklist (repeatable)")
    parser.add_argument("--compare", action="store_true", help="show your portfolio vs the formula-only portfolio")
    parser.add_argument("--brain", action="store_true", help="show the brain: regime, emotions, mood, top impacts")
    parser.add_argument("--brain-simulate", metavar="HEADLINE",
                        help="run a hypothetical headline through the brain, print JSON")
    parser.add_argument("--brain-nodes", action="store_true", help="list all knowledge-graph nodes")
    parser.add_argument("--advise", action="store_true", help="the top-10 trade list from the brain's field")
    parser.add_argument("--notify", action="store_true", help="with --advise: also send the list to Telegram")
    args = parser.parse_args()

    if args.advise:
        _advise(notify=args.notify)
        return
    if args.brain:
        _brain_status()
        return
    if args.brain_simulate:
        _brain_simulate(args.brain_simulate)
        return
    if args.brain_nodes:
        _brain_nodes()
        return

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

    if (args.stance or args.decisiveness is not None or args.risk_appetite is not None
            or args.view or args.block or args.unblock):
        _edit_views(args)
        return

    if args.show_views:
        _show_views()
        return

    if args.compare:
        _compare()
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
