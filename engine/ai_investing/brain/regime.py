"""Persistent macro regime state, market emotion, and the brain's own mood.

Three layers of "feeling", all quantified and persisted cycle to cycle:

1. Regime — what world are we in (risk appetite, rate trajectory, dollar trend,
   inflation trend, geopolitical tension, China stance). Derived from hard data
   (VIX, DXY, yields, FRED) plus the aggregate polarity of credible events. EMA
   smoothing gives it memory: one loud headline doesn't flip the worldview.
2. Market emotion — the crowd's state (fear/greed/euphoria/panic), read from the
   VIX plus the emotion tags on credible events. Extremes are contrarian
   information: euphoria is fragile, panic is opportunity.
3. Brain mood — the system's OWN emotional state: confidence (is my formula
   predicting well? is the regime stable?) and caution (drawdown, noise level,
   instability). Mood scales how hard the MacroLinkageSignal presses its views —
   a humble brain in a chaotic tape sizes down.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional

_EMA = 0.7  # weight on the previous state (memory); 0.3 on the new observation


def _ema(prev: float, new: float, w: float = _EMA) -> float:
    return round(w * prev + (1 - w) * new, 4)


def _label(value: float, neg: str, mid: str, pos: str, lo: float = -0.2, hi: float = 0.2) -> str:
    return neg if value < lo else (pos if value > hi else mid)


@dataclass
class MacroRegime:
    # continuous internal state in [-1, 1]; labels derived for humans
    risk_appetite: float = 0.0        # -1 risk-off .. +1 risk-on
    rate_trajectory: float = 0.0      # -1 easing .. +1 tightening
    dollar_trend: float = 0.0
    inflation_trend: float = 0.0
    china_stance: float = 0.0         # -1 crackdown/tightening .. +1 stimulus/support
    geopolitical_tension: float = 0.3  # 0..1
    stability: float = 0.7            # 0..1 — how close the field sits to its stable points
    fragility: float = 0.0            # 0..1 — portfolio exposure × concentration
    # market emotion (crowd)
    fear: float = 0.3                 # 0..1
    greed: float = 0.3                # 0..1
    emotion_label: str = "neutral"
    # brain's own mood
    mood_confidence: float = 0.5      # 0..1: formula predicting well + regime stable
    mood_caution: float = 0.3         # 0..1: drawdown + noise + instability
    mood_label: str = "measured"
    updated: str = ""
    inputs: dict = field(default_factory=dict)   # last hard readings, for the dashboard

    # -- persistence ---------------------------------------------------------
    @classmethod
    def load(cls, path: str) -> "MacroRegime":
        try:
            with open(path) as fh:
                d = json.load(fh)
            return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
        except (OSError, json.JSONDecodeError, TypeError):
            return cls()

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w") as fh:
            json.dump(self.to_dict(), fh, indent=2)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["labels"] = {
            "risk_appetite": _label(self.risk_appetite, "risk_off", "neutral", "risk_on"),
            "rate_trajectory": _label(self.rate_trajectory, "easing", "holding", "tightening"),
            "dollar_trend": _label(self.dollar_trend, "weakening", "stable", "strengthening"),
            "inflation_trend": _label(self.inflation_trend, "cooling", "stable", "heating"),
            "china_stance": _label(self.china_stance, "tightening", "mixed", "supportive"),
        }
        return d

    # -- the update (called every cycle) --------------------------------------
    def update(self, macro: Optional[dict], events: list[dict],
               performance: Optional[dict] = None) -> None:
        """Blend hard data (macro snapshot), credible events, and own performance."""
        macro = macro or {}
        self.inputs = {k: v for k, v in macro.items() if v is not None}

        # --- hard data first ---
        vix = macro.get("vix")
        if vix is not None:
            # VIX 15 -> +0.4 risk-on; 25 -> -0.4; 35+ -> deep risk-off
            self.risk_appetite = _ema(self.risk_appetite, max(-1.0, min(1.0, (20.0 - vix) / 12.5)))
            self.fear = _ema(self.fear, max(0.0, min(1.0, (vix - 12.0) / 25.0)))
        if macro.get("tnx_chg_20d") is not None:
            self.rate_trajectory = _ema(self.rate_trajectory,
                                        max(-1.0, min(1.0, macro["tnx_chg_20d"] * 12)))
        if macro.get("dxy_chg_20d") is not None:
            self.dollar_trend = _ema(self.dollar_trend,
                                     max(-1.0, min(1.0, macro["dxy_chg_20d"] * 25)))
        if macro.get("cpi_yoy") is not None:
            self.inflation_trend = _ema(self.inflation_trend,
                                        max(-1.0, min(1.0, (macro["cpi_yoy"] - 2.0) / 2.0)))

        # --- credible events nudge the softer dials ---
        signal_events = [e for e in events if not e.get("is_noise")]
        geo = [e["impulse"] for e in signal_events
               if "geopolitical_tension" in e.get("nodes", []) or e.get("type") == "geopolitics"]
        if geo:
            self.geopolitical_tension = _ema(
                self.geopolitical_tension,
                max(0.0, min(1.0, self.geopolitical_tension + sum(geo) / len(geo))))
        china = [e["impulse"] for e in signal_events
                 if any(n.startswith("china_") or n == "pboc_rate" for n in e.get("nodes", []))]
        if china:
            self.china_stance = _ema(self.china_stance,
                                     max(-1.0, min(1.0, sum(china) / len(china) * 2)))

        # --- crowd emotion from event tags + VIX ---
        greedy = [e["emotion_intensity"] for e in signal_events
                  if e.get("emotion") in ("greed", "euphoria", "complacency")]
        fearful = [e["emotion_intensity"] for e in signal_events
                   if e.get("emotion") in ("fear", "panic")]
        if greedy:
            self.greed = _ema(self.greed, min(1.0, sum(greedy) / len(greedy) + 0.2))
        if fearful:
            self.fear = _ema(self.fear, min(1.0, max(self.fear, sum(fearful) / len(fearful) + 0.2)))
        if self.fear > 0.7:
            self.emotion_label = "panic" if self.fear > 0.85 else "fear"
        elif self.greed > 0.7:
            self.emotion_label = "euphoria" if self.greed > 0.85 else "greed"
        elif self.fear < 0.25 and self.greed < 0.35:
            self.emotion_label = "complacency"
        else:
            self.emotion_label = "neutral"

        # --- stability: how far the dials sit from their stable points ---
        shock = sum(abs(e["impulse"]) for e in signal_events)
        displacement = (abs(self.risk_appetite) * 0.3 + self.geopolitical_tension * 0.3
                        + abs(self.inflation_trend) * 0.2 + min(1.0, shock) * 0.2)
        self.stability = _ema(self.stability, max(0.0, min(1.0, 1.0 - displacement)))

        # --- the brain's own mood ---
        perf = performance or {}
        pred_quality = perf.get("prediction_quality")   # 0..1 or None
        drawdown = perf.get("drawdown", 0.0)            # 0..1 fraction from peak
        if perf.get("fragility") is not None:
            self.fragility = float(perf["fragility"])
        noise_ratio = (sum(1 for e in events if e.get("is_noise")) / len(events)) if events else 0.0
        conf_obs = 0.5
        if pred_quality is not None:
            conf_obs = 0.6 * pred_quality + 0.4 * self.stability
        else:
            conf_obs = 0.5 * self.stability + 0.25
        self.mood_confidence = _ema(self.mood_confidence, max(0.0, min(1.0, conf_obs)))
        # fragility (exposure × concentration): a fragile book in an unstable
        # field is exactly when the brain should press its views most softly
        caution_obs = min(1.0, drawdown * 4 + (1 - self.stability) * 0.4
                          + noise_ratio * 0.3 + self.fragility * 0.3)
        self.mood_caution = _ema(self.mood_caution, caution_obs)
        if self.mood_caution > 0.65:
            self.mood_label = "defensive"
        elif self.mood_caution > 0.45:
            self.mood_label = "wary"
        elif self.mood_confidence > 0.65:
            self.mood_label = "assured"
        else:
            self.mood_label = "measured"

        self.updated = datetime.now(timezone.utc).isoformat()

    def conviction_multiplier(self) -> float:
        """How hard the brain lets its macro views press into position sizing.
        Confident + calm ≈ 1.0; cautious/unstable shrinks toward 0.4."""
        m = 0.4 + 0.6 * self.mood_confidence * (1.0 - 0.7 * self.mood_caution)
        return round(max(0.3, min(1.0, m)), 3)
