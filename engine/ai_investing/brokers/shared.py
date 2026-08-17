"""One real Longbridge account, shared safely by several independent books.

THE PROBLEM
-----------
This engine runs four books, each with its own capital pool, its own state file
and its own strategy. Longbridge has no concept of a book: one account, one cash
balance, one blended position per symbol. Ask it "how much NVDA does the event
sleeve hold" and there is no answer — only "the account holds 40 NVDA", which is
the sleeve's 10 plus the trading book's 30, indistinguishable.

Sharing an account naively therefore breaks in two directions at once. Every
book reads the blended total as its own, so each one thinks it holds 40 NVDA and
each one books the others' P&L. And every book can sell shares it never bought,
because a SELL of 40 is a perfectly valid order against an account that holds
40 — the trading book's position is closed by the sleeve's exit and neither one
notices.

There is no second account to escape into: Longbridge's dashboard only toggles
between the one demo account and the real funded one. And a funded account will
be exactly one account too, so this has to be solved regardless. Solving it here,
against the demo account, is the cheap version of a problem that otherwise gets
solved for the first time with real money.

THE RULES
---------
1. A book only ever SEES its own claimed positions, held locally in its own
   `BookLedger`. A raw read of the shared account is never a book's own view.
2. A book only ever SELLS what it has locally claimed.
3. Stock SHORTS are refused entirely while the account is shared — see
   `SHORTS_REFUSED` below, this one is subtle and cost the design a rewrite.
4. Real account cash is consulted fresh before every buy, as a hard ceiling on
   top of the book's own ceiling.

Rule 4 is safe without any locking because every book in this engine executes
strictly sequentially, in one thread, inside one `Runner.run_cycle()` call —
verified: there is no threading, multiprocessing or file locking anywhere in
this codebase. By the time book N submits an order, Longbridge's own
`get_cash()` already reflects every fill the earlier books made this cycle.

ONE POT PER BOOK, NOT TWO
-------------------------
A book trades stocks AND crypto (the sleeve reacts to `UNI/USD` shocks the same
way it reacts to `NVDA` ones), but only stocks can go to Longbridge. The obvious
split — keep the old `PaperBroker` for crypto, add a ledger for stocks — quietly
DOUBLES the book's capital: a $100k sleeve becomes a $100k crypto pot plus a
$100k stock pot, and `EventSleeve` sizes entries at `equity / EVENT_N`, so every
position doubles too.

So there is one `BookLedger` per book covering both asset classes, and cash is
`base + realized + adjust - fees - Σ(avg·qty)` across all of them — one pot,
exactly as before. Stock orders go to the real venue; crypto orders fill locally
at the reference price, which is what they already did.

ASYNCHRONOUS FILLS
------------------
`LongbridgeBroker.submit()` honours the contract in `brokers/base.py`: it polls
briefly and returns PENDING rather than inventing a fill. That is correct, and it
is also the one thing that would otherwise make local claims drift permanently —
an order that returns PENDING and fills a minute later is real shares the book
never claimed, which reconciliation would then report as drift forever.

So pending orders are PERSISTED with their venue order id and re-queried at the
start of every cycle (`resolve_pending`). A late fill lands in the book that
placed it, deterministically, because the order id is the attribution. This is
the piece that makes the whole design survive contact with a real venue.
"""
from __future__ import annotations

import math
import os
from datetime import datetime, timezone

from ai_investing.brokers.base import BrokerAdapter
from ai_investing.execution import fees as fee_model
from ai_investing.execution.capital import BookLedger, asset_from_mark
from ai_investing.models import AssetClass, Order, OrderStatus, OrderType, Position, Side

# A stock short is refused, not merely capped, while the account is shared.
#
# Rule 2 ("sell only what you claim") looks like it covers this and does not. At
# the venue, "book A opens a 10-share NVDA short" and "book A sells book B's 10
# NVDA" are THE SAME ORDER — a sell of 10 against an account holding 10. The
# account nets to flat, B's position is gone, and B's ledger still claims it.
# Nothing errors; the two books simply disagree with reality until the next
# reconciliation halts trading.
#
# Netting-aware shorting (allow it only while the sum of all books' claims stays
# non-negative) is possible but needs every book to read every other book's state
# at submit time, and gets the answer wrong the moment one of them is mid-cycle.
# Refusing is honest and cheap. Crypto shorts are unaffected: those fill locally
# against a pot nobody else touches.
SHORTS_REFUSED = ("shared account: stock shorts are disabled — a short is "
                  "indistinguishable from selling another book's shares")

# How long a venue order may sit unresolved before it is worth mentioning.
# Longbridge day orders expire at the close, so this is a symptom-of-trouble
# threshold, not a timeout: nothing is ever abandoned on age alone, because an
# abandoned claim is exactly the permanent drift this machinery exists to stop.
PENDING_WARN_SECONDS = float(os.environ.get("SHARED_PENDING_WARN_SECONDS", "7200"))


def routes_to_venue(asset, base_currency: str = "USD") -> bool:
    """Can this asset actually be sent to the shared account?

    USD-listed stocks only — the same rule, for the same two reasons, that
    `Runner._live_universe()` already applies to the trading book: Longbridge's
    symbol format only round-trips cleanly for `.US` names, and `cost_price`
    arrives in the LISTING currency while every price in this engine is
    USD-normalised, so an HK position would mix HKD into a USD book.

    This is NOT a detail that could be left out. The investing book holds
    `PRX.AS` (Amsterdam), `2331.HK` and `2097.HK` (Hong Kong) right now. The
    trading book has been fenced off from those since `_live_universe()` was
    written; a book that reached the venue without the same fence would send
    them, and the first symptom would be either a rejected order or — worse — a
    filled one whose cost basis is in the wrong currency.

    Anything that does not route stays SIMULATED locally, exactly as today. The
    alternative, refusing it, would silently delete this book's ability to hold a
    European or Hong Kong thesis, which is not a change this work is entitled to
    make.
    """
    if asset.asset_class is not AssetClass.STOCK:
        return False
    try:
        from ai_investing.data.fx import currency_of
        return currency_of(asset.symbol, "stock") == base_currency
    except Exception:                                             # noqa: BLE001
        # Cannot tell => do not send it. A locally simulated position is a
        # reversible mistake; a real order in the wrong currency is not.
        return False


class BookBroker(BrokerAdapter):
    """A `BrokerAdapter` scoped to ONE book, over a shared real stock account.

    Drop-in for `PaperBroker` from a strategy's point of view: same four methods,
    same `Position` dict keyed by `Asset.key`. What changes is where the truth
    lives — in this book's own `BookLedger` rather than in a private simulator.
    """

    name = "book"

    def __init__(self, book_id: str, ledger: BookLedger,
                 stock_broker: BrokerAdapter | None = None,
                 pending: list | None = None, allow_short: bool = False,
                 base_currency: str = "USD"):
        self.book_id = book_id
        self.ledger = ledger
        self.base_currency = base_currency
        # Applies to CRYPTO only. Stock shorts are refused unconditionally while
        # the account is shared — see SHORTS_REFUSED.
        self.allow_short = allow_short
        # The ONE shared real stock broker instance, or None to keep stocks
        # simulated (the flag-off path, and every unit test that isn't about the
        # venue). A book with no stock broker is a paper book with better
        # accounting, which is a useful thing to be able to run.
        self.stock_broker = stock_broker
        self.live = bool(getattr(stock_broker, "live", False))
        # The working view. Seeded from the ledger's marks (these books are
        # rebuilt from disk every cycle, so this is the only restore path) and
        # mutated by fills as the cycle runs. `ledger.marks` itself is touched
        # ONLY by `BookLedger.observe()`, once per cycle, via `settle()`.
        self._working: dict[str, Position] = ledger.positions()
        self.pending: list[dict] = [dict(p) for p in (pending or [])]
        self.notes: list[str] = []
        # Keys touched by the most recent `resolve_pending()`. A late fill changes
        # the book without any order having been placed THIS cycle, which reads
        # as drift to a naive snapshot comparison — the runner uses this to
        # re-baseline exactly those keys and no others.
        self.resolved_keys: set[str] = set()
        # Symbols whose in-flight order ended with NOTHING filled — refused,
        # cancelled, or expired at the close. A strategy that recorded an intent
        # when it submitted has to be told to forget it, or the symbol stays
        # blocked by a trade that never happened.
        self.dropped_symbols: set[str] = set()

    # -- the BrokerAdapter surface ------------------------------------------
    def get_positions(self) -> dict[str, Position]:
        return {k: p for k, p in self._working.items() if abs(p.qty) > 1e-9}

    def get_cash(self) -> float:
        """SPENDABLE cash — the ledger's, less what live orders have already
        committed.

        The distinction is the whole ballgame and its absence nearly cost the
        event sleeve its book. Longbridge answers an order placed outside US
        market hours with `NotReported`: queued, not filled, not rejected. That
        is honestly PENDING, so no position is claimed and the ledger does not
        move — and the ledger is what this used to return. So the book reported
        its full cash again on the very next cycle, and again, and again, and
        every one of those cycles was free to spend it a second time.

        On 2026-08-17 the sleeve held $7,612 and had $33,946 of queued buy
        orders against it — 4.46x a book whose docstring says LONG ONLY AND
        UNLEVERED — waiting for the opening bell to all fill at once.

        Cash committed to a live order is not cash. Equity therefore reads low
        by the committed amount while orders are in flight; that is the
        conservative direction, it is visible in `pending_commitment()`, and it
        resolves the moment the venue answers.
        """
        return self.ledger.book_portfolio(self.get_positions()).cash - self.pending_commitment()

    def pending_commitment(self) -> float:
        """Cash promised to buy orders the venue has taken but not yet answered."""
        return sum(float(p.get("qty", 0.0)) * float(p.get("price", 0.0))
                   for p in self.pending if p.get("side") == Side.BUY.value)

    def pending_symbols(self) -> set[str]:
        """Symbols with an order in flight.

        A strategy asking "do I already hold this?" is really asking "have I
        already acted on this?", and between submitting and filling those differ.
        Every re-entry guard in this engine was written against positions alone,
        so while an order sat queued the same shock re-qualified the same symbol
        every cycle: NVDA and AMD were each ordered twice within 45 minutes.
        """
        return {str(p.get("symbol")) for p in self.pending if p.get("symbol")}

    def working_positions(self) -> dict[str, Position]:
        """This book's claim on the shared account. Feed to `reconcile_claims`."""
        return dict(self.get_positions())

    def submit(self, order: Order, price: float) -> Order:
        if order.qty <= 0 or price <= 0 or not math.isfinite(price):
            order.status = OrderStatus.REJECTED
            order.reason = (order.reason + " | invalid price/qty").strip(" |")
            return order
        if (self.stock_broker is None
                or not routes_to_venue(order.asset, self.base_currency)):
            return self._simulate(order, price)
        return self._submit_stock(order, price)

    # -- stocks: the real, shared venue -------------------------------------
    def _submit_stock(self, order: Order, price: float) -> Order:
        key = order.asset.key
        held = self._working.get(key)
        held_qty = float(held.qty) if held else 0.0

        # Whole shares, floored. Floored and not rounded: rounding UP invents
        # shares the cash ceilings below were never checked against, and the
        # venue truncates anyway (`live.py`: `qty = int(order.qty)`), so anything
        # this layer does not floor gets floored silently one layer down where
        # nobody can see it.
        qty = math.floor(order.qty)
        if qty < 1:
            order.status = OrderStatus.REJECTED
            order.reason = (order.reason + f" | floors to 0 whole shares "
                                           f"(wanted {order.qty:.4f})").strip(" |")
            return order

        if order.side is Side.BUY:
            # Ceiling 1: this book's own cash. Without it a book spends the
            # account's money rather than its own allocation.
            own = self.get_cash()
            if price * qty > own:
                qty = math.floor(max(0.0, own) / price)
            if qty < 1:
                order.status = OrderStatus.REJECTED
                order.reason = (order.reason + f" | insufficient {self.book_id} "
                                               f"cash (${own:,.2f})").strip(" |")
                return order
            # Ceiling 2: the real account, read fresh. The books' ceilings can
            # sum to more than the account actually holds — after losses, or a
            # withdrawal — and this is what stops the last book to trade from
            # finding out the hard way.
            try:
                real = float(self.stock_broker.get_cash())
            except Exception as exc:                              # noqa: BLE001
                order.status = OrderStatus.REJECTED
                order.reason = (order.reason + f" | cannot read shared account "
                                               f"cash: {exc}").strip(" |")
                return order
            if price * qty > real:
                qty = math.floor(max(0.0, real) / price)
                self.notes.append(
                    f"{self.book_id}: {order.asset.symbol} buy trimmed to {qty} "
                    f"share(s) by shared-account cash (${real:,.2f})")
            if qty < 1:
                order.status = OrderStatus.REJECTED
                order.reason = (order.reason + f" | shared account cash exhausted "
                                               f"(${real:,.2f})").strip(" |")
                return order
        else:  # SELL
            if held_qty <= 1e-9:
                order.status = OrderStatus.REJECTED
                order.reason = (order.reason + " | " + SHORTS_REFUSED).strip(" |")
                return order
            # Cap at the claim. A book that asks to sell more than it holds is
            # reaching into another book's position, whether it means to or not.
            capped = min(qty, math.floor(held_qty))
            if capped < qty:
                self.notes.append(
                    f"{self.book_id}: {order.asset.symbol} sell capped at its own "
                    f"claim of {capped} share(s), asked {qty}")
            qty = capped
            if qty < 1:
                order.status = OrderStatus.REJECTED
                order.reason = (order.reason + f" | {self.book_id} claims no "
                                               f"{key} to sell").strip(" |")
                return order

        order.qty = float(qty)
        result = self.stock_broker.submit(order, price)

        if result.status is OrderStatus.FILLED and (result.filled_qty or 0) > 0:
            self._apply_fill(result, price)
        elif result.status is OrderStatus.PENDING and result.id:
            # Acknowledged but unconfirmed. Remember it so the fill lands in THIS
            # book when it comes, however many cycles later that is.
            self.pending.append({
                "id": str(result.id), "key": key,
                "symbol": order.asset.symbol,
                "asset_class": order.asset.asset_class.value,
                "exchange": order.asset.exchange, "quote": order.asset.quote,
                "side": order.side.value, "qty": float(qty),
                "price": float(price), "filled_qty": 0.0,
                "ts": datetime.now(timezone.utc).isoformat(), "checks": 0})
        return result

    # -- crypto (and the flag-off path): fill locally at the reference price --
    def _simulate(self, order: Order, price: float) -> Order:
        """The old `PaperBroker` behaviour, accounted through the ledger.

        Deliberately NOT delegated to `PaperBroker`: that class owns its own cash
        pot, and a second pot is the double-counting this module exists to avoid.
        Cash here is always `ledger.book_portfolio(...).cash`.
        """
        if order.order_type is OrderType.LIMIT and order.limit_price is not None:
            if (order.side is Side.BUY and price > order.limit_price) or \
               (order.side is Side.SELL and price < order.limit_price):
                order.status = OrderStatus.REJECTED
                order.reason = (order.reason + " | limit not reached").strip(" |")
                return order

        key = order.asset.key
        pos = self._working.get(key)
        held = float(pos.qty) if pos else 0.0
        qty = float(order.qty)

        if order.side is Side.BUY:
            cash = self.get_cash()
            if price * qty > cash + 1e-6:
                qty = max(0.0, cash) / price          # shrink to fit, as before
            if qty <= 1e-9:
                order.status = OrderStatus.REJECTED
                order.reason = (order.reason + " | insufficient cash").strip(" |")
                return order
        else:
            # Crypto shorting stays available (the investing book expresses a
            # bubble thesis that way) — it is a local pot, so rule 3 does not
            # apply. Closing more than is held is still capped.
            if not self.allow_short:
                qty = min(qty, max(0.0, held))
            if qty <= 1e-9:
                order.status = OrderStatus.REJECTED
                order.reason = (order.reason + " | nothing to sell").strip(" |")
                return order

        order.qty = qty
        order.filled_qty = qty
        order.filled_price = price
        order.status = OrderStatus.FILLED
        self._apply_fill(order, price, charge_fees=False)
        return order

    # -- fills ---------------------------------------------------------------
    def _apply_fill(self, order: Order, price: float, charge_fees: bool = True) -> None:
        key = order.asset.key
        px = float(order.filled_price or price)
        filled = float(order.filled_qty or 0.0)
        if filled <= 0 or px <= 0:
            return
        signed = filled if order.side is Side.BUY else -filled
        if charge_fees:
            self.ledger.charge(fee_model.fill_fee(order.side, filled, px))

        pos = self._working.get(key)
        if pos is None:
            self._working[key] = Position(order.asset, signed, px)
            return
        new_qty = pos.qty + signed
        if abs(new_qty) < 1e-9:
            # Drop it rather than leave a qty=0 tombstone: `observe()` skips
            # zero-qty entries anyway, but a persisted tombstone makes every
            # reader that COUNTS positions overstate the book. (paper.py carries
            # the same fix and the same scar.)
            self._working.pop(key, None)
        elif (pos.qty > 0) == (signed > 0):
            # Adding to the same side: blend the cost basis.
            pos.avg_price = (pos.avg_price * pos.qty + px * signed) / new_qty
            pos.qty = new_qty
        else:
            # Reducing (or flipping): the OLD basis has to survive until
            # `observe()` books the P&L against it. Overwriting it here would
            # book every exit as flat.
            pos.qty = new_qty

    # -- late fills ----------------------------------------------------------
    def drain_notes(self) -> list[str]:
        """Everything worth saying since the last drain, and clear it.

        The rules in `submit()` are silent by construction — an order trimmed
        from 50 shares to 25 by the shared account's cash still returns FILLED,
        and the journal records the 25 as though 25 were what was wanted. These
        notes are the difference between the two, which is the only evidence that
        the books are competing for the same money.
        """
        out, self.notes = list(self.notes), []
        return out

    def resolve_pending(self) -> list[str]:
        """Re-query every unconfirmed order and apply whatever actually happened.

        Called at the START of a cycle, before the strategy looks at its
        positions — so a fill from three cycles ago is part of the book before
        anything decides what to do next.
        """
        self.resolved_keys, self.dropped_symbols = set(), set()
        if not self.pending or self.stock_broker is None:
            return []
        still: list[dict] = []
        out: list[str] = []
        for rec in self.pending:
            before = len(still)
            note = self._resolve_one(rec, still)
            if note:
                out.append(note)
            # The age warning lives HERE, not inside `_resolve_one`, because it
            # applies to every record that SURVIVES — including the one that
            # survived because the venue could not be reached, which is the case
            # most worth hearing about and the one the old placement skipped.
            if len(still) > before:
                stuck = self._age_note(still[-1])
                if stuck:
                    out.append(stuck)
        self.pending = still
        return out

    def _age_note(self, rec: dict) -> str | None:
        """Say it ONCE. This fired on every poll past the threshold and wrote 209
        journal lines about nine orders in a single evening — the same
        alert-fatigue failure that buried the crash-loop diagnosis in STATE
        §4.16. An order sitting queued is a STATE; announce it when it becomes
        true, not for as long as it stays true."""
        if rec.get("warned"):
            return None
        age = _age_seconds(rec.get("ts"))
        if age is None or age <= PENDING_WARN_SECONDS:
            return None
        rec["warned"] = True
        return (f"{self.book_id}: order {rec['id']} ({rec['symbol']} "
                f"{rec['side']} {rec['qty']:g}) still unresolved after "
                f"{age / 3600:.1f}h — its cash stays committed until it settles")

    def _resolve_one(self, rec: dict, still: list[dict]) -> str | None:
        rec["checks"] = int(rec.get("checks", 0)) + 1
        try:
            got = self.stock_broker.fetch_fill(rec["id"])
        except Exception as exc:                                  # noqa: BLE001
            still.append(rec)
            return (f"{self.book_id}: order {rec['id']} ({rec['symbol']}) could not "
                    f"be checked: {type(exc).__name__}: {exc}")
        if got is None:
            still.append(rec)
            return None
        status, qty, px = got
        s = str(status or "").split(".")[-1].lower()
        try:
            cum = float(qty or 0.0)
        except (TypeError, ValueError):
            cum = 0.0
        try:
            px = float(px or 0.0)
        except (TypeError, ValueError):
            px = 0.0

        # The venue reports CUMULATIVE executed quantity, so book only the delta.
        # A partial that fills further over three cycles must not be booked three
        # times over.
        new = cum - float(rec.get("filled_qty", 0.0) or 0.0)
        if new > 1e-9:
            asset = asset_from_mark(rec["key"], rec)
            side = Side.BUY if rec["side"] == Side.BUY.value else Side.SELL
            fill = Order(asset, side, new, status=OrderStatus.FILLED,
                         filled_qty=new,
                         filled_price=px if px > 0 else float(rec["price"]),
                         reason="late fill (resolved from pending)")
            self._apply_fill(fill, float(rec["price"]))
            rec["filled_qty"] = cum
            self.resolved_keys.add(rec["key"])

        if s == "filled" or (new > 1e-9 and cum >= float(rec["qty"]) - 1e-9):
            return (f"{self.book_id}: late fill {rec['symbol']} {rec['side']} "
                    f"{cum:g} @ {px or rec['price']:.4f} (order {rec['id']})")
        if s in ("rejected", "canceled", "cancelled", "expired"):
            if new > 1e-9 or cum > 1e-9:
                return (f"{self.book_id}: {rec['symbol']} partially filled {cum:g} "
                        f"of {rec['qty']:g} then {s} (order {rec['id']})")
            # A clean reject claims nothing — and releases everything: the cash it
            # had committed, and the strategy's record of having acted on this
            # name. Without the second, a Day order that simply expired unfilled
            # would bar its symbol from the book for good.
            self.dropped_symbols.add(str(rec.get("symbol")))
            return (f"{self.book_id}: {rec['symbol']} {rec['side']} {rec['qty']:g} "
                    f"{s} unfilled — cash released (order {rec['id']})")
        still.append(rec)          # still working; the age warning is in the caller
        return None

    # -- end of cycle --------------------------------------------------------
    def settle(self, prices_by_symbol: dict) -> float:
        """Fold this cycle's closes into realised P&L and re-baseline the marks.

        Once per cycle, AFTER trading, BEFORE saving. `BookLedger.observe()` keys
        prices by POSITION KEY while every strategy here carries them by SYMBOL,
        which is exactly the mismatch that made the sleeve's re-entry guard a
        no-op for the life of the project — so the translation happens here, once,
        rather than at each call site.
        """
        positions = self.get_positions()
        prices = {}
        for key, pos in positions.items():
            px = (prices_by_symbol or {}).get(pos.asset.symbol)
            if px:
                prices[key] = px
        # Marks for positions that are GONE this cycle still need a price to book
        # the P&L against, and they are no longer in `positions`.
        for key, m in (self.ledger.marks or {}).items():
            if key in prices:
                continue
            px = (prices_by_symbol or {}).get(
                m.get("symbol") or asset_from_mark(key, m).symbol)
            if px:
                prices[key] = px
        return self.ledger.observe(positions, prices)

    def ledger_state(self) -> dict:
        """THE authoritative record — everything needed to rebuild this book."""
        return {"ledger": self.ledger.to_dict(), "pending": self.pending}

    def state(self) -> dict:
        """The same book in `PaperBroker.state()`'s shape, FOR READERS ONLY.

        The Telegram portfolio view, the dashboard and each book's own
        `_stamp_marks()` all read `state["broker"]["positions"]`. Switching a
        book's storage format would break every one of them silently — they would
        find no positions and report a book that holds nothing, which is the most
        dangerous possible way to be wrong. So the reader-facing shape is kept
        exactly, and the real record lives beside it under `stock_ledger`.

        Never load from this. `ledger_state()` is the one that round-trips.
        """
        return {"cash": self.get_cash(), "positions": [
            {"symbol": p.asset.symbol, "asset_class": p.asset.asset_class.value,
             "exchange": p.asset.exchange, "quote": p.asset.quote,
             "qty": p.qty, "avg_price": p.avg_price}
            for p in self.get_positions().values()]}


def _age_seconds(ts) -> float | None:
    try:
        then = datetime.fromisoformat(str(ts))
    except (TypeError, ValueError):
        return None
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - then).total_seconds()


# -- construction and one-time migration --------------------------------------
def migrate_paper_state(paper: dict | None, base: float,
                        base_currency: str = "USD") -> tuple[BookLedger, dict]:
    """Turn a book's old `PaperBroker` state into its first `BookLedger`.

    Positions that will now become REAL are dropped, not carried over. They were
    bought at whatever price a simulator was handed, fractionally, with no fees,
    no lot size and no market-hours check — the event sleeve's NVDA/TSM/AMD were
    bought on a Sunday. Making those real retroactively would put shares in a
    real account that no real order ever bought, and would hand the book a cost
    basis it never paid. They are closed at their own cost basis, so the book's
    CASH is exactly preserved and no fictional profit or loss is ever booked.

    Everything that STAYS simulated carries over untouched — crypto, and any
    stock that cannot reach the venue (`routes_to_venue`: the investing book's
    `PRX.AS`, `2331.HK`, `2097.HK`). Closing those would be destroying live
    theses to celebrate a bookkeeping change; nothing about them is changing
    except which file records them.

    Whatever cash the old book had is preserved to the cent through `adjust`,
    which is deliberately not `realized` — see `BookLedger.adjust`. A migration is
    an accounting change, and a book whose track record jumps because its
    bookkeeping changed has no track record.
    """
    from ai_investing.models import Asset

    paper = paper or {}
    cash = float(paper.get("cash", 0.0) or 0.0)
    marks, closed, cost_kept, freed = {}, [], 0.0, 0.0
    for p in paper.get("positions") or []:
        try:
            qty, avg = float(p["qty"]), float(p["avg_price"])
            cls = AssetClass(p["asset_class"])
            sym = p["symbol"]
        except (KeyError, TypeError, ValueError):
            continue
        if abs(qty) <= 1e-9:
            continue
        exchange = p.get("exchange", "") or ""
        quote = p.get("quote", "USD") or "USD"
        if routes_to_venue(Asset(sym, cls, exchange=exchange, quote=quote), base_currency):
            freed += avg * qty                      # closed at cost: P&L exactly 0
            closed.append({"symbol": sym, "qty": qty,
                           "avg_price": avg, "notional": round(avg * qty, 2)})
            continue
        marks[f"{cls.value}:{sym}"] = {
            "qty": qty, "avg": avg, "symbol": sym, "asset_class": cls.value,
            "exchange": exchange, "quote": quote}
        cost_kept += avg * qty

    target_cash = cash + freed
    ledger = BookLedger(base=float(base), realized=0.0, marks=marks,
                        adjust=target_cash + cost_kept - float(base))
    note = {"closed_simulated_stock": closed,
            "cash_before": round(cash, 2), "cash_after": round(target_cash, 2),
            "carried_simulated": sorted(marks), "adjust": round(ledger.adjust, 2)}
    return ledger, note


def build_book_broker(book_id: str, settings, state: dict, base_cash: float,
                      allow_short: bool = False,
                      stock_broker: BrokerAdapter | None = None):
    """The one place a book decides what kind of broker it has.

    Returns `(broker, migration_note_or_None)`. With `SHARED_STOCK_ACCOUNT` off
    this hands back the same `PaperBroker` the book has always had, loaded from
    the same state key — so the flag-off path is byte-for-byte the old behaviour
    and the change can be deployed before it is turned on.
    """
    from ai_investing.brokers.paper import PaperBroker

    if not getattr(settings, "shared_stock_account", False):
        if state.get("broker"):
            return PaperBroker.from_state(state["broker"], allow_short=allow_short), None
        return PaperBroker(float(base_cash), allow_short=allow_short), None

    saved = state.get("stock_ledger") or {}
    note, pending = None, []
    if saved.get("ledger"):
        ledger = BookLedger.from_dict(saved["ledger"], float(base_cash))
        pending = saved.get("pending") or []
    elif state.get("broker"):
        # There is a simulated book to carry over. Only here — a book with no
        # prior state has nothing to migrate, and running the migration on it
        # anyway computed `adjust = 0 - base` and started the book at zero cash.
        ledger, note = migrate_paper_state(
            state["broker"], float(base_cash),
            getattr(settings, "base_currency", "USD"))
    else:
        ledger = BookLedger(base=float(base_cash))
    return BookBroker(book_id, ledger, stock_broker=stock_broker,
                      pending=pending, allow_short=allow_short,
                      base_currency=getattr(settings, "base_currency", "USD")), note


# -- aggregate reconciliation ------------------------------------------------
def reconcile_claims(claims_by_book: dict[str, dict[str, Position]],
                     real_positions: dict[str, Position],
                     tol: float = 1e-3, base_currency: str = "USD") -> list[str]:
    """Do the books' claims add up to what the account actually holds?

    The per-book rules keep each book honest about ITSELF. This is the only check
    that can catch the failures that live between books, or outside them: a
    manual trade in the Longbridge app, a late fill attributed to nobody, a book
    that crashed mid-cycle with its state half-written.

    Only keys that can actually REACH the account are compared. Crypto never
    does, and neither does a non-USD listing (`routes_to_venue`) — the investing
    book's `2331.HK` is simulated locally, so the account correctly holds none of
    it and treating that as drift would halt the engine every cycle, forever, on
    a position working exactly as designed.

    Returns human-readable drift lines, empty when everything agrees.
    """
    def _stock(d):
        return {k: p for k, p in (d or {}).items()
                if str(k).startswith("stock:") and routes_to_venue(p.asset, base_currency)}

    real = _stock(real_positions)
    claims = {b: _stock(c) for b, c in (claims_by_book or {}).items()}
    keys = set(real) | {k for c in claims.values() for k in c}
    drift: list[str] = []
    for key in sorted(keys):
        claimed = sum(float(c[key].qty) for c in claims.values() if key in c)
        actual = float(real[key].qty) if key in real else 0.0
        if abs(claimed - actual) > max(tol, 1e-3 * abs(actual)):
            per_book = {b: round(float(c[key].qty), 4)
                        for b, c in claims.items() if key in c}
            drift.append(f"{key}: books claim {claimed:.4f} total {per_book or '{}'}, "
                         f"account holds {actual:.4f}")
    return drift
