"""Your input as a decisive factor in the decision formula.

The signals, news, and sentiment are blended by the model into `model_conviction`. This
layer lets YOU tilt it — per asset (bullish/bearish), and via your risk profile — and
controls how much your view overrides the model:

    w        = decisiveness × |your view|                 # effective override weight
    blend    = (1 − w) · model_conviction + w · your_view
    final    = blend × stance × risk_appetite             # your risk profile scales exposure

So a strong view with high decisiveness dominates (your call wins); no view means the
model runs untouched; and your risk appetite + stance scale how big it sizes. Loaded fresh
each cycle from `data/views.json`, so dashboard/CLI edits take effect live. Safety limits
(circuit breaker, caps) always override this.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

STANCE_MULT = {"aggressive": 1.3, "normal": 1.0, "cautious": 0.6, "defensive": 0.3, "cash": 0.0}


@dataclass
class UserViews:
    decisiveness: float = 0.7                        # how much your views override the model (0..1)
    risk_appetite: float = 0.5                       # 0..1 -> exposure ×0.4..×1.6 (within safety caps)
    stance: str = "normal"                           # aggressive|normal|cautious|defensive|cash
    views: dict = field(default_factory=dict)        # SYMBOL -> -1..+1 (bearish..bullish)
    blocklist: list = field(default_factory=list)    # never trade these
    focus: list = field(default_factory=list)        # if non-empty, ONLY trade these

    # -- persistence --------------------------------------------------------
    @classmethod
    def load(cls, path: str) -> "UserViews":
        try:
            with open(path) as fh:
                d = json.load(fh)
            return cls(
                decisiveness=max(0.0, min(1.0, float(d.get("decisiveness", 0.7)))),
                risk_appetite=max(0.0, min(1.0, float(d.get("risk_appetite", 0.5)))),
                stance=str(d.get("stance", "normal")).lower(),
                views={str(k).upper(): max(-1.0, min(1.0, float(v)))
                       for k, v in (d.get("views") or {}).items()},
                blocklist=[str(s).upper() for s in (d.get("blocklist") or [])],
                focus=[str(s).upper() for s in (d.get("focus") or [])],
            )
        except (OSError, json.JSONDecodeError, ValueError, TypeError):
            return cls()

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w") as fh:
            json.dump(self.to_dict(), fh, indent=2)

    def to_dict(self) -> dict:
        return {"decisiveness": self.decisiveness, "risk_appetite": self.risk_appetite,
                "stance": self.stance, "views": self.views,
                "blocklist": self.blocklist, "focus": self.focus}

    # -- queries ------------------------------------------------------------
    def view_for(self, symbol: str):
        return self.views.get(symbol.upper())

    def is_allowed(self, symbol: str) -> bool:
        s = symbol.upper()
        if s in self.blocklist:
            return False
        return not self.focus or s in self.focus

    def stance_multiplier(self) -> float:
        return STANCE_MULT.get(self.stance, 1.0)

    def appetite_multiplier(self) -> float:
        return 0.4 + 1.2 * max(0.0, min(1.0, self.risk_appetite))

    def exposure_multiplier(self) -> float:
        return self.stance_multiplier() * self.appetite_multiplier()

    # -- the tilt -----------------------------------------------------------
    def apply(self, symbol: str, model_conviction: float) -> float:
        v = self.view_for(symbol)
        blended = model_conviction
        if v is not None:
            w = max(0.0, min(1.0, self.decisiveness)) * abs(v)
            blended = (1 - w) * model_conviction + w * v
        return max(-1.0, min(1.0, blended * self.exposure_multiplier()))
