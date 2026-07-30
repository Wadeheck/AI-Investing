"""Stock bull+bear replay (price-only). Same discipline as crypto_replay:
train 55% / holdout 25% / final 20% untouched; hard maxDD<=25% screen both
tuning windows; survival first. Costs 10bps per side. Long-only + defensive
rotation (cash/TLT/GLD) — the bear-market objective is: lose little or make
a positive defensive return while SPY draws down.

Survivorship caveat: the single-stock universe was picked in 2026 → flatters
stock-picking variants. ETF-only variants (SPY/sectors/TLT/GLD) are clean.
"""
import warnings, json
warnings.filterwarnings("ignore")
from pathlib import Path
import numpy as np
import pandas as pd

D = Path(__file__).parent / "replay_data"  # populate with replay_fetch_data.py
px = pd.read_csv(D / "stock_px.csv", index_col=0, parse_dates=True).dropna(how="all")
COST = 0.0010
SECTORS = ["XLK", "XLF", "XLE", "XLV", "XLP", "XLI", "XLU"]
STOCKS = [c for c in px.columns if c not in SECTORS + ["SPY", "QQQ", "IWM", "TLT", "IEF", "GLD", "SHV"]]

n = len(px)
i_tr, i_ho = int(n * 0.55), int(n * 0.80)
W = {"train": px.index[:i_tr], "holdout": px.index[i_tr:i_ho], "final": px.index[i_ho:]}
print("windows:", {k: f"{v[0].date()}->{v[-1].date()}" for k, v in W.items()})

BEARS = {"2018Q4": ("2018-09-20", "2018-12-24"),
         "covid": ("2020-02-19", "2020-03-23"),
         "2022 bear": ("2022-01-03", "2022-10-12")}
BULLS = {"2019 bull": ("2019-01-01", "2020-02-19"),
         "2023-24 bull": ("2023-01-01", "2024-12-31")}

rets = px.pct_change().fillna(0.0)

def metrics(eq):
    eq = eq.dropna()
    if len(eq) < 30: return None
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1
    r = eq.pct_change().dropna()
    sharpe = r.mean() / (r.std() + 1e-12) * np.sqrt(252)
    dd = (eq / eq.cummax() - 1).min()
    return {"cagr": round(float(cagr), 3), "sharpe": round(float(sharpe), 2),
            "maxdd": round(float(dd), 3)}

def run(w: pd.DataFrame) -> pd.Series:
    w = w.shift(1).fillna(0.0)
    port = (w * rets[w.columns]).sum(axis=1)
    port -= w.diff().abs().sum(axis=1).fillna(0.0) * COST
    return (1 + port).cumprod()

def defensive_weights(idx, mode):
    """what to hold when risk assets are gated off"""
    w = pd.DataFrame(0.0, index=idx, columns=px.columns)
    if mode == "cash":
        return w
    if mode in ("TLT", "GLD"):
        w[mode] = 1.0
        return w
    if mode == "gld_shv":
        w["GLD"] = 0.5; w["SHV"] = 0.5
        return w
    if mode == "best":  # best of TLT/GLD/SHV by 3m momentum (defensive momentum)
        mom = px[["TLT", "GLD", "SHV"]].pct_change(63)
        has = mom.notna().any(axis=1)
        b = mom[has].idxmax(axis=1).reindex(idx)
        for c in ("TLT", "GLD", "SHV"):
            w[c] = (b == c).astype(float)
        return w
    raise ValueError(mode)

def strat_trend(ma_n=200, defensive="cash", vt=None):
    """SPY when above its MA, defensive otherwise."""
    on = (px["SPY"] > px["SPY"].rolling(ma_n).mean()).astype(float)
    w = pd.DataFrame(0.0, index=px.index, columns=px.columns)
    w["SPY"] = on
    dw = defensive_weights(px.index, defensive)
    w = w.add(dw.mul(1 - on, axis=0), fill_value=0.0)
    if vt:
        rvol = px["SPY"].pct_change().rolling(20).std() * np.sqrt(252)
        w = w.mul((vt / rvol).clip(upper=1.0).fillna(0.0) * on + (1 - on), axis=0)
    return w

def strat_trend_short(ma_n=200, short=0.3):
    on = (px["SPY"] > px["SPY"].rolling(ma_n).mean()).astype(float)
    w = pd.DataFrame(0.0, index=px.index, columns=px.columns)
    w["SPY"] = on - short * (1 - on)          # long above trend, small short below
    w["SHV"] = (1 - on)                        # cash parked in bills while short
    return w

def strat_sector(k=3, mom_n=126, ma_n=200, defensive="best"):
    """monthly: top-k sector ETFs by momentum if positive AND SPY>MA; else defensive."""
    me = px.resample("ME").last().index
    mom = px[SECTORS].pct_change(mom_n)
    spy_on = px["SPY"] > px["SPY"].rolling(ma_n).mean()
    w = pd.DataFrame(0.0, index=px.index, columns=px.columns)
    monthly = pd.DataFrame(0.0, index=me, columns=px.columns)
    for d in me:
        i = px.index.asof(d)
        if pd.isna(i): continue
        row = mom.loc[i].dropna()
        picks = row[row > 0].nlargest(k)
        if spy_on.loc[i] and len(picks):
            for c in picks.index:
                monthly.loc[d, c] = 1.0 / k
            monthly.loc[d, "SHV"] = 1.0 - len(picks) / k
        else:
            dm = px[["TLT", "GLD", "SHV"]].pct_change(63).loc[i]
            if defensive == "best" and dm.notna().any():
                monthly.loc[d, dm.idxmax()] = 1.0
    return monthly.reindex(px.index).ffill().fillna(0.0)

def strat_stockmom(k=8, ma_n=200, defensive="best"):
    """monthly: top-k stocks by 12-1 momentum, gated by SPY trend (SURVIVORSHIP-FLATTERED)."""
    me = px.resample("ME").last().index
    mom = px[STOCKS].pct_change(252) - px[STOCKS].pct_change(21)
    spy_on = px["SPY"] > px["SPY"].rolling(ma_n).mean()
    monthly = pd.DataFrame(0.0, index=me, columns=px.columns)
    for d in me:
        i = px.index.asof(d)
        if pd.isna(i): continue
        row = mom.loc[i].dropna()
        picks = row[row > 0].nlargest(k)
        if spy_on.loc[i] and len(picks):
            for c in picks.index:
                monthly.loc[d, c] = 1.0 / max(k, len(picks))
        else:
            dm = px[["TLT", "GLD", "SHV"]].pct_change(63).loc[i]
            if defensive == "best" and dm.notna().any():
                monthly.loc[d, dm.idxmax()] = 1.0
    return monthly.reindex(px.index).ffill().fillna(0.0)

CANDS = {}
for ma_n in (150, 200):
    for dfn in ("cash", "TLT", "GLD", "gld_shv", "best"):
        CANDS[f"trend{ma_n}/{dfn}"] = strat_trend(ma_n, dfn)
        CANDS[f"trend{ma_n}/{dfn}/vt15"] = strat_trend(ma_n, dfn, vt=0.15)
for k in (2, 3):
    for mn in (126, 189):
        CANDS[f"sector{k}/m{mn}"] = strat_sector(k, mn)
CANDS["trend200/short30"] = strat_trend_short(200, 0.3)
CANDS["trend150/short30"] = strat_trend_short(150, 0.3)
CANDS["stockmom8"] = strat_stockmom(8)
CANDS["stockmom5"] = strat_stockmom(5)

bench_eq = {"SPY hold": run(pd.DataFrame({"SPY": 1.0}, index=px.index).reindex(columns=px.columns, fill_value=0.0)),
            "QQQ hold": run(pd.DataFrame({"QQQ": 1.0}, index=px.index).reindex(columns=px.columns, fill_value=0.0)),
            "60/40": run(pd.DataFrame({"SPY": 0.6, "IEF": 0.4}, index=px.index).reindex(columns=px.columns, fill_value=0.0))}
print("\nbenchmarks:")
for nm, eq in bench_eq.items():
    m = {k: metrics(eq.loc[w]) for k, w in W.items()}
    bears = {b: round(float(eq.loc[s:e].iloc[-1] / eq.loc[s:e].iloc[0] - 1), 3) for b, (s, e) in BEARS.items()}
    print(f"  {nm:16s} train {m['train']} holdout {m['holdout']} final {m['final']} bears {bears}")

rows = []
for nm, wdf in CANDS.items():
    eq = run(wdf)
    m = {k: metrics(eq.loc[w]) for k, w in W.items()}
    ok = m["train"]["maxdd"] > -0.25 and m["holdout"]["maxdd"] > -0.25
    rows.append({"name": nm, "eq": eq, **{k: m[k] for k in ("train", "holdout")}, "survives": ok})

print("\nall candidates (bears shown for the screen-failers too):")
for r in sorted(rows, key=lambda r: r["holdout"]["cagr"], reverse=True):
    eqx = r["eq"]
    bears = {b: round(float(eqx.loc[s0:e0].iloc[-1] / eqx.loc[s0:e0].iloc[0] - 1), 3)
             for b, (s0, e0) in BEARS.items()}
    print(f"  {'PASS' if r['survives'] else 'fail'} {r['name']:22s} train {r['train']} holdout {r['holdout']} bears {bears}")

surv = [r for r in rows if r["survives"]]
surv.sort(key=lambda r: r["train"]["cagr"] / max(0.03, -r["train"]["maxdd"]), reverse=True)
top = surv[:8]
top.sort(key=lambda r: r["holdout"]["cagr"] / max(0.03, -r["holdout"]["maxdd"]), reverse=True)
print(f"\n{len(surv)}/{len(rows)} survive DD screen; top (train-ranked, holdout-verified):")
for r in top[:6]:
    print(f"  {r['name']:20s} train {r['train']} holdout {r['holdout']}")

pick = top[0]
eq = pick["eq"]
print(f"\nCHOSEN: {pick['name']}")
print("final (untouched):", metrics(eq.loc[W["final"]]))
print("bears:", {b: round(float(eq.loc[s:e].iloc[-1] / eq.loc[s:e].iloc[0] - 1), 3) for b, (s, e) in BEARS.items()})
print("bulls:", {b: round(float(eq.loc[s:e].iloc[-1] / eq.loc[s:e].iloc[0] - 1), 3) for b, (s, e) in BULLS.items()})
print("full-period:", metrics(eq))
