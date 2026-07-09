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
from ai_investing.brokers import get_broker
from ai_investing.config import Settings
from ai_investing.data import get_provider
from ai_investing.data import news as news_mod
from ai_investing.execution.costs import CostModel
from ai_investing.learning import OutcomeTracker, ParamStore, RLSLearner
from ai_investing.models import Asset, AssetClass, Order, OrderStatus, Side
from ai_investing.safety import CircuitBreaker, DataGuard, validate_settings, write_heartbeat
from ai_investing.signals import default_signals
from ai_investing.storage import Journal
from ai_investing.strategy import DecisionEngine, RegimeGate, RiskManager, build_market_stats


class Runner:
    def __init__(self, settings: Settings, use_news: bool = True):
        self.settings = settings
        self.use_news = use_news
        self.provider = get_provider(settings)
        self.broker = get_broker(settings)
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
        self.engine = DecisionEngine(default_signals(), model=self.model)
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

    def _build_watchlist(self) -> list[Asset]:
        stocks = [Asset(s, AssetClass.STOCK) for s in self.settings.stock_watchlist]
        crypto = [Asset(s, AssetClass.CRYPTO, exchange=self.settings.crypto_exchange)
                  for s in self.settings.crypto_watchlist]
        return stocks + crypto

    # -- one full evaluation/execution/learning pass ------------------------
    def run_cycle(self) -> dict:
        self._cycles += 1
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
            try:
                context = news_mod.build_market_context(self.settings, self.assets)
            except Exception as exc:
                self.journal.record_event("news_error", str(exc))
                if self.settings.alerts.on_error:
                    self.notifier.send(f"⚠️ news/context error: {exc}")
        if context.get("briefing"):
            print(f"[briefing] {context['briefing']}")

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

        # 2) Protective exits always run (even at caps / bad data); never blocked by slippage.
        for o in self.risk.stop_orders(portfolio, prices, market=self._stats):
            executed.append(self._execute(o, prices, guard_slippage=False))

        # 3) Decisions — excluding symbols the data guard flagged.
        portfolio = self.broker.portfolio()
        equity = portfolio.equity(prices)
        active = [a for a in self.assets if a.key not in bad_data]
        decisions = [self.engine.decide(a, bars_by_key[a.key], context) for a in active]
        features_by_key = {d.asset.key: d.features for d in decisions}
        for d in decisions:
            self.journal.record_decision(d)

        # 4) Size and open new positions — only if the breaker allows it.
        if breaker.allow_new:
            for o in self.risk.size_orders(decisions, portfolio, prices, equity,
                                           market=self._stats, model=self.model):
                executed.append(self._execute(o, prices))
        elif breaker.reason:
            print(f"  (no new positions — {breaker.reason})")

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

    # -- execution helpers --------------------------------------------------
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
            frac = self.costs.cost_fraction(order.qty, mid, ms.adv if ms else None, ms.vol if ms else None)
            if frac * 1e4 > self.settings.safety.max_slippage_bps:
                print(f"  SKIP     {order.asset.symbol} — modeled slippage {frac * 1e4:.0f}bps "
                      f"> {self.settings.safety.max_slippage_bps:.0f}bps cap")
                order.reason = "slippage cap"
                order.status = OrderStatus.REJECTED
                return order

        order.client_order_id = cid
        eff = self.costs.effective_price(order.side, mid, order.qty,
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
                 "expected_return": round(d.expected_return, 5), "rationale": d.rationale}
                for d in decisions
            ],
        }
        data_dir = os.path.dirname(os.path.abspath(self.settings.state_path))
        try:
            os.makedirs(data_dir, exist_ok=True)
            with open(self.settings.state_path, "w") as fh:
                json.dump(state, fh, indent=2)
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
        })
        with open(path, "w") as fh:
            json.dump({"updated": state["ts"], "points": points[-500:]}, fh)
