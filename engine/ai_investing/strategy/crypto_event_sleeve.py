"""The crypto event-reaction sleeve — crypto's OWN third policy, not a copy of
`event_sleeve.py` and not `crypto_book.py` run twice.

All three books can share the same brain, but "trade the fresh shock" means
something different for each asset class, and copying the stock sleeve's
numbers onto crypto assets would be pasting one market's calibration onto a
different one's volatility and clock:

  vs `event_sleeve.py` (stocks, fresh shock too):
    - SIZING: vol-targeted (CRYPTO_EVENT_VOL_TARGET), not an equal slice of
      equity. A stock event sleeve's 3 names are drawn from one universe of
      broadly similar large/mid-cap vol; this book's 3 names can be BTC
      (~60% annualized) next to a thinly-traded alt (200%+). An equal-dollar
      slice would let the alt dominate the book's actual risk while looking
      identically sized on paper — vol-targeting scales the notional down
      for the wilder name so 1-of-3 slots means 1-of-3 RISK, roughly.
    - CLOCK: CRYPTO_EVENT_HOLD_DAYS defaults to 1, not 2 — the user's own
      framing for wanting this sleeve at all was "crypto goes in and out
      fast"; a shock that hasn't resolved in a day is a different trade than
      the 2-day window the stock gauntlet actually validated.
    - REGIME: gated on `winter` (BTC below its 100d average) by default —
      see WINTER GATE below. The stock sleeve only wires this in as an
      off-by-default conditional (R38/R39); here it is the crypto-specific
      default because the asset class actually crashes 60-80% on a cycle,
      which US large caps don't.
    - No lot-size flooring, no shared-venue plumbing (see below) — crypto
      trades fractionally and never touches Longbridge, so the whole-share
      truncation and pending-order machinery `event_sleeve.py` needs for
      real fills doesn't apply here at all, not just "isn't used yet".

  vs `crypto_book.py` (crypto, but the ACCUMULATED field, not fresh shocks):
    - Different signal entirely: `crypto_book.py`'s tactical sleeve reacts to
      `asset_impacts` (conviction built up with decay over days); this book
      reacts to `shock_assets` (today's news alone, no history, no decay).
      Same brain, different clock — this one can act within a cycle of the
      event, the accumulated-field sleeve reacts to a trend forming.
    - NOT majors-only (R27). That restriction exists because the ACCUMULATED
      field over thin alt-coin history is easy to mistake for edge — a slow
      drift with little data behind it. A single fresh shock crossing a
      fixed floor is a different claim: if an alt-coin node throws a large
      enough shock to qualify, catching that IS the point of an event
      sleeve. See `tradable_crypto_symbols()` in `brain/seed.py` for the
      full curated coin list this book can act on (23 coins as of
      2026-08-19; whichever of those the live exchange actually lists ends
      up on CRYPTO_WATCHLIST and is what `prices_by_sym` carries in).
    - No HODL core, no bear-driven core trim — this book holds nothing by
      default and never rebalances a passive position; every position here
      was opened by a specific shock and closes by its own clock or stop.
    - Separate capital, separate ledger policy name ("crypto_event" vs
      "crypto_tact"/"crypto"), so the learning spine scores this sleeve's
      calls on their own merits rather than blending them into the tactical
      sleeve's track record.

WINTER GATE: while BTC trades below its 100-day average, this book stops
OPENING new positions — existing ones still exit on their own clock or stop,
exits are never gated. This is deliberately narrower than `crypto_book.py`'s
R28 bear exit (four-stream ensemble, liquidates + trims the core): a single
trend signal is enough to make one policy decision ("don't buy MORE risk into
a downtrend") without pretending to forecast the full BEAR_K=2-of-4 call that
governs actual liquidation elsewhere. CRYPTO_EVENT_WINTER_GATE=0 turns it off.

Same fresh-shock shape as the stock sleeve otherwise:
  - enter when |fresh shock| >= CRYPTO_EVENT_MIN, at most CRYPTO_EVENT_N
    concurrent positions
  - exit after CRYPTO_EVENT_HOLD_DAYS, or on the user's 10% hard stop
  - no leverage, ever.
  - runs on EVERY engine cycle, 24/7, same reasoning as `crypto_book.py`.
  - it "decides if it wants to trade": the threshold (and now the winter
    gate) IS the decision. A quiet cycle, or a cycle in a downtrend, holds
    cash and does nothing.

SHORTS: mechanically supported (CRYPTO_EVENT_SHORT=1 opens a short on a
sufficiently negative fresh shock, gated to crypto winter only unless
CRYPTO_EVENT_SHORT_WINTER=0), OFF BY DEFAULT — and this default is not a
placeholder, it is the evidence:

  - The identical shape (react to a bad-news shock in both directions) was
    gauntlet-tested as R37 (all-weather) and rejected. Retried narrower as
    R39 (shorts only inside crypto winter, on the theory that a bad-news
    shock has a tailwind there) — also rejected, TWICE: the original run
    (2026-08-02) and the monthly re-audit (`research_retest.log.1`,
    2026-08-17: "R39 winter-gated event shorts ... no candidate beat
    incumbent — feature NOT adopted"). Both verdicts are recent, not stale
    priors from early in the project.
  - Separately, `docs/research/SHORT_STRATEGY.md`'s dedicated bear-profit
    short sleeve (200d regime lock + bear-rally-fade entry + squeeze stop —
    a genuinely different, price-only signal, not shock-driven) IS real
    evidence of a working short, but its own untouched final-window test
    underperforms long-only (confirmed by re-running
    `research/replay_crypto_short.py` against current data on 2026-08-19:
    final CAGR -4.7% combined vs -1.2% long-only) — it trims 2018/2022
    winter drawdowns at a net cost on the most recent honest evaluation.
    It is not this sleeve's shape anyway (it is not shock-driven), so it
    was not ported here; see that doc if a dedicated bear sleeve is ever
    wanted on `crypto_book.py`.

So: the capability is real and tested end-to-end (see `test_crypto_event_sleeve.py`),
not a stub — but nothing in the evidence says flip it on. It stays available
for the same reason `event_sleeve.py` keeps EVENT_LEV/EVENT_SHORT wired:
the corpus keeps growing, and `scripts/research_retest.py` re-hears rejected
rounds monthly. Flip CRYPTO_EVENT_SHORT only after a re-run actually adopts
the matching round.

No shared venue here — crypto never routes to Longbridge in this codebase,
so this book uses a local, non-venue `PaperBroker` exactly like
`crypto_book.py`, none of the shared-account plumbing `event_sleeve.py`
needs for its real stock fills (pending-order resolution, lot flooring,
migration). Shorting here is a pure paper-P&L simulation for the same
reason the whole crypto side of the engine is paper today (see
`crypto_book.py` — "pretend money" until a live venue leg is wired up), so
enabling it costs nothing but simulated equity, not real margin exposure.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from ai_investing.brokers.paper import PaperBroker
from ai_investing.util import atomic
from ai_investing.strategy.booklog import BookBasisMixin
from ai_investing.models import Asset, AssetClass, Order, Side, mark_price

CRYPTO_EVENT_MIN = float(os.environ.get("CRYPTO_EVENT_MIN", "0.05"))
CRYPTO_EVENT_N = int(os.environ.get("CRYPTO_EVENT_N", "3"))
CRYPTO_EVENT_HOLD_DAYS = int(os.environ.get("CRYPTO_EVENT_HOLD_DAYS", "1"))
HARD_STOP = 0.10          # USER HARD RULE: max 10% loss on any position
START_CASH = float(os.environ.get("CRYPTO_EVENT_START_CASH", "100000"))
# Crypto-specific sizing and regime knobs — independently tunable from both
# event_sleeve.py's EVENT_* and crypto_book.py's VOL_TARGET/BEAR_K.
CRYPTO_EVENT_VOL_TARGET = float(os.environ.get("CRYPTO_EVENT_VOL_TARGET", "0.04"))
CRYPTO_EVENT_WINTER_GATE = os.environ.get("CRYPTO_EVENT_WINTER_GATE", "1").lower() in ("1", "true", "yes")
# Mechanically supported, OFF by default — R37 (all-weather) and R39
# (winter-gated) are both tested and REJECTED shapes, twice each as of
# 2026-08-17. See module docstring "SHORTS" section before flipping either.
CRYPTO_EVENT_SHORT = os.environ.get("CRYPTO_EVENT_SHORT", "0").lower() in ("1", "true", "yes")
CRYPTO_EVENT_SHORT_WINTER = os.environ.get("CRYPTO_EVENT_SHORT_WINTER", "1").lower() in ("1", "true", "yes")


class CryptoEventSleeve(BookBasisMixin):
    def __init__(self, settings):
        self.settings = settings
        data_dir = os.path.dirname(os.path.abspath(settings.state_path))
        self.path = os.path.join(data_dir, "crypto_event_state.json")
        self.journal = os.path.join(data_dir, "crypto_event_journal.jsonl")
        self._state = self._load()
        b = self._state.get("broker")
        if getattr(settings, "crypto_event_live", False):
            from ai_investing.brokers.live import BinanceFuturesBroker
            self.broker = BinanceFuturesBroker(
                settings, long_only=False,
                api_key=settings.crypto_event_binance_api_key,
                api_secret=settings.crypto_event_binance_api_secret)
        else:
            # allow_short=True unconditionally: the ENTRY logic below is what
            # actually decides whether a short ever gets submitted
            # (CRYPTO_EVENT_SHORT, off by default) — the broker just needs to be
            # able to fill one if asked. Safe to leave permissive: this is a
            # local PaperBroker, not a real venue (see module docstring).
            self.broker = (PaperBroker.from_state(b, allow_short=True) if b
                           else PaperBroker(START_CASH, allow_short=True))
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
        venue_equity = self.broker.get_equity()
        self._state["equity"] = (round(venue_equity, 2) if venue_equity is not None
                                 else round(float(b.get("cash", 0.0)) + mv, 2))
        self._state["stale_marks"] = stale
        self._state["marked_at"] = datetime.now(timezone.utc).isoformat()

    def mark(self, prices: dict) -> None:
        self._mark_prices = prices
        self._save()

    def _save(self) -> None:
        # A live broker's positions live at the exchange, not here (see
        # CryptoBook._save for the same reasoning) — snapshot() reads fresh
        # from the venue purely so _stamp_marks below sees real numbers; it
        # is never fed back into from_state() on restart.
        if hasattr(self.broker, "state"):
            self._state["broker"] = self.broker.state()
        else:
            self._state["broker"] = self.broker.snapshot()
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
        venue_equity = self.broker.get_equity()
        if venue_equity is not None:
            return venue_equity
        eq = self.broker.get_cash()
        for p in self.broker.get_positions().values():
            px = prices.get(p.asset.symbol, 0.0)
            if px > 0:
                eq += p.qty * px
        return eq

    # -- one pass per engine cycle, 24/7 --------------------------------------
    def cycle(self, shock_assets: dict, prices_by_sym: dict, bars_by_sym: dict | None = None,
              notifier=None, labels: dict | None = None, regime: str = "neutral",
              winter: bool = False) -> dict:
        """shock_assets: brain state["shock_assets"] — FRESH impacts only.
        bars_by_sym: recent daily bars per symbol, for vol-targeted sizing.
        winter: BTC below its 100d average — gates new entries, not exits."""
        labels = labels or {}
        bars_by_sym = bars_by_sym or {}
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
            short = pos.qty < 0
            move = ((pos.avg_price - px) if short else (px - pos.avg_price)) / pos.avg_price
            age = len([d for d in days if d >= meta.get("opened_day", today)]) - 1
            reason = None
            if move <= -HARD_STOP:
                reason = f"hard stop {move*100:+.1f}%"
            elif age >= CRYPTO_EVENT_HOLD_DAYS:
                reason = f"clock {age}d {move*100:+.1f}%"
            if reason:
                entry = pos.avg_price
                o = self.broker.submit(Order(pos.asset, Side.BUY if short else Side.SELL,
                                             abs(pos.qty),
                                             reason=f"crypto event sleeve: {reason}"), px)
                filled = float(o.filled_qty or 0.0)
                if filled <= 0:
                    self._log("exit_unfilled", symbol=pos.asset.symbol, price=px,
                              requested_qty=round(abs(pos.qty), 6), reason=reason,
                              detail=(o.reason or "no fill"))
                    continue
                pnl = (px - entry) * (filled if not short else -filled)
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

        # 2) entries — biggest fresh crypto shocks above the floor.
        # LONG WINTER GATE: a downtrending BTC doesn't stop this book from
        # EXITING (the loop above never checks it) — only from adding new
        # LONG risk. This must NOT also block shorts: CRYPTO_EVENT_SHORT_WINTER
        # (see module docstring) exists precisely to open shorts DURING
        # winter, so zeroing `room` outright here would make that gate
        # unsatisfiable by construction. Each candidate is filtered by
        # direction below instead.
        long_gated = winter and CRYPTO_EVENT_WINTER_GATE
        shorts_ok = CRYPTO_EVENT_SHORT and (winter or not CRYPTO_EVENT_SHORT_WINTER)
        room = max(0, CRYPTO_EVENT_N - len(open_syms))
        if long_gated and shock_assets:
            blocked = {s: r for s, r in shock_assets.items()
                      if "/" in s and float(r.get("impact", 0.0)) >= CRYPTO_EVENT_MIN}
            if blocked:
                self._log("gated", reason="winter (BTC < 100d)",
                          shocks={s: round(float(r.get("impact", 0.0)), 4)
                                  for s, r in blocked.items()})
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
                if im >= CRYPTO_EVENT_MIN:
                    if long_gated:
                        continue
                elif not (shorts_ok and im <= -CRYPTO_EVENT_MIN):
                    continue
                cands.append((abs(im), im, sym, row))
            cands.sort(reverse=True)
            trust = self.ledger.size_multiplier("crypto_event", regime) if self.ledger else 1.0
            for _, im, sym, row in cands[:room]:
                base = min(eq * trust / max(1, CRYPTO_EVENT_N),
                           self.broker.get_cash() * 0.9)
                # VOL-TARGETED SIZING (crypto-specific — see module docstring):
                # an equal slice treats BTC and a thin alt as the same bet.
                # Scale by target/realized daily vol, clipped 0.3-2.0x like
                # crypto_book.py's tactical sleeve, so 1-of-3 slots is closer
                # to 1-of-3 RISK than 1-of-3 DOLLARS.
                rv_daily = 0.04
                bars = bars_by_sym.get(sym) or []
                if len(bars) >= 21:
                    rets = [(bars[i].close / bars[i - 1].close - 1.0)
                            for i in range(-20, 0) if bars[i - 1].close]
                    if rets:
                        mu = sum(rets) / len(rets)
                        rv = (sum((r - mu) ** 2 for r in rets) / max(1, len(rets) - 1)) ** 0.5
                        if rv > 1e-6:
                            rv_daily = rv
                            base *= max(0.3, min(2.0, CRYPTO_EVENT_VOL_TARGET / rv))
                notional = min(base, self.broker.get_cash() * 0.9)
                if notional < 500:
                    continue
                px = prices_by_sym[sym]
                asset = Asset(sym, AssetClass.CRYPTO, exchange=self.settings.crypto_exchange)
                short = im < 0
                qty = notional / px
                o = self.broker.submit(
                    Order(asset, Side.SELL if short else Side.BUY, qty,
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
                self._log("short" if short else "buy", symbol=sym, price=px,
                          notional=round(notional, 2), shock=round(im, 4),
                          node=row.get("node", ""), size_mult=round(trust, 3),
                          rv_daily=round(rv_daily, 4))
                if self.ledger:
                    self.ledger.record("crypto_event", sym, 1, im, rv_daily,
                                       CRYPTO_EVENT_HOLD_DAYS, regime=regime,
                                       driver=row.get("node", ""), notional=notional)
                if notifier:
                    verb = "shorted" if short else "bought"
                    notifier.send(
                        f"⚡️₿ *Crypto event sleeve — {verb} {labels.get(sym, sym)}* ({sym}), "
                        f"~${notional:,.0f} on a fresh news shock of {im:+.2f} "
                        f"via {row.get('node','the web')}. Out in {CRYPTO_EVENT_HOLD_DAYS} days "
                        f"or on a 10% stop — whichever comes first (pretend money).")

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
