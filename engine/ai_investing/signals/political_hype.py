from __future__ import annotations

from typing import Optional

from ai_investing.models import Asset, Bar, SignalDirection, SignalResult
from ai_investing.signals.base import Signal


class PoliticalHypeSignal(Signal):
    """The anti-manipulation signal.

    Detects hype-driven pumps -- a sharp price + volume spike, especially when it
    coincides with promotional or political news (a president/official talking an
    asset or sector up, a meme-coin launch) -- and *fades* them. History says these
    spikes tend to revert, so the signal returns a NEGATIVE score (short / avoid),
    scaled by how violent the pump and how loud the hype.

    Price/volume spike is computed from bars here. The hype flags come from the news
    module, which asks Claude to classify headlines as promotional/political and rate
    their intensity; the runner puts them in `context["hype_flags"][symbol]`.
    """

    name = "political_hype"

    def __init__(self, spike_window: int = 3, spike_threshold: float = 0.12, vol_mult: float = 2.0):
        self.spike_window = spike_window
        self.spike_threshold = spike_threshold
        self.vol_mult = vol_mult

    def evaluate(self, asset: Asset, bars: list[Bar], context: Optional[dict] = None) -> SignalResult:
        hype = (context or {}).get("hype_flags", {}).get(asset.symbol, {})
        if len(bars) < self.spike_window + 21:
            return SignalResult(self.name, SignalDirection.FLAT, 0.0, 0.0, "insufficient history")

        closes = [b.close for b in bars]
        vols = [b.volume for b in bars]
        base = closes[-1 - self.spike_window]
        recent_ret = (closes[-1] - base) / base if base else 0.0
        prior_vol = vols[-21:-1]
        avg_vol = sum(prior_vol) / len(prior_vol) if prior_vol else 0.0
        vol_spike = (vols[-1] / avg_vol) if avg_vol else 1.0

        promotional = bool(hype.get("promotional"))
        political = bool(hype.get("political"))
        intensity = max(0.0, min(1.0, float(hype.get("intensity", 0.0))))
        hype_flag = promotional or political

        pump = recent_ret >= self.spike_threshold and vol_spike >= self.vol_mult
        if not (pump or hype_flag):
            return SignalResult(self.name, SignalDirection.FLAT, 0.0, 0.0,
                                f"no hype/pump (ret {recent_ret * 100:+.1f}%, vol x{vol_spike:.1f})")

        price_strength = min(1.0, recent_ret / self.spike_threshold) if recent_ret > 0 else 0.0
        strength = min(1.0, 0.5 * price_strength + 0.5 * intensity)
        score = -max(0.15, strength)  # always at least a mild fade once triggered
        conf = min(1.0, 0.4 + 0.6 * intensity) if hype_flag else min(1.0, price_strength)

        tags = [t for t, on in (("promotional", promotional), ("political", political)) if on]
        reason = f"pump {recent_ret * 100:+.1f}% on vol x{vol_spike:.1f}"
        if tags:
            reason += f"; hype={tags} intensity={intensity:.2f}"
        reason += " -> FADE"
        return SignalResult(self.name, SignalDirection.SHORT, score, conf, reason,
                            {"recent_ret": recent_ret, "vol_spike": vol_spike, **hype})
