"""Alternative-data interfaces for the manipulation/hype thesis — the real edge.

These are the integration points for options flow, on-chain activity, and social
velocity. They are guarded so the engine runs without them (each returns
`available=False` until you wire a provider + key), and honest about being scaffolds:
none is connected to a live feed yet. Once implemented, feed the results into
`news.build_market_context`'s hype_flags so the PoliticalHypeSignal reacts to real
manipulation signals, not just price/volume + headline sentiment.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class AltSignal:
    source: str
    available: bool = False
    intensity: float = 0.0     # 0..1 — how loud / unusual
    bullish: float = 0.0       # -1..1 — directional lean
    detail: str = ""
    meta: dict = field(default_factory=dict)


def options_flow(symbol: str) -> AltSignal:
    """Unusual options activity: call/put skew, volume-vs-open-interest, sweeps.
    Wire to an options-flow provider using OPTIONS_API_KEY."""
    if not os.environ.get("OPTIONS_API_KEY"):
        return AltSignal("options_flow", detail="unconfigured — set OPTIONS_API_KEY")
    return AltSignal("options_flow", detail="TODO: fetch + score unusual activity")


def onchain_flow(symbol: str) -> AltSignal:
    """Crypto on-chain: exchange in/outflows, whale transfers, new-holder velocity,
    smart-money wallets. Wire to a chain-data API using ONCHAIN_API_KEY."""
    if not os.environ.get("ONCHAIN_API_KEY"):
        return AltSignal("onchain", detail="unconfigured — set ONCHAIN_API_KEY")
    return AltSignal("onchain", detail="TODO: fetch + score on-chain flows")


def social_velocity(symbol: str) -> AltSignal:
    """Rate-of-change of mentions on X / Reddit / Truth Social — the pump amplifier.
    Wire to the platform APIs using SOCIAL_API_KEY."""
    if not os.environ.get("SOCIAL_API_KEY"):
        return AltSignal("social", detail="unconfigured — set SOCIAL_API_KEY")
    return AltSignal("social", detail="TODO: fetch + score mention velocity")


def collect(symbol: str) -> list[AltSignal]:
    """All alt-data signals for a symbol (only the configured ones are 'available')."""
    return [options_flow(symbol), onchain_flow(symbol), social_velocity(symbol)]
