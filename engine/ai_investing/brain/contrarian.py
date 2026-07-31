"""The contrarian composer: turn detected emotion and manipulation into trades.

Every detector in this system used to end in abstention — noise didn't
propagate, flagged assets didn't get bought, froth haircut longs. This module
is the OFFENSE. It composes four existing layers into two lists and one map:

BUY (panic in clean value):        fear high on the node or its themes
                                   x integrity clean (books not in doubt)
                                   x not inside a financing circle
                                   x value case (value_scanner, or deep
                                     capitulation in the field as fallback)
                                   x stabilization gate — the knife has hit the
                                     floor (last move not still cascading);
                                     candidates still falling are listed as
                                     WATCHING with zero boost, not bought
FADE (euphoria in froth):          greed high x (bubble froth | circularity |
                                   campaign pressure) — and if a pump lifecycle
                                   stage is known, ONLY in the dump phase.
                                   Never fade a pump that is still working.
BENEFICIARIES (fraud routing):     an integrity flag on X is a tailwind for
                                   X's competes_with neighbors (Luckin's fraud
                                   was Starbucks China's market share) — tilt
                                   competitors positive, scaled by severity.

Both directions are scaled by MEASURED emotion coefficients
(brain/emotion_calibration.py): honest priors until this system's own history
proves panic overshoots and euphoria mean-reverts. Output: data/contrarian.json,
consumed by the adviser as scored boosts, visible in the daily overview.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from ai_investing.brain.emotion_field import asset_emotion, membership_parents
from ai_investing.brain.scale import price_series, prior_vol, realized_daily_vol

FEAR_MIN = 0.45
GREED_MIN = 0.45
INTEGRITY_CLEAN = 0.15         # flagged above this = books in doubt = never a buy
FROTH_MIN = 0.40
PRESSURE_MIN = 0.40
CAPITULATION = -0.25           # value fallback: field activation this deep = washed out
BENEFIT_SEV_MIN = 0.30
MAX_ROWS = 12


def _path(settings) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(settings.brain.db_path)),
                        "contrarian.json")


def _stabilized(prices: list[float], vol: float) -> bool | None:
    """Has the falling knife hit the floor? None = not enough data to say."""
    if len(prices) < 2:
        return None
    last = prices[-1] / prices[-2] - 1.0
    return last >= -0.5 * vol


def compose(settings, graph, activations: dict[str, float],
            emotions: dict[str, dict], campaigns: dict[str, dict]) -> dict:
    """Build buy/fade/beneficiary lists from the current field. Pure reads."""
    from ai_investing.brain.emotion_calibration import coefficients
    coefs = coefficients(settings)
    try:
        from ai_investing.brain.integrity import current_flags
        flags = current_flags(settings)
    except Exception:
        flags = {}
    in_loop: set[str] = set()
    try:
        for lp in graph.detect_circular_financing():
            in_loop.update(lp.get("participants") or [])
    except Exception:
        pass
    try:
        from ai_investing.brain.bubble import bubble_scores
        froth = bubble_scores(settings).get("symbols", {})
    except Exception:
        froth = {}
    value_scores: dict[str, dict] = {}
    try:
        from ai_investing.data.value_scanner import stock_value_scores
        value_scores = stock_value_scores(settings)
    except Exception:
        pass
    series = price_series(settings)
    parents = membership_parents(graph)

    buys, watching, fades = [], [], []
    for nid, node in graph.nodes.items():
        if node.type != "asset" or not node.symbol:
            continue
        sym = node.symbol.upper()
        emo = asset_emotion(graph, emotions, nid, parents)
        fear, greed = emo["fear"], emo["greed"]
        camp = campaigns.get(nid, {})
        pressure = float(camp.get("pressure", 0.0))
        sev = flags.get(nid, {}).get("severity", 0.0)

        # ---- BUY: panic in clean value ----
        if fear >= FEAR_MIN and coefs["panic_rebound"] > 0:
            if sev >= INTEGRITY_CLEAN or nid in in_loop or pressure >= PRESSURE_MIN:
                pass                       # scared AND suspect = just scared
            else:
                vs = value_scores.get(sym, {}).get("score", 0.0)
                capitulated = activations.get(nid, 0.0) <= CAPITULATION
                if vs > 0 or capitulated:
                    vol = (realized_daily_vol(series.get(sym, []))
                           or prior_vol(node))
                    stab = _stabilized(series.get(sym, []), vol)
                    value_strength = min(1.0, max(vs, 0.4 if capitulated else 0.0))
                    score = round(coefs["panic_rebound"] * fear
                                  * (0.6 + 0.4 * value_strength), 4)
                    why = (f"fear {fear:.2f}, books clean, "
                           + (f"value {vs:.2f}" if vs > 0 else "capitulation-deep field"))
                    row = {"symbol": sym, "node": nid, "label": node.label,
                           "score": score, "fear": fear, "why": why}
                    if stab:
                        buys.append(row)
                    else:
                        row["why"] += " — still falling, no bid yet" if stab is False \
                            else " — no price data for stabilization gate"
                        watching.append(row)

        # ---- FADE: euphoria in froth (only where the pump has cracked) ----
        if greed >= GREED_MIN and coefs["euphoria_fade"] < 0:
            fr = froth.get(sym, 0.0)
            reasons = []
            if fr >= FROTH_MIN:
                reasons.append(f"froth {fr:.2f}")
            if nid in in_loop:
                reasons.append("circular financing")
            if pressure >= PRESSURE_MIN:
                reasons.append(f"campaign pressure {pressure:.2f}")
            if reasons:
                phase = camp.get("phase")
                if phase and not camp.get("fade_ok"):
                    continue               # pump still working — never fade into it
                strength = max(fr, pressure, 0.5 if nid in in_loop else 0.0)
                fades.append({"symbol": sym, "node": nid, "label": node.label,
                              "score": round(abs(coefs["euphoria_fade"]) * greed
                                             * strength, 4),
                              "greed": greed, "why": ", ".join(reasons)
                              + (f", phase {phase}" if phase else "")})

    # ---- BENEFICIARIES: a fraud flag on X is a tailwind for X's competitors ----
    beneficiaries: dict[str, dict] = {}
    for nid, f in flags.items():
        sev = f.get("severity", 0.0)
        if sev < BENEFIT_SEV_MIN:
            continue
        for e in graph.edges:
            if e.type != "competes_with" or nid not in (e.src, e.dst):
                continue
            other = e.dst if e.src == nid else e.src
            n2 = graph.nodes.get(other)
            if (n2 is None or n2.type != "asset" or not n2.symbol
                    or flags.get(other, {}).get("severity", 0.0) >= INTEGRITY_CLEAN
                    or other in in_loop):
                continue
            benefit = round(min(0.5, 0.4 * sev * max(0.0, min(1.0, e.weight))), 4)
            sym2 = n2.symbol.upper()
            if benefit > beneficiaries.get(sym2, {}).get("benefit", 0.0):
                flagged_label = graph.nodes[nid].label if nid in graph.nodes else nid
                beneficiaries[sym2] = {"benefit": benefit, "node": other,
                                       "why": f"competitor {flagged_label} "
                                              f"integrity-flagged ({sev:.2f})"}

    buys.sort(key=lambda r: -r["score"])
    fades.sort(key=lambda r: -r["score"])
    report = {"ts": datetime.now(timezone.utc).isoformat(),
              "coefficients": coefs,
              "buys": buys[:MAX_ROWS], "watching": watching[:MAX_ROWS],
              "fades": fades[:MAX_ROWS], "beneficiaries": beneficiaries}
    try:
        os.makedirs(os.path.dirname(_path(settings)), exist_ok=True)
        with open(_path(settings), "w") as fh:
            json.dump(report, fh, indent=1)
    except OSError:
        pass
    return report


def load(settings) -> dict:
    try:
        with open(_path(settings)) as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}
