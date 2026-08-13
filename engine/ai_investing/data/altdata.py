"""Alternative-data feeds for the manipulation/hype thesis — the real edge.

Live integrations (stdlib urllib, guarded, graceful):
  - options_flow  : Polygon.io options snapshot -> call/put skew + volume-vs-OI churn
                    (stocks). Needs POLYGON_API_KEY; requires a PAID Polygon plan
                    (v3/snapshot/options 403s on the free Basic tier) -- stays
                    soft-unavailable there.
  - polygon_news_sentiment: Polygon.io per-ticker News API (bundled with the free
                    Stocks Basic plan) -> precomputed positive/negative/neutral
                    insight per article, averaged. Same articles also feed the
                    LLM-scored headline stream (data/news.py _polygon_headlines);
                    this is the fast/cheap corroborating half.
  - crypto_hype   : CoinGecko -> 24h move, volume/mcap churn, community vote skew
                    (crypto). Free; optional COINGECKO_API_KEY.
  - deribit_options_flow: Deribit PUBLIC REST API -> BTC/ETH options call/put
                    skew + volume-vs-OI churn, the crypto counterpart to
                    options_flow. No key/auth needed at all (unlike Polygon's,
                    which needs a paid plan) -- it's an open market-data endpoint.
  - etherscan_whale_flow: net ETH balance change across a small set of known
                    exchange hot wallets (Binance Hot Wallet 20, Coinbase 44) --
                    rising exchange balances (inflow) reads bearish, falling
                    (outflow) reads bullish. Needs ETHERSCAN_API_KEY (free).
                    The two wallet addresses were sourced from public
                    Etherscan labels and independently cross-checked with live
                    balance queries (739,595 ETH / 23,444 ETH respectively)
                    before being hardcoded -- do not add more addresses here
                    without the same verification, a wrong address silently
                    produces a meaningless signal instead of an error.
  - social_velocity: Reddit public search -> mention count + upvote ratio (both).
                    Free; just needs a REDDIT_USER_AGENT.

Each returns AltSignal(available, intensity 0..1, bullish -1..1). `aggregate()` folds
them into a single hype reading, and news.build_market_context feeds that into the
PoliticalHypeSignal so the engine fades real manipulation, not just price/volume.
Master switch: ALTDATA_ENABLED (default off, to avoid hammering free APIs every cycle).
"""
from __future__ import annotations

import json
import os
import time
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


# Free "Basic" Polygon plans share one 5-calls/minute budget across every
# product AND every call site (this sentiment signal, data/news.py's headline
# stream, and the manual `--altdata` probe) -- so the throttle is a single
# in-process cooldown here, the same pattern data/news.py already uses for its
# LLM endpoint failover (_ENDPOINT_COOLDOWN). Resets on restart, which is fine:
# a handful of calls right after a restart is not a real risk.
_POLYGON_NEWS_TTL_S = 20 * 60
_POLYGON_MIN_CALL_GAP_S = 13.0     # keeps calls under 5/min with margin
_polygon_last_call = 0.0


def _polygon_news_cache_path(settings) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(settings.state_path)), "polygon_news_cache.json")


def _load_polygon_news_cache(settings) -> dict:
    try:
        with open(_polygon_news_cache_path(settings)) as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_polygon_news_cache(settings, cache: dict) -> None:
    try:
        path = _polygon_news_cache_path(settings)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            json.dump(cache, fh)
    except OSError:
        pass


def polygon_news_raw(settings, symbol: str, limit: int = 10) -> list[dict]:
    """Polygon's per-ticker News API -- bundled with the free Stocks Basic plan,
    unlike v3/snapshot/options (paid-only, see options_flow). US-listed tickers
    only (the free plan doesn't cover foreign exchanges); cached per symbol and
    rate-limited account-wide, both because the 5-calls/minute budget is shared."""
    global _polygon_last_call
    key = settings.altdata.polygon_api_key
    if not key or "." in symbol:      # foreign-exchange suffix (.HK/.SS/.KS/.T/...): not covered
        return []
    sym = _base(symbol)
    cache = _load_polygon_news_cache(settings)
    entry = cache.get(sym, {})
    if time.time() - entry.get("ts", 0) < _POLYGON_NEWS_TTL_S:
        return entry.get("articles", [])
    now = time.time()
    if now - _polygon_last_call < _POLYGON_MIN_CALL_GAP_S:
        return entry.get("articles", [])      # rate-limited this tick; stale beats nothing
    _polygon_last_call = now
    url = f"https://api.polygon.io/v2/reference/news?ticker={sym}&limit={limit}&apiKey={key}"
    try:
        articles = _get_json(url).get("results") or []
    except Exception:
        return entry.get("articles", [])      # stale beats nothing
    cache[sym] = {"ts": time.time(), "articles": articles}
    _save_polygon_news_cache(settings, cache)
    return articles


def polygon_news_sentiment(settings, symbol: str) -> AltSignal:
    """Fold Polygon's precomputed per-article, per-ticker sentiment into the
    alt-data hype blend -- a fast corroborating signal alongside the slower
    LLM-scored headline path these same articles also feed (see
    data/news.py _polygon_headlines)."""
    articles = polygon_news_raw(settings, symbol)
    if not articles:
        return AltSignal("polygon_news", detail="unconfigured or no recent articles")
    sym = _base(symbol)
    scores = [1.0 if (ins.get("sentiment") or "").lower() == "positive"
              else -1.0 if (ins.get("sentiment") or "").lower() == "negative"
              else 0.0
              for a in articles for ins in (a.get("insights") or [])
              if ins.get("ticker") == sym and (ins.get("sentiment") or "").lower()
              in ("positive", "negative", "neutral")]
    if not scores:
        return AltSignal("polygon_news", available=True,
                         detail=f"{len(articles)} articles, no scored insights")
    bullish = sum(scores) / len(scores)
    intensity = min(1.0, len(scores) / 10.0)    # volume of fresh coverage = loudness
    return AltSignal("polygon_news", available=True, intensity=intensity, bullish=bullish,
                     detail=f"{len(scores)} scored insights, net {bullish:+.2f}",
                     meta={"n": len(scores)})


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


# Deribit's book-summary endpoint is PUBLIC (no key/auth) but returns ~800
# instruments per currency, so it's cached the same way as the paid feeds above
# to avoid re-fetching every asset/cycle for what is really one call per coin.
_DERIBIT_URL = "https://www.deribit.com/api/v2/public/get_book_summary_by_currency"
_DERIBIT_TTL_S = 15 * 60
_DERIBIT_CURRENCIES = {"BTC", "ETH"}     # the only two Deribit lists options on


def _deribit_cache_path(settings) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(settings.state_path)), "deribit_cache.json")


def _load_deribit_cache(settings) -> dict:
    try:
        with open(_deribit_cache_path(settings)) as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_deribit_cache(settings, cache: dict) -> None:
    try:
        path = _deribit_cache_path(settings)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            json.dump(cache, fh)
    except OSError:
        pass


def deribit_options_flow(settings, symbol: str) -> AltSignal:
    """BTC/ETH options call/put skew + volume-vs-OI churn -- the crypto
    counterpart to options_flow() above, but on Deribit's PUBLIC market-data
    endpoint (no key needed, unlike Polygon's paid-only equivalent)."""
    base = _base(symbol)
    if base not in _DERIBIT_CURRENCIES:
        return AltSignal("deribit_options", detail=f"Deribit lists options for BTC/ETH only, not {base}")
    cache = _load_deribit_cache(settings)
    entry = cache.get(base, {})
    if time.time() - entry.get("ts", 0) >= _DERIBIT_TTL_S:
        try:
            results = _get_json(f"{_DERIBIT_URL}?currency={base}&kind=option").get("result") or []
            cache[base] = {"ts": time.time(), "results": results}
            _save_deribit_cache(settings, cache)
            entry = cache[base]
        except Exception:
            pass    # entry stays whatever was cached (possibly empty) -- stale beats nothing
    results = entry.get("results") or []
    if not results:
        return AltSignal("deribit_options", detail="no data (Deribit unreachable)")
    call_v = put_v = oi = 0.0
    for r in results:
        vol = r.get("volume") or 0.0
        oi += r.get("open_interest") or 0.0
        name = r.get("instrument_name", "")
        if name.endswith("-C"):
            call_v += vol
        elif name.endswith("-P"):
            put_v += vol
    total = call_v + put_v
    if total <= 0:
        return AltSignal("deribit_options", available=True, detail="no options volume",
                         meta={"contracts": len(results)})
    intensity = min(1.0, total / max(1.0, oi))
    bullish = (call_v - put_v) / total
    return AltSignal("deribit_options", available=True, intensity=intensity, bullish=bullish,
                     detail=f"C/P vol {call_v:.1f}/{put_v:.1f} {base}, vol/OI {total / max(1, oi):.2f}",
                     meta={"call_volume": call_v, "put_volume": put_v, "open_interest": oi})


# A small, manually-verified watchlist -- NOT sourced from memory. Each address
# was found via public Etherscan labels and confirmed live before being added
# (see module docstring for the balances at verification time). Extending this
# list requires the same live balance cross-check: a wrong/stale address here
# fails silently (a real-looking but meaningless signal), not with an error.
_ETHERSCAN_V2_URL = "https://api.etherscan.io/v2/api"
_ETHERSCAN_ETH_WALLETS = {
    "binance_hot_20": "0xf977814e90da44bfa03b6295a0616a897441acec",
    "coinbase_44": "0xb5d85cbf7cb3ee0d56b3bb207d5fc4b82f43f511",
}
_ETHERSCAN_SNAPSHOT_TTL_S = 30 * 60       # take a fresh balance reading at most this often
_ETHERSCAN_NETFLOW_WINDOW_S = 24 * 3600   # compare against the snapshot nearest this far back
_ETHERSCAN_HISTORY_MAX_S = 48 * 3600      # prune snapshots older than this


def _etherscan_cache_path(settings) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(settings.state_path)), "etherscan_cache.json")


def _load_etherscan_cache(settings) -> dict:
    try:
        with open(_etherscan_cache_path(settings)) as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_etherscan_cache(settings, cache: dict) -> None:
    try:
        path = _etherscan_cache_path(settings)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            json.dump(cache, fh)
    except OSError:
        pass


def _etherscan_balance(key: str, address: str) -> float | None:
    url = f"{_ETHERSCAN_V2_URL}?chainid=1&module=account&action=balance&address={address}&tag=latest&apikey={key}"
    try:
        d = _get_json(url)
        if d.get("status") == "1":
            return int(d["result"]) / 1e18
    except Exception:
        pass
    return None


def etherscan_whale_flow(settings, symbol: str) -> AltSignal:
    """Net ETH balance change across the verified exchange-wallet watchlist
    above, over ~24h. Rising exchange balances (net inflow) means funds are
    being staged to sell -- bearish; falling balances (net outflow) means
    funds are moving to cold storage/accumulation -- bullish. Snapshots
    persist across restarts (disk cache), so history builds up over real time
    rather than needing to be collected in one run."""
    key = settings.altdata.etherscan_api_key
    if not key or _base(symbol) != "ETH":
        return AltSignal("etherscan_whale", detail="unconfigured or not ETH")
    cache = _load_etherscan_cache(settings)
    history = cache.get("history", [])
    now = time.time()
    if not history or now - history[-1]["ts"] >= _ETHERSCAN_SNAPSHOT_TTL_S:
        balances = {name: bal for name, addr in _ETHERSCAN_ETH_WALLETS.items()
                   if (bal := _etherscan_balance(key, addr)) is not None}
        if balances:
            history.append({"ts": now, "balances": balances})
            history = [h for h in history if now - h["ts"] <= _ETHERSCAN_HISTORY_MAX_S]
            cache["history"] = history
            _save_etherscan_cache(settings, cache)
    if len(history) < 2:
        return AltSignal("etherscan_whale", available=True,
                         detail=f"warming up ({len(history)} snapshot(s), need ~24h of history)")
    latest = history[-1]
    baseline = min(history[:-1], key=lambda h: abs(h["ts"] - (latest["ts"] - _ETHERSCAN_NETFLOW_WINDOW_S)))
    common = set(latest["balances"]) & set(baseline["balances"])
    if not common:
        return AltSignal("etherscan_whale", detail="no comparable snapshots")
    net = sum(latest["balances"][k] - baseline["balances"][k] for k in common)
    total = sum(latest["balances"][k] for k in common)
    hours = (latest["ts"] - baseline["ts"]) / 3600
    bullish = max(-1.0, min(1.0, -net / max(1.0, total) * 20))    # outflow (net<0) -> bullish
    intensity = min(1.0, abs(net) / max(1.0, total) * 20)
    return AltSignal("etherscan_whale", available=True, intensity=intensity, bullish=bullish,
                     detail=f"exchange netflow {net:+.1f} ETH over {hours:.1f}h ({', '.join(sorted(common))})",
                     meta={"net_eth": net, "hours": hours, "wallets": sorted(common)})


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
    if asset_class == "crypto":
        signals = [crypto_hype(settings, symbol), deribit_options_flow(settings, symbol),
                  etherscan_whale_flow(settings, symbol)]
    else:
        signals = [options_flow(settings, symbol), polygon_news_sentiment(settings, symbol)]
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
