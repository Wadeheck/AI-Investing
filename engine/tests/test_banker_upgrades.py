"""The 7 investment-banker upgrades: cluster caps, event gating, estimates,
ownership, balance-sheet depth, comps, stress."""
import datetime

from ai_investing.brain.graph import KnowledgeGraph
from ai_investing.brain.stress import SCENARIOS, run_stress
from ai_investing.data.calendar_events import FOMC, is_macro_event_day
from ai_investing.data.estimates import score as est_score
from ai_investing.data.fundamentals_history import trajectory
from ai_investing.data.ownership import score as own_score
from ai_investing.strategy.clusters import cluster_gross, clusters_for


# ---- 1. structural clusters -------------------------------------------------
def test_ai_bom_tickers_share_a_cluster():
    """Seven AI-BOM tickers must resolve to one common structural bet."""
    syms = ["NVDA", "SMCI", "VRT", "AMAT", "ANET", "TSM", "AVGO"]
    common = set.intersection(*(set(clusters_for(s)) for s in syms))
    assert "ai_capex_cycle" in common          # the true name of the shared bet


def test_unrelated_names_do_not_cluster_together():
    assert not (clusters_for("KO") & clusters_for("NVDA"))


def test_cluster_gross_aggregates_the_bet():
    g = cluster_gross({"stock:NVDA": 30_000.0, "stock:SMCI": 20_000.0,
                       "stock:KO": 10_000.0})
    assert g.get("ai_datacenter", 0) >= 50_000.0          # one 50k bet, not two 25k
    assert g.get("food_beverage", 0) == 10_000.0


# ---- 2. event calendar ------------------------------------------------------
def test_fomc_days_gate_and_normal_days_dont():
    d = datetime.date.fromisoformat(FOMC[2026][0])
    assert is_macro_event_day(d)
    assert not is_macro_event_day(d + datetime.timedelta(days=1))


# ---- 3. expectations layer --------------------------------------------------
def test_estimate_scoring_directions():
    up = est_score({"rev_30d": 0.06, "surprise_avg4": 0.08, "target_gap": 0.2})
    down = est_score({"rev_30d": -0.06, "surprise_avg4": -0.05})
    assert up >= 0.6 > 0 > down <= -0.5
    assert est_score({}) == 0.0


# ---- 4. ownership -----------------------------------------------------------
def test_insider_cluster_buys_dominate():
    # cluster = 2+ open-market buys from 2+ DISTINCT insiders
    assert own_score({"insider_buys": 3, "insider_buyers": 2, "insider_sells": 1}) >= 0.35
    # one insider buying repeatedly is notable, not a cluster
    assert own_score({"insider_buys": 3, "insider_buyers": 1, "insider_sells": 0}) <= 0.15
    assert own_score({"insider_buys": 0, "insider_buyers": 0, "insider_sells": 8}) < 0
    strong = {"insider_buys": 3, "insider_buyers": 2, "insider_sells": 1}
    assert own_score({**strong, "short_pct_float": 0.25}) < own_score(strong)


# ---- 5. balance-sheet depth -------------------------------------------------
def _yr(y, **kw):
    base = {"year": y, "revenue": 1000.0, "net_income": 100.0, "fcf": 100.0,
            "total_debt": 400.0, "cash": 150.0, "equity": 800.0, "total_assets": 2000.0}
    base.update(kw)
    return base


def test_maturity_wall_and_coverage_flags():
    ys = [_yr(2023), _yr(2024, current_debt=250.0, interest_expense=40.0, ebit=80.0)]
    t = trajectory(ys)
    assert t["maturity_wall_risk"]                        # 250 due > 150 cash
    assert t["interest_coverage"] == 2.0                  # covenant zone
    healthy = trajectory([_yr(2023), _yr(2024, current_debt=40.0,
                                         interest_expense=10.0, ebit=300.0)])
    assert not healthy.get("maturity_wall_risk")
    assert t["health"] < healthy["health"]


def test_dilution_tax_and_buyback_bonus():
    dil = trajectory([_yr(2022, diluted_shares=1000.0), _yr(2023, diluted_shares=1080.0),
                      _yr(2024, diluted_shares=1170.0)])
    bb = trajectory([_yr(2022, diluted_shares=1000.0), _yr(2023, diluted_shares=975.0),
                     _yr(2024, diluted_shares=950.0)])
    assert dil["dilution_rate"] > 0.04 > 0 > bb["dilution_rate"]
    assert bb["health"] > dil["health"]


# ---- 6+7. comps guard & stress engine --------------------------------------
def test_comps_currency_guard():
    from ai_investing.data.comps import ev_ebitda
    hist = {"X": {"years": [{"year": 2024, "ebit": 50_000.0, "dna": 10_000.0,
                             "total_debt": 0.0, "cash": 0.0}],
                  "trajectory": {"is_financial": False}}}
    assert ev_ebitda("X", {"X": {"marketCap": 600_000.0}}, hist) == 10.0
    # JPY-statements-vs-USD-mcap artifact: multiple of 0.01x must be rejected
    assert ev_ebitda("X", {"X": {"marketCap": 600.0}}, hist) is None


def test_stress_scenarios_hit_the_right_assets():
    g = KnowledgeGraph.seeded()
    rep = run_stress(g)
    assert set(rep) >= set(SCENARIOS)
    ai_worst = dict(rep["ai_unwind"]["worst_assets"])
    assert any(s in ai_worst for s in ("NVDA", "SMCI", "CRWV", "AVGO", "TSM"))
    tw_worst = dict(rep["taiwan_strait"]["worst_assets"])
    assert any(s in tw_worst for s in ("TSM", "2317.TW", "NVDA"))
    # book exposure: long AI book must be hurt by the AI unwind
    rep2 = run_stress(g, positions_weights={"NVDA": 0.2, "SMCI": 0.1, "KO": 0.1})
    assert rep2["ai_unwind"]["book_exposure"] < 0
    assert rep2["_summary"]["worst_exposure"] <= rep2["ai_unwind"]["book_exposure"]
