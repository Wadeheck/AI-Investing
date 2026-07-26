"""3-year walk-forward replay of the web-driven strategy.

Day by day, exactly as the live engine would see it (no lookahead):
  - each day's price moves pulse their asset nodes and PROPAGATE through the
    knowledge graph (same path-sum math, same decay half-lives)
  - the trading book scores = W_FIELD*field + W_FORMULA*formula(momentum,
    mean-reversion), enters when |score| clears the engine's threshold,
    vol-targeted sizing, ATR stop/take, costs charged per side
  - the investing book rebalances weekly into the strongest positive field
    names (equal weight, wide 25% stop), like auto-approved theses
  - every proposal is auto-accepted (per the user's instruction)

NOT replayed (honestly impossible without hindsight bias): news events, LLM
theses, valuation anchors (no free historical fundamentals). This tests the
mechanical core of the web strategy.
"""
import math
import sys
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))

import numpy as np
import pandas as pd
import yfinance as yf

from ai_investing.brain.graph import KnowledgeGraph
from ai_investing.brain.field import HALF_LIFE_BY_TYPE, HALF_LIFE_HOURS

GRAPH_PATH = str(__import__("pathlib").Path(__file__).resolve().parents[3] / "data" / "knowledge_graph.json")
W_FIELD, W_FORMULA = 1.0, 0.6
ENTRY, MAX_W, TARGET_VOL = 0.10, 0.15, 0.02
STOP_ATR, TAKE_ATR = 3.0, 6.0
COST_SIDE = 0.0005              # 5 bps per side (commission+spread+impact)
START_CASH = 100_000.0

g = KnowledgeGraph.load(GRAPH_PATH)
node_types = {nid: n.type for nid, n in g.nodes.items()}
sym_by_node, node_by_sym = {}, {}
for nid, n in g.nodes.items():
    s = getattr(n, "symbol", None)
    if s:
        sym_by_node[nid] = s
        node_by_sym[s] = nid

def yf_sym(s):
    return s.replace("/", "-") if "/" in s else s

symbols = sorted(node_by_sym)
data = yf.download([yf_sym(s) for s in symbols], period="3y", interval="1d",
                   auto_adjust=True, progress=False)
close = data["Close"].rename(columns={yf_sym(s): s for s in symbols})
# crypto trades weekends -> stocks are NaN on those rows; align on the STOCK
# calendar (rows where at least a third of names printed), then forward-fill
close = close[close.notna().mean(axis=1) > 0.33].ffill(limit=5)
close = close.dropna(axis=1, thresh=int(len(close) * 0.8))
symbols = [s for s in symbols if s in close.columns]
rets = close.pct_change()
print(f"universe: {len(symbols)} symbols, {len(close)} trading days "
      f"({close.index[0].date()} -> {close.index[-1].date()})", flush=True)

# --- daily loop state ---
field: dict[str, float] = {}
trade_book = {"cash": START_CASH, "pos": {}}   # sym -> {qty, entry, stop, take}
inv_book = {"cash": START_CASH, "pos": {}}     # sym -> {qty, entry}
tb_curve, ib_curve, dates = [], [], []
trades, wins = 0, 0

def decay_field(f, hours=24.0):
    out = {}
    for k, v in f.items():
        hl = HALF_LIFE_BY_TYPE.get(node_types.get(k, ""), HALF_LIFE_HOURS)
        d = v * math.pow(0.5, hours / hl)
        if abs(d) >= 0.02:
            out[k] = d
    return out

def book_equity(book, px):
    eq = book["cash"]
    for s, p in book["pos"].items():
        if s in px and not np.isnan(px[s]):
            eq += p["qty"] * px[s]
    return eq

warm = 30
for i in range(warm, len(close)):
    day = close.index[i]
    px = close.iloc[i]
    # 1) price pulses -> web
    impulses = {}
    for s in symbols:
        r = rets[s].iloc[i]
        if not np.isnan(r) and abs(r) >= 0.01:
            impulses[node_by_sym[s]] = max(-0.4, min(0.4, 3.0 * r))
    field = decay_field(field)
    if impulses:
        impacts, _, _ = g.propagate(impulses, max_hops=3, decay=0.6)
        for k, v in impacts.items():
            field[k] = max(-1.0, min(1.0, field.get(k, 0.0) + v))
    asset_imp = g.asset_impacts(field)

    # 2) trading book — exits first (stop/take/score flip), then entries
    win = close.iloc[max(0, i - 20):i + 1]
    for s in list(trade_book["pos"]):
        p = trade_book["pos"][s]
        v = px[s]
        if np.isnan(v):
            continue
        direction = 1 if p["qty"] > 0 else -1
        hit = (direction == 1 and (v <= p["stop"] or v >= p["take"])) or \
              (direction == -1 and (v >= p["stop"] or v <= p["take"]))
        if hit:
            pnl = (v - p["entry"]) * p["qty"]
            trade_book["cash"] += p["qty"] * v * (1 - COST_SIDE * direction)
            trades += 1
            wins += 1 if pnl > 0 else 0
            del trade_book["pos"][s]
    eq = book_equity(trade_book, px)
    for s in symbols:
        if s in trade_book["pos"] or np.isnan(px[s]):
            continue
        h = win[s].dropna()
        if len(h) < 15:
            continue
        mom = h.iloc[-1] / h.iloc[0] - 1.0
        z = (h.iloc[-1] - h.mean()) / (h.std() + 1e-9)
        formula = math.tanh(20 * (0.02 * max(-1, min(1, mom / 0.10))
                                  + 0.015 * max(-1, min(1, -z / 2))))
        fimp = asset_imp.get(s, {}).get("impact", 0.0)
        score = W_FIELD * fimp + W_FORMULA * formula
        if abs(score) < ENTRY:
            continue
        vol = h.pct_change().std()
        w = min(MAX_W, abs(score) * 0.3) * min(3.0, TARGET_VOL / (vol + 1e-9))
        w = min(MAX_W, w)
        notional = eq * w
        if notional < 500 or notional > trade_book["cash"] and score > 0:
            continue
        atr = (h.diff().abs().mean())
        qty = (notional / px[s]) * (1 if score > 0 else -1)
        trade_book["cash"] -= qty * px[s] * (1 + COST_SIDE * (1 if qty > 0 else -1))
        trade_book["pos"][s] = {"qty": qty, "entry": px[s],
                                "stop": px[s] - STOP_ATR * atr * (1 if qty > 0 else -1),
                                "take": px[s] + TAKE_ATR * atr * (1 if qty > 0 else -1)}

    # 3) investing book — weekly: hold top-5 positive-field names, 25% stop
    if i % 5 == 0:
        ranked = sorted(((asset_imp.get(s, {}).get("impact", 0.0), s) for s in symbols
                         if not np.isnan(px[s])), reverse=True)
        targets = {s for v, s in ranked[:5] if v > 0.05}
        for s in list(inv_book["pos"]):
            p = inv_book["pos"][s]
            v = px[s]
            if np.isnan(v):
                continue
            if s not in targets or v <= p["entry"] * 0.75:
                inv_book["cash"] += p["qty"] * v * (1 - COST_SIDE)
                del inv_book["pos"][s]
        ieq = book_equity(inv_book, px)
        for s in targets - set(inv_book["pos"]):
            notional = min(ieq * 0.18, inv_book["cash"])
            if notional < 1000:
                continue
            qty = notional / px[s]
            inv_book["cash"] -= qty * px[s] * (1 + COST_SIDE)
            inv_book["pos"][s] = {"qty": qty, "entry": px[s]}

    dates.append(day)
    tb_curve.append(book_equity(trade_book, px))
    ib_curve.append(book_equity(inv_book, px))

# --- results ---
def stats(curve):
    c = pd.Series(curve, index=dates)
    r = c.pct_change().dropna()
    years = len(c) / 252
    cagr = (c.iloc[-1] / c.iloc[0]) ** (1 / years) - 1
    sharpe = r.mean() / (r.std() + 1e-12) * math.sqrt(252)
    dd = ((c / c.cummax()) - 1).min()
    return c.iloc[-1], cagr, sharpe, dd, c

bench = (close / close.iloc[0]).mean(axis=1).iloc[warm:]    # equal-weight, normalized
spy = yf.download("SPY", period="3y", interval="1d", auto_adjust=True,
                  progress=False)["Close"].squeeze().reindex(close.index).ffill().iloc[warm:]

print("\n=== 3-YEAR REPLAY: all proposals auto-accepted ===")
for name, curve in (("TRADING book (web+formula)", tb_curve),
                    ("INVESTING book (field top-5 weekly)", ib_curve)):
    fin, cagr, sh, dd, c = stats(curve)
    for y in sorted({d.year for d in dates}):
        yc = c[c.index.year == y]
        if len(yc) > 5:
            print(f"      {y}: {yc.iloc[-1] / yc.iloc[0] - 1:+.1%}", end="")
    print()
    print(f"  {name}: final ${fin:,.0f}  CAGR {cagr:+.1%}  Sharpe {sh:.2f}  maxDD {dd:.1%}")
print(f"  trades in trading book: {trades}, win rate {wins / max(1, trades):.0%}")
for name, series in (("equal-weight universe buy&hold", bench), ("SPY buy&hold", spy)):
    n = series / series.iloc[0] * START_CASH
    fin, cagr, sh, dd, _ = stats(list(n))
    print(f"  BENCH {name}: final ${fin:,.0f}  CAGR {cagr:+.1%}  Sharpe {sh:.2f}  maxDD {dd:.1%}")
