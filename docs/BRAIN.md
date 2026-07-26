# The Brain — a macro & relationship intelligence layer

**Status: IMPLEMENTED** (`engine/ai_investing/brain/`, dashboard `/brain` page).
This documents the design and how it maps to code. The brain is a persistent,
cross-asset world model: it tracks the macro regime, knows how factors influence
each other (and where their stable points sit), links events to industries the way
an analyst would, separates signal from engineered noise, reads the crowd's
emotions, and keeps an emotional state of its own.

## 0. The vision (what this is for)

The brain understands the macro *field*: the factors, the relationships between
them, and their stable points. When a news item shocks one factor, the brain knows
how the shock propagates to every other factor and down into assets — across US,
HK, China A, and Singapore markets (all reachable via Longbridge), not just US
mega-caps. Factors are **nodes**; you can inject a headline on the dashboard's
Brain page and *watch* it ripple through the nodes. From that field view, strategy
follows.

Quick map from vision to code:

| Vision | Where it lives |
|---|---|
| Factors as nodes, signed relationships, stable points | `brain/graph.py` + `brain/seed.py` (62 nodes, 85 curated edges; factor nodes carry an `equilibrium` note) |
| News shocks a node and ripples to the others | `KnowledgeGraph.propagate()` — impulse × sign × weight × per-hop decay, with a full traversal trace |
| Multi-market (Longbridge, not just US) | Asset nodes across US / HK / CN / SG / crypto; `MacroLinkageSignal` bridges Longbridge symbols (700.HK) to canonical ones (0700.HK) |
| Noise vs real information (manipulation filter) | `brain/events.py` credibility score: source trust × corroboration × manipulation-likelihood × hype-language; sub-threshold events are labeled NOISE, shown but never propagated or traded |
| Emotions — the crowd's and the brain's own | `brain/regime.py`: fear/greed/euphoria/panic from event emotion tags + VIX; the brain's own mood (confidence/caution) scales how hard macro views press into sizing |
| Visualization: inject news, watch nodes react | Dashboard `/brain`: force-directed graph, hop-by-hop ripple animation, regime dials, emotion meters, signal/noise feed; CLI: `--brain`, `--brain-simulate`, `--brain-nodes` |

## 1. Audit — what exists today, and its gaps

The engine already has a signal → decision → risk pipeline (`signals/`,
`strategy/decision.py`, `learning/formula.py`) and a per-cycle news pass
(`data/news.py`). Concretely, today:

| Piece | What it does | Gap |
|---|---|---|
| `data/news.py: analyze_with_claude` | One LLM call per cycle: RSS headlines → per-ticker sentiment score | Only scores tickers **named verbatim** in a headline **and** already in the watchlist. A Fed decision or China tariff story that never says "NVDA" gives NVDA nothing, even when the implication is obvious to a human analyst. |
| `signals/political_hype.py` | Fades a price+volume pump when it coincides with LLM-flagged political/promotional hype | Per-symbol only, reactive to a pump already underway. Not a general "politics affects sector X" model. |
| `strategy/regime.py: RegimeGate` | De-risks on high realized volatility / out-of-distribution features | Purely statistical (vol + z-score). Not macro-aware — doesn't know *why* vol is up. |
| `data/news.py: global_briefing()` | One-off prose briefing (Macro/Rates, Geopolitics, Crypto, Risks) | Cosmetic — only wired to the standalone `--briefing` CLI command, **never consulted by `decide()`**. Regenerated from scratch every call with no memory of yesterday's regime. |
| Watchlist (`STOCK_WATCHLIST`/`CRYPTO_WATCHLIST`) | The only assets the engine looks at or trades | No commodities, no staples ETFs, no rates/FX/vol instruments — structurally can't notice opportunity outside the named mega-caps. |

This matches what you ran into directly: the interactive backtest session this week had
to manually research fundamentals + catalysts for 11 names by hand, one at a time, with
no persistent place for that analysis to live or compound — next month, or next
session, it starts from zero again.

## 2. Goals, restated precisely

1. **Holistic macro view** — rates, inflation, trade policy, elections, central banks,
   geopolitics — tracked continuously, not reconstructed fresh each prompt.
2. **Cross-asset linkage ("birds-eye view")** — an event doesn't just hit the one
   ticker it names; it should propagate to everything exposed to that theme/sector/
   policy, the way "China anti-corruption crackdown → baijiu demand → Moutai" isn't
   a Moutai headline, it's an inference.
3. **Broader universe** — commodities, staples, sector proxies as first-class context
   (and optionally tradable), not just the mega-cap names that already get the most
   attention/crowding.
4. **Anticipatory, not reactive** — pre-committed reasoning ("if PBOC cuts again,
   expect X") so a reaction fires the moment a trigger is confirmed, not several
   LLM-parsing-steps later.
5. **Political factor as a first-class macro driver**, not just a per-symbol
   pump-fade.

Honest caveat up front: this cannot manufacture true foresight — no legitimate public
information source tells you the future before it's public (systems that claim to are
either lucky or trading on something they shouldn't be). What it *can* do is widen the
aperture (catch indirect exposures a name-match misses) and cut latency (react the
moment a pre-registered trigger is confirmed, instead of re-deriving the implication
from scratch). That's the honest version of "don't be a laggard."

## 3. Proposed architecture

Four new pieces, layered on the existing pipeline, roughly in build order.

### 3.1 Expand the universe (foundation — cheap, no new integrations)

Add a `MACRO_WATCHLIST` of context-only instruments (not necessarily traded, just
observed), all fetchable today via the `yfinance` provider already in use:

| Instrument | Ticker | Why |
|---|---|---|
| Gold | `GC=F` | Risk-off / inflation hedge demand |
| Crude oil | `CL=F` | Energy costs, inflation, geopolitical risk proxy |
| Copper | `HG=F` | China/global industrial-demand bellwether |
| US Dollar Index | `DX-Y.NYB` | Cross-asset risk appetite, EM/commodity headwind-tailwind |
| 10Y Treasury yield | `^TNX` | Rate trajectory |
| VIX | `^VIX` | Risk appetite / vol regime |
| Sector ETFs | `XLK`, `XLE`, `XLF`, `XLP` | Sector-level rotation context |

Separately, widen the **tradable** universe to include staples/commodity ETFs
(`XLP`, `GLD`, `USO`, `DBA`) so opportunity in "boring" sectors isn't structurally
excluded by a watchlist that only ever lists mega-cap growth names.

Add `data/macro.py` (sibling to `altdata.py`) pulling hard macro series from
**FRED** (Federal Reserve Economic Data — free API key, no cost): CPI, Fed funds
rate, unemployment, ISM/PMI, yield-curve spread.

### 3.2 Structured event extraction (upgrade `news.py`)

Today's LLM call asks for **per-ticker** sentiment. Extend the prompt to also return
**events** tagged by sector/theme/actor, not just literal tickers:

```json
{
  "events": [
    {
      "summary": "PBOC cuts 1yr LPR by 10bps",
      "actors": ["PBOC", "China"],
      "type": "monetary_policy",
      "themes": ["china_financials", "china_rates", "china_property"],
      "polarity": -1,
      "magnitude": 0.4,
      "confidence": 0.8
    }
  ]
}
```

This is a prompt change to `analyze_with_claude` (or a parallel function reusing
the same `_call_llm` plumbing) — no new infrastructure. It directly fixes the
"never named, so ignored" gap: an event tagged `china_financials` can now reach
ICBC even though the headline never says "ICBC."

### 3.3 The relationship graph (the actual "brain" wiring)

A lightweight, file-backed graph — `data/knowledge_graph.json` — of nodes
(companies, sectors, commodities, countries/policy actors, themes) and typed edges
(`exposed_to`, `supplies`, `competes_with`, `regulated_by`, `correlates_with`).

Two ways to populate it, used together:

1. **Seeded/curated** (high precision, do this first) — hand-authored starter
   edges that formalize analysis already done rather than re-deriving it every
   session. Literally the fundamentals research from this week becomes the first
   ~15-20 edges:
   - `NVDA -exposed_to-> {china_export_controls, ai_capex_cycle}`
   - `CATL -supplies-> {tesla, global_ev_oems}`; `-exposed_to-> {lithium_price, us_tariff_policy}`
   - `600519.SH -exposed_to-> {china_anti_corruption_policy, china_consumer_demand}`
   - `601398.SH -exposed_to-> {pboc_rate_policy, china_property_sector}`
2. **LLM-proposed, appended over time** — each cycle's structured events (3.2)
   propose new edges with a confidence + provenance tag (which event proposed it,
   when). These are *appended*, not blindly trusted permanently — see §6 on review.

**Propagation**: an event tagged `themes: ["china_financials"]` walks the graph for
every asset with an `exposed_to` edge into that theme — including assets never
named in the headline. That walk *is* "linking one industry to another."

### 3.4 Persistent macro regime state

Today's `global_briefing()` is prose, regenerated from scratch, and unused by
`decide()`. Replace/supplement with a small **persistent, quantified** state file,
`data/macro_regime.json`, updated each cycle:

```json
{
  "risk_appetite": "risk_off",
  "rate_trajectory": "easing",
  "dollar_trend": "weakening",
  "geopolitical_tension": 0.62,
  "trade_policy_stance": "escalating",
  "updated": "2026-07-26T06:00:00Z"
}
```

Derived from FRED series + VIX/DXY levels (3.1) + the structured events' aggregate
polarity (3.2). Because it persists cycle-to-cycle, this is actual situational
memory — "what world are we in" — instead of a fresh, forgetful LLM call each time.

### 3.5 Anticipatory scenario registry

A small hand-curated list of forward-looking hypotheses, checked against each
cycle's structured events:

```json
{
  "trigger": "PBOC cuts rates again",
  "implication": "further ICBC NIM pressure",
  "assets": ["601398.SH"],
  "direction": -1,
  "status": "watching"
}
```

When an incoming event matches a registered trigger, the implication is already
known — the system doesn't re-derive "does a rate cut hurt ICBC" from scratch under
time pressure, it fires immediately. Start this registry with the specific
hypotheses already surfaced this week (PBOC → ICBC, China stimulus → staples,
tariff escalation → CATL overseas risk) rather than inventing new ones.

### 3.6 Wiring into decisions

Add `signals/macro_linkage.py` — a `MacroLinkageSignal(Signal)` that, for a given
asset, looks up graph edges (3.3) + regime state (3.4) + the scenario registry
(3.5), and returns a score/confidence exactly like `momentum` or `sentiment` do
today. This is the clean integration point: it becomes one more feature in
`learning/features.py`, and the existing walk-forward optimizer
(`backtest/walkforward.py`) learns how much to trust it over time, same as every
other signal — it doesn't need a second bespoke overlay mechanism competing with
`UserViews`.

## 4. Build order

| Phase | Work | Cost |
|---|---|---|
| 0 | Add `MACRO_WATCHLIST` context tickers (yfinance) + `data/macro.py` (FRED) | Near-zero — free data, no new plumbing |
| 1 | Upgrade `news.py` prompt to extract structured events (§3.2) | Small prompt change, reuses existing LLM plumbing |
| 2 | Seed `data/knowledge_graph.json` with ~15-20 curated edges from this week's research | Manual, one-time |
| 3 | Persistent `data/macro_regime.json`, updated from FRED + VIX + events | New small module |
| 4 | Seed the scenario registry with this week's specific hypotheses | Manual, one-time |
| 5 | `signals/macro_linkage.py`, wired into `default_signals()` | Follows existing Signal interface |
| 6 (later, optional) | GDELT Project integration (free, global event stream) for broader geopolitical coverage than RSS+LLM alone | Higher effort — GDELT is high-volume/noisy, needs its own filtering pass |

Phases 0-2 alone would have let this week's manual research (fundamentals +
catalysts for 11 names) get *saved* somewhere reusable instead of starting cold
next time.

## 4b. What was actually built (delta from the plan above)

The implementation follows §3 with these deliberate upgrades:

- **A factor layer, not just event→theme→asset.** Edges connect macro factors to
  each other with signs (`fed_rate -(+)→ usd_strength -(−)→ gold_price`), so a
  shock can travel multiple hops through the macro field before touching an
  asset. Factor nodes carry an `equilibrium` description — the stable point — and
  the regime tracks a `stability` dial measuring how far the field sits from
  stable.
- **Credibility / noise scoring** (§ not in the original plan): every event gets
  `credibility ∈ [0,1]` from source trust (wire services > blogs > social),
  cross-feed corroboration, LLM-judged manipulation likelihood, and hype-language
  heuristics. `is_noise` events are displayed but never propagate and never trade.
  The effective impulse is `polarity × magnitude × credibility × confidence`.
- **Emotions, two layers.** Events carry crowd-emotion tags; the regime aggregates
  them (with VIX) into fear/greed dials and a label (panic/fear/neutral/greed/
  euphoria/complacency). Separately the brain keeps its own mood — confidence
  (regime stability + prediction quality) and caution (drawdown + noise ratio +
  instability) — which becomes a conviction multiplier on the MacroLinkageSignal.
  A wary brain in a chaotic tape presses its views more softly.
- **Multi-market universe.** Seed assets span US, HK (Tencent, Alibaba, Meituan,
  BYD, ICBC, Tracker Fund), China A (Moutai, CATL), Singapore (DBS, OCBC, UOB,
  STI ETF, CICT), and crypto. Symbol bridging handles Longbridge (`700.HK`,
  `D05.SG`) vs yfinance (`0700.HK`, `D05.SI`) conventions.
- **The visualization.** Dashboard `/brain`: the graph as a living field —
  inject a hypothetical headline, the brain judges signal-vs-noise, and the
  ripple animates hop by hop with per-node impact halos. Right rail shows regime
  dials, emotion meters, mood, fired scenarios, and ranked asset impacts.
- **θ migration.** Adding `macro_linkage` to the feature vector migrates saved
  formulas in place (new feature starts at its default weight, RLS state
  re-initializes) — no learned state is thrown away.

Files: `brain/{graph,seed,events,regime,scenarios,core}.py`, `data/macro.py`,
`signals/macro_linkage.py`, `tests/test_brain.py`; state lives in
`data/{knowledge_graph,macro_regime,scenarios,brain,macro_cache}.json`.

## 4c. Adopted from the World Systems Economics Framework (2026-07-26)

From the two framework docs (`World_Systems_Economics_Framework[_Extended].docx`),
the brain adopted the pieces that survive contact with a trading horizon:

- **Time-delayed edges (τ).** Edges carry `delay_days`; a contribution crossing a
  τ-edge doesn't land now — it's queued in `data/field_state.json` with a due
  date and re-enters propagation as a fresh impulse when it matures (then ripples
  onward from there). Seeded lags: oil→CPI ~30d, tariffs→CPI ~45d, credit
  crunch→growth ~60d, tension→defense budgets ~90d, Fed→real economy ~120d,
  money supply→inflation ~180d. The dashboard shows "delayed effects in the pipe."
- **Persistent node state with damping (the master-equation core, dX/dt = ΣwX(t−τ)
  − decay).** `brain/field.py`: each node's activation absorbs propagated impacts
  and decays toward its stable point with a 36h half-life — the balancing feedback
  loop. The live dashboard shows this *field* (what's still ringing), while a
  simulation shows the instantaneous ripple. This doubles as the framework's
  "belief layer": a persistently activated node is a live narrative.
- **Centrality.** `KnowledgeGraph.centrality()` (damped PageRank over |weights|)
  ranks systemically important nodes; the viz sizes nodes by it.
- **Fragility = exposure × concentration.** Computed from the actual book
  (gross exposure × √HHI of position weights), shown as a regime dial, and fed
  into the brain's caution — a fragile book in an unstable field is exactly when
  macro conviction gets pressed most softly.
- **~17 new nodes** from their 80-node catalog, filtered for tradability: money
  supply/liquidity, US government debt, credit conditions, US labor market, US
  consumer, US election cycle, sanctions, shipping/supply chains, critical
  minerals/rare earths, datacenter power demand, defense spending, natural gas +
  themes US financials & defense industry + assets XLF, ITA, TLT. Seed is now
  versioned (`SEED_VERSION`): existing graph files merge new curated wiring on
  load without losing LLM-proposed edges.

**Deliberately not adopted:** demographics/birth-rates/education/water-type nodes
(decade-scale, untradable at our horizon), agent-based modeling (research
program, not an engine feature), and a separate belief layer (emotions +
credibility + persistent activations already cover it). The framework's own
"critical limitation" — estimating dynamic edge weights is the hardest problem —
is answered here the same way as everything else: the graph's output is one
signal whose formula weight is *learned* by walk-forward, not asserted.

## 4d. The mathematics (v2) — and its honest limits

The propagation is a truncated path-sum over the graph. For every directed path
p = (n₀→n₁→…→n_k), k ≤ max_hops:

    contribution(p) = impulse(n₀) · ∏ᵢ [ signᵢ · weightᵢ · decay ]
    raw(n)          = Σ over all paths ending at n
    impact(n)       = tanh(raw(n))                       — smooth saturation
    impulse(n₀)     = polarity · magnitude · credibility · confidence

Properties, deliberately: (1) **sum over paths, not max-path** — converging
medium-strength paths add, which is how clusters actually move; (2) **tanh, not
clipping** — stacked shocks keep their ordering near saturation; (3) **no
same-edge echo** — a path never immediately re-crosses the edge it arrived by,
so asset↔proxy pairs can't bounce a shock back onto its source, while genuine
feedback loops through distinct edges are summed correctly; (4) **asymmetric
edges** (`weight_rev`) — NVDA is ~11% of TSMC's revenue but TSMC is ~100% of
NVDA's supply, and the two directions carry different weights; (5) **per-type
persistence** — activations decay with type-specific half-lives (factor 96h,
commodity 72h, theme 48h, asset 24h): policy regimes outlive single-name news;
(6) **τ-delays** move contributions through a dated pending queue; (7) `decay`
per hop is not physics — it encodes growing MODEL uncertainty with inference
depth; (8) government influence is wiring, not commentary: state stakes /
SOE control are `regulated_by` edges with real weights (US gov↔Intel/MP,
Beijing↔ICBC/Moutai/CR), and equity stakes are `owns` edges weighted by the
stake's share of the owner.

Known simplifications that remain (the roadmap, in honesty):

- **Linearity.** Real responses are nonlinear (a 10bp cut ≠ 1/10th of a 100bp
  cut) and state-dependent (good jobs news is bad equity news in a tightening
  regime). Today nonlinearity enters only via tanh and via composition through
  intermediate nodes. Next step: per-node response curves / regime-conditional
  weights — but every such parameter must be LEARNED, not asserted, or it's
  astrology with extra steps.
- **Hand-set weights.** Curated edge weights are educated priors. The honest
  fix is empirical: regress historical node shocks against realized asset moves
  and let data adjust weights (the framework doc's own "hardest problem").
  node_history + events tables already collect exactly the data needed.
- **No belief updating on old events.** A story judged noise is not upgraded
  when a trusted source later confirms it; the confirmation arrives as a NEW
  event instead. Adequate, not elegant.
- **Volatility ≠ direction.** Some shocks (elections) mainly widen the
  distribution rather than move its mean; the graph currently only models mean
  shifts.

## 5. Guardrails (don't skip these)

- **LLM-proposed graph edges need periodic review.** An auto-appended relationship
  can be wrong, stale, or true-in-2025-only. Treat confidence/provenance tags as
  real — don't let the graph silently calcify around a bad inference.
- **More signals = more overfitting surface.** The project already gates new
  formula adoption on deflated Sharpe ratio (`learning/walkforward.py`,
  `min_dsr`). `MacroLinkageSignal` goes through that same discipline — it doesn't
  get to bypass the walk-forward test just because it sounds sophisticated.
- **This is a widening/latency improvement, not prophecy.** Communicate results
  in those terms, not as "predicting the future."
