"""The autonomous loop: data -> signals -> formula -> risk -> execute -> journal, with
online learning, cost-adjusted fills, a regime gate, broker reconciliation, and
idempotent orders.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone

from ai_investing.alerts import get_notifier
from ai_investing.brokers import PaperBroker, get_broker
from ai_investing.config import Settings
from ai_investing.data import get_provider
from ai_investing.data import news as news_mod
from ai_investing.execution.costs import CostModel
from ai_investing.learning import OutcomeTracker, ParamStore, RLSLearner
from ai_investing.models import Asset, AssetClass, Order, OrderStatus, OrderType, Side
from ai_investing.safety import CircuitBreaker, DataGuard, validate_settings, write_heartbeat
from ai_investing.signals import default_signals
from ai_investing.storage import Journal
from ai_investing.strategy import (DecisionEngine, RegimeGate, RiskManager, UserViews,
                                   build_market_stats)


class Runner:
    def __init__(self, settings: Settings, use_news: bool = True):
        self.settings = settings
        self.use_news = use_news
        self.provider = get_provider(settings)
        self.broker = get_broker(settings)
        # paper book persistence: restore holdings/cash across engine restarts
        # (PC-off overnight must not amnesia the portfolio)
        self._paper_path = os.path.join(
            os.path.dirname(os.path.abspath(settings.state_path)), "paper_state.json")
        if not settings.live and isinstance(self.broker, PaperBroker):
            try:
                with open(self._paper_path) as fh:
                    self.broker = PaperBroker.from_state(
                        json.load(fh), allow_short=settings.risk.allow_short)
            except (OSError, json.JSONDecodeError, KeyError):
                pass
        self.journal = Journal(settings.db_path)
        self.assets = self._build_watchlist()
        self._first_cycle = True
        self._cycles = 0
        self._run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self._submitted: set[str] = set()      # idempotency: client order IDs sent this run
        self._last_positions: dict[str, float] | None = None
        self._stats: dict = {}

        # --- learning engine ---
        self.store = ParamStore(settings.params_path)
        self.model, rls = self.store.load()
        self.user_views = UserViews.load(settings.user_views_path)
        self.engine = DecisionEngine(default_signals(), model=self.model, user_views=self.user_views)
        lc = settings.learning
        self.rls = rls or RLSLearner.initialize(
            self.model.weights, prior_confidence=lc.prior_confidence,
            mu=lc.forgetting_mu, trust_region=lc.trust_region)
        self.tracker = OutcomeTracker()
        self.samples_seen = self.rls.updates

        # --- execution realism + safety ---
        c = settings.cost
        self.costs = CostModel(enabled=c.enabled, commission_bps=c.commission_bps,
                               spread_bps=c.spread_bps, slippage_coef=c.slippage_coef)
        # per-market frictions: HK stamp duty, Asia taxes, crypto taker fees —
        # every fill is charged what REAL money would lose in that market
        from ai_investing.execution.costs import MARKET_COSTS_BPS, market_cost_model
        self._market_costs = {m: market_cost_model(self.costs, m) for m in MARKET_COSTS_BPS}
        rg = settings.regime
        self.regime = RegimeGate(high_vol=rg.high_vol, ood_z=rg.ood_z, min_mult=rg.min_mult,
                                 feature_mean=self.model.feature_mean,
                                 feature_std=self.model.feature_std) if rg.enabled else None
        self.risk = RiskManager(settings.risk, regime_gate=self.regime)

        # --- alerts ---
        self.notifier = get_notifier(settings)
        if self.notifier.enabled:
            self.notifier.send(f"🟢 AI-Investing started "
                               f"({'LIVE' if settings.live else 'paper'}) — θv{self.model.version}")

        # --- safety layer ---
        errors, warnings = validate_settings(settings)
        for w in warnings:
            print(f"  [config warning] {w}")
        for e in errors:
            print(f"  [config ERROR] {e}")
        if errors and settings.live:
            raise RuntimeError("refusing to start LIVE with config errors: " + "; ".join(errors))
        self.breaker = CircuitBreaker(settings.safety, settings.risk.max_daily_drawdown, settings.breaker_path)
        self.guard = DataGuard(settings.safety)
        self._last_prices: dict[str, float] = {}

        # --- shadow "formula-only" portfolio (ignores your input) for the comparison ---
        self._shadow_path = os.path.join(
            os.path.dirname(os.path.abspath(settings.state_path)), "shadow.json")
        self.shadow_broker = self._load_shadow(settings.starting_cash)
        self.shadow_engine = DecisionEngine(default_signals(), model=self.model, user_views=UserViews())
        self.shadow_risk = RiskManager(settings.risk, regime_gate=self.regime)

    def _load_shadow(self, starting_cash: float) -> PaperBroker:
        # Persist in ALL modes: the paper track record (and its formula-only
        # A/B twin) must survive restarts — the brain REMEMBERS what it holds.
        # Fresh start = delete data/shadow.json + data/paper_state.json.
        try:
            with open(self._shadow_path) as fh:
                return PaperBroker.from_state(json.load(fh), allow_short=self.settings.risk.allow_short)
        except (OSError, json.JSONDecodeError, KeyError):
            pass
        return PaperBroker(starting_cash, allow_short=self.settings.risk.allow_short)

    def _costs_for(self, asset) -> CostModel:
        from ai_investing.execution.costs import market_of_symbol
        mkt = market_of_symbol(asset.symbol, asset.asset_class.value)
        return self._market_costs.get(mkt, self.costs)

    def _build_watchlist(self) -> list[Asset]:
        stocks = [Asset(s, AssetClass.STOCK) for s in self.settings.stock_watchlist]
        crypto = [Asset(s, AssetClass.CRYPTO, exchange=self.settings.crypto_exchange)
                  for s in self.settings.crypto_watchlist]
        return stocks + crypto

    # -- one full evaluation/execution/learning pass ------------------------
    def run_cycle(self) -> dict:
        self._cycles += 1
        self.user_views = UserViews.load(self.settings.user_views_path)   # live edits take effect
        self.engine.user_views = self.user_views
        bars_by_key = {a.key: self.provider.get_bars(a, limit=250) for a in self.assets}
        prices = {k: (b[-1].close if b else 0.0) for k, b in bars_by_key.items()}
        self._stats = build_market_stats(bars_by_key, lookback=20)
        self._last_prices = prices

        # Data sanity guard: drop symbols with bad/stale/absurd prices this cycle.
        bad_data, data_msgs = self.guard.check(prices, bars_by_key)
        if bad_data:
            detail = "; ".join(data_msgs)
            self.journal.record_event("data_anomaly", detail)
            print(f"!! DATA GUARD flagged: {detail}")
            if self.settings.alerts.on_error:
                self.notifier.send(f"⚠️ *DATA GUARD*: {detail}")

        portfolio = self.broker.portfolio()
        equity = portfolio.equity(prices)
        mode = "LIVE" if self.settings.live else "PAPER"
        print(f"\n=== cycle {datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S}Z  [{mode}]  "
              f"equity ${equity:,.0f}  cash ${portfolio.cash:,.0f}  "
              f"θv{self.model.version} (learned from {self.samples_seen} trades) ===")

        # 0) Reconcile the engine's world with the broker's before doing anything.
        if not self._reconcile(portfolio):
            self._snapshot(prices, [], {}, halted=True)
            return {"halted": True, "reason": "reconcile_drift", "equity": equity}

        if self._first_cycle:
            self.risk.mark_day_start(equity)
            self._first_cycle = False

        context: dict = {}
        if self.use_news:
            # yesterday->today price moves pulse the web once a day (assets are
            # nodes too: the market's own action is part of the world model)
            price_moves: dict = {}
            try:
                from ai_investing.brain.scorecard import Scorecard
                _sc = Scorecard(self.settings)
                price_moves = _sc.day_moves({a.symbol: prices.get(a.key, 0.0)
                                             for a in self.assets})
                _sc.close()
            except Exception:
                pass
            try:
                context = news_mod.build_market_context(self.settings, self.assets,
                                                        price_moves)
            except Exception as exc:
                self.journal.record_event("news_error", str(exc))
                if self.settings.alerts.on_error:
                    self.notifier.send(f"⚠️ news/context error: {exc}")
        if context.get("briefing"):
            print(f"[briefing] {context['briefing']}")

        # Once a day (SGT): plain-language overview — strongest ripples, the
        # standing 6-month strategy (challenged, not rewritten), then the ideas.
        if context.get("brain"):
            px_by_sym = {a.symbol: prices.get(a.key, 0.0) for a in self.assets}
            # scorecard: snapshot prices, judge every call ≥5 days old, learn
            track = learn_notes = None
            try:
                from ai_investing.brain.scorecard import Scorecard
                sc = Scorecard(self.settings)
                vol_by_sym = {a.symbol: (bars_by_key[a.key][-1].volume
                                         if bars_by_key.get(a.key) else 0.0)
                              for a in self.assets}
                sc.snapshot_prices(px_by_sym, vol_by_sym)
                outcomes = sc.score_due()
                learn_notes = sc.update_reliability(outcomes)
                track = sc.track_record()
                sc.close()
                if outcomes:
                    print(f"  [scorecard] judged {len(outcomes)} past calls; "
                          f"30d hit-rate {track.get('hit_rate')}")
            except Exception as exc:
                print(f"  [scorecard] skipped: {type(exc).__name__}: {exc}")
            try:
                from ai_investing.brain.strategist import maybe_daily_overview
                maybe_daily_overview(self.settings, context["brain"],
                                     context.get("briefing", ""), self.notifier,
                                     track=track, learn_notes=learn_notes)
            except Exception as exc:
                print(f"  [strategist] skipped: {type(exc).__name__}: {exc}")
            # the 🏛 investing book: express the 6-month theses (daily, gated inside)
            try:
                from ai_investing.brain.strategist import load_strategy, _labels
                from ai_investing.strategy.investor import Investor
                Investor(self.settings).daily_manage(
                    px_by_sym, load_strategy(self.settings), self.notifier,
                    _labels(self.settings))
            except Exception as exc:
                print(f"  [investor] skipped: {type(exc).__name__}: {exc}")

        # Shadow "formula-only" portfolio — what the model would do ignoring your input.
        self._run_shadow(prices, context, bars_by_key, bad_data)

        executed: list[Order] = []

        # 1) Circuit breaker: daily / trailing / inception drawdown + per-day caps.
        breaker = self.breaker.check(equity)
        if breaker.flatten:
            print(f"!! CIRCUIT BREAKER — {breaker.reason}. Flattening and halting.")
            self.journal.record_event("circuit_breaker", breaker.reason)
            if self.settings.alerts.on_kill:
                self.notifier.send(f"🛑 *CIRCUIT BREAKER* — {breaker.reason}. "
                                   f"Flattened & halted. equity ${equity:,.0f}")
            executed += self._flatten(prices)
            self._finish(prices, [], context, halted=True)
            return {"halted": True, "reason": breaker.reason, "equity": equity}

        # name risk: refresh per-symbol integrity/distress charges BEFORE stops
        # so a flagged holding gets its tightened leash this very cycle
        try:
            from ai_investing.brain.integrity import current_flags
            self.risk.set_name_risk(current_flags(self.settings))
        except Exception:
            pass

        # 2) Protective exits always run (even at caps / bad data); never blocked by slippage.
        for o in self.risk.stop_orders(portfolio, prices, market=self._stats):
            executed.append(self._execute(o, prices, guard_slippage=False))

        # 2b) Exit any position you've blocked / de-focused (your input, applied).
        for key, pos in list(self.broker.get_positions().items()):
            if not self.user_views.is_allowed(pos.asset.symbol):
                side = Side.SELL if pos.qty > 0 else Side.BUY
                executed.append(self._execute(
                    Order(pos.asset, side, abs(pos.qty), reason="user blocked"), prices, guard_slippage=False))

        # 3) Decisions — excluding data-guard-flagged and user-blocked symbols.
        portfolio = self.broker.portfolio()
        equity = portfolio.equity(prices)
        active = [a for a in self.assets if a.key not in bad_data and self.user_views.is_allowed(a.symbol)]
        decisions = [self.engine.decide(a, bars_by_key[a.key], context) for a in active]
        features_by_key = {d.asset.key: d.features for d in decisions}
        for d in decisions:
            self.journal.record_decision(d)

        # 4) Size and open new positions — only if the breaker allows it.
        # With TRADE_APPROVAL on, entries first go to you on Telegram and only
        # execute once approved (exits above are never gated).
        if breaker.allow_new:
            entries = self.risk.size_orders(decisions, portfolio, prices, equity,
                                            market=self._stats, model=self.model)
            if self.settings.trade_approval:
                entries = self._gate_entries(entries, prices)
            for o in entries:
                executed.append(self._execute(o, prices))
        elif breaker.reason:
            print(f"  (no new positions — {breaker.reason})")

        # 4a) The ₿ crypto book: crypto traded on its OWN policy, every cycle,
        # 24/7 — hard stops and the bear exit run even when stock markets are
        # shut, because that is when crypto crashes.
        try:
            from ai_investing.strategy.crypto_book import CryptoBook
            px_by_sym = {a.symbol: prices.get(a.key, 0.0) for a in self.assets}
            bars_by_sym = {a.symbol: bars_by_key.get(a.key, []) for a in self.assets}
            b_assets = (context.get("brain") or {}).get("asset_impacts") or {}
            cb = CryptoBook(self.settings).cycle(b_assets, bars_by_sym, px_by_sym,
                                                 self.notifier)
            if cb["opened"] or cb["closed"]:
                print(f"  [crypto book] +{len(cb['opened'])} -{len(cb['closed'])} | "
                      f"equity ${cb['equity']:,.0f} | "
                      f"{'BEAR — in cash' if cb['bear'] else 'risk-on'}")
        except Exception as exc:
            print(f"  [crypto book] skipped: {type(exc).__name__}: {exc}")

        # 4b) The ⚡ event sleeve (third policy): trade TODAY's fresh news shock,
        # time-boxed, own capital. Exits never wait; entries are its own book.
        if context.get("brain") and context["brain"].get("shock_assets"):
            try:
                from ai_investing.strategy.event_sleeve import EventSleeve
                px_by_sym = {a.symbol: prices.get(a.key, 0.0) for a in self.assets}
                from ai_investing.learning.spine import regime_of
                ra = ((context.get("brain") or {}).get("regime") or {}).get("risk_appetite")
                ev_res = EventSleeve(self.settings).cycle(
                    context["brain"]["shock_assets"], px_by_sym, self.notifier,
                    regime=regime_of(ra))
                if ev_res["opened"] or ev_res["closed"]:
                    print(f"  [event sleeve] +{len(ev_res['opened'])} "
                          f"-{len(ev_res['closed'])} | equity ${ev_res['equity']:,.0f}")
            except Exception as exc:
                print(f"  [event sleeve] skipped: {type(exc).__name__}: {exc}")

        # 5) Learn from trades that just closed.
        self._learn(prices, features_by_key)

        # 6) Record + report.
        self._finish(prices, decisions, context, halted=False)
        self._print_positions(self.broker.portfolio(), prices)
        return {"halted": False, "equity": self.broker.portfolio().equity(prices), "orders": len(executed)}

    def run_forever(self) -> None:
        print(f"Autonomous loop started (every {self.settings.poll_seconds}s). Ctrl-C to stop.")
        print(self.model.describe())
        try:
            while True:
                if self.run_cycle().get("halted"):
                    print("Halted. Sleeping until next session / manual check.")
                time.sleep(self.settings.poll_seconds)
        except KeyboardInterrupt:
            print("\nStopped by user.")
        finally:
            if self.settings.safety.flatten_on_exit and self.settings.live and self._last_prices:
                print("flatten_on_exit — closing positions.")
                self._flatten(self._last_prices)
            self.store.save(self.model, self.rls, journal=self.journal)
            self.journal.close()

    # -- safety: reconciliation ---------------------------------------------
    def _reconcile(self, portfolio) -> bool:
        """Compare current broker positions with what we left last cycle. Any drift
        (external trade, async/partial fill, rejected order we assumed filled) means our
        world model is wrong — halt in live mode rather than trade on bad state."""
        current = {k: p.qty for k, p in portfolio.positions.items()}
        if self._last_positions is None:
            self._last_positions = current
            return True
        drift = []
        for key in set(current) | set(self._last_positions):
            a, b = current.get(key, 0.0), self._last_positions.get(key, 0.0)
            if abs(a - b) > max(1e-6, 1e-3 * abs(b)):
                drift.append(f"{key}: expected {b:.4f} got {a:.4f}")
        if drift:
            detail = "; ".join(drift)
            self.journal.record_event("reconcile_drift", detail)
            print(f"!! RECONCILE DRIFT: {detail}")
            if self.settings.alerts.on_error:
                self.notifier.send(f"⚠️ *RECONCILE DRIFT*: {detail}")
            if self.settings.live:
                print("   Live mode — halting for manual review.")
                return False
        self._last_positions = current
        return True

    # -- learning -----------------------------------------------------------
    def _learn(self, prices: dict[str, float], features_by_key: dict[str, dict]) -> None:
        lc = self.settings.learning
        samples = self.tracker.sync(self.broker.get_positions(), features_by_key, prices)
        if not lc.enable_online:
            return
        for s in samples:
            phi = [s.features.get(n, 0.0) for n in self.model.feature_names]
            err = self.rls.update(phi, s.realized_return)
            self.samples_seen += 1
            self.journal.record_outcome(s.symbol, s.realized_return, s.features, err)
            print(f"  LEARN   {s.symbol:<10} realized {s.realized_return * 100:+.2f}%  "
                  f"pred_err {err * 100:+.2f}%  (sample #{self.samples_seen})")
        if self.samples_seen >= lc.min_samples and samples:
            self.model.weights = list(self.rls.theta)
        if samples and self._cycles % lc.save_every == 0:
            self.store.save(self.model, self.rls, journal=self.journal)

    # -- shadow "formula-only" portfolio (the comparison baseline) ----------
    def _run_shadow(self, prices, context, bars_by_key, bad_data) -> None:
        """Trade a parallel paper portfolio on pure model conviction (no user input),
        so we can measure whether YOUR input helped or hurt vs. following the formula."""
        b = self.shadow_broker
        for o in self.shadow_risk.stop_orders(b.portfolio(), prices, market=self._stats):
            self._shadow_fill(o, prices)
        port = b.portfolio()
        equity = port.equity(prices)
        active = [a for a in self.assets if a.key not in bad_data]
        decisions = [self.shadow_engine.decide(a, bars_by_key[a.key], context) for a in active]
        for o in self.shadow_risk.size_orders(decisions, port, prices, equity,
                                              market=self._stats, model=self.model):
            self._shadow_fill(o, prices)
        try:   # persist in ALL modes: the A/B must survive engine restarts
            with open(self._shadow_path, "w") as fh:
                json.dump(b.state(), fh)
        except OSError:
            pass

    def _shadow_fill(self, order: Order, prices: dict[str, float]) -> None:
        mid = prices.get(order.asset.key, 0.0)
        ms = self._stats.get(order.asset.key)
        eff = self._costs_for(order.asset).effective_price(order.side, mid, order.qty,
                                                           ms.adv if ms else None, ms.vol if ms else None)
        self.shadow_broker.submit(order, eff)

    def _comparison(self, real_portfolio, prices) -> dict:
        shadow = self.shadow_broker.portfolio()
        real_pos = {p.asset.symbol: p for p in real_portfolio.positions.values()}
        shad_pos = {p.asset.symbol: p for p in shadow.positions.values()}
        assets = []
        for s in sorted(set(real_pos) | set(shad_pos)):
            rp, sp = real_pos.get(s), shad_pos.get(s)
            ref = rp or sp
            px = prices.get(ref.asset.key, ref.avg_price)
            assets.append({
                "symbol": s,
                "your_qty": round(rp.qty, 4) if rp else 0.0,
                "your_pnl": round(rp.unrealized_pnl(px), 2) if rp else 0.0,
                "formula_qty": round(sp.qty, 4) if sp else 0.0,
                "formula_pnl": round(sp.unrealized_pnl(px), 2) if sp else 0.0,
            })
        your_eq = real_portfolio.equity(prices)
        formula_eq = shadow.equity(prices)
        return {"your_equity": round(your_eq, 2), "formula_equity": round(formula_eq, 2),
                "input_value": round(your_eq - formula_eq, 2), "assets": assets}

    # -- execution helpers --------------------------------------------------
    def _gate_entries(self, entries: list[Order], prices: dict[str, float]) -> list[Order]:
        """Human-in-the-loop: an entry executes only against a fresh approval.
        Unseen entries become proposals pushed to Telegram with tap buttons;
        pending/rejected ones wait silently until decided or expired."""
        from ai_investing.execution.approvals import ProposalBook
        book = ProposalBook(self.settings.proposals_path, self.settings.approval_ttl_hours)
        book.prune()
        allowed: list[Order] = []
        asked: list[dict] = []
        for o in entries:
            sym = o.asset.symbol
            p = book.get(sym, o.side.value)
            if p and p["status"] == "approved":
                book.consume(p["id"])          # one approval buys one entry
                allowed.append(o)
            elif p:                            # pending or rejected: wait, don't nag
                continue
            else:
                price = prices.get(o.asset.key, 0.0)
                # ATR-scaled stop/take, same math the risk layer will apply
                ms = (self._stats or {}).get(o.asset.key)
                stop_pct, take_pct = self.settings.risk.per_trade_stop_loss, self.settings.risk.take_profit
                if self.settings.risk.use_atr_stops and ms is not None and ms.atr > 0 and price > 0:
                    stop_pct = self.settings.risk.atr_stop_mult * ms.atr / price
                    take_pct = self.settings.risk.atr_take_mult * ms.atr / price
                stop_pct = min(stop_pct, self.settings.risk.max_loss_per_position)
                from ai_investing.execution.explain import explain_entry
                equity = self.broker.portfolio().equity(prices)
                extra = explain_entry(self.settings, sym, o.side.value, o.qty, price,
                                      o.reason, equity, stop_pct, take_pct)
                extra["horizon"] = "short"
                asked.append(book.propose(sym, o.side.value, o.qty, price, o.reason, extra))
        if asked:
            from ai_investing.execution.explain import graph_map_notes
            map_notes = graph_map_notes(self.settings,
                                        [(p["symbol"], p["side"]) for p in asked])
            sent = True
            for p in asked:      # one message per stock — easy to answer one by one
                verb = "Buy" if p["side"] == "buy" else "Bet against"
                text = (
                    f"⚡ *Trading book — approval needed* (pretend money)\n\n"
                    f"*{verb}: {p.get('label', p['symbol'])}* ({p['symbol']}"
                    f"{', ' + p['market'] if p.get('market') else ''}) — "
                    f"about *${p.get('notional', 0):,.0f}* ({p.get('pct', 0):.1%} of the trading pot)\n"
                    f"💡 *Why:* {p.get('why', p['reason'])}\n"
                    f"🤔 *This assumes:* {p.get('assumptions', 'the current picture holds')}\n"
                    f"🗺 *The plan:* {p.get('plan', 'hold while the reasons hold; automatic safety stop')}\n"
                    + (f"{map_notes[p['symbol']]}\n" if map_notes.get(p["symbol"]) else "")
                    + (f"{p['bubble_note']}\n" if p.get("bubble_note") else "")
                    + f"_No answer = it quietly expires in {self.settings.approval_ttl_hours:g}h. "
                    f"Selling to protect you never waits for approval._")
                buttons = [[(f"✅ yes, {verb.lower()} {p['symbol']}", f"ap:{p['id']}"),
                            ("❌ skip", f"rj:{p['id']}"),
                            ("🚫 never", f"b:{p['symbol']}")]]
                sent = self.notifier.send(text, buttons) and sent
            if not sent:
                print("  !! TRADE_APPROVAL is on but Telegram is not configured — "
                      f"{len(asked)} entries will wait unheard (set the bot up or unset TRADE_APPROVAL)")
            print(f"  (awaiting your approval: {', '.join(p['symbol'] for p in asked)})")
        waiting = [p["symbol"] for p in book.pending() if p["symbol"] not in {q["symbol"] for q in asked}]
        if waiting:
            print(f"  (still awaiting approval: {', '.join(waiting)})")
        return allowed

    def _execute(self, order: Order, prices: dict[str, float], guard_slippage: bool = True) -> Order:
        cid = f"{self._run_id}-{self._cycles}-{order.asset.key}-{order.side.value}"
        if cid in self._submitted:
            print(f"  SKIP     duplicate order {cid}")
            order.reason = "duplicate (idempotency)"
            return order

        key = order.asset.key
        mid = prices.get(key, 0.0)
        ms = self._stats.get(key)

        # Slippage guard: refuse to OPEN a position whose modeled cost is too high
        # (illiquid / oversized). Protective exits pass guard_slippage=False.
        if guard_slippage and mid > 0:
            frac = self._costs_for(order.asset).cost_fraction(order.qty, mid, ms.adv if ms else None, ms.vol if ms else None)
            if frac * 1e4 > self.settings.safety.max_slippage_bps:
                print(f"  SKIP     {order.asset.symbol} — modeled slippage {frac * 1e4:.0f}bps "
                      f"> {self.settings.safety.max_slippage_bps:.0f}bps cap")
                order.reason = "slippage cap"
                order.status = OrderStatus.REJECTED
                return order

        # Limit-order price protection on opening trades (protective exits stay market).
        if guard_slippage and mid > 0 and self.settings.execution.order_type == "limit":
            # the band is protection ON TOP of the market's normal frictions —
            # a flat band tighter than HK stamp duty would reject every HK fill
            cm = self._costs_for(order.asset)
            band = (self.settings.execution.limit_band_bps
                    + cm.commission_bps + cm.spread_bps) / 1e4
            order.order_type = OrderType.LIMIT
            order.limit_price = mid * (1 + band) if order.side is Side.BUY else mid * (1 - band)

        order.client_order_id = cid
        eff = self._costs_for(order.asset).effective_price(order.side, mid, order.qty,
                                                           ms.adv if ms else None, ms.vol if ms else None)
        filled = self.broker.submit(order, eff)
        self._submitted.add(cid)
        self.journal.record_order(filled, self.settings.live)

        slip = (eff / mid - 1) * 100 if mid else 0.0
        print(f"  {filled.status.value.upper():8} {filled.side.value:4} "
              f"{filled.filled_qty or filled.qty:>10.4f} {order.asset.symbol:<10} "
              f"@ ${eff:,.2f} ({slip:+.2f}% cost)  ({order.reason})")

        if filled.status is OrderStatus.FILLED:
            notional = (filled.filled_qty or 0.0) * (filled.filled_price or 0.0)
            self.breaker.register_trade(notional)
            if guard_slippage and self.settings.live and self.settings.execution.stop_at_exchange:
                self._place_exchange_stop(order.asset, filled, ms)
            # Live: alert if the real fill deviated far from the mark we sized against.
            if (self.settings.live and mid
                    and abs((filled.filled_price or mid) / mid - 1) * 1e4 > 2 * self.settings.safety.max_slippage_bps):
                self.journal.record_event("slippage_alert", f"{key} fill {filled.filled_price} vs mid {mid}")
                if self.settings.alerts.on_error:
                    self.notifier.send(f"⚠️ large slippage on {order.asset.symbol}: "
                                       f"fill ${filled.filled_price} vs mid ${mid:.2f}")
            if self.settings.alerts.on_trade and notional >= self.settings.alerts.min_notional:
                emoji = "🟩" if filled.side is Side.BUY else "🟥"
                self.notifier.send(f"{emoji} *{filled.side.value.upper()}* {filled.filled_qty:.4f} "
                                   f"{order.asset.symbol} @ ${eff:,.2f}  (_{order.reason}_)")
        return filled

    def _place_exchange_stop(self, asset, filled, ms) -> None:
        """Rest a protective stop AT THE VENUE after opening a long — survives a crash and
        triggers on an intraday gap between cycles. Long-only case; experimental (untested
        vs. funded accounts). Requires a broker that implements place_stop (ccxt today)."""
        if filled.side is not Side.BUY or self.settings.risk.allow_short:
            return
        entry = filled.filled_price or 0.0
        if entry <= 0:
            return
        stop_frac = self.settings.risk.per_trade_stop_loss
        if self.settings.risk.use_atr_stops and ms and ms.atr > 0:
            stop_frac = self.settings.risk.atr_stop_mult * (ms.atr / entry)
        stop_price = entry * (1 - stop_frac)
        if self.broker.place_stop(asset, Side.SELL, filled.filled_qty, stop_price):
            print(f"  STOP-SET  {asset.symbol} @ ${stop_price:,.2f} (exchange)")
        else:
            self.journal.record_event("exchange_stop_unsupported", asset.symbol)

    def _flatten(self, prices: dict[str, float]) -> list[Order]:
        out: list[Order] = []
        for key, pos in list(self.broker.get_positions().items()):
            side = Side.SELL if pos.qty > 0 else Side.BUY
            out.append(self._execute(Order(pos.asset, side, abs(pos.qty), reason="flatten"),
                                     prices, guard_slippage=False))
        return out

    def _finish(self, prices, decisions, context, halted: bool) -> None:
        portfolio = self.broker.portfolio()
        self.journal.record_equity(portfolio.equity(prices), portfolio.cash, len(portfolio.positions))
        self._last_positions = {k: p.qty for k, p in portfolio.positions.items()}
        self._snapshot(prices, decisions, context, halted)

    def _print_positions(self, portfolio, prices) -> None:
        if not portfolio.positions:
            print("  (no open positions)")
            return
        for key, pos in portfolio.positions.items():
            px = prices.get(key, pos.avg_price)
            print(f"  HELD    {pos.qty:>10.4f} {pos.asset.symbol:<10} "
                  f"@ ${pos.avg_price:,.2f} -> ${px:,.2f}  PnL ${pos.unrealized_pnl(px):,.0f}")

    def _snapshot(self, prices, decisions, context, halted: bool) -> None:
        portfolio = self.broker.portfolio()
        state = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "mode": "live" if self.settings.live else "paper",
            "halted": halted,
            "equity": portfolio.equity(prices),
            "cash": portfolio.cash,
            "briefing": context.get("briefing", ""),
            "formula": {
                "version": self.model.version,
                "trades_learned": self.samples_seen,
                "fitted": self.model.fitted,
                "weights": dict(zip(self.model.feature_names, self.model.weights)),
                "gain": self.model.gain,
                "entry_threshold": self.model.entry_threshold,
            },
            "controls": {
                "stance": self.user_views.stance,
                "decisiveness": self.user_views.decisiveness,
                "views": self.user_views.views,
                "blocklist": self.user_views.blocklist,
                "focus": self.user_views.focus,
            },
            "positions": [
                {"symbol": p.asset.symbol, "qty": p.qty, "avg_price": p.avg_price,
                 "price": prices.get(k, p.avg_price),
                 "value": p.market_value(prices.get(k, p.avg_price)),
                 "pnl": p.unrealized_pnl(prices.get(k, p.avg_price))}
                for k, p in portfolio.positions.items()
            ],
            "decisions": [
                {"symbol": d.asset.symbol, "direction": d.direction.value,
                 "score": round(d.score, 3), "confidence": round(d.confidence, 3),
                 "expected_return": round(d.expected_return, 5),
                 "user_view": round(d.user_view, 3), "rationale": d.rationale}
                for d in decisions
            ],
        }
        state["comparison"] = self._comparison(portfolio, prices)
        data_dir = os.path.dirname(os.path.abspath(self.settings.state_path))
        try:
            os.makedirs(data_dir, exist_ok=True)
            with open(self.settings.state_path, "w") as fh:
                json.dump(state, fh, indent=2)
            # the brain REMEMBERS its holdings: persist the paper book every cycle
            if not self.settings.live and isinstance(self.broker, PaperBroker):
                with open(self._paper_path, "w") as fh:
                    json.dump(self.broker.state(), fh)
            self._append_history(data_dir, state)
            write_heartbeat(self.settings.heartbeat_path,
                            {"equity": state["equity"], "cash": state["cash"],
                             "halted": halted, "cycle": self._cycles, "mode": state["mode"]})
        except OSError:
            pass

    def _append_history(self, data_dir: str, state: dict) -> None:
        path = os.path.join(data_dir, "history.json")
        points = []
        if os.path.exists(path):
            try:
                with open(path) as fh:
                    points = json.load(fh).get("points", [])
            except (OSError, json.JSONDecodeError):
                points = []
        points.append({
            "ts": state["ts"], "equity": round(state["equity"], 2), "cash": round(state["cash"], 2),
            "version": self.model.version, "trades_learned": self.samples_seen,
            "shadow_equity": round(state.get("comparison", {}).get("formula_equity", state["equity"]), 2),
        })
        with open(path, "w") as fh:
            json.dump({"updated": state["ts"], "points": points[-500:]}, fh)
