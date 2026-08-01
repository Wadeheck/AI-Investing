"""Cross-era stress test for the mechanical trend sleeve (transcript-4).

The lockbox burn (2026-08-01) showed the stock core has no bear protection:
−34% dd vs the 25% limit. The candidate fix is the R33/R34 winter gate —
SPY under its moving average trims the core into a defensive asset. That
mechanic is a published, decades-old strategy family, so unlike the news
layers it CAN be judged on history far outside our 3-year corpus. This
script replays the mechanical proxy through every major regime since 1995:
dot-com bust, GFC, the whole 2000-09 lost decade, 2011, 2015-16, 2018Q4,
covid, the 2022 bear — and the bull runs in between (a gate that dodges
bears by sleeping through bulls is not protection, it's absence).

Free daily data only. Gold before GLD's 2004 inception is spliced from
GC=F futures (scaled to match at the joint); TLT starts mid-2002 —
defensive picks fall back to cash while a series doesn't exist yet.
Costs 10 bps per side on all turnover. Weights lag signals by one day
(decide on close, trade next day). No parameter here was ever tuned on
the burned lockbox window; this is pre-2023-heavy history.

Run:  .venv/bin/python -m ai_investing.research.stress_eras
Writes a JSON summary to data/stress_eras.json.
"""
import json
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd
import yfinance as yf

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
COST = 0.0010            # 10 bps per side, deliberately fatter than US reality

BEARS = {"dotcom 00-02":  ("2000-03-24", "2002-10-09"),
         "GFC 07-09":     ("2007-10-09", "2009-03-09"),
         "lost decade":   ("2000-01-01", "2009-12-31"),
         "2011 crash":    ("2011-04-29", "2011-10-03"),
         "2015-16":       ("2015-05-21", "2016-02-11"),
         "2018Q4":        ("2018-09-20", "2018-12-24"),
         "covid":         ("2020-02-19", "2020-03-23"),
         "2022 bear":     ("2022-01-03", "2022-10-12")}
BULLS = {"95-00 bull":    ("1995-01-03", "2000-03-24"),
         "03-07 bull":    ("2003-03-11", "2007-10-09"),
         "09-20 bull":    ("2009-03-09", "2020-02-19"),
         "23-24 bull":    ("2023-01-03", "2024-12-31")}


def fetch():
    raw = yf.download(["SPY", "QQQ", "GLD", "TLT", "IEF", "GC=F"],
                      start="1994-01-01", auto_adjust=True, progress=False)["Close"]
    raw = raw.dropna(how="all")
    px = pd.DataFrame(index=raw.index)
    px["SPY"], px["QQQ"] = raw["SPY"], raw["QQQ"]
    px["TLT"], px["IEF"] = raw["TLT"], raw["IEF"]
    # gold: GLD once it exists, GC=F scaled to meet it before that
    gld, gc = raw["GLD"].dropna(), raw["GC=F"].dropna()
    if len(gld) and len(gc):
        j = gld.index[0]
        pre = gc.loc[:j]
        scale = gld.iloc[0] / pre.iloc[-1]
        px["GOLD"] = pd.concat([pre.iloc[:-1] * scale, gld]).reindex(px.index)
    else:
        px["GOLD"] = raw["GLD"].reindex(px.index)
    return px.ffill(limit=5)


def regime(px, ma_n, band):
    """Daily risk-on flag with the trainer's hysteresis: winter starts on a
    clear break BELOW ma*(1-band), ends only on a clean reclaim of the ma."""
    spy, ma = px["SPY"], px["SPY"].rolling(ma_n).mean()
    on, cur = [], True
    for p, m in zip(spy.values, ma.values):
        if np.isnan(m):
            cur = True
        elif cur and p < m * (1.0 - band):
            cur = False
        elif not cur and p >= m:
            cur = True
        on.append(cur)
    return pd.Series(on, index=px.index, dtype=float)


def defensive_col(px, mode):
    """Which column shelters the trimmed sleeve each day (None = cash).
    'best' = higher trailing 63d momentum of GOLD vs TLT, cash if neither."""
    if mode == "cash":
        return pd.Series(None, index=px.index, dtype=object)
    if mode in ("GOLD", "TLT"):
        return pd.Series(np.where(px[mode].notna(), mode, None), index=px.index)
    mom = px[["GOLD", "TLT"]].pct_change(63)
    has = mom.notna().any(axis=1)
    pick = pd.Series(None, index=px.index, dtype=object)
    pick[has] = mom[has].fillna(-np.inf).idxmax(axis=1)
    return pick


def weights(px, ma_n, band, trim, dmode):
    on = regime(px, ma_n, band)
    dcol = defensive_col(px, dmode)
    w = pd.DataFrame(0.0, index=px.index, columns=px.columns)
    w["SPY"] = on + (1 - on) * (1 - trim)
    off = (1 - on) * trim
    for c in ("GOLD", "TLT"):
        w[c] = w.get(c, 0.0) + off * (dcol == c).astype(float)
    return w


def equity(px, w):
    rets = px.pct_change().fillna(0.0)
    w = w.shift(1).fillna(0.0)                       # decide close, trade next day
    port = (w * rets).sum(axis=1)
    port -= w.diff().abs().sum(axis=1).fillna(0.0) * COST
    return (1 + port).cumprod()


def metrics(eq):
    eq = eq.dropna()
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    r = eq.pct_change().dropna()
    return {"cagr": round(float((eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1), 3),
            "sharpe": round(float(r.mean() / (r.std() + 1e-12) * np.sqrt(252)), 2),
            "maxdd": round(float((eq / eq.cummax() - 1).min()), 3)}


def era_returns(eq, eras):
    out = {}
    for name, (s, e) in eras.items():
        seg = eq.loc[s:e]
        if len(seg) < 10:
            out[name] = None
            continue
        out[name] = {"ret": round(float(seg.iloc[-1] / seg.iloc[0] - 1), 3),
                     "maxdd": round(float((seg / seg.cummax() - 1).min()), 3)}
    return out


def main():
    px = fetch()
    print(f"data: {px.index[0].date()} -> {px.index[-1].date()}, "
          f"{len(px)} days  (GOLD spliced GC=F->GLD; TLT from "
          f"{px['TLT'].first_valid_index().date()})")

    results = []
    for ma_n in (100, 150, 200):
        for band in (0.0, 0.02):
            for trim in (0.5, 0.8, 1.0):
                for dmode in ("cash", "GOLD", "TLT", "best"):
                    eq = equity(px, weights(px, ma_n, band, trim, dmode))
                    r = {"name": f"ma{ma_n}/b{band:g}/t{trim:g}/{dmode}",
                         "ma": ma_n, "band": band, "trim": trim, "def": dmode,
                         "full": metrics(eq),
                         "bears": era_returns(eq, BEARS),
                         "bulls": era_returns(eq, BULLS)}
                    bear_worst = min(v["ret"] for v in r["bears"].values() if v)
                    bear_dd = min(v["maxdd"] for v in r["bears"].values() if v)
                    r["worst_bear"] = bear_worst
                    # strict screen: every bear era held above -20%, full-history
                    # drawdown inside -30% (tighter than SPY's -55% GFC).
                    r["survives"] = (bear_worst > -0.20
                                     and r["full"]["maxdd"] > -0.30)
                    # user-mandate screen: no bear era ever breaches the 25%
                    # continuous-drawdown rule (full-history dd reported, not
                    # screened — 30 years of one asset is a stricter game than
                    # the engine's capped, vol-sized, multi-asset book plays)
                    r["survives_25"] = bear_dd > -0.25
                    results.append(r)

    bench = {}
    for b in ("SPY", "QQQ"):
        w = pd.DataFrame(0.0, index=px.index, columns=px.columns)
        w[b] = px[b].notna().astype(float)
        eq = equity(px, w)
        bench[b] = {"full": metrics(eq.loc[px[b].first_valid_index():]),
                    "bears": era_returns(eq, BEARS), "bulls": era_returns(eq, BULLS)}
        bb = " ".join(f"{k}:{v['ret']:+.0%}" for k, v in bench[b]["bears"].items() if v)
        print(f"\n{b} hold  full {bench[b]['full']}  bears {bb}")

    surv = [r for r in results if r["survives"]]
    print(f"\n{len(surv)}/{len(results)} variants survive the STRICT screen "
          f"(every bear > -20%, full maxdd > -30%)")
    surv25 = [r for r in results if r["survives_25"]]
    print(f"{len(surv25)}/{len(results)} variants keep every bear era inside "
          f"the user's 25% drawdown rule")
    if not surv:                  # no survivors: still show the honest ranking
        surv = surv25 or results

    def score(r):     # preservation-first, same spirit as the trainer objective
        return r["full"]["cagr"] - 2.0 * abs(r["full"]["maxdd"])

    print("\ntop variants (preservation-first score):")
    for r in sorted(surv, key=score, reverse=True)[:12]:
        bb = " ".join(f"{k}:{v['ret']:+.0%}" for k, v in r["bears"].items()
                      if v and k in ("dotcom 00-02", "GFC 07-09", "2022 bear"))
        bl = " ".join(f"{k}:{v['ret']:+.0%}" for k, v in r["bulls"].items()
                      if v and k in ("09-20 bull", "23-24 bull"))
        print(f"  {r['name']:22s} full {r['full']}  {bb}  |  {bl}")

    # plateau view: does the neighborhood agree, or is one setting lucky?
    print("\nplateau check — mean score / survival rate along each axis:")
    df = pd.DataFrame([{**{k: r[k] for k in ("ma", "band", "trim", "def")},
                        "score": score(r), "ok": r["survives"]} for r in results])
    for axis in ("ma", "band", "trim", "def"):
        g = df.groupby(axis).agg(score=("score", "mean"), surv=("ok", "mean"))
        row = "  ".join(f"{ix}: {v.score:+.3f} ({v.surv:.0%})" for ix, v in g.iterrows())
        print(f"  {axis:5s} {row}")

    out = {"generated": str(px.index[-1].date()), "cost_per_side": COST,
           "benchmarks": bench, "screen": "bears>-20%, full maxdd>-30%",
           "survivors": len(surv), "total": len(results),
           "results": [{k: v for k, v in r.items()} for r in results]}
    (DATA_DIR / "stress_eras.json").write_text(json.dumps(out, indent=1))
    print(f"\nwrote {DATA_DIR / 'stress_eras.json'}")


if __name__ == "__main__":
    main()
