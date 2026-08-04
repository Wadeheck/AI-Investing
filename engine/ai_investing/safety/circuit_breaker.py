"""Persistent, multi-horizon circuit breaker — the bounded worst case.

Fixes the old kill switch's holes: state is persisted to disk so a restart can't reset
your loss limits, and it enforces THREE drawdown horizons plus per-day hard caps:

  - daily     : loss vs the day's starting equity (auto-clears next day)
  - trailing  : loss from the equity peak (latched — needs manual reset)
  - inception : loss from the very first equity seen (latched)
  - caps      : max trades/day and max traded-notional/day (stop opening, don't flatten)

`check(equity)` returns a BreakerDecision: whether to allow new positions and whether to
emergency-flatten. `register_trade(notional)` feeds the per-day caps.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class BreakerDecision:
    allow_new: bool     # may open / add positions
    flatten: bool       # emergency: flatten everything and halt
    reason: str
    # True only on the cycle that LATCHES the halt. A latched breaker returns
    # flatten=True forever, and the runner alerted on every one of them: a halt
    # at 02:43 became a Telegram message every five minutes, all night, all
    # identical. That is worse than useless — it teaches you to swipe away the
    # channel that every other safeguard reports through. Announce the event, not
    # the state.
    announce: bool = True


class CircuitBreaker:
    def __init__(self, safety_cfg, daily_drawdown_limit: float, path: str):
        self.cfg = safety_cfg
        self.daily_limit = daily_drawdown_limit
        self.path = path
        self.state = self._load()

    def _default(self) -> dict:
        return {"inception_equity": None, "peak_equity": None, "day": "",
                "day_start_equity": None, "trades_today": 0, "notional_today": 0.0,
                "halted": False, "halt_reason": ""}

    def _load(self) -> dict:
        try:
            with open(self.path) as fh:
                base = self._default()
                base.update(json.load(fh))
                return base
        except (OSError, json.JSONDecodeError):
            return self._default()

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
            with open(self.path, "w") as fh:
                json.dump(self.state, fh, indent=2)
        except OSError:
            pass

    @staticmethod
    def _dd(ref, equity) -> float:
        return (ref - equity) / ref if ref and ref > 0 else 0.0

    def check(self, equity: float) -> BreakerDecision:
        s = self.state
        # An unusable equity reading must never move this state machine. Every
        # threshold here is a comparison, and NaN loses every comparison, so a
        # NaN equity does not trip the breaker — it walks past it, and on the way
        # past it overwrites day_start_equity and peak_equity with garbage that
        # then mismeasures every later cycle. Refuse the reading instead: hold
        # the gate shut, do NOT flatten (there is no evidence of a loss, only an
        # absence of evidence), and leave the marks alone until the feed is back.
        if not (isinstance(equity, (int, float)) and math.isfinite(equity) and equity > 0):
            return BreakerDecision(False, False,
                                   f"equity unreadable ({equity!r}) — gate shut, "
                                   f"marks untouched until the feed recovers")
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if s["day"] != today:
            s["day"] = today
            s["day_start_equity"] = equity
            s["trades_today"] = 0
            s["notional_today"] = 0.0
            if str(s.get("halt_reason", "")).startswith("daily"):  # daily halt clears next day
                s["halted"] = False
                s["halt_reason"] = ""
        if s["inception_equity"] is None:
            s["inception_equity"] = equity
        if s["day_start_equity"] is None:
            s["day_start_equity"] = equity
        s["peak_equity"] = equity if s["peak_equity"] is None else max(s["peak_equity"], equity)

        # monthly high-water mark (user's ratchet): when a month closes higher
        # than the locked base, that equity becomes the new base — banked gains
        # are never treated as risk capital again
        month = today[:7]
        if s.get("hwm_month") != month:
            prev_eq = s.get("month_close_equity")
            if prev_eq is not None and (s.get("hwm") is None or prev_eq > s["hwm"]):
                s["hwm"] = prev_eq
            s["hwm_month"] = month
        s["month_close_equity"] = equity                   # rolls until month flips

        if s["halted"]:                                   # latched (trailing/inception, or same-day daily)
            self._save()
            return BreakerDecision(False, True, s["halt_reason"], announce=False)

        inc = self._dd(s["inception_equity"], equity)
        if inc >= self.cfg.max_inception_drawdown:
            return self._latch(f"inception drawdown {inc:.1%} >= {self.cfg.max_inception_drawdown:.0%}")
        trail = self._dd(s["peak_equity"], equity)
        if trail >= self.cfg.max_trailing_drawdown:
            return self._latch(f"trailing drawdown {trail:.1%} >= {self.cfg.max_trailing_drawdown:.0%}")
        day = self._dd(s["day_start_equity"], equity)
        if day >= self.daily_limit:
            s["halted"] = True
            s["halt_reason"] = f"daily drawdown {day:.1%} >= {self.daily_limit:.0%}"
            self._save()
            return BreakerDecision(False, True, s["halt_reason"])

        hwm_dd = self._dd(s.get("hwm"), equity)
        if s.get("hwm") and hwm_dd >= self.cfg.hwm_drawdown_limit:
            self._save()                # not latched: recovery re-opens the gate
            return BreakerDecision(False, False,
                                   f"{hwm_dd:.1%} below the monthly high-water mark "
                                   f"(${s['hwm']:,.0f}) — protecting banked gains")

        if self.cfg.max_trades_per_day and s["trades_today"] >= self.cfg.max_trades_per_day:
            self._save()
            return BreakerDecision(False, False, f"max {self.cfg.max_trades_per_day} trades/day reached")
        if self.cfg.max_notional_per_day and s["notional_today"] >= self.cfg.max_notional_per_day:
            self._save()
            return BreakerDecision(False, False, f"max notional/day ${self.cfg.max_notional_per_day:,.0f} reached")

        self._save()
        return BreakerDecision(True, False, "")

    def _latch(self, reason: str) -> BreakerDecision:
        self.state["halted"] = True
        self.state["halt_reason"] = reason
        self._save()
        return BreakerDecision(False, True, reason)

    def register_trade(self, notional: float) -> None:
        self.state["trades_today"] += 1
        self.state["notional_today"] += abs(notional)
        self._save()

    def reset(self) -> None:
        """Manual reset of a latched halt (operator action)."""
        self.state["halted"] = False
        self.state["halt_reason"] = ""
        self._save()

    def status(self) -> dict:
        return dict(self.state)
