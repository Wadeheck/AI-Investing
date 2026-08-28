"""The NN-v3's own trading book — a live decision-maker, isolated from the brain.

WHAT THIS IS. `nn_v3.py` fits a net; `backtest/main.py --optimize` decides
whether it may ever be adopted. Neither of those makes a DECISION on live data,
and neither leaves a record you can hold beside the brain's. This does: every
cycle the net sees exactly the context the live engine sees — the same signals,
the same news, the same brain field, the same curated wiring — forms its own
view on every asset, trades a paper book on it, and journals what it chose and
why. Later the same journal is graded, so the net learns from what it caught AND
from what it stood aside for.

WHAT IT IS NOT, and this is the whole design constraint. It cannot influence
what the live system trades. Its isolation is structural, not conventional:

  1. Its own `PaperBroker`. It never sees the real broker or the live books.
  2. Its own state, under `data/nn_v3/` only. It never writes
     `data/formula.json`, `data/state.json`, or any book file.
  3. Its own model object. It never touches `runner.model` or `runner.rls`, so
     the linear formula the engine actually trades cannot be perturbed by
     anything here.
  4. `UserViews()` empty by construction — the net is judged on its own read,
     not on the operator's tilts.
  5. The runner calls it inside a hard `try/except`. A failure here prints and
     the cycle continues. Note `_run_shadow` (the formula-only twin) is NOT
     guarded that way; this one is, because a second shadow lane must never be
     able to cost a live cycle.

THE COUNTING UNIT IS (symbol, day), NOT THE ROW. The engine cycles every ~8
minutes, so journalling one row per decision per cycle would re-log a standing
view ~65 times a day against the same forward return — precisely the defect
BRAIN_REVIEW_2026-08-21 found inflating the whole evidence base 65x (§4.37).
Every row is written and auditable; exactly one per (symbol, SGT day) carries
`is_primary`, and only those are graded or compared. Anything that counts rows
here is wrong, and a test pins it.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from ai_investing.learning.features import FeatureExtractor  # noqa: F401  (contract)
from ai_investing.models import SignalDirection, Order, OrderStatus, Side
from ai_investing.util import atomic

SHADOW_DIR = "nn_v3"
DECISIONS = "nn_decisions.jsonl"
BOOK = "nn_book.json"
SCORECARD = "nn_scorecard.json"

# Grading horizon, in days. Matches the brain's 5d advice horizon so the two
# records are directly comparable — a different horizon would make every
# side-by-side number meaningless.
HORIZON_DAYS = 5

# A move this large (over the horizon, in the direction the net could have
# taken) counts as a real opportunity. Below it, standing aside is not a miss —
# it is correct restraint, and scoring it as a miss would push the net to be
# permanently long everything.
OPPORTUNITY_PCT = 2.0


def _sgt_day(ts: datetime) -> str:
    """SGT calendar day. The books run on Singapore time and the brain's
    scorecard already counts observations this way; using UTC here would split
    one trading day across two rows for the Asian session."""
    return (ts + timedelta(hours=8)).strftime("%Y-%m-%d")


class NN3LiveBook:
    """The NN-v3's parallel book. Constructed per runner, cheap when unavailable."""

    def __init__(self, settings, starting_cash: Optional[float] = None):
        self.settings = settings
        self.dir = os.path.join(
            os.path.dirname(os.path.abspath(settings.state_path)), SHADOW_DIR)
        self.model = None
        self.engine = None
        self.broker = None
        self.risk = None
        self.reason = ""
        try:
            os.makedirs(self.dir, exist_ok=True)
        except OSError as exc:
            self.reason = f"cannot create {self.dir}: {exc}"
            return
        self._load(starting_cash if starting_cash is not None
                   else getattr(settings, "starting_cash", 10000.0))
        from ai_investing.learning.outcome_ledger import OutcomeLedger
        self.outcomes = OutcomeLedger(self.dir, SHADOW_DIR, HORIZON_DAYS)

    # -- construction --------------------------------------------------------
    def _load(self, starting_cash: float) -> None:
        """Build the lane, or record why it is unavailable.

        Unavailable is the NORMAL state until a net has been fitted. The weekly
        challenger writes `data/nn_v3/formula.json` only when a fit
        succeeds; until then there is no net and this lane must say so rather
        than invent one. A randomly initialised net trading a book would produce
        a record that looks like evidence and is noise.
        """
        from ai_investing.brokers.paper import PaperBroker
        from ai_investing.learning.nn_v3 import NN3FormulaModel
        from ai_investing.strategy.decision import DecisionEngine
        from ai_investing.strategy.risk import RiskManager
        from ai_investing.strategy.user_views import UserViews
        from ai_investing.signals import default_signals

        path = os.path.join(self.dir, "formula.json")
        payload = atomic.read_json(path)
        if not isinstance(payload, dict):
            self.reason = ("no net fitted yet — data/nn_v3/formula.json absent. "
                           "The weekly challenger writes it only on a successful fit.")
            return
        model_d = payload.get("model") if isinstance(payload.get("model"), dict) else payload
        if (payload.get("model_type") or model_d.get("model_type")) != "nn3":
            self.reason = "data/nn_v3/formula.json is not an NN3 model"
            return
        try:
            self.model = NN3FormulaModel.from_dict(model_d)
        except (KeyError, TypeError, ValueError) as exc:
            self.reason = f"cannot load NN3 model: {exc}"
            return

        state = atomic.read_json(os.path.join(self.dir, BOOK))
        if isinstance(state, dict):
            try:
                self.broker = PaperBroker.from_state(
                    state, allow_short=self.settings.risk.allow_short)
                cash = getattr(self.broker, "_cash", None)
                if cash is None or cash != cash:
                    raise ValueError(f"non-finite cash {cash!r}")
            except (KeyError, ValueError, TypeError) as exc:
                print(f"!! NN3 LIVE BOOK rebuilt from scratch: {exc}")
                self.broker = None
        if self.broker is None:
            self.broker = PaperBroker(starting_cash, allow_short=self.settings.risk.allow_short)

        # UserViews() EMPTY on purpose: the net is graded on its own read.
        self.engine = DecisionEngine(default_signals(), model=self.model,
                                     user_views=UserViews())
        self.risk = RiskManager(self.settings.risk)
        # Do not treat the model loaded during construction as a new model on
        # every engine cycle. Without this, refresh() rebuilt the paper broker
        # repeatedly and made a healthy lane look like it was constantly
        # reloading.
        try:
            self._net_mtime = os.path.getmtime(path)
        except OSError:
            self._net_mtime = None

    @property
    def available(self) -> bool:
        return self.engine is not None and self.broker is not None

    def refresh(self) -> bool:
        """Reload the net if the challenger has written a newer one.

        Without this the lane loads its model once, at Runner construction, and
        a net written by Monday's 04:00 job would not be traded until the engine
        next restarted. That is a staleness trap of exactly the kind that has
        already cost this session twice: a process holding pre-deploy code, and
        a graph file read before the cycle wrote it. Both looked like "the
        feature does not work" and were really "the thing you are reading is
        older than the thing you changed".

        Cheap: one `stat` per cycle, and a reload only when the mtime moves.
        Returns True when a new net was actually taken up.
        """
        path = os.path.join(self.dir, "formula.json")
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return False
        if mtime == getattr(self, "_net_mtime", None):
            return False
        prev = self.model
        # `_load` restores the book from `nn_book.json`, which is written every
        # cycle, so the positions survive the model swap without being carried
        # by hand. They are the RECORD — a new net inherits the book its
        # predecessor opened, exactly as a new formula version does live.
        self._load(getattr(self.settings, "starting_cash", 10000.0))
        self._net_mtime = mtime
        took = self.model is not None and self.model is not prev
        if took:
            print(f"  [nn3-live] picked up a newly fitted net "
                  f"({getattr(self.model, 'n_params', '?')} params)")
        return took

    # -- the per-cycle pass --------------------------------------------------
    def run_cycle(self, prices: dict, context: dict, bars_by_key: dict, assets: list,
                  bad_data: set | None = None,
                  live_decisions: Optional[dict] = None, now: Optional[datetime] = None) -> dict:
        """Decide on every asset, journal it, and trade the paper book.
        
        This method is called by the runner for every cycle and makes actual trades,
        not just shadow records.
        """
        # Pick up a net the challenger wrote since this process started, before
        # deciding anything with the old one.
        try:
            self.refresh()
        except Exception as exc:
            print(f"  [nn3-live] refresh skipped: {type(exc).__name__}: {exc}")
        if not self.available:
            return {"available": False, "reason": self.reason}
        from ai_investing.util import atomic

        now = now or datetime.now(timezone.utc)
        day = _sgt_day(now)
        bad = bad_data or set()
        active = [a for a in assets if a.key not in bad and a.key in bars_by_key]
        from ai_investing.strategy.market import build_market_stats
        self._market = build_market_stats({a.key: bars_by_key[a.key] for a in active}, lookback=20)

        primaries = self._primary_symbols_for(day)
        rows, decisions = [], []
        for a in active:
            try:
                d = self.engine.decide(a, bars_by_key[a.key], context)
            except Exception as exc:          # one bad asset must not kill the lane
                print(f"  [nn3-live] {a.symbol}: {type(exc).__name__}: {exc}")
                continue
            decisions.append(d)
            live = (live_decisions or {}).get(a.symbol)
            is_primary = a.symbol not in primaries
            if is_primary:
                primaries.add(a.symbol)
            rows.append({
                "ts": now.isoformat(), "day": day, "symbol": a.symbol,
                "asset_key": a.key, "asset_class": a.asset_class.value,
                "is_primary": is_primary,
                "nn3": {
                    "direction": d.direction.name,
                    "target_weight": round(float(d.target_weight), 5),
                    "expected_return": round(float(d.expected_return), 6),
                    "confidence": round(float(d.confidence), 4),
                    "rationale": d.rationale[:220],
                    "ood_multiplier": 1.0,
                },
                # The brain's own call on the same asset, same cycle, same
                # inputs. Written here so "did the net see something the brain
                # missed" is answerable without reconstructing anything.
                "brain": None if live is None else {
                    "direction": live.direction.name,
                    "target_weight": round(float(live.target_weight), 5),
                    "expected_return": round(float(live.expected_return), 6),
                },
                "price": prices.get(a.key),
                "features": d.features,
                "model_version": getattr(self.model, "version", None),
                "state": "open" if is_primary else "replica",
            })

        self._append(rows)
        settled = self.outcomes.settle(self._path(DECISIONS), prices, assets, now)

        # trade the paper book — stops first, then sizing, exactly as the live
        # lane does, so the comparison is like-for-like rather than a difference
        # in risk plumbing wearing the label of a difference in model.
        try:
            port = self.broker.portfolio()
            for o in self.risk.stop_orders(port, prices, market=self._market):
                self._fill(o, prices)
            port = self.broker.portfolio()
            equity = port.equity(prices)
            for o in self.risk.size_orders(decisions, port, prices, equity,
                                           market=self._market, model=self.model):
                self._fill(o, prices)
            atomic.write_json(os.path.join(self.dir, BOOK), self.broker.state())
        except Exception as exc:
            print(f"  [nn3-live] book skipped: {type(exc).__name__}: {exc}")

        return {"available": True, "decided": len(decisions),
                "primaries": sum(1 for r in rows if r["is_primary"]),
                "equity": round(self.broker.portfolio().equity(prices), 2),
                "settled": settled}

    def _fill(self, order, prices: dict) -> None:
        """No price, no fill. The 0.0-sentinel that put NaN into `shadow.json`
        (§4A) is not repeated here — an unpriced order is dropped, not filled at
        zero."""
        mid = prices.get(order.asset.key)
        if not mid or mid != mid:
            return
        from ai_investing.execution.costs import CostModel, market_cost_model, market_of_symbol
        stats = getattr(self, "_market", {}).get(order.asset.key)
        asset_class = getattr(getattr(order.asset, "asset_class", None), "value", "stock")
        costs = market_cost_model(CostModel(), market_of_symbol(
            order.asset.symbol, asset_class))
        effective = costs.effective_price(getattr(order, "side", None), mid, getattr(order, "qty", 0.0),
                                          stats.adv if stats else None,
                                          stats.vol if stats else None)
        self.broker.submit(order, effective)

    # -- journal -------------------------------------------------------------
    def _path(self, name: str) -> str:
        return os.path.join(self.dir, name)

    def _append(self, rows: list[dict]) -> None:
        if not rows:
            return
        try:
            with open(self._path(DECISIONS), "a") as fh:
                for r in rows:
                    fh.write(json.dumps(r) + "\n")
        except OSError as exc:
            print(f"  [nn3-live] journal write failed: {type(exc).__name__}: {exc}")

    def _primary_symbols_for(self, day: str) -> set:
        """Symbols already holding today's primary row. Read from disk so a
        restart mid-day cannot mint a second primary for the same (symbol, day)
        — which would be the 65x defect reappearing through the back door."""
        out: set = set()
        try:
            with open(self._path(DECISIONS), errors="replace") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or f'"{day}"' not in line:
                        continue
                    try:
                        r = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if r.get("day") == day and r.get("is_primary"):
                        out.add(r.get("symbol"))
        except OSError:
            pass
        return out

    def read_primaries(self) -> list[dict]:
        """Every primary row, oldest first. The unit of every comparison."""
        rows = []
        try:
            with open(self._path(DECISIONS), errors="replace") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        r = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if r.get("is_primary"):
                        rows.append(r)
        except OSError:
            pass
        return rows
NNv3LiveBook = NN3LiveBook
