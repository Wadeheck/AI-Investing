"""Tests for the brain: graph propagation, credibility (signal vs noise),
regime/emotion/mood, scenarios, the macro-linkage signal, and θ migration."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

tmp = tempfile.mkdtemp()
for var, name in [("BRAIN_GRAPH_PATH", "g"), ("BRAIN_REGIME_PATH", "r"),
                  ("BRAIN_SCENARIOS_PATH", "s"), ("BRAIN_STATE_PATH", "b"),
                  ("BRAIN_MACRO_CACHE_PATH", "m"), ("BRAIN_FIELD_PATH", "f")]:
    os.environ[var] = os.path.join(tmp, name + ".json")

from ai_investing.brain.events import corroboration, credibility, source_trust  # noqa: E402
from ai_investing.brain.graph import KnowledgeGraph  # noqa: E402
from ai_investing.brain.regime import MacroRegime  # noqa: E402
from ai_investing.brain.scenarios import ScenarioRegistry, SEED_SCENARIOS  # noqa: E402
from ai_investing.config import Settings  # noqa: E402
from ai_investing.models import Asset, AssetClass  # noqa: E402
from ai_investing.signals import MacroLinkageSignal  # noqa: E402


def test_graph_seeds_and_propagates_to_unnamed_assets():
    g = KnowledgeGraph.seeded()
    assert len(g.nodes) > 50 and len(g.edges) > 70
    # A chip-export-controls shock must reach NVDA though no headline named it.
    impacts, trace, _d = g.propagate({"china_export_controls": 0.5})
    assert impacts.get("semis", 0) < 0          # controls up -> semis down
    assert impacts.get("nvda", 0) < 0           # ...and down into the member asset
    assert any(t["to"] == "nvda" for t in trace)


def test_propagation_signs_multi_hop():
    g = KnowledgeGraph.seeded()
    # Fed HIKES (+): USD up, gold pressured via USD (multi-hop, sign flip).
    impacts, _, _d = g.propagate({"fed_rate": 0.6})
    assert impacts["usd_strength"] > 0
    assert impacts.get("gold_price", 0) < 0
    assert impacts.get("sg_reits", 0) < 0       # via 10Y yield


def test_multi_market_assets_reachable():
    g = KnowledgeGraph.seeded()
    impacts, _, _d = g.propagate({"china_anti_corruption": 0.6})
    a = g.asset_impacts(impacts)
    assert a.get("600519.SS", {}).get("impact", 0) < 0   # Moutai hit by crackdown
    impacts2, _, _d2 = g.propagate({"mas_policy": 0.6})
    a2 = g.asset_impacts(impacts2)
    assert a2.get("D05.SI", {}).get("impact", 0) > 0     # DBS NIM tailwind
    assert a2.get("C38U.SI", {}).get("impact", 0) < 0    # REIT headwind


def test_credibility_noise_vs_signal():
    heads = [
        {"title": "Fed raises rates by 25 basis points as inflation stays hot", "source": "reuters.com"},
        {"title": "Federal Reserve hikes rates 25bps citing inflation", "source": "bbc.co.uk"},
        {"title": "This coin will 100x — insiders say get in now before it explodes", "source": "cryptoblog"},
    ]
    real = {"headline": heads[0]["title"], "source": "reuters.com",
            "type": "monetary_policy", "manipulation_likelihood": 0.05}
    pump = {"headline": heads[2]["title"], "source": "cryptoblog",
            "type": "rumor_hype", "manipulation_likelihood": 0.9}
    c_real, c_pump = credibility(real, heads), credibility(pump, heads)
    assert c_real > 0.6 and c_pump < 0.2 and c_real > c_pump
    assert corroboration(heads[0]["title"], "reuters.com", heads) >= 1
    assert source_trust("reuters.com") > source_trust("randomblog.io") > source_trust("reddit.com")


def test_regime_emotion_and_mood():
    r = MacroRegime()
    events = [{"impulse": 0.4, "nodes": ["geopolitical_tension"], "type": "geopolitics",
               "is_noise": False, "emotion": "fear", "emotion_intensity": 0.8}]
    for _ in range(6):
        r.update({"vix": 34.0, "tnx_chg_20d": -0.05, "dxy_chg_20d": -0.02, "cpi_yoy": 2.1},
                 events, performance={"drawdown": 0.10})
    d = r.to_dict()
    assert d["labels"]["risk_appetite"] == "risk_off"
    assert d["labels"]["rate_trajectory"] == "easing"
    assert r.fear > 0.5 and r.emotion_label in ("fear", "panic")
    assert r.mood_caution > 0.45 and r.mood_label in ("wary", "defensive")
    assert r.conviction_multiplier() < 0.85
    # persistence roundtrip
    p = os.path.join(tmp, "regime_rt.json")
    r.save(p)
    assert abs(MacroRegime.load(p).fear - r.fear) < 1e-6


def test_scenarios_fire_on_direction():
    reg = ScenarioRegistry([dict(s) for s in SEED_SCENARIOS])
    cut = [{"impulse": -0.3, "nodes": ["pboc_rate"], "is_noise": False, "summary": "PBOC cuts LPR"}]
    fired = reg.match(cut)
    assert any(f["id"] == "pboc-cut-icbc-nim" for f in fired)
    hike = [{"impulse": 0.3, "nodes": ["pboc_rate"], "is_noise": False, "summary": "PBOC hikes"}]
    assert not reg.match(hike)                       # wrong direction: no fire
    noise = [{"impulse": -0.3, "nodes": ["pboc_rate"], "is_noise": True, "summary": "rumor"}]
    assert not reg.match(noise)                      # noise never fires scenarios


def test_macro_linkage_signal_and_symbol_bridging():
    ctx = {"brain": {"conviction_multiplier": 0.8, "regime": {"mood_label": "wary"},
                     "asset_impacts": {"1398.HK": {"impact": -0.4, "node": "icbc"},
                                       "NVDA": {"impact": 0.3, "node": "nvda"}}}}
    sig = MacroLinkageSignal()
    r = sig.evaluate(Asset("NVDA", AssetClass.STOCK), [], ctx)
    assert r.direction.value == "long" and r.score > 0
    # Longbridge-style symbol resolves to the canonical HK node
    r2 = sig.evaluate(Asset("1398.HK", AssetClass.STOCK), [], ctx)
    assert r2.direction.value == "short"
    r3 = sig.evaluate(Asset("AAPL", AssetClass.STOCK), [], ctx)
    assert r3.confidence == 0.0


def test_brain_simulate_offline_and_theta_migration():
    s = Settings()
    from ai_investing.brain import Brain
    out = Brain(s).simulate("US announces sweeping new tariffs on Chinese EV imports")
    assert out["simulated"] and out["impulses"]
    assert any(k in out["impacts"] for k in ("ev_supply_chain", "us_china_tariffs"))
    # θ migration: an old 7-feature model gains macro_linkage without breaking
    import json
    from ai_investing.learning.store import ParamStore
    from ai_investing.learning.formula import FormulaModel
    old = FormulaModel(feature_names=["bias", "momentum", "mean_reversion", "sentiment",
                                      "political_hype", "consensus", "mom_lowvol"],
                       weights=[0.0, 0.02, 0.015, 0.02, 0.03, 0.01, 0.008], fitted=True)
    p = os.path.join(tmp, "formula.json")
    with open(p, "w") as fh:
        json.dump({"model": old.to_dict(), "rls": None}, fh)
    model, rls = ParamStore(p).load()
    assert "macro_linkage" in model.feature_names
    assert len(model.weights) == len(model.feature_names)
    assert model.fitted   # migration keeps the learned formula


def test_delayed_edges_defer_not_land():
    g = KnowledgeGraph.seeded()
    # tariffs -> us_inflation is a τ=45d edge: must NOT land same-cycle
    impacts, trace, deferred = g.propagate({"us_china_tariffs": 0.6})
    assert not any(t["to"] == "us_inflation" and t["from"] == "us_china_tariffs" for t in trace)
    assert any(d["node"] == "us_inflation" and d["delay_days"] == 45 for d in deferred)


def test_field_state_decay_maturation_and_dedup():
    from datetime import datetime, timedelta, timezone
    from ai_investing.brain.field import FieldState
    now = datetime.now(timezone.utc)
    f = FieldState({"semis": -0.4}, updated=(now - timedelta(hours=36)).isoformat())
    f.decay(now)
    assert abs(f.activations["semis"] + 0.2) < 0.02      # one half-life gone
    f.defer([{"node": "us_inflation", "contribution": 0.1, "delay_days": 30, "via": "oil_price"}], now)
    f.defer([{"node": "us_inflation", "contribution": 0.12, "delay_days": 30, "via": "oil_price"}], now)
    assert len(f.pending) == 1                            # same story refreshed, not stacked
    assert not f.mature_pending(now)                      # not due yet
    due = f.mature_pending(now + timedelta(days=31))
    assert abs(due["us_inflation"] - 0.12) < 1e-9 and not f.pending
    # roundtrip
    p = os.path.join(tmp, "field_rt.json")
    f.absorb({"gold_price": 0.3})
    f.save(p)
    assert FieldState.load(p).activations.get("gold_price") == 0.3


def test_centrality_ranks_systemic_nodes():
    g = KnowledgeGraph.seeded()
    c = g.centrality()
    assert max(c.values()) == 1.0
    # macro hubs must outrank a leaf asset
    assert c["us_inflation"] > c["cict"] and c["risk_appetite"] > c["moutai"]


def test_fragility_feeds_caution():
    r = MacroRegime()
    for _ in range(6):
        r.update({"vix": 16.0}, [], performance={"drawdown": 0.0, "fragility": 0.9})
    assert r.fragility == 0.9 and r.mood_caution > 0.3


def test_seed_merge_preserves_llm_edges():
    import json
    g = KnowledgeGraph.seeded()
    g.propose_edge("oil_price", "sg_banks", "influences", 1, 0.3, 0.4, "test event", "2026-01-01")
    p = os.path.join(tmp, "merge.json")
    g.save(p)
    with open(p) as fh:
        d = json.load(fh)
    d["seed_version"] = 1                                 # pretend it's an old file
    d["nodes"] = [n for n in d["nodes"] if n["id"] != "tlt"]  # and missing a new node
    with open(p, "w") as fh:
        json.dump(d, fh)
    g2 = KnowledgeGraph.load(p)
    assert "tlt" in g2.nodes                              # new seed node merged in
    assert any(e.provenance == "llm" and e.dst == "sg_banks" for e in g2.edges)  # llm kept


if __name__ == "__main__":
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")
    print("test_brain: all passed")
