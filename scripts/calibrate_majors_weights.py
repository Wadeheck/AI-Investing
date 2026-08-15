"""Are the `member_of crypto_majors` weights measurable, instead of asserted?

A member_of edge transmits a theme shock to its member, so its weight should
track how strongly that coin actually co-moves with the majors complex. The 20
pre-existing weights (btc/eth 0.9 ... tao/fet 0.3) were hand-assigned. If they
correlate with measured beta-to-basket, that mapping is the graph author's
intuition made explicit -- and it can then be applied to the six coins added in
seed v38, whose weights are currently narrative guesses.

Daily closes from Binance spot klines (keyless, ~2y).
"""
import json
import math
import sys
import time
import urllib.request

# existing seed weights (member_of -> crypto_majors)
EXISTING = {
    "BTC": 0.9, "ETH": 0.9, "SOL": 0.8, "XRP": 0.7, "BNB": 0.7, "AVAX": 0.7,
    "NEAR": 0.7, "LINK": 0.7, "INJ": 0.6, "ARB": 0.6, "DOGE": 0.5, "RENDER": 0.5,
    "TAO": 0.3, "FET": 0.3, "AKT": 0.5, "IO": 0.4, "HYPE": 0.6,
}
NEW = {"UNI": 0.6, "AAVE": 0.6, "ATOM": 0.6, "DOT": 0.6, "LTC": 0.5, "BCH": 0.5}
# the basket = the coins everyone agrees are the core complex, so a candidate is
# never scored against a basket it dominates
CORE = ["BTC", "ETH", "SOL", "XRP", "BNB"]


def klines(sym, limit=730):
    url = (f"https://api.binance.com/api/v3/klines?symbol={sym}USDT"
           f"&interval=1d&limit={limit}")
    req = urllib.request.Request(url, headers={"user-agent": "ai-investing/0.1"})
    with urllib.request.urlopen(req, timeout=20) as r:
        rows = json.loads(r.read().decode())
    return {int(k[0]) // 86400000: float(k[4]) for k in rows}


closes = {}
for sym in list(EXISTING) + list(NEW):
    try:
        closes[sym] = klines(sym)
        time.sleep(0.12)
    except Exception as exc:
        print(f"  ! {sym}: {type(exc).__name__} — skipped")
print(f"fetched {len(closes)} symbols\n")


def rets(series, days):
    out = {}
    for d in days:
        if d in series and (d - 1) in series and series[d - 1] > 0:
            out[d] = series[d] / series[d - 1] - 1
    return out


all_days = sorted(set.intersection(*[set(closes[s]) for s in CORE if s in closes]))
core_r = {s: rets(closes[s], all_days) for s in CORE if s in closes}
basket = {}
for d in all_days:
    vals = [core_r[s][d] for s in core_r if d in core_r[s]]
    if len(vals) == len(core_r):
        basket[d] = sum(vals) / len(vals)
print(f"basket: equal-weight {'+'.join(core_r)} over {len(basket)} daily returns\n")


def beta_corr(sym):
    r = rets(closes[sym], sorted(closes[sym]))
    days = sorted(set(r) & set(basket))
    if len(days) < 200:
        return None
    x = [basket[d] for d in days]
    y = [r[d] for d in days]
    n = len(x)
    mx, my = sum(x) / n, sum(y) / n
    cxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    cxx = sum((a - mx) ** 2 for a in x)
    cyy = sum((b - my) ** 2 for b in y)
    beta = cxy / cxx if cxx > 0 else 0.0
    corr = cxy / math.sqrt(cxx * cyy) if cxx * cyy > 0 else 0.0
    return beta, corr, n


print(f"{'coin':<8}{'seed w':>7}{'beta':>8}{'corr':>8}{'n':>6}")
print("-" * 40)
meas = {}
for sym, w in sorted(EXISTING.items(), key=lambda kv: -kv[1]):
    if sym not in closes:
        continue
    bc = beta_corr(sym)
    if not bc:
        print(f"{sym:<8}{w:>7.1f}{'  (too little history)':>22}")
        continue
    meas[sym] = bc
    print(f"{sym:<8}{w:>7.1f}{bc[0]:>8.2f}{bc[1]:>8.2f}{bc[2]:>6}")

print()
for sym, w in NEW.items():
    if sym not in closes:
        continue
    bc = beta_corr(sym)
    if not bc:
        print(f"{sym:<8}{w:>7.1f}  (too little history)")
        continue
    meas[sym] = bc
    print(f"{sym:<8}{w:>7.1f}{bc[0]:>8.2f}{bc[1]:>8.2f}{bc[2]:>6}   <- NEW (prior)")


def pearson(a, b):
    n = len(a)
    ma, mb = sum(a) / n, sum(b) / n
    ca, cb = [x - ma for x in a], [x - mb for x in b]
    da, db = math.sqrt(sum(x * x for x in ca)), math.sqrt(sum(x * x for x in cb))
    return sum(x * y for x, y in zip(ca, cb)) / (da * db) if da * db else 0.0


ex = [(s, EXISTING[s], *meas[s]) for s in EXISTING if s in meas]
print(f"\n--- does the hand-assigned scale track measured co-movement? (n={len(ex)}) ---")
ws = [e[1] for e in ex]
print(f"  corr(seed weight, beta) = {pearson(ws, [e[2] for e in ex]):+.3f}")
print(f"  corr(seed weight, corr) = {pearson(ws, [e[3] for e in ex]):+.3f}")

# least squares weight ~ a + b*corr, fitted on the existing coins only
cs = [e[3] for e in ex]
n = len(cs)
mc, mw = sum(cs) / n, sum(ws) / n
b1 = sum((c - mc) * (w - mw) for c, w in zip(cs, ws)) / sum((c - mc) ** 2 for c in cs)
b0 = mw - b1 * mc
resid = [w - (b0 + b1 * c) for c, w in zip(cs, ws)]
rmse = math.sqrt(sum(r * r for r in resid) / n)
print(f"\n  fit: weight = {b0:+.3f} + {b1:+.3f} * corr     (RMSE {rmse:.3f})")
print(f"\n{'coin':<8}{'seed':>7}{'implied':>9}{'delta':>8}")
print("-" * 32)
for sym in NEW:
    if sym not in meas:
        continue
    implied = b0 + b1 * meas[sym][1]
    snapped = round(implied * 10) / 10
    print(f"{sym:<8}{NEW[sym]:>7.1f}{implied:>9.2f}{implied-NEW[sym]:>+8.2f}   -> snap {snapped:.1f}")
