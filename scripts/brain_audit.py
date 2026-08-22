#!/usr/bin/env python3
"""Audit the brain: every measurement in BRAIN_REVIEW_2026-08-21, on demand.

WHY THIS EXISTS. That review was produced with throwaway scripts. Its findings
were real and several were serious — a 65x sample-replication defect that had
reversed the conclusions of two earlier reviews, a graph resolving 202 objects
across 476 assets, four learning loops that had never produced an output — but
the *instrument* that found them did not survive the session. A finding you
cannot re-measure is a story, not a metric, and the next person (or the next
model) starts from zero.

So: one command, no arguments, read-only, no market calls and no LLM. It
reproduces every number in that review against whatever the live state says
today, and it is designed to be run BEFORE writing any future review.

    python3 scripts/brain_audit.py                 # everything, human-readable
    python3 scripts/brain_audit.py --json          # same, machine-readable
    python3 scripts/brain_audit.py --section graph # just one

WHAT IT WILL NOT DO. It does not decide anything, trade, or write to any file
the engine reads. Judgement stays with the reader — see §10.4 of the review for
what was deliberately left open and why.

THE FOUR TRAPS IT ENCODES. Each of these produced a wrong published conclusion
in this project's own history, and each is now checked rather than remembered:

  1. PSEUDO-REPLICATION. `advice_log` is written every cycle, so one standing
     view was graded ~126 times a day against the same forward return. Count
     (symbol, day) observations, never rows. §1.
  2. OVERLAPPING WINDOWS. Daily samples of a 5-day forward return share 4/5 of
     their window, so even deduplicated observations are not independent. The
     sample size is deflated by ~HORIZON_DAYS, giving `n_effective`. §1.2.
  3. NO BENCHMARK. A call graded against zero measures the tape's drift. This
     bit the advice scorecard in August (its `_BENCH` comment) and bit
     event_outcomes again in the same way. §4.4.
  4. NO CONTROL GROUP. "Panic rebounds" is a COMPARATIVE claim and needs an
     ordinary event to compare against — measured against zero it returned the
     same answer for opposite emotions. §4.4.
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))

MIN_DAYS = 8                # below this, a hit-rate is an anecdote
P_BAR = 0.05                # two-sided binomial, against a coin


# --------------------------------------------------------------- statistics --
def _binom_p(hits: int, n: int) -> float | None:
    """Two-sided exact binomial p-value against p=0.5.

    WHY NOT A t-TEST. `hit` is Bernoulli, and a t-test on it degenerates
    exactly where the evidence is strongest: a symbol that hit 12 out of 12 has
    zero sample variance, so the t is undefined and the pair silently drops out
    of any "what clears a bar" list. The first draft of this script did that and
    lost four of the nine pairs the 2026-08-21 review had reported, including a
    12-for-12 record. A binomial test handles a perfect run natively, which is
    the case that matters most.
    """
    if n <= 0:
        return None
    hits = max(0, min(n, int(round(hits))))
    # P(X = k) under p=0.5 is C(n,k)/2^n; sum the tail at or below the observed
    # likelihood, which for a symmetric null is both tails at distance >= |k-n/2|
    d = abs(hits - n / 2)
    total = sum(math.comb(n, k) for k in range(n + 1)
                if abs(k - n / 2) >= d - 1e-9)
    return min(1.0, total / (2 ** n))


def _effective_n(n: int, horizon: int) -> int:
    """Trap 2. Consecutive daily observations of an h-day forward return share
    (h-1)/h of their window, so `n` daily samples carry roughly n/h independent
    ones. Applying the deflation to the SAMPLE SIZE rather than to a finished
    statistic is both simpler to explain and correct for a binomial: it says
    plainly that 12 daily observations are about 2 independent bets."""
    return max(1, int(n / max(1, horizon)))


def _evidence(hits: int, n: int, horizon: int) -> dict:
    """The honest pair: what the raw sample says, and what it says after the
    windows are accounted for. Always report both — the gap between them IS the
    finding, and quoting only the first is how this project published two
    reviews that contradicted each other."""
    n_eff = _effective_n(n, horizon)
    return {
        "n": n, "hits": hits,
        "hit": round(hits / n, 3) if n else None,
        "p": (None if (p := _binom_p(hits, n)) is None else round(p, 4)),
        "n_effective": n_eff,
        "p_effective": (None if (pe := _binom_p(round(hits * n_eff / n), n_eff)
                                 if n else None) is None else round(pe, 4)),
    }


def _ro(path: str):
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def _has_column(con, table: str, column: str) -> bool:
    try:
        return column in {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
    except sqlite3.Error:
        return False


# ------------------------------------------------------------------ section --
def counting_unit(s) -> dict:
    """Trap 1, as a standing check. Rows vs (symbol, day) observations."""
    con = _ro(s.brain.db_path)
    has = _has_column(con, "advice_outcomes", "is_primary")
    try:
        rows = con.execute("select count(*) from advice_outcomes").fetchone()[0]
        obs = con.execute(
            "select count(distinct symbol || date(ts_issued,'+8 hours')) "
            "from advice_outcomes").fetchone()[0]
        labelled = (con.execute(
            "select count(*) from advice_outcomes where is_primary=1").fetchone()[0]
            if has else None)
        gradable = (con.execute(
            "select count(*) from advice_outcomes where is_primary=1 "
            "and hit is not null").fetchone()[0] if has else None)
    except sqlite3.Error as exc:
        return {"error": str(exc)}
    finally:
        con.close()
    return {
        "rows": rows, "observations": obs,
        "replication": round(rows / obs, 1) if obs else None,
        "labelled_primary": labelled,
        # Like for like: distinct (symbol, day) over ALL rows, against the
        # count of rows carrying the label. If these diverge, some write path
        # is bypassing the rule -- which is how the original defect existed.
        "label_agrees": labelled == obs if labelled is not None else None,
        "gradable_observations": gradable,
        "lost_to_deadband": (obs - gradable) if gradable is not None else None,
        # A symbol-day whose FIRST call fell inside the deadband contributes no
        # claim, and must NOT be replaced by a later re-issue that happened to
        # land outside it -- that is selection on the outcome. Note also that
        # re-issues of one day are graded at different moments against
        # different "latest" prices, so near the deadband boundary they can
        # genuinely disagree; the primary row is graded once, deterministically.
        "note": "deadband losses are dropped, never back-filled from a re-issue",
    }


def directional_record(s, horizon: int) -> dict:
    """direction x conviction, ONE observation per (symbol, day)."""
    con = _ro(s.brain.db_path)
    primary = " and is_primary=1" if _has_column(con, "advice_outcomes", "is_primary") else ""
    try:
        rows = con.execute(
            "select direction, coalesce(is_conviction,1), symbol, "
            "       date(ts_issued,'+8 hours') as d, hit, excess_ret "
            "from advice_outcomes "
            f"where hit is not null and excess_ret is not null{primary}").fetchall()
    except sqlite3.Error as exc:
        con.close()
        return {"error": str(exc)}
    con.close()

    buckets: dict[tuple, list] = collections.defaultdict(list)
    for direction, conv, _sym, _d, hit, exc in rows:
        buckets[(direction, int(conv))].append((hit, exc))

    out = {}
    for (direction, conv), vals in sorted(buckets.items()):
        out[f"{direction}/conv={conv}"] = {
            **_evidence(sum(v[0] for v in vals), len(vals), horizon),
            "avg_excess_pct": round(100 * sum(v[1] for v in vals) / len(vals), 2),
        }
    return out


def symbol_record(s, horizon: int) -> dict:
    """Which (symbol, call) pairs clear a real bar — in BOTH directions.

    Reporting only the winners is how a track record flatters itself. This
    reports every pair with >= MIN_DAYS distinct days clearing a two-sided
    binomial p <= P_BAR, and separates the ones that are significantly RIGHT
    from the ones that are significantly WRONG.
    """
    con = _ro(s.brain.db_path)
    primary = " and is_primary=1" if _has_column(con, "advice_outcomes", "is_primary") else ""
    try:
        rows = con.execute(
            "select symbol, direction, date(ts_issued,'+8 hours') as d, hit, excess_ret "
            "from advice_outcomes "
            f"where hit is not null and excess_ret is not null{primary}").fetchall()
    except sqlite3.Error as exc:
        con.close()
        return {"error": str(exc)}
    con.close()

    per: dict[tuple, list] = collections.defaultdict(list)
    for sym, direction, _d, hit, exc in rows:
        per[(sym, direction)].append((hit, exc))

    right, wrong, total = [], [], 0
    for (sym, direction), vals in per.items():
        total += 1
        if len(vals) < MIN_DAYS:
            continue
        ev = _evidence(sum(v[0] for v in vals), len(vals), horizon)
        if ev["p"] is None or ev["p"] > P_BAR:
            continue
        rec = {"symbol": sym, "call": direction, "days": len(vals),
               "avg_excess_pct": round(100 * sum(v[1] for v in vals) / len(vals), 2),
               **ev}
        (right if ev["hit"] > 0.5 else wrong).append(rec)
    return {"pairs_examined": total,
            "bar": f">= {MIN_DAYS} distinct days and binomial p <= {P_BAR}",
            "significantly_right": sorted(right, key=lambda r: r["p"]),
            "significantly_wrong": sorted(wrong, key=lambda r: r["p"])}


def event_record(s) -> dict:
    """The second, independent instrument: graded event predictions.

    Two different measurements agreeing is the only reason to believe anything
    at this sample size, so this is reported beside the advice record rather
    than folded into it.
    """
    con = _ro(s.brain.db_path)
    has_basis = _has_column(con, "event_outcomes", "basis")
    try:
        by_sign = {}
        for sign, noise, n, hit in con.execute(
                "select impact_sign, is_noise, count(*), avg(hit) from event_outcomes "
                "where hit is not null group by 1,2 order by 1,2"):
            by_sign[f"sign={sign:+d}/noise={noise}"] = {
                "n": n, "hit": round(hit, 3)}
        by_emotion = {}
        for emo, n, hit in con.execute(
                "select emotion, count(*), avg(hit) from event_outcomes "
                "where hit is not null group by 1 having count(*) >= 100 "
                "order by count(*) desc"):
            by_emotion[emo or "(none)"] = {"n": n, "hit": round(hit, 3)}
        basis = {}
        if has_basis:
            for b, n in con.execute(
                    "select coalesce(basis,'(null)'), count(*) "
                    "from event_outcomes group by 1"):
                basis[b] = n
            benched = con.execute(
                "select count(*) from event_outcomes "
                "where bench_symbol is not null").fetchone()[0]
        else:
            benched = 0
    except sqlite3.Error as exc:
        con.close()
        return {"error": str(exc)}
    con.close()
    return {
        "by_sign": by_sign, "by_emotion": by_emotion,
        "grading_basis": basis or "pre-migration (absolute only)",
        "rows_with_benchmark": benched,
        # Trap 3, named at the point of measurement rather than in a docstring
        # nobody reads: a hit graded against zero measures the tape.
        "warning": (None if benched else
                    "NO row is market-relative yet — every hit-rate here is "
                    "graded against ZERO, so it partly measures the window's "
                    "drift. Treat the +1/-1 ASYMMETRY as the signal, not the level."),
    }


def graph_resolution(s) -> dict:
    """How many distinct objects the graph can actually tell apart.

    Probes every origin node individually and groups assets by their response
    vector. This is the measurement behind "202 signatures across 476 assets".
    It is the slowest section (a few seconds to a minute).
    """
    from ai_investing.brain.adviser import indistinguishable_groups
    from ai_investing.brain.graph import KnowledgeGraph

    g = KnowledgeGraph.load(s.brain.graph_path)
    origins = sorted(i for i, n in g.nodes.items()
                     if n.type in ("factor", "commodity", "actor"))
    assets = [i for i, n in g.nodes.items() if n.type == "asset"]

    signatures: dict[str, list] = {a: [] for a in assets}
    for o in origins:
        impacts = g.propagate({o: 0.6}, max_hops=3)[0]
        for a in assets:
            signatures[a].append(round(impacts.get(a, 0.0), 5))

    groups = collections.defaultdict(list)
    for a, vec in signatures.items():
        groups[tuple(vec)].append(a)
    inert = [a for a, vec in signatures.items() if not any(vec)]
    duplicated = sum(len(v) for k, v in groups.items() if len(v) > 1 and any(k))

    llm = [e for e in g.edges if e.provenance == "llm"]
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    # Judged by each node's OWN type: a THEME node naming a category
    # (`uk_banks`) is the definition, not a placeholder. Passing the bare id
    # defaults to "asset" and reported three curated seeds as junk.
    placeholders = [n.id for n in g.nodes.values()
                    if KnowledgeGraph.is_non_entity(n.id, n.type)]

    # a worked example, so the number is legible rather than abstract
    example = indistinguishable_groups(
        g.asset_impacts(g.propagate({"crypto_liquidity": 0.6}, max_hops=3)[0]))

    return {
        "nodes": len(g.nodes), "edges": len(g.edges), "assets": len(assets),
        "origins_probed": len(origins),
        "distinct_signatures": len(groups),
        "resolution_pct": round(100 * len(groups) / len(assets), 1) if assets else None,
        "inert_assets": len(inert),
        "assets_duplicating_a_peer": duplicated,
        "llm_edges": len(llm),
        "llm_share_pct": round(100 * len(llm) / len(g.edges), 1) if g.edges else None,
        "llm_proposed_last_7d": g.proposal_rate(week_ago),
        "daily_proposal_budget": g.daily_proposal_budget,
        "unreviewed_llm_edges": sum(1 for e in llm if not e.reviewed_at),
        "placeholder_nodes": placeholders,
        "orphan_llm_nodes": len(g.orphan_nodes()),
        "example_crypto_liquidity_shock": {
            "assets_touched": len([1 for v in g.asset_impacts(
                g.propagate({"crypto_liquidity": 0.6}, max_hops=3)[0]).values()
                if abs(v["impact"]) > 1e-4]),
            "of_which_indistinguishable": len(example),
        },
    }


def learning_loops(s) -> dict:
    """Is anything actually learning? Each loop, with the evidence.

    Every one of these was DESCRIBED as operating in the design docs while
    producing no output in production. A loop that has never moved is not a
    slow loop, it is a broken one, and it should be visible without reading
    five JSON files by hand.
    """
    out: dict = {}
    data = Path(s.brain.db_path).parent

    # -- the formula: two loops, per FORMULA.md §4 ---------------------------
    try:
        f = json.loads((data / "formula.json").read_text())
        model, rls = f.get("model") or {}, f.get("rls") or {}
        theta, prior = rls.get("theta") or [], model.get("weights") or []
        moved = any(abs(a - b) > 1e-12 for a, b in zip(theta, prior)) \
            if len(theta) == len(prior) and theta else None
        out["formula"] = {
            "written": f.get("ts"), "version": model.get("version"),
            "fitted": model.get("fitted"),
            "features": len(model.get("feature_names") or []),
            "feature_names": model.get("feature_names"),
            "rls_samples": rls.get("n"),
            "rls_theta_moved_from_prior": moved,
            "alive": bool(model.get("fitted")) or bool(moved),
        }
    except (OSError, json.JSONDecodeError) as exc:
        out["formula"] = {"error": str(exc)}

    try:
        con = _ro(s.db_path)
        out["formula"]["outcomes_rows"] = con.execute(
            "select count(*) from outcomes").fetchone()[0]
        out["formula"]["param_versions"] = con.execute(
            "select count(distinct weights) from params").fetchone()[0]
        con.close()
    except sqlite3.Error as exc:
        out["formula"]["outcomes_rows"] = f"error: {exc}"

    # -- the edge calibrator -------------------------------------------------
    try:
        cal = json.loads((data / "edge_calibration.json").read_text())
        summary = cal.get("summary") or {}
        gain = cal.get("gain")
        out["edge_calibration"] = {
            "generated": cal.get("generated"), **summary, "gain": gain,
            # 0.25 and 2.0 are the clamp bounds in calibration.py. Sitting ON a
            # bound means the estimate is saturated: the true value is at least
            # this far out and the calibrator cannot say how much further.
            "gain_saturated": gain in (0.25, 2.0),
            "alive": (summary.get("supported", 0) + summary.get("contradicted", 0)) > 0,
        }
    except (OSError, json.JSONDecodeError) as exc:
        out["edge_calibration"] = {"error": str(exc)}

    # -- expected_move vs the NOISE FLOOR -------------------------------------
    # The control §4.45 lacked. |realised/expected| looks like a calibration
    # error and is mostly a signal-to-noise measure: `expected_move` is the move
    # ATTRIBUTABLE to an event, `realized_move` is the asset's TOTAL move, which
    # its own volatility dominates. Reporting the observed ratio WITHOUT the
    # ratio pure noise would produce is how "the model is 14x too small" gets
    # believed, and how someone reaches for the gain. They are printed together
    # or not at all.
    try:
        import math as _m
        opens, settled = {}, []
        for line in (data / "expectations.jsonl").read_text().splitlines():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("state") == "open":
                opens[r.get("id")] = r
            elif r.get("state") == "settled":
                settled.append(r)
        obs, noise, hits, flat_vol = [], [], [], 0
        for st in settled:
            o = opens.get(st.get("id"))
            if not o or not st.get("expected_move"):
                continue
            vol = float(o.get("vol_daily") or 0.0)
            h = int(o.get("horizon_days") or 5)
            exp, real = float(st["expected_move"]), float(st.get("realized_move") or 0.0)
            obs.append(abs(real / exp))
            if vol:
                noise.append(vol * _m.sqrt(h) * 0.7979 / exp)
            hits.append(1 if real * (o.get("direction") or 1) > 0 else 0)
            flat_vol += (abs(vol - 0.02) < 1e-9)
        def _med(xs):
            xs = sorted(xs)
            return round(xs[len(xs) // 2], 1) if xs else None
        out["expected_move"] = {
            "n_settled": len(obs),
            "median_observed_ratio": _med(obs),
            "median_noise_ratio": _med(noise),
            "hit_rate": round(sum(hits) / len(hits), 3) if hits else None,
            "ratio_is_indistinguishable_from_noise":
                bool(obs and noise and abs((_med(obs) or 0) - (_med(noise) or 0))
                     < 0.5 * (_med(noise) or 1)),
            "claims_with_the_2pct_default_vol": flat_vol,
            "note": ("observed ~= noise means the ratio measures signal-to-noise, "
                     "NOT that expected_move is too small. Raising `gain` cannot "
                     "close it and would make the model claim the asset's whole "
                     "range. The honest lever is bigger IMPACT (graph wiring)."),
        }
    except (OSError, ZeroDivisionError) as exc:
        out["expected_move"] = {"error": str(exc)}

    # -- per-symbol reliability ----------------------------------------------
    try:
        rel = json.loads((data / "reliability.json").read_text())
        vals = [v.get("r", 1.0) if isinstance(v, dict) else v for v in rel.values()]
        pinned = sum(1 for v in vals if v <= 0.51 or v >= 1.39)
        out["reliability"] = {
            "symbols": len(vals), "pinned_at_a_bound": pinned,
            "pinned_pct": round(100 * pinned / len(vals), 1) if vals else None,
            "neutral": sum(1 for v in vals if abs(v - 1.0) < 1e-9),
            # Saturation is the signature of an estimator stepping many times
            # per real observation -- the defect fixed on 2026-08-21.
            "healthy": (pinned / len(vals) < 0.25) if vals else None,
        }
    except (OSError, json.JSONDecodeError) as exc:
        out["reliability"] = {"error": str(exc)}

    # -- emotion coefficients ------------------------------------------------
    try:
        emo = json.loads((data / "emotion_calibration.json").read_text())
        out["emotion_calibration"] = {
            "generated": emo.get("generated"),
            "return_basis": emo.get("return_basis", "(pre-control-group)"),
            **{k: {kk: emo[k].get(kk) for kk in
                   ("coef", "basis", "n", "baseline_n", "lift", "tstat")}
               for k in ("panic_rebound", "euphoria_fade") if k in emo},
            "has_control_group": "baseline_n" in (emo.get("panic_rebound") or {}),
        }
    except (OSError, json.JSONDecodeError) as exc:
        out["emotion_calibration"] = {"error": str(exc)}

    # -- the adviser sizing gate --------------------------------------------
    try:
        gate = json.loads((data / "adviser_gate.json").read_text())
        out["adviser_gate"] = {k: gate.get(k) for k in
                               ("checked_at", "eligible", "adviser_long",
                                "formula_short", "threshold")}
    except (OSError, json.JSONDecodeError) as exc:
        out["adviser_gate"] = {"error": str(exc)}
    return out


def reach(s, horizon: int) -> dict:
    """Correct calls the books could not act on — by market, and by whether the
    symbol was EVER held.

    THE FINDING THIS USED TO KEEP VISIBLE, AND WHY IT IS NOW RETIRED. This
    section existed to show that the brain's conviction-long hit-rate ranked
    INVERSELY with its ability to place the order — best in Korea and Tokyo,
    both unreachable, worst in the US, its only open market. That claim was
    used, on 2026-08-22, to argue for a first live order on an unproven market
    path.

    It does not survive its own sample. These are daily readings of a 5-day
    forward return, so consecutive rows overlap almost entirely and the
    independent count is n/HORIZON:

        market  raw n  hit    n_eff   p(n_eff)
        KS          9  0.889    1.8     0.250
        SI          8  0.875    1.6     0.750
        HK         16  0.562    3.2     0.500
        US         51  0.529   10.2     0.623

    Not one row is distinguishable from a coin flip. The "inverse ranking" was
    noise, ranked. §4.37 fixed this counting defect in the scorecard and §4.47
    fixed it in the calibrator; this section — the one actually used to argue
    about which market to trade — never got it. So every row now carries
    `n_independent` and a `significant` verdict, and `hit` is not reported
    without them.
    """
    data = Path(s.brain.db_path).parent
    held: set[str] = set()
    for jf in ("event_journal.jsonl", "invest_journal.jsonl", "crypto_journal.jsonl",
               "stock_journal.jsonl", "crypto_event_journal.jsonl"):
        try:
            for line in (data / jf).read_text().splitlines():
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if r.get("symbol"):
                    held.add(r["symbol"])
        except OSError:
            continue

    con = _ro(s.brain.db_path)
    primary = " and is_primary=1" if _has_column(con, "advice_outcomes", "is_primary") else ""
    try:
        rows = con.execute(
            "select symbol, date(ts_issued,'+8 hours'), hit, excess_ret "
            "from advice_outcomes where direction='long' and is_conviction=1 "
            f"  and hit is not null and excess_ret is not null{primary}").fetchall()
    except sqlite3.Error as exc:
        con.close()
        return {"error": str(exc)}
    con.close()

    def market(sym: str) -> str:
        if "/" in sym:
            return "CRYPTO"
        return sym.rsplit(".", 1)[1] if "." in sym else "US"

    by_market = collections.defaultdict(list)
    by_symbol = collections.defaultdict(list)
    for sym, _d, hit, exc in rows:
        by_market[market(sym)].append((hit, exc))
        by_symbol[sym].append((hit, exc))

    def _binom_p(k: int, n: int) -> float:
        """One-sided P(X >= k) under a fair coin. The honest test for a hit
        rate, and the one §4.37 established: `hit` is Bernoulli, so a t-test
        degenerates on it."""
        return sum(math.comb(n, i) for i in range(k, n + 1)) / (2 ** n)

    markets = {}
    for m, vals in sorted(by_market.items(), key=lambda kv: -len(kv[1])):
        n, hit = len(vals), sum(v[0] for v in vals) / len(vals)
        # Daily readings of a HORIZON-day forward return overlap almost
        # entirely. n/HORIZON is what the sample is actually worth.
        n_eff = max(1, round(n / horizon))
        p = _binom_p(round(hit * n_eff), n_eff)
        markets[m] = {
            "n": n,
            "n_independent": n_eff,
            "hit": round(hit, 3),
            "p_value": round(p, 3),
            "significant": bool(p < 0.05),
            "avg_excess_pct": round(100 * sum(v[1] for v in vals) / len(vals), 2)}

    never = []
    for sym, vals in by_symbol.items():
        if sym in held or len(vals) < 3:
            continue
        hit = sum(v[0] for v in vals) / len(vals)
        if hit < 0.6:
            continue
        n_eff = max(1, round(len(vals) / horizon))
        never.append({"symbol": sym, "days": len(vals),
                      "n_independent": n_eff,
                      "hit": round(hit, 2),
                      "p_value": round(_binom_p(round(hit * n_eff), n_eff), 3),
                      "significant": bool(_binom_p(round(hit * n_eff), n_eff) < 0.05),
                      "avg_excess_pct": round(
                          100 * sum(v[1] for v in vals) / len(vals), 2)})
    return {"by_market": markets,
            "symbols_traded_ever": len(held),
            "horizon_days": horizon,
            "note": ("`days` is symbol-days; `n_independent` = days/horizon is what "
                     "the sample is worth, because daily readings of a forward return "
                     "overlap. A row with significant=false is NOT a missed "
                     "opportunity — it is a coin flip that landed heads. Do not size "
                     "a trade on one."),
            "correct_but_never_held": sorted(
                never, key=lambda r: -r["avg_excess_pct"] * r["days"])}


def _student_p(t: float, df: int) -> float:
    """Two-sided p for Student's t, via the regularised incomplete beta.

    Written out rather than imported because the normal approximation is wrong
    exactly where this audit operates — small n. At n=6 the normal says p=0.029
    where t actually says p=0.081, and the difference is the whole verdict.
    """
    if df <= 0:
        return 1.0
    x = df / (df + t * t)
    return _betainc(df / 2.0, 0.5, x)


def _betainc(a: float, b: float, x: float) -> float:
    """Regularised incomplete beta I_x(a, b) by continued fraction (Lentz)."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    lbeta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    front = math.exp(math.log(x) * a + math.log(1 - x) * b - lbeta) / a
    if x >= (a + 1) / (a + b + 2):          # use the symmetry for convergence
        return 1.0 - _betainc(b, a, 1 - x)
    f, c, d = 1.0, 1.0, 0.0
    for i in range(0, 300):
        m = i // 2
        if i == 0:
            num = 1.0
        elif i % 2 == 0:
            num = m * (b - m) * x / ((a + 2 * m - 1) * (a + 2 * m))
        else:
            num = -((a + m) * (a + b + m) * x) / ((a + 2 * m) * (a + 2 * m + 1))
        d = 1.0 + num * d
        d = 1e-30 if abs(d) < 1e-30 else d
        d = 1.0 / d
        c = 1.0 + num / c
        c = 1e-30 if abs(c) < 1e-30 else c
        f *= c * d
        if abs(1.0 - c * d) < 1e-10:
            break
    return front * (f - 1.0)


def significance(xs):
    """Mean, t, and a p-value from Student's t — NOT the normal.

    The first version used the normal approximation and reported
    **p = 0.000 at n = 3**, which is nonsense: with 2 degrees of freedom
    the standard error is itself estimated from the same three points.
    `test_pnl_significance.py` asserted that tiny samples must never be
    credited with significance, and then this function did exactly that
    — the test was about the arithmetic and the bug was in the code
    beside it.

    Below MIN_N_FOR_P observations no p-value is reported at all. Not a
    conservative one: none. A number that cannot mean anything should
    not be printed in a field a reader will compare against 0.05.
    """
    MIN_N_FOR_P = 5
    n = len(xs)
    if n < 2:
        return {"n": n, "t": None, "p": None, "significant": False}
    m = sum(xs) / n
    sd = (sum((x - m) ** 2 for x in xs) / (n - 1)) ** 0.5
    t = m / (sd / math.sqrt(n)) if sd else 0.0
    out = {"n": n, "mean": round(m, 4), "t": round(t, 2)}
    if n < MIN_N_FOR_P:
        out.update({"p": None, "significant": False,
                    "note": f"n<{MIN_N_FOR_P}: no p-value is meaningful"})
        return out
    p = _student_p(abs(t), n - 1)
    out.update({"p": round(p, 4), "significant": bool(p < 0.05)})
    return out


def pnl_significance(s, horizon: int) -> dict:
    """Per-book realised P&L, and whether it is distinguishable from luck.

    §4.56. This is the question the whole system exists to answer, and it had
    never been asked with the counting discipline the rest of the audit uses.

    THE UNIT IS THE BET, NOT THE FILL. The event sleeve's record reads 16 fills,
    +$1,146, t=2.19, p=0.045 — significant. But it enters and exits a BASKET:
    those fills land on 6 distinct days, three names at a time, and the names
    within a basket are correlated (`NVDA, AMD, 000660.KS` is one semis bet
    wearing three tickers). Counted as baskets it is t=1.64, p=0.162 — not
    significant. Counted as THEMES (energy, solar/materials, semis) it is n=3,
    at which nothing can be significant.

    (Figures above are the CURRENT ones. The first version of this docstring
    quoted 17 trades / +$1,196 / p=0.022 / baskets p=0.082 — the pre-bugfix
    counts and normal-approximation p-values. Corrected 2026-08-22; see
    AUDITING.md's seventh trap. If you change what this function measures,
    change these too, or the next reader inherits the same problem.)

    Same defect as §4.37, §4.47 and §4.53, now at the portfolio level: the
    thing being counted is not the thing that varies independently.

    Both figures are reported, always, because the gap between them IS the
    finding. A book that looks significant per-fill and not per-basket has not
    demonstrated edge; it has demonstrated that it holds correlated positions.
    """
    data = Path(s.brain.db_path).parent

    # --- the benchmark, which is what makes "edge not demonstrated" honest ---
    # §4.6's lesson at the BOOK level. The sleeve's winning baskets were semis
    # and solar during a period when semis and solar ran; a long book in a
    # rising sector makes money without skill. Until a trade's return is
    # measured against what its own market did over the SAME window, no verdict
    # about edge means anything in either direction.
    from ai_investing.brain.scorecard import sector_benchmark_for  # noqa: PLC0415
    series: dict[str, list[tuple[str, float]]] = {}
    try:
        con = _ro(s.brain.db_path)
        for sym, d, px in con.execute(
                "select symbol, date, price from price_history order by date"):
            series.setdefault(sym, []).append((d, float(px)))
        con.close()
    except sqlite3.Error:
        series = {}

    def _px_on(sym: str, day: str):
        """Last price at or before `day`. Markets close; a holiday must not
        silently become 'no benchmark' when yesterday's close is right there."""
        rows = series.get(sym) or []
        best = None
        for d, px in rows:
            if d <= day:
                best = px
            else:
                break
        return best

    def _bench_ret(sym: str, exit_day: str, held: int):
        """Excess against the SECTOR where one exists, the broad market
        otherwise. A single stock measured against SPY has its sector beta
        counted as skill — the exact way a long book in a rising sector looks
        talented (§4.6, §4.57)."""
        b, conf = sector_benchmark_for(sym)
        if not b or held is None:
            return None, None, conf
        entry_day = (datetime.fromisoformat(exit_day)
                     - timedelta(days=int(held))).date().isoformat()
        p0, p1 = _px_on(b, entry_day), _px_on(b, exit_day)
        if not p0 or not p1:
            return b, None, conf
        return b, (p1 - p0) / p0, conf

    out = {}
    for jf, book in (("event_journal.jsonl", "event_sleeve"),
                     ("crypto_journal.jsonl", "crypto"),
                     ("invest_journal.jsonl", "investing"),
                     ("crypto_event_journal.jsonl", "crypto_event"),
                     ("stock_journal.jsonl", "trading")):
        try:
            lines = (data / jf).read_text().splitlines()
        except OSError:
            continue
        fills = []
        for line in lines:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            # The books disagree on the key: the sleeves write `pnl` on a
            # sell row, others write `realized`. Read both rather than pick
            # one and silently measure a subset — the first version read only
            # `realized` and reported nothing at all, which at least failed
            # loudly instead of reporting a confident partial number.
            v = r.get("realized")
            if v is None:
                v = r.get("pnl")
            if v is None or not r.get("symbol"):
                continue
            try:
                day, pnl = str(r.get("ts", ""))[:10], float(v)
            except (TypeError, ValueError):
                continue
            ret = r.get("ret")
            b, br, conf = _bench_ret(r["symbol"], day, r.get("held_days"))
            excess = (float(ret) - br) if (ret is not None and br is not None) else None
            fills.append((day, pnl, excess, b, conf))
        if not fills:
            continue

        by_day: dict[str, float] = {}
        for d, v, _e, _b, _c in fills:
            by_day[d] = by_day.get(d, 0.0) + v
        per_fill = significance([v for _, v, _e, _b, _c in fills])
        per_basket = significance(list(by_day.values()))

        # The same two units again, but on EXCESS over each trade's own market.
        ex = [(d, e) for d, _v, e, _b, _c in fills if e is not None]
        ex_day: dict[str, list[float]] = {}
        for d, e in ex:
            ex_day.setdefault(d, []).append(e)
        excess_block = {"n_benchmarked": len(ex), "of_fills": len(fills)}
        if ex:
            excess_block["per_fill"] = significance([e for _, e in ex])
            excess_block["per_basket"] = significance(
                [sum(v) / len(v) for v in ex_day.values()])
            excess_block["mean_excess_pct"] = round(
                100 * sum(e for _, e in ex) / len(ex), 2)
            excess_block["benchmarks"] = sorted(
                {b for _d, _v, e, b, _c in fills if e is not None and b})
            # How much of the sample got the HARDER test. Without this, a
            # broad-market result reads as a sector-adjusted one.
            excess_block["sector_adjusted_fills"] = sum(
                1 for _d, _v, e, _b, c in fills if e is not None and c == "sector")

        # The verdict is driven by EXCESS at BASKET level, and by nothing else.
        # A first version keyed it off RAW per_basket, which is wrong in both
        # directions: raw P&L in a rising sector is beta (§4.6), and raw P&L is
        # NOISIER than excess because the market factor it contains swamps the
        # residual. On the live record the sleeve is not significant raw
        # (p=0.162) and moves MUCH closer on excess (p=0.080) — same trades.
        # It does not cross 0.05, and the verdict is still "edge not
        # demonstrated"; the point is the DIRECTION of the move. Removing the
        # common factor is what lets a residual be seen at all.
        # (This comment previously read "IS significant on excess (p=0.029)".
        # Those were normal-approximation values; the excess figure has never
        # cleared the bar under Student's t. Corrected 2026-08-22.)
        # SIGNIFICANT AND POSITIVE. The first version tested only significance,
        # and duly reported `crypto_event` — mean excess **-7.44%** — as
        # "beats its benchmark". A two-sided test says "not zero"; it does not
        # say "good". Direction has to be asserted separately, always.
        _eb = excess_block.get("per_basket") or {}
        beat = bool(_eb.get("significant") and (_eb.get("mean") or 0) > 0)
        lags = bool(_eb.get("significant") and (_eb.get("mean") or 0) < 0)
        out[book] = {
            "total_realised": round(sum(v for _, v, _e, _b, _c in fills), 2),
            "per_fill": per_fill,
            "per_basket": per_basket,
            "inflation": (round(per_fill["n"] / per_basket["n"], 1)
                          if per_basket.get("n") else None),
            "excess_over_benchmark": excess_block,
            "verdict": ("beats its benchmark — small sample, read the caveats" if beat
                        else "UNDERPERFORMS its benchmark significantly" if lags
                        else "edge not demonstrated"),
        }
    out["_note"] = ("`per_fill` counts tickers; `per_basket` counts DAYS a bet was "
                    "taken off. A book that is significant per_fill and not "
                    "per_basket has not shown edge — it has shown that it holds "
                    "correlated positions. `excess_over_benchmark` is the measure "
                    "that can see skill: raw P&L in a rising sector is beta (§4.6), "
                    "and raw is also NOISIER, because the market factor it carries "
                    "swamps the residual. Read `per_basket` under excess. "
                    "TWO CAVEATS THAT ARE NOT OPTIONAL: (1) the benchmark is a broad "
                    "index, so excess for a high-beta sector name still contains a "
                    "SECTOR factor — SPY is not the right yardstick for a semis "
                    "basket, and the honest benchmark would be SOXX. (2) four books "
                    "are tested here; one p~0.03 among them is roughly what chance "
                    "produces, so a single significant book is a reason to keep "
                    "measuring, never a reason to size up.")
    return out


# Books whose venue margins positions rather than debiting cash for them.
_MARGINED_BOOKS = {"crypto", "crypto_event"}


def books(s) -> dict:
    """Per-book equity, deployment, and the declared basis it belongs to.

    `basis` is the guard against §4.14: a change of BOOK read as a change in
    VALUE. A step in an equity curve with a basis change beside it is
    explained; the same step without one is a -50% day to the circuit breaker.

    IS THE BOOK DEPLOYING CAPITAL? is the question this section actually exists
    to answer, and getting it wrong is easy in two specific ways that both
    happened on 2026-08-21:

      1. `state.json.broker.positions` is EMPTY for the routed trading book and
         always will be. Its holdings live in the BookLedger (`live_book.json`)
         because the shared Longbridge account holds the shares and the ledger
         records this book's CLAIM on them. Reading the wrong file said "0
         positions" on a book holding ~$4,800 across eight names.
      2. `stock_journal.jsonl` carries ONE DAILY EQUITY MARK by design
         (runner._append_stock_journal) and has never carried fills. Counting
         `event: buy` there said "0 buys" on a book with 24 filled buys.

    Both readings suggested a frozen flagship book. It was trading normally.
    So deployment is computed from the authoritative source per book, and the
    order flow comes from `journal.db.orders`, which is where orders actually
    are.
    """
    data = Path(s.brain.db_path).parent
    out: dict = {}

    # order flow — one source for every book that routes through the engine
    fills: dict = {}
    try:
        con = _ro(s.db_path)
        n_fill, n_buy = con.execute(
            "select count(*), sum(case when side='buy' then 1 else 0 end) "
            "from orders where status='filled'").fetchone()
        last = con.execute("select max(ts) from orders where status='filled'").fetchone()[0]
        rejects = dict(con.execute(
            "select status, count(*) from orders group by 1").fetchall())
        con.close()
        fills = {"filled": n_fill, "buys_filled": n_buy, "last_fill": last,
                 "by_status": rejects}
    except sqlite3.Error as exc:
        fills = {"error": str(exc)}

    for label, fn in (("trading", "state.json"), ("investing", "invest_state.json"),
                      ("event_sleeve", "event_state.json"), ("crypto", "crypto_state.json"),
                      ("crypto_event", "crypto_event_state.json")):
        try:
            d = json.loads((data / fn).read_text())
        except (OSError, json.JSONDecodeError):
            out[label] = {"error": f"{fn} unreadable"}
            continue
        eq = d.get("equity")
        cash = d.get("cash")
        b = d.get("broker") or {}
        if cash is None:
            cash = b.get("cash")
        n_pos = len(b.get("positions") or [])
        source = fn
        if label == "trading":
            # authoritative for the routed book — see the docstring
            try:
                led = json.loads((data / "live_book.json").read_text()).get("ledger") or {}
                marks = led.get("marks") or {}
                n_pos = sum(1 for m in marks.values() if (m.get("qty") or 0) != 0)
                source = "live_book.json (BookLedger)"
            except (OSError, json.JSONDecodeError):
                pass
        out[label] = {
            "equity": eq, "cash": cash, "positions": n_pos,
            "positions_source": source,
            # MARGINED BOOKS DO NOT SPEND CASH. On the 1x futures accounts a
            # position is collateralised, not paid for, so wallet cash stays
            # whole and cash/equity reads ~100% on a fully deployed book. That
            # is the §4.36 accounting trap wearing a different hat: reporting it
            # as "idle" would have said the crypto book was still frozen minutes
            # after it bought its entire mandate. Only meaningful where cash is
            # actually consumed by a position.
            "idle_pct": (round(100 * cash / eq, 1)
                         if (isinstance(eq, (int, float)) and eq
                             and isinstance(cash, (int, float))
                             and label not in _MARGINED_BOOKS)
                         else None),
            "cash_is_collateral": label in _MARGINED_BOOKS,
            "basis": d.get("basis", "(undeclared)"),
            "ts": d.get("ts"), "halted": d.get("halted"),
        }
    out["_order_flow"] = fills
    out["_note"] = ("positions 0 AND no recent fill = a frozen book; check the "
                    "trade floors (§4.41). idle_pct is null for margined books "
                    "because their cash is collateral, not spending money.")
    return out


SECTIONS = {
    "counting_unit": counting_unit,
    "directional": directional_record,
    "symbols": symbol_record,
    "events": event_record,
    "graph": graph_resolution,
    "learning": learning_loops,
    "reach": reach,
    "books": books,
    "pnl": pnl_significance,
}
_NEEDS_HORIZON = {"directional", "symbols", "reach", "pnl"}


# --------------------------------------------------------------- rendering --
def _render(name: str, payload) -> None:
    print(f"\n\033[1m{'=' * 74}\n{name.upper()}\n{'=' * 74}\033[0m")
    print(json.dumps(payload, indent=1, default=str))


def _snapshot(s, report: dict) -> None:
    """Append the handful of numbers worth a TIME SERIES.

    A single audit says where the brain is. A series says which way it is
    going, which is the question every one of these numbers actually raises —
    is resolution improving as wiring is curated? is llm share still climbing
    under the budget? did the learning loops ever start? Today those questions
    can only be answered by finding an old review and trusting its arithmetic,
    which is precisely what went wrong (§4.37).

    Deliberately compact: a dozen scalars, not the whole report. A history file
    nobody can skim is a history file nobody reads.
    """
    def sec(name: str) -> dict:
        """A section that was not run (or failed) contributes nulls, never a
        crash -- --snapshot must survive `--section` being narrowed."""
        v = report.get(name)
        return v if isinstance(v, dict) else {}

    g, c, lrn = sec("graph"), sec("counting_unit"), sec("learning")
    row = {
        "ts": report.get("generated"),
        "nodes": g.get("nodes"), "edges": g.get("edges"),
        "llm_share_pct": g.get("llm_share_pct"),
        "llm_last_7d": g.get("llm_proposed_last_7d"),
        "resolution_pct": g.get("resolution_pct"),
        "inert_assets": g.get("inert_assets"),
        "duplicate_assets": g.get("assets_duplicating_a_peer"),
        "observations": c.get("observations"),
        "replication": c.get("replication"),
        "counting_unit_ok": c.get("label_agrees"),
        "formula_alive": (lrn.get("formula") or {}).get("alive"),
        "calibrator_alive": (lrn.get("edge_calibration") or {}).get("alive"),
        "calibrator_gain_saturated": (lrn.get("edge_calibration") or {}).get("gain_saturated"),
        "reliability_pinned_pct": (lrn.get("reliability") or {}).get("pinned_pct"),
        "gate_eligible": (lrn.get("adviser_gate") or {}).get("eligible"),
        "long_conv": sec("directional").get("long/conv=1"),
    }
    path = Path(s.brain.db_path).parent / "brain_audit_history.jsonl"
    try:
        with open(path, "a") as fh:
            fh.write(json.dumps(row, default=str) + "\n")
        print(f"  snapshot appended to {path}")
    except OSError as exc:
        print(f"  (snapshot failed: {exc})")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="audit the brain — read-only, no market calls")
    ap.add_argument("--json", action="store_true", help="machine-readable, all sections")
    ap.add_argument("--section", choices=sorted(SECTIONS), action="append",
                    help="run only this section (repeatable)")
    ap.add_argument("--horizon", type=int, default=None,
                    help="forward-return horizon in days (default: the scorecard's)")
    ap.add_argument("--snapshot", action="store_true",
                    help="append a compact record to data/brain_audit_history.jsonl")
    args = ap.parse_args(argv)

    from ai_investing.brain.scorecard import HORIZON_DAYS
    from ai_investing.config import Settings
    settings = Settings()
    horizon = args.horizon or HORIZON_DAYS

    wanted = args.section or list(SECTIONS)
    # NOTE the key names: metadata must not collide with a SECTION name.
    # `graph` did, so `report["graph"]` was the graph's file path whenever the
    # graph section had not been run -- and --snapshot then tried to read
    # `.get("nodes")` off a string.
    report = {"generated": datetime.now(timezone.utc).isoformat(),
              "horizon_days": horizon,
              "brain_db_path": settings.brain.db_path,
              "graph_path": settings.brain.graph_path}
    for name in wanted:
        fn = SECTIONS[name]
        try:
            report[name] = fn(settings, horizon) if name in _NEEDS_HORIZON else fn(settings)
        except Exception as exc:      # one broken section must not hide the rest
            report[name] = {"error": f"{type(exc).__name__}: {exc}"}

    if args.snapshot:
        _snapshot(settings, report)

    if args.json:
        print(json.dumps(report, indent=1, default=str))
        return 0

    print(f"\nbrain audit — {report['generated']}")
    print(f"  {settings.brain.db_path}")
    print(f"  horizon {horizon}d; every hit-rate below is one observation per "
          f"(symbol, day)")
    for name in wanted:
        _render(name, report[name])

    print(f"\n\033[1m{'=' * 74}\nHOW TO READ THIS\n{'=' * 74}\033[0m")
    print("""
  counting_unit  `replication` is rows per real observation. It is ~65 by
                 construction (advice is re-logged every cycle) and that is
                 FINE — what matters is that `label_agrees` is true, i.e. every
                 statistic above counted observations. If it goes false, some
                 write path is bypassing the rule.

  directional    `p` is the raw binomial p-value; `p_effective` is the one to
                 quote. Daily samples of a 5-day forward return share 4/5 of
                 their window, so `n_effective` = n/5 independent bets. The GAP
                 between p and p_effective is itself the finding.

  symbols        Both lists matter, and they are printed at the same bar.
                 `significantly_wrong` being long, and mostly bearish calls,
                 was the 2026-08-21 finding three instruments agreed on. A
                 track record that reports only its winners is a brochure.

  events         The SECOND instrument, and independent of the advice record.
                 Two measurements agreeing is the only reason to believe
                 anything at this sample size. Read the +1 vs -1 asymmetry.

  graph          `resolution_pct` is how many distinct objects the graph can
                 tell apart, as a share of the assets it holds. Below ~50% most
                 "stock picks" are sector calls wearing a ticker.

  learning       Each loop reports `alive`. A loop that has never moved is not
                 a slow loop.

  reach          If hit-rate ranks INVERSELY with tradability, the constraint
                 is the venue, not the model.
""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
