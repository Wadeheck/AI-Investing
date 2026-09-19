"""Isolated NNv5 residual paper lane; it cannot place live orders."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

from ai_investing.brokers.paper import PaperBroker
from ai_investing.execution.costs import CostModel, market_cost_model, market_of_symbol
from ai_investing.learning.nn_v5 import NN5ResidualModel
from ai_investing.learning.outcome_ledger import OutcomeLedger
from ai_investing.models import SignalDirection
from ai_investing.strategy.decision import DecisionEngine
from ai_investing.strategy.market import build_market_stats
from ai_investing.strategy.risk import RiskManager
from ai_investing.signals import default_signals
from ai_investing.util import atomic

DIR, DECISIONS, BOOK, HORIZON = "nn_v5", "nn_decisions.jsonl", "nn_book.json", 5


def _day(now): return (now + timedelta(hours=8)).strftime("%Y-%m-%d")


class NN5LiveBook:
    def __init__(self, settings, starting_cash=None):
        self.settings = settings
        self.dir = os.path.join(os.path.dirname(os.path.abspath(settings.state_path)), DIR)
        os.makedirs(self.dir, exist_ok=True)
        self.model = self.engine = self.broker = self.risk = None
        self.reason = ""
        self._load(starting_cash or settings.starting_cash)
        self.outcomes = OutcomeLedger(self.dir, DIR, HORIZON)

    def _load(self, starting_cash):
        path = os.path.join(self.dir, "formula.json"); payload = atomic.read_json(path)
        if not isinstance(payload, dict) or payload.get("model_type") != "nn5":
            self.reason = "no fitted NNv5 residual artifact"; return
        try: self.model = NN5ResidualModel.from_dict(payload["model"])
        except (KeyError, TypeError, ValueError) as exc:
            self.reason = f"cannot load NNv5 model: {exc}"; return
        state = atomic.read_json(os.path.join(self.dir, BOOK))
        try: self.broker = PaperBroker.from_state(state, allow_short=self.settings.risk.allow_short) if isinstance(state, dict) else None
        except (KeyError, TypeError, ValueError): self.broker = None
        self.broker = self.broker or PaperBroker(starting_cash, allow_short=self.settings.risk.allow_short)
        self.engine = DecisionEngine(default_signals(), model=self.model)
        self.risk = RiskManager(self.settings.risk)
        self._mtime = os.path.getmtime(path)

    @property
    def available(self): return self.model is not None and self.broker is not None

    def refresh(self):
        path = os.path.join(self.dir, "formula.json")
        try: mtime = os.path.getmtime(path)
        except OSError: return False
        if mtime == getattr(self, "_mtime", None): return False
        old = self.model; self._load(self.settings.starting_cash); self._mtime = mtime
        return self.model is not None and self.model is not old

    def run_cycle(self, prices, context, bars_by_key, assets, bad_data=None, live_decisions=None, now=None):
        try: self.refresh()
        except Exception as exc: print(f"  [nn5-live] refresh skipped: {type(exc).__name__}: {exc}")
        if not self.available: return {"available": False, "reason": self.reason}
        now = now or datetime.now(timezone.utc); day = _day(now); bad = bad_data or set()
        active = [a for a in assets if a.key not in bad and a.key in bars_by_key]
        market = build_market_stats({a.key: bars_by_key[a.key] for a in active}, lookback=20)
        seen = self._primary_symbols_for(day); rows = []; decisions = []
        for asset in active:
            try:
                d = self.engine.decide(asset, bars_by_key[asset.key], context); decisions.append(d)
                primary = asset.symbol not in seen; seen.add(asset.symbol)
                live = (live_decisions or {}).get(asset.symbol)
                rows.append({"ts": now.isoformat(), "day": day, "symbol": asset.symbol,
                    "asset_key": asset.key, "asset_class": asset.asset_class.value,
                    "is_primary": primary, "nn5": {"direction": d.direction.name,
                    "target_weight": float(d.target_weight), "expected_return": float(d.expected_return),
                    "confidence": float(d.confidence), "residual": self.model.residual(d.features)},
                    "brain": None if live is None else {"direction": live.direction.name,
                    "target_weight": float(live.target_weight), "expected_return": float(live.expected_return)},
                    "price": prices.get(asset.key), "features": d.features,
                    "model_version": self.model.version, "state": "open" if primary else "replica"})
            except Exception as exc: print(f"  [nn5-live] {asset.symbol}: {type(exc).__name__}: {exc}")
        self._append(rows); settled = self.outcomes.settle(os.path.join(self.dir, DECISIONS), prices, assets, now)
        try:
            port = self.broker.portfolio(); equity = port.equity(prices)
            for order in self.risk.size_orders(decisions, port, prices, equity, market=market, model=self.model):
                mid = prices.get(order.asset.key)
                if not mid or mid != mid: continue
                stats = market.get(order.asset.key)
                costs = market_cost_model(CostModel(), market_of_symbol(order.asset.symbol, order.asset.asset_class.value))
                self.broker.submit(order, costs.effective_price(order.side, mid, order.qty,
                                                                  stats.adv if stats else None, stats.vol if stats else None))
            atomic.write_json(os.path.join(self.dir, BOOK), self.broker.state())
        except Exception as exc: print(f"  [nn5-live] book skipped: {type(exc).__name__}: {exc}")
        return {"available": True, "decided": len(decisions), "primaries": sum(r["is_primary"] for r in rows),
                "settled": settled, "equity": round(self.broker.portfolio().equity(prices), 2)}

    def _append(self, rows):
        if rows:
            with open(os.path.join(self.dir, DECISIONS), "a") as fh:
                for row in rows: fh.write(json.dumps(row) + "\n")

    def _primary_symbols_for(self, day):
        out = set(); path = os.path.join(self.dir, DECISIONS)
        try:
            for line in open(path, errors="replace"):
                if f'"day": "{day}"' not in line: continue
                row = json.loads(line)
                if row.get("day") == day and row.get("is_primary"): out.add(row.get("symbol"))
        except (OSError, json.JSONDecodeError): pass
        return out
