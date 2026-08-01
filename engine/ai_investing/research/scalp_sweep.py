"""Train-window-only variant sweep for the scalp families. The holdout is
NOT touched here — the winning variant per family (if any is positive on
train) gets judged on the holdout exactly once by scalp_backtest.
Run: .venv/bin/python -m ai_investing.research.scalp_sweep
"""
import warnings

warnings.filterwarnings("ignore")
import numpy as np

from ai_investing.research import scalp_backtest as bt
from ai_investing.scalp import engine as eng
from ai_investing.scalp import indicators as ind
from ai_investing.scalp import strategies as st

VARIANTS = {
    "S1_sweep": [
        {},                                             # as shipped
        {"MIN_STOP_FRAC": 0.006, "RR_TARGET": 1.5},     # wider stop, closer target
        {"MIN_STOP_FRAC": 0.008, "RR_TARGET": 1.0},     # reversion classic 1R
        {"SECOND_DRIVE_BARS": 96},                      # stricter second-drive
    ],
    "S2_retest": [
        {},
        {"MIN_STOP_FRAC": 0.006},
        {"RR_TARGET": 3.0},
    ],
    "S3_exhaust": [
        {},
        {"_r24": 0.04, "_run": 3, "_cvd": 0},           # softer stretch, no CVD gate
        {"_r24": 0.03, "_run": 2, "_cvd": 0},
    ],
    "S4_momo": [
        {},
        {"_rvol": 1.2, "_box": 2.5},
        {"_rvol": 1.0, "_box": 3.0, "_btc": 0},
    ],
}


def apply(v):
    for k, val in v.items():
        if not k.startswith("_"):
            setattr(st, k, val)
    # soft knobs read via module globals patched into the strategy functions
    st._SOFT = {k: val for k, val in v.items() if k.startswith("_")}


def main():
    btc1 = ind.load_1m(bt.HIST / "BTCUSDT_1m.csv")
    btc5 = ind.enrich(ind.resample(btc1, "5min"))
    t_end = int(len(btc5) * 0.70)
    base = {k: getattr(st, k) for k in ("MIN_STOP_FRAC", "RR_TARGET", "SECOND_DRIVE_BARS")}
    for fam, vars_ in VARIANTS.items():
        for vi, v in enumerate(vars_):
            for k, val in base.items():
                setattr(st, k, val)
            st._SOFT = {}
            apply(v)
            nets, trades = [], 0
            for sym in bt.SYMS:
                bk, df = bt.run_symbol(sym, btc5, 0, t_end, (fam,))
                m = bt.metrics(bk, df, 0, t_end)
                nets.append(m.get("net", 0.0))
                trades += m.get("trades", 0)
            print(f"{fam} v{vi} {v}: train net avg {np.mean(nets):+.2%}, {trades} trades")
    for k, val in base.items():
        setattr(st, k, val)


if __name__ == "__main__":
    main()
