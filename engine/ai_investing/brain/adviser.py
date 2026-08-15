"""The Adviser: turn the brain's field into a ranked, explained trade list.

    score(asset) = field impact reaching the asset (persistent activations)
                 + latest formula conviction (state.json decisions, if present)
                 + fired-scenario boosts (last 48h)
                 + regime fit (risk-off tilts defensives up, high-beta down)
                 − crowding/hype penalty (noise events touching the asset's wiring)
    all × the brain's mood conviction multiplier.

Every recommendation carries its CAUSAL CHAIN — the strongest activated path
through the graph into the asset — plus what would invalidate it and how fresh
the driving events are. No LLM calls: this is pure graph + arithmetic, so it
runs every cycle for free.

Honest framing: this is decision support feeding your views, not an autonomous
trader. Orders still flow through the formula, risk caps, and safety stack, and
every list is frozen in advice_log so the adviser's hit-rate can be measured.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

DEFENSIVE = {"GLD", "XLP", "TLT"}
HIGH_BETA = {"BTC/USD", "ETH/USD", "SOL/USD", "XLK", "NVDA", "TSLA"}

# Confirmed-miscalibrated, formula-only symbols (SCORECARD_REVIEW_2026-08-15).
# UNI/USD: n=1,096 graded long calls, hit-rate 6.3%, avg excess -7.1%, and it
# got WORSE (not better) as the sample grew from n=636 three days earlier.
# Zeroed here rather than dropped from the watchlist, so it still gets a
# `no_view` row and price data keeps flowing.
#
# Removal has TWO conditions, per the original note. ONE is now met (seed v38,
# 2026-08-15): `uni` is a real graph node (member_of crypto_majors), so every
# general-purpose haircut below (crowding, priced-in, integrity, froth) now
# applies to it like any other coin, instead of nothing correcting a bad
# formula read. STILL WAITING: calibration.py needs n>=20 realised-return
# observations on the new `uni -> crypto_majors` edge before it can issue a
# verdict -- that takes real elapsed time to accumulate and can't be
# shortcut, so this override stays in place until it does. Do not remove on
# the graph-node condition alone.
CONFIRMED_MISCALIBRATED = {"UNI/USD"}

W_FIELD, W_FORMULA, W_SCENARIO, W_REGIME, W_CROWD = 1.0, 0.6, 0.5, 0.25, 0.6
W_CONTRA, W_BENEF = 0.45, 0.3
CAMPAIGN_HAIRCUT = 0.6         # long score x (1 - this x pressure) on campaigned names
MIN_SCORE = 0.03


_SUFFIX_MARKET = {"HK": "HK", "SI": "SG", "SS": "CN", "SZ": "CN", "T": "JP",
                  "KS": "KR", "TW": "TW", "PA": "EU", "DE": "EU", "AS": "EU",
                  "L": "EU", "SW": "EU"}


def _market_of(symbol: str) -> str:
    """Market for a candidate the graph has no node for, so the scorecard can pick
    the right benchmark. Ticker suffix is the only thing available here."""
    if "/" in symbol:
        return "CRYPTO"
    if "." in symbol:
        return _SUFFIX_MARKET.get(symbol.rsplit(".", 1)[-1].upper(), "US")
    return "US"


def _formula_views(settings) -> dict[str, float]:
    """Latest per-symbol conviction from the engine's last cycle (θ·φ squashed)."""
    try:
        with open(settings.state_path) as fh:
            decisions = json.load(fh).get("decisions", [])
        return {d["symbol"].upper(): float(d.get("score", 0.0)) for d in decisions}
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return {}


def _scenario_boosts(brain, now: datetime) -> dict[str, float]:
    boosts: dict[str, float] = {}
    cutoff = (now - timedelta(hours=48)).isoformat()
    for sc in brain.scenarios.scenarios:
        if (sc.get("last_fired") or "") < cutoff:
            continue
        for sym, tilt in (sc.get("assets") or {}).items():
            boosts[sym.upper()] = boosts.get(sym.upper(), 0.0) + tilt
    return boosts


def _crowding(brain, hours: float = 48.0) -> dict[str, float]:
    """Noise pressure per node: how much manipulation-flagged flow touched the
    wiring recently. An asset pumped by noise gets its LONG score haircut."""
    pressure: dict[str, float] = {}
    try:
        noisy = [e for e in brain.store.recent_events(hours, signal_only=False)
                 if e.get("is_noise")]
    except Exception:
        return pressure
    for e in noisy:
        for n in e.get("nodes", []):
            pressure[n] = pressure.get(n, 0.0) + abs(e.get("magnitude", 0.0)) * 0.5
    return pressure


def _chain(graph, activations: dict[str, float], asset_node: str, depth: int = 3) -> list[str]:
    """Greedy strongest activated path INTO the asset — the human-readable 'why'."""
    adj = graph._adjacency()
    incoming: dict[str, list] = {}
    for src, nbrs in adj.items():
        for dst, sign, w, edge in nbrs:
            incoming.setdefault(dst, []).append((src, sign, w))
    path, cur, seen = [], asset_node, {asset_node}
    for _ in range(depth):
        cands = [(src, sign, w, abs(activations.get(src, 0.0)) * w)
                 for src, sign, w in incoming.get(cur, []) if src not in seen]
        if not cands:
            break
        src, sign, w, strength = max(cands, key=lambda c: c[3])
        if strength < 0.01:
            break
        path.append(src)
        seen.add(src)
        cur = src
    path.reverse()
    labels = []
    for nid in path + [asset_node]:
        n = graph.nodes.get(nid)
        a = activations.get(nid, 0.0)
        arrow = "↑" if a > 0.01 else ("↓" if a < -0.01 else "")
        labels.append(f"{n.label if n else nid} {arrow}".strip())
    return labels


def advise(settings, brain, log: bool = True) -> dict:
    """Rank the top-N trades from the current field. Pure computation, no LLM."""
    now = datetime.now(timezone.utc)
    graph, field = brain.graph, brain.field
    activations = field.activations
    asset_impacts = graph.asset_impacts(activations)
    # scale + priced-in: impacts become expected moves; signals the tape already
    # ran on get discounted before they can become conviction
    try:
        from ai_investing.brain.priced_in import priced_in_scores
        from ai_investing.brain.scale import enrich_with_scale
        vols = enrich_with_scale(asset_impacts, settings, graph)
        priced_in = priced_in_scores(settings, asset_impacts, vols)
    except Exception:
        vols, priced_in = {}, {}
    formula = _formula_views(settings)
    boosts = _scenario_boosts(brain, now)
    crowding = _crowding(brain)
    mood_mult = brain.regime.conviction_multiplier()
    risk_off = brain.regime.risk_appetite < -0.2
    risk_on = brain.regime.risk_appetite > 0.2
    # circular-financing haircut: revenue booked around an owns+supplies loop is
    # partly the same dollar twice — never take that growth story at face value
    in_loop: set[str] = set()
    for loop in graph.detect_circular_financing():
        in_loop.update(loop.get("participants") or [loop["investor"], loop["counterparty"]])
    try:
        from ai_investing.brain.integrity import current_flags
        integrity_flags = current_flags(settings)
    except Exception:
        integrity_flags = {}

    # learned trust: symbols where past field-driven calls kept missing get
    # listened to less (scorecard EMA, r ∈ [0.5, 1.4]); bubble froth haircuts longs
    from ai_investing.brain.scorecard import reliability_weights
    from ai_investing.brain.bubble import bubble_scores
    rel = reliability_weights(settings)
    try:
        froth = bubble_scores(settings).get("symbols", {})
    except Exception:
        froth = {}

    # the offense: contrarian buy/fade lists, fraud-beneficiary tilts, and the
    # campaign-pressure index (all precomputed by the brain cycle; pure reads)
    try:
        from ai_investing.brain.contrarian import load as load_contrarian
        contra = load_contrarian(settings)
    except Exception:
        contra = {}
    contra_buy = {r["symbol"]: r["score"] for r in contra.get("buys", [])}
    contra_fade = {r["symbol"]: r["score"] for r in contra.get("fades", [])}
    beneficiaries = {s: v["benefit"] for s, v in (contra.get("beneficiaries") or {}).items()}
    try:
        from ai_investing.brain.campaign import load as load_campaigns
        campaign_pressure = {v["symbol"]: v["pressure"]
                             for v in load_campaigns(settings).values() if v.get("symbol")}
    except Exception:
        campaign_pressure = {}

    rows: list[dict] = []
    no_view: list[str] = []
    symbols = (set(asset_impacts) | set(boosts) | set(formula)
               | set(contra_buy) | set(contra_fade) | set(beneficiaries))
    # Symbols the engine actually watches but the causal graph has no node for.
    # Without this the universe was whatever the graph happened to name, which is
    # why every one of the 95 considered names was a stock and crypto never
    # appeared in a single advice list: at the time this was written, only
    # BTC/USD, ETH/USD and SOL/USD had graph nodes at all (seed v21, 2026-07-31,
    # added the other 13 coins — CRYPTO_WATCHLIST just hadn't caught up to them
    # until seed v36). Symbols still watched but genuinely nodeless are scored
    # on the formula/technical leg only — no causal chain to show, and their
    # `chain` says so honestly.
    watched = set(settings.stock_watchlist) | set(settings.crypto_watchlist)
    symbols |= {s for s in watched if s in formula}

    for sym in symbols:
        node = graph.node_for_symbol(sym)
        if node is not None and node.type != "asset":
            continue
        if node is None and sym not in watched:
            continue
        if sym in CONFIRMED_MISCALIBRATED:
            if sym in watched:
                no_view.append(sym)
            continue
        impact = asset_impacts.get(sym, {}).get("impact", 0.0)
        pi = priced_in.get(sym, {}).get("priced_in", 0.0)
        impact_eff = impact * (1.0 - pi)   # the tape already ran? less signal left
        score = W_FIELD * impact_eff * rel.get(sym, 1.0)
        score += W_FORMULA * formula.get(sym, 0.0)
        score += W_SCENARIO * boosts.get(sym, 0.0)
        if risk_off:
            score += W_REGIME * (0.5 if sym in DEFENSIVE else (-0.5 if sym in HIGH_BETA else 0.0))
        elif risk_on:
            score += W_REGIME * (0.4 if sym in HIGH_BETA else 0.0)
        # contrarian offense: buy panic in clean value, fade euphoric froth,
        # tilt toward competitors of integrity-flagged names
        contra_net = (W_CONTRA * contra_buy.get(sym, 0.0)
                      - W_CONTRA * contra_fade.get(sym, 0.0)
                      + W_BENEF * beneficiaries.get(sym, 0.0))
        score += contra_net
        # campaign pressure: someone is paying to excite this name — a fresh
        # LONG must not take the bait (fade/short direction unaffected)
        camp_p = campaign_pressure.get(sym, 0.0)
        if score > 0 and camp_p > 0:
            score *= max(0.0, 1.0 - CAMPAIGN_HAIRCUT * camp_p)
        # crowding: never BUY what noise is pumping (short/fade is unaffected)
        # A graph-less candidate has no node id, so every graph-derived haircut
        # below simply does not apply to it. That is honest — there is no causal
        # chain to be crowded, circular or flagged — but it also means these names
        # skip protections the graph-backed ones get, which is why their `chain`
        # records "formula/technical only (no causal chain)".
        nid = node.id if node is not None else None
        crowd = sum(p for n, p in crowding.items()
                    if nid is not None
                    and (n == nid or any(e.src == nid and e.dst == n for e in graph.edges)))
        if score > 0 and crowd > 0:
            score -= W_CROWD * min(score, crowd)
        circular = nid is not None and nid in in_loop
        if circular and score > 0:
            score *= 0.6    # 40% haircut on long conviction inside a financing circle
        # integrity flags: never recommend a FRESH long on an asset whose books
        # are in doubt — the upside case rests on numbers that may be fake
        integ = integrity_flags.get(nid) if nid is not None else None
        if integ and score > 0:
            score *= max(0.0, 1.0 - 1.5 * integ["severity"])   # sev>=0.67 zeroes the long
        b = froth.get(sym, 0.0)
        if b >= 0.4 and score > 0:
            score *= max(0.4, 1.0 - 0.6 * b)   # don't chase what already smells like a bubble
        score *= mood_mult
        if abs(score) < MIN_SCORE:
            if sym in watched:
                no_view.append(sym)      # watched, considered, no opinion — say so
            continue
        chain = _chain(graph, activations, nid) if nid is not None else []
        root = chain[0] if len(chain) > 1 else None
        # size RISK, not conviction: the same score buys half the notional in a
        # 4%-a-day asset as in a 1% one (weight scaled by 2% reference vol)
        vol = vols.get(sym, 0.02)
        vol_norm = max(0.4, min(2.0, 0.02 / vol)) if vol else 1.0
        rows.append({
            "symbol": sym,
            "market": (node.market if node is not None
                       else ("CRYPTO" if "/" in sym else _market_of(sym))),
            "label": node.label if node is not None else sym,
            # ONE MEANING PER LABEL (2026-08-04). Was "short_or_avoid", which the
            # scorecard then graded as a prediction of a FALL — marking every
            # correct avoid in a rising market as a miss and dragging the measured
            # hit rate to 0.182. Nothing here shorts stocks (both paper venues
            # refuse it; shorts failed six tests in docs/research), so a negative
            # call means "expect this to LAG the market", and that is how it is
            # now graded. See scorecard.verdict.
            "direction": "long" if score > 0 else "avoid",
            "score": round(score, 4),
            "weight_suggestion": round(min(settings.risk.max_position_weight,
                                           abs(score) * 0.3 * vol_norm) * mood_mult, 4),
            "chain": (" → ".join(chain) if len(chain) > 1
                      else ("formula/technical only (no causal chain)" if nid is None
                            else "formula/scenario driven")),
            "invalidation": f"reversal of: {root}" if root else "formula conviction fading",
            "drivers": {"field": round(impact, 3), "formula": round(formula.get(sym, 0.0), 3),
                        "scenarios": round(boosts.get(sym, 0.0), 3),
                        "crowding_penalty": round(crowd, 3),
                        "priced_in": round(pi, 3),
                        **({"contrarian": round(contra_net, 3)} if contra_net else {}),
                        **({"campaign_pressure": round(camp_p, 3)} if camp_p else {})},
            **({"expected_move_pct": asset_impacts[sym]["expected_move_pct"]}
               if asset_impacts.get(sym, {}).get("expected_move_pct") is not None else {}),
            **({"vol_daily": round(vol, 4)} if vol else {}),
            **({"circular_financing": True} if circular else {}),
        })
    rows.sort(key=lambda r: -abs(r["score"]))
    # QUALITY FLOOR, not a quota: only ideas with real conviction are advised.
    # Some days that is zero — and saying so is honest, valuable advice.
    floor = settings.brain.advise_min_conviction
    n = settings.brain.advise_top_n
    top = [r for r in rows if abs(r["score"]) >= floor][:n]
    for i, r in enumerate(top, 1):
        r["rank"] = i
        r["conviction"] = True

    # COVERAGE, PER ASSET CLASS. `top` stays a pure conviction list — forcing
    # filler into it would corrupt the number that matters. But learning needs
    # data points on both sides of every market, so `watch` is topped up until
    # EACH class carries at least `n` graded calls between the two lists.
    #
    # Without a per-class quota crypto never appeared: one global ranking, and a
    # stock scores on three legs (field + formula + scenario) where a coin without
    # a graph node has only the formula. All 13 coins had live scores from -0.35 to
    # +0.34 and still lost every seat to stocks — invisible in `below_floor`, and
    # nothing to learn from.
    def _cls(r):
        return "crypto" if "/" in r["symbol"] else "stock"

    in_top = {id(r) for r in top}
    watch: list[dict] = []
    for cls in ("stock", "crypto"):
        have = sum(1 for r in top if _cls(r) == cls)
        # NOT `abs(score) < floor`. That was the first version and it lost the most
        # convinced calls of the minority class: a name can clear the conviction
        # floor and still be cut by the global top-n cap, and such a row then
        # matched neither list. Observed immediately — ETH, UNI and ATOM cleared
        # the floor, ranked below ten stocks, and vanished, so the quota delivered
        # 4 crypto instead of 7. Coverage means "everything not already advised",
        # ranked by conviction.
        pool = [r for r in rows if _cls(r) == cls and id(r) not in in_top]
        for r in pool[:max(0, n - have)]:
            r["conviction"] = False
            watch.append(r)
    watch.sort(key=lambda r: -abs(r["score"]))

    advice = {
        "ts": now.isoformat(),
        "trades": top,
        "watch": watch,          # considered + scored but below conviction — visible, not advised
        "considered": len(rows),
        "below_floor": len(rows) - len(top),
        # Watched names the model has NO directional view on: |score| under
        # MIN_SCORE, dropped before ranking. Reported rather than hidden, because
        # "10 names it thinks will rise or fall" has an honest answer of fewer than
        # 10 on a quiet day, and manufacturing a direction from a score of -0.001
        # produces a coin-flip that dilutes the record instead of teaching anything.
        # 6 of 13 coins sat here on 2026-08-04; that number moves with news flow.
        "no_view": sorted(no_view),
        "mood": brain.regime.mood_label,
        "conviction_multiplier": mood_mult,
        "regime_note": ("risk-off tilt: defensives favored" if risk_off
                        else "risk-on tilt: beta favored" if risk_on else "neutral regime"),
        **({"note": "no idea clears the conviction floor today — cash is a position"}
           if not top else {}),
    }
    try:
        os.makedirs(os.path.dirname(os.path.abspath(settings.brain.advice_path)), exist_ok=True)
        with open(settings.brain.advice_path, "w") as fh:
            json.dump(advice, fh, indent=1)
        if log and top:
            brain.store.log_advice(advice)
    except OSError:
        pass
    return advice
