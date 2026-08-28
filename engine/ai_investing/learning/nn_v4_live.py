"""Isolated NNv4 paper lane. It cannot submit or influence real orders."""
from __future__ import annotations
import json, os
from datetime import datetime, timedelta, timezone

from ai_investing.models import Decision, SignalDirection
from ai_investing.util import atomic
from ai_investing.learning.features import FeatureExtractor
from ai_investing.learning.nn_v4 import NN4FormulaModel, build_nn4_features
from ai_investing.learning.outcome_ledger import OutcomeLedger

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
        path = os.path.join(self.dir, "formula.json"); payload = atomic.read_json(path)
        if not isinstance(payload, dict) or payload.get("model_type") != "nn4":
            self.reason = "no fitted NNv4 model"; return
        try: self.model = NN4FormulaModel.from_dict(payload["model"])
        except (KeyError, TypeError, ValueError) as exc: self.reason = f"cannot load NNv4 model: {exc}"; return
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
        decisions, rows = [], []; primaries = self._primary_symbols_for(day)
        settled = 0
        for asset in active:
            try:
                feats, results = build_nn4_features(asset, bars_by_key[asset.key], self.signals, context)
                out = self.model.outputs(feats)
                # NNv4 is still being calibrated. Keep its paper lane from
                # turning an uncalibrated score into a full portfolio bet.
                target = max(-MAX_SHADOW_TARGET, min(MAX_SHADOW_TARGET, self.model.target_weight(feats)))
                direction = SignalDirection.LONG if target > 1e-4 else SignalDirection.SHORT if target < -1e-4 else SignalDirection.FLAT
                d = Decision(asset=asset, target_weight=target, direction=direction, score=self.model.score(feats), confidence=abs(self.model.conviction(feats)), signals=results, features=feats, expected_return=out["expected_return"], rationale=f"E[excess]={out['expected_return']*100:+.2f}% p={out['probability']:.2f} risk={out['risk']:.3f}")
                decisions.append(d); live = (live_decisions or {}).get(asset.symbol)
                is_primary = asset.symbol not in primaries; primaries.add(asset.symbol)
                rows.append({"ts": now.isoformat(), "day": day, "symbol": asset.symbol, "asset_key": asset.key, "asset_class": asset.asset_class.value, "is_primary": is_primary, "nn4": {"direction": direction.name, "target_weight": round(target, 5), "expected_return": round(out["expected_return"], 6), "probability": round(out["probability"], 5), "risk": round(out["risk"], 6), "score": round(self.model.score(feats), 6), "ood_multiplier": round(out.get("ood_multiplier", 1.0), 6)}, "brain": None if live is None else {"direction": live.direction.name, "target_weight": round(live.target_weight, 5), "expected_return": round(live.expected_return, 6)}, "price": prices.get(asset.key), "features": feats, "model_version": getattr(self.model, "version", None), "state": "open" if is_primary else "replica"})
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
                if mid and mid == mid: self.broker.submit(order, mid)
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
                        if row.get("day") == day and row.get("is_primary"): out.add(row.get("symbol"))
                    except json.JSONDecodeError: continue
        except OSError: pass
        return out
