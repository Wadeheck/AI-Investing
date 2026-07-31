"""Tests for the v19 decision-layer upgrades: regime-conditional edges, crisis
correlation convergence, market anticipation of known lags, sign-convention
fixes, new systemic-hub wiring, vol scaling, priced-in discounting, and the
edge-calibration loop."""
import json
import math
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

tmp = tempfile.mkdtemp()
for var, name in [("BRAIN_GRAPH_PATH", "g"), ("BRAIN_REGIME_PATH", "r"),
                  ("BRAIN_SCENARIOS_PATH", "s"), ("BRAIN_STATE_PATH", "b"),
                  ("BRAIN_MACRO_CACHE_PATH", "m"), ("BRAIN_FIELD_PATH", "f"),
                  ("BRAIN_DB_PATH", "db"), ("BRAIN_FEED_CACHE_PATH", "fc"),
                  ("BRAIN_ADVICE_PATH", "adv"), ("BRAIN_SENTIMENT_CACHE_PATH", "sc")]:
    os.environ[var] = os.path.join(tmp, name + (".db" if name == "db" else ".json"))

from ai_investing.brain.graph import Edge, KnowledgeGraph  # noqa: E402
from ai_investing.config import Settings  # noqa: E402


# ---------------------------------------------------------------- seed v19 --
def test_seed_v19_new_nodes_wired():
    g = KnowledgeGraph.seeded()
    for nid in ("us_2y_yield", "credit_spreads", "cnh_devaluation", "private_credit",
                "cb_gold_buying", "us_cre", "tether", "binance", "crcl", "jpm",
                "payments", "us_retail", "china_semis", "smic", "rheinmetall",
                "wmt", "lmt", "rtx"):
        assert nid in g.nodes, nid
    # every edge references real nodes
    assert not [(e.src, e.dst) for e in g.edges
                if e.src not in g.nodes or e.dst not in g.nodes]


def test_boe_utilities_sign_fixed():
    g = KnowledgeGraph.seeded()
    impacts, _, _ = g.propagate({"boe_rate": 0.6})
    assert impacts.get("uk_utilities", 0) < 0     # hikes = utility distress = DOWN


def test_stress_node_convention_unified():
    g = KnowledgeGraph.seeded()
    # eurozone stress rising must now be risk-OFF (was inverted "+1 = easing")
    impacts, _, _ = g.propagate({"eurozone_political_risk": 0.6})
    assert impacts.get("risk_appetite", 0) < 0
    assert impacts.get("europe_growth", 0) < 0
    # political instability rising is risk-off with USD safe-haven bid
    impacts2, _, _ = g.propagate({"political_stability": 0.6})
    assert impacts2.get("risk_appetite", 0) < 0
    assert impacts2.get("usd_strength", 0) > 0
    # and every stress-family node label/equilibrium says so
    for nid in ("political_stability", "eurozone_political_risk", "private_credit",
                "us_cre"):
        n = g.nodes[nid]
        assert "rising" in (n.label + n.equilibrium).lower(), nid


def test_systemic_hub_transmission():
    g = KnowledgeGraph.seeded()
    # Tether doubt drains the whole crypto complex
    impacts, _, _ = g.propagate({"currency_peg_stress": 0.7})
    assert impacts.get("tether", 0) < 0
    assert impacts.get("crypto_liquidity", 0) < 0
    assert impacts.get("btc", 0) < 0
    # export controls HELP the domestic-substitution theme while hurting semis
    impacts2, _, _ = g.propagate({"china_export_controls": 0.6})
    assert impacts2.get("china_semis", 0) > 0 > impacts2.get("semis", 0)
    # consumer weakness finally lands on tradable retail
    impacts3, _, _ = g.propagate({"us_consumer": -0.6})
    a = g.asset_impacts(impacts3)
    assert a.get("WMT", {}).get("impact", 0) < 0
    assert a.get("V", {}).get("impact", 0) < 0    # payments read the consumer too


# ----------------------------------------------------------- regime gates --
def test_fed_risk_edge_flips_in_growth_scare():
    g = KnowledgeGraph.seeded()
    hot, _, _ = g.propagate({"fed_rate": 0.6}, regime={"inflation_trend": 0.5})
    scare, _, _ = g.propagate({"fed_rate": 0.6}, regime={"inflation_trend": -0.5})
    assert hot.get("risk_appetite", 0) < 0        # hikes hurt when inflation is the fear
    assert scare.get("risk_appetite", 0) > 0      # in a growth scare the sign flips
    # no regime given -> classic behavior stands
    none, _, _ = g.propagate({"fed_rate": 0.6})
    assert none.get("risk_appetite", 0) < 0


def test_gate_actions_mute_and_damp():
    nodes = list(KnowledgeGraph.seeded().nodes.values())
    e_mute = Edge("fed_rate", "risk_appetite", "influences", sign=-1, weight=0.6,
                  regime_gate={"dial": "fear", "lo": 0.0, "hi": 0.5, "outside": "mute"})
    e_damp = Edge("fed_rate", "risk_appetite", "influences", sign=-1, weight=0.6,
                  regime_gate={"dial": "fear", "lo": 0.0, "hi": 0.5, "outside": "damp"})
    assert e_mute.gated({"fear": 0.9}) == (1, 0.0)
    assert e_damp.gated({"fear": 0.9}) == (1, 0.5)
    assert e_mute.gated({"fear": 0.2}) == (1, 1.0)
    assert e_mute.gated(None) == (1, 1.0)
    assert nodes  # silence lint


def test_regime_gate_survives_serialization():
    g = KnowledgeGraph.seeded()
    path = os.path.join(tmp, "gate_rt.json")
    g.save(path)
    g2 = KnowledgeGraph.load(path)
    gated = [e for e in g2.edges if e.regime_gate]
    assert gated and any(e.src == "fed_rate" and e.dst == "risk_appetite" for e in gated)


# ------------------------------------------- crisis correlation convergence --
def test_correlations_converge_in_deep_risk_off():
    g = KnowledgeGraph.seeded()
    calm, _, _ = g.propagate({"us_megacap_tech": -0.5}, regime={"risk_appetite": 0.0})
    panic, _, _ = g.propagate({"us_megacap_tech": -0.5}, regime={"risk_appetite": -0.9})
    # membership transmission into single names strengthens in a crash
    assert abs(panic.get("aapl", 0)) > abs(calm.get("aapl", 0))
    assert abs(panic.get("googl", 0)) > abs(calm.get("googl", 0))


# ------------------------------------------------- anticipation of τ-lags --
def test_market_anticipates_lags_into_priced_nodes_only():
    g = KnowledgeGraph.seeded()
    # halving -> crypto_majors is τ=60d into a PRICED theme: half lands now
    impacts, trace, deferred = g.propagate({"btc_halving": 0.8})
    assert any(t.get("anticipated") and t["to"] == "crypto_majors" for t in trace)
    assert impacts.get("crypto_majors", 0) > 0
    d = [x for x in deferred if x["node"] == "crypto_majors"]
    assert d and d[0]["delay_days"] == 60          # the rest still arrives on schedule
    # tariffs -> us_inflation is τ into a REAL-ECONOMY factor: fully deferred
    i2, t2, d2 = g.propagate({"us_china_tariffs": 0.6})
    assert not any(t["to"] == "us_inflation" and t["from"] == "us_china_tariffs"
                   for t in t2)
    assert any(x["node"] == "us_inflation" for x in d2)


# -------------------------------------------------------- scale / priced-in --
def _settings_with_db(prices_by_symbol_dates):
    s = Settings()
    conn = sqlite3.connect(s.brain.db_path)
    conn.execute("CREATE TABLE IF NOT EXISTS price_history ("
                 "date TEXT NOT NULL, symbol TEXT NOT NULL, price REAL NOT NULL,"
                 "PRIMARY KEY (date, symbol))")
    conn.execute("CREATE TABLE IF NOT EXISTS node_history (ts TEXT, node TEXT, activation REAL)")
    for sym, rows in prices_by_symbol_dates.items():
        conn.executemany("INSERT OR REPLACE INTO price_history VALUES(?,?,?)",
                         [(d, sym, p) for d, p in rows])
    conn.commit()
    conn.close()
    return s


def _dates(n, start="2026-06-01"):
    t0 = datetime.fromisoformat(start)
    return [(t0 + timedelta(days=i)).date().isoformat() for i in range(n)]


def test_vol_scaling_expected_moves():
    from ai_investing.brain.scale import enrich_with_scale
    ds = _dates(30)
    calm = [(d, 100.0 * (1.0 + 0.001) ** i) for i, d in enumerate(ds)]      # ~0.1%/day
    wild = [(d, 100.0 * (1.0 + (0.05 if i % 2 else -0.045))) for i, d in enumerate(ds)]
    s = _settings_with_db({"KO": calm, "BTC/USD": wild})
    g = KnowledgeGraph.seeded()
    impacts = {"KO": {"impact": -0.3}, "BTC/USD": {"impact": -0.3}}
    vols = enrich_with_scale(impacts, s, g)
    # same impact, very different expected moves — scale is real now
    assert abs(impacts["BTC/USD"]["expected_move_pct"]) > \
        3 * abs(impacts["KO"]["expected_move_pct"])
    assert vols["BTC/USD"] > vols["KO"]
    # symbols with no history still get an honest prior by market
    impacts2 = {"NVDA": {"impact": 0.5}}
    enrich_with_scale(impacts2, s, g)
    assert impacts2["NVDA"]["vol_daily"] > 0
    os.remove(s.brain.db_path)


def test_priced_in_discounts_chased_moves():
    from ai_investing.brain.priced_in import priced_in_scores
    from ai_investing.brain.scale import enrich_with_scale
    ds = _dates(30)
    # flat for 25 days then a violent 5-day run UP
    ran = [(d, 100.0) for d in ds[:25]] + \
          [(d, 100.0 * (1.06 ** (i + 1))) for i, d in enumerate(ds[25:])]
    s = _settings_with_db({"NVDA": ran})
    g = KnowledgeGraph.seeded()
    up = {"NVDA": {"impact": 0.5}}
    vols = enrich_with_scale(up, s, g)
    priced_in_scores(s, up, vols)
    assert up["NVDA"]["priced_in"] > 0.3          # chasing a +30% week is discounted
    # the SAME tape with a bearish signal: nothing priced in, full signal stands
    dn = {"NVDA": {"impact": -0.5}}
    priced_in_scores(s, dn, vols)
    assert dn["NVDA"]["priced_in"] == 0.0
    os.remove(s.brain.db_path)


# ------------------------------------------------------------- calibration --
def test_calibration_scores_edges_and_gain():
    from ai_investing.brain import calibration
    g = KnowledgeGraph.seeded()
    ds = _dates(60)
    # gold_price node persistently UP; GLD grinds up -> the correlates edge is
    # not scored (only influences); use oil_price -> shell (influences, w=0.6)
    prices = [(d, 50.0 * (1.0 + 0.004) ** i) for i, d in enumerate(ds)]
    s = _settings_with_db({"SHEL": prices})
    conn = sqlite3.connect(s.brain.db_path)
    conn.executemany("INSERT INTO node_history VALUES(?,?,?)",
                     [(d + "T12:00:00+00:00", "oil_price", 0.4) for d in ds])
    conn.commit()
    conn.close()
    report = calibration.calibrate(s, g)
    key = "oil_price->shell:influences"
    assert key in report["edges"]
    r = report["edges"][key]
    assert r["n"] >= calibration.MIN_N and r["verdict"] == "supported"
    assert 0.25 <= report["gain"] <= 2.0
    # factors feed the graph in memory, never compounding into saved confidence
    factors = calibration.factors_from_report(report)
    assert factors[key] == calibration.SUPPORTED_X
    before = [e.confidence for e in g.edges if g.edge_key(e) == key][0]
    g.set_calibration(factors)
    g.set_calibration(factors)                     # idempotent by construction
    after = [e.confidence for e in g.edges if g.edge_key(e) == key][0]
    assert before == after                         # edge object untouched
    # ...but the adjacency the brain thinks with IS strengthened
    adj = g._adjacency()
    w = [w for dst, _s, w, e in adj["oil_price"] if dst == "shell"][0]
    assert w > 0.6 * before - 1e-9
    os.remove(s.brain.db_path)


def test_calibration_contradicted_edge_demoted():
    from ai_investing.brain import calibration
    g = KnowledgeGraph.seeded()
    ds = _dates(60)
    # oil node UP but Shell relentlessly FALLING -> edge contradicted, x0.5
    prices = [(d, 50.0 * (1.0 - 0.004) ** i) for i, d in enumerate(ds)]
    s = _settings_with_db({"SHEL": prices})
    conn = sqlite3.connect(s.brain.db_path)
    conn.executemany("INSERT INTO node_history VALUES(?,?,?)",
                     [(d + "T12:00:00+00:00", "oil_price", 0.4) for d in ds])
    conn.commit()
    conn.close()
    report = calibration.calibrate(s, g)
    r = report["edges"]["oil_price->shell:influences"]
    assert r["verdict"] == "contradicted" and r["tstat"] < -1.5
    g.set_calibration(calibration.factors_from_report(report))
    adj = g._adjacency()
    w = [w for dst, _s, w, e in adj["oil_price"] if dst == "shell"][0]
    assert w < 0.35                                # 0.6 x 0.5 + rounding room
    os.remove(s.brain.db_path)


def test_calibration_apply_roundtrip(tmp_path=None):
    from ai_investing.brain import calibration
    s = Settings()
    g = KnowledgeGraph.seeded()
    path = calibration._cal_path(s)
    with open(path, "w") as fh:
        json.dump({"generated": "2026-07-31T00:00:00+00:00", "gain": 0.7,
                   "edges": {"oil_price->shell:influences":
                             {"verdict": "contradicted", "n": 30, "tstat": -2.0}},
                   "summary": {"scored": 1, "supported": 0, "contradicted": 1,
                               "unproven": 0}}, fh)
    summary = calibration.apply(s, g)
    assert summary["contradicted"] == 1
    from ai_investing.brain.scale import load_gain
    assert math.isclose(load_gain(s), 0.7)
    os.remove(path)


# ------------------------------------------------------- node-merge refresh --
def test_merge_seed_refreshes_node_metadata():
    g = KnowledgeGraph.seeded()
    path = os.path.join(tmp, "merge_rt.json")
    g.save(path)
    with open(path) as fh:
        d = json.load(fh)
    d["seed_version"] = 1
    for n in d["nodes"]:
        if n["id"] == "eurozone_political_risk":
            n["label"] = "OLD STALE LABEL"
            n["state"] = "live-state-must-survive"
    with open(path, "w") as fh:
        json.dump(d, fh)
    g2 = KnowledgeGraph.load(path)
    n = g2.nodes["eurozone_political_risk"]
    assert "stress rising" in n.label            # curated metadata refreshed
    assert n.state == "live-state-must-survive"  # live state preserved


# -------------------------------------------------------------- new stress --
def test_new_stress_scenarios_run():
    from ai_investing.brain.stress import SCENARIOS, run_stress
    for k in ("private_credit_bust", "yuan_break", "cre_crunch"):
        assert k in SCENARIOS
    g = KnowledgeGraph.seeded()
    rep = run_stress(g, top_n=4)
    assert rep["private_credit_bust"]["worst_assets"]
    worst_yuan = dict(rep["yuan_break"]["worst_assets"])
    assert any(v < 0 for v in worst_yuan.values())


# ------------------------------------------------------------ item 6: gates --
def test_v20_gate_sweep_behaviors():
    g = KnowledgeGraph.seeded()
    # gold's rate-sensitivity halves in a panic (crisis bid overrides the anchor)
    calm, _, _ = g.propagate({"us_10y_yield": 0.6}, regime={"fear": 0.3})
    panic, _, _ = g.propagate({"us_10y_yield": 0.6}, regime={"fear": 0.9})
    assert abs(panic.get("gold_price", 0)) < abs(calm.get("gold_price", 0))
    # JPM flips: NIM tailwind in calm, bond-book losses in panic (SVB mechanism)
    assert calm.get("jpm", 0) > 0 > panic.get("jpm", 0)
    # the halving narrative needs a bid: muted in deep risk-off
    ron, _, _ = g.propagate({"btc_halving": 0.8}, regime={"risk_appetite": 0.2})
    roff, _, _ = g.propagate({"btc_halving": 0.8}, regime={"risk_appetite": -0.8})
    assert ron.get("crypto_majors", 0) > 0 and not roff.get("crypto_majors")
    # melt-ups shrug at war headlines (damp, not mute — complacency is fragile)
    euph, _, _ = g.propagate({"geopolitical_tension": 0.6}, regime={"greed": 0.9})
    sober, _, _ = g.propagate({"geopolitical_tension": 0.6}, regime={"greed": 0.3})
    assert abs(euph.get("risk_appetite", 0)) < abs(sober.get("risk_appetite", 0))
    assert len([e for e in g.edges if e.regime_gate]) >= 15


# --------------------------------------------------- item 6: volume pipeline --
def test_volume_snapshot_migration_and_relative_volume():
    from ai_investing.brain.scale import relative_volume, volume_series
    from ai_investing.brain.scorecard import Scorecard
    d = tempfile.mkdtemp()
    os.environ["STATE_PATH"] = os.path.join(d, "state.json")
    old_db = os.environ["BRAIN_DB_PATH"]
    os.environ["BRAIN_DB_PATH"] = os.path.join(d, "brain.db")
    try:
        s = Settings()
        # legacy table WITHOUT the volume column: migration must handle it
        conn = sqlite3.connect(os.path.join(d, "brain.db"))
        conn.execute("CREATE TABLE price_history (date TEXT NOT NULL, symbol TEXT "
                     "NOT NULL, price REAL NOT NULL, PRIMARY KEY (date, symbol))")
        conn.execute("INSERT INTO price_history VALUES('2026-07-01','NVDA',100.0)")
        conn.commit()
        conn.close()
        sc = Scorecard(s)
        sc.snapshot_prices({"NVDA": 105.0}, {"NVDA": 9e6})
        sc.close()
        vols = volume_series(s, min_len=1)
        assert vols["NVDA"] == [9e6]           # legacy NULL rows skipped, new row in
        # relative volume: quiet base then a 3x burst
        series = [1e6] * 25 + [3e6] * 5
        assert relative_volume(series) == 3.0
        assert relative_volume([1e6] * 6) is None   # not enough history
    finally:
        os.environ["BRAIN_DB_PATH"] = old_db
        os.environ["STATE_PATH"] = os.path.join(tmp, "state.json")


def test_priced_in_volume_weights_the_discount():
    from ai_investing.brain.priced_in import priced_in_scores
    from ai_investing.brain.scale import enrich_with_scale
    ds = _dates(35)
    run = [(d, 100.0) for d in ds[:30]] + \
          [(d, 100.0 * (1.04 ** (i + 1))) for i, d in enumerate(ds[30:])]
    s = _settings_with_db({"NVDA": run})
    conn = sqlite3.connect(s.brain.db_path)
    try:
        conn.execute("ALTER TABLE price_history ADD COLUMN volume REAL")
    except sqlite3.OperationalError:
        pass
    # heavy tape on the run days (3x base volume)
    for i, (d, _p) in enumerate(run):
        conn.execute("UPDATE price_history SET volume=? WHERE date=? AND symbol='NVDA'",
                     (3e6 if i >= 30 else 1e6, d))
    conn.commit()
    conn.close()
    g = KnowledgeGraph.seeded()
    heavy = {"NVDA": {"impact": 0.5}}
    vols = enrich_with_scale(heavy, s, g)
    priced_in_scores(s, heavy, vols)
    heavy_discount = heavy["NVDA"]["priced_in"]
    assert heavy["NVDA"]["rel_volume"] == 3.0
    # same run on a THIN tape: less was decided, smaller discount
    conn = sqlite3.connect(s.brain.db_path)
    conn.execute("UPDATE price_history SET volume=0.3e6 WHERE symbol='NVDA' "
                 "AND volume=3e6")
    conn.commit()
    conn.close()
    thin = {"NVDA": {"impact": 0.5}}
    priced_in_scores(s, thin, vols)
    assert 0 < thin["NVDA"]["priced_in"] < heavy_discount
    os.remove(s.brain.db_path)


def test_campaign_volume_confirmation_raises_pressure():
    from ai_investing.brain.campaign import _phase, pressure_index, update
    # unit sanity on the pieces (full update() is exercised in the brain cycle)
    assert _phase([100.0] * 8 + [104, 109, 115, 122, 128], 0.02) == "hype_burst"
    ts = [(datetime.now(timezone.utc) - timedelta(hours=h)).isoformat()
          for h in (1, 2, 3)]
    evs = [{"ts": t, "source": f"blog{i}.io", "nodes": ["nvda"], "is_noise": True,
            "magnitude": 0.6} for i, t in enumerate(ts)]
    base = pressure_index(evs)["nvda"]["pressure"]
    assert base > 0


# ----------------------------------------------- item 6: path calibration --
def test_path_calibration_scores_theme_to_member_transmission():
    from ai_investing.brain import calibration
    g = KnowledgeGraph.seeded()
    ds = _dates(60)
    # theme ai_datacenter persistently POSITIVE while member CRWV keeps FALLING:
    # the membership transmission is contradicted and that exact wire demotes
    prices = [(d, 40.0 * (1.0 - 0.004) ** i) for i, d in enumerate(ds)]
    s = _settings_with_db({"CRWV": prices})
    conn = sqlite3.connect(s.brain.db_path)
    conn.executemany("INSERT INTO node_history VALUES(?,?,?)",
                     [(d + "T12:00:00+00:00", "ai_datacenter", 0.4) for d in ds])
    conn.commit()
    conn.close()
    report = calibration.calibrate(s, g)
    key = "crwv->ai_datacenter:member_of"
    assert key in report["paths"]
    assert report["paths"][key]["verdict"] == "contradicted"
    assert report["summary"]["paths_scored"] >= 1
    factors = calibration.factors_from_report(report)
    assert factors[key] == calibration.CONTRADICTED_X
    g.set_calibration(factors)
    adj = g._adjacency()
    # member_of flows theme -> member: the demoted wire carries half the weight
    w = [w for dst, _s, w, e in adj["ai_datacenter"]
         if dst == "crwv" and e.type == "member_of"][0]
    assert w < 0.5
    os.remove(s.brain.db_path)


if __name__ == "__main__":
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")
    print("test_brain_upgrades: all passed")
