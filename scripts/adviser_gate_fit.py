"""Can the adviser-gate blend weight be fitted from what the system has recorded?

Run from the repo root:  .venv/bin/python scripts/adviser_gate_fit.py

Answer as of 2026-08-15: NO, and this script is how you re-check that rather than
taking it on trust. It reports the joined sample size, the per-day and split-half
optimal beta, and the correlation structure. The blend weight in
brain/adviser_gate.py is derived from measured adviser hit-rate instead (see
blend_weight there); re-run this once the record spans enough distinct regimes to
support an actual fit, which as of writing it does not -- everything starts
2026-07-26.

Reconstructs, per (symbol, calendar day):
  formula target_weight  <- decisions.score is final_conv; target_from_conviction()
                            is exact given entry_threshold/size_scale (constant
                            0.1 / 1.0 across the whole record, per journal.params)
  adviser score          <- brain.db advice_log, the last snapshot of that day
  realized 5d excess ret <- brain.db price_history vs scorecard.benchmark_for

then grids beta and reports the P&L of the blended weight, in-sample and split.
"""
import json
import sqlite3
import sys
from datetime import datetime, timedelta

sys.path.insert(0, "engine")
from ai_investing.brain.scorecard import HORIZON_DAYS, benchmark_for  # noqa: E402

ENTRY_THRESHOLD, SIZE_SCALE = 0.10, 1.0
BLEND_CLAMP = 1.0


def target_from_conviction(c):
    sign = 1.0 if c >= 0 else -1.0
    mag = max(0.0, abs(c) - ENTRY_THRESHOLD) / (1.0 - ENTRY_THRESHOLD)
    return max(-1.0, min(1.0, sign * mag * SIZE_SCALE))


# ---- formula side ----------------------------------------------------------
j = sqlite3.connect("file:data/journal.db?mode=ro", uri=True)
rows = j.execute("""
    select d.symbol, date(d.ts) as day, d.score
    from decisions d
    join (select symbol, date(ts) as day, max(ts) as mts
          from decisions group by symbol, date(ts)) l
      on d.symbol=l.symbol and date(d.ts)=l.day and d.ts=l.mts
""").fetchall()
formula = {(s, day): target_from_conviction(sc) for s, day, sc in rows if sc is not None}
print(f"formula decisions (deduped): {len(formula)}")
nonzero = [abs(v) for v in formula.values() if abs(v) > 1e-9]
nonzero.sort()
print(f"  nonzero positions: {len(nonzero)} ({100*len(nonzero)/len(formula):.1f}%)")
if nonzero:
    q = lambda p: nonzero[min(len(nonzero) - 1, int(p * len(nonzero)))]
    print(f"  |target_weight| p10={q(.10):.3f} p25={q(.25):.3f} median={q(.50):.3f} "
          f"p75={q(.75):.3f} p90={q(.90):.3f} max={nonzero[-1]:.3f}")

# ---- adviser side ----------------------------------------------------------
b = sqlite3.connect("file:data/brain.db?mode=ro", uri=True)
adviser = {}
for ts, blob in b.execute("select ts, advice from advice_log order by ts"):
    day = ts[:10]
    try:
        adv = json.loads(blob)
    except json.JSONDecodeError:
        continue
    for bucket in ("trades", "watch"):
        for r in adv.get(bucket) or []:
            if isinstance(r.get("score"), (int, float)):
                adviser[(r["symbol"], day)] = r["score"]   # later ts overwrites
print(f"adviser scores (deduped): {len(adviser)}")
sc = sorted(abs(v) for v in adviser.values())
if sc:
    q = lambda p: sc[min(len(sc) - 1, int(p * len(sc)))]
    print(f"  |adviser score| median={q(.50):.3f} p90={q(.90):.3f} p99={q(.99):.3f} max={sc[-1]:.3f}"
          f"  (>1.0: {sum(1 for v in sc if v > 1.0)})")

# ---- returns ---------------------------------------------------------------
px = {}
for sym, day, price in b.execute("select symbol, date, price from price_history"):
    px.setdefault(sym, {})[day] = price


def price(sym, day):
    s = px.get(sym) or {}
    if day in s:
        return s[day]
    later = sorted(d for d in s if d >= day)
    return s[later[0]] if later else None


def excess(sym, day):
    e, x = price(sym, day), price(sym, (datetime.fromisoformat(day)
                                        + timedelta(days=HORIZON_DAYS)).date().isoformat())
    if not e or not x or e <= 0:
        return None
    ret = x / e - 1
    bench = benchmark_for(sym)
    if not bench:
        return None
    be, bx = price(bench, day), price(bench, (datetime.fromisoformat(day)
                                              + timedelta(days=HORIZON_DAYS)).date().isoformat())
    if not be or not bx or be <= 0:
        return None
    return ret - (bx / be - 1)


# ---- joined sample ---------------------------------------------------------
sample = []
for key, tw in formula.items():
    if abs(tw) <= 1e-9:          # the gate never touches a flat decision
        continue
    adv = adviser.get(key)
    if adv is None:
        continue
    ex = excess(*key)
    if ex is None:
        continue
    sample.append((key[1], tw, adv, ex))
days = sorted({d for d, _, _, _ in sample})
print(f"\nJOINED SAMPLE: n={len(sample)} over {len(days)} distinct days {days[:1]}..{days[-1:]}")
if not sample:
    sys.exit("nothing to fit")


def pnl(rows, beta):
    """Mean P&L per observation of the blended weight, using the exact rule in
    apply_adviser_gate: clamp the adviser score, tilt, cap at +-1, never flip."""
    tot = 0.0
    for _, tw, adv, ex in rows:
        w = tw + beta * max(-BLEND_CLAMP, min(BLEND_CLAMP, adv))
        w = max(-1.0, min(1.0, w))
        if (w >= 0) != (tw >= 0):
            w = 0.0
        tot += w * ex
    return tot / len(rows)


grid = [i / 100 for i in range(0, 101, 5)]
best = max(grid, key=lambda g: pnl(sample, g))
print(f"\nfull-sample optimal beta = {best:.2f}   "
      f"(pnl {pnl(sample, best)*1e4:+.2f}bp vs {pnl(sample, 0.0)*1e4:+.2f}bp at beta=0)")

print("\nper-day optimal beta (this is the stability question):")
flips = []
for d in days:
    rows = [r for r in sample if r[0] == d]
    if len(rows) < 20:
        continue
    bd = max(grid, key=lambda g: pnl(rows, g))
    flips.append(bd)
    print(f"  {d}  n={len(rows):5d}  beta*={bd:.2f}   "
          f"pnl@0={pnl(rows,0.0)*1e4:+8.2f}bp  pnl@best={pnl(rows,bd)*1e4:+8.2f}bp")
if flips:
    print(f"\n  per-day beta*: min={min(flips):.2f} max={max(flips):.2f} "
          f"spread={max(flips)-min(flips):.2f}  ({sum(1 for f in flips if f==0.0)}/{len(flips)} days want beta=0)")

half = days[: len(days) // 2]
a = [r for r in sample if r[0] in half]
c = [r for r in sample if r[0] not in half]
if a and c:
    ba = max(grid, key=lambda g: pnl(a, g))
    bc = max(grid, key=lambda g: pnl(c, g))
    print(f"\nsplit-half: first-half beta*={ba:.2f} (n={len(a)}), second-half beta*={bc:.2f} (n={len(c)})")
    print(f"  first-half's beta applied out-of-sample to second half: "
          f"{pnl(c, ba)*1e4:+.2f}bp vs {pnl(c, 0.0)*1e4:+.2f}bp at beta=0  "
          f"({'HELPS' if pnl(c,ba) > pnl(c,0.0) else 'HURTS'})")

# ---- is the tilt even independent of what it is tilting? -------------------
import math
tws = [r[1] for r in sample]
advs = [r[2] for r in sample]
exs = [r[3] for r in sample]


def corr(a, b):
    n = len(a)
    ma, mb = sum(a) / n, sum(b) / n
    ca = [x - ma for x in a]
    cb = [x - mb for x in b]
    da = math.sqrt(sum(x * x for x in ca))
    db = math.sqrt(sum(x * x for x in cb))
    return sum(x * y for x, y in zip(ca, cb)) / (da * db) if da * db > 0 else 0.0


print(f"\ncorr(target_weight, adviser_score) = {corr(tws, advs):+.3f}")
print(f"  same sign: {100*sum(1 for t,a in zip(tws,advs) if (t>=0)==(a>=0))/len(tws):.1f}% of the sample")
print(f"corr(target_weight, excess_ret)    = {corr(tws, exs):+.3f}   <- formula's own edge")
print(f"corr(adviser_score, excess_ret)    = {corr(advs, exs):+.3f}   <- adviser's edge")

print("\nfull beta curve (mean pnl per observation):")
for g in [0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.50, 0.75, 1.0]:
    print(f"  beta={g:.2f}  {pnl(sample, g)*1e4:+8.2f}bp")


# ============================================================================
# Section 2: is the tilt independent of what it is tilting?
# ============================================================================
# adviser.py: score = W_FIELD*field + W_FORMULA*formula + W_SCENARIO*scen + ...
# so `score` restates the formula conviction target_weight is already made of.
# advice_log records the drivers separately, so the split is checkable.
W_FIELD, W_FORMULA, W_SCENARIO = 1.0, 0.6, 0.5
drv = {}
for ts, blob in b.execute('select ts, advice from advice_log order by ts'):
    try: a = json.loads(blob)
    except json.JSONDecodeError: continue
    for bucket in ('trades', 'watch'):
        for r in a.get(bucket) or []:
            if (r.get('drivers') or {}) and isinstance(r.get('score'), (int, float)):
                drv[(r['symbol'], ts[:10])] = (r['score'], r['drivers'])
dec = [(tw, *drv[k], ex) for k, tw in formula.items()
       if abs(tw) > 1e-9 and k in drv and (ex := excess(*k)) is not None]
if dec:
    tw_ = [d[0] for d in dec]; sc_ = [d[1] for d in dec]; ex_ = [d[3] for d in dec]
    fml_ = [W_FORMULA * float(d[2].get('formula') or 0.0) for d in dec]
    ind_ = [W_FIELD * float(d[2].get('field') or 0.0)
            + W_SCENARIO * float(d[2].get('scenarios') or 0.0) for d in dec]
    print(f'\nn = {len(dec)}')
    print(f'  corr(target_weight, adviser FORMULA part)     = {corr(tw_, fml_):+.3f}  <- restatement')
    print(f'  corr(target_weight, adviser INDEPENDENT part) = {corr(tw_, ind_):+.3f}  <- diversifying')
    print(f'  corr(independent part, excess return)         = {corr(ind_, ex_):+.3f}')
    mags = sorted(abs(v) for v in ind_); tws = sorted(abs(v) for v in tw_)
    qq = lambda v, p: v[min(len(v) - 1, int(p * len(v)))]
    print('\n  tilt size vs the position it tilts (median |target_weight| = '
          f'{qq(tws,.5):.4f}):')
    for beta in (0.30, 0.20, 0.15, 0.10, 0.05):
        print(f'    beta={beta:.2f}: median tilt {beta*qq(mags,.5):.4f} '
              f'({100*beta*qq(mags,.5)/qq(tws,.5):3.0f}% of a typical position), '
              f'max observed {beta*mags[-1]:.4f} ({100*beta*mags[-1]/qq(tws,.5):3.0f}%)')
