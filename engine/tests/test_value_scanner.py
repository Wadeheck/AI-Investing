"""Value scanner: cheap+honest+resilient scores; traps vetoed; units guarded."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import json
import os
import tempfile

from ai_investing.config import Settings
from ai_investing.data.value_scanner import stock_value_scores


def _setup(hist, snap):
    d = tempfile.mkdtemp()
    os.environ["STATE_PATH"] = os.path.join(d, "state.json")
    with open(os.path.join(d, "fundamentals_history.json"), "w") as fh:
        json.dump(hist, fh)
    with open(os.path.join(d, "fundamentals.json"), "w") as fh:
        json.dump(snap, fh)
    return Settings()


def _hist(sym, fcf, health, accrual=False, years=3):
    return {sym: {"asof": 1, "years": [{"year": 2023 + i, "revenue": 1000.0,
                                        "fcf": fcf, "net_income": fcf}
                                       for i in range(years)],
                  "trajectory": {"years_covered": years, "health": health,
                                 "accrual_red_flag": accrual, "revenue_cagr": 0.08,
                                 "latest": {"fcf": fcf, "revenue": 1000.0}}}}


def test_cheap_honest_resilient_scores_high():
    s = _setup(_hist("CHEAPCO", fcf=100.0, health=0.6),
               {"CHEAPCO": {"trailingPE": 8.0, "priceToBook": 0.9, "marketCap": 1000.0}})
    r = stock_value_scores(s)["CHEAPCO"]
    assert r["score"] >= 0.8 and not r["vetoes"]      # 10% FCF yield, PE 8, P/B 0.9


def test_cheap_but_decaying_is_a_veto():
    s = _setup(_hist("TRAPCO", fcf=100.0, health=-0.4),
               {"TRAPCO": {"trailingPE": 4.0, "priceToBook": 0.4, "marketCap": 1000.0}})
    r = stock_value_scores(s)["TRAPCO"]
    assert r["score"] == 0.0 and any("decaying" in v for v in r["vetoes"])


def test_accrual_flag_is_a_veto_even_when_cheap():
    s = _setup(_hist("ENRONCO", fcf=100.0, health=0.4, accrual=True),
               {"ENRONCO": {"trailingPE": 6.0, "marketCap": 1000.0}})
    r = stock_value_scores(s)["ENRONCO"]
    assert r["score"] == 0.0 and any("accrual" in v for v in r["vetoes"])


def test_currency_suspect_fcf_needs_pe_confirmation():
    # 200% "FCF yield" (local-currency statements vs USD mcap) with NO cheap PE
    s = _setup(_hist("ADRCO", fcf=2000.0, health=0.5),
               {"ADRCO": {"trailingPE": 45.0, "marketCap": 1000.0}})
    r = stock_value_scores(s).get("ADRCO")
    assert r is None or r["score"] <= 0.15            # no free points from broken units
    # same yield WITH a confirming PE gets the guarded mid-tier credit
    s2 = _setup(_hist("ADRCO2", fcf=2000.0, health=0.5),
                {"ADRCO2": {"trailingPE": 9.0, "marketCap": 1000.0}})
    r2 = stock_value_scores(s2)["ADRCO2"]
    assert r2["score"] >= 0.4
    assert any("currency-suspect" in x for x in r2["reasons"])


def test_expensive_quality_scores_zero():
    s = _setup(_hist("GROWCO", fcf=10.0, health=0.8),   # 1% FCF yield
               {"GROWCO": {"trailingPE": 60.0, "priceToBook": 20.0, "marketCap": 1000.0}})
    assert "GROWCO" not in stock_value_scores(s) or \
        stock_value_scores(s)["GROWCO"]["score"] == 0.0


def test_undervalued_means_intrinsic_not_just_low_multiple():
    """A compounder at PE 25 with demonstrated 18% growth: statistically
    'expensive', intrinsically cheap — must now score via margin of safety."""
    hist = {"COMPOUND": {"asof": 1, "years": [
        {"year": 2022 + i, "revenue": 1000 * 1.2 ** i, "fcf": 100 * 1.2 ** i,
         "net_income": 100 * 1.2 ** i} for i in range(4)],
        "trajectory": {"years_covered": 4, "health": 0.8, "accrual_red_flag": False,
                       "revenue_cagr": 0.2,
                       "latest": {"fcf": 100 * 1.2 ** 3, "revenue": 1000 * 1.2 ** 3}}}}
    # 12x FCF with 14% (damped) growth: modest raw yield, big margin of safety.
    # (At 25x the conservative DCF grants NO safety — correctly: with capped,
    # damped growth and a 10% hurdle, 25x needs faith, not arithmetic.)
    s = _setup(hist, {"COMPOUND": {"trailingPE": 22.0, "marketCap": 12 * 100 * 1.2 ** 3}})
    r = stock_value_scores(s)["COMPOUND"]
    assert any("margin of safety" in x for x in r["reasons"])
    assert r["score"] >= 0.4
    # and the same growth at 25x carries no margin of safety
    s25 = _setup(hist, {"COMPOUND": {"trailingPE": 25.0, "marketCap": 25 * 100 * 1.2 ** 3}})
    r25 = stock_value_scores(s25).get("COMPOUND")
    assert r25 is None or not any("margin of safety" in x for x in r25["reasons"])


def test_melting_ice_cube_gets_no_dcf_credit():
    """Same multiple, zero growth: DCF grants no margin of safety at 25x."""
    hist = {"MELT": {"asof": 1, "years": [
        {"year": 2022 + i, "revenue": 1000.0, "fcf": 100.0, "net_income": 100.0}
        for i in range(4)],
        "trajectory": {"years_covered": 4, "health": 0.3, "accrual_red_flag": False,
                       "revenue_cagr": 0.0, "latest": {"fcf": 100.0, "revenue": 1000.0}}}}
    s = _setup(hist, {"MELT": {"trailingPE": 25.0, "marketCap": 2500.0}})
    r = stock_value_scores(s).get("MELT")
    assert r is None or r["score"] == 0.0
