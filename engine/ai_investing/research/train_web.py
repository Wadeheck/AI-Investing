"""Overnight web trainer: principled upgrades, iterated until targets or exhaustion.

The user's mandate:
  - capital preservation FIRST, growth second (drawdown is penalized above all)
  - targets: stocks ~50%/yr; crypto ~3x/yr (HODL core + daily tactical overlay)
  - the web decides everything; upgrades must be FUNDAMENTAL (new factors:
    emotions, manipulation-intent, influential figures; parameters; structure),
    never a tweak that only flatters one test run.

ANTI-CHEAT PROTOCOL (the user's "do not cheat" rule, made structural):
  every candidate upgrade is tuned ONLY on the TRAIN window and then judged
  blind on the HOLDOUT window that no parameter ever saw. An upgrade is
  adopted only if it helps BOTH windows. Every round is logged to
  data/web_training.json — including the failures.

EVIDENCE PROTOCOL v2 (2026-07-28) — the replay must be pessimistic enough
to trust:
  frictions : per-market commissions/taxes/half-spread + sqrt market impact
              (HK stamp duty, KR/TW transaction taxes, crypto taker fees) —
              replaces the old flat 5bps assumption
  fills     : stock entries fill at the NEXT day's open (no same-bar fills);
              stops/takes are resting intraday orders — a gap through the
              stop fills at the open, so losses CAN exceed the 10% rule
  windows   : train 55% / holdout 25% / LOCKBOX 20%. No adoption decision
              ever sees the lockbox; evaluate_lockbox() (--lockbox) runs it
              manually, ONCE, when a strategy is frozen for deployment
  benchmarks: SPY, QQQ, 60/40, BTC buy-and-hold reported beside every
              window — alpha must beat doing nothing
  Numbers produced before v2 are NOT comparable to numbers after it.

v2.1 (2026-07-28, same day): FX correctness — non-USD prices converted to
USD daily (currency P&L is real); SHORT positions accrue conservative
borrow fees daily; crypto hard stops check every CALENDAR day including
weekends (Saturday crashes count); new hard-data anchor rounds R16 (VIX ->
risk node) and R17 (DXY/USDJPY -> usd_strength/yen_carry).

New factor families the trainer can add to the web (all computed from the
day's own headlines — replicable live, no hindsight):
  emotion   : fear/greed keyword balance pulses the risk-appetite node
  manip     : hype-language discounts that day's news impulse magnitudes
  figures   : headlines quoting central bankers / heads of state amplify
              their policy nodes (powell->fed, xi->china, trump->us gov...)
  regime    : when the field's risk-appetite turns deeply negative, gross
              exposure is cut (capital preservation as a web-driven reflex)

Runs unattended: waits for the news pipeline (fetch+digest) to finish, then
trains in rounds. Writes an honest report to data/web_training_report.md.
"""
from __future__ import annotations

import itertools
import json
import math
import re
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ai_investing.execution.costs import CostModel  # noqa: E402

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
ARCHIVE = DATA_DIR / "news_archive.jsonl"
IMPULSES = DATA_DIR / "news_impulses.jsonl"
OUT_JSON = DATA_DIR / "web_training.json"
OUT_MD = DATA_DIR / "web_training_report.md"

TARGET_STOCK_CAGR = 0.50
TARGET_CRYPTO_CAGR = 2.0          # 3x = +200%
MAX_DD_LIMIT = 0.25               # capital preservation: hard screen

FEAR = re.compile(r"\b(crash|plunge|panic|recession|crisis|war|invasion|selloff|"
                  r"tumbl\w+|collaps\w+|default|contagion|meltdown|slump)\b", re.I)
GREED = re.compile(r"\b(rally|surge|record high|boom|soar\w*|all-time high|"
                   r"bull run|melt-up|euphori\w+)\b", re.I)
HYPE = re.compile(r"\b(to the moon|skyrocket|explode|guaranteed|100x|10x|"
                  r"massive gains|next nvidia|next bitcoin|get in now|"
                  r"don't miss|could soar|set to surge|unstoppable)\b", re.I)
FIGURES = {  # who moves which node when they speak
    re.compile(r"\b(powell|fomc|federal reserve chair)\b", re.I): "fed_rate",
    re.compile(r"\btrump\b", re.I): "us_government",
    re.compile(r"\b(xi jinping|xi's|beijing)\b", re.I): "china_government",
    re.compile(r"\bmusk\b", re.I): "us_megacap_tech",
    re.compile(r"\b(opec|saudi)\b", re.I): "oil_supply",
}


def log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc):%H:%M:%S}] {msg}", flush=True)


# ------------------------------------------------------------ wait for data --
def wait_for_pipeline(max_hours: float = 24.0) -> None:
    wiki = DATA_DIR / "news_archive_wiki.jsonl"
    t0 = time.time()
    while time.time() - t0 < max_hours * 3600:
        days = set()
        for p in (ARCHIVE, wiki):
            if p.exists():
                for line in p.open():
                    try:
                        days.add(json.loads(line)["date"])
                    except (json.JSONDecodeError, KeyError):
                        pass
        imp = sum(1 for _ in IMPULSES.open()) if IMPULSES.exists() else 0
        if len(days) >= 770 and imp >= len(days) * 0.9:
            log(f"pipeline complete: {len(days)} days covered, {imp} digested")
            return
        log(f"waiting for pipeline… covered {len(days)}/785 (gdelt+wiki), digested {imp}")
        time.sleep(600)
    log("WARNING: pipeline incomplete after timeout — training on what exists")


# ------------------------------------------------------------------ dataset --
def load_dataset():
    import numpy as np
    import pandas as pd
    import yfinance as yf
    from ai_investing.brain.graph import KnowledgeGraph
    from ai_investing.brain.field import HALF_LIFE_BY_TYPE, HALF_LIFE_HOURS

    g = KnowledgeGraph.load(str(DATA_DIR / "knowledge_graph.json"))
    node_types = {nid: n.type for nid, n in g.nodes.items()}
    node_by_sym = {n.symbol: nid for nid, n in g.nodes.items() if getattr(n, "symbol", None)}
    valid_nodes = set(g.nodes)

    def nearest_node(*cands):
        for c in cands:
            if c in valid_nodes:
                return c
        return None

    risk_node = nearest_node("global_risk_appetite", "risk_appetite")
    news, texts = {}, {}
    if IMPULSES.exists():
        for line in IMPULSES.open():
            try:
                r = json.loads(line)
                news[r["date"]] = {k: v for k, v in r.get("impulses", {}).items()
                                   if k in valid_nodes}
            except (json.JSONDecodeError, KeyError):
                pass
    for line in ARCHIVE.open():
        try:
            r = json.loads(line)
            texts[r["date"]] = " ~ ".join(h["title"] for h in r.get("headlines", []))
        except (json.JSONDecodeError, KeyError):
            pass

    # per-day headline-derived factors (computable live — replicable, no LLM)
    factors = {}
    for d, t in texts.items():
        n_heads = max(1, t.count("~") + 1)
        fear, greed = len(FEAR.findall(t)), len(GREED.findall(t))
        fig_hits = {node: bool(rx.search(t)) for rx, node in FIGURES.items()}
        factors[d] = {"emotion": max(-1.0, min(1.0, (greed - fear) / (0.6 * n_heads))),
                      "hype": min(1.0, len(HYPE.findall(t)) / 3.0),
                      "figures": [n for n, hit in fig_hits.items() if hit and n in valid_nodes]}

    symbols = sorted(node_by_sym)
    yfs = lambda s: s.replace("/", "-")
    ren = {yfs(s): s for s in symbols}
    data = yf.download([yfs(s) for s in symbols], period="3y", interval="1d",
                       auto_adjust=True, progress=False)
    close_raw = data["Close"].rename(columns=ren)
    close = close_raw[close_raw.notna().mean(axis=1) > 0.33].ffill(limit=5)
    close = close.dropna(axis=1, thresh=int(len(close) * 0.8))
    symbols = [s for s in symbols if s in close.columns]
    close = close[symbols]
    # intraday OHLC for resting-order (stop/take) fills; volume for impact
    opn = data["Open"].rename(columns=ren).reindex(close.index)[symbols]
    high = data["High"].rename(columns=ren).reindex(close.index)[symbols]
    low = data["Low"].rename(columns=ren).reindex(close.index)[symbols]
    adv = (data["Volume"].rename(columns=ren).reindex(close.index)[symbols]
           .rolling(20, min_periods=5).mean())
    # ---- FX correctness: convert non-USD prices to USD (v2.1) ------------
    # 'div' quotes are <CCY> per USD (divide local price); 'mul' are USD per
    # unit (multiply). Without this, ~30 non-USD names' currency P&L is
    # invisible and cross-currency sizing is wrong.
    fx_map = {"hk": ("HKD=X", "div"), "sg": ("SGD=X", "div"),
              "jp": ("JPY=X", "div"), "kr": ("KRW=X", "div"),
              "tw": ("TWD=X", "div"), "cn": ("CNY=X", "div"),
              "eu": ("EURUSD=X", "mul")}
    anchor_tickers = sorted({t for t, _ in fx_map.values()} | {"^VIX", "DX-Y.NYB"})
    ax = yf.download(anchor_tickers, period="3y", interval="1d",
                     auto_adjust=True, progress=False)["Close"]
    ax = ax.reindex(close.index).ffill()
    if ax.isna().all().any():
        missing = list(ax.columns[ax.isna().all()])
        log(f"WARNING: anchor series entirely missing: {missing}")
    for s in symbols:
        mkt = market_of(s)
        if mkt in fx_map:
            t, mode = fx_map[mkt]
            rate = ax[t]
            if rate.notna().mean() < 0.5:
                log(f"WARNING: no FX for {mkt} — {s} left in local currency")
                continue
            for frame in (close, opn, high, low):
                frame[s] = frame[s] / rate if mode == "div" else frame[s] * rate
    import numpy as _np
    vix_dlog = _np.log(ax["^VIX"]).diff() if "^VIX" in ax else None
    dxy_dlog = _np.log(ax["DX-Y.NYB"]).diff() if "DX-Y.NYB" in ax else None
    jpy_dlog = _np.log(ax["JPY=X"]).diff() if "JPY=X" in ax else None
    # ---- full-calendar crypto OHLC: weekends exist and stops must see them
    crypto_syms = [s for s in symbols if "/" in s]
    c_open = data["Open"].rename(columns=ren)[crypto_syms]
    c_low = data["Low"].rename(columns=ren)[crypto_syms]
    c_high = data["High"].rename(columns=ren)[crypto_syms]
    c_close = close_raw[crypto_syms]
    rets = close.pct_change()
    vol20 = rets.rolling(20, min_periods=10).std()
    # benchmarks: what doing nothing clever earns over the same dates
    bpx = yf.download(["SPY", "QQQ", "AGG"], period="3y", interval="1d",
                      auto_adjust=True, progress=False)["Close"]
    bench = {"SPY": bpx["SPY"].reindex(close.index).ffill(),
             "QQQ": bpx["QQQ"].reindex(close.index).ffill()}
    agg = bpx["AGG"].reindex(close.index).ffill()
    r6040 = 0.6 * bench["SPY"].pct_change() + 0.4 * agg.pct_change()
    bench["60/40"] = 100.0 * (1.0 + r6040.fillna(0.0)).cumprod()
    btc_sym = next((s for s in symbols if s.startswith("BTC")), None)
    if btc_sym:
        bench["BTC hodl"] = close[btc_sym]
    # crypto-native signals (funding z / fear-greed / on-chain trend), computed
    # with trailing windows only — nothing from the future leaks backward
    crypto_sig = {"fz": {}, "fng": {}, "addr": {}}
    try:
        cs = json.loads((DATA_DIR / "crypto_signals.json").read_text())
        crypto_sig["fng"] = {k: int(v) for k, v in cs.get("fng", {}).items()}
        for sym, series in cs.get("funding", {}).items():
            s_ = pd.Series(series).sort_index()
            z = (s_ - s_.rolling(90, min_periods=30).mean()) / (
                s_.rolling(90, min_periods=30).std() + 1e-9)
            crypto_sig["fz"][sym] = z.dropna().to_dict()
        a = pd.Series(cs.get("btc_addr", {})).sort_index()
        tr = (a.rolling(10).mean() - a.rolling(40).mean()) / (a.rolling(40).mean() + 1e-9)
        crypto_sig["addr"] = tr.dropna().to_dict()
    except Exception as exc:
        log(f"crypto signals unavailable: {exc}")
    log(f"dataset: {len(symbols)} symbols, {len(close)} days, news {len(news)} days, "
        f"factors {len(factors)} days, crypto-sig days {len(crypto_sig['fng'])}, "
        f"risk node = {risk_node}")
    return dict(g=g, node_types=node_types, node_by_sym=node_by_sym, close=close,
                open=opn, high=high, low=low, adv=adv, vol20=vol20, bench=bench,
                rets=rets, news=news, factors=factors,
                symbols=symbols, risk_node=risk_node, valid_nodes=set(g.nodes),
                crypto_sig=crypto_sig,
                vix_dlog=vix_dlog, dxy_dlog=dxy_dlog, jpy_dlog=jpy_dlog,
                c_open=c_open, c_low=c_low, c_high=c_high, c_close=c_close,
                HL=HALF_LIFE_BY_TYPE, HL_DEF=HALF_LIFE_HOURS,
                cryptos=[s for s in symbols if "/" in s])


def refresh_news(ds) -> None:
    """Re-read impulses so holdout evaluation sees news digested since startup
    (training may begin while the digester is still finishing the tail)."""
    news = {}
    if IMPULSES.exists():
        for line in IMPULSES.open():
            try:
                r = json.loads(line)
                news[r["date"]] = {k: v for k, v in r.get("impulses", {}).items()
                                   if k in ds["valid_nodes"]}
            except (json.JSONDecodeError, KeyError):
                pass
    ds["news"] = news


# ------------------------------------------------------------------- replay --
BASE = dict(w_field=1.0, w_formula=0.6, entry=0.10, hop_decay=0.6, max_hops=3,
            stop_atr=3.0, take_atr=6.0, use_emotion=0, emotion_gain=0.0,
            use_manip=0, use_figures=0, figure_gain=0.0,
            regime_gate=0, gate_level=-0.35, gate_frac=0.3,
            crypto_hodl=0.2, crypto_gain=0.5,
            tact_take=0.08,                 # fast tactical: bank quick profits
            tact_hold=5,                    # fast tactical: max holding days
            crypto_gate=0,                  # deep risk-off also trims the HODL core
            short_bias=0.0,                 # lower entry bar for SHORTS in risk-off
            # --- scoring-function upgrades (the math itself is searchable) ---
            w_fmom=0.0,                     # field momentum: building ripples > stale ones
            w_agree=0.0,                    # bonus when web and price action AGREE
            crypto_trend=0,                 # BTC under its 100d average = crypto winter
            w_funding=0.0,                  # contrarian leverage-crowding (funding z)
            w_fng=0.0,                      # contrarian crypto fear/greed extremes
            w_onchain=0.0,                  # on-chain usage trend (BTC adoption)
            trail_atr=0.0,                  # >0: trailing exits — let winners RUN
            use_rel=0,                      # per-symbol reliability reweighting
            w_vix=0.0,                      # real vol regime (VIX) pulses the risk node
            w_fx=0.0,                       # DXY -> usd_strength, USDJPY -> yen_carry
            # --- two-sleeve stock book (USER MANDATE 2026-07-28): a long-term
            # value/conviction CORE that holds through dips (NO 10% cap, NO HWM
            # lockout — the long game), beside the tactical sleeve where the
            # 10% rule and ratchet still rule. Preservation (25% continuous dd)
            # still screens the COMBINED book.
            stock_core=0.0,                 # fraction of stock capital in the core
            core_n=12,                      # core holdings, equal weight
            core_reb=21,                    # rebalance cadence (trading days)
            core_dstop=0.30)                # disaster stop: thesis assumed broken
# -------------------------------------------------------------- frictions --
# Real per-market frictions, charged on EVERY fill (per side):
#   commission_bps : commissions + transaction taxes (HK stamp duty 0.1%;
#                    KR/TW sell-side taxes averaged across both sides)
#   spread_bps     : half the typical bid-ask spread for liquid names there
# plus square-root market impact (execution.costs.CostModel) using the real
# 20-day share ADV — negligible at this book size, but charged anyway.
# Crypto pays taker fee + spread and skips the impact term (yfinance reports
# quote-currency volume, so share-participation would be meaningless).
COST_MODELS = {
    "us": CostModel(commission_bps=1.5, spread_bps=2.5),
    "hk": CostModel(commission_bps=15.0, spread_bps=10.0),
    "cn": CostModel(commission_bps=5.0, spread_bps=5.0),
    "sg": CostModel(commission_bps=8.0, spread_bps=12.0),
    "jp": CostModel(commission_bps=3.0, spread_bps=5.0),
    "kr": CostModel(commission_bps=12.0, spread_bps=6.0),
    "tw": CostModel(commission_bps=17.0, spread_bps=6.0),
    "eu": CostModel(commission_bps=5.0, spread_bps=5.0),
    "crypto": CostModel(commission_bps=10.0, spread_bps=5.0),
}
_SUFFIX_MKT = {"HK": "hk", "SS": "cn", "SZ": "cn", "SI": "sg", "T": "jp",
               "KS": "kr", "KQ": "kr", "TW": "tw", "TWO": "tw",
               "PA": "eu", "DE": "eu", "AS": "eu", "L": "eu", "MI": "eu"}


def market_of(s: str) -> str:
    if "/" in s:
        return "crypto"
    if "." in s:
        return _SUFFIX_MKT.get(s.rsplit(".", 1)[1], "us")
    return "us"


def cost_frac(ds, s: str, qty: float, price: float, i: int) -> float:
    """Per-side cost fraction for filling |qty| of s at price on day i."""
    mkt = market_of(s)
    adv = None
    if mkt != "crypto" and s in ds["adv"].columns:
        a = float(ds["adv"][s].iloc[i])
        adv = a if a == a and a > 0 else None
    v = float(ds["vol20"][s].iloc[i]) if s in ds["vol20"].columns else float("nan")
    return COST_MODELS[mkt].cost_fraction(abs(qty), price, adv, v if v == v else None)


HARD_STOP = 0.10   # USER HARD RULE: max 10% loss on ANY trade or investment

# USER CRYPTO MANDATE (2026-07-28): skeptical stance — 20% HODL core,
# fast tactical sleeve capped at 70% of the crypto book (buy/sell churn,
# quick take-profits, time-boxed holds), remainder cash buffer. The HODL
# fraction is PINNED (not searchable); the search may not drift it.
CRYPTO_MANDATE = {"crypto_hodl": 0.20}
CRYPTO_TACT_CAP = 0.70

# Conservative flat borrow fees for SHORT stock positions (no free historical
# per-name data exists; these are deliberately pessimistic). Accrued daily.
SHORT_BORROW_APR = {"us": 0.02, "eu": 0.02, "jp": 0.02,
                    "hk": 0.04, "cn": 0.04, "kr": 0.04, "tw": 0.04, "sg": 0.04}


def run_replay(ds, cfg, i0, i1):
    """One walk-forward pass over close.iloc[i0:i1]. Returns metrics per book.

    Execution realism (evidence protocol v2):
      - stock entries decided at day t's close FILL AT DAY t+1's OPEN
      - stock stops/takes rest intraday: triggered off high/low; a gap
        through the stop fills at the open — losses CAN exceed the 10% stop
      - crypto fills at the daily close (continuous market); hard stops are
        checked daily off the intraday low, gap-aware
      - every fill pays per-market commission/tax/spread + sqrt impact
    """
    import numpy as np
    g, close, rets = ds["g"], ds["close"], ds["rets"]
    opn, high, low = ds["open"], ds["high"], ds["low"]
    node_by_sym, node_types = ds["node_by_sym"], ds["node_types"]
    symbols, cryptos = ds["symbols"], ds["cryptos"]
    stocks = [s for s in symbols if s not in cryptos]
    field: dict[str, float] = {}
    prev_imp: dict[str, float] = {}
    btc = next((s for s in cryptos if s.startswith("BTC")), None)
    core_frac = min(max(cfg["stock_core"], 0.0), 0.9)
    book = {"cash": 100_000.0 * (1.0 - core_frac), "pos": {}}   # tactical sleeve
    kbook = {"cash": 100_000.0 * core_frac, "pos": {}}          # long-term core
    slow_imp: dict[str, float] = {}         # ~30d EMA of field impact (core signal)
    ktrades = 0
    pending: list[dict] = []                # stock orders awaiting next open
    rel: dict[str, float] = {}              # learned per-symbol trust (trailing)
    cbook = {"cash": 100_000.0, "hodl": {}, "tact": {}}
    curve, ccurve, tcurve = [], [], []      # combined stock / crypto / tactical-only
    hwm = {"tb": None, "cb": None}         # monthly high-water marks (user ratchet)
    mclose = {"tb": None, "cb": None}
    cur_month = None
    blocked = {"tb": False, "cb": False}
    graded = wins = total = 0

    def decay_field(f):
        out = {}
        for k, v in f.items():
            hl = ds["HL"].get(node_types.get(k, ""), ds["HL_DEF"])
            dv = v * math.pow(0.5, 24.0 / hl)
            if abs(dv) >= 0.02:
                out[k] = dv
        return out

    def eq_of(bk, px):
        e = bk["cash"]
        for grp in ("pos", "hodl", "tact"):
            for s, p in bk.get(grp, {}).items():
                if s in px and not np.isnan(px[s]):
                    e += p["qty"] * px[s]
        return e

    c_open, c_low, c_high, c_close = (ds["c_open"], ds["c_low"],
                                      ds["c_high"], ds["c_close"])
    cal_idx = c_low.index

    def crypto_take_fill(s, take_px, prev_td, cur_td):
        """Weekend-aware resting take-profit: first calendar day whose high
        reaches the target; a gap above it fills at the open (better)."""
        a = (cal_idx.searchsorted(prev_td, side="right") if prev_td is not None
             else cal_idx.searchsorted(cur_td, side="left"))
        b = cal_idx.searchsorted(cur_td, side="right")
        highs = c_high[s].iloc[a:b]
        hit = highs[highs >= take_px]
        if hit.empty:
            return None
        d0 = hit.index[0]
        o = c_open[s].loc[d0]
        if np.isnan(o):
            o = c_close[s].loc[d0]
        return max(o, take_px) if not np.isnan(o) else take_px

    def crypto_stop_fill(s, stop_px, prev_td, cur_td):
        """Weekend-aware resting stop: first CALENDAR day in (prev_td, cur_td]
        whose low breaches the stop — Saturday crashes count. Returns the
        gap-aware fill price, or None if never breached."""
        a = (cal_idx.searchsorted(prev_td, side="right") if prev_td is not None
             else cal_idx.searchsorted(cur_td, side="left"))
        b = cal_idx.searchsorted(cur_td, side="right")
        lows = c_low[s].iloc[a:b]
        hit = lows[lows <= stop_px]
        if hit.empty:
            return None
        d0 = hit.index[0]
        o = c_open[s].loc[d0]
        if np.isnan(o):
            o = c_close[s].loc[d0]
        return min(o, stop_px) if not np.isnan(o) else stop_px

    # crypto HODL core: buy once at window start, hold. The allocation is
    # HARD-CAPPED at 95% of cash: there is no free leverage in this sim —
    # the refiner once walked crypto_hodl to 1.19 and bought crypto with
    # cash the book didn't have.
    px0 = close.iloc[i0]
    per = min(cfg["crypto_hodl"], 0.95) * cbook["cash"] / max(1, len(cryptos))
    for s in cryptos:
        if not np.isnan(px0[s]):
            qty = per / px0[s]
            cbook["cash"] -= per * (1 + cost_frac(ds, s, qty, px0[s], i0))
            cbook["hodl"][s] = {"qty": qty, "entry": px0[s]}

    for i in range(i0, i1):
        px = close.iloc[i]
        dstr = close.index[i].date().isoformat()
        m = dstr[:7]
        if cur_month != m:
            for k in hwm:
                if mclose[k] is not None and (hwm[k] is None or mclose[k] > hwm[k]):
                    hwm[k] = mclose[k]
            cur_month = m
        if curve:
            # HWM ratchet protects FAST capital only: tactical sleeve + crypto.
            # The long-term core rides through (user mandate 2026-07-28).
            mclose["tb"], mclose["cb"] = tcurve[-1], ccurve[-1]
            for k, v in (("tb", tcurve[-1]), ("cb", ccurve[-1])):
                blocked[k] = bool(hwm[k]) and v < hwm[k] * (1 - HARD_STOP)
        po, phi, plo = opn.iloc[i], high.iloc[i], low.iloc[i]

        # ---- fill stock entries queued at yesterday's close, at today's open
        for od in pending:
            s = od["s"]
            o = po[s]
            if np.isnan(o) or o <= 0 or s in book["pos"] or len(book["pos"]) >= 12:
                continue
            qty = (od["notional"] / o) * od["dir"]
            frac = cost_frac(ds, s, qty, o, i)
            if od["dir"] > 0 and od["notional"] * (1 + frac) > book["cash"]:
                continue
            book["cash"] -= qty * o * (1 + frac * od["dir"])
            book["pos"][s] = {
                "qty": qty, "entry": o, "ei": i, "atr0": od["atr"],
                "stop": o - min(cfg["stop_atr"] * od["atr"], HARD_STOP * o) * od["dir"],
                "take": o + cfg["take_atr"] * od["atr"] * od["dir"]}
        pending = []
        fac = ds["factors"].get(dstr, {})
        manip_disc = (1.0 - 0.5 * fac.get("hype", 0.0)) if cfg["use_manip"] else 1.0

        impulses = {}
        for k, v in ds["news"].get(dstr, {}).items():
            impulses[k] = v * manip_disc
        if cfg["use_emotion"] and ds["risk_node"] and abs(fac.get("emotion", 0)) > 0.05:
            e = cfg["emotion_gain"] * fac["emotion"]
            impulses[ds["risk_node"]] = max(impulses.get(ds["risk_node"], 0.0), e, key=abs)
        if cfg["use_figures"]:
            for node in fac.get("figures", []):
                cur = impulses.get(node, 0.0)
                impulses[node] = cur * (1 + cfg["figure_gain"]) if cur else cfg["figure_gain"] * 0.3
        for s in symbols:
            r = rets[s].iloc[i]
            if not np.isnan(r) and abs(r) >= 0.01:
                nid = node_by_sym[s]
                impulses[nid] = max(impulses.get(nid, 0.0),
                                    max(-0.4, min(0.4, 3.0 * r)), key=abs)
        # crypto-native signals pulse the crypto nodes (the web stays the boss)
        cs = ds["crypto_sig"]
        for s in cryptos:
            nid = node_by_sym[s]
            add = 0.0
            if cfg["w_funding"]:
                fz = cs["fz"].get(s, {}).get(dstr)
                if fz is not None and abs(fz) > 1.0:      # only meaningful extremes
                    add += -cfg["w_funding"] * max(-1.0, min(1.0, fz / 2.5)) * 0.35
            if cfg["w_fng"]:
                v = cs["fng"].get(dstr)
                if v is not None and (v <= 20 or v >= 75):
                    add += cfg["w_fng"] * (0.3 if v <= 20 else -0.3)
            if cfg["w_onchain"] and s.startswith("BTC"):
                tr = cs["addr"].get(dstr)
                if tr is not None:
                    add += cfg["w_onchain"] * max(-0.25, min(0.25, tr * 8))
            if abs(add) > 0.03:
                impulses[nid] = max(impulses.get(nid, 0.0),
                                    max(-0.5, min(0.5, add)), key=abs)
        # hard-data anchors (v2.1): real series pulse their factor nodes
        if cfg["w_vix"] and ds["vix_dlog"] is not None and ds["risk_node"]:
            dv = ds["vix_dlog"].iloc[i]
            if not np.isnan(dv) and abs(dv) > 0.05:      # >5% VIX move
                add = -cfg["w_vix"] * max(-0.5, min(0.5, dv * 2.0))
                impulses[ds["risk_node"]] = max(
                    impulses.get(ds["risk_node"], 0.0), add, key=abs)
        if cfg["w_fx"]:
            for dser, node, sgn in ((ds["dxy_dlog"], "usd_strength", 1.0),
                                    (ds["jpy_dlog"], "yen_carry", -1.0)):
                if dser is None or node not in ds["valid_nodes"]:
                    continue
                dv = dser.iloc[i]
                if not np.isnan(dv) and abs(dv) > 0.003:  # >0.3% FX move
                    add = sgn * cfg["w_fx"] * max(-0.5, min(0.5, dv * 40.0))
                    impulses[node] = max(impulses.get(node, 0.0), add, key=abs)
        field = decay_field(field)
        if impulses:
            impacts, _, _ = g.propagate(impulses, max_hops=cfg["max_hops"],
                                        decay=cfg["hop_decay"])
            for k, v in impacts.items():
                field[k] = max(-1.0, min(1.0, field.get(k, 0.0) + v))
        asset_imp = g.asset_impacts(field)
        for s in stocks:    # slow conviction: the persistent narrative, not the ripple
            slow_imp[s] = (0.97 * slow_imp.get(s, 0.0)
                           + 0.03 * asset_imp.get(s, {}).get("impact", 0.0))
        risk = field.get(ds["risk_node"], 0.0) if ds["risk_node"] else 0.0
        gate = cfg["gate_frac"] if (cfg["regime_gate"] and risk < cfg["gate_level"]) else 1.0

        # ---- stock book: resting stop/take orders, gap-aware intraday fills
        win = close.iloc[max(0, i - 20):i + 1]
        for s, p in book["pos"].items():        # daily borrow fee on shorts
            if p["qty"] < 0 and not np.isnan(px[s]):
                apr = SHORT_BORROW_APR.get(market_of(s), 0.03)
                book["cash"] -= abs(p["qty"]) * px[s] * apr / 252.0
        for s in list(book["pos"]):
            p, v = book["pos"][s], px[s]
            if np.isnan(v):
                continue
            o, hi_, lo_ = po[s], phi[s], plo[s]
            if np.isnan(o):
                o = v
            if np.isnan(hi_):
                hi_ = max(o, v)
            if np.isnan(lo_):
                lo_ = min(o, v)
            d_ = 1 if p["qty"] > 0 else -1
            hit_stop = lo_ <= p["stop"] if d_ == 1 else hi_ >= p["stop"]
            hit_take = hi_ >= p["take"] if d_ == 1 else lo_ <= p["take"]
            if hit_stop or hit_take:
                if hit_stop:    # both touched same day -> assume the worst
                    fill = min(o, p["stop"]) if d_ == 1 else max(o, p["stop"])
                else:           # limit take: gap past it fills at the open
                    fill = max(o, p["take"]) if d_ == 1 else min(o, p["take"])
                frac = cost_frac(ds, s, p["qty"], fill, i)
                book["cash"] += p["qty"] * fill * (1 - frac * d_)
                total += 1
                won = (fill - p["entry"]) * p["qty"] > 0
                wins += 1 if won else 0
                rel[s] = max(0.5, min(1.5, rel.get(s, 1.0) + (0.08 if won else -0.08)))
                hz = min(p["ei"] + 5, len(close) - 1)
                graded += 1 if (close[s].iloc[hz] / p["entry"] - 1) * d_ > 0.003 else 0
                del book["pos"][s]
                continue
            if cfg["trail_atr"] > 0:    # ratchet AFTER the exit check: today's
                # peak can only move TOMORROW's stop (no same-day lookahead)
                p["peak"] = max(p.get("peak", p["entry"]) * d_, v * d_) * d_
                trail = p["peak"] - cfg["trail_atr"] * p.get("atr0", 0.0) * d_
                p["stop"] = max(p["stop"] * d_, trail * d_) * d_
                p["take"] = p["entry"] * (1 + 99 * d_)      # no fixed cap
        eq = eq_of(book, px)
        gross = sum(abs(p["qty"]) * px[s] for s, p in book["pos"].items()
                    if not np.isnan(px[s]))
        cands = []
        for s in stocks:
            if s in book["pos"] or np.isnan(px[s]):
                continue
            h = win[s].dropna()
            if len(h) < 15:
                continue
            mom = h.iloc[-1] / h.iloc[0] - 1.0
            z = (h.iloc[-1] - h.mean()) / (h.std() + 1e-9)
            formula = math.tanh(20 * (0.02 * max(-1, min(1, mom / 0.10))
                                      + 0.015 * max(-1, min(1, -z / 2))))
            fimp = asset_imp.get(s, {}).get("impact", 0.0)
            if cfg["use_rel"]:
                fimp *= rel.get(s, 1.0)                 # learned trust, trailing only
            fmom = fimp - prev_imp.get(s, 0.0)          # ripple building vs fading
            agree = (min(abs(fimp), abs(formula))       # web & tape in agreement
                     * (1 if fimp * formula > 0 else -0.5))
            score = (cfg["w_field"] * fimp + cfg["w_formula"] * formula
                     + cfg["w_fmom"] * fmom + cfg["w_agree"] * agree)
            bar = cfg["entry"]
            if score < 0 and risk < -0.1:   # bear regime: shorts get an easier bar
                bar = cfg["entry"] * (1.0 - cfg["short_bias"])
            if abs(score) >= bar:
                cands.append((abs(score), score, s, h))
        for _, score, s, h in (sorted(cands, reverse=True) if not blocked["tb"] else []):
            if len(book["pos"]) + len(pending) >= 12 or gross >= gate * eq:
                break
            vol = h.pct_change().std()
            w = min(0.15, min(0.15, abs(score) * 0.3) * min(3.0, 0.02 / (vol + 1e-9))) * gate
            notional = min(eq * w, gate * eq - gross)
            if notional < 500 or (score > 0 and notional > book["cash"]):
                continue
            atr = h.diff().abs().mean()
            # no same-bar fills: the order rests and fills at TOMORROW's open
            pending.append({"s": s, "dir": 1 if score > 0 else -1,
                            "notional": notional, "atr": atr})
            gross += notional

        # ---- crypto book: HODL core + web-driven tactical sleeve ----
        # preservation reflex for crypto too: deep risk-off halves the HODL
        # core (sold to cash); it is rebought when the field recovers.
        # crypto_trend adds a second winter signal: BTC under its 100d average.
        prev_imp = {s: asset_imp.get(s, {}).get("impact", 0.0) for s in symbols}
        winter = False
        if cfg["crypto_trend"] and btc and i >= 100:
            ma = close[btc].iloc[i - 100:i].mean()
            winter = not np.isnan(px[btc]) and px[btc] < ma
        # HARD RULE applies to the HODL core too — a resting stop checked over
        # every CALENDAR day since the last trading day (weekends included;
        # a gap through the stop fills at that day's open).
        prev_td = close.index[i - 1] if i > i0 else None
        cur_td = close.index[i]
        for s in cryptos:
            h_ = cbook["hodl"].get(s)
            if not h_ or h_["qty"] <= 0 or np.isnan(px[s]):
                continue
            stop_px = h_["entry"] * (1 - HARD_STOP)
            fill = crypto_stop_fill(s, stop_px, prev_td, cur_td)
            if fill is not None:
                cbook["cash"] += h_["qty"] * fill * (1 - cost_frac(ds, s, h_["qty"], fill, i))
                h_["qty"] = 0.0
                h_["stopped"] = True
        if i % 5 == 0:
            for s in cryptos:
                if np.isnan(px[s]):
                    continue
                h_ = cbook["hodl"].get(s)
                if h_ and h_.get("stopped") and i >= 100:
                    ma = close[s].iloc[i - 100:i].mean()
                    if px[s] > ma:
                        share = cfg["crypto_hodl"] * eq_of(cbook, px) / max(1, len(cryptos))
                        buy = min(share, cbook["cash"] * 0.9)
                        if buy > 500:
                            qty = buy / px[s]
                            h_["qty"] = qty
                            h_["entry"] = px[s]
                            h_["stopped"] = False
                            cbook["cash"] -= buy * (1 + cost_frac(ds, s, qty, px[s], i))
        if cfg["crypto_gate"] or winter:
            deep = winter or (cfg["crypto_gate"] and risk < cfg["gate_level"])
            for s in cryptos:
                if np.isnan(px[s]):
                    continue
                h_ = cbook["hodl"].get(s)
                if deep and h_ and not h_.get("trimmed"):
                    sell = h_["qty"] * 0.5
                    cbook["cash"] += sell * px[s] * (1 - cost_frac(ds, s, sell, px[s], i))
                    h_["qty"] -= sell
                    h_["trimmed"] = True
                elif not deep and h_ and h_.get("trimmed"):
                    buy = min(h_["qty"], cbook["cash"] * 0.3 / max(px[s], 1e-9))
                    cbook["cash"] -= buy * px[s] * (1 + cost_frac(ds, s, buy, px[s], i))
                    h_["qty"] += buy
                    h_["trimmed"] = False
        ceq = eq_of(cbook, px)
        tact_val = sum(p["qty"] * px[s2] for s2, p in cbook["tact"].items()
                       if not np.isnan(px[s2]))
        for s in cryptos:
            if np.isnan(px[s]):
                continue
            fimp = asset_imp.get(s, {}).get("impact", 0.0)
            tact = cbook["tact"].get(s)
            exited = False
            if tact:
                stop_px = tact["entry"] * (1 - HARD_STOP)
                fill = crypto_stop_fill(s, stop_px, prev_td, cur_td)
                tfill = (crypto_take_fill(s, tact["entry"] * (1 + cfg["tact_take"]),
                                          prev_td, cur_td)
                         if cfg["tact_take"] > 0 else None)
                if fill is not None:    # worst case first: the stop, gap-aware
                    cbook["cash"] += tact["qty"] * fill * (1 - cost_frac(ds, s, tact["qty"], fill, i))
                    del cbook["tact"][s]
                    tact, exited = None, True
                elif tfill is not None:  # bank the quick profit (fast mandate)
                    cbook["cash"] += tact["qty"] * tfill * (1 - cost_frac(ds, s, tact["qty"], tfill, i))
                    del cbook["tact"][s]
                    tact, exited = None, True
                elif (fimp < -0.05      # signal gone, or held past the clock
                      or i - tact.get("ei", i) >= int(cfg["tact_hold"])):
                    cbook["cash"] += tact["qty"] * px[s] * (1 - cost_frac(ds, s, tact["qty"], px[s], i))
                    del cbook["tact"][s]
                    tact, exited = None, True
                if exited:
                    tact_val = sum(p["qty"] * px[s2] for s2, p in cbook["tact"].items()
                                   if not np.isnan(px[s2]))
            if (not tact and not exited and fimp > 0.10 and gate == 1.0
                    and not winter and not blocked["cb"]):
                room = CRYPTO_TACT_CAP * ceq - tact_val   # mandate: tactical <=70%
                notional = min(cfg["crypto_gain"] * fimp * ceq * 0.4,
                               cbook["cash"] * 0.9, room)
                if notional > 1000:
                    qty = notional / px[s]
                    cbook["cash"] -= notional * (1 + cost_frac(ds, s, qty, px[s], i))
                    cbook["tact"][s] = {"qty": qty, "entry": px[s], "ei": i}
                    tact_val += notional
        # ---- long-term value core: hold through dips, exit on thesis break
        if core_frac > 0:
            for s in list(kbook["pos"]):    # disaster stop only (gap-aware)
                p, v = kbook["pos"][s], px[s]
                if np.isnan(v):
                    continue
                o, lo_ = po[s], plo[s]
                if np.isnan(o):
                    o = v
                if np.isnan(lo_):
                    lo_ = min(o, v)
                dstop = p["entry"] * (1 - cfg["core_dstop"])
                if lo_ <= dstop:
                    fill = min(o, dstop)
                    kbook["cash"] += p["qty"] * fill * (1 - cost_frac(ds, s, p["qty"], fill, i))
                    ktrades += 1
                    del kbook["pos"][s]
            if i - i0 >= 60 and (i - i0) % int(cfg["core_reb"]) == 0:
                scores = {}
                for s in stocks:
                    if np.isnan(px[s]):
                        continue
                    h = close[s].iloc[max(0, i - 200):i].dropna()
                    if len(h) < 60:
                        continue
                    trend = px[s] / h.mean() - 1.0
                    scores[s] = slow_imp.get(s, 0.0) + 0.5 * math.tanh(3.0 * trend)
                ranked = sorted(scores, key=scores.get, reverse=True)
                top = ranked[:int(cfg["core_n"])]
                keep = set(ranked[:2 * int(cfg["core_n"])])
                for s in list(kbook["pos"]):    # thesis break: out of the top 2N
                    if s not in keep and not np.isnan(px[s]):
                        p = kbook["pos"][s]
                        kbook["cash"] += p["qty"] * px[s] * (1 - cost_frac(ds, s, p["qty"], px[s], i))
                        ktrades += 1
                        del kbook["pos"][s]
                per_slot = 0.95 * eq_of(kbook, px) / max(1, int(cfg["core_n"]))
                for s in top:
                    if s in kbook["pos"] or per_slot < 500:
                        continue
                    if kbook["cash"] < per_slot * 1.02:
                        break
                    qty = per_slot / px[s]
                    kbook["cash"] -= qty * px[s] * (1 + cost_frac(ds, s, qty, px[s], i))
                    kbook["pos"][s] = {"qty": qty, "entry": px[s]}
                    ktrades += 1
        keq = eq_of(kbook, px) if core_frac > 0 else 0.0
        tcurve.append(eq)
        curve.append(eq + keq)
        ccurve.append(eq_of(cbook, px))

    import pandas as pd
    idx = close.index[i0:i1]
    out = {}
    for name, cv in (("stock", curve), ("crypto", ccurve)):
        c = pd.Series(cv, index=idx)
        r = c.pct_change().dropna()
        yrs = len(c) / 252
        out[name] = {"final": round(float(c.iloc[-1]), 0),
                     "cagr": round(float((c.iloc[-1] / c.iloc[0]) ** (1 / yrs) - 1), 4),
                     "sharpe": round(float(r.mean() / (r.std() + 1e-12) * math.sqrt(252)), 2),
                     "maxdd": round(float(((c / c.cummax()) - 1).min()), 4)}
    out["trades"] = total
    out["win_rate"] = round(wins / max(1, total), 3)
    out["precision5d"] = round(graded / max(1, total), 3)
    out["core_trades"] = ktrades
    return out


def series_metrics(c):
    """CAGR / Sharpe / maxDD for a price-like series on a trading-day index."""
    c = c.dropna()
    r = c.pct_change().dropna()
    yrs = max(len(c) / 252, 1e-9)
    return {"cagr": round(float((c.iloc[-1] / c.iloc[0]) ** (1 / yrs) - 1), 4),
            "sharpe": round(float(r.mean() / (r.std() + 1e-12) * math.sqrt(252)), 2),
            "maxdd": round(float(((c / c.cummax()) - 1).min()), 4)}


def bench_metrics(ds, i0, i1):
    """Buy-and-hold benchmarks over the same window — alpha must beat these."""
    return {name: series_metrics(c.iloc[i0:i1]) for name, c in ds["bench"].items()}


def objective(m):
    """Capital preservation first: drawdowns beyond the limit are disqualifying;
    inside the limit, growth counts and drawdown still subtracts."""
    s, c = m["stock"], m["crypto"]
    pen = 0.0
    for b in (s, c):
        if abs(b["maxdd"]) > MAX_DD_LIMIT:
            pen += 3.0 * (abs(b["maxdd"]) - MAX_DD_LIMIT)
    return s["cagr"] + 0.5 * c["cagr"] - 2.0 * (abs(s["maxdd"]) + abs(c["maxdd"])) / 2 - pen


# ----------------------------------------------------------------- training --
ROUNDS = [
    ("R1 baseline + parameter sweep", {
        "w_field": [0.8, 1.0, 1.4], "entry": [0.10, 0.16, 0.22],
        "hop_decay": [0.5, 0.6], "take_atr": [6.0, 9.0]}),
    ("R2 + emotion factor (fear/greed pulses risk node)", {
        "use_emotion": [1], "emotion_gain": [0.2, 0.4]}),
    ("R3 + manipulation discount (hype-language haircuts news)", {
        "use_manip": [1]}),
    ("R4 + influential figures (powell/trump/xi/opec amplify their nodes)", {
        "use_figures": [1], "figure_gain": [0.2, 0.4]}),
    ("R5 + regime gate (deep risk-off cuts gross — preservation reflex)", {
        "regime_gate": [1], "gate_level": [-0.25, -0.4], "gate_frac": [0.2, 0.4]}),
    ("R6 crypto tactical aggressiveness (HODL share pinned by mandate)", {
        "crypto_gain": [0.5, 1.0]}),
    ("R7 crypto preservation (deep risk-off trims the HODL core)", {
        "crypto_gate": [1], "gate_level": [-0.2, -0.3]}),
    ("R8 bear-market shorting (risk-off lowers the entry bar for shorts)", {
        "short_bias": [0.3, 0.5]}),
    ("R9 scoring-function upgrade (field momentum + web/tape agreement)", {
        "w_fmom": [0.0, 0.5, 1.0], "w_agree": [0.0, 0.4, 0.8]}),
    ("R10 crypto winter gate (BTC under its 100-day average)", {
        "crypto_trend": [1]}),
    ("R11 funding-rate crowding (contrarian leverage signal into the web)", {
        "w_funding": [0.4, 0.8]}),
    ("R12 crypto fear/greed extremes (contrarian crowd emotion into the web)", {
        "w_fng": [0.4, 0.8]}),
    ("R13 on-chain adoption trend (BTC active addresses into the web)", {
        "w_onchain": [0.4, 0.8]}),
    ("R14 trailing exits — cut losers at 10%, let winners RUN", {
        "trail_atr": [1.5, 2.5, 3.5]}),
    ("R15 per-symbol reliability — learned trust reweights the field", {
        "use_rel": [1]}),
    ("R16 VIX anchor (real vol regime pulses the risk node)", {
        "w_vix": [0.3, 0.6]}),
    ("R17 FX anchors (DXY into usd_strength, USDJPY into yen_carry)", {
        "w_fx": [0.3, 0.6]}),
    ("R18 two-sleeve stock book (long-term value core beside tactical)", {
        "stock_core": [0.3, 0.5, 0.7]}),
    ("R19 fast-crypto rhythm (take-profit level x max holding days)", {
        "tact_take": [0.05, 0.08, 0.12], "tact_hold": [3, 5, 10]}),
]

NUMERIC = ("w_field", "w_formula", "entry", "hop_decay", "emotion_gain", "figure_gain",
           "gate_level", "gate_frac", "crypto_gain", "short_bias",
           "w_fmom", "w_agree", "stop_atr", "take_atr", "w_funding", "w_fng", "w_onchain",
           "trail_atr", "w_vix", "w_fx", "stock_core", "core_dstop", "tact_take")


def preservation_ok(dev_new, dev_old):
    """USER MANDATE, structural: the CONTINUOUS train+holdout path must respect
    the drawdown limit. A candidate passes if every book is inside the limit,
    or at least no deeper than the incumbent's (so the search can climb OUT
    of a breach but never deeper into one)."""
    for b in ("stock", "crypto"):
        dd_new = abs(dev_new[b]["maxdd"])
        dd_old = abs(dev_old[b]["maxdd"])
        if dd_new > MAX_DD_LIMIT and dd_new > dd_old + 0.005:
            return False
    return True


def refine(ds, cfg, base_obj, warm, t_end, h_end, history, widen=1.0):
    """Local finetuning: perturb each numeric parameter ±20%·widen around the
    incumbent; keep a perturbation only if it helps train AND holdout AND
    does not deepen a continuous-path drawdown breach."""
    best_cfg, best_obj = dict(cfg), base_obj
    best_dev = run_replay(ds, best_cfg, warm, h_end)
    for k in NUMERIC:
        v = best_cfg.get(k, 0.0)
        if not isinstance(v, (int, float)) or v == 0:
            continue
        for f in (1 - 0.2 * widen, 1 + 0.2 * widen):
            cand = {**best_cfg, k: round(v * f, 4)}
            m = run_replay(ds, cand, warm, t_end)
            o = objective(m)
            history.append({"round": f"refine {k}x{f:.2f}", "obj": round(o, 4)})
            if o > best_obj + 1e-4:
                oos_old = run_replay(ds, best_cfg, t_end, h_end)
                oos_new = run_replay(ds, cand, t_end, h_end)
                if objective(oos_new) < objective(oos_old) - 0.01:
                    continue
                dev_new = run_replay(ds, cand, warm, h_end)
                if not preservation_ok(dev_new, best_dev):
                    log(f"  refine: {k} -> {cand[k]} VETOED (continuous dd "
                        f"breach: stock {dev_new['stock']['maxdd']:.0%} "
                        f"crypto {dev_new['crypto']['maxdd']:.0%})")
                    continue
                best_cfg, best_obj, best_dev = cand, o, dev_new
                log(f"  refine: {k} -> {cand[k]} (obj {o:.3f}, holdout ok, dd ok)")
    return best_cfg, best_obj


def train_forever() -> None:
    """Cycle until the targets are hit on the FULL period with holdout-honest
    upgrades. Each cycle: staged rounds -> local refinement; stuck cycles widen
    the refinement radius (explore). Every cycle appended to
    data/web_training_history.jsonl; latest state always in web_training.json."""
    hist_path = DATA_DIR / "web_training_history.jsonl"
    cycle, stuck, incumbent = 0, 0, None
    try:                                   # resume from the best known config
        prev = json.loads(OUT_JSON.read_text())["best_cfg"]
        incumbent = {**dict(BASE), **prev}
        log("resuming from incumbent config on disk")
    except Exception:
        pass
    while True:
        cycle += 1
        log(f"===== TRAINING CYCLE {cycle} (stuck={stuck}) =====")
        result = train(seed_cfg=incumbent, widen=1.0 + 0.5 * stuck)
        with hist_path.open("a") as fh:
            fh.write(json.dumps({"cycle": cycle,
                                 "ts": datetime.now(timezone.utc).isoformat(),
                                 "cfg": result["best_cfg"], "dev": result["dev"],
                                 "target_hit": result["target_hit"]}) + "\n")
        if all(result["target_hit"].values()):
            log(f"🎯 TARGETS HIT in cycle {cycle} — stopping. Verify before "
                "trusting; when freezing for deployment, run --lockbox ONCE.")
            return
        improved = (incumbent is None
                    or json.dumps(result["best_cfg"], sort_keys=True)
                    != json.dumps(incumbent, sort_keys=True))
        stuck = 0 if improved else stuck + 1
        incumbent = result["best_cfg"]
        s, c = result["dev"]["stock"], result["dev"]["crypto"]
        log(f"cycle {cycle} best: stock {s['cagr']:+.1%}/dd {s['maxdd']:.0%} | "
            f"crypto {c['cagr']:+.1%}/dd {c['maxdd']:.0%} — continuing")
        if stuck >= 5:
            log("search converged at this function structure — the remaining gap "
                "needs NEW factor families (structural work, not more tuning). "
                "Pausing to avoid burning cycles on a exhausted search space. "
                "When freezing this strategy for deployment, run --lockbox ONCE.")
            return


def train(seed_cfg: dict | None = None, widen: float = 1.0) -> dict:
    ds = load_dataset()
    n = len(ds["close"])
    warm = 30
    t_end = int(n * 0.55)     # tuning sees ONLY [warm, t_end)
    h_end = int(n * 0.80)     # adoption gate judges on [t_end, h_end)
    # [h_end, n) is the LOCKBOX: never evaluated here — see evaluate_lockbox()
    history, best_cfg = [], {**dict(seed_cfg or BASE), **CRYPTO_MANDATE}
    best_train = run_replay(ds, best_cfg, warm, t_end)
    best_obj = objective(best_train)
    best_dev = run_replay(ds, best_cfg, warm, h_end)
    log(f"baseline train obj={best_obj:.3f} {best_train['stock']} {best_train['crypto']}")
    log(f"baseline continuous dd: stock {best_dev['stock']['maxdd']:.0%} "
        f"crypto {best_dev['crypto']['maxdd']:.0%} (limit {MAX_DD_LIMIT:.0%})")

    for round_name, grid in ROUNDS:
        keys = sorted(grid)
        combos = list(itertools.product(*(grid[k] for k in keys)))
        log(f"--- {round_name}: {len(combos)} candidates ---")
        round_best, round_best_obj, round_best_m = None, best_obj, None
        for vals in combos:
            cfg = {**best_cfg, **dict(zip(keys, vals))}
            m = run_replay(ds, cfg, warm, t_end)
            o = objective(m)
            history.append({"round": round_name, "cfg": {k: cfg[k] for k in keys},
                            "train": m, "obj": round(o, 4)})
            if o > round_best_obj:
                round_best, round_best_obj, round_best_m = cfg, o, m
        if round_best is None:
            log(f"{round_name}: no candidate beat incumbent — feature NOT adopted")
            continue
        # anti-cheat: the winner must also help OUT-OF-SAMPLE, unseen by tuning
        refresh_news(ds)          # include any news digested while we trained
        oos_old = run_replay(ds, best_cfg, t_end, h_end)
        oos_new = run_replay(ds, round_best, t_end, h_end)
        if objective(oos_new) < objective(oos_old) - 0.01:
            log(f"{round_name}: REJECTED by holdout (looked good in training only "
                f"— that would be cheating)")
        else:
            # user mandate: the continuous path must not breach the dd limit
            dev_new = run_replay(ds, round_best, warm, h_end)
            if not preservation_ok(dev_new, best_dev):
                log(f"{round_name}: VETOED by preservation (continuous dd "
                    f"stock {dev_new['stock']['maxdd']:.0%} / "
                    f"crypto {dev_new['crypto']['maxdd']:.0%} "
                    f"exceeds {MAX_DD_LIMIT:.0%})")
            else:
                best_cfg, best_obj, best_dev = round_best, round_best_obj, dev_new
                log(f"{round_name}: ADOPTED (train obj {round_best_obj:.3f}; "
                    f"holdout obj {objective(oos_new):.3f} vs {objective(oos_old):.3f})")
        history.append({"round": round_name, "holdout_old": oos_old, "holdout_new": oos_new,
                        "adopted": best_cfg == round_best})

    # local finetuning around the staged winner (holdout-checked per step)
    log("--- refinement pass (±20% around incumbent, holdout-checked) ---")
    best_cfg, best_obj = refine(ds, best_cfg, best_obj, warm, t_end, h_end, history, widen)

    refresh_news(ds)
    final_train = run_replay(ds, best_cfg, warm, t_end)
    final_oos = run_replay(ds, best_cfg, t_end, h_end)
    final_dev = run_replay(ds, best_cfg, warm, h_end)
    bench = {"train": bench_metrics(ds, warm, t_end),
             "holdout": bench_metrics(ds, t_end, h_end),
             "train+holdout": bench_metrics(ds, warm, h_end)}
    idx = ds["close"].index
    windows = {"train": [str(idx[warm].date()), str(idx[t_end - 1].date())],
               "holdout": [str(idx[t_end].date()), str(idx[h_end - 1].date())],
               "lockbox": [str(idx[h_end].date()), str(idx[n - 1].date())]}
    result = {"ts": datetime.now(timezone.utc).isoformat(), "best_cfg": best_cfg,
              "train": final_train, "holdout": final_oos, "dev": final_dev,
              "benchmarks": bench, "windows": windows,
              "targets": {"stock_cagr": TARGET_STOCK_CAGR, "crypto_cagr": TARGET_CRYPTO_CAGR,
                          "maxdd_limit": MAX_DD_LIMIT},
              "target_hit": {
                  "stock": final_dev["stock"]["cagr"] >= TARGET_STOCK_CAGR,
                  "crypto": final_dev["crypto"]["cagr"] >= TARGET_CRYPTO_CAGR,
                  "preservation": (abs(final_dev["stock"]["maxdd"]) <= MAX_DD_LIMIT
                                   and abs(final_dev["crypto"]["maxdd"]) <= MAX_DD_LIMIT)},
              "history": history[-200:]}
    OUT_JSON.write_text(json.dumps(result, indent=1))

    lines = ["# Web training report", f"generated {result['ts']}", "",
             "evidence protocol v2: real per-market frictions, next-open fills, "
             "gap-aware resting stops; benchmark-anchored; lockbox "
             f"({windows['lockbox'][0]} → {windows['lockbox'][1]}) untouched.", "",
             f"adopted config: `{json.dumps(best_cfg)}`", "",
             "| window | book | CAGR | Sharpe | maxDD |", "|---|---|---|---|---|"]
    for wname, m in (("train", final_train), ("holdout", final_oos),
                     ("train+holdout", final_dev)):
        for bname in ("stock", "crypto"):
            b = m[bname]
            lines.append(f"| {wname} | {bname} | {b['cagr']:+.1%} | {b['sharpe']} | {b['maxdd']:.1%} |")
    lines += ["", "## benchmarks (buy & hold, same windows) — beat these or it isn't alpha",
              "", "| window | benchmark | CAGR | Sharpe | maxDD |", "|---|---|---|---|---|"]
    for wname, bm in bench.items():
        for name, b in bm.items():
            lines.append(f"| {wname} | {name} | {b['cagr']:+.1%} | {b['sharpe']} | {b['maxdd']:.1%} |")
    lines += ["", f"trades {final_dev['trades']}, win rate {final_dev['win_rate']:.0%}, "
                  f"5-day precision {final_dev['precision5d']:.0%}",
              "", f"targets hit (train+holdout): {result['target_hit']}",
              "", "lockbox: run `train_web --lockbox` ONCE when freezing a strategy "
                  "for deployment — every look burns it."]
    OUT_MD.write_text("\n".join(lines))
    log(f"TRAINING CYCLE COMPLETE — targets hit: {result['target_hit']}")
    log(f"train+holdout: stock {final_dev['stock']} crypto {final_dev['crypto']}")
    return result


def evaluate_lockbox() -> dict:
    """FINAL EXAM — run the frozen incumbent on the untouched last 20%.

    Run ONCE, manually (--lockbox), when a strategy is frozen for deployment.
    Every look burns the window: its results must NEVER feed back into tuning
    or adoption decisions. Honesty note: rounds adopted before 2026-07-28 saw
    this data through the old 66/34 holdout split, so the lockbox is only
    fully clean for adoptions made after the v2 protocol landed.
    """
    cfg = {**dict(BASE), **json.loads(OUT_JSON.read_text())["best_cfg"]}
    ds = load_dataset()
    n = len(ds["close"])
    h_end = int(n * 0.80)
    idx = ds["close"].index
    m = run_replay(ds, cfg, h_end, n)
    b = bench_metrics(ds, h_end, n)
    out = {"ts": datetime.now(timezone.utc).isoformat(),
           "window": [str(idx[h_end].date()), str(idx[n - 1].date())],
           "cfg": cfg, "metrics": m, "benchmarks": b}
    (DATA_DIR / "web_training_lockbox.json").write_text(json.dumps(out, indent=1))
    log(f"LOCKBOX {out['window'][0]} → {out['window'][1]}: "
        f"stock {m['stock']} | crypto {m['crypto']}")
    log(f"benchmarks over the same window: {b}")
    log("this window is now BURNED — do not tune against it")
    return out


if __name__ == "__main__":
    if "--lockbox" in sys.argv:
        evaluate_lockbox()
    else:
        if "--no-wait" not in sys.argv:
            wait_for_pipeline()
        if "--once" in sys.argv:
            train()
        else:
            train_forever()
