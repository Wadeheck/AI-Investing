"""The autonomous loop: data -> signals -> formula -> risk -> execute -> journal,
plus the online learning step that matures θ from realized P&L each cycle.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone

from ai_investing.brokers import get_broker
from ai_investing.config import Settings
from ai_investing.data import get_provider
from ai_investing.data import news as news_mod
from ai_investing.learning import OutcomeTracker, ParamStore, RLSLearner
from ai_investing.models import Asset, AssetClass, Order, Side
from ai_investing.signals import default_signals
from ai_investing.storage import Journal
from ai_investing.strategy import DecisionEngine, RiskManager


class Runner:
    def __init__(self, settings: Settings, use_news: bool = True):
        self.settings = settings
        self.use_news = use_news
        self.provider = get_provider(settings)
        self.risk = RiskManager(settings.risk)
        self.broker = get_broker(settings)
        self.journal = Journal(settings.db_path)
        self.assets = self._build_watchlist()
        self._first_cycle = True
        self._cycles = 0

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

        context: dict = {}
        if self.use_news:
            try:
                context = news_mod.build_market_context(self.settings, [a.symbol for a in self.assets])
            except Exception as exc:
                self.journal.record_event("news_error", str(exc))

        portfolio = self.broker.portfolio()
        equity = portfolio.equity(prices)
        if self._first_cycle:
            self.risk.mark_day_start(equity)
            self._first_cycle = False

        mode = "LIVE" if self.settings.live else "PAPER"
        print(f"\n=== cycle {datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S}Z  [{mode}]  "
              f"equity ${equity:,.0f}  cash ${portfolio.cash:,.0f}  "
              f"θv{self.model.version} (learned from {self.samples_seen} trades) ===")
        if context.get("briefing"):
            print(f"[briefing] {context['briefing']}")

        executed: list[Order] = []

        # 1) Kill switch.
        if self.risk.kill_switch_triggered(equity):
            print("!! KILL SWITCH: daily drawdown limit hit — flattening and halting.")
            self.journal.record_event("kill_switch", f"equity={equity:.2f}")
            executed += self._flatten(prices)
            self._snapshot(prices, [], context, halted=True)
            return {"halted": True, "equity": equity}

        # 2) Protective exits.
        for o in self.risk.stop_orders(portfolio, prices):
            executed.append(self._execute(o, prices))

        # 3) Decisions via the formula.
        portfolio = self.broker.portfolio()
        equity = portfolio.equity(prices)
        decisions = [self.engine.decide(a, bars_by_key[a.key], context) for a in self.assets]
        features_by_key = {d.asset.key: d.features for d in decisions}
        for d in decisions:
            self.journal.record_decision(d)

        # 4) Size and execute.
        for o in self.risk.size_orders(decisions, portfolio, prices, equity):
            executed.append(self._execute(o, prices))

        # 5) Learn from any trades that just closed.
        self._learn(prices, features_by_key)

        # 6) Record + report.
        portfolio = self.broker.portfolio()
        equity = portfolio.equity(prices)
        self.journal.record_equity(equity, portfolio.cash, len(portfolio.positions))
        self._snapshot(prices, decisions, context, halted=False)
        self._print_positions(portfolio, prices)
        return {"halted": False, "equity": equity, "orders": len(executed)}

    def run_forever(self) -> None:
        print(f"Autonomous loop started (every {self.settings.poll_seconds}s). Ctrl-C to stop.")
        print(self.model.describe())
        try:
            while True:
                if self.run_cycle().get("halted"):
                    print("Halted for the day. Sleeping until next session.")
                time.sleep(self.settings.poll_seconds)
        except KeyboardInterrupt:
            print("\nStopped by user.")
        finally:
            self.store.save(self.model, self.rls, journal=self.journal)
            self.journal.close()

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
        # Apply matured weights once we have enough evidence.
        if self.samples_seen >= lc.min_samples and samples:
            self.model.weights = list(self.rls.theta)
        if samples and self._cycles % lc.save_every == 0:
            self.store.save(self.model, self.rls, journal=self.journal)

    # -- execution helpers --------------------------------------------------
    def _execute(self, order: Order, prices: dict[str, float]) -> Order:
        px = prices.get(order.asset.key, 0.0)
        filled = self.broker.submit(order, px)
        self.journal.record_order(filled, self.settings.live)
        print(f"  {filled.status.value.upper():8} {filled.side.value:4} "
              f"{filled.filled_qty or filled.qty:>10.4f} {order.asset.symbol:<10} @ ${px:,.2f}  ({order.reason})")
        return filled

    def _flatten(self, prices: dict[str, float]) -> list[Order]:
        out: list[Order] = []
        for key, pos in list(self.broker.get_positions().items()):
            side = Side.SELL if pos.qty > 0 else Side.BUY
            out.append(self._execute(Order(pos.asset, side, abs(pos.qty), reason="flatten"), prices))
        return out

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
        import os
        data_dir = os.path.dirname(os.path.abspath(self.settings.state_path))
        try:
            os.makedirs(data_dir, exist_ok=True)
            with open(self.settings.state_path, "w") as fh:
                json.dump(state, fh, indent=2)
            self._append_history(data_dir, state)
        except OSError:
            pass

    def _append_history(self, data_dir: str, state: dict) -> None:
        """Append this cycle's equity/θ point to history.json (capped) for the chart."""
        path = os.path.join(data_dir, "history.json")
        points = []
        if os.path.exists(path):
            try:
                with open(path) as fh:
                    points = json.load(fh).get("points", [])
            except (OSError, json.JSONDecodeError):
                points = []
        points.append({
            "ts": state["ts"],
            "equity": round(state["equity"], 2),
            "cash": round(state["cash"], 2),
            "version": self.model.version,
            "trades_learned": self.samples_seen,
        })
        with open(path, "w") as fh:
            json.dump({"updated": state["ts"], "points": points[-500:]}, fh)
