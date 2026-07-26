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
import os
from datetime import datetime, timedelta, timezone

from ai_investing.brokers.paper import PaperBroker
from ai_investing.execution.approvals import ProposalBook
from ai_investing.models import Asset, AssetClass, Order, Side

STOP_PCT = 0.25            # wide: a 6-month thesis survives normal wobble
MAX_WEIGHT = 0.12          # target weight per position in the investing pot


def _today_sgt() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=8)).date().isoformat()


def _asset(symbol: str, crypto_exchange: str = "") -> Asset:
    if "/" in symbol:
        return Asset(symbol, AssetClass.CRYPTO, exchange=crypto_exchange)
    return Asset(symbol, AssetClass.STOCK)


class Investor:
    def __init__(self, settings):
        self.settings = settings
        data_dir = os.path.dirname(os.path.abspath(settings.state_path))
        self.path = os.path.join(data_dir, "invest_state.json")
        self._state = self._load()
        self.broker = PaperBroker.from_state(self._state.get("broker", {}), allow_short=True) \
            if self._state.get("broker") else PaperBroker(
                float(getattr(settings, "invest_starting_cash", 100000.0)), allow_short=True)

    def _load(self) -> dict:
        try:
            with open(self.path) as fh:
                return json.load(fh)
        except (OSError, json.JSONDecodeError):
            return {}

    def _save(self) -> None:
        self._state["broker"] = self.broker.state()
        with open(self.path, "w") as fh:
            json.dump(self._state, fh, indent=1)

    # ------------------------------------------------------------------ core --
    def daily_manage(self, prices_by_symbol: dict[str, float], strat: dict,
                     notifier, labels: dict[str, str] | None = None) -> None:
        """Runs at most once per SGT day: exits first, then approved entries,
        then new proposals for unexpressed theses."""
        if self._state.get("last_managed") == _today_sgt():
            return
        labels = labels or {}
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
                o = self.broker.submit(Order(pos.asset, side, abs(pos.qty), reason=reason), px)
                pnl = (px - pos.avg_price) * pos.qty
                notifier.send(f"🏛 *Investing book — closed {labels.get(sym, sym)}* ({sym}): {reason}. "
                              f"P&L ${pnl:,.0f} (pretend money).")

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
                self.broker.submit(Order(_asset(sym, self.settings.crypto_exchange),
                                         side, qty, reason=f"thesis: {t.get('title', '')}"), px)
                verb = "Bought" if side == Side.BUY else "Shorted"
                notifier.send(f"🏛 *Investing book — {verb} {labels.get(sym, sym)}* ({sym}), "
                              f"~${qty * px:,.0f}, under thesis “{t.get('title')}”. "
                              f"Held while the thesis holds; wide {STOP_PCT:.0%} safety stop.")

        # 3) propose entries for theses not yet expressed — one message per stock.
        # Budget-aware: never queue more buying than the pot's cash can honor.
        equity = self._equity(prices_by_symbol)
        budget = self.broker.get_cash()
        for p in book.pending():                          # cash already spoken for
            if p.get("horizon") == "long" and p["side"] == "buy":
                budget -= p.get("qty", 0) * p.get("price", 0)
        for sym, t in want.items():
            px = prices_by_symbol.get(sym, 0.0)
            if px <= 0 or self._held(sym):
                continue
            side = "buy" if t["stance"] == "long" else "sell"
            if book.get(sym, side, "long"):
                continue                                   # pending/decided already
            target = equity * MAX_WEIGHT
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
                "notional": round(qty * px, 2), "pct": MAX_WEIGHT,
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
            p = book.propose(sym, side, qty, px, f"thesis: {t.get('title', '')}", extra)
            notifier.send(
                f"🏛 *Investing book — approval needed* (pretend money)\n\n"
                f"*{verb}: {name}* ({sym}) — about *${qty * px:,.0f}* "
                f"({MAX_WEIGHT:.0%} of the investing pot)\n"
                f"📜 *Thesis “{t.get('title')}”:* {extra['why']}\n"
                f"🤔 {extra['assumptions']}\n"
                f"🗺 {extra['plan']}\n"
                + (extra["bubble_note"] if extra.get("bubble_note") else ""),
                [[(f"✅ yes, {('buy' if side == 'buy' else 'short')} {sym}", f"ap:{p['id']}"),
                  ("❌ skip", f"rj:{p['id']}"),
                  ("🚫 never", f"b:{sym}")]])

        self._state["last_managed"] = _today_sgt()
        self._save()

    # --------------------------------------------------------------- helpers --
    def _held(self, symbol: str) -> bool:
        return any(p.asset.symbol == symbol and abs(p.qty) > 1e-9
                   for p in self.broker.get_positions().values())

    def _equity(self, prices_by_symbol: dict[str, float]) -> float:
        eq = self.broker.get_cash()
        for p in self.broker.get_positions().values():
            eq += p.qty * prices_by_symbol.get(p.asset.symbol, p.avg_price)
        return eq

    def summary(self, prices_by_symbol: dict[str, float]) -> dict:
        return {
            "equity": round(self._equity(prices_by_symbol), 2),
            "cash": round(self.broker.get_cash(), 2),
            "positions": [
                {"symbol": p.asset.symbol, "qty": round(p.qty, 4),
                 "avg_price": round(p.avg_price, 4),
                 "pnl": round((prices_by_symbol.get(p.asset.symbol, p.avg_price)
                               - p.avg_price) * p.qty, 2)}
                for p in self.broker.get_positions().values()],
        }
