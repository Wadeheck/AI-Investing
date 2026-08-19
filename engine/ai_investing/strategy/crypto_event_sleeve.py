"""The crypto event-reaction sleeve — crypto's twin of `event_sleeve.py`.

`EventSleeve` trades the FRESH SHOCK (today's news alone, no history, no
decay) but is stocks only (2026-08-19): crypto and stocks used to fight over
the same 3 slots and the same $10k, so a loud crypto shock could starve a
stock candidate of size out of a pool the user thinks of as "the stock event
sleeve". This module is the split-out other half — same fresh-shock idea,
own capital, own slots, crypto only.

It deliberately does NOT inherit the majors-only restriction from
`crypto_book.py` (R27: alts are signal-only there). That restriction exists
because the HODL/tactical sleeve trades the ACCUMULATED field, where alt
history is thin and a slow drift is easy to mistake for edge. This sleeve
reacts to a single fresh shock crossing a fixed floor — if an alt-coin node
throws a large enough shock to qualify, catching that IS the point of an
event sleeve, alts included.

Same shape as the stock event sleeve, translated to a 24/7 book:
  - enter when |fresh shock| >= CRYPTO_EVENT_MIN
  - at most CRYPTO_EVENT_N concurrent positions, equal slices of the sleeve's
    equity
  - exit after CRYPTO_EVENT_HOLD_DAYS, or on the user's 10% hard stop
  - LONG ONLY. No leverage, no shorts — v1, mirroring the stock sleeve's
    adopted (R35) shape rather than its off-by-default conditional variants.
  - runs on EVERY engine cycle, not gated to stock-market hours — crypto
    never closes, same reasoning as `crypto_book.py`.
  - it "decides if it wants to trade": the threshold IS the decision. A
    quiet cycle with no shock over CRYPTO_EVENT_MIN holds cash and does
    nothing, same as the stock sleeve on a quiet news day.

No shared venue here — crypto never routes to Longbridge in this codebase,
so this book uses a local, non-venue `PaperBroker` exactly like
`crypto_book.py`, none of the shared-account plumbing `event_sleeve.py`
needs for its real stock fills (pending-order resolution, lot flooring,
migration).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from ai_investing.brokers.paper import PaperBroker
from ai_investing.util import atomic
from ai_investing.models import Asset, AssetClass, Order, Side, mark_price

CRYPTO_EVENT_MIN = float(os.environ.get("CRYPTO_EVENT_MIN", "0.05"))
CRYPTO_EVENT_N = int(os.environ.get("CRYPTO_EVENT_N", "3"))
CRYPTO_EVENT_HOLD_DAYS = int(os.environ.get("CRYPTO_EVENT_HOLD_DAYS", "2"))
HARD_STOP = 0.10          # USER HARD RULE: max 10% loss on any position
START_CASH = float(os.environ.get("CRYPTO_EVENT_START_CASH", "100000"))


class CryptoEventSleeve:
    def __init__(self, settings):
        self.settings = settings
        data_dir = os.path.dirname(os.path.abspath(settings.state_path))
        self.path = os.path.join(data_dir, "crypto_event_state.json")
        self.journal = os.path.join(data_dir, "crypto_event_journal.jsonl")
        self._state = self._load()
        b = self._state.get("broker")
        self.broker = PaperBroker.from_state(b) if b else PaperBroker(START_CASH)
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
        b = self._state.get("broker") or {}
        mv = 0.0
        stale = 0
        for p in b.get("positions", []):
            avg = float(p.get("avg_price", 0) or 0.0)
            qty = float(p.get("qty", 0) or 0.0)
            raw = prices.get(p.get("symbol"))
            px = mark_price(raw, avg)
            priced = mark_price(raw, 0.0) > 0.0
            p["price"] = round(px, 6)
            p["pnl"] = round((px - avg) * qty, 2)
            p["stale_mark"] = not priced
            mv += qty * px
            stale += 0 if priced else 1
        self._state["equity"] = round(float(b.get("cash", 0.0)) + mv, 2)
        self._state["stale_marks"] = stale
        self._state["marked_at"] = datetime.now(timezone.utc).isoformat()

    def mark(self, prices: dict) -> None:
        self._mark_prices = prices
        self._save()

    def _save(self) -> None:
        self._state["broker"] = self.broker.state()
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

    # -- one pass per engine cycle, 24/7 --------------------------------------
    def cycle(self, shock_assets: dict, prices_by_sym: dict, notifier=None,
              labels: dict | None = None, regime: str = "neutral") -> dict:
        """shock_assets: brain state["shock_assets"] — FRESH impacts only."""
        labels = labels or {}
        opened, closed = [], []
        held = self._state.setdefault("held", {})     # sym -> {entry, opened_day, shock}
        open_syms = {p.asset.symbol for p in self.broker.get_positions().values()}
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
            elif age >= CRYPTO_EVENT_HOLD_DAYS:
                reason = f"clock {age}d {move*100:+.1f}%"
            if reason:
                entry = pos.avg_price
                o = self.broker.submit(Order(pos.asset, Side.SELL, abs(pos.qty),
                                             reason=f"crypto event sleeve: {reason}"), px)
                filled = float(o.filled_qty or 0.0)
                if filled <= 0:
                    self._log("exit_unfilled", symbol=pos.asset.symbol, price=px,
                              requested_qty=round(abs(pos.qty), 6), reason=reason,
                              detail=(o.reason or "no fill"))
                    continue
                pnl = (px - entry) * filled
                settled = (self.ledger.settle("crypto_event", pos.asset.symbol, move,
                                              held_days=age, exit_reason=reason)
                           if self.ledger else None)
                self._log("sell", symbol=pos.asset.symbol, price=px,
                          qty=round(filled, 6), entry=round(entry, 6),
                          pnl=round(pnl, 2), ret=round(move, 4), held_days=age,
                          reason=reason, shock=meta.get("shock"),
                          **({"expected": settled["expected_move"],
                              "ratio": settled["ratio"],
                              "score": settled["score"]} if settled else {}))
                held.pop(pos.asset.symbol, None)
                closed.append((pos.asset.symbol, reason, move))
                if notifier:
                    notifier.send(f"⚡️₿ *Crypto event sleeve — closed "
                                  f"{labels.get(pos.asset.symbol, pos.asset.symbol)}*"
                                  f" ({pos.asset.symbol}): {reason} (pretend money).")

        # 2) entries — biggest fresh crypto shocks above the floor. Long only.
        room = max(0, CRYPTO_EVENT_N - len(open_syms))
        if room:
            eq = self._equity(prices_by_sym)
            cands = []
            for sym, row in (shock_assets or {}).items():
                if "/" not in sym:
                    # CRYPTO ONLY — stock shocks belong to event_sleeve.py,
                    # not this book's slots and capital.
                    continue
                im = float(row.get("impact", 0.0))
                px = prices_by_sym.get(sym, 0.0)
                if px <= 0 or sym in open_syms or sym in held:
                    continue
                if im < CRYPTO_EVENT_MIN:
                    continue
                cands.append((abs(im), im, sym, row))
            cands.sort(reverse=True)
            trust = self.ledger.size_multiplier("crypto_event", regime) if self.ledger else 1.0
            for _, im, sym, row in cands[:room]:
                notional = min(eq * trust / max(1, CRYPTO_EVENT_N),
                               self.broker.get_cash() * 0.9)
                if notional < 500:
                    continue
                px = prices_by_sym[sym]
                asset = Asset(sym, AssetClass.CRYPTO, exchange=self.settings.crypto_exchange)
                qty = notional / px
                o = self.broker.submit(
                    Order(asset, Side.BUY, qty,
                          reason=f"crypto event sleeve: fresh shock {im:+.3f}"), px)
                if not o.filled_qty:
                    self._log("rejected", symbol=sym, price=round(px, 6),
                              requested_qty=round(qty, 6), shock=round(im, 4),
                              notional=round(notional, 2),
                              reason=(o.reason or "no fill"))
                    continue
                notional = float(o.filled_qty) * float(o.filled_price or px)
                held[sym] = {"entry": float(o.filled_price or px),
                             "opened_day": today, "shock": round(im, 4)}
                opened.append((sym, im, notional))
                self._log("buy", symbol=sym, price=px, notional=round(notional, 2),
                          shock=round(im, 4), node=row.get("node", ""),
                          size_mult=round(trust, 3))
                if self.ledger:
                    self.ledger.record("crypto_event", sym, 1, im,
                                       float(row.get("vol_daily") or 0.03),
                                       CRYPTO_EVENT_HOLD_DAYS, regime=regime,
                                       driver=row.get("node", ""), notional=notional)
                if notifier:
                    notifier.send(
                        f"⚡️₿ *Crypto event sleeve — bought {labels.get(sym, sym)}* ({sym}), "
                        f"~${notional:,.0f} on a fresh news shock of {im:+.2f} "
                        f"via {row.get('node','the web')}. Out in {CRYPTO_EVENT_HOLD_DAYS} days "
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
