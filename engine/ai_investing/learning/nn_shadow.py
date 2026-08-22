"""The NN's own trading book — a shadow decision-maker, isolated from the brain.

WHAT THIS IS. `nn_formula.py` fits a net; `backtest/main.py --optimize` decides
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
  2. Its own state, under `data/nn_shadow/` only. It never writes
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
from ai_investing.models import SignalDirection

SHADOW_DIR = "nn_shadow"
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


class NNShadowBook:
    """The net's parallel book. Constructed per runner, cheap when unavailable."""

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

    # -- construction --------------------------------------------------------
    def _load(self, starting_cash: float) -> None:
        """Build the lane, or record why it is unavailable.

        Unavailable is the NORMAL state until a net has been fitted. The weekly
        challenger writes `data/nn_shadow/formula.json` only when a fit
        succeeds; until then there is no net and this lane must say so rather
        than invent one. A randomly initialised net trading a book would produce
        a record that looks like evidence and is noise.
        """
        from ai_investing.brokers.paper import PaperBroker
        from ai_investing.learning.nn_formula import NNFormulaModel
        from ai_investing.strategy.decision import DecisionEngine
        from ai_investing.strategy.risk import RiskManager
        from ai_investing.strategy.user_views import UserViews
        from ai_investing.signals import default_signals
        from ai_investing.util import atomic

        path = os.path.join(self.dir, "formula.json")
        payload = atomic.read_json(path)
        if not isinstance(payload, dict):
            self.reason = ("no net fitted yet — data/nn_shadow/formula.json absent. "
                           "The weekly challenger writes it only on a successful fit.")
            return
        model_d = payload.get("model") if isinstance(payload.get("model"), dict) else payload
        if (payload.get("model_type") or model_d.get("model_type")) != "nn":
            self.reason = "data/nn_shadow/formula.json is not an NN model"
            return
        try:
            self.model = NNFormulaModel.from_dict(model_d)
        except (KeyError, TypeError, ValueError) as exc:
            self.reason = f"cannot load NN model: {exc}"
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
                print(f"!! NN SHADOW BOOK rebuilt from scratch: {exc}")
                self.broker = None
        if self.broker is None:
            self.broker = PaperBroker(cash=starting_cash,
                                      allow_short=self.settings.risk.allow_short)
        # UserViews() EMPTY on purpose: the net is graded on its own read.
        self.engine = DecisionEngine(default_signals(), model=self.model,
                                     user_views=UserViews())
        self.risk = RiskManager(self.settings.risk)

    @property
    def available(self) -> bool:
        return self.engine is not None and self.broker is not None

    # -- the per-cycle pass --------------------------------------------------
    def run(self, prices: dict, context: dict, bars_by_key: dict, assets: list,
            bad_data: set | None = None,
            live_decisions: Optional[dict] = None, now: Optional[datetime] = None) -> dict:
        """Decide on every asset, journal it, and trade the paper book.

        `live_decisions` maps symbol -> the live engine's Decision for this same
        cycle. It is journalled ALONGSIDE the net's own so the comparison is a
        row lookup later rather than a join across two systems on a timestamp,
        which is where this kind of comparison usually rots.
        """
        if not self.available:
            return {"available": False, "reason": self.reason}
        from ai_investing.util import atomic

        now = now or datetime.now(timezone.utc)
        day = _sgt_day(now)
        bad = bad_data or set()
        active = [a for a in assets if a.key not in bad and a.key in bars_by_key]

        primaries = self._primary_symbols_for(day)
        rows, decisions = [], []
        for a in active:
            try:
                d = self.engine.decide(a, bars_by_key[a.key], context)
            except Exception as exc:          # one bad asset must not kill the lane
                print(f"  [nn-shadow] {a.symbol}: {type(exc).__name__}: {exc}")
                continue
            decisions.append(d)
            live = (live_decisions or {}).get(a.symbol)
            is_primary = a.symbol not in primaries
            if is_primary:
                primaries.add(a.symbol)
            rows.append({
                "ts": now.isoformat(), "day": day, "symbol": a.symbol,
                "is_primary": is_primary,
                "nn": {
                    "direction": d.direction.name,
                    "target_weight": round(float(d.target_weight), 5),
                    "expected_return": round(float(d.expected_return), 6),
                    "confidence": round(float(d.confidence), 4),
                    "rationale": d.rationale[:220],
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
                "state": "open" if is_primary else "replica",
            })

        self._append(rows)

        # trade the paper book — stops first, then sizing, exactly as the live
        # lane does, so the comparison is like-for-like rather than a difference
        # in risk plumbing wearing the label of a difference in model.
        try:
            port = self.broker.portfolio()
            for o in self.risk.stop_orders(port, prices):
                self._fill(o, prices)
            port = self.broker.portfolio()
            equity = port.equity(prices)
            for o in self.risk.size_orders(decisions, port, prices, equity,
                                           model=self.model):
                self._fill(o, prices)
            atomic.write_json(os.path.join(self.dir, BOOK), self.broker.state())
        except Exception as exc:
            print(f"  [nn-shadow] book skipped: {type(exc).__name__}: {exc}")

        return {"available": True, "decided": len(decisions),
                "primaries": sum(1 for r in rows if r["is_primary"]),
                "equity": round(self.broker.portfolio().equity(prices), 2)}

    def _fill(self, order, prices: dict) -> None:
        """No price, no fill. The 0.0-sentinel that put NaN into `shadow.json`
        (§4A) is not repeated here — an unpriced order is dropped, not filled at
        zero."""
        mid = prices.get(order.asset.key)
        if not mid or mid != mid:
            return
        self.broker.submit(order, mid)

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
            print(f"  [nn-shadow] journal write failed: {type(exc).__name__}: {exc}")

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


def grade(settings, price_lookup, horizon: int = HORIZON_DAYS,
          now: Optional[datetime] = None) -> dict:
    """Grade matured primary decisions, and score the net against the brain.

    `price_lookup(symbol, day) -> float | None` supplies the settled price, so
    this function does no market access of its own and is testable offline.

    FOUR OUTCOMES, because a decision record that only counts what it took is a
    brochure. Standing aside is a decision and it is graded:

      captured  positioned, and the move went its way
      wrong     positioned, and it did not
      missed    FLAT while the asset moved more than OPPORTUNITY_PCT — the
                opportunity cost that a P&L-only record never shows
      avoided   FLAT and the move was small, or would have lost money

    `missed` is the half the user asked for and the half normally absent. A book
    that never trades has no losses and looks disciplined; counting its misses
    is what separates discipline from paralysis.
    """
    now = now or datetime.now(timezone.utc)
    book = NNShadowBook(settings)
    rows = book.read_primaries()
    cutoff = _sgt_day(now - timedelta(days=horizon))

    out = {"captured": 0, "wrong": 0, "missed": 0, "avoided": 0,
           "graded": 0, "pending": 0, "agree_with_brain": 0, "disagree": 0,
           "nn_right_brain_wrong": 0, "brain_right_nn_wrong": 0}
    for r in rows:
        if r.get("day", "") > cutoff:
            out["pending"] += 1
            continue
        entry, settle = r.get("price"), price_lookup(r.get("symbol"), r.get("day"))
        if not entry or not settle:
            out["pending"] += 1
            continue
        ret_pct = (settle - entry) / entry * 100.0
        nn = r.get("nn") or {}
        d = nn.get("direction")
        out["graded"] += 1

        if d == SignalDirection.LONG.name:
            nn_right = ret_pct > 0
            out["captured" if nn_right else "wrong"] += 1
        elif d == SignalDirection.SHORT.name:
            nn_right = ret_pct < 0
            out["captured" if nn_right else "wrong"] += 1
        else:
            nn_right = abs(ret_pct) < OPPORTUNITY_PCT
            out["avoided" if nn_right else "missed"] += 1

        brain = r.get("brain") or {}
        bd = brain.get("direction")
        if bd:
            if bd == d:
                out["agree_with_brain"] += 1
            else:
                out["disagree"] += 1
                if bd == SignalDirection.LONG.name:
                    brain_right = ret_pct > 0
                elif bd == SignalDirection.SHORT.name:
                    brain_right = ret_pct < 0
                else:
                    brain_right = abs(ret_pct) < OPPORTUNITY_PCT
                if nn_right and not brain_right:
                    out["nn_right_brain_wrong"] += 1
                elif brain_right and not nn_right:
                    out["brain_right_nn_wrong"] += 1

    taken = out["captured"] + out["wrong"]
    out["hit_rate_when_positioned"] = (round(out["captured"] / taken, 3)
                                       if taken else None)
    # Independent observations, not rows. Daily readings of a 5-day forward
    # return overlap by 4/5, so the honest sample is n/horizon — the gap between
    # them IS the finding (AUDITING.md trap 2).
    out["n_independent"] = max(1, out["graded"] // max(1, horizon))
    out["note"] = (f"one observation per (symbol, day); `missed` counts FLAT calls "
                   f"where the asset moved >{OPPORTUNITY_PCT}% — the opportunity "
                   f"cost a P&L-only record cannot show. n_independent, not "
                   f"`graded`, is what the sample is worth.")
    return out
