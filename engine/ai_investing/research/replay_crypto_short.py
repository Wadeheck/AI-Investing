"""Crypto SHORT-signal test: can we be PROFITABLE in bears, not just flat?

Same discipline: train 55% / holdout 25% / final 20% untouched. Costs 15bps
per side PLUS 10%/yr funding/borrow charged on any short exposure (conservative
— in real bears perp funding often pays shorts, we assume it costs instead).
Shorts are BTC-only (deepest market). Every short carries a squeeze stop.

Short-signal candidates (all daily-close mechanical):
  regime   : BTC < 200d MA  (bear regime filter — never short in a bull)
  breakdown: BTC < 20d low  (fresh leg down)
  momdown  : 20d momentum < -X%
  fade     : bear regime AND 10d bounce > +B% (bear-market-rally fade)
Exit/stop : price rises S% above the low since entry (squeeze stop), or regime ends.
"""
import warnings
warnings.filterwarnings("ignore")
from pathlib import Path
import numpy as np
import pandas as pd

D = Path(__file__).parent / "replay_data"  # populate with replay_fetch_data.py
px = pd.read_csv(D / "crypto_px.csv", index_col=0, parse_dates=True)
btc = px["BTC-USD"]
COST = 0.0015
FUND = 0.10 / 365          # funding/borrow on shorts, per day

n = len(px)
i_tr, i_ho = int(n * 0.55), int(n * 0.80)
W = {"train": px.index[:i_tr], "holdout": px.index[i_tr:i_ho], "final": px.index[i_ho:]}

BEARS = {"2018 winter": ("2018-01-06", "2018-12-15"),
         "covid crash": ("2020-02-14", "2020-03-16"),
         "2022 winter": ("2021-11-08", "2022-11-21")}
BULLS = {"2020-21 bull": ("2020-03-16", "2021-11-08"),
         "2023-24 bull": ("2023-01-01", "2024-03-13")}

ret = btc.pct_change().fillna(0.0)
ma200 = btc.rolling(200).mean()
lo20 = btc.rolling(20).min()
hi20 = btc.rolling(20).max()
mom20 = btc.pct_change(20)
bounce10 = btc.pct_change(10)

def metrics(eq):
    eq = eq.dropna()
    if len(eq) < 30: return None
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    r = eq.pct_change().dropna()
    return {"cagr": round(float((eq.iloc[-1]/eq.iloc[0])**(1/yrs)-1), 3),
            "sharpe": round(float(r.mean()/(r.std()+1e-12)*np.sqrt(365)), 2),
            "maxdd": round(float((eq/eq.cummax()-1).min()), 3)}

def seg(eq, s, e):
    x = eq.loc[s:e]
    return round(float(x.iloc[-1]/x.iloc[0]-1), 3)

def short_weights(entry_mode, size, stop, mom_x=0.0, fade_b=0.10):
    """stateful daily loop: enter short on signal, exit on squeeze-stop or regime end."""
    w = np.zeros(len(btc))
    in_short, entry_low = False, np.nan
    pxv, mav, lov, momv, bncv = btc.values, ma200.values, lo20.values, mom20.values, bounce10.values
    for i in range(200, len(btc)):
        bear = pxv[i] < mav[i]
        if in_short:
            entry_low = min(entry_low, pxv[i])
            if not bear or pxv[i] > entry_low * (1 + stop):
                in_short = False                    # squeeze stop or bull regime -> cover
        if not in_short and bear:
            if entry_mode == "regime":
                sig = True
            elif entry_mode == "breakdown":
                sig = pxv[i] <= lov[i - 1] if i > 0 else False
            elif entry_mode == "momdown":
                sig = momv[i] < -mom_x
            elif entry_mode == "fade":
                sig = bncv[i] > fade_b
            if sig:
                in_short, entry_low = True, pxv[i]
        w[i] = -size if in_short else 0.0
    return pd.Series(w, index=btc.index)

def run_short(w):
    ws = w.shift(1).fillna(0.0)
    pnl = ws * ret - ws.diff().abs().fillna(0.0) * COST - ws.abs() * FUND
    return (1 + pnl).cumprod()

print("=== A. standalone short sleeves (is the signal itself profitable?) ===")
cands = []
for mode, kw in [("regime", {}), ("breakdown", {}), ("momdown", {"mom_x": 0.05}),
                 ("momdown", {"mom_x": 0.10}), ("fade", {"fade_b": 0.10}), ("fade", {"fade_b": 0.15})]:
    for size in (0.3, 0.5):
        for stop in (0.10, 0.20):
            nm = f"{mode}{kw.get('mom_x', kw.get('fade_b',''))}/s{size}/x{stop}"
            eq = run_short(short_weights(mode, size, stop, **kw))
            m = {k: metrics(eq.loc[v]) for k, v in W.items()}
            bears = {b: seg(eq, s, e) for b, (s, e) in BEARS.items()}
            bulls = {b: seg(eq, s, e) for b, (s, e) in BULLS.items()}
            cands.append((nm, eq, m, bears, bulls))

cands.sort(key=lambda c: c[2]["holdout"]["cagr"], reverse=True)
for nm, eq, m, bears, bulls in cands[:8]:
    print(f"  {nm:24s} train {m['train']} holdout {m['holdout']}")
    print(f"    {'':22s} bears {bears} bulls {bulls}")

# ---- B. combined book: the chosen LONG model + best short sleeve (picked on train)
print("\n=== B. combined: long model (prev. chosen) + short sleeve ===")
fng = pd.read_csv(D / "fng.csv", index_col=0, parse_dates=True)["fng"].reindex(px.index).ffill()

def long_weights():   # chosen config from crypto_replay: ma200/core.6/tact.4/mom20/vt.25/trail
    ma = px.rolling(200).mean()
    above = (px > ma).astype(float) * (px > 0.90 * px.rolling(20).max()).astype(float)
    w = pd.DataFrame(0.0, index=px.index, columns=px.columns)
    for c in ("BTC-USD", "ETH-USD"):
        w[c] += 0.6 / 2 * above[c]
    mom = px.pct_change(20)
    elig = mom.where(mom > 0).where(above > 0)
    has = elig.notna().any(axis=1)
    best = elig[has].idxmax(axis=1).reindex(px.index)
    for c in px.columns:
        w[c] += 0.4 * (best == c).astype(float)
    rvol = px["BTC-USD"].pct_change().rolling(30).std() * np.sqrt(365)
    return w.mul((0.25 / rvol).clip(upper=1.0).fillna(0.0), axis=0).clip(0, 1)

lw = long_weights()
rets_all = px.pct_change().fillna(0.0)

# rank standalone sleeves on TRAIN only, then try top-3 combined, verify holdout
cands.sort(key=lambda c: c[2]["train"]["cagr"] / max(0.03, -c[2]["train"]["maxdd"]), reverse=True)
best_combo = None
for nm, _, _, _, _ in [c[:1] + c[1:] for c in cands[:3]]:
    mode = nm.split("/")[0]
    base = "".join(ch for ch in mode if ch.isalpha())
    num = mode[len(base):]
    kw = {}
    if base == "momdown": kw["mom_x"] = float(num)
    if base == "fade": kw["fade_b"] = float(num)
    size = float(nm.split("/s")[1].split("/")[0]); stop = float(nm.split("/x")[1])
    sw = short_weights(base, size, stop, **kw)
    wl = lw.shift(1).fillna(0.0); ws = sw.shift(1).fillna(0.0)
    pnl = (wl * rets_all).sum(axis=1) + ws * ret
    pnl -= (wl.diff().abs().sum(axis=1).fillna(0.0) + ws.diff().abs().fillna(0.0)) * COST
    pnl -= ws.abs() * FUND
    eq = (1 + pnl).cumprod()
    m = {k: metrics(eq.loc[v]) for k, v in W.items()}
    bears = {b: seg(eq, s, e) for b, (s, e) in BEARS.items()}
    bulls = {b: seg(eq, s, e) for b, (s, e) in BULLS.items()}
    ok = m["train"]["maxdd"] > -0.25 and m["holdout"]["maxdd"] > -0.25
    print(f"  {'PASS' if ok else 'fail'} long + {nm:22s} train {m['train']} holdout {m['holdout']}")
    print(f"       final(untouched) {m['final']} bears {bears} bulls {bulls}")
    if ok and (best_combo is None or m["holdout"]["cagr"] > best_combo[1]["holdout"]["cagr"]):
        best_combo = (nm, m, bears, bulls)

# long-only reference for the same windows
wl = lw.shift(1).fillna(0.0)
pnl = (wl * rets_all).sum(axis=1) - wl.diff().abs().sum(axis=1).fillna(0.0) * COST
eql = (1 + pnl).cumprod()
ml = {k: metrics(eql.loc[v]) for k, v in W.items()}
print(f"\n  reference long-only     train {ml['train']} holdout {ml['holdout']} final {ml['final']}")
print(f"       bears {({b: seg(eql, s, e) for b, (s, e) in BEARS.items()})}")
