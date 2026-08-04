"""The event-reaction sleeve — the THIRD policy (adopted R35, 2026-08-02).

The trading book trades the accumulated field (conviction that builds over
days). The investing book trades 6-month theses. This sleeve trades the FRESH
SHOCK: what today's news alone says, propagated on its own with no history and
no decay (`brain.think()` -> state["shock_assets"]).

Same brain, faster clock. Own capital, own book file, own rules:
  - enter when |fresh shock| >= EVENT_MIN (0.05 = the measured p90 of the
    shock distribution; p99 is 0.11)
  - at most EVENT_N concurrent positions, equal slices of the sleeve's equity
  - exit after EVENT_HOLD trading days, or on the user's 10% hard stop
  - LONG ONLY and UNLEVERED: the gauntlet rejected shorts (R37) and leverage
    (R36) on their own merits — do not re-enable without re-testing
  - exits never ask permission; entries respect the same approval setting as
    the other books when TRADE_APPROVAL is on (handled by the caller)

Backtest evidence (train window): +6.4% on its own capital, Sharpe 0.66,
-7.1% dd, ~32 trades; adding it lifted the blended holdout objective from
-0.060 to +0.029 — the first positive holdout objective on record. Its LIVE
edge should be better than the backtest can show, because the replay can only
react on daily bars while this reacts within a cycle of the event.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from ai_investing.brokers.paper import PaperBroker
from ai_investing.util import atomic
from ai_investing.models import Asset, AssetClass, Order, Side, mark_price

EVENT_MIN = float(os.environ.get("EVENT_MIN", "0.05"))
EVENT_N = int(os.environ.get("EVENT_N", "3"))
EVENT_HOLD_DAYS = int(os.environ.get("EVENT_HOLD_DAYS", "2"))
HARD_STOP = 0.10          # USER HARD RULE: max 10% loss on any position
START_CASH = float(os.environ.get("EVENT_START_CASH", "100000"))


def _asset(sym: str, exchange: str) -> Asset:
    if "/" in sym:
        return Asset(sym, AssetClass.CRYPTO, exchange=exchange)
    return Asset(sym, AssetClass.STOCK)


class EventSleeve:
    def __init__(self, settings):
        self.settings = settings
        data_dir = os.path.dirname(os.path.abspath(settings.state_path))
        self.path = os.path.join(data_dir, "event_state.json")
        self.journal = os.path.join(data_dir, "event_journal.jsonl")
        self._state = self._load()
        self.broker = PaperBroker.from_state(self._state.get("broker", {})) \
            if self._state.get("broker") else PaperBroker(START_CASH)
        try:                       # the expectation ledger: claim -> outcome -> learn
            from ai_investing.learning.spine import LearningSpine
            self.ledger = LearningSpine(settings)
        except Exception:
            self.ledger = None

    def _load(self) -> dict:
        try:
            with open(self.path) as fh:
                return json.load(fh)
        except (OSError, json.JSONDecodeError):
            return {}


    def _stamp_marks(self, prices: dict) -> None:
        """Record equity and per-position marks into the saved state.

        Readers (the Telegram portfolio, any dashboard) only have the state
        file. Without marks they can show cash but not VALUE — and cash alone
        is actively misleading once a book holds shorts, because short proceeds
        sit in cash that is still owed. The engine already has prices every
        cycle; persisting them here means no reader ever needs to refetch.
        """
        b = self._state.get("broker") or {}
        mv = 0.0
        stale = 0
        for p in b.get("positions", []):
            avg = float(p.get("avg_price", 0) or 0.0)
            qty = float(p.get("qty", 0) or 0.0)
            raw = prices.get(p.get("symbol"))
            px = mark_price(raw, avg)
            priced = mark_price(raw, 0.0) > 0.0
            # EVERY position is valued, always. The old form only added a
            # position to `mv` when it had a live price, which silently dropped
            # unpriced holdings out of equity -- an unpriced short read as a debt
            # that vanished. Cost basis keeps it in the book at the last price
            # actually paid, and stale_mark tells a reader that is what happened.
            p["price"] = round(px, 6)
            p["pnl"] = round((px - avg) * qty, 2)
            p["stale_mark"] = not priced
            mv += qty * px
            stale += 0 if priced else 1
        self._state["equity"] = round(float(b.get("cash", 0.0)) + mv, 2)
        self._state["stale_marks"] = stale
        self._state["marked_at"] = datetime.now(timezone.utc).isoformat()

    def mark(self, prices: dict) -> None:
        """Value the book without trading it.

        Valuation must not depend on whether the trading logic ran: this book
        gates itself (once a day, or only on fresh shocks), so its saved state
        could sit unmarked for hours while positions moved.
        """
        self._mark_prices = prices
        self._save()

    def _save(self) -> None:
        self._state["broker"] = self.broker.state()
        # AFTER the refresh: broker.state() rebuilds the positions list, so
        # marks written before this line are silently discarded.
        if getattr(self, "_mark_prices", None):
            self._stamp_marks(self._mark_prices)
        self._state["ts"] = datetime.now(timezone.utc).isoformat()
        try:
            atomic.write_json(self.path, self._state, indent=1)
        except OSError:
            pass

    def _log(self, event: str, **kw) -> None:
        try:
            with open(self.journal, "a") as fh:
                fh.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(),
                                     "event": event, **kw}) + "\n")
        except OSError:
            pass

    def _equity(self, prices: dict) -> float:
        eq = self.broker.get_cash()
        for p in self.broker.get_positions().values():
            px = prices.get(p.asset.symbol, 0.0)
            if px > 0:
                eq += p.qty * px
        return eq

    # -- one pass per engine cycle -------------------------------------------
    def cycle(self, shock_assets: dict, prices_by_sym: dict, notifier=None,
              labels: dict | None = None, regime: str = "neutral") -> dict:
        """shock_assets: brain state["shock_assets"] — FRESH impacts only."""
        labels = labels or {}
        opened, closed = [], []
        held = self._state.setdefault("held", {})     # sym -> {entry, opened_iso, bars}
        today = datetime.now(timezone.utc).date().isoformat()
        days = self._state.setdefault("seen_days", [])
        if today not in days:
            days.append(today)
            self._state["seen_days"] = days[-30:]

        # 1) exits first — clock or hard stop; never gated by anything
        for sym, pos in list(self.broker.get_positions().items()):
            px = prices_by_sym.get(pos.asset.symbol, 0.0)
            meta = held.get(pos.asset.symbol, {})
            if px <= 0 or pos.qty == 0:
                continue
            move = (px - pos.avg_price) / pos.avg_price
            age = len([d for d in days if d >= meta.get("opened_day", today)]) - 1
            reason = None
            if move <= -HARD_STOP:
                reason = f"hard stop {move*100:+.1f}%"
            elif age >= EVENT_HOLD_DAYS:
                reason = f"clock {age}d {move*100:+.1f}%"
            if reason:
                pnl = (px - pos.avg_price) * pos.qty
                self.broker.submit(Order(pos.asset, Side.SELL, abs(pos.qty),
                                         reason=f"event sleeve: {reason}"), px)
                settled = (self.ledger.settle("event", pos.asset.symbol, move,
                                              held_days=age, exit_reason=reason)
                           if self.ledger else None)
                self._log("sell", symbol=pos.asset.symbol, price=px,
                          entry=round(pos.avg_price, 6), pnl=round(pnl, 2),
                          ret=round(move, 4), held_days=age, reason=reason,
                          shock=meta.get("shock"),
                          **({"expected": settled["expected_move"],
                              "ratio": settled["ratio"],
                              "score": settled["score"]} if settled else {}))
                held.pop(pos.asset.symbol, None)
                closed.append((pos.asset.symbol, reason, move))
                if notifier:
                    notifier.send(f"⚡️ *Event sleeve — closed {labels.get(pos.asset.symbol, pos.asset.symbol)}*"
                                  f" ({pos.asset.symbol}): {reason} (pretend money).")

        # 2) entries — biggest fresh shocks above the floor, long only
        open_n = len(self.broker.get_positions())
        room = max(0, EVENT_N - open_n)
        if room:
            eq = self._equity(prices_by_sym)
            # THE RE-ENTRY GUARD, AND IT NEVER WORKED (fixed 2026-08-04).
            # `sym in self.broker.get_positions()` compared a bare symbol ("USO")
            # against a dict keyed by Asset.key ("stock:USO"), so it was ALWAYS
            # False. Every time a symbol reappeared as a fresh shock the sleeve
            # bought it again: USO went in twice, $33,479 each, ending at $66,958
            # — 67% of a book whose design puts 33% in any one name (eq/EVENT_N).
            #
            # It also silently overwrote held[sym], losing the first entry's price
            # and opened_day, so the position's stop and 2-day clock were measured
            # from the SECOND buy.
            #
            # Compare symbols to symbols. The exit path a few lines up got this
            # right — it uses `pos.asset.symbol` — which is why exits worked while
            # entries doubled up, and why nothing looked broken.
            open_syms = {p.asset.symbol for p in self.broker.get_positions().values()}
            cands = []
            for sym, row in (shock_assets or {}).items():
                im = float(row.get("impact", 0.0))
                px = prices_by_sym.get(sym, 0.0)
                if im < EVENT_MIN or px <= 0 or sym in open_syms or sym in held:
                    continue
                cands.append((im, sym, row))
            cands.sort(reverse=True)
            trust = self.ledger.size_multiplier("event", regime) if self.ledger else 1.0
            for im, sym, row in cands[:room]:
                notional = min(eq * trust / max(1, EVENT_N), self.broker.get_cash() * 0.9)
                if notional < 500:
                    continue
                px = prices_by_sym[sym]
                o = self.broker.submit(
                    Order(_asset(sym, self.settings.crypto_exchange), Side.BUY,
                          notional / px, reason=f"event sleeve: fresh shock {im:+.3f}"), px)
                if o.filled_qty:
                    held[sym] = {"entry": px, "opened_day": today, "shock": round(im, 4)}
                    opened.append((sym, im, notional))
                    self._log("buy", symbol=sym, price=px, notional=round(notional, 2),
                              shock=round(im, 4), node=row.get("node", ""),
                              size_mult=round(trust, 3))
                    if self.ledger:
                        self.ledger.record("event", sym, 1, im,
                                           float(row.get("vol_daily") or 0.02),
                                           EVENT_HOLD_DAYS, regime=regime,
                                           driver=row.get("node", ""), notional=notional)
                    if notifier:
                        notifier.send(
                            f"⚡️ *Event sleeve — bought {labels.get(sym, sym)}* ({sym}), "
                            f"~${notional:,.0f} on a fresh news shock of {im:+.2f} "
                            f"via {row.get('node','the web')}. Out in {EVENT_HOLD_DAYS} days "
                            f"or on a 10% stop — whichever comes first (pretend money).")
        eqnow = self._equity(prices_by_sym)
        if self._state.get("last_mark") != today:
            self._state["last_mark"] = today
            self._log("mark", equity=round(eqnow, 2), cash=round(self.broker.get_cash(), 2),
                      positions=len(self.broker.get_positions()))
        self._mark_prices = prices_by_sym
        self._save()
        return {"opened": opened, "closed": closed,
                "equity": round(self._equity(prices_by_sym), 2),
                "cash": round(self.broker.get_cash(), 2),
                "positions": len(self.broker.get_positions())}
