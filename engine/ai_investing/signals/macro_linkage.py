from __future__ import annotations

from typing import Optional

from ai_investing.models import Asset, Bar, SignalDirection, SignalResult
from ai_investing.signals.base import Signal


class MacroLinkageSignal(Signal):
    """Turns the brain's propagated macro view into a per-asset signal.

    The runner precomputes `context["brain"]` once per cycle (see brain/core.py):
    credible events shock graph nodes, the shock ripples through the relationship
    graph, and `asset_impacts` is the per-symbol residue — including assets never
    named in any headline. Fired scenarios are already folded in.

    The brain's own mood scales confidence: a wary brain in an unstable regime
    presses its macro views more softly. Like every other signal, this one earns
    its formula weight through the same walk-forward discipline — it gets no
    special treatment just because it sounds sophisticated.
    """

    name = "macro_linkage"

    def evaluate(self, asset: Asset, bars: list[Bar], context: Optional[dict] = None) -> SignalResult:
        brain = (context or {}).get("brain") or {}
        impacts = brain.get("asset_impacts") or {}
        entry = impacts.get(asset.symbol.upper())
        if entry is None:
            # Longbridge-style symbols (700.HK, D05.SG) vs canonical (0700.HK, D05.SI):
            # fall back to a bare-ticker match.
            bare = asset.symbol.split(".")[0].lstrip("0").upper()
            for sym, e in impacts.items():
                if sym.split(".")[0].lstrip("0").upper() == bare and bare:
                    entry = e
                    break
        if not entry or not entry.get("impact"):
            return SignalResult(self.name, SignalDirection.FLAT, 0.0, 0.0, "no macro linkage")

        impact = max(-1.0, min(1.0, float(entry["impact"])))
        mood_mult = float(brain.get("conviction_multiplier", 1.0))
        confidence = min(1.0, abs(impact) * 1.5) * mood_mult
        if impact > 0.05:
            direction = SignalDirection.LONG
        elif impact < -0.05:
            direction = SignalDirection.SHORT
        else:
            direction = SignalDirection.FLAT

        why = f"graph impact {impact:+.2f}"
        if entry.get("scenarios"):
            why += f" (scenarios: {', '.join(entry['scenarios'])})"
        regime = brain.get("regime") or {}
        if regime.get("mood_label"):
            why += f" [brain {regime['mood_label']}]"
        return SignalResult(self.name, direction, impact, round(confidence, 3), why,
                            {"impact": impact, "node": entry.get("node", ""),
                             "scenarios": entry.get("scenarios", []),
                             "mood_multiplier": mood_mult})
