"""Peer comps — the banker's core craft, automated from data we already hold.

Absolute valuation (the DCF) answers "cheap versus its own cash flows".
Comps answer the question every PM asks first: "cheap versus its PEERS?"

  EV        = market cap + total debt − cash        (snapshot + statements)
  EBITDA    = EBIT + D&A                            (statements)
  peer group= the knowledge graph's theme clusters  (member_of)

For each theme with 3+ members carrying clean data, every member gets a
z-score of its EV/EBITDA within the group: −1.0 = a full standard deviation
cheaper than peers. Financial-mode symbols are excluded (EV/EBITDA is
meaningless for banks — their comps are P/B and ROE, which the value
scanner already uses for them).

CLI: python -m ai_investing.data.comps [THEME_ID]
"""
from __future__ import annotations

import json
import os
import sys


def _snap(settings=None) -> dict:
    base = (os.path.dirname(os.path.abspath(settings.state_path)) if settings is not None
            else os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.dirname(os.path.abspath(__file__))))), "data"))
    try:
        with open(os.path.join(base, "fundamentals.json")) as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}


def ev_ebitda(sym: str, snap: dict, hist: dict) -> float | None:
    rec = hist.get(sym) or {}
    traj = rec.get("trajectory") or {}
    if traj.get("is_financial") or not rec.get("years"):
        return None
    last = rec["years"][-1]
    mcap = (snap.get(sym) or {}).get("marketCap")
    ebit, dna = last.get("ebit"), last.get("dna")
    if not mcap or ebit is None:
        return None
    ebitda = ebit + (dna or 0.0)
    if ebitda <= 0:
        return None
    ev = mcap + (last.get("total_debt") or 0.0) - (last.get("cash") or 0.0)
    ratio = ev / ebitda
    # currency-mismatch guard (ADR mcap in USD vs local-currency statements):
    # implausibly tiny multiples are unit artifacts, not bargains
    if ratio < 1.0 or ratio > 200:
        return None
    return round(ratio, 2)


def theme_comps(settings=None, min_members: int = 3) -> dict[str, dict]:
    """theme id -> {members: {sym: {ev_ebitda, z}}, median} for every graph
    theme with enough clean members to make a comps table honest."""
    from ai_investing.brain.graph import KnowledgeGraph
    from ai_investing.data.fundamentals_history import load_cache
    g = KnowledgeGraph.seeded()
    snap, hist = _snap(settings), load_cache(settings)
    by_theme: dict[str, list[tuple[str, float]]] = {}
    for e in g.edges:
        if e.type != "member_of":
            continue
        n, t = g.nodes.get(e.src), g.nodes.get(e.dst)
        if n is None or t is None or n.type != "asset" or not n.symbol \
                or t.type not in ("theme", "sector"):
            continue
        r = ev_ebitda(n.symbol, snap, hist)
        if r is not None:
            by_theme.setdefault(t.id, []).append((n.symbol, r))
    out: dict[str, dict] = {}
    for theme, rows in by_theme.items():
        if len(rows) < min_members:
            continue
        vals = [v for _, v in rows]
        mean = sum(vals) / len(vals)
        sd = (sum((v - mean) ** 2 for v in vals) / max(1, len(vals) - 1)) ** 0.5
        med = sorted(vals)[len(vals) // 2]
        out[theme] = {"median": round(med, 2),
                      "members": {s: {"ev_ebitda": v,
                                      "z": round((v - mean) / sd, 2) if sd > 1e-9 else 0.0}
                                  for s, v in sorted(rows, key=lambda x: x[1])}}
    return out


def relative_value_scores(settings=None) -> dict[str, float]:
    """symbol -> peer-relative cheapness in [0,1]: 0.5 at z=-1, 1.0 at z<=-2.
    A symbol in several themes takes its BEST (cheapest-relative) group —
    generous on purpose; the absolute layer and trap gates temper it."""
    out: dict[str, float] = {}
    for theme, tbl in theme_comps(settings).items():
        for sym, r in tbl["members"].items():
            z = r["z"]
            if z <= -0.5:
                score = min(1.0, (-z - 0.5) / 1.5)
                if score > out.get(sym, 0.0):
                    out[sym] = round(score, 3)
    return out


if __name__ == "__main__":
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    tables = theme_comps()
    want = sys.argv[1] if len(sys.argv) > 1 else None
    for theme, tbl in sorted(tables.items()):
        if want and theme != want:
            continue
        print(f"\n{theme}  (median EV/EBITDA {tbl['median']}):")
        for sym, r in tbl["members"].items():
            tag = " <== cheap vs peers" if r["z"] <= -1 else (" [rich]" if r["z"] >= 1 else "")
            print(f"  {sym:10s} {r['ev_ebitda']:>7.1f}x  z {r['z']:+.2f}{tag}")
