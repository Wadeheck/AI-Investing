"""Bar-driven scalp paper engine — shared by the backtest and the live loop.

Execution realism (the fee rules every digest converged on):
  - entries are RESTING LIMITS: fill only when a later bar trades through the
    price; pay MAKER fee. Unfilled intents expire after ttl bars.
  - targets are resting limits (maker). Stops fill taker + slippage; a gap
    through the stop fills at the bar open (worse).
  - risk 0.25%/trade of equity, daily loss halt 2%, max concurrent positions,
    per-day trade cap, no re-entry at a level that just stopped out (Gala).
  - S4 trails: exit on first 5m CLOSE below EMA9 (Jeff) at taker.
Fees: Binance USDT-perp public tier — maker 2bps, taker 5bps, slip 2bps.
"""
from __future__ import annotations

from dataclasses import dataclass, field

MAKER = 0.0002
TAKER = 0.0005
SLIP = 0.0002
RISK_FRAC = 0.0025
DAILY_HALT = 0.02
MAX_POS = 3
MAX_TRADES_DAY = 8
NO_REENTRY_FRAC = 0.002    # blocked band around a just-stopped level


@dataclass
class Book:
    equity: float = 10_000.0
    pending: list = field(default_factory=list)
    positions: list = field(default_factory=list)
    trades: list = field(default_factory=list)
    day: str = ""
    day_start_eq: float = 0.0
    day_trades: int = 0
    blocked_px: list = field(default_factory=list)
    curve: list = field(default_factory=list)


def _new_day(bk: Book, day: str) -> None:
    bk.day, bk.day_start_eq, bk.day_trades = day, bk.equity, 0
    bk.blocked_px = []


def on_bar(bk: Book, sym: str, ts, bar, intents: list[dict]) -> None:
    """Advance one 5m bar: fill pendings, manage positions, accept intents."""
    day = str(ts)[:10]
    if day != bk.day:
        _new_day(bk, day)
    halted = (bk.day_start_eq - bk.equity) / max(bk.day_start_eq, 1e-9) >= DAILY_HALT
    o, h, l, c = float(bar["open"]), float(bar["high"]), float(bar["low"]), float(bar["close"])
    ema9 = float(bar.get("ema9", c))

    # --- manage open positions (stop first: pessimistic ordering) ----------
    for p in list(bk.positions):
        if p["sym"] != sym:
            continue
        exit_px, how = None, ""
        if p["side"] > 0:
            if l <= p["stop"]:
                exit_px, how = (min(o, p["stop"]) * (1 - SLIP), "stop")
            elif p.get("trail_ema9") and c < ema9:
                exit_px, how = (c * (1 - SLIP), "trail")
            elif h >= p["target"] and not p.get("trail_ema9"):
                exit_px, how = (p["target"], "target")
        else:
            if h >= p["stop"]:
                exit_px, how = (max(o, p["stop"]) * (1 + SLIP), "stop")
            elif l <= p["target"]:
                exit_px, how = (p["target"], "target")
        p["bars"] = p.get("bars", 0) + 1
        if exit_px is None and p["bars"] >= 12 and not p.get("trail_ema9"):
            exit_px, how = (c, "time")               # 1h time stop (Gala)
        if exit_px is not None:
            fee = TAKER if how in ("stop", "trail", "time") else MAKER
            pnl = p["side"] * (exit_px - p["entry"]) * p["qty"]
            bk.equity += pnl - exit_px * p["qty"] * fee
            net = pnl - exit_px * p["qty"] * fee - p["entry"] * p["qty"] * MAKER
            bk.trades.append({"sym": sym, "tag": p["tag"], "side": p["side"],
                              "entry": p["entry"], "exit": exit_px, "how": how,
                              "pnl": round(net, 4), "ts": str(ts)})
            if how == "stop":
                bk.blocked_px.append(p["entry"])
            bk.positions.remove(p)

    # --- fill pending limits ----------------------------------------------
    for pd_ in list(bk.pending):
        if pd_["sym"] != sym:
            continue
        pd_["ttl"] -= 1
        filled = (l <= pd_["entry"]) if pd_["side"] > 0 else (h >= pd_["entry"])
        if filled and not halted and len(bk.positions) < MAX_POS:
            qty = (bk.equity * RISK_FRAC) / max(abs(pd_["entry"] - pd_["stop"]), 1e-9)
            bk.equity -= pd_["entry"] * qty * MAKER
            bk.positions.append({**pd_, "qty": qty, "bars": 0})
            bk.pending.remove(pd_)
        elif pd_["ttl"] <= 0:
            bk.pending.remove(pd_)

    # --- accept new intents ------------------------------------------------
    if not halted and bk.day_trades < MAX_TRADES_DAY:
        for it in intents:
            if any(abs(it["entry"] - b) / max(b, 1e-9) < NO_REENTRY_FRAC
                   for b in bk.blocked_px):
                continue
            if any(p["sym"] == sym and p["tag"] == it["tag"] for p in bk.positions):
                continue
            if any(p["sym"] == sym and p["tag"] == it["tag"] for p in bk.pending):
                continue
            bk.pending.append({**it, "sym": sym})
            bk.day_trades += 1

    bk.curve.append({"ts": str(ts), "equity": round(bk.equity, 2)})
