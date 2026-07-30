"""Crypto bull+bear replay on real data (no news — price/trend/sentiment only).

Discipline (mirrors research/train_web.py):
  train   = first 55%   (2018 bear + 2020 crash + 2017/2020-21 bulls)
  holdout = next 25%    (2022 winter + 2023 recovery) — pick on this, once ranked on train
  final   = last 20%    UNTOUCHED until one evaluation of the single chosen config
Mandate: survival first — hard screen maxDD <= 25% in EVERY window; rank
survivors by holdout CAGR/|maxDD|. Costs 15 bps per side. Long-only, no leverage.
"""
import warnings, itertools, json
warnings.filterwarnings("ignore")
from pathlib import Path
import numpy as np
import pandas as pd

D = Path(__file__).parent / "replay_data"  # populate with replay_fetch_data.py
px = pd.read_csv(D / "crypto_px.csv", index_col=0, parse_dates=True)
fng = pd.read_csv(D / "fng.csv", index_col=0, parse_dates=True)["fng"].reindex(px.index).ffill()
COST = 0.0015

n = len(px)
i_tr, i_ho = int(n * 0.55), int(n * 0.80)
W = {"train": px.index[:i_tr], "holdout": px.index[i_tr:i_ho], "final": px.index[i_ho:]}
print("windows:", {k: f"{v[0].date()}->{v[-1].date()}" for k, v in W.items()})

BEARS = {"2018 winter": ("2018-01-06", "2018-12-15"),
         "covid crash": ("2020-02-14", "2020-03-16"),
         "2022 winter": ("2021-11-08", "2022-11-21")}
BULLS = {"2020-21 bull": ("2020-03-16", "2021-11-08"),
         "2023-24 bull": ("2023-01-01", "2024-03-13")}

def metrics(eq):
    eq = eq.dropna()
    if len(eq) < 30: return None
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1
    r = eq.pct_change().dropna()
    sharpe = r.mean() / (r.std() + 1e-12) * np.sqrt(365)
    dd = (eq / eq.cummax() - 1).min()
    return {"cagr": round(cagr, 3), "sharpe": round(sharpe, 2), "maxdd": round(dd, 3)}

def run(weights: pd.DataFrame) -> pd.Series:
    """weights: per-coin target weight (rest cash). Next-day-close execution."""
    w = weights.shift(1).fillna(0.0)             # decide at close t, hold t+1
    rets = px.pct_change().fillna(0.0)
    port = (w * rets).sum(axis=1)
    turnover = w.diff().abs().sum(axis=1).fillna(0.0)
    port -= turnover * COST
    return (1 + port).cumprod()

def strat(ma_n=100, core=0.5, tact=0.5, mom_n=20, greed_cut=None, vt=None,
          trail=False, coins=("BTC-USD", "ETH-USD")):
    """gated HODL core (each coin held only above its MA) + tactical momentum
    sleeve (best momentum coin, only if above MA and momentum>0).
    greed_cut: halve exposure when F&G > threshold (contrarian de-risk)."""
    ma = px.rolling(ma_n).mean()
    above = (px > ma).astype(float)
    if trail:   # R14-style: also exit when >10% below the 20d high (crash brake)
        above = above * (px > 0.90 * px.rolling(20).max()).astype(float)
    w = pd.DataFrame(0.0, index=px.index, columns=px.columns)
    for c in coins:
        w[c] += core / len(coins) * above[c]
    mom = px.pct_change(mom_n)
    tc = [c for c in px.columns if c in coins or c == "SOL-USD"]
    elig = mom[tc].where(mom[tc] > 0).where(above[tc] > 0)
    has = elig.notna().any(axis=1)
    best = elig[has].idxmax(axis=1).reindex(px.index)
    for c in tc:
        w[c] += tact * (best == c).astype(float)
    if greed_cut:
        w = w.mul(np.where(fng > greed_cut, 0.5, 1.0), axis=0)
    if vt:   # volatility targeting: scale gross down when realized vol > target
        rvol = px["BTC-USD"].pct_change().rolling(30).std() * np.sqrt(365)
        w = w.mul((vt / rvol).clip(upper=1.0).fillna(0.0), axis=0)
    return w.clip(0, 1)

grid = []
for ma_n in (100, 150, 200):
    for core, tact in ((1.0, 0.0), (0.6, 0.4), (0.4, 0.6), (0.2, 0.7), (0.0, 0.9)):
        for mom_n in (20, 60):
            for gc in (None, 75):
                for vt in (None, 0.5, 0.35, 0.25):
                    for tr in (False, True):
                        if tact == 0 and mom_n != 20: continue
                        grid.append({"ma_n": ma_n, "core": core, "tact": tact,
                                     "mom_n": mom_n, "greed_cut": gc, "vt": vt,
                                     "trail": tr})

rows = []
for g in grid:
    eq = run(strat(**g))
    m = {k: metrics(eq.loc[w]) for k, w in W.items()}
    if not m["train"] or not m["holdout"]: continue
    ok = m["train"]["maxdd"] > -0.25 and m["holdout"]["maxdd"] > -0.25
    rows.append({**g, "train": m["train"], "holdout": m["holdout"], "survives": ok})

# benchmarks
bench = {}
for name, wgt in [("BTC hodl", {"BTC-USD": 1.0}), ("BTC/ETH hodl", {"BTC-USD": .5, "ETH-USD": .5})]:
    wdf = pd.DataFrame(0.0, index=px.index, columns=px.columns)
    for c, v in wgt.items(): wdf[c] = v
    eq = run(wdf)
    bench[name] = {k: metrics(eq.loc[w]) for k, w in W.items()}
    bench[name]["bears"] = {b: round(eq.loc[s:e].iloc[-1]/eq.loc[s:e].iloc[0]-1, 3) for b, (s, e) in BEARS.items()}
    bench[name]["bulls"] = {b: round(eq.loc[s:e].iloc[-1]/eq.loc[s:e].iloc[0]-1, 3) for b, (s, e) in BULLS.items()}

rows.sort(key=lambda r: min(r["train"]["maxdd"], r["holdout"]["maxdd"]), reverse=True)
print("\nbest-drawdown configs (screen diagnostics):")
for r in rows[:5]:
    print(" ", {k: r[k] for k in ("ma_n", "core", "tact", "mom_n", "greed_cut", "vt")},
          "train", r["train"], "holdout", r["holdout"])

surv = [r for r in rows if r["survives"]]
# rank on TRAIN first (tune), then verify holdout agrees; final selection = best holdout obj among top-10 train
surv.sort(key=lambda r: r["train"]["cagr"] / max(0.03, -r["train"]["maxdd"]), reverse=True)
top_train = surv[:10]
top_train.sort(key=lambda r: r["holdout"]["cagr"] / max(0.03, -r["holdout"]["maxdd"]), reverse=True)
pick = top_train[0]

print(f"\n{len(surv)}/{len(rows)} configs survive the 25% DD screen in BOTH tuning windows")
print("\nbenchmarks:", json.dumps(bench, indent=1))
print("\ntop-5 (train-ranked then holdout-verified):")
for r in top_train[:5]:
    print(" ", {k: r[k] for k in ("ma_n", "core", "tact", "mom_n", "greed_cut", "vt")},
          "train", r["train"], "holdout", r["holdout"])

# ---- evaluate the ONE chosen config on the untouched final window + regimes
PICK_KEYS = ("ma_n", "core", "tact", "mom_n", "greed_cut", "vt", "trail")
eq = run(strat(**{k: pick[k] for k in PICK_KEYS}))
fin = metrics(eq.loc[W["final"]])
print("\nCHOSEN:", {k: pick[k] for k in PICK_KEYS})
print("final (untouched) window:", fin)
print("bears:", {b: round(eq.loc[s:e].iloc[-1]/eq.loc[s:e].iloc[0]-1, 3) for b, (s, e) in BEARS.items()})
print("bulls:", {b: round(eq.loc[s:e].iloc[-1]/eq.loc[s:e].iloc[0]-1, 3) for b, (s, e) in BULLS.items()})
m_all = metrics(eq)
print("full-period:", m_all)
