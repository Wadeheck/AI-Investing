"""Multi-year fundamental history for every stock in the knowledge graph.

The weekly `fundamentals.py` cache is a SNAPSHOT (today's ratios). This module
compiles the TRAJECTORY: annual statements — revenue, net income, free cash
flow, total debt, cash, total assets, equity — for ~4-5 fiscal years per
company (the depth the free provider exposes), plus derived per-year ratios
and a health score built from the trend, not the level:

  - consistent positive FCF across the window (resilience)
  - revenue growing (goods/services actually demanded)
  - FCF growing (the growth converts to cash)
  - deleveraging or conservative debt (survives a downturn)
  - penalties: latest FCF negative, negative equity, debt rising while
    revenue shrinks (the classic death spiral)

Cache: data/fundamentals_history.json, per-symbol asof stamp, refreshed when
older than MAX_AGE_DAYS. ETFs/crypto return no statements and are recorded
as empty so they don't burn the fetch budget again until stale.

CLI:
  python -m ai_investing.data.fundamentals_history --compile [--limit 30]
  python -m ai_investing.data.fundamentals_history --show SMCI
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone

MAX_AGE_DAYS = 30
FETCH_BUDGET = 25            # symbols refreshed per --compile/refresh call

# statement row -> our field (first match wins)
_ROWS = {
    "revenue": ("Total Revenue", "Operating Revenue"),
    "net_income": ("Net Income", "Net Income Common Stockholders"),
    "fcf": ("Free Cash Flow",),
    "op_cashflow": ("Operating Cash Flow", "Cash Flow From Continuing Operating Activities"),
    "capex": ("Capital Expenditure",),
    "total_debt": ("Total Debt", "Long Term Debt And Capital Lease Obligation", "Long Term Debt"),
    "cash": ("Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments"),
    "total_assets": ("Total Assets",),
    "equity": ("Stockholders Equity", "Common Stock Equity", "Total Equity Gross Minority Interest"),
    "dividends_paid": ("Cash Dividends Paid", "Common Stock Dividend Paid"),
    # banker's balance-sheet depth (seen by trajectory() below):
    "current_debt": ("Current Debt", "Current Debt And Capital Lease Obligation",
                     "Other Current Borrowings"),
    "interest_expense": ("Interest Expense", "Interest Expense Non Operating"),
    "ebit": ("EBIT", "Operating Income"),
    "diluted_shares": ("Diluted Average Shares", "Basic Average Shares"),
    "dna": ("Depreciation And Amortization", "Depreciation Amortization Depletion"),
}


def _cache_path(settings=None) -> str:
    from ai_investing.data.paths import data_path
    return data_path("fundamentals_history.json", settings)


def load_cache(settings=None) -> dict:
    try:
        with open(_cache_path(settings)) as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}


def _save(cache: dict, settings=None) -> None:
    path = _cache_path(settings)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(cache, fh)


def _pick(df, names):
    for n in names:
        if n in df.index:
            return df.loc[n]
    return None


def fetch_years(symbol: str) -> list[dict]:
    """Annual statement history for one symbol, oldest -> newest. [] = none
    (ETF, index, crypto, or provider has nothing)."""
    import yfinance as yf
    t = yf.Ticker(symbol)
    try:
        inc, bal, cf = t.income_stmt, t.balance_sheet, t.cashflow
    except Exception:
        return []
    if inc is None or inc.empty:
        return []
    series = {}
    for field, names in _ROWS.items():
        for df in (inc, bal, cf):
            if df is None or df.empty:
                continue
            s = _pick(df, names)
            if s is not None:
                series[field] = s
                break
    years: dict[int, dict] = {}
    for field, s in series.items():
        for col, val in s.items():
            if val is None or (isinstance(val, float) and val != val):   # NaN
                continue
            y = col.year if hasattr(col, "year") else int(str(col)[:4])
            years.setdefault(y, {"year": y})[field] = float(val)
    out = []
    for y in sorted(years):
        r = years[y]
        if "fcf" not in r and "op_cashflow" in r:
            r["fcf"] = r["op_cashflow"] + r.get("capex", 0.0)   # capex is negative
        rev, ni, fcf, eq = (r.get(k) for k in ("revenue", "net_income", "fcf", "equity"))
        if rev:
            if ni is not None:
                r["net_margin"] = round(ni / rev, 4)
            if fcf is not None:
                r["fcf_margin"] = round(fcf / rev, 4)
        if eq and r.get("total_debt") is not None:
            r["debt_to_equity"] = round(r["total_debt"] / eq, 3) if eq > 0 else None
        div = r.get("dividends_paid")
        if div is not None:
            r["dividends_paid"] = abs(div)          # statements report it negative
            if fcf and fcf > 0:
                r["payout_fcf"] = round(r["dividends_paid"] / fcf, 3)
            if ni and ni > 0:
                r["payout_ni"] = round(r["dividends_paid"] / ni, 3)
        out.append(r)
    return out


def fetch_dividends_per_share(symbol: str, years_back: int = 15) -> dict[str, float]:
    """Annual dividend-per-share totals from the full payout history (goes back
    DECADES — much deeper than the statements). {} = never paid / no data."""
    import yfinance as yf
    try:
        s = yf.Ticker(symbol).dividends
        if s is None or s.empty:
            return {}
        by_year: dict[str, float] = {}
        for ts, v in s.items():
            by_year[str(ts.year)] = by_year.get(str(ts.year), 0.0) + float(v)
        yrs = sorted(by_year)[-years_back:]
        return {y: round(by_year[y], 4) for y in yrs}
    except Exception:
        return {}


def dividend_trajectory(dps: dict[str, float], years: list[dict]) -> dict:
    """Dividend strength read: streak, growth, cuts, and — the part that
    predicts cuts before they're announced — CASH COVERAGE. Dividends are paid
    from the same FCF pool everything else is; a dividend that FCF no longer
    covers is a promise, not a payout.

    at_risk fires on any of the classic pre-cut signatures:
      - payout > 90% of FCF (no room left)
      - dividend held/raised while FCF fell >30% (paying from the past)
      - paying a dividend while FCF is negative (paying from debt)
    """
    # drop the current partial year (looks like a false cut mid-year)
    from datetime import datetime, timezone
    this_year = str(datetime.now(timezone.utc).year)
    hist = {y: v for y, v in (dps or {}).items() if y < this_year and v > 0}
    if not hist:
        return {"pays": False}
    ys = sorted(hist)
    # lapsed payer (e.g. stopped paying decades ago): history exists but is
    # stale — that's "discontinued", not a recent cut, and not income today
    if int(ys[-1]) < int(this_year) - 2:
        return {"pays": False, "verdict": "discontinued",
                "last_paid_year": int(ys[-1])}
    out: dict = {"pays": True, "years_of_history": len(ys),
                 "latest_dps": hist[ys[-1]], "latest_year": int(ys[-1])}
    # consecutive payment streak (from most recent backward, no gap years)
    streak = 1
    for a, b in zip(reversed(ys[:-1]), reversed(ys[1:])):
        if int(b) - int(a) == 1:
            streak += 1
        else:
            break
    out["streak_years"] = streak
    cuts = [(ys[i], round(hist[ys[i]] / hist[ys[i - 1]] - 1, 3))
            for i in range(1, len(ys))
            if hist[ys[i]] < hist[ys[i - 1]] * 0.90]        # >10% drop = a cut
    out["cuts"] = cuts[-3:]
    out["cut_recently"] = any(int(y) >= int(ys[-1]) - 2 for y, _ in cuts)
    grew = sum(1 for i in range(1, len(ys)) if hist[ys[i]] > hist[ys[i - 1]] * 1.005)
    out["growth_years"] = grew
    if len(ys) >= 4 and hist[ys[-4]] > 0:
        out["dps_cagr_3y"] = round((hist[ys[-1]] / hist[ys[-4]]) ** (1 / 3) - 1, 4)
    # cash coverage from the statements window
    recent = [y for y in years if y.get("dividends_paid")]
    risks = []
    if recent:
        last = recent[-1]
        fcf = last.get("fcf")
        if fcf is not None and fcf <= 0:
            risks.append("paying a dividend while FCF is negative (funded by debt)")
        elif last.get("payout_fcf") is not None:
            out["payout_fcf"] = last["payout_fcf"]
            if last["payout_fcf"] > 0.9:
                risks.append(f"payout is {last['payout_fcf']:.0%} of FCF — no room left")
        fcfs = [y.get("fcf") for y in years if y.get("fcf") is not None]
        divs = [y.get("dividends_paid") for y in recent]
        if (len(fcfs) >= 2 and fcfs[0] and fcfs[-1] < fcfs[0] * 0.7
                and len(divs) >= 2 and divs[-1] >= divs[0] * 0.99):
            risks.append("dividend held while FCF fell >30% — paying from the past")
    out["at_risk"] = bool(risks)
    out["risk_reasons"] = risks
    # one-word verdict for humans and the dashboard
    if out["at_risk"]:
        out["verdict"] = "at_risk"
    elif out["cut_recently"]:
        out["verdict"] = "recently_cut"
    elif streak >= 10 and grew >= len(ys) * 0.6:
        out["verdict"] = "compounder"
    elif streak >= 5:
        out["verdict"] = "steady"
    else:
        out["verdict"] = "young"
    return out


def trajectory(years: list[dict]) -> dict:
    """Trend metrics + health score in [-1, 1] from >=2 annual records."""
    ys = [y for y in years if y.get("revenue")]
    if len(ys) < 2:
        return {"health": 0.0, "years_covered": len(ys), "note": "insufficient history"}
    first, last = ys[0], ys[-1]
    n = len(ys) - 1
    out: dict = {"years_covered": len(ys),
                 "span": f"{first['year']}-{last['year']}"}
    if first["revenue"] > 0:
        out["revenue_cagr"] = round((last["revenue"] / first["revenue"]) ** (1 / n) - 1, 4)
    fcfs = [y.get("fcf") for y in ys if y.get("fcf") is not None]
    out["fcf_positive_years"] = sum(1 for f in fcfs if f > 0)
    out["fcf_years"] = len(fcfs)
    if len(fcfs) >= 2 and fcfs[0]:
        out["fcf_growing"] = fcfs[-1] > fcfs[0] > 0
    debts = [y.get("total_debt") for y in ys if y.get("total_debt") is not None]
    if len(debts) >= 2:
        out["deleveraging"] = debts[-1] < debts[0]
    out["latest"] = {k: last.get(k) for k in
                     ("year", "revenue", "net_income", "fcf", "total_debt", "cash",
                      "total_assets", "equity", "net_margin", "fcf_margin", "debt_to_equity")}

    # -- banker's balance-sheet depth ------------------------------------
    # maturity wall proxy: how much of the debt is due within a year, and can
    # cash cover it? (Refinancing risk is what kills companies in tight credit.)
    cd, td, cash = last.get("current_debt"), last.get("total_debt"), last.get("cash")
    if cd is not None and td:
        out["debt_due_1y_pct"] = round(cd / td, 3)
        if cash is not None:
            out["maturity_wall_risk"] = bool(cd > cash and cd / td > 0.35)
    # interest coverage: EBIT / interest — the covenant metric
    ie, ebit = last.get("interest_expense"), last.get("ebit")
    if ie and abs(ie) > 0 and ebit is not None:
        out["interest_coverage"] = round(ebit / abs(ie), 2)
    # dilution: share count trajectory (SBC's silent tax; negative = buybacks)
    shares = [(y["year"], y["diluted_shares"]) for y in ys if y.get("diluted_shares")]
    if len(shares) >= 2 and shares[0][1] > 0:
        yrs_span = max(1, shares[-1][0] - shares[0][0])
        out["dilution_rate"] = round((shares[-1][1] / shares[0][1]) ** (1 / yrs_span) - 1, 4)

    # financial-institution mode: banks/insurers have revenue tiny relative to
    # the balance sheet; FCF and debt/equity are meaningless for them (the
    # balance sheet IS the business). Skip the industrial-style cash tests.
    ta = last.get("total_assets")
    is_financial = bool(ta and last["revenue"] / ta < 0.12)
    out["is_financial"] = is_financial

    # earnings quality (the Enron/Wirecard/Luckin tell): profits that never
    # become cash. cash_conversion = median FCF/NI across profitable years.
    convs = [y["fcf"] / y["net_income"] for y in ys
             if y.get("net_income") and y["net_income"] > 0 and y.get("fcf") is not None]
    if convs:
        convs.sort()
        out["cash_conversion"] = round(convs[len(convs) // 2], 3)
    nis = [y.get("net_income") for y in ys if y.get("net_income") is not None]
    earnings_growing = len(nis) >= 2 and nis[-1] > nis[0] > 0
    out["accrual_red_flag"] = bool(
        not is_financial and earnings_growing and convs and out["cash_conversion"] < 0.5)

    h = 0.0
    if out["accrual_red_flag"]:
        h -= 0.35        # reported profits growing but cash persistently missing
    if fcfs:
        if out["fcf_positive_years"] == len(fcfs):
            h += 0.3                                     # cash machine, every year
        elif fcfs[-1] is not None and fcfs[-1] <= 0:
            h -= 0.3                                     # currently burning cash
    if out.get("fcf_growing"):
        h += 0.2
    rc = out.get("revenue_cagr")
    if rc is not None:
        h += 0.2 if rc > 0.05 else (-0.2 if rc < 0 else 0.0)
    de = last.get("debt_to_equity")
    if not is_financial:                       # leverage IS a bank's business model
        if out.get("deleveraging") or (de is not None and 0 <= de < 1.0):
            h += 0.15
        if de is not None and de > 2.5:
            h -= 0.15
    if last.get("equity") is not None and last["equity"] < 0:
        h -= 0.25                                        # negative book value
    if (len(debts) >= 2 and debts[-1] > debts[0] and rc is not None and rc < 0):
        h -= 0.25                                        # borrowing while shrinking
    if not is_financial:
        if out.get("maturity_wall_risk"):
            h -= 0.15        # near-term debt exceeds cash — refinancing hostage
        ic = out.get("interest_coverage")
        if ic is not None and 0 <= ic < 3:
            h -= 0.15        # covenant-zone coverage
        dil = out.get("dilution_rate")
        if dil is not None:
            if dil > 0.04:
                h -= 0.10    # >4%/yr dilution silently taxes every holder
            elif dil < -0.01:
                h += 0.05    # steady buybacks: a standing bid under the stock
    out["health"] = round(max(-1.0, min(1.0, h)), 3)
    return out


def health_with_dividends(traj: dict, div: dict) -> float:
    """Blend the dividend read into overall health: a long, covered, growing
    payout is evidence of discipline (+); an at-risk or freshly cut one is an
    early stress signal the income statement hasn't admitted yet (−)."""
    h = traj.get("health", 0.0)
    if not div.get("pays"):
        return h
    if div.get("at_risk"):
        h -= 0.2
    elif div.get("cut_recently"):
        h -= 0.1
    elif div.get("verdict") == "compounder":
        h += 0.1
    elif div.get("verdict") == "steady":
        h += 0.05
    return round(max(-1.0, min(1.0, h)), 3)


def graph_stock_symbols() -> list[str]:
    from ai_investing.brain.graph import KnowledgeGraph
    g = KnowledgeGraph.seeded()
    return [n.symbol for n in g.nodes.values()
            if n.type == "asset" and n.symbol and n.market != "CRYPTO"]


def compile_history(symbols: list[str] | None = None, budget: int = FETCH_BUDGET,
                    settings=None) -> dict:
    """Refresh up to `budget` stale symbols; returns the full cache."""
    cache = load_cache(settings)
    now = time.time()
    todo = []
    for sym in (symbols or graph_stock_symbols()):
        rec = cache.get(sym)
        if rec and now - rec.get("asof", 0) < MAX_AGE_DAYS * 86400:
            continue
        todo.append(sym)
    for sym in todo[:budget]:
        try:
            years = fetch_years(sym)
        except Exception:
            years = []
        dps = fetch_dividends_per_share(sym) if years else {}
        cache[sym] = {"asof": now, "years": years, "dps": dps,
                      "trajectory": trajectory(years) if years else {"health": 0.0,
                                                                     "years_covered": 0},
                      "dividends": dividend_trajectory(dps, years)}
        print(f"[fund-hist] {sym}: {len(years)} fiscal years, "
              f"health {cache[sym]['trajectory'].get('health')}, "
              f"dividend {cache[sym]['dividends'].get('verdict', '-')}", flush=True)
        time.sleep(0.5)
    _save(cache, settings)
    remaining = max(0, len(todo) - budget)
    if remaining:
        print(f"[fund-hist] {remaining} symbols still stale — re-run to continue", flush=True)
    return cache


def health_scores(settings=None) -> dict[str, float]:
    """symbol -> health in [-1,1] (trajectory + dividend read), only where
    real history exists."""
    out = {}
    for sym, rec in load_cache(settings).items():
        if rec.get("years") and rec.get("trajectory", {}).get("years_covered", 0) >= 2:
            out[sym] = health_with_dividends(rec["trajectory"], rec.get("dividends", {}))
    return out


if __name__ == "__main__":
    if "--show" in sys.argv:
        sym = sys.argv[sys.argv.index("--show") + 1]
        rec = load_cache().get(sym)
        print(json.dumps(rec, indent=1, default=str) if rec else f"{sym}: not compiled yet")
    else:
        syms = None
        if "--symbols" in sys.argv:
            syms = sys.argv[sys.argv.index("--symbols") + 1].split(",")
        budget = FETCH_BUDGET
        if "--limit" in sys.argv:
            budget = int(sys.argv[sys.argv.index("--limit") + 1])
        print(f"[fund-hist] compiled {datetime.now(timezone.utc).isoformat(timespec='seconds')}; "
              f"cache now {len(compile_history(syms, budget))} symbols")
