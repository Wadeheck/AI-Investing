"""The event-reaction sleeve — the THIRD policy (adopted R35, 2026-08-02).

The trading book trades the accumulated field (conviction that builds over
days). The investing book trades 6-month theses. This sleeve trades the FRESH
SHOCK: what today's news alone says, propagated on its own with no history and
no decay (`brain.think()` -> state["shock_assets"]).

STOCKS ONLY (2026-08-19). `_asset()` used to route any symbol with a "/" to
crypto, so this sleeve could fill one of its 3 slots with a crypto shock and
starve a stock candidate of the same size, out of a pool the user thinks of as
"the stock event sleeve". Crypto shocks now get their own capital and slots in
`crypto_event_sleeve.py` — see that module for the twin. Filtered at the
candidate loop, not just in `_asset`, so a crypto shock is never sized, held or
counted against EVENT_N here.

Same brain, faster clock. Own capital, own book file, own rules:
  - enter when |fresh shock| >= EVENT_MIN (0.05 = the measured p90 of the
    shock distribution; p99 is 0.11)
  - at most EVENT_N concurrent positions, equal slices of the sleeve's equity
  - exit after EVENT_HOLD trading days, or on the user's 10% hard stop
  - LONG ONLY and UNLEVERED by default: the gauntlet rejected all-weather
    shorts (R37) and leverage (R36) on their own merits. The CONDITIONAL
    variants are wired but OFF: EVENT_LEV>1 gears entries only while the risk
    field is >= EVENT_LEV_GATE (R38), EVENT_SHORT=1 allows bad-news shorts
    only in crypto winter (R39, EVENT_SHORT_WINTER=0 removes the winter gate
    — that shape was R37, rejected). Flip these envs ONLY after the monthly
    gauntlet re-run ADOPTS the matching round; the sim and this code
    deliberately share semantics so a verdict there is a license here.
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
import math
import os
from datetime import datetime, timezone

from ai_investing.brokers.shared import build_book_broker
from ai_investing.util import atomic
from ai_investing.strategy.booklog import BookBasisMixin
from ai_investing.models import Asset, AssetClass, Order, OrderStatus, Side, mark_price

EVENT_MIN = float(os.environ.get("EVENT_MIN", "0.05"))
EVENT_N = int(os.environ.get("EVENT_N", "3"))
EVENT_HOLD_DAYS = int(os.environ.get("EVENT_HOLD_DAYS", "2"))
HARD_STOP = 0.10          # USER HARD RULE: max 10% loss on any position
START_CASH = float(os.environ.get("EVENT_START_CASH", "100000"))
# R38/R39 conditional variants — defaults are the adopted (R35) shape: off.
EVENT_LEV = float(os.environ.get("EVENT_LEV", "1.0"))
EVENT_LEV_GATE = float(os.environ.get("EVENT_LEV_GATE", "0.0"))
EVENT_SHORT = os.environ.get("EVENT_SHORT", "0").lower() in ("1", "true", "yes")
EVENT_SHORT_WINTER = os.environ.get("EVENT_SHORT_WINTER", "1").lower() in ("1", "true", "yes")


def _asset(sym: str, exchange: str) -> Asset:
    return Asset(sym, AssetClass.STOCK)


class EventSleeve(BookBasisMixin):
    def __init__(self, settings, stock_broker=None, lots=None):
        """`stock_broker` is the ONE shared live stock adapter, or None.

        None is the normal case and covers three of them: SHARED_STOCK_ACCOUNT
        off, the engine not live, and the mark-only path (valuing a book must
        never need a venue). Only `Runner.run_cycle` passes a real one, and it
        passes the instance it already built rather than constructing a second —
        `LongbridgeBroker.__init__` makes a live API call.
        """
        self.settings = settings
        data_dir = os.path.dirname(os.path.abspath(settings.state_path))
        self.path = os.path.join(data_dir, "event_state.json")
        self.journal = os.path.join(data_dir, "event_journal.jsonl")
        self._state = self._load()
        self.broker, migration = build_book_broker(
            "event", settings, self._state, START_CASH,
            stock_broker=stock_broker, lots=lots)
        # Journalled by `_save()`, once the migration has actually been
        # PERSISTED — not here. These books are constructed several times a
        # cycle and some paths return without saving (`Investor.daily_manage`
        # bails early when the day is already managed), so logging at
        # construction records migrations that were computed and thrown away.
        # It happened on the real cutover: two identical lines, one book.
        self._migration = migration
        if migration:
            # THE RE-ENTRY GUARD OUTLIVES THE POSITION IT GUARDED. `held` is
            # popped on exit, and migration is not an exit — it closes the
            # simulated position directly. Left alone, `sym in held` (the entry
            # filter below) would block NVDA, TSM and AMD from this sleeve
            # permanently, and the symptom would be a sleeve that quietly never
            # trades its three best-known names again.
            closed = {c["symbol"] for c in migration["closed_simulated_stock"]}
            held = self._state.get("held") or {}
            for sym in closed:
                held.pop(sym, None)
            self._state["held"] = held
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

    def _money(self) -> str:
        """What every Telegram message calls this book's money.

        Hardcoded as "pretend money" everywhere until now, which stops being true
        the moment stock orders route to a real venue. A message that says
        "pretend" about a real order is worse than no message: it is the one line
        a reader would use to decide an alert can wait.
        """
        return ("real orders on the shared account"
                if getattr(self.broker, "live", False) else "pretend money")

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

        This is also the only path that runs EVERY cycle, so it is where the
        shared account's two per-cycle obligations live: pick up late fills, and
        book realised P&L. `cycle()` does both as well, but `cycle()` only wakes
        on a fresh shock — an order that fills on a quiet day would otherwise sit
        unclaimed until the next one, which is exactly the drift the pending
        machinery exists to close.
        """
        self._mark_prices = prices
        for note in (self.broker.resolve_pending()
                     if hasattr(self.broker, "resolve_pending") else []):
            self._log("pending", note=note)
        if hasattr(self.broker, "settle"):
            self.broker.settle(prices)
        self._save()

    def _save(self) -> None:
        # `state()` is the reader-facing shape in BOTH modes (see BookBroker.state);
        # `ledger_state()` is what actually reloads, so it has to be written too.
        self._state["broker"] = self.broker.state()
        if hasattr(self.broker, "ledger_state"):
            self._state["stock_ledger"] = self.broker.ledger_state()
        # AFTER the refresh: broker.state() rebuilds the positions list, so
        # marks written before this line are silently discarded.
        if getattr(self, "_mark_prices", None):
            self._stamp_marks(self._mark_prices)
        self._state["ts"] = datetime.now(timezone.utc).isoformat()
        try:
            atomic.write_json(self.path, self._state, indent=1)
        except OSError:
            return
        if self._migration:
            self._log("migrated_to_shared_account", **self._migration)
            self._migration = None

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
              labels: dict | None = None, regime: str = "neutral",
              risk: float = 0.0, winter: bool = False) -> dict:
        """shock_assets: brain state["shock_assets"] — FRESH impacts only.
        risk: the brain's live risk-field value (R38 leverage gate input).
        winter: BTC under its 100d average (R39 shorts gate input)."""
        labels = labels or {}
        opened, closed = [], []
        # Orders the venue acknowledged but had not confirmed when a previous
        # cycle ended. Resolved FIRST, before anything reads a position: a fill
        # from three cycles ago is part of this book, and an exit decision taken
        # without it is taken on a book that does not exist. No-op unless the
        # shared account is on and something is actually outstanding.
        for note in (self.broker.resolve_pending()
                     if hasattr(self.broker, "resolve_pending") else []):
            self._log("pending", note=note)
            print(f"  [event sleeve] {note}")
        held = self._state.setdefault("held", {})     # sym -> {entry, opened_iso, bars}
        # WHAT THIS BOOK HAS ALREADY ACTED ON: filled positions plus orders still
        # in flight. Computed once, here, because three separate decisions below
        # need the same answer and the last time this book asked the question two
        # different ways it bought USO twice.
        in_flight = (self.broker.pending_symbols()
                     if hasattr(self.broker, "pending_symbols") else set())
        open_syms = ({p.asset.symbol for p in self.broker.get_positions().values()}
                     | in_flight)
        # `held` records an INTENT, and an intent can die. An entry marked
        # pending whose order is neither filled nor still in flight was refused,
        # cancelled or expired at the close — it must stop barring its symbol, or
        # a trade that never happened bars the name for good. Written as an
        # invariant rather than an event handler so it also heals an order
        # cancelled by hand at the venue.
        for sym in [s for s, m in list(held.items())
                    if (m or {}).get("pending") and s not in open_syms]:
            held.pop(sym, None)
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
            short = pos.qty < 0
            move = ((pos.avg_price - px) if short else (px - pos.avg_price)) / pos.avg_price
            age = len([d for d in days if d >= meta.get("opened_day", today)]) - 1
            reason = None
            if move <= -HARD_STOP:
                reason = f"hard stop {move*100:+.1f}%"
            elif age >= EVENT_HOLD_DAYS:
                reason = f"clock {age}d {move*100:+.1f}%"
            if reason:
                entry = pos.avg_price
                o = self.broker.submit(Order(pos.asset, Side.BUY if short else Side.SELL,
                                             abs(pos.qty),
                                             reason=f"event sleeve: {reason}"), px)
                filled = float(o.filled_qty or 0.0)
                if filled <= 0:
                    # THE EXIT DID NOT HAPPEN. A real venue acknowledges an order
                    # without filling it, so this used to be safe only because the
                    # simulator could not fail: the old code dropped `held[sym]`,
                    # settled the learning spine and announced a close on the
                    # strength of having ASKED. Against Longbridge that forgets a
                    # position the book still owns — and a forgotten position has
                    # no stop and no clock. Keep it; the exit re-fires next cycle
                    # because the conditions above have not changed.
                    # WHY `waiting` EXISTS. An exit whose own earlier sell is
                    # still resting at the venue re-fires every cycle and is
                    # correctly capped by the double-sell guard
                    # (brokers/shared: "sell capped at its own claim of 0
                    # share(s)"). That is the system working — the shares are
                    # promised to an order that has not been answered yet, and
                    # selling them twice would take the account short or through
                    # another book's position.
                    #
                    # But it is indistinguishable, in the log, from an exit that
                    # is genuinely failing. On 2026-08-21 three clock exits
                    # (EWY/NVDA/TSM) were submitted at 00:07 UTC against a US
                    # session that opens at 13:30, and the resulting ~29
                    # `exit_unfilled` lines per symbol read as a broken exit path
                    # on the one book with a demonstrated edge. It cost a real
                    # investigation to establish that nothing was wrong.
                    promised = 0.0
                    try:
                        promised = self.broker.pending_qty(
                            pos.asset.key, Side.SELL)          # type: ignore[attr-defined]
                    except Exception:
                        pass
                    self._log("exit_unfilled", symbol=pos.asset.symbol, price=px,
                              requested_qty=round(abs(pos.qty), 6), reason=reason,
                              detail=(o.reason or "no fill"),
                              waiting=bool(promised > 1e-9),
                              promised_qty=round(promised, 6) or None)
                    continue
                pnl = (px - entry) * (filled if not short else -filled)
                settled = (self.ledger.settle("event", pos.asset.symbol, move,
                                              held_days=age, exit_reason=reason)
                           if self.ledger else None)
                self._log("sell", symbol=pos.asset.symbol, price=px,
                          qty=round(filled, 6), requested_qty=round(abs(pos.qty), 6),
                          entry=round(entry, 6), pnl=round(pnl, 2),
                          ret=round(move, 4), held_days=age, reason=reason,
                          shock=meta.get("shock"),
                          **({"expected": settled["expected_move"],
                              "ratio": settled["ratio"],
                              "score": settled["score"]} if settled else {}))
                held.pop(pos.asset.symbol, None)
                closed.append((pos.asset.symbol, reason, move))
                if notifier:
                    notifier.send(f"⚡️ *Event sleeve — closed {labels.get(pos.asset.symbol, pos.asset.symbol)}*"
                                  f" ({pos.asset.symbol}): {reason} ({self._money()}).")

        # 2) entries — biggest fresh shocks above the floor. Long only by
        # default; negative shocks become shorts only when EVENT_SHORT is on
        # AND (winter, unless the winter gate is explicitly removed).
        # IN-FLIGHT ORDERS OCCUPY A SLOT. Counting only filled positions is what
        # let the sleeve hold ten orders against a three-position limit on
        # 2026-08-17: Longbridge answers `NotReported` to anything submitted
        # outside US market hours, so nothing filled, so every cycle believed all
        # three slots were free and spent the book again.
        room = max(0, EVENT_N - len(open_syms))
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
            # ...and `open_syms` (computed at the top of this method) now covers
            # orders still in flight as well, for the same reason and with the
            # same consequence: NVDA and AMD were each ordered twice within 45
            # minutes on 2026-08-17 because a queued order is not a position.
            shorts_ok = EVENT_SHORT and (winter or not EVENT_SHORT_WINTER)
            cands = []
            for sym, row in (shock_assets or {}).items():
                if "/" in sym:
                    # STOCKS ONLY — crypto shocks belong to crypto_event_sleeve.py,
                    # not this book's 3 slots and $10k. See module docstring.
                    continue
                im = float(row.get("impact", 0.0))
                px = prices_by_sym.get(sym, 0.0)
                if px <= 0 or sym in open_syms or sym in held:
                    continue
                if im < EVENT_MIN and not (shorts_ok and im <= -EVENT_MIN):
                    continue
                cands.append((abs(im), im, sym, row))
            cands.sort(reverse=True)
            trust = self.ledger.size_multiplier("event", regime) if self.ledger else 1.0
            # R38: leverage is a fair-weather tool — gear only while the risk
            # field holds at/above the gate; in stress the sleeve is unlevered.
            eff_lev = EVENT_LEV if (EVENT_LEV > 1.0 and risk >= EVENT_LEV_GATE) else 1.0
            for _, im, sym, row in cands[:room]:
                notional = min(eq * trust * eff_lev / max(1, EVENT_N),
                               self.broker.get_cash() * 0.9)
                if notional < 500:
                    continue
                px = prices_by_sym[sym]
                asset = _asset(sym, self.settings.crypto_exchange)
                qty = notional / px
                if asset.asset_class is AssetClass.STOCK:
                    # WHOLE SHARES, AT THE SIZER (2026-08-16). `notional / px` is
                    # a raw float and always was: the sleeve "bought" 0.71 shares
                    # of NVDA and the simulator happily filled it. A real venue
                    # truncates to `int(qty)` and rejects at zero, so a sub-share
                    # entry is not a small position — it is a reject, repeated
                    # every cycle the shock persists. Floor here, where the
                    # refusal can be explained, rather than at the adapter where
                    # it can only be counted.
                    # Board lots where the market has them (HK trades in 100s
                    # and 500s), whole shares where it does not. `_lot` is 1 for
                    # US listings and for any book with no lot table attached.
                    lot = (self.broker._lot(sym)
                           if hasattr(self.broker, "_lot") else 1)
                    qty = float(math.floor(qty / lot) * lot) if lot >= 1 else 0.0
                    if qty < max(1, lot):
                        self._log("rejected", symbol=sym, price=round(px, 6),
                                  requested_qty=round(notional / px, 6),
                                  notional=round(notional, 2), shock=round(im, 4),
                                  lot=lot,
                                  reason=(f"floors to 0 {'whole shares' if lot == 1 else f'lots of {lot}'} — one "
                                          f"{'share' if lot == 1 else 'lot'} costs "
                                          f"${px * max(1, lot):,.2f}, slice is ${notional:,.0f}"))
                        continue
                o = self.broker.submit(
                    Order(asset, Side.BUY if im > 0 else Side.SELL, qty,
                          reason=f"event sleeve: fresh shock {im:+.3f}"), px)
                if not o.filled_qty:
                    # An entry that did not happen is information. Until now this
                    # path was silent, so "why did the sleeve skip that shock" had
                    # no answer anywhere — investor.py has logged its refusals
                    # since it was written and this file never did.
                    #
                    # PENDING IS NOT REJECTED. The venue took the order and has
                    # not answered yet; calling that a refusal in the record
                    # reads as "the sleeve declined this shock" when in fact it
                    # has money committed to it. Ten of these were journalled as
                    # rejections on 2026-08-17 while $33,946 sat queued.
                    submitted = o.status is OrderStatus.PENDING
                    self._log("submitted" if submitted else "rejected",
                              symbol=sym, price=round(px, 6),
                              requested_qty=round(qty, 6), shock=round(im, 4),
                              notional=round(notional, 2),
                              order_id=(o.id or None) if submitted else None,
                              reason=(o.reason or ("awaiting the venue" if submitted
                                                   else "no fill")))
                    if submitted:
                        # It occupies a slot and its cash from here on, so record
                        # the intent now rather than when it fills — otherwise the
                        # clock and the stop start from whenever the venue gets
                        # round to it.
                        held.setdefault(sym, {"entry": px, "opened_day": today,
                                              "shock": round(im, 4), "pending": True})
                if o.filled_qty:
                    notional = float(o.filled_qty) * float(o.filled_price or px)
                    held[sym] = {"entry": float(o.filled_price or px),
                                 "opened_day": today, "shock": round(im, 4)}
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
                            f"or on a 10% stop — whichever comes first ({self._money()}).")
        # Fold this cycle's closes into realised P&L and re-baseline the marks.
        # Once, after all trading, before anything reports equity — the same
        # placement and the same reason as the trading book's own ledger call.
        for note in (self.broker.drain_notes()
                     if hasattr(self.broker, "drain_notes") else []):
            self._log("shared_account", note=note)
            print(f"  [event sleeve] {note}")
        if hasattr(self.broker, "settle"):
            booked = self.broker.settle(prices_by_sym)
            if abs(booked) > 0.005:
                self._log("realised", pnl=round(booked, 2),
                          total=round(self.broker.ledger.realized, 2),
                          fees=round(self.broker.ledger.fees, 2))
        eqnow = self._equity(prices_by_sym)
        if self._state.get("last_mark") != today:
            self._state["last_mark"] = today
            self._log("mark", equity=round(eqnow, 2), cash=round(self.broker.get_cash(), 2),
                      positions=len(self.broker.get_positions()),
                      **self._basis_fields())
        self._mark_prices = prices_by_sym
        self._save()
        return {"opened": opened, "closed": closed,
                "equity": round(self._equity(prices_by_sym), 2),
                "cash": round(self.broker.get_cash(), 2),
                "positions": len(self.broker.get_positions())}
