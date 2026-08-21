"""The ₿ crypto book — crypto traded on its own, 24/7, by its own policy.

Crypto never closes, so this book runs on EVERY engine cycle rather than on the
stock market's clock. It is the live implementation of the crypto configuration
the walk-forward gauntlet actually adopted (runs 10-12), so what trades here is
what was tested — not a fresh improvisation:

  MANDATE (pinned, not searchable)
    - 20% HODL core, majors only (BTC/ETH/SOL). Alts stay SIGNAL-ONLY: the
      graph watches them, the book does not buy them (R27, adopted 5x).
    - tactical sleeve capped at 70% of the book; the rest is dry powder.
    - LONG ONLY. Shorts were rejected six independent times (R8/R21/R37...).
    - 10% hard stop on every position (user rule), checked every cycle —
      including weekends, which is when crypto crashes.

  THE BEAR EXIT (R28 — the reason the crypto book survived the lockbox at
  -1% while BTC fell 42%). Four independent evidence streams:
      winter    : BTC below its 100-day average
      liquidity : stablecoin supply contracting over 30d
      vol       : Deribit DVOL spiking >1.5 sigma
      flows     : spot-ETF 5-day net flow strongly negative
  Two or more firing => liquidate the tactical sleeve to cash (stables) and
  trim the HODL core by 80%. Recovery redeploys. Cash IS a position.

  SIZING: vol-targeted (R32) — position scales with target_vol / realized_vol,
  so the book trades smaller when crypto is wild and larger when it is calm.

Everything is recorded: every fill and every daily equity mark is appended to
data/crypto_journal.jsonl so the forward record can be measured honestly.
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone

from ai_investing.brokers.paper import PaperBroker
from ai_investing.util import atomic
from ai_investing.strategy.booklog import BookBasisMixin
from ai_investing.models import Asset, AssetClass, Order, Side, mark_price

MAJORS = ("BTC/USD", "ETH/USD", "SOL/USD")
HODL_FRAC = 0.20               # pinned by the user's crypto mandate
TACT_CAP = 0.70                # tactical sleeve ceiling
HARD_STOP = 0.10               # user rule: max 10% loss on any position
TAKE = 0.12                    # tactical take-profit (tact_take, adopted)
HOLD_DAYS = 5                  # tactical max hold (tact_hold, adopted)
ENTRY_MIN = 0.10               # field impact needed to open a tactical long
GAIN = 0.4                     # crypto_gain (adopted)
VOL_TARGET = 0.024             # R32 vol-targeted sizing
BEAR_K = 2                     # evidence streams needed to cash out (R28)
HODL_TRIM = 0.80               # fraction of the core sold in a bear
START_CASH = float(os.environ.get("CRYPTO_START_CASH", "100000"))


def _hist(settings, name: str):
    """Read a crypto history series from THIS BOOK'S data directory.

    Resolved from `settings.state_path`, exactly as `crypto_state.json` is a
    few lines below. It used to be hardcoded to the repo's real `data/` via a
    chain of `dirname()` calls, which ignored settings completely and had two
    consequences:

      * No test could control it. `test_crypto_book.py` redirected state_path
        into a temp dir and still read the LIVE market history, so whether the
        bear-exit test passed depended on the real stablecoin supply. It passed
        on the dev box (a stale snapshot showing supply draining -> 2 signals)
        and failed on the ProDesk (live data -> 1 signal), and on either machine
        it could flip on any day the market moved. Found 2026-08-05 (§4.21).
      * Two books could never read different histories, because the path could
        not be pointed anywhere.

    A component that reads from a path its caller cannot set is not testable and
    not configurable, and those are the same defect.
    """
    d = os.path.dirname(os.path.abspath(settings.state_path))
    try:
        with open(os.path.join(d, "crypto_history", name)) as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


class CryptoBook(BookBasisMixin):
    def __init__(self, settings):
        self.settings = settings
        d = os.path.dirname(os.path.abspath(settings.state_path))
        self.path = os.path.join(d, "crypto_state.json")
        self.journal = os.path.join(d, "crypto_journal.jsonl")
        self._state = self._load()
        if getattr(settings, "crypto_book_live", False):
            from ai_investing.brokers.live import BinanceFuturesBroker
            self.broker = BinanceFuturesBroker(settings)
        else:
            b = self._state.get("broker")
            self.broker = PaperBroker.from_state(b) if b else PaperBroker(START_CASH)
        try:                       # expectation ledger: claim -> outcome -> learn
            from ai_investing.learning.spine import LearningSpine
            self.ledger = LearningSpine(settings)
        except Exception:
            self.ledger = None

    # -- persistence ---------------------------------------------------------
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
        venue_equity = self.broker.get_equity()
        self._state["equity"] = (round(venue_equity, 2) if venue_equity is not None
                                 else round(float(b.get("cash", 0.0)) + mv, 2))
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
        # A live broker's positions live at the exchange, not here — nothing to
        # persist for restart, and re-hydrating them from a stale local
        # snapshot on the next restart would fight the venue's own view of the
        # account. `snapshot()` is used instead of `state()`: read fresh from
        # the venue every save, purely so `_stamp_marks` below (dashboards,
        # equity marks) sees real numbers rather than an empty positions list
        # — it is never fed back into `from_state()`.
        if hasattr(self.broker, "state"):
            self._state["broker"] = self.broker.state()
        else:
            self._state["broker"] = self.broker.snapshot()
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

    def equity(self, prices: dict) -> float:
        venue_equity = self.broker.get_equity()
        if venue_equity is not None:
            return venue_equity
        eq = self.broker.get_cash()
        for p in self.broker.get_positions().values():
            px = prices.get(p.asset.symbol, 0.0)
            if px > 0:
                eq += p.qty * px
        return eq

    # -- the four bear-evidence streams (R28) --------------------------------
    def bear_evidence(self, bars_by_sym: dict) -> tuple[int, list]:
        fired = []
        bars = bars_by_sym.get("BTC/USD") or []
        if len(bars) >= 100:
            closes = [b.close for b in bars[-100:]]
            if bars[-1].close < sum(closes) / len(closes):
                fired.append("winter (BTC < 100d)")
        rows = _hist(self.settings, "stablecoins_daily.json")
        if rows and len(rows) > 31:
            now_, then = rows[-1]["usd_bn"], rows[-31]["usd_bn"]
            if then and (now_ / then - 1.0) < -0.01:
                fired.append("stablecoin supply draining")
        dv = _hist(self.settings, "dvol_btc.json")
        if dv and len(dv) > 90:
            xs = [r["close"] for r in dv[-90:]]
            mu = sum(xs) / len(xs)
            sd = (sum((x - mu) ** 2 for x in xs) / max(1, len(xs) - 1)) ** 0.5
            if sd > 1e-9 and (xs[-1] - mu) / sd > 1.5:
                fired.append("implied vol spiking")
        etf = _hist(self.settings, "btc_etf_flows.json")
        if etf and len(etf) >= 5:
            tot = 0.0
            for row in etf[-5:]:
                try:
                    tot += float(str(row[-1]).replace(",", ""))
                except (ValueError, IndexError):
                    pass
            if tot < -300:
                fired.append("ETF outflows")
        return len(fired), fired

    # -- one pass, every cycle, 24/7 -----------------------------------------
    def cycle(self, brain_assets: dict, bars_by_sym: dict, prices: dict,
              notifier=None) -> dict:
        held = self._state.setdefault("held", {})
        today = datetime.now(timezone.utc).date().isoformat()
        days = self._state.setdefault("days", [])
        if today not in days:
            days.append(today)
            self._state["days"] = days[-60:]
        n_bear, why = self.bear_evidence(bars_by_sym)
        bear = n_bear >= BEAR_K
        try:
            from ai_investing.learning.spine import regime_of
            regime = regime_of(None, bear=bear)
        except Exception:
            regime = "neutral"
        opened, closed = [], []

        def sell(sym, qty, px, reason):
            pos = self.broker.get_positions().get(f"crypto:{sym}") or \
                  next((p for k, p in self.broker.get_positions().items()
                        if p.asset.symbol == sym), None)
            if pos is None or qty <= 0:
                return
            entry = pos.avg_price
            pnl = (px - entry) * qty
            ret = (px / entry - 1.0) if entry else 0.0
            settled = None
            if self.ledger and held.get(sym, {}).get("kind") == "tact":
                settled = self.ledger.settle("crypto_tact", sym, ret,
                                             held_days=len([d for d in days
                                                            if d >= held.get(sym, {}).get("day", today)]) - 1,
                                             exit_reason=reason)
            self.broker.submit(Order(pos.asset, Side.SELL, qty, reason=reason), px)
            closed.append((sym, reason))
            self._log("sell", symbol=sym, qty=round(qty, 6), price=px, entry=round(entry, 6),
                      pnl=round(pnl, 2), ret=round(ret, 4), reason=reason,
                      kind=held.get(sym, {}).get("kind", "?"),
                      held_days=len([d for d in days if d >= held.get(sym, {}).get("day", today)]) - 1,
                      **({"expected": settled["expected_move"], "ratio": settled["ratio"],
                          "score": settled["score"]} if settled else {}))
            if notifier:
                notifier.send(f"₿ *Crypto book — sold {sym}*: {reason} (pretend money).")

        # 1) HARD STOP first — every cycle, weekends included
        for key, pos in list(self.broker.get_positions().items()):
            sym = pos.asset.symbol
            px = prices.get(sym, 0.0)
            if px <= 0 or pos.qty <= 0:
                continue
            if (px - pos.avg_price) / pos.avg_price <= -HARD_STOP:
                sell(sym, pos.qty, px, f"hard stop -{HARD_STOP:.0%}")
                held.pop(sym, None)

        # 2) BEAR EXIT — liquidate tactical, trim the core, sit in cash
        if bear and not self._state.get("bear_mode"):
            for key, pos in list(self.broker.get_positions().items()):
                sym = pos.asset.symbol
                px = prices.get(sym, 0.0)
                if px <= 0 or pos.qty <= 0:
                    continue
                meta = held.get(sym, {})
                qty = pos.qty if meta.get("kind") == "tact" else pos.qty * HODL_TRIM
                sell(sym, qty, px, f"bear exit ({n_bear}/4: {', '.join(why)})")
                if meta.get("kind") == "tact":
                    held.pop(sym, None)
            self._state["bear_mode"] = True
            if notifier:
                notifier.send(f"₿ *Crypto book — BEAR EXIT.* {n_bear} of 4 signals "
                              f"firing ({', '.join(why)}). Tactical sleeve sold, core "
                              f"trimmed {HODL_TRIM:.0%}; holding cash/stables until it clears.")
        elif not bear and self._state.get("bear_mode"):
            self._state["bear_mode"] = False
            if notifier:
                notifier.send("₿ *Crypto book — bear signals cleared.* Rebuilding the "
                              "HODL core; tactical trading resumes.")

        eq = self.equity(prices)

        # 3) HODL core — majors only, restored when not in a bear
        if not bear:
            per = HODL_FRAC * eq / len(MAJORS)
            for sym in MAJORS:
                px = prices.get(sym, 0.0)
                if px <= 0:
                    continue
                cur = next((p.qty * px for p in self.broker.get_positions().values()
                            if p.asset.symbol == sym and held.get(sym, {}).get("kind") == "hodl"), 0.0)
                gap = per - cur
                if gap > max(500.0, 0.02 * eq) and self.broker.get_cash() > gap:
                    o = self.broker.submit(Order(Asset(sym, AssetClass.CRYPTO,
                                                       exchange=self.settings.crypto_exchange),
                                                 Side.BUY, gap / px, reason="HODL core"), px)
                    if o.filled_qty:
                        held[sym] = {"kind": "hodl", "day": today}
                        opened.append((sym, "hodl", gap))
                        self._log("buy", symbol=sym, kind="hodl", qty=round(o.filled_qty, 6),
                                  price=px, notional=round(gap, 2))

        # 4) TACTICAL sleeve — field-driven, vol-sized, time-boxed
        tact_val = sum(p.qty * mark_price(prices.get(p.asset.symbol), p.avg_price)
                       for p in self.broker.get_positions().values()
                       if held.get(p.asset.symbol, {}).get("kind") == "tact")
        for key, pos in list(self.broker.get_positions().items()):
            sym = pos.asset.symbol
            meta = held.get(sym, {})
            if meta.get("kind") != "tact":
                continue
            px = prices.get(sym, 0.0)
            if px <= 0:
                continue
            move = (px - pos.avg_price) / pos.avg_price
            age = len([d for d in days if d >= meta.get("day", today)]) - 1
            imp = float((brain_assets.get(sym) or {}).get("impact", 0.0))
            reason = None
            if move >= TAKE:
                reason = f"take +{move:.1%}"
            elif age >= HOLD_DAYS:
                reason = f"clock {age}d {move:+.1%}"
            elif imp < -0.05:
                reason = f"signal flipped ({imp:+.2f})"
            if reason:
                sell(sym, pos.qty, px, reason)
                held.pop(sym, None)

        if not bear:
            for sym in MAJORS:
                px = prices.get(sym, 0.0)
                if px <= 0 or held.get(sym, {}).get("kind") == "tact":
                    continue
                imp = float((brain_assets.get(sym) or {}).get("impact", 0.0))
                if imp < ENTRY_MIN:
                    continue
                bars = bars_by_sym.get(sym) or []
                trust = self.ledger.size_multiplier("crypto_tact", regime) if self.ledger else 1.0
                notional = GAIN * imp * eq * 0.4 * trust
                rv_daily = 0.03
                if len(bars) >= 21:                       # vol-targeted sizing (R32)
                    rets = [(bars[i].close / bars[i - 1].close - 1.0)
                            for i in range(-20, 0) if bars[i - 1].close]
                    mu = sum(rets) / max(1, len(rets))
                    rv = (sum((r - mu) ** 2 for r in rets) / max(1, len(rets) - 1)) ** 0.5
                    if rv > 1e-6:
                        rv_daily = rv
                        notional *= max(0.3, min(2.0, VOL_TARGET / rv))
                room = TACT_CAP * eq - tact_val
                notional = min(notional, room, self.broker.get_cash() * 0.9)
                if notional < 500:
                    continue
                o = self.broker.submit(Order(Asset(sym, AssetClass.CRYPTO,
                                                   exchange=self.settings.crypto_exchange),
                                             Side.BUY, notional / px,
                                             reason=f"tactical: field {imp:+.2f}"), px)
                if o.filled_qty:
                    held[sym] = {"kind": "tact", "day": today}
                    tact_val += notional
                    opened.append((sym, "tact", notional))
                    self._log("buy", symbol=sym, kind="tact", qty=round(o.filled_qty, 6),
                              price=px, notional=round(notional, 2), impact=round(imp, 3),
                              size_mult=round(trust, 3))
                    if self.ledger:
                        self.ledger.record("crypto_tact", sym, 1, imp, rv_daily,
                                           HOLD_DAYS, regime=regime,
                                           driver="crypto_field", notional=notional)
                    if notifier:
                        notifier.send(f"₿ *Crypto book — bought {sym}* ~${notional:,.0f} "
                                      f"(web signal {imp:+.2f}). Take +{TAKE:.0%}, "
                                      f"{HOLD_DAYS}-day clock, 10% stop (pretend money).")

        eq = self.equity(prices)
        last_mark = self._state.get("last_mark_day")
        if last_mark != today:                      # one equity mark per day
            self._state["last_mark_day"] = today
            self._log("mark", equity=round(eq, 2), cash=round(self.broker.get_cash(), 2),
                      positions=len(self.broker.get_positions()),
                      bear=bool(bear), bear_signals=why,
                      **self._basis_fields())
        self._mark_prices = prices
        self._save()
        return {"equity": round(eq, 2), "cash": round(self.broker.get_cash(), 2),
                "positions": len(self.broker.get_positions()),
                "bear": bear, "bear_signals": why,
                "opened": opened, "closed": closed}
