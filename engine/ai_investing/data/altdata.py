"""Alternative-data feeds for the manipulation/hype thesis — the real edge.

Three live integrations (stdlib urllib, guarded, graceful):
  - options_flow  : Polygon.io options snapshot -> call/put skew + volume-vs-OI churn
                    (stocks). Needs POLYGON_API_KEY (free tier).
  - crypto_hype   : CoinGecko -> 24h move, volume/mcap churn, community vote skew
                    (crypto). Free; optional COINGECKO_API_KEY.
  - social_velocity: Reddit public search -> mention count + upvote ratio (both).
                    Free; just needs a REDDIT_USER_AGENT.

Each returns AltSignal(available, intensity 0..1, bullish -1..1). `aggregate()` folds
them into a single hype reading, and news.build_market_context feeds that into the
PoliticalHypeSignal so the engine fades real manipulation, not just price/volume.
Master switch: ALTDATA_ENABLED (default off, to avoid hammering free APIs every cycle).
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

_CG_IDS = {
    "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana", "XRP": "ripple",
    "DOGE": "dogecoin", "ADA": "cardano", "BNB": "binancecoin", "AVAX": "avalanche-2",
    "MATIC": "matic-network", "LTC": "litecoin", "LINK": "chainlink", "DOT": "polkadot",
}


@dataclass
class AltSignal:
    source: str
    available: bool = False
    intensity: float = 0.0     # 0..1 — how loud / unusual
    bullish: float = 0.0       # -1..1 — directional lean
    detail: str = ""
    meta: dict = field(default_factory=dict)


def _get_json(url: str, headers: dict | None = None, timeout: int = 12):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _base(symbol: str) -> str:
    return symbol.split("/")[0].split(".")[0].upper()


def options_flow(settings, symbol: str) -> AltSignal:
    key = settings.altdata.polygon_api_key
    if not key:
        return AltSignal("options_flow", detail="unconfigured — set POLYGON_API_KEY")
    sym = _base(symbol)
    url = f"https://api.polygon.io/v3/snapshot/options/{sym}?limit=250&apiKey={key}"
    try:
        data = _get_json(url)
    except Exception as exc:
        return AltSignal("options_flow", detail=f"error: {exc}")
    results = data.get("results") or []
    call_v = put_v = oi = 0.0
    for c in results:
        vol = (c.get("day") or {}).get("volume", 0) or 0
        oi += c.get("open_interest") or 0
        typ = (c.get("details") or {}).get("contract_type", "")
        if typ == "call":
            call_v += vol
        elif typ == "put":
            put_v += vol
    total = call_v + put_v
    if total <= 0:
        return AltSignal("options_flow", available=True, detail="no options volume",
                         meta={"contracts": len(results)})
    intensity = min(1.0, total / max(1.0, oi))     # churn: volume vs open interest
    bullish = (call_v - put_v) / total
    return AltSignal("options_flow", available=True, intensity=intensity, bullish=bullish,
                     detail=f"C/P vol {call_v:.0f}/{put_v:.0f}, vol/OI {total / max(1, oi):.2f}",
                     meta={"call_volume": call_v, "put_volume": put_v, "open_interest": oi})


def crypto_hype(settings, symbol: str) -> AltSignal:
    base = _base(symbol)
    cid = _CG_IDS.get(base)
    headers = {"User-Agent": settings.altdata.reddit_user_agent}
    if settings.altdata.coingecko_api_key:
        headers["x-cg-demo-api-key"] = settings.altdata.coingecko_api_key
    try:
        if not cid:
            found = _get_json(f"https://api.coingecko.com/api/v3/search?query={urllib.parse.quote(base)}", headers)
            coins = found.get("coins") or []
            if not coins:
                return AltSignal("crypto_hype", detail=f"unknown coin {base}")
            cid = coins[0]["id"]
        d = _get_json(
            f"https://api.coingecko.com/api/v3/coins/{cid}"
            "?localization=false&tickers=false&market_data=true&community_data=true"
            "&developer_data=false&sparkline=false", headers)
    except Exception as exc:
        return AltSignal("crypto_hype", detail=f"error: {exc}")
    md = d.get("market_data") or {}
    chg = (md.get("price_change_percentage_24h") or 0.0) / 100.0
    tv = (md.get("total_volume") or {}).get("usd", 0) or 0
    mc = (md.get("market_cap") or {}).get("usd", 0) or 0
    churn = (tv / mc) if mc else 0.0
    up = d.get("sentiment_votes_up_percentage")
    vote_lean = ((up - 50) / 50.0) if up is not None else 0.0
    bullish = max(-1.0, min(1.0, 0.5 * vote_lean + 0.5 * max(-1.0, min(1.0, chg * 5))))
    intensity = min(1.0, abs(chg) * 3 + churn)      # big move + high churn = hype
    return AltSignal("crypto_hype", available=True, intensity=intensity, bullish=bullish,
                     detail=f"24h {chg * 100:+.1f}%, vol/mcap {churn:.2f}, votes_up {up}",
                     meta={"price_change_24h": chg, "vol_mcap": churn, "votes_up": up})


def social_velocity(settings, symbol: str) -> AltSignal:
    base = _base(symbol)
    ua = settings.altdata.reddit_user_agent or "ai-investing/0.1"
    url = f"https://www.reddit.com/search.json?q={urllib.parse.quote(base)}&sort=new&t=day&limit=100"
    try:
        d = _get_json(url, headers={"User-Agent": ua})
    except Exception as exc:
        return AltSignal("social", detail=f"error: {exc}")
    posts = [c.get("data", {}) for c in (d.get("data", {}).get("children") or [])]
    if not posts:
        return AltSignal("social", available=True, detail="no recent posts", meta={"mentions": 0})
    n = len(posts)
    ratios = [p.get("upvote_ratio", 0.5) for p in posts if "upvote_ratio" in p]
    avg_ratio = sum(ratios) / len(ratios) if ratios else 0.5
    return AltSignal("social", available=True, intensity=min(1.0, n / 100.0),
                     bullish=max(-1.0, min(1.0, (avg_ratio - 0.5) * 2)),
                     detail=f"{n} reddit posts/day, upvote_ratio {avg_ratio:.2f}",
                     meta={"mentions": n, "upvote_ratio": avg_ratio})


def collect(settings, symbol: str, asset_class: str = "stock") -> list[AltSignal]:
    signals = [crypto_hype(settings, symbol)] if asset_class == "crypto" else [options_flow(settings, symbol)]
    signals.append(social_velocity(settings, symbol))
    return signals


def aggregate(signals: list[AltSignal]) -> dict:
    """Fold available alt-signals into one hype reading."""
    avail = [s for s in signals if s.available]
    if not avail:
        return {"available": False, "intensity": 0.0, "bullish": 0.0, "sources": [], "detail": ""}
    return {
        "available": True,
        "intensity": max(s.intensity for s in avail),
        "bullish": sum(s.bullish for s in avail) / len(avail),
        "sources": [s.source for s in avail],
        "detail": "; ".join(f"{s.source}: {s.detail}" for s in avail),
    }
