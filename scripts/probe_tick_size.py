#!/usr/bin/env python3
"""Settle what Longbridge error 602035 actually objects to.

Eight consecutive live orders were rejected with "Wrong bid size, please change
the price" and one filled. Quantity cannot be the cause: `LongbridgeBroker.submit`
already truncates with `int(order.qty)`, so all nine submitted exactly 1 share.
The only remaining variable is the price — `live.py` sends
`round(order.limit_price, 3)`, and US equities trade in $0.01 ticks, so a third
decimal is an invalid price ~9 times in 10. That matches 1 fill in 9 attempts,
but matching is not proving, and the submitted price was never recorded.

So: send two orders that differ in NOTHING but the third decimal, and read the
venue's answer.

  A  limit at a valid 2-decimal tick     -> expected: accepted
  B  same price + $0.003                 -> expected: 602035 if the theory holds

Both are BUY limits placed ~10% BELOW the last price, so neither can fill: far
enough from market to rest, close enough to stay inside the venue's price bands
(an absurd price would risk a DIFFERENT rejection and confound the test). Any
order that is accepted is cancelled in a `finally`, and the script re-lists open
orders at the end so it cannot quietly leave one resting.

  python3 scripts/probe_tick_size.py            # dry run: print, send nothing
  python3 scripts/probe_tick_size.py --send     # actually place the two probes
"""
import argparse
import os
import sys
from decimal import Decimal

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "engine"))

SYMBOL = "AAPL.US"
BELOW = 0.10          # place the resting bid 10% under the last trade


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true", help="place the probe orders")
    args = ap.parse_args()

    # Importing config is what loads .env (`_load_dotenv` runs at import time),
    # and the credentials live there rather than in the ambient environment.
    import ai_investing.config  # noqa: F401
    from longport.openapi import (Config, TradeContext, QuoteContext,  # type: ignore
                                  OrderSide, OrderType, TimeInForceType)

    # Built exactly as LongbridgeBroker builds it — from_env() does not exist in
    # this SDK version, and a probe that authenticates differently from the
    # engine is not probing the engine's path.
    cfg = Config.from_apikey(app_key=os.environ["LONGPORT_APP_KEY"],
                             app_secret=os.environ["LONGPORT_APP_SECRET"],
                             access_token=os.environ["LONGPORT_ACCESS_TOKEN"])
    trade = TradeContext(cfg)
    quote = QuoteContext(cfg)

    # SAFETY: never probe anything but the paper account. Same contract as
    # LongbridgeBroker's startup guard (c2c1133) — the token alone decides which
    # account is reached, so it must be checked here too rather than assumed.
    expected = os.environ.get("LONGPORT_EXPECT_CHANNEL", "lb_papertrading")
    channels = [ch.account_channel for ch in trade.stock_positions().channels]
    print(f"account channel(s): {channels or '(none — account holds no positions)'}")
    if expected and [c for c in channels if c != expected]:
        raise SystemExit(f"REFUSING: token maps to {channels!r}, expected {expected!r}")

    from ai_investing.brokers.live import snap_to_tick
    from ai_investing.models import Side

    last = float(quote.quote([SYMBOL])[0].last_done)
    base = round(last * (1 - BELOW), 2)          # valid US tick: exactly 2dp
    bad = round(base + 0.003, 3)                 # same price, invalid third decimal
    fixed = snap_to_tick(bad, SYMBOL, Side.BUY)  # what the adapter now sends
    print(f"{SYMBOL} last {last:.2f}   resting bid {BELOW:.0%} below")
    print(f"  A  valid tick    {base}")
    print(f"  B  third decimal {bad}")
    print(f"  C  B through snap_to_tick -> {fixed}")
    if not args.send:
        print("\ndry run — nothing sent. Re-run with --send to place them.")
        return 0

    placed = []
    try:
        for tag, px in (("A valid 2dp", base), ("B invalid 3dp", bad),
                        ("C snapped   ", fixed)):
            try:
                resp = trade.submit_order(
                    symbol=SYMBOL, side=OrderSide.Buy, order_type=OrderType.LO,
                    submitted_quantity=Decimal("1"),
                    submitted_price=Decimal(str(px)),
                    time_in_force=TimeInForceType.Day)
                oid = str(getattr(resp, "order_id", ""))
                placed.append(oid)
                print(f"\n  {tag} @ {px}  -> ACCEPTED  order_id={oid}")
            except Exception as exc:
                print(f"\n  {tag} @ {px}  -> REJECTED  {type(exc).__name__}: {exc}")
    finally:
        for oid in placed:
            try:
                trade.cancel_order(oid)
                print(f"  cancelled {oid}")
            except Exception as exc:
                print(f"  !! COULD NOT CANCEL {oid}: {exc} — CANCEL IT MANUALLY")
        try:
            today = trade.today_orders()
            resting = [o for o in today
                       if str(getattr(o, "status", "")).lower().find("filled") < 0
                       and str(getattr(o, "order_id", "")) in placed]
            print(f"\n  open probe orders remaining: {len(resting)}")
            for o in resting:
                print(f"    {o.order_id}  {getattr(o, 'status', '?')}")
        except Exception as exc:
            print(f"  (could not re-list today's orders: {exc})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
