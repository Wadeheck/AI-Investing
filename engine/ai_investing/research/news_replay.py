"""The honest 3-year replay, done right: BACKDATED NEWS feeds the web.

For every trading day in the window, this pipeline:
  1. FETCH  — pulls that day's real market-relevant headlines from the GDELT
              archive (free, historical, timestamped — no hindsight).
  2. DIGEST — runs those headlines through the SAME event extractor the live
              brain uses (local qwen tags events to graph nodes with signed
              impulses; noise filter applies).
  3. REPLAY — walks forward day by day: news impulses + price pulses enter the
              field, propagate through the web, and the web's output drives
              both books with every proposal auto-accepted, engine caps on,
              costs charged. Nothing from day T+1 is ever visible at day T.

The replay grades what the user demanded:
  - bull AND bear: monthly up-capture vs down-capture against SPY
  - call-level precision: every entry's predicted direction is checked at a
    5-trading-day horizon (did it actually go our way?), plus trade ledger
  - blindspots: the worst misses are listed, not hidden

Residual bias, disclosed: the LLM tagging 2024 headlines knows what 2024 led
to; tagging is mechanical (event -> origin node + sign) so leakage is limited,
but magnitudes may be subtly wiser than a true 2024 observer. Direction of
bias: flatters the strategy. Read results with that discount.

Usage:
    python -m ai_investing.research.news_replay fetch    # ~2h (GDELT is slow)
    python -m ai_investing.research.news_replay digest   # hours (local LLM)
    python -m ai_investing.research.news_replay replay   # minutes
    python -m ai_investing.research.news_replay all
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
import urllib.parse
import urllib.request
import warnings
from datetime import date, timedelta
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
ARCHIVE = DATA_DIR / "news_archive.jsonl"      # date -> headlines (GDELT)
IMPULSES = DATA_DIR / "news_impulses.jsonl"    # date -> node impulses (LLM-digested)
START, END = date(2023, 7, 24), date(2026, 7, 24)

GDELT_QUERY = ('("federal reserve" OR inflation OR tariff OR OPEC OR semiconductor '
               'OR china economy OR "interest rate" OR "stock market" OR crude oil '
               'OR bitcoin OR "supply chain" OR geopolitical) sourcelang:english')


def _days() -> list[date]:
    d, out = START, []
    while d <= END:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _done_dates(path: Path) -> set[str]:
    done = set()
    if path.exists():
        for line in path.open():
            try:
                done.add(json.loads(line)["date"])
            except (json.JSONDecodeError, KeyError):
                pass
    return done


# ------------------------------------------------------------------- fetch --
def fetch() -> None:
    done = _done_dates(ARCHIVE)
    days = [d for d in _days() if d.isoformat() not in done]
    print(f"[fetch] {len(days)} days to fetch (resumable; {len(done)} already done)", flush=True)
    with ARCHIVE.open("a") as fh:
        for i, d in enumerate(days):
            params = urllib.parse.urlencode({
                "query": GDELT_QUERY, "mode": "artlist", "maxrecords": "25",
                "format": "json", "sort": "hybridrel",
                "startdatetime": d.strftime("%Y%m%d") + "000000",
                "enddatetime": d.strftime("%Y%m%d") + "235959"})
            url = "https://api.gdeltproject.org/api/v2/doc/doc?" + params
            heads, tries = [], 0
            while tries < 4:
                tries += 1
                try:
                    req = urllib.request.Request(url, headers={"user-agent": "ai-investing-research/0.1"})
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        body = resp.read().decode()
                    arts = json.loads(body).get("articles", [])
                    seen_titles = set()
                    for a in arts:
                        t = (a.get("title") or "").strip()
                        if t and t.lower() not in seen_titles:
                            seen_titles.add(t.lower())
                            heads.append({"title": t[:200], "source": a.get("domain", "")[:60]})
                    break
                except Exception:
                    time.sleep(90)          # 429 / hiccup: long backoff, retry
            fh.write(json.dumps({"date": d.isoformat(), "headlines": heads}) + "\n")
            fh.flush()
            if i % 25 == 0:
                print(f"[fetch] {d} ({i}/{len(days)}) — {len(heads)} headlines", flush=True)
            time.sleep(8)                   # be a polite citizen of GDELT


# ------------------------------------------------------------------ digest --
def digest() -> None:
    from ai_investing.brain.graph import KnowledgeGraph
    from ai_investing.brain import events as events_mod
    from ai_investing.config import settings
    g = KnowledgeGraph.load(str(DATA_DIR / "knowledge_graph.json"))
    done = _done_dates(IMPULSES)
    rows = []
    for line in ARCHIVE.open():
        try:
            r = json.loads(line)
            if r["date"] not in done and r.get("headlines"):
                rows.append(r)
        except (json.JSONDecodeError, KeyError):
            pass
    print(f"[digest] {len(rows)} days to digest through the local LLM "
          f"({len(done)} already done)", flush=True)
    t0 = time.time()
    with IMPULSES.open("a") as fh:
        for i, r in enumerate(rows):
            evs = events_mod.extract_events(r["headlines"][:20], g, settings)
            imp: dict[str, float] = {}
            for ev in evs:
                if ev.get("is_noise"):
                    continue
                for node in ev.get("nodes", []):
                    imp[node] = max(imp.get(node, 0.0), ev.get("impulse", 0.0), key=abs)
            fh.write(json.dumps({"date": r["date"], "impulses": imp,
                                 "events": len(evs)}) + "\n")
            fh.flush()
            if i % 10 == 0:
                rate = (time.time() - t0) / max(1, i + 1)
                print(f"[digest] {r['date']} ({i}/{len(rows)}) — {len(imp)} nodes pulsed; "
                      f"~{rate:.0f}s/day, ETA {(len(rows) - i) * rate / 3600:.1f}h", flush=True)


# ------------------------------------------------------------------ replay --
W_FIELD, W_FORMULA = 1.0, 0.6
ENTRY, MAX_W, TARGET_VOL = 0.10, 0.15, 0.02
MAX_POSITIONS, GROSS_CAP = 12, 1.0             # the live engine's caps, applied
STOP_ATR, TAKE_ATR = 3.0, 6.0
COST_SIDE = 0.0005
START_CASH = 100_000.0
HORIZON = 5                                     # precision check: right within 5 days?


def replay() -> None:
    import numpy as np
    import pandas as pd
    import yfinance as yf
    from ai_investing.brain.graph import KnowledgeGraph
    from ai_investing.brain.field import HALF_LIFE_BY_TYPE, HALF_LIFE_HOURS

    g = KnowledgeGraph.load(str(DATA_DIR / "knowledge_graph.json"))
    node_types = {nid: n.type for nid, n in g.nodes.items()}
    node_by_sym = {n.symbol: nid for nid, n in g.nodes.items() if getattr(n, "symbol", None)}
    news = {}
    if IMPULSES.exists():
        for line in IMPULSES.open():
            try:
                r = json.loads(line)
                news[r["date"]] = r.get("impulses", {})
            except (json.JSONDecodeError, KeyError):
                pass
    print(f"[replay] news impulses loaded for {len(news)} days", flush=True)

    symbols = sorted(node_by_sym)
    yfs = lambda s: s.replace("/", "-")
    data = yf.download([yfs(s) for s in symbols], period="3y", interval="1d",
                       auto_adjust=True, progress=False)
    close = data["Close"].rename(columns={yfs(s): s for s in symbols})
    close = close[close.notna().mean(axis=1) > 0.33].ffill(limit=5)
    close = close.dropna(axis=1, thresh=int(len(close) * 0.8))
    symbols = [s for s in symbols if s in close.columns]
    rets = close.pct_change()
    spy = yf.download("SPY", period="3y", interval="1d", auto_adjust=True,
                      progress=False)["Close"].squeeze().reindex(close.index).ffill()
    print(f"[replay] {len(symbols)} symbols, {len(close)} days "
          f"({close.index[0].date()} -> {close.index[-1].date()})", flush=True)

    field: dict[str, float] = {}
    book = {"cash": START_CASH, "pos": {}}
    inv = {"cash": START_CASH, "pos": {}}
    curve, icurve, dates = [], [], []
    ledger: list[dict] = []                     # every trading-book bet, graded

    def decay(f, hours=24.0):
        out = {}
        for k, v in f.items():
            hl = HALF_LIFE_BY_TYPE.get(node_types.get(k, ""), HALF_LIFE_HOURS)
            d = v * math.pow(0.5, hours / hl)
            if abs(d) >= 0.02:
                out[k] = d
        return out

    def equity(bk, px):
        return bk["cash"] + sum(p["qty"] * px[s] for s, p in bk["pos"].items()
                                if s in px and not np.isnan(px[s]))

    warm = 30
    for i in range(warm, len(close)):
        day = close.index[i]
        dstr = day.date().isoformat()
        px = close.iloc[i]

        impulses = dict(news.get(dstr, {}))                 # NEWS first — the point
        for s in symbols:                                   # then price pulses
            r = rets[s].iloc[i]
            if not np.isnan(r) and abs(r) >= 0.01:
                nid = node_by_sym[s]
                pulse = max(-0.4, min(0.4, 3.0 * r))
                impulses[nid] = max(impulses.get(nid, 0.0), pulse, key=abs)
        field = decay(field)
        if impulses:
            impacts, _, _ = g.propagate(impulses, max_hops=3, decay=0.6)
            for k, v in impacts.items():
                field[k] = max(-1.0, min(1.0, field.get(k, 0.0) + v))
        asset_imp = g.asset_impacts(field)

        # --- trading book: exits, then capped entries ---
        win = close.iloc[max(0, i - 20):i + 1]
        for s in list(book["pos"]):
            p, v = book["pos"][s], px[s]
            if np.isnan(v):
                continue
            d_ = 1 if p["qty"] > 0 else -1
            if (d_ == 1 and (v <= p["stop"] or v >= p["take"])) or \
               (d_ == -1 and (v >= p["stop"] or v <= p["take"])):
                book["cash"] += p["qty"] * v * (1 - COST_SIDE * d_)
                p["exit_i"], p["exit_px"] = i, v
                ledger.append(p)
                del book["pos"][s]
        eq = equity(book, px)
        gross = sum(abs(p["qty"]) * px[s] for s, p in book["pos"].items()
                    if s in px and not np.isnan(px[s]))
        cands = []
        for s in symbols:
            if s in book["pos"] or np.isnan(px[s]):
                continue
            h = win[s].dropna()
            if len(h) < 15:
                continue
            mom = h.iloc[-1] / h.iloc[0] - 1.0
            z = (h.iloc[-1] - h.mean()) / (h.std() + 1e-9)
            formula = math.tanh(20 * (0.02 * max(-1, min(1, mom / 0.10))
                                      + 0.015 * max(-1, min(1, -z / 2))))
            score = W_FIELD * asset_imp.get(s, {}).get("impact", 0.0) + W_FORMULA * formula
            if abs(score) >= ENTRY:
                cands.append((abs(score), score, s, h))
        for _, score, s, h in sorted(cands, reverse=True):
            if len(book["pos"]) >= MAX_POSITIONS or gross >= GROSS_CAP * eq:
                break
            vol = h.pct_change().std()
            w = min(MAX_W, min(MAX_W, abs(score) * 0.3) * min(3.0, TARGET_VOL / (vol + 1e-9)))
            notional = min(eq * w, GROSS_CAP * eq - gross)
            if notional < 500 or (score > 0 and notional > book["cash"]):
                continue
            atr = h.diff().abs().mean()
            qty = (notional / px[s]) * (1 if score > 0 else -1)
            book["cash"] -= qty * px[s] * (1 + COST_SIDE * (1 if qty > 0 else -1))
            book["pos"][s] = {"sym": s, "qty": qty, "entry": px[s], "entry_i": i,
                              "dir": 1 if qty > 0 else -1,
                              "stop": px[s] - STOP_ATR * atr * (1 if qty > 0 else -1),
                              "take": px[s] + TAKE_ATR * atr * (1 if qty > 0 else -1)}
            gross += notional

        # --- investing book: weekly, field top-5, wide stop ---
        if i % 5 == 0:
            ranked = sorted(((asset_imp.get(s, {}).get("impact", 0.0), s)
                             for s in symbols if not np.isnan(px[s])), reverse=True)
            targets = {s for v, s in ranked[:5] if v > 0.05}
            for s in list(inv["pos"]):
                p, v = inv["pos"][s], px[s]
                if np.isnan(v):
                    continue
                if s not in targets or v <= p["entry"] * 0.75:
                    inv["cash"] += p["qty"] * v * (1 - COST_SIDE)
                    del inv["pos"][s]
            ieq = equity(inv, px)
            for s in targets - set(inv["pos"]):
                notional = min(ieq * 0.18, inv["cash"])
                if notional >= 1000:
                    qty = notional / px[s]
                    inv["cash"] -= qty * px[s] * (1 + COST_SIDE)
                    inv["pos"][s] = {"qty": qty, "entry": px[s]}

        dates.append(day)
        curve.append(equity(book, px))
        icurve.append(equity(inv, px))

    # ---- grade the ledger: pnl + 5-day directional precision + blindspots ----
    for p in ledger + list(book["pos"].values()):
        s, ei = p["sym"], p["entry_i"]
        hz = min(ei + HORIZON, len(close) - 1)
        fwd = close[s].iloc[hz] / p["entry"] - 1.0
        p["fwd5"] = fwd
        p["precise"] = (fwd * p["dir"]) > 0.003
        exit_px = p.get("exit_px", close[s].iloc[-1])
        p["pnl"] = (exit_px - p["entry"]) * p["qty"]

    graded = [p for p in ledger if "precise" in p]
    prec = sum(p["precise"] for p in graded) / max(1, len(graded))
    winr = sum(p["pnl"] > 0 for p in graded) / max(1, len(graded))
    worst = sorted(graded, key=lambda p: p["pnl"])[:5]

    c = pd.Series(curve, index=dates)
    ic = pd.Series(icurve, index=dates)
    spy_al = spy.iloc[warm:]

    def stats(series):
        r = series.pct_change().dropna()
        yrs = len(series) / 252
        return ((series.iloc[-1] / series.iloc[0]) ** (1 / yrs) - 1,
                r.mean() / (r.std() + 1e-12) * math.sqrt(252),
                ((series / series.cummax()) - 1).min())

    # bull/bear split: monthly returns bucketed by SPY's month sign
    m = pd.DataFrame({"strat": c, "inv": ic, "spy": spy_al}).resample("ME").last().pct_change().dropna()
    up, down = m[m["spy"] > 0], m[m["spy"] <= 0]

    print("\n========== 3-YEAR NEWS-FED REPLAY ==========")
    for name, series in (("TRADING book", c), ("INVESTING book", ic), ("SPY", spy_al)):
        cagr, sh, dd = stats(series)
        print(f"  {name:<16} final ${series.iloc[-1] / series.iloc[0] * START_CASH:,.0f}  "
              f"CAGR {cagr:+.1%}  Sharpe {sh:.2f}  maxDD {dd:.1%}")
    print(f"\n  BULL/BEAR SPLIT (monthly, vs SPY sign; capture = ours/SPY):")
    for label, bucket in (("up-months", up), ("down-months", down)):
        if len(bucket):
            print(f"    {label:<11} n={len(bucket):<3} SPY avg {bucket['spy'].mean():+.2%}  "
                  f"trading {bucket['strat'].mean():+.2%}  investing {bucket['inv'].mean():+.2%}")
    print(f"\n  CALL PRECISION (trading book): {len(graded)} closed bets")
    print(f"    5-day direction right: {prec:.0%}   trade win rate: {winr:.0%}")
    print("    worst misses (blindspots):")
    for p in worst:
        print(f"      {'LONG' if p['dir'] > 0 else 'SHORT':<5} {p['sym']:<10} "
              f"pnl ${p['pnl']:,.0f}  5d move {p['fwd5']:+.1%}")
    days_with_news = sum(1 for d in dates if news.get(d.date().isoformat()))
    print(f"\n  news coverage: {days_with_news}/{len(dates)} replay days had digested news")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    if cmd in ("fetch", "all"):
        fetch()
    if cmd in ("digest", "all"):
        digest()
    if cmd in ("replay", "all"):
        replay()
