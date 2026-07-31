"""Edge calibration: every hand-assigned weight must earn its keep against data.

The seed's weights (0.6 vs 0.5) are beliefs. This module turns them into
evidence: brain.db already records the field activation of every node each
cycle (node_history) and a daily price for every tradable (price_history).
Cross them:

  for each curated `influences` edge (factor/theme/commodity -> asset):
      on every day the SOURCE node was meaningfully activated (|a| >= MIN_ACT),
      the edge predicted sign(a) x edge.sign for the asset's forward ~5d return.
      Score the prediction against what prices then did.

Per edge: n, hit_rate, mean signed return, t-stat, verdict —
  supported     t >= +1.5, n >= MIN_N   -> confidence x1.15 (capped)
  contradicted  t <= -1.5, n >= MIN_N   -> confidence x0.5
  unproven      otherwise               -> x1.0 (belief stands, unbacked)

Plus a global GAIN: the ratio of realized |move| to predicted |expected move|
across all active signals — if the brain systematically overshoots (predicts 3%
moves that come in at 1%), gain < 1 shrinks every expected-move readout
(brain/scale.py applies it).

Results land in data/edge_calibration.json. The graph applies the multipliers
IN MEMORY at load (KnowledgeGraph.set_calibration) — never persisted into edge
confidence, so re-running can't compound.

CLI:  cd engine && python3 -m ai_investing.brain.calibration
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
from datetime import datetime, timezone

MIN_ACT = 0.05        # source activation below this is noise, not a signal
MIN_N = 20            # samples before a verdict is allowed
T_BAR = 1.5           # |t| needed to move an edge off "unproven"
DEADBAND = 0.003      # |move| under 0.3% decides nothing (matches scorecard)
HORIZON = 5           # calendar snapshots ~ trading days, matches scorecard
SUPPORTED_X, CONTRADICTED_X = 1.15, 0.5


def _cal_path(settings) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(settings.brain.db_path)),
                        "edge_calibration.json")


def _load_histories(settings) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, float]]]:
    """(activations[node][date] = last activation, prices[symbol][date] = price)."""
    acts: dict[str, dict[str, float]] = {}
    prices: dict[str, dict[str, float]] = {}
    try:
        conn = sqlite3.connect(settings.brain.db_path)
        for ts, node, a in conn.execute(
                "SELECT ts, node, activation FROM node_history ORDER BY ts"):
            acts.setdefault(node, {})[str(ts)[:10]] = a     # last write per day wins
        for sym, date, px in conn.execute(
                "SELECT symbol, date, price FROM price_history"):
            if px and px > 0:
                prices.setdefault(sym, {})[date] = px
        conn.close()
    except sqlite3.Error:
        pass
    return acts, prices


def _forward_return(dated_prices: dict[str, float], dates: list[str],
                    i: int, horizon: int) -> float | None:
    """Return from dates[i] to the first snapshot >= horizon days later."""
    d0 = dates[i]
    p0 = dated_prices[d0]
    t0 = datetime.fromisoformat(d0)
    for d1 in dates[i + 1:]:
        if (datetime.fromisoformat(d1) - t0).days >= horizon:
            return dated_prices[d1] / p0 - 1.0
    return None


def _score_pair(src_acts: dict[str, float], px: dict[str, float], sign: int,
                weight: float, vol: float, horizon: int,
                mags: tuple[list[float], list[float]]) -> dict | None:
    """Score one (source node -> asset) transmission: on every day the source
    was meaningfully activated, did the asset's forward return match?"""
    if not src_acts or len(px) < 3:
        return None
    dates = sorted(px)
    signed: list[float] = []
    hits = misses = 0
    realized_mag, predicted_mag = mags
    for i, d in enumerate(dates):
        a = src_acts.get(d)
        if a is None or abs(a) < MIN_ACT:
            continue
        fwd = _forward_return(px, dates, i, horizon)
        if fwd is None:
            continue
        pred = (1 if a > 0 else -1) * sign
        signed.append(pred * fwd)
        realized_mag.append(abs(fwd))
        predicted_mag.append(abs(a) * weight * vol * math.sqrt(horizon))
        if abs(fwd) >= DEADBAND:
            if pred * fwd > 0:
                hits += 1
            else:
                misses += 1
    n = len(signed)
    if n == 0:
        return None
    mean = sum(signed) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in signed) / max(1, n - 1))
    if sd > 1e-12 and n > 1:
        t = mean / (sd / math.sqrt(n))
    else:
        # zero-variance sample: unanimous evidence, t is effectively infinite
        t = math.copysign(99.0, mean) if abs(mean) > DEADBAND else 0.0
    t = max(-99.0, min(99.0, t))
    decided = hits + misses
    verdict = "unproven"
    if n >= MIN_N and t >= T_BAR:
        verdict = "supported"
    elif n >= MIN_N and t <= -T_BAR:
        verdict = "contradicted"
    return {"n": n, "hits": hits, "misses": misses,
            "hit_rate": round(hits / decided, 3) if decided else None,
            "mean_signed_ret": round(mean, 5), "tstat": round(t, 2),
            "verdict": verdict}


def calibrate(settings, graph, horizon: int = HORIZON) -> dict:
    """Score every curated influences-edge into an asset, AND every theme ->
    member transmission path (most impact arrives via membership, so auditing
    only direct edges leaves the graph's main arteries unexamined). Write the
    report."""
    acts, prices = _load_histories(settings)
    edges_report: dict[str, dict] = {}
    paths_report: dict[str, dict] = {}
    mags: tuple[list[float], list[float]] = ([], [])
    try:
        from ai_investing.brain.scale import symbol_vols
        vols = symbol_vols(settings, graph)
    except Exception:
        vols = {}

    for e in graph.edges:
        if e.provenance != "seed":
            continue
        if e.type == "influences":
            dst = graph.nodes.get(e.dst)
            if dst is None or dst.type != "asset" or not dst.symbol:
                continue
            sym = dst.symbol.upper()
            r = _score_pair(acts.get(e.src) or {}, prices.get(sym) or {}, e.sign,
                            e.weight, vols.get(sym, 0.02), horizon, mags)
            if r:
                edges_report[graph.edge_key(e)] = r
        elif e.type == "member_of":
            # path: theme/sector activation -> member asset forward return
            # (member_of flows in reverse: theme shock hits the member, sign +)
            src_asset = graph.nodes.get(e.src)
            theme = graph.nodes.get(e.dst)
            if (src_asset is None or theme is None or src_asset.type != "asset"
                    or not src_asset.symbol or theme.type not in ("theme", "sector")):
                continue
            sym = src_asset.symbol.upper()
            r = _score_pair(acts.get(e.dst) or {}, prices.get(sym) or {}, e.sign,
                            e.weight, vols.get(sym, 0.02), horizon, mags)
            if r:
                paths_report[graph.edge_key(e)] = r

    realized_mag, predicted_mag = mags
    gain = 1.0
    if len(realized_mag) >= MIN_N and predicted_mag:
        rm = sorted(realized_mag)[len(realized_mag) // 2]
        pm = sorted(predicted_mag)[len(predicted_mag) // 2]
        if pm > 1e-9:
            gain = max(0.25, min(2.0, rm / pm))

    scored = {**edges_report, **paths_report}
    report = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "horizon_days": horizon,
        "edges": edges_report,
        "paths": paths_report,
        "gain": round(gain, 3),
        "summary": {
            "scored": len(scored),
            "paths_scored": len(paths_report),
            "supported": sum(1 for r in scored.values() if r["verdict"] == "supported"),
            "contradicted": sum(1 for r in scored.values() if r["verdict"] == "contradicted"),
            "unproven": sum(1 for r in scored.values() if r["verdict"] == "unproven"),
        },
    }
    try:
        with open(_cal_path(settings), "w") as fh:
            json.dump(report, fh, indent=1)
    except OSError:
        pass
    return report


def factors_from_report(report: dict) -> dict[str, float]:
    """Edge-key -> confidence multiplier, for KnowledgeGraph.set_calibration.
    Path verdicts land on their member_of edges — a contradicted theme->member
    transmission demotes exactly that membership wire."""
    out: dict[str, float] = {}
    for group in ("edges", "paths"):
        for key, r in (report.get(group) or {}).items():
            if r.get("verdict") == "supported":
                out[key] = SUPPORTED_X
            elif r.get("verdict") == "contradicted":
                out[key] = CONTRADICTED_X
    return out


def apply(settings, graph) -> dict:
    """Load the saved report (if any) and attach its multipliers to the graph.
    Returns a small summary for the brain state; {} when nothing saved yet."""
    try:
        with open(_cal_path(settings)) as fh:
            report = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}
    graph.set_calibration(factors_from_report(report))
    return {"generated": report.get("generated"), "gain": report.get("gain", 1.0),
            **(report.get("summary") or {})}


def main() -> None:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from ai_investing.config import settings
    from ai_investing.brain.graph import KnowledgeGraph
    graph = KnowledgeGraph.load(settings.brain.graph_path)
    report = calibrate(settings, graph)
    s = report["summary"]
    print(f"Edge calibration ({report['horizon_days']}d horizon): "
          f"{s['scored']} scored ({s.get('paths_scored', 0)} membership paths) — "
          f"{s['supported']} supported, "
          f"{s['contradicted']} contradicted, {s['unproven']} unproven. "
          f"gain={report['gain']}")
    ranked = sorted({**report["edges"], **report.get("paths", {})}.items(),
                    key=lambda kv: kv[1]["tstat"])
    if ranked:
        print("\n  weakest edges (candidates for demotion):")
        for key, r in ranked[:8]:
            print(f"    {key:<50} n={r['n']:>4} t={r['tstat']:>6.2f} {r['verdict']}")
        print("\n  strongest edges:")
        for key, r in ranked[-8:][::-1]:
            print(f"    {key:<50} n={r['n']:>4} t={r['tstat']:>6.2f} {r['verdict']}")
    if not ranked:
        print("  (no samples yet — the calibrator needs node_history + price_history "
              "to accumulate; it scores automatically as the engine runs daily)")


if __name__ == "__main__":
    main()
