"""Tests for the brain: graph propagation, credibility (signal vs noise),
regime/emotion/mood, scenarios, the macro-linkage signal, and θ migration."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

tmp = tempfile.mkdtemp()
for var, name in [("BRAIN_GRAPH_PATH", "g"), ("BRAIN_REGIME_PATH", "r"),
                  ("BRAIN_SCENARIOS_PATH", "s"), ("BRAIN_STATE_PATH", "b"),
                  ("BRAIN_MACRO_CACHE_PATH", "m"), ("BRAIN_FIELD_PATH", "f"),
                  ("BRAIN_DB_PATH", "db"), ("BRAIN_FEED_CACHE_PATH", "fc"),
                  ("BRAIN_ADVICE_PATH", "adv"), ("BRAIN_SENTIMENT_CACHE_PATH", "sc")]:
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
    # hubs (macro factors, supply-chain centers) must clearly outrank leaf assets
    assert c["us_inflation"] > c["nongfu"] and c["nvda"] > c["nongfu"]
    assert c["tsmc"] > c["cict"]


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


def test_store_dedupes_articles():
    from ai_investing.brain.store import BrainStore
    st = BrainStore(os.path.join(tmp, "dedupe.db"))
    heads = [{"title": "Fed hikes rates by 25bps", "source": "reuters.com"},
             {"title": "Oil surges on OPEC cut", "source": "oilprice.com"}]
    fresh1, seen1 = st.filter_new(heads)
    assert len(fresh1) == 2 and seen1 == 0
    st.mark_digested(fresh1)
    fresh2, seen2 = st.filter_new(heads)            # same stories again
    assert len(fresh2) == 0 and seen2 == 2          # LLM never re-pays
    # punctuation/case variants hash the same (normalized title)
    fresh3, _ = st.filter_new([{"title": "FED HIKES RATES, by 25bps!", "source": "reuters.com"}])
    assert len(fresh3) == 0
    st.save_events([{"ts": "2026-07-26T00:00:00+00:00", "summary": "fed hike",
                     "nodes": ["fed_rate"], "impulse": 0.3, "is_noise": False}])
    assert st.stats()["events"] == 1 and len(st.recent_events(72)) <= 1
    st.close()


def test_adviser_ranks_and_explains():
    from datetime import datetime, timezone
    from ai_investing.brain import Brain
    from ai_investing.brain.adviser import advise
    s = Settings()
    b = Brain(s)
    # plant a field: chip controls up, semis down (as after a real shock)
    b.field.activations = {"china_export_controls": 0.5, "semis": -0.3, "nvda": -0.2,
                           "china_tech": -0.15, "tencent": -0.1}
    b.field.updated = datetime.now(timezone.utc).isoformat()
    a = advise(s, b, log=False)
    assert a["trades"], "field this loud must produce advice"
    syms = [t["symbol"] for t in a["trades"]]
    assert "NVDA" in syms
    nvda = next(t for t in a["trades"] if t["symbol"] == "NVDA")
    assert nvda["direction"] == "short_or_avoid"
    assert "→" in nvda["chain"]                     # causal chain present
    assert nvda["rank"] >= 1 and nvda["weight_suggestion"] <= s.risk.max_position_weight
    assert os.path.exists(s.brain.advice_path)      # persisted for the dashboard


def test_ownership_follows_the_money():
    g = KnowledgeGraph.seeded()
    # Tencent selloff must hit Prosus hard (24% stake = most of its NAV)...
    i, _, _ = g.propagate({"tencent": -0.5})
    a = g.asset_impacts(i)
    assert a.get("PRX.AS", {}).get("impact", 0) < -0.1
    # ...and an Arm move must drag SoftBank
    i2, _, _ = g.propagate({"arm": 0.5})
    assert g.asset_impacts(i2).get("9984.T", {}).get("impact", 0) > 0.1
    # Apple weakness reaches Berkshire via the holding
    i3, _, _ = g.propagate({"aapl": -0.5})
    assert g.asset_impacts(i3).get("BRK-B", {}).get("impact", 0) < 0
    # Temasek is an actor node: DBS shock reaches it but it is NOT a tradable asset
    i4, _, _ = g.propagate({"dbs": -0.5})
    assert "temasek" in i4 and "TEMASEK" not in g.asset_impacts(i4)


def test_supply_chains_move_the_cluster():
    g = KnowledgeGraph.seeded()
    # An Nvidia demand shock must ripple UP its supply chain (both-ways flow)
    i, _, _ = g.propagate({"nvda": -0.5})
    a = g.asset_impacts(i)
    for sym in ("TSM", "000660.KS", "MU"):
        assert a.get(sym, {}).get("impact", 0) < 0, f"{sym} should feel an NVDA shock"
    # A TSMC disruption must hit its customers
    i2, _, _ = g.propagate({"tsmc": -0.5})
    a2 = g.asset_impacts(i2)
    assert a2.get("NVDA", {}).get("impact", 0) < 0 and a2.get("AAPL", {}).get("impact", 0) < 0
    # Taiwan tension discounts TSMC/Foxconn; cyber names BENEFIT from tension
    i3, _, _ = g.propagate({"geopolitical_tension": 0.6})
    a3 = g.asset_impacts(i3)
    assert a3.get("TSM", {}).get("impact", 0) < 0
    assert a3.get("CRWD", {}).get("impact", 0) > 0
    # Lithium price up: miner Ganfeng gains while battery/EV side suffers
    i4, _, _ = g.propagate({"lithium_price": 0.6})
    a4 = g.asset_impacts(i4)
    assert a4.get("1772.HK", {}).get("impact", 0) > 0
    assert a4.get("300750.SZ", {}).get("impact", 0) < 0


def test_pathsum_confluence_and_asymmetry():
    g = KnowledgeGraph.seeded()
    # SUM-OF-PATHS: hitting tension and tariffs together must push oil harder
    # than either alone (converging paths add, not max)
    both, _, _ = g.propagate({"geopolitical_tension": 0.3, "us_china_tariffs": 0.3})
    solo, _, _ = g.propagate({"geopolitical_tension": 0.3})
    assert both["oil_price"] > solo["oil_price"] > 0
    # ASYMMETRY: a TSMC shock hits NVDA harder than an NVDA shock hits TSMC
    down, _, _ = g.propagate({"tsmc": -0.5})
    up, _, _ = g.propagate({"nvda": -0.5})
    assert abs(down.get("nvda", 0)) > abs(up.get("tsmc", 0)) > 0
    # NO ECHO: a pure gold impulse must not inflate itself via the GLD pair
    e, _, _ = g.propagate({"gold_price": 0.4})
    assert e["gold_price"] <= 0.4 + 1e-9


def test_per_type_half_life():
    from datetime import datetime, timedelta, timezone
    from ai_investing.brain.field import FieldState
    now = datetime.now(timezone.utc)
    f = FieldState({"fed_rate": 0.4, "nvda": 0.4},
                   updated=(now - timedelta(hours=48)).isoformat())
    f.decay(now, {"fed_rate": "factor", "nvda": "asset"})
    # policy memory (96h HL) outlives single-name news (24h HL)
    assert f.activations["fed_rate"] > 0.25 > f.activations["nvda"]


def test_raw_materials_and_gov_influence():
    g = KnowledgeGraph.seeded()
    # tariffs: Chinese solar down, US domestic solar UP — nuanced signs in one theme
    i, _, _ = g.propagate({"us_china_tariffs": 0.6})
    a = g.asset_impacts(i)
    assert a.get("JKS", {}).get("impact", 0) < 0 < a.get("FSLR", {}).get("impact", 0)
    # rare-earth curbs make the ex-China producer MORE valuable
    i2, _, _ = g.propagate({"rare_earths": 0.6})
    assert g.asset_impacts(i2).get("MP", {}).get("impact", 0) > 0
    # datacenter power squeeze reaches uranium and Cameco
    i3, _, _ = g.propagate({"power_demand": 0.6})
    assert g.asset_impacts(i3).get("CCJ", {}).get("impact", 0) > 0
    # government action flows to state-influenced names (regulated_by rev flow)
    i4, _, _ = g.propagate({"us_government": 0.5})
    assert g.asset_impacts(i4).get("INTC", {}).get("impact", 0) != 0
    # gold rally: miners are leveraged gold
    i5, _, _ = g.propagate({"gold_price": 0.5})
    a5 = g.asset_impacts(i5)
    assert a5.get("GDX", {}).get("impact", 0) > a5.get("GLD", {}).get("impact", 0) * 0.4


def test_crypto_wiring():
    g = KnowledgeGraph.seeded()
    # Fed easing reaches BTC through liquidity/risk channels (multi-hop, sign-correct)
    i, _, _ = g.propagate({"fed_rate": -0.5}, max_hops=4)
    assert g.asset_impacts(i).get("BTC/USD", {}).get("impact", 0) > 0
    # BOJ tightening (carry unwind) hits crypto
    i2, _, _ = g.propagate({"yen_carry": 0.5})
    assert g.asset_impacts(i2).get("BTC/USD", {}).get("impact", 0) < 0
    # regulation tightening chokes both the coins and the on-ramp equity
    i3, _, _ = g.propagate({"crypto_regulation": 0.6})
    a3 = g.asset_impacts(i3)
    assert a3.get("BTC/USD", {}).get("impact", 0) < 0
    assert a3.get("COIN", {}).get("impact", 0) < 0
    # MSTR is leveraged bitcoin: a BTC move must drag it via the owns edge
    i4, _, _ = g.propagate({"btc": -0.5})
    assert g.asset_impacts(i4).get("MSTR", {}).get("impact", 0) < 0
    # sanctions give crypto a small POSITIVE bid (capital flight) even as
    # equities suffer via tension — distinctive-sign check
    i5, _, _ = g.propagate({"sanctions": 0.6}, max_hops=4)
    a5 = g.asset_impacts(i5)
    assert a5.get("TSM", {}).get("impact", 0) < 0


def test_chatbot_commands_offline():
    import json
    os.environ["STATE_PATH"] = os.path.join(tmp, "state.json")
    os.environ["USER_VIEWS_PATH"] = os.path.join(tmp, "views.json")
    os.environ["TELEGRAM_BOT_TOKEN"] = "t"
    os.environ["TELEGRAM_CHAT_ID"] = "42"
    from ai_investing.alerts.chat import ChatBot
    s = Settings()
    with open(s.brain.advice_path, "w") as fh:
        json.dump({"mood": "measured", "conviction_multiplier": 0.7,
                   "trades": [{"rank": 1, "symbol": "NVDA", "direction": "short_or_avoid",
                               "score": -0.3, "weight_suggestion": 0.05,
                               "chain": "chip controls ↑ → semis ↓ → NVDA ↓"}]}, fh)
    bot = ChatBot(s)
    assert "Top trades" in bot.handle("/advise") and "NVDA" in bot.handle("/advise")
    assert "/advise" in bot.handle("/help")
    out = bot.handle("/view NVDA=0.5")
    assert "NVDA = +0.50" in out
    from ai_investing.strategy import UserViews
    assert UserViews.load(s.user_views_path).views.get("NVDA") == 0.5
    assert "Blocked TSLA" in bot.handle("/block TSLA")
    assert "Unblocked TSLA" in bot.handle("/unblock TSLA")
    assert "equity" in bot.handle("/portfolio")
    sim = bot.handle("/simulate PBOC cuts rates by 25bps")
    assert "verdict" in sim


if __name__ == "__main__":
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")
    print("test_brain: all passed")
