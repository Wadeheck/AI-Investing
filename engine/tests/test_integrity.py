"""Fraud/manipulation detection: hardcoded tier, adaptive (LLM) tier, and the
mechanism-free math detectors — replaying history's episodes as inputs."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import os
import tempfile

from ai_investing import indicators as ind
from ai_investing.brain import integrity
from ai_investing.brain.graph import KnowledgeGraph, Node
from ai_investing.config import Settings


def _settings():
    d = tempfile.mkdtemp()
    os.environ["STATE_PATH"] = os.path.join(d, "state.json")
    return Settings()


def _graph():
    return KnowledgeGraph(
        [Node(id="wirecard", type="asset", label="Wirecard", symbol="WDI.DE", market="EU"),
         Node(id="coin", type="asset", label="Coinbase", symbol="COIN", market="US")], [])


def test_hardcoded_tier_flags_the_wirecard_pattern():
    s, g = _settings(), _graph()
    hits = integrity.scan_headlines(
        [{"title": "Wirecard auditor refuses to sign off accounts", "summary": ""}], g, s)
    assert "wirecard" in hits and hits["wirecard"]["severity"] >= 0.85
    # flag persists, decayed, and shows its reasons
    flags = integrity.current_flags(s)
    assert flags["wirecard"]["severity"] > 0.8
    assert any("auditor" in r for r in flags["wirecard"]["reasons"])


def test_ftx_style_withdrawal_halt_flags_exchange():
    s, g = _settings(), _graph()
    hits = integrity.scan_headlines(
        [{"title": "Coinbase rival halts customer withdrawals amid reserve doubts",
          "summary": "proof of reserves questioned; Coinbase shares fall"}], g, s)
    assert "coin" in hits and hits["coin"]["severity"] >= 0.85


def test_adaptive_tier_catches_a_novel_mechanism():
    """No regex knows this mechanism — the LLM tier judges it freshly."""
    s, g = _settings(), _graph()
    ev = {"is_noise": False, "credibility": 0.8,
          "integrity": [{"company": "Wirecard", "severity": 0.7,
                         "mechanism": "insures its own customers' losses via an "
                                      "affiliate it secretly controls"}]}
    hits = integrity.absorb_llm_integrity([ev], g, s)
    assert "wirecard" in hits
    assert 0.4 <= hits["wirecard"]["severity"] <= 0.7   # discounted by credibility
    assert any("[llm]" in r for r in hits["wirecard"]["reasons"])


def test_noise_and_unknown_entities_never_flag():
    s, g = _settings(), _graph()
    assert integrity.absorb_llm_integrity(
        [{"is_noise": True, "credibility": 0.9,
          "integrity": [{"company": "Wirecard", "severity": 0.9, "mechanism": "x"}]}],
        g, s) == {}
    assert integrity.absorb_llm_integrity(
        [{"is_noise": False, "credibility": 0.9,
          "integrity": [{"company": "NoSuchCo", "severity": 0.9, "mechanism": "x"}]}],
        g, s) == {}


def test_madoff_smoothness_detector():
    """Steady ~1%/month with no down months screams; real vol doesn't."""
    madoff = [0.0005] * 250                             # constant positive daily return
    assert ind.smoothness_anomaly(madoff) >= 0.9
    import random
    random.seed(11)
    honest = [random.gauss(0.0004, 0.012) for _ in range(250)]   # SPY-like
    assert ind.smoothness_anomaly(honest) <= 0.2
    steady_loss = [-0.001] * 250                        # losses aren't a ponzi
    assert ind.smoothness_anomaly(steady_loss) == 0.0


def test_enron_accrual_red_flag():
    """Reported profits marching up while cash never arrives."""
    from ai_investing.data.fundamentals_history import trajectory
    ys = [{"year": 2022 + i, "revenue": 1000 * (1.2 ** i),
           "net_income": 100 * (1.3 ** i),                 # earnings 'growing'
           "fcf": 100 * (1.3 ** i) * 0.1,                  # ...but 10% becomes cash
           "total_debt": 400 + 150 * i, "equity": 800.0}
          for i in range(4)]
    t = trajectory(ys)
    assert t["accrual_red_flag"] and t["cash_conversion"] < 0.2
    honest = [{**y, "fcf": y["net_income"] * 0.9} for y in ys]
    assert not trajectory(honest)["accrual_red_flag"]
