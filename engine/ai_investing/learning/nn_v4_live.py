"""Isolated NNv4 paper lane. It cannot submit or influence real orders."""
from __future__ import annotations
import json, os
from datetime import datetime, timedelta, timezone

from ai_investing.models import Decision, SignalDirection
from ai_investing.util import atomic
from ai_investing.learning.features import FeatureExtractor
from ai_investing.learning.nn_v4 import NN4FormulaModel, build_nn4_features
from ai_investing.learning.outcome_ledger import OutcomeLedger
from ai_investing.learning.outcome_ledger import artifact_model_id

DIR, JOURNAL, BOOK = "nn_v4", "nn_decisions.jsonl", "nn_book.json"
MAX_SHADOW_TARGET = 0.25


class NN4LiveBook:
    def __init__(self, settings, starting_cash=None):
        self.settings = settings; self.dir = os.path.join(os.path.dirname(os.path.abspath(settings.state_path)), DIR)
        self.model = self.engine = self.broker = self.risk = None; self.reason = ""
        os.makedirs(self.dir, exist_ok=True); self._load(starting_cash or settings.starting_cash)
        self.outcomes = OutcomeLedger(self.dir, DIR, 5)

    def _load(self, starting_cash):
        from ai_investing.brokers.paper import PaperBroker
        from ai_investing.signals import default_signals
        from ai_investing.strategy.risk import RiskManager
        self.model = self.engine = self.broker = self.risk = None
        path = os.path.join(self.dir, "formula.json"); payload = atomic.read_json(path)
        if os.getenv("NN4_ALLOW_CURRENT", "0").lower() not in {"1", "true", "yes"}:
            self.reason = "current NNv4 artifact quarantined; set NN4_ALLOW_CURRENT=1 only for a repaired artifact"
            return
        if not isinstance(payload, dict) or payload.get("model_type") != "nn4":
            self.reason = "no fitted NNv4 model"; return
        try: self.model = NN4FormulaModel.from_dict(payload["model"])
        except (KeyError, TypeError, ValueError) as exc: self.reason = f"cannot load NNv4 model: {exc}"; return
        self.model_id = artifact_model_id(path, "nn4")
        state = atomic.read_json(os.path.join(self.dir, BOOK))
        try: self.broker = PaperBroker.from_state(state, allow_short=self.settings.risk.allow_short) if isinstance(state, dict) else None
        except (KeyError, TypeError, ValueError): self.broker = None
        self.broker = self.broker or PaperBroker(starting_cash, allow_short=self.settings.risk.allow_short)
        self.signals = default_signals(); self.features = FeatureExtractor(); self.risk = RiskManager(self.settings.risk)
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
        except Exception as exc: print(f"  [nn4-live] refresh skipped: {type(exc).__name__}: {exc}")
        if not self.available: return {"available": False, "reason": self.reason}
        now = now or datetime.now(timezone.utc); day = (now + timedelta(hours=8)).strftime("%Y-%m-%d")
        active = [a for a in assets if a.key not in (bad_data or set()) and a.key in bars_by_key]
        # Compute the same cross-sectional benchmark used by training before
        # creating live features. This keeps relative_strength a real relative
        # feature and makes volatility use the training horizon's units.
        raw_20d = []
        for asset in active:
            try:
                raw_20d.append(build_nn4_features(asset, bars_by_key[asset.key],
                                                   self.signals, context,
                                                   benchmark_return=0.0)[0].get("return_20d", 0.0))
            except Exception:
                continue
        benchmark20 = (sorted(raw_20d)[len(raw_20d) // 2] if raw_20d else 0.0)
        decisions, rows = [], []; primaries = self._primary_symbols_for(day)
        settled = 0
        for asset in active:
            try:
                feats, results = build_nn4_features(asset, bars_by_key[asset.key], self.signals, context,
                                                    benchmark_return=benchmark20, horizon=5)
                out = self.model.outputs(feats)
                # NNv4 is still being calibrated. Keep its paper lane from
                # turning an uncalibrated score into a full portfolio bet.
                target = max(-MAX_SHADOW_TARGET, min(MAX_SHADOW_TARGET, self.model.target_weight(feats)))
                direction = SignalDirection.LONG if target > 1e-4 else SignalDirection.SHORT if target < -1e-4 else SignalDirection.FLAT
                d = Decision(asset=asset, target_weight=target, direction=direction, score=self.model.score(feats), confidence=abs(self.model.conviction(feats)), signals=results, features=feats, expected_return=out["expected_return"], rationale=f"E[excess]={out['expected_return']*100:+.2f}% p={out['probability']:.2f} risk={out['risk']:.3f}")
                decisions.append(d); live = (live_decisions or {}).get(asset.symbol)
                is_primary = asset.symbol not in primaries; primaries.add(asset.symbol)
                rows.append({"ts": now.isoformat(), "day": day, "symbol": asset.symbol, "asset_key": asset.key, "asset_class": asset.asset_class.value, "is_primary": is_primary, "model_id": self.model_id, "prediction_id": f"{self.model_id}:{asset.key}:{day}", "prediction": {"direction": direction.name, "target_weight": round(target, 5), "expected_return": round(out["expected_return"], 6), "probability": round(out["probability"], 5), "risk": round(out["risk"], 6), "score": round(self.model.score(feats), 6), "ood_multiplier": round(out.get("ood_multiplier", 1.0), 6)}, "decision_ts": now.isoformat(), "feature_cutoff_ts": now.isoformat(), "nn4": {"direction": direction.name, "target_weight": round(target, 5), "expected_return": round(out["expected_return"], 6), "probability": round(out["probability"], 5), "risk": round(out["risk"], 6), "score": round(self.model.score(feats), 6), "ood_multiplier": round(out.get("ood_multiplier", 1.0), 6)}, "brain": None if live is None else {"direction": live.direction.name, "target_weight": round(live.target_weight, 5), "expected_return": round(live.expected_return, 6)}, "price": prices.get(asset.key), "features": feats, "model_version": getattr(self.model, "version", None), "state": "open" if is_primary else "replica"})
                rows[-1]["schema_version"] = 2
                rows[-1]["scheduled_exit_ts"] = (now + timedelta(days=5)).isoformat()
            except Exception as exc: print(f"  [nn4-live] {asset.symbol}: {type(exc).__name__}: {exc}")
        try:
            with open(os.path.join(self.dir, JOURNAL), "a") as fh:
                for row in rows: fh.write(json.dumps(row) + "\n")
            settled = self.outcomes.settle(os.path.join(self.dir, JOURNAL), prices, assets, now)
            from ai_investing.strategy.market import build_market_stats
            market = build_market_stats({a.key: bars_by_key[a.key] for a in active}, lookback=20)
            port = self.broker.portfolio(); equity = port.equity(prices)
            for order in self.risk.size_orders(decisions, port, prices, equity, market=market, model=self.model):
                mid = prices.get(order.asset.key)
                if mid and mid == mid:
                    from ai_investing.execution.costs import CostModel, market_cost_model, market_of_symbol
                    stats = market.get(order.asset.key)
                    costs = market_cost_model(CostModel(), market_of_symbol(
                        order.asset.symbol, order.asset.asset_class.value))
                    effective = costs.effective_price(order.side, mid, order.qty,
                                                      stats.adv if stats else None,
                                                      stats.vol if stats else None)
                    self.broker.submit(order, effective)
            atomic.write_json(os.path.join(self.dir, BOOK), self.broker.state())
        except Exception as exc: print(f"  [nn4-live] book skipped: {type(exc).__name__}: {exc}")
        return {"available": True, "decided": len(decisions), "primaries": sum(1 for r in rows if r["is_primary"]), "settled": settled, "equity": round(self.broker.portfolio().equity(prices), 2)}

    def _primary_symbols_for(self, day):
        out = set(); path = os.path.join(self.dir, JOURNAL)
        try:
            with open(path, errors="replace") as fh:
                for line in fh:
                    if f'"day": "{day}"' not in line: continue
                    try:
                        row = json.loads(line)
                        if row.get("day") == day and row.get("is_primary") and int(row.get("schema_version", 0)) >= 2: out.add(row.get("symbol"))
                    except json.JSONDecodeError: continue
        except OSError: pass
        return out
