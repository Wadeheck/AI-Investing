"""Undervaluation scanner — cheap AND honest AND resilient, never just cheap.

The classic value-investing failure is the value trap: a stock that screens
cheap because the market has correctly smelled decay or dishonesty (Wirecard
was "cheap" all the way to zero). So this scanner composes three layers that
already exist:

  CHEAP      — FCF yield (latest annual FCF / market cap: the king metric),
               earnings yield (1/PE), price-to-book
  RESILIENT  — the multi-year trajectory health score (growing/consistent
               FCF, sane leverage) must be non-negative
  HONEST     — hard veto on: accrual red flag, active integrity flag;
               circular-financing participants get halved

Stock score in [0,1]. Financial-institution mode symbols (banks) score on
earnings yield + P/B only (FCF is meaningless for them).

Crypto has no cash flows, so "value" = price vs its own long-run adoption:
  - Mayer multiple (price / 200d MA) — historically <0.8 marked value zones
  - usage/price divergence: BTC active addresses trending UP over ~90d while
    price trended DOWN (people using it more while it gets cheaper)
  - extreme fear (F&G <= 20) as the contrarian confirmation

Both feed the brain as POSITIVE resting anchors (the node "wants" to rise),
deliberately capped: value says WHAT to own, the trend/winter gates still
say WHEN — a value anchor never overrides the don't-catch-knives machinery.

CLI: python -m ai_investing.data.value_scanner        # ranked stock report
     python -m ai_investing.data.value_scanner --crypto
"""
from __future__ import annotations

import json
import os
import sys
import time

CACHE_MAX_AGE = 6 * 3600


def _data_dir(settings=None) -> str:
    if settings is not None:
        return os.path.dirname(os.path.abspath(settings.state_path))
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))))
    return os.path.join(root, "data")


# ------------------------------------------------------------- intrinsic ----
DISCOUNT_RATE = 0.10        # required return — the hurdle every business must clear
TERMINAL_GROWTH = 0.025     # ~nominal GDP forever after year 5
GROWTH_CAP = 0.20           # never extrapolate hypergrowth
GROWTH_DAMP = 0.70          # trust only 70% of measured growth going forward


def intrinsic_value(years: list[dict]) -> dict | None:
    """Conservative owner-earnings DCF from the compiled annual history.

    Undervalued != low multiple. A compounder at PE 25 can be worth more than
    its price; a PE-6 melting ice cube can be worth less. So: project the
    latest FCF forward 5 years at a DAMPED, CAPPED version of the growth the
    company actually demonstrated (min of FCF and revenue growth — the more
    conservative of the two), then a terminal value at ~GDP growth, all
    discounted at 10%. Every assumption leans low on purpose: the output is a
    floor-ish estimate, and the margin of safety does the rest."""
    ys = [y for y in years if y.get("fcf") is not None]
    if len(ys) < 2:
        return None
    fcfs = [y["fcf"] for y in ys]
    base = (fcfs[-1] + fcfs[-2]) / 2 if len(fcfs) >= 2 else fcfs[-1]   # smooth one-offs
    if base <= 0:
        return None
    n = len(ys) - 1
    g_fcf = (fcfs[-1] / fcfs[0]) ** (1 / n) - 1 if fcfs[0] > 0 else 0.0
    revs = [y.get("revenue") for y in ys if y.get("revenue")]
    g_rev = (revs[-1] / revs[0]) ** (1 / (len(revs) - 1)) - 1 if len(revs) >= 2 and revs[0] > 0 else 0.0
    g = max(0.0, min(GROWTH_CAP, min(g_fcf, g_rev))) * GROWTH_DAMP
    iv, cf = 0.0, base
    for t in range(1, 6):
        cf *= (1 + g)
        iv += cf / (1 + DISCOUNT_RATE) ** t
    terminal = cf * (1 + TERMINAL_GROWTH) / (DISCOUNT_RATE - TERMINAL_GROWTH)
    iv += terminal / (1 + DISCOUNT_RATE) ** 5
    return {"iv": iv, "growth_used": round(g, 4), "base_fcf": base}


# ---------------------------------------------------------------- stocks ----
def stock_value_scores(settings=None) -> dict[str, dict]:
    """symbol -> {score 0..1, reasons, vetoes} for every graph stock with data."""
    from ai_investing.data.fundamentals_history import load_cache
    try:
        with open(os.path.join(_data_dir(settings), "fundamentals.json")) as fh:
            snap = json.load(fh)
    except (OSError, json.JSONDecodeError):
        snap = {}
    try:
        from ai_investing.brain.integrity import current_flags
        from ai_investing.brain.graph import KnowledgeGraph
        g = KnowledgeGraph.seeded()
        flagged_syms = {g.nodes[nid].symbol for nid in current_flags(settings)
                        if nid in g.nodes and g.nodes[nid].symbol}
        in_circle = set()
        for lp in g.detect_circular_financing():
            for nid in lp.get("participants", []):
                n = g.nodes.get(nid)
                if n is not None and n.symbol:
                    in_circle.add(n.symbol)
    except Exception:
        flagged_syms, in_circle = set(), set()
    try:
        from ai_investing.data.comps import relative_value_scores
        rel = relative_value_scores(settings)
    except Exception:
        rel = {}

    out: dict[str, dict] = {}
    for sym, rec in load_cache(settings).items():
        years, traj = rec.get("years") or [], rec.get("trajectory") or {}
        if not years or traj.get("years_covered", 0) < 2:
            continue
        latest = traj.get("latest") or years[-1]
        f = snap.get(sym, {})
        reasons, vetoes = [], []
        score = 0.0
        mcap = f.get("marketCap")
        is_fin = traj.get("is_financial")

        if not is_fin and mcap and latest.get("fcf") and latest["fcf"] > 0:
            fcf_yield = latest["fcf"] / mcap
            pe_cheap = f.get("trailingPE") and 0 < f["trailingPE"] <= 14
            if fcf_yield > 0.30:
                # implausible: almost always local-currency statements vs USD
                # market cap (ADRs: JPY/TWD/SEK...). PE is currency-consistent,
                # so only credit cheapness if PE independently confirms it.
                if pe_cheap:
                    score += 0.25
                    reasons.append("FCF yield high but currency-suspect; PE confirms cheap")
            else:
                # Two routes to "undervalued", credit the BETTER one:
                #  - intrinsic: margin of safety vs a conservative DCF (catches
                #    compounders whose growth is worth more than their multiple)
                #  - raw cash yield (catches no-growth deep cheapness)
                dcf = intrinsic_value(years)
                mos = 1.0 - mcap / dcf["iv"] if dcf and dcf["iv"] > 0 else None
                dcf_credit = 0.0
                if mos is not None and mos >= 0.15:
                    dcf_credit = 0.45 if mos >= 0.40 else (0.35 if mos >= 0.30 else 0.20)
                yield_credit = 0.40 if fcf_yield >= 0.08 else (0.25 if fcf_yield >= 0.05 else 0.0)
                if dcf_credit or yield_credit:
                    score += max(dcf_credit, yield_credit)
                    if dcf_credit >= yield_credit:
                        reasons.append(f"margin of safety {mos:.0%} vs DCF "
                                       f"(growth used {dcf['growth_used']:.0%})")
                    else:
                        reasons.append(f"FCF yield {fcf_yield:.0%}")
                    if dcf_credit and yield_credit and dcf_credit < yield_credit:
                        reasons.append(f"DCF agrees (MoS {mos:.0%})")

        pe = f.get("trailingPE") or f.get("forwardPE")
        if pe and 0 < pe <= 10:
            score += 0.20; reasons.append(f"PE {pe:.1f}")
        elif pe and 0 < pe <= 14:
            score += 0.10; reasons.append(f"PE {pe:.1f}")

        pb = f.get("priceToBook")
        if pb and 0 < pb < 1.2:
            score += 0.15; reasons.append(f"P/B {pb:.2f}")

        rc = traj.get("revenue_cagr")
        if score > 0 and rc is not None and rc > 0.05:
            score += 0.10; reasons.append(f"still growing {rc:.0%}/yr")

        # sustainable dividend: covered by cash (<=70% of FCF), long record,
        # not at risk — income you can actually rely on adds to the value case
        div = rec.get("dividends") or {}
        dy = f.get("dividendYield")
        if dy and dy > 1.0:
            dy = dy / 100.0            # yfinance version drift: percent vs fraction
        if (score > 0 and div.get("pays") and not div.get("at_risk")
                and not div.get("cut_recently")
                and div.get("verdict") in ("compounder", "steady")
                and (div.get("payout_fcf") or 0) <= 0.7 and dy and dy >= 0.03):
            score += 0.10
            reasons.append(f"covered dividend {dy:.1%} "
                           f"({div['verdict']}, {div.get('streak_years', 0)}y streak)")
        elif div.get("at_risk"):
            reasons.append("caution: dividend at risk — " +
                           "; ".join(div.get("risk_reasons", [])[:1]))

        # peer comps: also cheap RELATIVE to its own theme group (EV/EBITDA z)
        if score > 0 and rel.get(sym, 0.0) >= 0.2:
            score += 0.15 * rel[sym]
            reasons.append(f"cheap vs peers (comps score {rel[sym]:.2f})")

        # ---- honesty & resilience gates (this is what kills value traps) ----
        health = traj.get("health", 0.0)
        if health < 0:
            vetoes.append(f"decaying trajectory (health {health:+.2f})")
        if traj.get("accrual_red_flag"):
            vetoes.append("accrual red flag: profits aren't becoming cash")
        if sym in flagged_syms:
            vetoes.append("active integrity flag")
        if vetoes:
            score = 0.0
        elif sym in in_circle:
            score *= 0.5
            reasons.append("halved: circular-financing participant")
        elif health >= 0.5:
            score = min(1.0, score * 1.2)
            reasons.append(f"quality bonus (health {health:+.2f})")

        if score > 0 or vetoes:
            out[sym] = {"score": round(min(1.0, score), 3),
                        "reasons": reasons, "vetoes": vetoes}
    return out


# ---------------------------------------------------------------- crypto ----
def crypto_value_scores(settings=None) -> dict[str, dict]:
    """BTC/ETH/SOL value-zone scores from mayer multiple, usage/price
    divergence (BTC only), and extreme fear. Cached ~6h."""
    path = os.path.join(_data_dir(settings), "crypto_value.json")
    try:
        with open(path) as fh:
            cached = json.load(fh)
        if time.time() - cached.get("asof", 0) < CACHE_MAX_AGE:
            return cached["scores"]
    except (OSError, json.JSONDecodeError, KeyError):
        pass

    scores: dict[str, dict] = {}
    try:
        import warnings
        warnings.filterwarnings("ignore")
        import yfinance as yf
        fng = None
        try:
            from ai_investing.research.crypto_signals import refresh_live
            days = sorted((refresh_live().get("fng") or {}).items())
            fng = int(days[-1][1]) if days else None
        except Exception:
            pass
        addr_trend = None
        try:
            import urllib.request
            req = urllib.request.Request(
                "https://api.blockchain.info/charts/n-unique-addresses?timespan=180days&format=json",
                headers={"User-Agent": "ai-investing/0.1"})
            vals = [v["y"] for v in json.loads(urllib.request.urlopen(req, timeout=30
                                                                      ).read())["values"]]
            if len(vals) >= 60:
                addr_trend = (sum(vals[-30:]) / 30) / (sum(vals[:30]) / 30) - 1
        except Exception:
            pass
        for sym in ("BTC-USD", "ETH-USD", "SOL-USD"):
            px = yf.Ticker(sym).history(period="1y", interval="1d")["Close"]
            if len(px) < 210:
                continue
            mayer = float(px.iloc[-1] / px.rolling(200).mean().iloc[-1])
            ret90 = float(px.iloc[-1] / px.iloc[-90] - 1)
            s, reasons = 0.0, []
            if mayer < 0.8:
                s += min(0.4, (0.8 - mayer) * 2)
                reasons.append(f"mayer {mayer:.2f} (deep below 200d)")
            if fng is not None and fng <= 20:
                s += 0.3; reasons.append(f"extreme fear (F&G {fng})")
            if sym == "BTC-USD" and addr_trend is not None and addr_trend > 0.05 and ret90 < -0.1:
                s += 0.3
                reasons.append(f"usage/price divergence (addresses +{addr_trend:.0%}, price {ret90:.0%})")
            if s > 0:
                scores[sym.replace("-USD", "/USD")] = {"score": round(min(1.0, s), 3),
                                                       "reasons": reasons,
                                                       "mayer": round(mayer, 3)}
    except Exception:
        pass
    try:
        with open(path, "w") as fh:
            json.dump({"asof": time.time(), "scores": scores}, fh)
    except OSError:
        pass
    return scores


if __name__ == "__main__":
    if "--crypto" in sys.argv:
        for sym, r in sorted(crypto_value_scores().items(), key=lambda kv: -kv[1]["score"]):
            print(f"{sym:9s} {r['score']:.2f}  {'; '.join(r['reasons'])}")
        print("(empty = nothing in the value zone right now — that is a valid answer)")
    else:
        rows = stock_value_scores()
        ranked = sorted((r for r in rows.items() if r[1]["score"] > 0),
                        key=lambda kv: -kv[1]["score"])
        print(f"UNDERVALUED (cheap + honest + resilient), {len(ranked)} candidates:")
        for sym, r in ranked[:20]:
            print(f"  {sym:10s} {r['score']:.2f}  {'; '.join(r['reasons'])}")
        trapped = [(s, r) for s, r in rows.items() if r["vetoes"]]
        if trapped:
            print(f"\nVALUE TRAPS excluded ({len(trapped)}):")
            for sym, r in trapped[:12]:
                print(f"  {sym:10s} —  {'; '.join(r['vetoes'])}")
