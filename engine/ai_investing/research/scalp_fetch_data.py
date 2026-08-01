"""Pull free Binance 1m history for the scalp backtests (resumable).

Klines come from the raw endpoint (not ccxt.fetch_ohlcv) because the raw rows
carry taker-buy volume — a free order-flow proxy: delta = 2*takerBuy - total.
Writes one CSV per symbol to data/scalp_history/.
"""
import csv, sys, time
from pathlib import Path

import ccxt

OUT = Path(__file__).resolve().parents[3] / "data" / "scalp_history"
OUT.mkdir(parents=True, exist_ok=True)
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 60
COLS = ["ts", "open", "high", "low", "close", "vol", "taker_buy_vol", "n_trades"]

ex = ccxt.binance()
now = ex.milliseconds()
start_all = now - DAYS * 86_400_000

for sym in SYMBOLS:
    path = OUT / f"{sym}_1m.csv"
    since = start_all
    mode = "w"
    if path.exists():                      # resume from last saved bar
        with path.open() as fh:
            last = None
            for last in csv.reader(fh):
                pass
        if last and last[0] != "ts":
            since, mode = int(last[0]) + 60_000, "a"
    with path.open(mode, newline="") as fh:
        w = csv.writer(fh)
        if mode == "w":
            w.writerow(COLS)
        fetched = 0
        while since < now - 60_000:
            for attempt in range(5):
                try:
                    rows = ex.publicGetKlines({"symbol": sym, "interval": "1m",
                                               "startTime": since, "limit": 1000})
                    break
                except Exception as e:
                    print(f"{sym}: retry {attempt+1} ({e})", flush=True)
                    time.sleep(5 * (attempt + 1))
            else:
                sys.exit(f"{sym}: giving up")
            if not rows:
                break
            for r in rows:
                # raw kline: [openTime, o, h, l, c, vol, closeTime, quoteVol,
                #             nTrades, takerBuyBase, takerBuyQuote, ignore]
                w.writerow([r[0], r[1], r[2], r[3], r[4], r[5], r[9], r[8]])
            fetched += len(rows)
            since = int(rows[-1][0]) + 60_000
            if fetched % 20_000 < 1000:
                print(f"{sym}: {fetched} bars…", flush=True)
            time.sleep(0.15)               # well under binance rate limits
    print(f"{sym}: done ({path})", flush=True)
print("all done")
