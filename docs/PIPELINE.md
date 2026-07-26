# The Pipeline — global news → nodes → ripple → 10 trades

**Status: design, agreed direction.** This is the target architecture for turning
the Brain (docs/BRAIN.md) into the full loop the project is aiming at:

> ingest global information continuously → digest each item ONCE and remember it
> locally → feed the relevant nodes → propagate through the field → rank and
> explain the top 10 trades.

The design principle throughout: **crawl cheap, digest once, remember locally.**
The expensive resource is LLM tokens, not bandwidth. Nothing gets sent to a model
twice.

## 1. Where we are vs. where this goes

| Layer | Today | Target |
|---|---|---|
| Ingestion | 2-3 RSS feeds, refetched every cycle | 12-20 curated global feeds + FRED + alt-data, conditional GET, GDELT later |
| Memory | none — same headlines re-scored by LLM every 5 min | SQLite article/event store; only NEVER-SEEN items reach the LLM |
| Digestion | one LLM call per cycle over everything | one batched call per cycle over *new* items only (~95% token cut) |
| Field | persistent activations + τ-queue (done) | unchanged — this part is ready |
| Graph | 79 nodes / ~120 edges (done, reviewable) | +global coverage nodes (§4), grows via provenance-tagged LLM proposals |
| Output | per-asset signal into the formula | + **the Adviser**: ranked top-10 trades with causal chains (§5) |

## 2. Local memory: `data/brain.db` (SQLite)

One database, same pattern as the existing `journal.db`. Tables:

- **articles** — `id = sha1(normalized_title + source)`, title, source, url,
  published, first_seen, `digested` flag. The dedupe key means a story seen at
  09:00 is *never* re-sent to the LLM at 09:05. A materially UPDATED story has a
  different title → different hash → digested as news. That is exactly the
  "don't re-crawl the same info unless updated" rule.
- **events** — the digested output (summary, origin nodes, polarity, magnitude,
  credibility, emotion, article_ids). This is the compounding knowledge store:
  next month's session starts warm, not cold.
- **node_history** — per-cycle field activations per node → lets the dashboard
  plot "how has the tariff node been trending for 3 weeks" and lets us backtest
  the brain itself.
- **advice_log** — every top-10 list ever issued, with the reasoning frozen at
  issue time → later we score the adviser against realized returns (same
  discipline as the formula: it must EARN trust).

Retention: articles 90 days, events 1 year, node_history/advice forever (tiny).

## 3. Ingestion (crawl cheap)

**Phase A — curated feeds (build now).** RSS/Atom remains the right backbone:
free, structured, legal, cache-friendly. Expand `NEWS_RSS` to a global set
covering our markets: Reuters world/markets, WSJ, BBC, CNBC, FT (headlines),
Nikkei Asia, SCMP (China/HK), Caixin, Straits Times / Business Times (SG),
CoinDesk (crypto), OilPrice (energy). Fetcher upgrades:

- conditional GET (`ETag` / `If-Modified-Since`) — most polls cost ~0 bytes;
- per-feed failure isolation + staleness flag (a dead feed must be visible);
- every headline stored with its source (already done) and hash-deduped into
  `articles` before anything else happens.

**Phase B — later, optional:** GDELT 15-min global event dumps (huge recall,
noisy — needs its own pre-filter), plus targeted API pulls (central bank
calendars, earnings dates). Arbitrary-website crawling is deliberately NOT in
the plan: fragile, slow, and the curated feeds already carry the signal.

## 4. Graph readiness — node gaps to close for "global"

The current 79 nodes cover US/China/SG well. For genuinely global digestion add
(~12 nodes, all with curated edges, SEED_VERSION bump):

- `ecb_policy`, `europe_growth` (eurozone bloc — moves DAX/luxury/China exports)
- `india_growth` (the other EM engine; SG banks exposure)
- `em_flows` (EM capital flows — USD edge already exists to point at it)
- `us_tech_regulation` (antitrust/AI regulation — mega-cap risk)
- `crypto_regulation` (ETF approvals, stablecoin law — crypto_liquidity's sibling)
- `oil_supply` vs existing `oil_price` (OPEC/shale supply side distinct from price)
- `agri_food` (food prices — inflation edge, DBA asset)
- `japan_equities` theme (yen_carry already exists; add EWJ or 1329.T asset)
- `europe_equities` theme (+ VGK or FEZ asset)
- `india_equities` theme (+ INDA asset)

Rule stays: assets only get added when they're tradable on our brokers.

## 5. The Adviser — "tell me the 10 trades"

New module `brain/adviser.py`, CLI `--advise`, dashboard panel, optional
Telegram digest. For every tradable asset in the graph ∪ watchlist:

```
score(asset) = w1·field_impact          (persistent activation reaching the asset)
             + w2·formula_conviction    (θ·φ where price data exists)
             + w3·scenario_boost        (fired, pre-committed hypotheses)
             + w4·regime_fit            (risk-off regime tilts toward defensives/gold;
                                         risk-on toward beta/crypto)
             − w5·crowding_penalty      (hype flags / promotional intensity —
                                         manipulation never gets BOUGHT, at most faded)
all × brain mood conviction multiplier (a wary brain sizes down everything)
```

Output per trade — ranked top 10, each with:

1. **direction + suggested weight** (vol-targeted, within existing risk caps);
2. **the causal chain**, verbatim from the graph walk — e.g.
   `tariff escalation ↑ → rare-earth curbs ↑ → semis ↓ → NVDA (short bias)` —
   so every recommendation is inspectable, never a black box;
3. **what would invalidate it** (the trigger's reversal, from the scenario/edge);
4. **freshness** — which events drive it and how decayed they are.

Written to `data/advice.json` + logged to `advice_log`. Honest framing: this is
decision support feeding your views (UserViews), not a second autonomous trader —
the engine's actual orders still flow through the formula + risk + safety stack,
and the adviser's hit-rate gets measured before it's ever trusted with sizing.

## 6. Cadence & cost budget

| Task | Cadence | Cost |
|---|---|---|
| Feed polling | every cycle (5 min) | ~free (conditional GET) |
| LLM digestion | every cycle, **new articles only**, batched, fast tier | the big saving — tokens scale with novel news, not with polling frequency |
| Macro data (FRED/yfinance) | 6 h cache (done) | free |
| Deep global scan + adviser refresh | 1×/day, smart tier | one call |
| LLM-edge review queue | weekly, human-in-the-loop | your 10 minutes |

## 7. Build order

1. `data/brain.db` store + hash-dedupe in the fetch→digest path (the cost fix) —
   highest value, smallest risk.
2. Feed expansion + conditional GET + feed-health status on the dashboard.
3. Node/asset additions from §4 (SEED_VERSION bump).
4. `brain/adviser.py` + `--advise` + dashboard "Top trades" panel + advice_log.
5. Nightly deep-scan job + Telegram daily digest.
6. (later) GDELT pre-filtered firehose; adviser hit-rate report.
