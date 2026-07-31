"""Standing stress report: the graph as a risk-committee scenario engine.

`propagate()` was built to ripple news; the same machinery answers the CRO's
weekly question — "what happens to THIS book under THAT shock?" Each
canonical scenario injects calibrated impulses at the origin nodes and reads
the per-asset impact; crossed with current positions it becomes a directional
exposure report. Scenarios are severe-but-plausible (roughly 1-in-10-year
shapes), and the library is data, not code — add a dict, get a scenario.

CLI: python -m ai_investing.brain.stress            # exposures, no positions
     (the engine's cycle attaches book-weighted results to state["stress"])
"""
from __future__ import annotations

SCENARIOS = {
    "rates_shock_up": {
        "label": "Inflation returns: Fed +200bp repricing",
        "impulses": {"us_inflation": 0.7, "fed_rate": 0.7, "us_10y_yield": 0.6},
    },
    "recession": {
        "label": "Global recession: growth and credit crack together",
        "impulses": {"global_growth": -0.7, "us_growth": -0.6, "credit_conditions": -0.6,
                     "us_employment": -0.5},
    },
    "oil_geopolitics": {
        "label": "Middle-East escalation: oil +50%, shipping rerouted",
        "impulses": {"geopolitical_tension": 0.8, "oil_price": 0.7, "shipping_costs": 0.5},
    },
    "taiwan_strait": {
        "label": "Taiwan-strait crisis: the chip supply chain freezes",
        "impulses": {"geopolitical_tension": 0.9, "china_export_controls": 0.7,
                     "us_china_tariffs": 0.6},
    },
    "ai_unwind": {
        "label": "AI capex bust: circular financing exposed, orders cut",
        "impulses": {"ai_capex_cycle": -0.8, "ai_circularity": 0.7},
    },
    "china_hard_landing": {
        "label": "China hard landing: property + consumer + FX stress",
        "impulses": {"china_growth": -0.7, "china_property": -0.7, "china_consumer": -0.5,
                     "currency_peg_stress": 0.4},
    },
    "crypto_winter": {
        "label": "Crypto credit event: custody blowup + liquidity drain",
        "impulses": {"custody_risk": 0.8, "crypto_liquidity": -0.7, "crypto_regulation": 0.5},
    },
    "fraud_wave": {
        "label": "Late-cycle fraud wave: books stop being believed",
        "impulses": {"financial_fraud": 0.7, "financial_engineering": 0.5,
                     "credit_conditions": -0.4},
    },
    "private_credit_bust": {
        "label": "Private-credit bust: marks questioned, funds gated, spreads gap",
        "impulses": {"private_credit": 0.7, "credit_spreads": 0.6,
                     "financial_engineering": 0.4},
    },
    "yuan_break": {
        "label": "Yuan breaks: PBOC tolerates devaluation, EM sells as one",
        "impulses": {"cnh_devaluation": 0.7, "currency_peg_stress": 0.5,
                     "china_growth": -0.4},
    },
    "cre_crunch": {
        "label": "CRE refinancing crunch: office marks land on regional banks",
        "impulses": {"us_cre": 0.7, "credit_conditions": -0.5, "credit_spreads": 0.4},
    },
}


def run_stress(graph, positions_weights: dict[str, float] | None = None,
               top_n: int = 8) -> dict:
    """For each scenario: per-asset impacts, plus (when position weights are
    given, symbol -> signed weight) the book's weighted exposure. Impacts are
    tanh-squashed field units, not P&L — read them as directional beta to the
    scenario, ranked, and sized by the weights."""
    out: dict = {}
    for key, sc in SCENARIOS.items():
        impacts, _, deferred = graph.propagate(sc["impulses"])
        assets = graph.asset_impacts(impacts)
        ranked = sorted(assets.items(), key=lambda kv: kv[1]["impact"])
        row = {"label": sc["label"],
               "worst_assets": [(s, v["impact"]) for s, v in ranked[:top_n]],
               "best_assets": [(s, v["impact"]) for s, v in ranked[-top_n:][::-1]],
               "deferred_hits": len(deferred)}
        if positions_weights:
            expo = sum(w * assets.get(sym.upper(), {}).get("impact", 0.0)
                       for sym, w in positions_weights.items())
            row["book_exposure"] = round(expo, 4)
            row["book_detail"] = {sym: round(w * assets.get(sym.upper(), {}).get("impact", 0.0), 4)
                                  for sym, w in positions_weights.items()
                                  if abs(w * assets.get(sym.upper(), {}).get("impact", 0.0)) > 0.005}
        out[key] = row
    if positions_weights:
        worst = min(out.items(), key=lambda kv: kv[1].get("book_exposure", 0.0))
        out["_summary"] = {"worst_scenario": worst[0],
                           "worst_exposure": worst[1].get("book_exposure")}
    return out


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from ai_investing.brain.graph import KnowledgeGraph
    g = KnowledgeGraph.seeded()
    rep = run_stress(g)
    for key, row in rep.items():
        if key.startswith("_"):
            continue
        print(f"\n=== {row['label']} ===")
        print("  worst:", ", ".join(f"{s} {v:+.2f}" for s, v in row["worst_assets"][:6]))
        print("  best :", ", ".join(f"{s} {v:+.2f}" for s, v in row["best_assets"][:6]))
