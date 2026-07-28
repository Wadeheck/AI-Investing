# News Digestion Curriculum & Formula Improvement Plan

*This document teaches a tagging AI (the "digester" — Claude Sonnet 5 via the
existing `brain/events.py` extractor path) how to convert raw headlines into
graph impulses, and specifies the mathematical upgrades that turn those
impulses into better numbers. Written 2026-07-28, after evidence protocol v2.*

**Division of labor — do not blur it:**

| Who | Does | Does NOT |
|---|---|---|
| Digester AI | Semantic judgment: event → origin nodes, polarity, magnitude, confidence, manipulation, emotion, novelty | Credibility scoring, impulse math, graph propagation, trading |
| Code (`events.py`) | Source trust, corroboration, hype penalty → credibility; `impulse = polarity × magnitude × credibility × confidence` | Interpretation of meaning |
| Trainer (`train_web.py`) | Validates every formula change on train, gates on holdout, never touches the lockbox | Tuning on the full period |

---

## PART A — The Digestion Curriculum

### A1. Mission and mental model

You (the digester) are the sensory cortex of a trading web. The web is a graph
of 85 concept nodes (factors, commodities, themes, sectors, actors) connected
by 344 signed, weighted edges to each other and to 88 tradeable assets. When
you tag an event to a node with a signed impulse, the graph *ripples* it
outward — up to 3 hops, decaying — and the sum of ripples at each asset is the
trading signal.

Because the graph does the spreading, your job is **strictly local**: identify
where a shock ORIGINATES and how hard it hits that origin. Never tag the
places the shock will *arrive* — that double-counts the ripple.

### A2. The contract

**Input:** one day's headlines, each `[source] title — summary` (Guardian
records include a `summary`/trailText; use it — it often disambiguates the
headline). Up to ~100 headlines per day.

**Output:** strict JSON, the schema already enforced by `events.py`:

```json
{"events": [{
  "summary": "<one line, what actually happened>",
  "headline": "<verbatim headline this came from>",
  "source": "<the [source] tag>",
  "type": "monetary_policy|fiscal_policy|trade_policy|regulation|geopolitics|earnings|supply_chain|commodity|technology|market_flow|rumor_hype|other",
  "nodes": ["<1-3 ORIGIN node ids from the known list>"],
  "polarity": -1.0..1.0,
  "magnitude": 0.0..1.0,
  "confidence": 0.0..1.0,
  "manipulation_likelihood": 0.0..1.0,
  "emotion": "fear|greed|euphoria|panic|anger|hope|complacency|neutral",
  "emotion_intensity": 0.0..1.0,
  "novelty": 1.0|0.5|0.2,
  "event_key": "<stable slug for the underlying real-world event>",
  "ts": "<cited headline's UTC publication timestamp, verbatim>",
  "proposed_edges": []
}]}
```

`novelty`, `event_key`, and `ts` are NEW fields (formula upgrade R16 below,
and cross-timezone gating); the rest is the existing contract. See
SONNET_DIGEST_BRIEF.md for the operational protocol (ledger, escalation
pass, anchored-node rules) — that document is the digester's system prompt
and takes precedence on any wording difference. Unknown node ids are dropped by the validator —
wasted work. Tag ONLY ids from the list in A3.

**Hard rules:**
1. Merge duplicate headlines into ONE event (one event_key, corroboration is
   counted by the code, not by you emitting duplicates).
2. Skip celebrity/sports/lifestyle/fluff entirely.
3. 1–3 origin nodes per event. If you cannot name an origin node, the event
   does not belong in the web — skip it.
4. Never invent node ids. Never tag assets (the graph maps nodes→assets).

### A3. The node map — every node, and what polarity +1 means

**The universal convention: polarity is the direction of the NAMED QUANTITY,
never "good or bad for markets."** A rate CUT is polarity −1 on `fed_rate`
even though stocks may love it; the graph's edges encode whether that's
bullish or bearish for each asset. You report physics, not opinion.

**Factors (44):**

| Node | +1 means |
|---|---|
| `ai_capex_cycle` | AI infrastructure capex accelerating (bigger buildouts, higher guidance) |
| `ai_circularity` | MORE round-tripped/vendor-financed AI revenue revealed (see A9) |
| `bond_stress` | Bond market stress rising (yields spiking disorderly, auctions failing) |
| `btc_halving` | Halving-cycle supply tightening narrative strengthening |
| `china_anti_corruption` | Crackdown intensifying (probes, arrests, disappearing executives) |
| `china_consumer` | Chinese consumer spending strengthening |
| `china_export_controls` | Controls TIGHTENING (either direction: on China or by China) |
| `china_growth` | Chinese growth accelerating / data beating |
| `china_property` | Property sector IMPROVING (sales up, defaults resolved) |
| `china_stimulus` | MORE stimulus (announced, expanded, hinted by policymakers) |
| `credit_conditions` | Credit TIGHTENING (spreads widening, lending standards up) |
| `crypto_adoption` | Institutional/retail adoption advancing (ETF inflows, corporate treasuries, payment rails) |
| `crypto_liquidity` | Liquidity into crypto RISING (stablecoin issuance, exchange inflows) |
| `crypto_regulation` | Regulation TIGHTENING (enforcement, bans; approvals/clarity are −) |
| `defense_spending` | Defense budgets rising |
| `ecb_policy` | ECB TIGHTENING (hikes, hawkish guidance; cuts are −) |
| `em_flows` | Capital flowing INTO emerging markets |
| `energy_transition` | Transition accelerating (renewables policy, subsidies, targets) |
| `europe_growth` | European growth accelerating |
| `fed_rate` | Fed TIGHTENING (hike, hawkish dots/speech; cut or dovish is −) |
| `geopolitical_tension` | Tension ESCALATING (strikes, mobilization, ultimatums) |
| `global_growth` | Global growth accelerating (IMF upgrades, PMIs beating) |
| `india_growth` | Indian growth accelerating |
| `japan_debt` | Japan fiscal/debt stress rising (JGB stress, BoJ losing control) |
| `korea_growth` | Korean growth accelerating |
| `mas_policy` | MAS TIGHTENING (S$NEER band steepening) |
| `money_supply` | M2/liquidity EXPANDING |
| `oil_supply` | MORE supply (OPEC+ raising output, embargo lifted; cuts/outages are −) |
| `pboc_rate` | PBoC TIGHTENING (RRR/LPR hikes; cuts/injections are −) |
| `power_demand` | Electricity demand rising (datacenter load, grid strain) |
| `rare_earths` | Rare-earth supply RESTRICTING (export curbs; new supply is −) |
| `risk_appetite` | Risk-ON (see A6 — reserved for genuine market-wide mood shocks) |
| `sanctions` | Sanctions TIGHTENING/expanding |
| `shipping_costs` | Freight rates rising (canal closures, war-risk premiums) |
| `us_10y_yield` | 10-year Treasury yield RISING |
| `us_china_tariffs` | Tariffs/trade barriers RISING (truces and rollbacks are −) |
| `us_consumer` | US consumer strengthening (retail sales, sentiment beating) |
| `us_elections` | Election uncertainty/policy-change risk RISING |
| `us_employment` | US labor market strengthening (payrolls beat; claims spike is −) |
| `us_gov_debt` | US fiscal/debt stress rising (downgrades, shutdown, deficits) |
| `us_inflation` | US inflation RISING/hotter than expected (cool CPI is −) |
| `us_tech_regulation` | Tech regulation TIGHTENING (antitrust, AI acts, break-up suits) |
| `usd_strength` | Dollar strengthening |
| `yen_carry` | Carry trade PRESSURE rising (BoJ hikes, yen surge → unwind risk) |

**Commodities (9):** `agri_food`, `copper_price`, `gold_price`,
`lithium_price`, `natural_gas`, `nickel_price`, `oil_price`, `silver_price`,
`uranium_price` — +1 = the PRICE rising (or a shock that mechanically raises
it: mine closure, export ban, cartel cut). Use the `*_price` node for price
moves; use `oil_supply` for supply-side policy (they are separate nodes).

**Themes (26):** `ai_datacenter`, `china_financials`, `china_fnb`,
`china_staples`, `china_tech`, `crypto_majors`, `cybersecurity`,
`defense_industry`, `europe_equities`, `ev_supply_chain`, `food_beverage`,
`global_luxury`, `hardware_chain`, `healthcare`, `india_equities`,
`japan_equities`, `korea_equities`, `miners`, `robotics`, `semis`,
`sg_banks`, `sg_reits`, `solar`, `sportswear`, `us_financials`,
`us_megacap_tech` — +1 = business prospects of that industry IMPROVING
(demand, pricing power, order books). Tag a theme as origin ONLY for
industry-level news (e.g. "global chip demand forecast raised" → `semis`).
Company-level news about one stock in the theme: tag the theme only if the
news is a read-through for the whole industry (TSMC capex guidance → `semis`
yes; a single CEO resignation → skip).

**Sectors (2):** `consumer_staples`, `energy_sector` — same convention as
themes.

**Actors (4):** `us_government`, `china_government`, `opec`, `temasek` —
+1 = the actor ACTING/intervening more forcefully (fiscal push, decree,
production decision, major allocation). Use actor nodes when the news is
about the actor's *behavior* and a more specific factor node doesn't fit
(if OPEC cuts output, prefer `oil_supply` −1; add `opec` +1 only if the
political act itself is the story).

### A4. Magnitude — the anchored scale

Magnitude answers: *if true, how big a deal is this for the origin node?*
Calibrate to these anchors; the distribution over a normal month should have
median ≈ 0.3 and events ≥ 0.8 should be RARE (a few per year):

| Mag | Anchor | Examples |
|---|---|---|
| 0.1 | Routine data point, in-line | CPI exactly as forecast; minor exec quote |
| 0.3 | Notable surprise or development | CPI 0.2pp hot; mid-size stimulus measure; sector guidance cut |
| 0.5 | Significant shock | Surprise 25bp move; major company bankruptcy; new export-control regime |
| 0.7 | Major regime event | War outbreak; 75bp emergency action; systemic bank failure |
| 0.9–1.0 | Historic | COVID-scale shutdown; sovereign default; exchange collapse (FTX-scale) |

Two disciplines:
- **Surprise, not level.** For scheduled releases (CPI, payrolls, FOMC, GDP),
  magnitude measures the DEVIATION from expectations, not the number itself.
  An expected 25bp hike, fully priced: magnitude ≤ 0.15. Headlines usually
  say "unexpectedly", "shock", "in line" — use that language.
- **Escalation ladders saturate.** The 40th strike in an ongoing war is not
  a 0.7 every day. First occurrence sets the high mark; continuation news
  drops to 0.2–0.3 unless the *level* of conflict changes.

### A5. Confidence, manipulation, emotion

- **confidence** — how sure you are of your *reading* (nodes + polarity),
  not of the event's importance. Ambiguous headline, unclear attribution,
  translated/garbled text → 0.3–0.5. Clear factual report → 0.8–0.9.
- **manipulation_likelihood** — odds this is planted/pump material rather
  than organic verified news. Single-source "sources say" M&A chatter: ≥0.5.
  Promotional crypto/meme-stock language: ≥0.6. Official statistics: ≤0.1.
  Be aggressive — the code discounts credibility by 0.5×this.
- **emotion / emotion_intensity** — the dominant CROWD emotion the story
  carries (not yours). Market-crash coverage → fear/panic; melt-up coverage
  → greed/euphoria. Most business news is `neutral` at intensity ≤0.3. The
  risk node is pulsed from aggregate emotion, so mislabeled emotion moves
  real positions.

### A6. The origin-only discipline (the #1 error mode)

The graph propagates. Tagging downstream effects double-counts them.

- "Fed hikes 50bp, tech stocks plunge" → `fed_rate` +1. NOT `us_megacap_tech`,
  NOT `risk_appetite`. The edges fed_rate→tech already carry the effect.
- "Oil spikes as OPEC cuts output" → `oil_supply` −1 (origin). NOT
  `oil_price` +1 as well — the edge does that. Tag `oil_price` directly only
  when price moves WITHOUT a taggable cause ("oil jumps 4% on thin volume").
- "Chip stocks rally on strong TSMC guidance" → `semis` +1 (industry
  read-through). NOT `ai_capex_cycle` unless the story is capex specifically.
- `risk_appetite` is origin ONLY for mood-native shocks with no fundamental
  node: VIX spike on no news, broad panic/euphoria stories, "investors flee
  risk assets" as the story itself. If a fundamental cause exists, tag the
  cause and leave risk_appetite to the propagation and the emotion factor.

### A7. Deduplication, novelty, event chaining

Real-world events span many headlines and many days. The web must feel each
event ONCE at full strength.

- **Within a day:** merge all headlines about the same underlying event into
  one output event; pick the clearest headline as `headline`.
- **Across days:** assign a stable `event_key` — a slug you would reproduce
  seeing the story fresh (`2024-08-boj-hike-unwind`, `2023-10-gaza-war`,
  `2025-01-deepseek-shock`). Follow-up coverage of the same event on later
  days keeps the SAME event_key and sets `novelty`:
  - `1.0` first report of a new event (or a genuine escalation/phase change —
    then also update the summary to name what changed),
  - `0.5` material development within a known event,
  - `0.2` recap/opinion/anniversary coverage, no new facts.
  The impulse code multiplies by novelty (R16), so honest novelty tagging is
  what stops week-long story cycles from pounding the web daily.

### A8. No-hindsight discipline (historical tagging)

You will tag 2023–2026 headlines while knowing how 2023–2026 turned out.
The replay's honesty depends on you tagging **only what was knowable on that
day**. Concretely:

- Judge magnitude by how the event read AT THE TIME, not by what it caused.
  The first "new AI chatbot from a Chinese lab" headline is a 0.3 technology
  story even if you know it later cratered the market — the LATER headlines
  about the market reaction earn the bigger magnitudes on their own days.
- Never let knowledge of subsequent prices set polarity. "Bitcoin ETF
  approved" is `crypto_adoption` +1, `crypto_regulation` −1 (clarity) at the
  magnitude the day's coverage supports — regardless of what BTC did next.
- Forbidden internal reasoning: "this turned out to be important, so...",
  "this was the start of...", "markets would later...". If you catch
  yourself using outcome knowledge, re-read the headline as a stranger.
- Confidence must reflect the day's ambiguity, not resolved hindsight.

This cannot be fully verified, but spot audits (A11) compare your tags on
early-story days vs. what contemporaneous coverage supported.

### A9. Special radars (kept from v1)

- **Circular financing:** vendor-finances-its-customer, mutual
  investment+purchase deals, revenue round-trips → `ai_circularity` +1,
  type `market_flow`, manipulation ≥ 0.4.
- **Influential figures:** the live code separately amplifies
  Powell/Trump/Xi/OPEC mentions — you don't need to do anything special
  beyond normal tagging; do NOT inflate magnitude because a famous name
  appears.

### A10. proposed_edges

Only when a story reveals a RELATIONSHIP the node list can't express (e.g.
"Taiwan drought threatens chip production" → edge `agri_food`? no —
`{"src": "geopolitical_tension", ...}`? no — a genuinely new mechanism like
water supply → semis). Rare: expect ≤1 per week. Include a one-line `why`.
Proposals are queued for human/trainer review, never auto-applied.

### A11. Validation harness (code-side, but you are graded by it)

1. **Schema + node validity** — every event parses, every node id exists.
2. **Distribution priors** — per-month: median magnitude 0.2–0.4; ≤2% of
   events ≥0.8; ≤15% touching `risk_appetite`; novelty mix roughly
   50/35/15 (1.0/0.5/0.2). Sustained deviation → prompt or model drift.
3. **Golden set** — 50 hand-tagged headlines spanning every node type and
   trap in this document; re-run after any prompt/model change; require
   ≥90% node agreement, polarity sign agreement 100%, magnitude within ±0.2.
4. **Self-consistency** — the same day digested twice must produce ≥85%
   matching (event_key, nodes, sign) tuples; lower means the prompt is
   underdetermined.
5. **Zero-event days** — a day with 0 events from ≥30 headlines is a
   failure signature (the qwen lesson): retry, then flag, never record as
   quiet.

---

## PART B — The Formula Improvement Plan

Current state (what the numbers are today):

```
credibility = clip(0.15 + 0.45·trust + 0.15·min(corr,2)/2 + 0.1·official − 0.5·manip − 0.15·hype)
impulse     = polarity · magnitude · credibility · confidence
field       += propagate(impulses, hops=3, decay=0.5); field *= per-type half-life decay
score       = w_field·field_impact + w_formula·price_formula   (entry: |score| ≥ bar)
```

Every change below is a **candidate**, implemented as a trainer round and
adopted only if it survives the train→holdout gate under evidence protocol
v2. Numbers in brackets are starting values for the search, not decisions.

### B1. Impulse-level upgrades

- **R16 Novelty decay (needs the digester's `novelty` field).**
  `impulse ×= novelty`. Kills the multi-day story-cycle double-counting that
  currently lets a one-week narrative hit the web seven times at full
  strength. Search: use novelty as-is vs. `novelty^γ`, γ ∈ [0.5, 2].
- **R17 Corroboration scaling.** Replace the capped 0–2 count with
  `log(1+n_sources) / log(1+8)` — smooth, and Guardian+GDELT+wiki now give
  a real n to count. Search: reference count 4–16.
- **R18 Surprise separation for scheduled events.** The digester already
  encodes surprise in magnitude (A4); add an event-type flag so scheduled
  releases (type `monetary_policy` with in-line outcome) get a floor of
  near-zero impulse instead of riding a mistagged 0.3.
- **R19 Event-type half-lives.** The field currently decays per NODE type.
  Add per EVENT type persistence: monetary policy/regulation shocks decay
  slowly [half-life ×2], rumor/hype and market_flow fast [×0.5], measured by
  event-study fit (below), searched around those priors.

### B2. Calibration — fitting magnitude to reality (the "update the numbers" step)

After the Guardian re-digestion, run an **event study on the TRAIN window
only** (`research/event_study.py` exists as a base):

1. For each (event type, node type) bucket: regress next-5d abnormal return
   of exposed assets on the impulse delivered. Slope β_bucket = how much a
   unit of tagged impulse actually moved things.
2. Rescale: `impulse ×= shrink(β_bucket / β_median)`, shrunk toward 1 with
   empirical-Bayes weight by bucket sample size (buckets with <30 events
   stay at 1.0). This converts the digester's subjective scale into a
   market-calibrated one WITHOUT per-event hindsight (bucket-level, train
   window only).
3. The trainer validates the rescaled table on holdout as round **R20**.

### B3. Propagation upgrades

- **R21 Learned edge weights.** The 344 edge weights are hand-authored 2026
  priors — a hindsight liability. Re-fit: ridge regression of asset forward
  returns on origin-node impulses over the TRAIN window, with the seed
  weights as the prior mean (strong shrinkage λ; the seed graph is the
  regulariser, not the answer). Sign flips forbidden — an edge that wants
  to flip sign is set to 0 and logged for review. Holdout-gated.

### B4. Score, sizing, and portfolio upgrades

- **R22 Probability calibration + Kelly-capped sizing.** Fit logistic
  P(5d return > 0 | score) on train; enter only when calibrated edge > cost
  hurdle; size = min(current vol-target size, ¼-Kelly from calibrated edge).
  Fixes: score magnitude currently informs sizing only via a crude `|score|·0.3`.
- **R23 Correlated-ripple exposure cap.** All positions opened from the same
  origin impulse (same event_key ancestry, or field-correlation > 0.7) share
  a budget: aggregate risk from one story ≤ 1.5× single-position risk. This
  is the fix for the "12 positions = one AI bet wearing 12 hats" failure.
- **R24 Objective repair — stop sacrificing the stock book.** v2 cycles
  showed the optimizer feeding crypto while continuous stock CAGR went
  negative (cycle 13: −2.9% stocks / +63% crypto). Two changes:
  (a) benchmark-relative objective — reward `(stock_cagr − SPY_cagr)` and
  `(crypto_cagr − BTC_hodl_cagr)` instead of raw CAGRs, so beta stops being
  bought as alpha; (b) adopt a candidate only if NEITHER book's holdout
  objective degrades >1pt (two one-sided gates instead of one blended one).
- **R25 HWM ratchet valve (requires user sign-off — mandate change).** The
  monthly high-water-mark ratchet caused the fresh-start vs continuous gap
  (+20% vs +3.2%): one boundary drawdown blocks entries for months. Proposal
  keeping the spirit of the rule: the locked base decays toward current
  equity at 2%/month while blocked, so a lockout self-heals in ≤5 months;
  the 10% per-position hard rule is untouched.

### B5. Statistical rigor (applies to every round above)

- Bootstrap (block, 21-day) CIs on train AND holdout objectives; adopt only
  when the improvement's 80% CI excludes zero on train.
- Deflated-Sharpe check at each cycle end against the number of candidates
  tried that cycle (the walk-forward optimizer already has the machinery in
  `backtest/walkforward.py` — reuse it).
- The lockbox stays sealed through ALL of R16–R25. It is spent once, when a
  final config is frozen for paper deployment.

### B6. Execution order

```
1. Guardian backfill completes          (running — data/news_archive_guardian.jsonl)
2. Digester AI re-digests 2023→today    (Sonnet, batched; new file news_impulses_v2.jsonl;
   using THIS curriculum                 the qwen v1 file is preserved for A/B)
3. Validation harness on the digest     (A11: schema, distributions, golden set)
4. Event-study calibration on train     (B2 → impulse scale table)
5. Trainer rounds R16→R25, holdout-gated, v2 physics
6. A/B report: v1-digest incumbent vs v2-digest challenger, same windows
7. Freeze → run --lockbox ONCE → paper-live with the scorecard
```

**Honesty note for the record:** re-digesting history with a newer model
worsens the hindsight-leak caveat (Sonnet knows 2023–2026 better than qwen
did). A8 is the mitigation, the golden-set audit is the check, and the
forward paper test remains the only proof this document trusts.
