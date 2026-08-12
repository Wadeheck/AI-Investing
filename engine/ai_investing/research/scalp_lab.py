"""Scalp lab — rebuild the fast sleeve on evidence instead of doc folklore.

Why this file exists (2026-08-12). The 2026-08-01 module traded 5-minute
structure and lost on the holdout. The edge study that motivated the rebuild
separated the two possible causes, and found:

  1. Fee drag is exactly  fee_R = round_trip_bps / stop_bps.  The old module
     floored stops at 45bps, so EVERY trade handed 20% of its risk budget to
     the exchange. Because 5m ATR on majors is ~8bps, even a "3x ATR" stop hit
     that floor -- the old stop-width sweep was one single trade repeated.
  2. S1_sweep (96% of all signals) has NO gross edge: at an 800bps stop, where
     fees are ~1% of R, holdout expectancy is still negative with t ~ -3.
     No exit geometry rescues a signal with no direction.
  3. The only family with gross edge, S2_retest, made its money over HOURS
     (+45bps mean at 4h, t=3.0) -- i.e. it is not a scalp at all, and its
     holdout sample was 25 trades, far too few to fund.

So the rebuild moves the sleeve to 15m structure with stops wide enough that
fees are a rounding error, tests on 12 symbols x 240d (~16x the old sample),
and picks configs on TRAIN ONLY before a single holdout evaluation.

Run:  cd engine && ../.venv/bin/python -m ai_investing.research.scalp_lab [--build]
"""
from __future__ import annotations

import json
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(__file__).resolve().parents[3] / "data"
HIST = DATA / "scalp_history_wide"
CACHE = DATA / "scalp_lab_cache.pkl"
SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT",
        "ADAUSDT", "AVAXUSDT", "LINKUSDT", "LTCUSDT", "DOTUSDT", "NEARUSDT"]

# --- cost scenarios --------------------------------------------------------
# The original module assumed Binance USDT-perp fees (2/5bps). But .env sets
# CRYPTO_EXCHANGE=gemini, and execution/costs.py already charges this repo's own
# crypto book 15bps per side. A sleeve that only works at 2bps is not a strategy
# this account can trade, so the gate runs under all three.
COST_SCENARIOS = {
    # aspirational: Binance USDT-perp public schedule (needs an account this
    # SG-resident book may not be able to open — Binance.com is not MAS-licensed)
    "binance_perp": {"maker": 2.0, "taker": 5.0, "slip": 2.0, "fund8h": 1.5},
    # what the rest of this engine charges itself for crypto (costs.py)
    "repo_crypto":  {"maker": 15.0, "taker": 15.0, "slip": 0.0, "fund8h": 0.0},
    # Gemini ActiveTrader, low monthly volume — the venue actually configured
    "gemini_real":  {"maker": 25.0, "taker": 35.0, "slip": 5.0, "fund8h": 0.0},
}
MAKER_BPS, TAKER_BPS, SLIP_BPS, FUND_BPS_8H = 2.0, 5.0, 2.0, 1.5


def set_costs(name: str) -> None:
    global MAKER_BPS, TAKER_BPS, SLIP_BPS, FUND_BPS_8H
    c = COST_SCENARIOS[name]
    MAKER_BPS, TAKER_BPS = c["maker"], c["taker"]
    SLIP_BPS, FUND_BPS_8H = c["slip"], c["fund8h"]
TTL_BARS = 4               # unfilled 15m limit dies after 1h
PURGE_BARS = 96            # 24h purge gap between train and holdout
TRAIN_FRAC = 0.70
RISK_FRAC = 0.005          # 0.5% of book risked per trade

# Pre-committed BEFORE the holdout was ever evaluated (same discipline that
# killed the first module). Config selection happens on train only; the
# holdout is touched exactly once, by these rules:
GATE_TEXT = ("holdout meanR>0 AND t>=2.0 AND >=60% of symbols positive AND "
             "daily Sharpe>=0.5 AND holdout keeps train's sign at >=40% of "
             "its size")


# =========================== data / indicators =============================
def load(sym: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    df1 = pd.read_csv(HIST / f"{sym}_1m.csv")
    df1.index = pd.to_datetime(df1["ts"], unit="ms", utc=True)
    df1 = df1.drop(columns=["ts"]).astype(float)
    o = df1.resample("15min")
    d = pd.DataFrame({"open": o["open"].first(), "high": o["high"].max(),
                      "low": o["low"].min(), "close": o["close"].last(),
                      "vol": o["vol"].sum(),
                      "taker_buy_vol": o["taker_buy_vol"].sum()}).dropna(subset=["close"])
    return df1, enrich(d)


def enrich(d: pd.DataFrame) -> pd.DataFrame:
    c, h, l, v = d["close"], d["high"], d["low"], d["vol"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    d["atr"] = tr.rolling(14, min_periods=7).mean()
    d["atr_bps"] = d["atr"] / c * 1e4
    d["ema20"] = c.ewm(span=20, adjust=False).mean()
    d["ema50"] = c.ewm(span=50, adjust=False).mean()
    d["rvol"] = v / (v.rolling(96, min_periods=30).mean() + 1e-12)
    d["delta"] = 2.0 * d["taker_buy_vol"] - v
    d["delta_z"] = d["delta"] / (d["delta"].rolling(96, min_periods=30).std() + 1e-12)
    d["cvd"] = d["delta"].cumsum()
    d["ret24"] = c / c.shift(96) - 1.0
    d["don_hi"] = h.rolling(96, min_periods=48).max().shift(1)
    d["don_lo"] = l.rolling(96, min_periods=48).min().shift(1)
    pv = (c * v).rolling(96, min_periods=30).sum()
    d["vwap24"] = pv / (v.rolling(96, min_periods=30).sum() + 1e-12)
    d["dev_vwap"] = (c / d["vwap24"] - 1.0) * 1e4
    return d


# =============================== signals ===================================
# Every signal returns (side, entry_price) or None, using bars strictly < i.

def sig_breakout(d, i, p):
    """Donchian 24h breakout, volume-confirmed, trend-aligned. Continuation."""
    b = d.iloc[i - 1]
    if b["rvol"] < p["rvol"] or b["atr_bps"] != b["atr_bps"]:
        return None
    if b["close"] > b["don_hi"] and b["close"] > b["ema50"]:
        return 1, float(b["close"]) - p["pull"] * float(b["atr"])
    if b["close"] < b["don_lo"] and b["close"] < b["ema50"]:
        return -1, float(b["close"]) + p["pull"] * float(b["atr"])
    return None


def sig_retest(d, i, p):
    """S2 scaled to 15m: break a 24h extreme, then a bar whose body holds it."""
    if i < 4:
        return None
    brk, rt = d.iloc[i - 2], d.iloc[i - 1]
    if brk["rvol"] < p["rvol"]:
        return None
    up = (brk["close"] > brk["don_hi"] and rt["low"] <= brk["don_hi"]
          and min(rt["open"], rt["close"]) > brk["don_hi"])
    dn = (brk["close"] < brk["don_lo"] and rt["high"] >= brk["don_lo"]
          and max(rt["open"], rt["close"]) < brk["don_lo"])
    if up:
        return 1, float(brk["don_hi"])
    if dn:
        return -1, float(brk["don_lo"])
    return None


def sig_revert(d, i, p):
    """Stretched-from-VWAP fade with order-flow exhaustion. Tests whether
    mean-reversion works at 15m scale where it failed at 5m."""
    b = d.iloc[i - 1]
    dv, dz = float(b["dev_vwap"]), float(b["delta_z"])
    if dv != dv or dz != dz:
        return None
    if dv > p["dev"] and dz > p["dz"]:
        return -1, float(b["close"]) + p["pull"] * float(b["atr"])
    if dv < -p["dev"] and dz < -p["dz"]:
        return 1, float(b["close"]) - p["pull"] * float(b["atr"])
    return None


SIGNALS = {"breakout": sig_breakout, "retest": sig_retest, "revert": sig_revert}
GRID = {
    "breakout": [{"rvol": r, "pull": q} for r in (1.2, 1.6, 2.0) for q in (0.0, 0.3)],
    "retest":   [{"rvol": r, "pull": 0.0} for r in (1.0, 1.3, 1.8)],
    "revert":   [{"dev": dv, "dz": z, "pull": 0.3}
                 for dv in (150, 250, 400) for z in (1.0, 2.0)],
}


# ============================== evaluation =================================
def collect_paths(sym, df1, d, name, params, horizon_min):
    """For every signal, simulate the maker fill on the 1m tape and record the
    forward favourable/adverse excursion path (fractional, signed by side)."""
    fn = SIGNALS[name]
    hi, lo = df1["high"].values, df1["low"].values
    pos = {t: k for k, t in enumerate(df1.index)}
    out = []
    for i in range(100, len(d)):
        s = fn(d, i, params)
        if s is None:
            continue
        side, entry = s
        atr_bps = float(d["atr_bps"].iloc[i - 1])
        if atr_bps != atr_bps or atr_bps <= 0 or entry <= 0:
            continue
        k0 = pos.get(d.index[i])
        if k0 is None:
            continue
        w_lo, w_hi = lo[k0:k0 + TTL_BARS * 15], hi[k0:k0 + TTL_BARS * 15]
        hit = np.where(w_lo <= entry)[0] if side > 0 else np.where(w_hi >= entry)[0]
        if not len(hit):
            continue
        f = k0 + int(hit[0])
        fh, fl = hi[f:f + horizon_min], lo[f:f + horizon_min]
        if len(fh) < 120:
            continue
        up, dn = (fh - entry) / entry, (fl - entry) / entry
        fav, adv = (up, dn) if side > 0 else (-dn, -up)
        out.append({"sym": sym, "bar": i, "ts": d.index[i], "side": side,
                    "atr_bps": atr_bps,
                    "fav": fav.astype(np.float32), "adv": adv.astype(np.float32)})
    return out


def outcome(r, stop_bps, rr, tmax):
    """First-touch on the 1m tape; same-minute tie resolves to the stop.
    Returns (R_net, hold_minutes). Costs charged per exit type + funding."""
    s, t = stop_bps / 1e4, stop_bps / 1e4 * rr
    fav, adv = r["fav"][:tmax], r["adv"][:tmax]
    tk = np.argmax(fav >= t) if (fav >= t).any() else 10**9
    sk = np.argmax(adv <= -s) if (adv <= -s).any() else 10**9
    if sk <= tk and sk < 10**9:
        gross, hold, exit_bps = -1.0, int(sk) + 1, TAKER_BPS + SLIP_BPS
    elif tk < sk:
        gross, hold, exit_bps = rr, int(tk) + 1, MAKER_BPS
    else:
        gross = float(fav[-1] + adv[-1]) / 2.0 / s     # time exit ~ mid
        hold, exit_bps = len(fav), TAKER_BPS + SLIP_BPS
    fee_R = (MAKER_BPS + exit_bps) / stop_bps
    fund_R = (FUND_BPS_8H * hold / 480.0) / stop_bps
    return gross - fee_R - fund_R, hold


def evaluate(rows, stop_mult, rr, hours, floor_bps):
    """Aggregate R stats. stop = max(stop_mult * ATR_bps, floor_bps)."""
    tmax = hours * 60
    out = []
    for r in rows:
        sb = max(stop_mult * r["atr_bps"], floor_bps)
        R, hold = outcome(r, sb, rr, tmax)
        out.append((r["ts"], r["sym"], R, hold, sb))
    return out


def stats(recs):
    if len(recs) < 10:
        return None
    R = np.array([x[2] for x in recs])
    se = R.std() / np.sqrt(len(R))
    return {"n": len(R), "meanR": float(R.mean()), "t": float(R.mean() / (se + 1e-12)),
            "wr": float((R > 0).mean()), "medhold": float(np.median([x[3] for x in recs])),
            "stopbps": float(np.median([x[4] for x in recs]))}


def build_cache():
    horizon = 24 * 60
    cache = {}
    for sym in SYMS:
        if not (HIST / f"{sym}_1m.csv").exists():
            print(f"skip {sym}: no data"); continue
        df1, d = load(sym)
        for name, plist in GRID.items():
            for pi, params in enumerate(plist):
                cache.setdefault((name, pi), []).extend(
                    collect_paths(sym, df1, d, name, params, horizon))
        print(f"{sym}: cached {sum(len(v) for v in cache.values())} paths", flush=True)
    pickle.dump({"cache": cache, "grid": GRID}, open(CACHE, "wb"))
    return cache


def main(cache=None, scenario="binance_perp"):
    set_costs(scenario)
    print(f"\n################ COST SCENARIO: {scenario} "
          f"(maker {MAKER_BPS} / taker {TAKER_BPS} / slip {SLIP_BPS} bps) "
          f"################")
    if cache is None:
        cache = (build_cache() if ("--build" in sys.argv or not CACHE.exists())
                 else pickle.load(open(CACHE, "rb"))["cache"])

    all_ts = sorted({r["ts"] for v in cache.values() for r in v})
    split = all_ts[int(len(all_ts) * TRAIN_FRAC)]
    purge_end = split + pd.Timedelta(minutes=15 * PURGE_BARS)
    print(f"\nsplit {split} (holdout starts {purge_end} after purge)\n")

    # ---- stage 1: pick ONE config per family on TRAIN ONLY -----------------
    exits = [(sm, rr, hrs) for sm in (2.0, 3.0, 4.0) for rr in (1.0, 1.5, 2.0, 3.0)
             for hrs in (6, 12, 24)]
    picks = {}
    print(f"{'family':10s} {'cfg':>3} {'stopX':>5} {'RR':>4} {'hrs':>4} | "
          f"{'trainR':>8} {'t':>6} {'n':>6} {'wr':>5} {'stopbps':>7}")
    for name, plist in GRID.items():
        best = None
        for pi in range(len(plist)):
            rows = cache.get((name, pi), [])
            tr_rows = [r for r in rows if r["ts"] < split]
            for sm, rr, hrs in exits:
                recs = evaluate(tr_rows, sm, rr, hrs, floor_bps=100.0)
                st = stats(recs)
                if st is None or st["n"] < 200:
                    continue
                score = st["t"]
                if best is None or score > best[0]:
                    best = (score, pi, sm, rr, hrs, st)
        if best:
            _, pi, sm, rr, hrs, st = best
            picks[name] = {"pi": pi, "params": plist[pi], "stop_mult": sm,
                           "rr": rr, "hours": hrs, "train": st}
            print(f"{name:10s} {pi:3d} {sm:5.1f} {rr:4.1f} {hrs:4d} | "
                  f"{st['meanR']:+8.3f} {st['t']:+6.2f} {st['n']:6d} "
                  f"{st['wr']:5.0%} {st['stopbps']:7.0f}")
    # ---- stage 2: ONE holdout evaluation, gate pre-committed above ---------
    print(f"\n=== HOLDOUT (gate: {GATE_TEXT}) ===")
    report = {"split": str(split), "gate": GATE_TEXT, "families": {}}
    for name, pk in picks.items():
        rows = [r for r in cache.get((name, pk["pi"]), []) if r["ts"] >= purge_end]
        recs = evaluate(rows, pk["stop_mult"], pk["rr"], pk["hours"], 100.0)
        st = stats(recs)
        if st is None:
            print(f"{name:10s} too few holdout trades"); continue
        book = curve(recs, RISK_FRAC)
        per_sym = {}
        for s in sorted({x[1] for x in recs}):
            ss = stats([x for x in recs if x[1] == s])
            if ss:
                per_sym[s] = round(ss["meanR"], 4)
        pos_frac = (np.mean([v > 0 for v in per_sym.values()])
                    if per_sym else 0.0)
        tr = pk["train"]
        ships = bool(st["meanR"] > 0 and st["t"] >= 2.0 and pos_frac >= 0.6
                     and book["sharpe"] >= 0.5
                     and np.sign(st["meanR"]) == np.sign(tr["meanR"])
                     and abs(st["meanR"]) >= 0.4 * abs(tr["meanR"]))
        report["families"][name] = {
            "config": {k: pk[k] for k in ("params", "stop_mult", "rr", "hours")},
            "train": tr, "holdout": st, "curve": book,
            "per_symbol_R": per_sym, "symbols_positive": round(float(pos_frac), 2),
            "ships": ships}
        print(f"{name:10s} holdR {st['meanR']:+.3f} t {st['t']:+.2f} n {st['n']:5d} "
              f"wr {st['wr']:.0%} | net {book['net']:+.2%} sharpe {book['sharpe']:+.2f} "
              f"maxdd {book['maxdd']:.2%} | syms+ {pos_frac:.0%} -> "
              f"{'SHIPS' if ships else 'killed'}")
    out = DATA / f"scalp_lab_report_{scenario}.json"
    out.write_text(json.dumps(report, indent=1, default=str))
    print(f"wrote {out}")
    return report


def cost_vs_move(syms=None):
    """The ruling arithmetic, before any strategy question.

    Over a holding period h, the tradable move is bounded by how far price
    actually travels in h. Round-trip cost is fixed. So the fraction of the
    average move a strategy must capture just to break even is

        capture_required = round_trip_bps / E|return over h|

    Above ~100% the trade is arithmetically impossible: you would have to
    capture more than the entire average move, every time, to pay the fees.
    This is why a faster clock does not mean faster money — the cost is
    per-trade and constant, while the opportunity shrinks with the clock.
    """
    syms = syms or SYMS
    hs = [(15, "15m"), (60, "1h"), (240, "4h"), (1440, "1d"), (4320, "3d")]
    moves = {}
    for lbl in [x[1] for x in hs]:
        moves[lbl] = []
    for sym in syms:
        p = HIST / f"{sym}_1m.csv"
        if not p.exists():
            continue
        d = pd.read_csv(p, usecols=["ts", "close"])
        d.index = pd.to_datetime(d["ts"], unit="ms", utc=True)
        c = d["close"]
        for mins, lbl in hs:
            r = (c.shift(-mins) / c - 1.0).abs().dropna()
            moves[lbl].append(float(r.mean()) * 1e4)
    print("\n=== cost vs opportunity: % of the average move you must capture "
          "just to break even ===")
    print(f"{'hold':>6} {'avg |move|':>11} | " +
          " | ".join(f"{k:>13}" for k in COST_SCENARIOS))
    for _, lbl in hs:
        if not moves[lbl]:
            continue
        mv = float(np.mean(moves[lbl]))
        cells = []
        for name, c in COST_SCENARIOS.items():
            rt = c["maker"] + c["taker"] + c["slip"]
            cells.append(f"{rt / mv:12.0%} ")
        print(f"{lbl:>6} {mv:9.0f}bps | " + " | ".join(cells))
    print("(round trip = maker in + taker/slip out; funding excluded)")


def xsmom(train_only: bool = False):
    """Cross-sectional momentum on the panel — the fastest clock at which crypto
    has a well-documented edge, and the natural benchmark any per-symbol scalp
    signal has to beat. Rank symbols by trailing return, long the top k / short
    the bottom k, dollar-neutral, rebalance every `every` hours.

    Costs are turnover-based and honest: every unit of weight changed pays
    taker+slip, and gross notional pays perp funding for the time it is held.
    """
    px = {}
    for sym in SYMS:
        p = HIST / f"{sym}_1m.csv"
        if not p.exists():
            continue
        d = pd.read_csv(p, usecols=["ts", "close"])
        d.index = pd.to_datetime(d["ts"], unit="ms", utc=True)
        px[sym] = d["close"].resample("1h").last()
    panel = pd.DataFrame(px).dropna()
    print(f"\n=== cross-sectional momentum: {panel.shape[1]} symbols, "
          f"{len(panel)} hourly bars ===")
    split_i = int(len(panel) * TRAIN_FRAC)
    rets = panel.pct_change()
    results = []
    for look in (12, 24, 48, 96, 168):
        for every in (4, 8, 24):
            for k in (2, 3):
                if 2 * k > panel.shape[1] - 1:
                    continue      # long and short legs would overlap
                sig = panel.pct_change(look)
                w = pd.DataFrame(0.0, index=panel.index, columns=panel.columns)
                reb = range(look, len(panel), every)
                cur = pd.Series(0.0, index=panel.columns)
                for i in reb:
                    s = sig.iloc[i]
                    if s.isna().any():
                        continue
                    r = s.rank(ascending=False)
                    cur = pd.Series(0.0, index=panel.columns)
                    cur[r <= k] = 0.5 / k
                    cur[r > len(s) - k] = -0.5 / k
                    w.iloc[i:i + every] = cur.values
                gross = w.abs().sum(axis=1)
                turn = w.diff().abs().sum(axis=1).fillna(0.0)
                cost = turn * (TAKER_BPS + SLIP_BPS) / 1e4 + gross * (FUND_BPS_8H / 8) / 1e4
                pnl = (w.shift(1) * rets).sum(axis=1) - cost
                for lbl, seg in (("train", pnl.iloc[:split_i]),
                                 ("holdout", pnl.iloc[split_i:])):
                    if lbl == "train":
                        tr = seg
                    else:
                        ho = seg
                shp = lambda s: float(s.mean() / (s.std() + 1e-12) * np.sqrt(365 * 24))
                results.append({"look": look, "every": every, "k": k,
                                "train_net": float(tr.sum()), "train_sharpe": shp(tr),
                                "hold_net": float(ho.sum()), "hold_sharpe": shp(ho)})
    results.sort(key=lambda r: -r["train_sharpe"])
    print(f"{'look':>5} {'every':>5} {'k':>2} | {'trainNet':>9} {'trainShp':>8} | "
          f"{'holdNet':>8} {'holdShp':>8}")
    for r in results[:8]:
        print(f"{r['look']:5d} {r['every']:5d} {r['k']:2d} | {r['train_net']:+9.2%} "
              f"{r['train_sharpe']:+8.2f} | {r['hold_net']:+8.2%} {r['hold_sharpe']:+8.2f}")
    best = results[0]
    print(f"train-selected config -> holdout net {best['hold_net']:+.2%}, "
          f"sharpe {best['hold_sharpe']:+.2f}  "
          f"{'SHIPS' if best['hold_net'] > 0 and best['hold_sharpe'] >= 0.5 else 'killed'}")
    return results


def curve(recs, risk_frac):
    """Sequential book: one position per symbol at a time, risk_frac per trade."""
    recs = sorted(recs, key=lambda x: x[0])
    busy: dict = {}
    eq, pts = 1.0, []
    for ts, sym, R, hold, sb in recs:
        if busy.get(sym) is not None and ts < busy[sym]:
            continue
        busy[sym] = ts + pd.Timedelta(minutes=hold)
        eq *= (1.0 + risk_frac * R)
        pts.append((ts, eq))
    if len(pts) < 10:
        return {"net": 0.0, "sharpe": 0.0, "maxdd": 0.0, "trades": len(pts)}
    s = pd.Series([p[1] for p in pts], index=[p[0] for p in pts])
    daily = s.resample("1D").last().ffill()
    dr = daily.pct_change().dropna()
    sharpe = float(dr.mean() / (dr.std() + 1e-12) * np.sqrt(365)) if len(dr) > 2 else 0.0
    peak, dd = -1e9, 0.0
    for v in s.values:
        peak = max(peak, v)
        dd = min(dd, v / peak - 1.0)
    return {"net": float(s.iloc[-1] - 1.0), "sharpe": round(sharpe, 2),
            "maxdd": round(dd, 4), "trades": len(pts),
            "days": int(len(daily))}


if __name__ == "__main__":
    _cache = (build_cache() if ("--build" in sys.argv or not CACHE.exists())
              else pickle.load(open(CACHE, "rb"))["cache"])
    for _sc in COST_SCENARIOS:
        main(_cache, _sc)
    xsmom()
