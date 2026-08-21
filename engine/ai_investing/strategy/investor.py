"""The INVESTING book: a separate long-term paper portfolio driven by the
6-month strategy, managed once a day.

Two books, two hats:
  ⚡ trading book  — the existing engine: days-to-weeks, ATR stops, formula.
  🏛 investing book — THIS: positions that express the strategist's theses,
     entered only with the user's approval, held for months, exited when the
     thesis dies (revised away / dropped) or a wide safety stop trips.

Money: its own paper pot (INVEST_STARTING_CASH, default $100k) so the two
styles can be compared honestly. Shorting is allowed here — an "overvalued /
bubble" thesis is expressed as a short position.

Approval flow: entries go through the same ProposalBook / Telegram buttons
as the trading book (horizon="long"), one message per stock. Exits are
automatic — a dead thesis or a tripped stop doesn't wait for a human — but
every exit is reported.
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timedelta, timezone

from ai_investing.brokers.shared import build_book_broker
from ai_investing.util import atomic
from ai_investing.execution.approvals import ProposalBook
from ai_investing.strategy.booklog import BookBasisMixin
from ai_investing.models import Asset, AssetClass, Order, Side, mark_price

STOP_PCT = 0.10            # HARD RULE (user): max 10% loss on any investment
MAX_WEIGHT = 0.12          # target weight per position in the investing pot
import os as _os
CASH_RESERVE = max(0.0, min(0.6, float(_os.environ.get("INVEST_CASH_RESERVE", "0.25"))))
# dry powder: this fraction of the pot stays in cash no matter how many
# proposals get approved — future opportunities always have budget


def _today_sgt() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=8)).date().isoformat()


def _asset(symbol: str, crypto_exchange: str = "") -> Asset:
    if "/" in symbol:
        return Asset(symbol, AssetClass.CRYPTO, exchange=crypto_exchange)
    return Asset(symbol, AssetClass.STOCK)


class Investor(BookBasisMixin):
    def __init__(self, settings, stock_broker=None, lots=None):
        """`stock_broker` is the ONE shared live stock adapter, or None — see
        `EventSleeve.__init__` for why None is the normal case."""
        self.settings = settings
        data_dir = os.path.dirname(os.path.abspath(settings.state_path))
        self.path = os.path.join(data_dir, "invest_state.json")
        # The forward record. This book was the ONLY one of the four that wrote
        # no trade journal: the trading book records to journal.db `orders`, the
        # sleeve and crypto book to their own jsonl, and this one submitted the
        # order, sent a Telegram message, and kept nothing. The cost showed up
        # on 2026-08-10 as a realised -$11.32 that reconciled arithmetically and
        # could not be attributed to any trade, because no record of any exit
        # existed anywhere. Equity was never wrong; it was simply unauditable,
        # which is the same problem one step removed.
        self.journal = os.path.join(data_dir, "invest_journal.jsonl")
        self._state = self._load()
        self.broker, self._migration = build_book_broker(
            "investor", settings, self._state,
            float(getattr(settings, "invest_starting_cash", 100000.0)),
            allow_short=True, stock_broker=stock_broker, lots=lots)
        # Journalled by `_save()`, once actually PERSISTED. `daily_manage()`
        # returns early when the day is already managed — before any save — so
        # logging here records a migration that was computed and discarded, and
        # then `_mark_books` does it again. Two lines, one book; seen for real
        # on the 2026-08-16 cutover.

    def _load(self) -> dict:
        try:
            with open(self.path) as fh:
                return json.load(fh)
        except (OSError, json.JSONDecodeError):
            return {}

    def _log(self, event: str, **kw) -> None:
        """Append one line to the forward record. Never fatal: a book that
        cannot write its journal must still be able to exit a position, so a
        failure here costs the record and not the trade."""
        try:
            with open(self.journal, "a") as fh:
                fh.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(),
                                     "event": event, **kw}) + "\n")
        except OSError:
            pass

    def _stamp_marks(self, prices: dict) -> None:
        """Persist equity and per-position marks alongside the book.

        Readers only get the state file. Cash alone is misleading once a book
        holds shorts — short proceeds sit in cash that is still owed — so the
        value has to be written by whoever has the prices, which is here.
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

        Also the only every-cycle path, so — as in the sleeve — this is where
        late fills are picked up and realised P&L is booked. `daily_manage()`
        runs at most once per SGT day; an order that fills an hour after it
        returns must not wait until tomorrow to be claimed.
        """
        self._mark_prices = prices
        for note in (self.broker.resolve_pending()
                     if hasattr(self.broker, "resolve_pending") else []):
            self._log("pending", note=note)
        if hasattr(self.broker, "settle"):
            self.broker.settle(prices)
        self._save()
        # One equity line per day, matching the sleeve and crypto book. Marking
        # runs every cycle (~288/day), so logging each one would bury the trades
        # this file exists to record. Written after _save() so it reports the
        # equity that was actually persisted, not a recomputation of it.
        today = _today_sgt()
        if self._state.get("last_mark_day") != today:
            self._state["last_mark_day"] = today
            b = self._state.get("broker") or {}
            self._log("mark", equity=self._state.get("equity"),
                      cash=round(float(b.get("cash", 0.0)), 2),
                      positions=len(b.get("positions") or []),
                      stale_marks=self._state.get("stale_marks"),
                      **self._basis_fields())
            # PERSIST THE GATE (2026-08-12). last_mark_day was set on the
            # in-memory state AFTER the only _save() in this method, so it
            # reached disk solely if some later call happened to save. Across a
            # restart the flag was lost and the day re-logged; when no later save
            # came, the day was skipped. Both happened: in the eight days after
            # go-live this book wrote 3 mark lines to crypto's 12, double-logging
            # 08-10 and missing 08-12. The crypto book never had the bug because
            # it saves last. Save again here — cheap, once a day, and it makes
            # the journal the reliable daily series everything downstream
            # (correlation, per-book Sharpe, rebalancing) has to be built on.
            self._save()
            self._save()

    def _money(self) -> str:
        """See `EventSleeve._money` — "(pretend money)" must not survive the
        switch to a real venue."""
        return ("real orders on the shared account"
                if getattr(self.broker, "live", False) else "pretend money")

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
        atomic.write_json(self.path, self._state, indent=1)
        if self._migration:
            self._log("migrated_to_shared_account", **self._migration)
            self._migration = None

    # ------------------------------------------------------------------ core --
    def daily_manage(self, prices_by_symbol: dict[str, float], strat: dict,
                     notifier, labels: dict[str, str] | None = None) -> None:
        """Runs at most once per SGT day: exits first, then approved entries,
        then new proposals for unexpressed theses."""
        if self._state.get("last_managed") == _today_sgt():
            return
        labels = labels or {}
        # Late fills first, before any exit decision reads a position — see
        # `mark()`. A no-op unless the shared account is on and something from a
        # previous run is still outstanding.
        for note in (self.broker.resolve_pending()
                     if hasattr(self.broker, "resolve_pending") else []):
            self._log("pending", note=note)
            print(f"  [investor] {note}")
        book = ProposalBook(self.settings.proposals_path, ttl_hours=48)   # long book: 2 days to answer

        # which symbols the CURRENT strategy wants, and in which direction
        want: dict[str, dict] = {}
        for t in strat.get("theses", []):
            if t.get("stance") not in ("long", "short"):
                continue
            for sym in (t.get("symbols") or [])[:3]:
                want[sym] = t

        # 1) exits: thesis gone, or wide stop tripped — automatic, reported
        for key, pos in list(self.broker.get_positions().items()):
            sym = pos.asset.symbol
            px = prices_by_symbol.get(sym, 0.0)
            if px <= 0:
                continue
            direction = 1 if pos.qty > 0 else -1
            move = (px - pos.avg_price) / pos.avg_price * direction
            t = want.get(sym)
            wrong_side = t is not None and ((t["stance"] == "long") != (pos.qty > 0))
            reason = None
            if t is None or wrong_side:
                reason = "the thesis behind this position was revised away or dropped"
            elif move <= -STOP_PCT:
                reason = f"safety stop: {move:.0%} against us"
            if reason:
                side = Side.SELL if pos.qty > 0 else Side.BUY
                qty_closed = abs(pos.qty)
                entry = pos.avg_price
                o = self.broker.submit(Order(pos.asset, side, qty_closed, reason=reason), px)
                filled = float(o.filled_qty or 0.0)
                if filled <= 0:
                    # The venue took the order and has not filled it (or refused
                    # it). Announcing a close that did not happen loses the
                    # position: it would still be held, still be unstopped, and
                    # the daily gate means nothing would look at it again until
                    # tomorrow. Record the miss and leave the position alone —
                    # the same exit condition re-fires on the next run.
                    self._log("exit_unfilled", symbol=sym, price=round(px, 6),
                              requested_qty=round(qty_closed, 6), reason=reason,
                              detail=(o.reason or "no fill"),
                              side=("sell" if side is Side.SELL else "buy"))
                    notifier.send(f"🏛 *Investing book — could NOT close "
                                  f"{labels.get(sym, sym)}* ({sym}): {o.reason or 'no fill'}. "
                                  f"Still holding; it will retry.")
                    continue
                pnl = (px - entry) * (filled if pos.qty > 0 else -filled)
                # Journalled BEFORE the notifier, and with the fill rather than the
                # request: a partial close that reported a full one is exactly the
                # fabrication §4.15 found in the live adapter. `entry` is captured
                # above because submit() mutates the position out from under us.
                self._log("sell", symbol=sym, qty=round(filled, 6),
                          price=round(px, 6), entry=round(entry, 6),
                          pnl=round(pnl, 2),
                          ret=round((px - entry) / entry * direction, 4) if entry else None,
                          reason=reason, requested_qty=round(qty_closed, 6),
                          side=("sell" if side is Side.SELL else "buy"))
                notifier.send(f"🏛 *Investing book — closed {labels.get(sym, sym)}* ({sym}): {reason}. "
                              f"P&L ${pnl:,.0f} ({self._money()}).")

        # 2) execute entries you approved
        for sym, t in want.items():
            px = prices_by_symbol.get(sym, 0.0)
            if px <= 0 or self._held(sym):
                continue
            p = book.get(sym, "buy" if t["stance"] == "long" else "sell", "long")
            if p and p["status"] == "approved":
                book.consume(p["id"])
                qty = p.get("qty") or (self._equity(prices_by_symbol) * MAX_WEIGHT / px)
                side = Side.BUY if t["stance"] == "long" else Side.SELL
                self._open(sym, side, qty, px, t, notifier, labels, prices_by_symbol)

        # 3) propose entries for theses not yet expressed — one message per stock.
        # Budget-aware: never queue more buying than the pot's cash can honor.
        from ai_investing.execution.explain import graph_map_notes
        map_notes = graph_map_notes(
            self.settings,
            [(s, "buy" if t["stance"] == "long" else "sell") for s, t in want.items()
             if not self._held(s)])
        equity = self._equity(prices_by_symbol)
        budget = self.broker.get_cash()
        for p in book.pending():                          # cash already spoken for
            if p.get("horizon") == "long" and p["side"] == "buy":
                budget -= p.get("qty", 0) * p.get("price", 0)
        try:
            from ai_investing.data.fundamentals import get_fundamentals, quality_value
            fund = get_fundamentals(self.settings, list(want))
        except Exception:
            fund, quality_value = {}, None
        for sym, t in want.items():
            px = prices_by_symbol.get(sym, 0.0)
            if px <= 0 or self._held(sym):
                continue
            side = "buy" if t["stance"] == "long" else "sell"
            if book.get(sym, side, "long"):
                continue                                   # pending/decided already
            # margin of safety: quality-at-a-fair-price sizes up, junk sizes down
            qv, qv_reason = (quality_value(fund.get(sym, {})) if quality_value
                             else (0.5, ""))
            size_mult = 0.6 + 0.8 * qv                     # ×0.6 … ×1.4 of base weight
            weight = min(0.15, MAX_WEIGHT * size_mult)
            target = equity * weight
            if side == "buy":
                if budget < max(500.0, target * 0.25):
                    continue                               # pot is (nearly) fully invested
                target = min(target, budget)
                budget -= target
            qty = target / px
            name = labels.get(sym, sym)
            verb = "Buy and hold" if side == "buy" else "Bet against (short)"
            extra = {
                "horizon": "long", "label": name,
                "notional": round(qty * px, 2), "pct": round(weight, 4),
                "quality_note": (f"📏 Sized ×{size_mult:.1f}: {qv_reason}" if qv_reason else ""),
                "why": f"{t.get('thesis', '')}",
                "assumptions": t.get("assumptions", ""),
                "plan": (f"Hold for months while the thesis holds — this is the patient book. "
                         f"It exits automatically if the thesis is dropped in a daily challenge "
                         f"or if the price moves {STOP_PCT:.0%} against us."),
            }
            if side == "buy":
                try:
                    from ai_investing.brain.bubble import bubble_scores
                    b = bubble_scores(self.settings).get("symbols", {}).get(sym, 0.0)
                    if b >= 0.4:
                        extra["bubble_note"] = (f"🫧 Heads-up: my bubble indicator scores {name} "
                                                f"at {b:.2f}/1 — priced on story more than "
                                                f"earnings. A 6-month hold here needs conviction.")
                except Exception:
                    pass
            if map_notes.get(sym):
                extra["map_note"] = map_notes[sym]
            # AUTONOMY (2026-08-05). This book had NO trade_approval check: it only
            # ever executed a proposal the user had tapped `approved`. So when
            # TRADE_APPROVAL was set to false, three books went autonomous and this
            # one silently kept waiting for taps that were no longer coming — it
            # could not open a position at all, while still asking permission on
            # Telegram. Missed because only the 📈 book's path was checked.
            if not self.settings.trade_approval:
                self._open(sym, side, qty, px, t, notifier, labels, prices_by_symbol)
                continue

            p = book.propose(sym, side, qty, px, f"thesis: {t.get('title', '')}", extra)
            notifier.send(
                f"🏛 *Investing book — approval needed* ({self._money()})\n\n"
                f"*{verb}: {name}* ({sym}) — about *${qty * px:,.0f}* "
                f"({weight:.0%} of the investing pot)\n"
                f"📜 *Thesis “{t.get('title')}”:* {extra['why']}\n"
                f"🤔 {extra['assumptions']}\n"
                + (extra["quality_note"] + "\n" if extra.get("quality_note") else "")
                + f"🗺 {extra['plan']}\n"
                + (extra["map_note"] + "\n" if extra.get("map_note") else "")
                + (extra["bubble_note"] if extra.get("bubble_note") else ""),
                [[(f"✅ yes, {('buy' if side == 'buy' else 'short')} {sym}", f"ap:{p['id']}"),
                  ("❌ skip", f"rj:{p['id']}"),
                  ("🚫 never", f"b:{sym}")]])

        # Book this run's closes into realised P&L before the state is written.
        for note in (self.broker.drain_notes()
                     if hasattr(self.broker, "drain_notes") else []):
            self._log("shared_account", note=note)
            print(f"  [investor] {note}")
        if hasattr(self.broker, "settle"):
            booked = self.broker.settle(prices_by_symbol)
            if abs(booked) > 0.005:
                self._log("realised", pnl=round(booked, 2),
                          total=round(self.broker.ledger.realized, 2),
                          fees=round(self.broker.ledger.fees, 2))
        self._state["last_managed"] = _today_sgt()
        self._save()

    # --------------------------------------------------------------- helpers --
    def _open(self, sym: str, side, qty: float, px: float, thesis: dict,
              notifier, labels: dict, prices_by_symbol: dict) -> bool:
        """Open a thesis position, honouring the dry-powder reserve.

        Shared by the approved-proposal path and the autonomous path so the two
        cannot drift apart on the reserve rule — the kind of duplication that let
        the sleeve's entry and exit paths disagree about symbol keys for the life of
        the project.

        `side` may be a Side or the strings "buy"/"sell"; both callers exist.
        """
        s = Side.BUY if side in (Side.BUY, "buy") else Side.SELL
        asset = _asset(sym, self.settings.crypto_exchange)
        equity = self._equity(prices_by_symbol)
        # DRY-POWDER RESERVE: never let buying drain the pot — keep CASH_RESERVE of
        # equity liquid so the NEXT good thesis has budget. Buys shrink to fit;
        # buys scaled below the minimum are skipped, not forced.
        if s is Side.BUY:
            spendable = self.broker.get_cash() - CASH_RESERVE * equity
            if spendable < px * qty:
                qty = max(0.0, spendable) / px
            if qty * px < 500:
                # Journalled as well as announced. This is the COMMON refusal —
                # it fires whenever the pot is deployed — and it returns before
                # the broker is ever asked, so without a line here the record
                # would show a thesis the book simply never acted on, with no
                # trace of the reserve being the reason.
                self._log("rejected", symbol=sym, price=round(px, 6),
                          requested_qty=round(qty, 6),
                          side=("buy" if s is Side.BUY else "sell"),
                          reason=f"cash reserve floor ({CASH_RESERVE:.0%} stays liquid)",
                          spendable=round(spendable, 2),
                          thesis=str(thesis.get("title", ""))[:120])
                notifier.send(f"🏛 *Investing book — skipped {labels.get(sym, sym)}* "
                              f"({sym}): cash reserve floor "
                              f"({CASH_RESERVE:.0%} of the pot stays liquid for "
                              f"future opportunities). It can re-propose after an exit.")
                return False
        # WHOLE SHARES (2026-08-16). Both callers reach the broker through here —
        # the approved-proposal path and the autonomous path — so the floor goes
        # here once rather than at each of them, for the same reason the reserve
        # rule does. A real venue truncates to `int(qty)` and rejects at zero, so
        # a sub-share order is a reject that repeats daily, not a small position.
        requested = qty
        if asset.asset_class is AssetClass.STOCK:
            # Board lots where the market has them; 1 for US and for any book
            # with no lot table. See brokers/lots.py.
            lot = self.broker._lot(sym) if hasattr(self.broker, "_lot") else 1
            qty = float(math.floor(qty / lot) * lot) if lot >= 1 else 0.0
            if qty < max(1, lot):
                self._log("rejected", symbol=sym, price=round(px, 6),
                          requested_qty=round(requested, 6), lot=lot,
                          side=("buy" if s is Side.BUY else "sell"),
                          reason=(f"floors to 0 {'whole shares' if lot == 1 else f'lots of {lot}'} — "
                                  f"one {'share' if lot == 1 else 'lot'} costs "
                                  f"${px * max(1, lot):,.2f}"),
                          thesis=str(thesis.get("title", ""))[:120])
                return False
        o = self.broker.submit(Order(asset, s, qty,
                                     reason=f"thesis: {thesis.get('title', '')}"), px)
        if not (o.filled_qty or 0) > 0:
            # A rejected entry is recorded too. An entry that never happened is
            # information -- the dry-powder floor and the paper broker's
            # insufficient-cash path both refuse silently otherwise, and "why did
            # it not take that thesis" has no answer without this line.
            self._log("rejected", symbol=sym, price=round(px, 6),
                      requested_qty=round(qty, 6),
                      side=("buy" if s is Side.BUY else "sell"),
                      reason=(o.reason or "no fill"),
                      thesis=str(thesis.get("title", ""))[:120])
            return False
        filled = float(o.filled_qty or 0.0)
        fill_px = float(o.filled_price or px)
        self._log("buy" if s is Side.BUY else "short", symbol=sym,
                  qty=round(filled, 6), price=round(fill_px, 6),
                  notional=round(filled * fill_px, 2),
                  requested_qty=round(requested, 6),
                  thesis=str(thesis.get("title", ""))[:120])
        verb = "Bought" if s is Side.BUY else "Shorted"
        # The notional ACTUALLY filled, not the one asked for. Against a real
        # venue those differ — the size can be trimmed by the shared account's
        # cash or floored to whole shares — and the message is the only thing
        # most of these trades are ever read through.
        notifier.send(f"🏛 *Investing book — {verb} {labels.get(sym, sym)}* ({sym}), "
                      f"~${filled * fill_px:,.0f}, under thesis “{thesis.get('title')}”. "
                      f"Held while the thesis holds; wide {STOP_PCT:.0%} safety stop "
                      f"({self._money()}).")
        return True

    def _held(self, symbol: str) -> bool:
        """Have we already acted on this symbol — position OR order in flight?

        Positions alone is the wrong test once orders are real. Between
        submitting and filling the two differ, and Longbridge leaves an order
        submitted outside US market hours as `NotReported` for hours. Every
        caller of this gates an entry on it, so a fill-only answer re-proposes
        and re-buys the same name every day the order sits queued.
        """
        if any(p.asset.symbol == symbol and abs(p.qty) > 1e-9
               for p in self.broker.get_positions().values()):
            return True
        pend = getattr(self.broker, "pending_symbols", None)
        return bool(pend and symbol in pend())

    def _equity(self, prices_by_symbol: dict[str, float]) -> float:
        eq = self.broker.get_cash()
        for p in self.broker.get_positions().values():
            # the dict-default only covered a MISSING symbol; a present-but-zero
            # or NaN price sailed through and valued the position at nothing
            eq += p.qty * mark_price(prices_by_symbol.get(p.asset.symbol), p.avg_price)
        return eq

    def summary(self, prices_by_symbol: dict[str, float]) -> dict:
        return {
            "equity": round(self._equity(prices_by_symbol), 2),
            "cash": round(self.broker.get_cash(), 2),
            "positions": [
                {"symbol": p.asset.symbol, "qty": round(p.qty, 4),
                 "avg_price": round(p.avg_price, 4),
                 "pnl": round((mark_price(prices_by_symbol.get(p.asset.symbol),
                                          p.avg_price) - p.avg_price) * p.qty, 2)}
                for p in self.broker.get_positions().values()],
        }
