"""Trajectory scoring: synthetic multi-year records, no network."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ai_investing.data.fundamentals_history import trajectory


def _yr(year, rev, fcf, debt, equity=1000.0):
    return {"year": year, "revenue": rev, "net_income": fcf * 0.8, "fcf": fcf,
            "total_debt": debt, "cash": 100.0, "total_assets": 2000.0,
            "equity": equity, "debt_to_equity": debt / equity if equity > 0 else None}


def test_compounder_scores_high():
    """Growing revenue, growing always-positive FCF, deleveraging."""
    ys = [_yr(2022, 1000, 100, 500), _yr(2023, 1200, 140, 450),
          _yr(2024, 1450, 190, 400), _yr(2025, 1750, 260, 350)]
    t = trajectory(ys)
    assert t["health"] >= 0.7
    assert t["fcf_positive_years"] == 4 and t["fcf_growing"] and t["deleveraging"]
    assert t["revenue_cagr"] > 0.15
    assert t["latest"]["year"] == 2025


def test_death_spiral_scores_negative():
    """Shrinking revenue, cash burn, debt piling up, equity wiped out."""
    ys = [_yr(2022, 1000, 50, 400), _yr(2023, 900, -20, 600),
          _yr(2024, 750, -80, 900), _yr(2025, 600, -150, 1300, equity=-200.0)]
    t = trajectory(ys)
    assert t["health"] <= -0.7
    assert t["revenue_cagr"] < 0


def test_insufficient_history_is_neutral():
    assert trajectory([_yr(2025, 1000, 100, 300)])["health"] == 0.0
    assert trajectory([])["health"] == 0.0


def test_flat_boring_business_is_mildly_positive():
    """No growth but reliable FCF and low debt — resilient, not exciting."""
    ys = [_yr(2023, 1000, 120, 200), _yr(2024, 1010, 118, 200), _yr(2025, 1020, 121, 190)]
    t = trajectory(ys)
    assert 0.2 <= t["health"] <= 0.7


def test_dividend_compounder():
    from ai_investing.data.fundamentals_history import dividend_trajectory
    dps = {str(2010 + i): 1.0 * 1.07 ** i for i in range(15)}       # 15y, +7%/yr
    years = [{"year": 2023 + i, "fcf": 500.0, "net_income": 400.0,
              "dividends_paid": 200.0, "payout_fcf": 0.4} for i in range(3)]
    d = dividend_trajectory(dps, years)
    assert d["pays"] and d["verdict"] == "compounder"
    assert d["streak_years"] >= 14 and not d["at_risk"] and not d["cuts"]
    assert d["dps_cagr_3y"] > 0.05


def test_dividend_cut_detected():
    from ai_investing.data.fundamentals_history import dividend_trajectory
    dps = {"2019": 2.0, "2020": 2.1, "2021": 2.2, "2022": 2.3, "2023": 1.0, "2024": 1.0}
    d = dividend_trajectory(dps, [])
    assert d["cut_recently"] and d["verdict"] == "recently_cut"
    assert any(y == "2023" for y, _ in d["cuts"])


def test_dividend_at_risk_uncovered():
    from ai_investing.data.fundamentals_history import dividend_trajectory
    dps = {str(2015 + i): 3.0 for i in range(10)}
    years = [{"year": 2023, "fcf": 100.0, "dividends_paid": 95.0, "payout_fcf": 0.95},
             {"year": 2024, "fcf": 100.0, "dividends_paid": 96.0, "payout_fcf": 0.96}]
    d = dividend_trajectory(dps, years)
    assert d["at_risk"] and "no room left" in d["risk_reasons"][0]


def test_dividend_held_while_fcf_collapses():
    from ai_investing.data.fundamentals_history import dividend_trajectory
    dps = {str(2015 + i): 3.0 for i in range(10)}
    years = [{"year": 2022, "fcf": 300.0, "dividends_paid": 100.0, "payout_fcf": 0.33},
             {"year": 2023, "fcf": 180.0, "dividends_paid": 100.0, "payout_fcf": 0.56},
             {"year": 2024, "fcf": 90.0, "dividends_paid": 100.0, "payout_fcf": 1.11}]
    d = dividend_trajectory(dps, years)
    assert d["at_risk"]
    assert any("paying from the past" in r or "no room left" in r for r in d["risk_reasons"])


def test_non_payer_is_neutral():
    from ai_investing.data.fundamentals_history import (dividend_trajectory,
                                                        health_with_dividends)
    d = dividend_trajectory({}, [])
    assert d == {"pays": False}
    assert health_with_dividends({"health": 0.5}, d) == 0.5
