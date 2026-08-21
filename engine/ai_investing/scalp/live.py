"""Live scalp loop — free Binance data, paper-only, observation-first.

Every LOOP_SECS: pull the latest 1m klines (raw endpoint: taker-buy volume
included), rebuild 5m indicators, generate signals, advance the paper book
one bar when a new 5m bar closes, and write data/scalp_state.json for the
dashboard (/scalp).

The 2026-08-01 backtest killed all four families on the holdout (see
data/scalp_backtest.json + docs/research/SCALP_MODEL.md). The paper book therefore
runs as a FORWARD TEST at minimal risk — the signals stay visible and every
outcome is logged, but this earns promotion only by building a live paper
record, exactly like the main engine's scorecard philosophy.

Run: cd engine && ../.venv/bin/python -m ai_investing.scalp.live
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import ccxt
import pandas as pd

from . import engine as eng
from . import indicators as ind
from . import strategies as st

def _data() -> Path:
    """Resolved on USE, not at import.

    These were module constants built from `__file__`, which walks up to the
    repo's real data directory no matter what the caller configured — §4.21's
    defect, and the last of the seven §4A listed. Resolving lazily through the
    shared resolver means `STATE_PATH` redirects this module like everything
    else, and it costs one cached lookup.
    """
    from ai_investing.data.paths import data_dir
    return Path(data_dir())


def _state_file() -> Path:
    return _data() / "scalp_state.json"


def _book_file() -> Path:
    return _data() / "scalp_book.json"
SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
LOOP_SECS = 60
BARS_1M = 900          # 15h of context per refresh


def fetch_1m(ex, sym: str) -> pd.DataFrame:
    rows = ex.publicGetKlines({"symbol": sym, "interval": "1m", "limit": BARS_1M})
    df = pd.DataFrame(
        [[int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]),
          float(r[5]), float(r[9]), float(r[8])] for r in rows],
        columns=["ts", "open", "high", "low", "close", "vol", "taker_buy_vol", "n_trades"])
    df.index = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df.drop(columns=["ts"])


def load_book() -> eng.Book:
    bk = eng.Book()
    if _book_file().exists():
        try:
            d = json.loads(_book_file().read_text())
            bk.equity = d.get("equity", bk.equity)
            bk.positions = d.get("positions", [])
            bk.pending = d.get("pending", [])
            bk.trades = d.get("trades", [])[-500:]
            bk.curve = d.get("curve", [])[-2000:]
        except (json.JSONDecodeError, KeyError):
            pass
    return bk


def save_book(bk: eng.Book) -> None:
    _book_file().write_text(json.dumps({"equity": bk.equity, "positions": bk.positions,
                                "pending": bk.pending, "trades": bk.trades[-500:],
                                "curve": bk.curve[-2000:]}, indent=0))


def backtest_verdicts() -> dict:
    try:
        rep = json.loads((_data() / "scalp_backtest.json").read_text())
        return {f: v.get("ships", False) for f, v in rep.get("families", {}).items()}
    except (json.JSONDecodeError, OSError):
        return {}


def main() -> None:
    ex = ccxt.binance()
    bk = load_book()
    verdicts = backtest_verdicts()
    last_5m: dict[str, str] = {}
    signal_log: list[dict] = []
    print(f"[scalp] live loop up — paper ${bk.equity:,.0f}, "
          f"backtest verdicts {verdicts or 'none on file'}", flush=True)
    while True:
        state = {"updated": datetime.now(timezone.utc).isoformat(),
                 "verdicts": verdicts, "mode": "forward-paper (all families failed "
                 "the 60d holdout — earning trust forward, tiny risk)",
                 "equity": round(bk.equity, 2), "symbols": {}}
        btc5 = None
        for sym in SYMS:
            try:
                df1 = fetch_1m(ex, sym)
            except Exception as exc:                       # network hiccup: skip round
                print(f"[scalp] {sym} fetch failed: {exc}", flush=True)
                continue
            df = ind.enrich(ind.resample(df1, "5min"))
            if sym == "BTCUSDT":
                btc5 = df
            df1h = ind.resample(df1, "1h")
            df1h["dvol"] = df1h["close"] * df1h["vol"]
            i = len(df) - 1                                # last CLOSED bar = i-1
            levels = ind.confirmed_levels(df, i)
            va = ind.value_area(df, i)
            intents = st.generate(df, df1, df1h, btc5 if btc5 is not None else df,
                                  i, levels, va)
            new_bar = str(df.index[i - 1])
            if last_5m.get(sym) != new_bar:                # advance book once per 5m
                eng.on_bar(bk, sym, df.index[i - 1], df.iloc[i - 1], intents)
                last_5m[sym] = new_bar
                for it in intents:
                    signal_log.append({"ts": new_bar, "sym": sym, **{
                        k: it[k] for k in ("tag", "side", "entry", "stop", "target")}})
                signal_log[:] = signal_log[-200:]
            tail = df.iloc[-150:]
            state["symbols"][sym] = {
                "candles": [[str(t), round(r["open"], 2), round(r["high"], 2),
                             round(r["low"], 2), round(r["close"], 2), round(r["vol"], 2)]
                            for t, r in tail.iterrows()],
                "ema9": [round(x, 2) if x == x else None for x in tail["ema9"]],
                "vwap24": [round(x, 2) if x == x else None for x in tail["vwap24"]],
                "cvd": [round(x, 1) for x in (tail["cvd"] - tail["cvd"].iloc[0])],
                "levels": levels, "value_area": va,
                "last": round(float(df["close"].iloc[-1]), 2),
                "signals_active": intents}
        state["signal_log"] = signal_log[-50:]
        state["positions"] = bk.positions
        state["pending"] = bk.pending
        state["trades"] = bk.trades[-50:]
        state["curve"] = bk.curve[-500:]
        _state_file().write_text(json.dumps(state, indent=0))
        save_book(bk)
        time.sleep(LOOP_SECS)


if __name__ == "__main__":
    main()
