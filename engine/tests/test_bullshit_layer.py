"""Tests for the bullshit/emotion layer: per-node emotion field, campaign
detector + pump lifecycle, learned source trust + doom discount, emotion
calibration, chorus-aware credibility, and the contrarian composer."""
import json
import os
import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

tmp = tempfile.mkdtemp()
for var, name in [("BRAIN_GRAPH_PATH", "g.json"), ("BRAIN_REGIME_PATH", "r.json"),
                  ("BRAIN_SCENARIOS_PATH", "s.json"), ("BRAIN_STATE_PATH", "b.json"),
                  ("BRAIN_MACRO_CACHE_PATH", "m.json"), ("BRAIN_FIELD_PATH", "f.json"),
                  ("BRAIN_DB_PATH", "brain.db"), ("BRAIN_FEED_CACHE_PATH", "fc.json"),
                  ("BRAIN_ADVICE_PATH", "adv.json"), ("BRAIN_SENTIMENT_CACHE_PATH", "sc.json"),
                  ("STATE_PATH", "state.json")]:
    os.environ[var] = os.path.join(tmp, name)

from ai_investing.brain.graph import KnowledgeGraph  # noqa: E402
from ai_investing.config import Settings  # noqa: E402

NOW = datetime.now(timezone.utc)


def _fresh_settings():
    s = Settings()
    for f in ("brain.db", "emotion_field.json", "campaigns.json", "contrarian.json",
              "learned_trust.json", "emotion_calibration.json", "integrity_flags.json"):
        p = os.path.join(tmp, f)
        if os.path.exists(p):
            os.remove(p)
    return s


def _seed_prices(s, series_by_symbol, days=20):
    conn = sqlite3.connect(s.brain.db_path)
    conn.execute("CREATE TABLE IF NOT EXISTS price_history ("
                 "date TEXT NOT NULL, symbol TEXT NOT NULL, price REAL NOT NULL,"
                 "PRIMARY KEY (date, symbol))")
    t0 = NOW - timedelta(days=days)
    for sym, prices in series_by_symbol.items():
        for i, px in enumerate(prices):
            d = (t0 + timedelta(days=i)).date().isoformat()
            conn.execute("INSERT OR REPLACE INTO price_history VALUES(?,?,?)", (d, sym, px))
    conn.commit()
    conn.close()


# ------------------------------------------------------------ emotion field --
def test_emotion_field_charges_decays_and_inherits():
    from ai_investing.brain import emotion_field
    s = _fresh_settings()
    g = KnowledgeGraph.seeded()
    events = [
        {"nodes": ["china_tech"], "emotion": "panic", "emotion_intensity": 0.8,
         "credibility": 0.8, "is_noise": False},
        {"nodes": ["ai_datacenter"], "emotion": "euphoria", "emotion_intensity": 0.7,
         "credibility": 0.3, "is_noise": True},     # hype noise charges greed at half
        {"nodes": ["semis"], "emotion": "panic", "emotion_intensity": 0.9,
         "credibility": 0.2, "is_noise": True},     # fear-mongering spam: ignored
    ]
    nodes = emotion_field.update(s, events, NOW)
    assert nodes["china_tech"]["fear"] > 0.5
    assert 0 < nodes["ai_datacenter"]["greed"] < 0.5
    assert "semis" not in nodes                     # noise can't fake capitulation
    # assets inherit from their themes
    emo = emotion_field.asset_emotion(g, nodes, "tencent")
    assert abs(emo["fear"] - 0.7 * nodes["china_tech"]["fear"]) < 1e-3
    # decay: two half-lives later the charge has quartered
    later = emotion_field.node_emotions(s, NOW + timedelta(hours=96))
    assert abs(later["china_tech"]["fear"] - nodes["china_tech"]["fear"] / 4) < 0.02


# ---------------------------------------------------------------- campaigns --
def test_campaign_pressure_flags_coordinated_low_trust_chorus():
    from ai_investing.brain.campaign import pressure_index
    burst_ts = [(NOW - timedelta(hours=h)).isoformat() for h in (1, 2, 2.5, 3, 4, 5)]
    pump = [{"ts": t, "source": src, "nodes": ["nvda"], "is_noise": True, "magnitude": 0.5}
            for t, src in zip(burst_ts, ["cryptoblog", "moonpost", "gainzfeed",
                                         "pumpwire", "hypecast", "cryptoblog"])]
    organic = [{"ts": (NOW - timedelta(hours=30)).isoformat(), "source": "reuters",
                "nodes": ["fed_rate"], "is_noise": False, "magnitude": 0.5}]
    report = pressure_index(pump + organic, NOW)
    assert report["nvda"]["pressure"] >= 0.5
    assert report["nvda"]["coordination"] == 1.0    # >=3 distinct low-trust in 3h
    assert report["nvda"]["chorus"] > 0.5
    assert "fed_rate" not in report                 # one wire story is not a campaign


def test_pump_lifecycle_phases():
    from ai_investing.brain.campaign import _phase
    flat = [100.0] * 8
    pumping = flat + [104, 109, 115, 122, 128]      # running with the campaign
    cracked = flat + [104, 112, 124, 118, 111]      # ran hard, now below peak
    assert _phase(flat, 0.02) == "building"
    assert _phase(pumping, 0.02) == "hype_burst"
    assert _phase(cracked, 0.02) == "dump"


# --------------------------------------------- learned source trust + doom --
def test_source_learning_scores_events_and_learns_trust():
    from ai_investing.brain import source_learning
    from ai_investing.brain.events import source_trust
    from ai_investing.brain.store import BrainStore
    s = _fresh_settings()
    g = KnowledgeGraph.seeded()
    store = BrainStore(s.brain.db_path)
    old = (NOW - timedelta(days=10)).isoformat()
    # goodwire keeps being right (oil up, energy names then rise);
    # clickbait keeps being wrong (gold up, gold names then fall)
    events = []
    for i in range(12):
        events.append({"ts": old, "summary": f"oil {i}", "source": "goodwire.com",
                       "type": "commodity", "nodes": ["oil_price"], "polarity": 1.0,
                       "magnitude": 0.6, "credibility": 0.8, "is_noise": False,
                       "emotion": "neutral", "impulse": 0.4})
        events.append({"ts": old, "summary": f"gold {i}", "source": "clickbait.io",
                       "type": "commodity", "nodes": ["gold_price"], "polarity": 1.0,
                       "magnitude": 0.6, "credibility": 0.8, "is_noise": False,
                       "emotion": "neutral", "impulse": 0.4})
    store.save_events(events)
    store.close()
    up = [50.0 * (1.02 ** i) for i in range(20)]
    dn = [50.0 * (0.98 ** i) for i in range(20)]
    _seed_prices(s, {"SHEL": up, "USO": up, "XLE": up, "GLD": dn, "GDX": dn,
                     "2899.HK": dn})
    added = source_learning.score_events(s, g)
    assert added > 0
    learned = source_learning.learn(s)
    assert learned["goodwire.com"]["hit_rate"] == 1.0
    assert learned["clickbait.io"]["hit_rate"] == 0.0
    assert learned["goodwire.com"]["trust"] > learned["clickbait.io"]["trust"]
    # blending: the right feed now outranks its static default, the wolf-crier sinks
    assert source_trust("goodwire.com", s) > 0.5 > source_trust("clickbait.io", s)
    # scoring is idempotent — already-scored events don't come back
    assert source_learning.score_events(s, g) == 0


def test_doom_discount_for_fear_mongers():
    from ai_investing.brain import source_learning
    s = _fresh_settings()
    conn = sqlite3.connect(s.brain.db_path)
    conn.executescript(source_learning._SCHEMA)
    rows = []
    for i in range(8):     # doombot's doom never moves anything
        rows.append((100 + i, "SPY", -1, 0.001, None, "fear", "doombot.com", -0.8, 0, "t"))
    for i in range(8):     # the market DOES move on real news elsewhere
        rows.append((200 + i, "SPY", 1, 0.03, 1, "neutral", "reuters", 0.5, 0, "t"))
    conn.executemany(
        # columns named explicitly: event_outcomes grew benchmark columns
        # (source_learning._migrate) and a positional insert breaks on any
        # schema addition, in whichever test happens to run after a migration
        "INSERT INTO event_outcomes(event_id,symbol,impact_sign,realized_ret,hit,"
        " emotion,source,polarity,is_noise,scored_at) VALUES(?,?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()
    learned = source_learning.learn(s)
    assert learned["doombot.com"]["doom_discount"] == 0.5   # floor: pure noise doom
    assert "doom_discount" not in learned["reuters"]


# -------------------------------------------------------- emotion calibration --
def test_emotion_calibration_measures_overshoot():
    from ai_investing.brain import emotion_calibration, source_learning
    s = _fresh_settings()
    conn = sqlite3.connect(s.brain.db_path)
    conn.executescript(source_learning._SCHEMA)
    rows = []
    for i in range(25):    # after panic, prices rebound (+2%): overshoot is real
        rows.append((i, "AAA", -1, 0.02 + 0.001 * (i % 3), 0, "panic", "x", -0.5, 0, "t"))
    for i in range(25):    # after euphoria, prices bleed (-1.5%): chasing costs
        rows.append((100 + i, "BBB", 1, -0.015 - 0.001 * (i % 3), 0, "euphoria", "x", 0.5, 0, "t"))
    conn.executemany(
        # columns named explicitly: event_outcomes grew benchmark columns
        # (source_learning._migrate) and a positional insert breaks on any
        # schema addition, in whichever test happens to run after a migration
        "INSERT INTO event_outcomes(event_id,symbol,impact_sign,realized_ret,hit,"
        " emotion,source,polarity,is_noise,scored_at) VALUES(?,?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()
    rep = emotion_calibration.calibrate(s)
    assert rep["panic_rebound"]["basis"] == "measured" and rep["panic_rebound"]["coef"] > 0.5
    assert rep["euphoria_fade"]["basis"] == "measured" and rep["euphoria_fade"]["coef"] < -0.5
    # and without data, honest priors
    s2 = _fresh_settings()
    coefs = emotion_calibration.coefficients(s2)
    assert coefs == {"panic_rebound": 0.30, "euphoria_fade": -0.30}


# ------------------------------------------------- chorus-aware credibility --
def test_low_trust_chorus_is_not_corroboration():
    from ai_investing.brain.events import corroboration, credibility
    pump_title = "Secret token partnership will send this coin parabolic"
    chorus = [{"title": pump_title + f" v{i}", "source": f"moonblog{i}.io"}
              for i in range(4)]
    chorus_heads = [{"title": pump_title, "source": "cryptoblog"}] + chorus
    ev = {"headline": pump_title, "source": "cryptoblog", "type": "market_flow",
          "manipulation_likelihood": 0.2}
    # trusted-only corroboration sees nothing; unrestricted sees the echo chamber
    assert corroboration(pump_title, "cryptoblog", chorus_heads) == 0
    assert corroboration(pump_title, "cryptoblog", chorus_heads, min_trust=0.0) >= 3
    c_chorus = credibility(ev, chorus_heads)
    # the same story corroborated by ONE trusted wire scores higher than a
    # four-blog echo chamber — coordination is not confirmation
    confirmed = chorus_heads[:1] + [{"title": pump_title + " say filings",
                                     "source": "reuters.com"}]
    c_confirmed = credibility(ev, confirmed)
    assert c_confirmed > c_chorus


# ------------------------------------------------------ contrarian composer --
def test_contrarian_buys_panic_in_clean_value_only():
    from ai_investing.brain import contrarian
    s = _fresh_settings()
    g = KnowledgeGraph.seeded()
    _seed_prices(s, {"0700.HK": [100.0] * 16 + [92.0, 88.0, 87.8, 87.9]})  # stabilized
    emotions = {"china_tech": {"fear": 0.8, "greed": 0.0}}
    acts = {"tencent": -0.4}                        # capitulation-deep field
    rep = contrarian.compose(s, g, acts, emotions, {})
    buys = {r["symbol"]: r for r in rep["buys"]}
    assert "0700.HK" in buys and buys["0700.HK"]["score"] > 0
    # same panic on an integrity-flagged name: never a buy
    with open(os.path.join(tmp, "integrity_flags.json"), "w") as fh:
        json.dump({"tencent": {"severity": 0.6, "ts": time.time(), "reasons": []}}, fh)
    rep2 = contrarian.compose(s, g, acts, emotions, {})
    assert "0700.HK" not in {r["symbol"] for r in rep2["buys"]}


def test_contrarian_stabilization_gate_holds_falling_knives():
    from ai_investing.brain import contrarian
    s = _fresh_settings()
    g = KnowledgeGraph.seeded()
    _seed_prices(s, {"0700.HK": [100.0] * 16 + [95.0, 90.0, 84.0, 77.0]})  # cascading
    rep = contrarian.compose(s, g, {"tencent": -0.4},
                             {"china_tech": {"fear": 0.8, "greed": 0.0}}, {})
    assert "0700.HK" not in {r["symbol"] for r in rep["buys"]}
    assert "0700.HK" in {r["symbol"] for r in rep["watching"]}   # watched, not bought


def test_contrarian_fades_euphoric_circular_names_only_after_crack():
    from ai_investing.brain import contrarian
    s = _fresh_settings()
    g = KnowledgeGraph.seeded()
    emotions = {"ai_datacenter": {"fear": 0.0, "greed": 0.8}}
    # CRWV is in the NVDA vendor-financing loop and euphoric -> fade candidate
    rep = contrarian.compose(s, g, {}, emotions, {})
    fades = {r["symbol"]: r for r in rep["fades"]}
    assert "CRWV" in fades and "circular financing" in fades["CRWV"]["why"]
    # but if a campaign phase says the pump is still WORKING, never fade into it
    camp = {"crwv": {"pressure": 0.6, "symbol": "CRWV", "phase": "hype_burst",
                     "fade_ok": False}}
    rep2 = contrarian.compose(s, g, {}, emotions, camp)
    assert "CRWV" not in {r["symbol"] for r in rep2["fades"]}
    # ...until the dump phase opens the window
    camp["crwv"].update({"phase": "dump", "fade_ok": True})
    rep3 = contrarian.compose(s, g, {}, emotions, camp)
    assert "CRWV" in {r["symbol"] for r in rep3["fades"]}


def test_fraud_beneficiary_routing():
    from ai_investing.brain import contrarian
    s = _fresh_settings()
    g = KnowledgeGraph.seeded()
    with open(os.path.join(tmp, "integrity_flags.json"), "w") as fh:
        json.dump({"luckin": {"severity": 0.7, "ts": time.time(), "reasons": []}}, fh)
    rep = contrarian.compose(s, g, {}, {}, {})
    # Luckin's fraud is Starbucks China's market share (competes_with edge)
    assert "SBUX" in rep["beneficiaries"]
    assert rep["beneficiaries"]["SBUX"]["benefit"] > 0
    assert "Luckin" in rep["beneficiaries"]["SBUX"]["why"]


# --------------------------------------------------------- adviser plumbing --
def test_adviser_consumes_contrarian_and_campaign_layers():
    from datetime import datetime as dt
    from ai_investing.brain import Brain
    from ai_investing.brain.adviser import advise
    s = _fresh_settings()
    b = Brain(s)
    b.field.activations = {"nvda": 0.5, "ko": 0.5}
    b.field.updated = dt.now(timezone.utc).isoformat()
    with open(os.path.join(tmp, "contrarian.json"), "w") as fh:
        json.dump({"buys": [{"symbol": "KO", "score": 0.5}], "fades": [],
                   "beneficiaries": {}}, fh)
    with open(os.path.join(tmp, "campaigns.json"), "w") as fh:
        json.dump({"ts": "", "nodes": {"nvda": {"pressure": 0.8, "symbol": "NVDA"}}}, fh)
    a = advise(s, b, log=False)
    # a heavily-haircut name may fall below the conviction floor into the
    # visible watch list — the layers' effect on SCORE is what we assert
    by = {t["symbol"]: t for t in a["trades"] + a.get("watch", [])}
    # same field charge: KO boosted by the contrarian buy, NVDA haircut by pressure
    assert by["KO"]["score"] > by["NVDA"]["score"]
    assert by["KO"]["drivers"].get("contrarian", 0) > 0
    assert by["NVDA"]["drivers"].get("campaign_pressure", 0) == 0.8


# ------------------------------------------------------- chain integrity --
def test_think_chains_all_layers_without_silent_failure():
    """Full cycle: old scoreable events in the store must trigger the whole
    evidence cascade inside think() — outcomes scored, source trust learned,
    emotions calibrated, edges/paths recalibrated and re-applied — with the
    results visible in state and NO swallowed layer error."""
    from ai_investing.brain import Brain
    from ai_investing.brain.store import BrainStore
    s = _fresh_settings()
    store = BrainStore(s.brain.db_path)
    old = (NOW - timedelta(days=10)).isoformat()
    store.save_events([{"ts": old, "summary": f"oil {i}", "source": "goodwire.com",
                        "type": "commodity", "nodes": ["oil_price"], "polarity": 1.0,
                        "magnitude": 0.6, "credibility": 0.8, "is_noise": False,
                        "emotion": "neutral", "impulse": 0.4} for i in range(6)])
    store.close()
    _seed_prices(s, {"SHEL": [50.0 * 1.02 ** i for i in range(20)],
                     "USO": [50.0 * 1.02 ** i for i in range(20)]})
    b = Brain(s)
    state = b.think([], macro={"vix": 22.0})
    assert "layer_error" not in state, state.get("layer_error")
    assert "contrarian" in state                     # composer ran
    # the evidence cascade fired: outcomes -> learned trust -> calibration file
    assert os.path.exists(os.path.join(tmp, "learned_trust.json"))
    assert os.path.exists(os.path.join(tmp, "edge_calibration.json"))
    assert state["calibration"].get("generated")     # re-applied THIS cycle
    conn = sqlite3.connect(s.brain.db_path)
    n = conn.execute("SELECT COUNT(*) FROM event_outcomes").fetchone()[0]
    conn.close()
    assert n > 0


def test_regime_updates_before_propagation():
    """The gates must see TODAY'S dials: a cooling-CPI print this cycle must
    reach propagate() this cycle, not next."""
    from ai_investing.brain import Brain
    s = _fresh_settings()
    b = Brain(s)
    assert b.regime.inflation_trend == 0.0
    calls = []
    orig = b.graph.propagate

    def spy(impulses, max_hops=3, decay=0.6, regime=None):
        calls.append(regime)
        return orig(impulses, max_hops=max_hops, decay=decay, regime=regime)

    b.graph.propagate = spy
    b.think([], macro={"cpi_yoy": -1.0})            # deep-cooling print
    # the FIRST propagate is the cycle's main ripple (later ones are the
    # stress scenarios / outcome scoring, which run regime-free by design)
    main = calls[0]
    assert main["inflation_trend"] < -0.2           # fresh, not last cycle's 0.0
    assert abs(main["inflation_trend"] - b.regime.inflation_trend) < 1e-9


def test_learned_trust_flows_into_corroboration():
    from ai_investing.brain.events import corroboration
    s = _fresh_settings()
    heads = [{"title": "Copper supply deficit widens as smelters cut output",
              "source": "reuters.com"},
             {"title": "Copper deficit widens further, smelters cutting output",
              "source": "metalsdesk.io"}]     # unknown blog, static trust 0.5
    # statically: the unknown blog can't confirm
    assert corroboration(heads[0]["title"], "reuters.com", heads) == 0
    # but once it has EARNED precision, it can
    with open(os.path.join(tmp, "learned_trust.json"), "w") as fh:
        json.dump({"generated": "", "sources":
                   {"metalsdesk.io": {"n": 15, "hit_rate": 0.8, "trust": 0.81}}}, fh)
    assert corroboration(heads[0]["title"], "reuters.com", heads, settings=s) == 1


if __name__ == "__main__":
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")
    print("test_bullshit_layer: all passed")
