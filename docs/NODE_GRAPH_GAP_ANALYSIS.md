# Node Graph Gap Analysis

*Compiled 2026-07-29, updated continuously as digestion proceeds past
2023-08-09. Every gap below is backed by specific stories that were skipped
or force-tagged to an imperfect proxy node during actual digestion runs —
see `data/digest_v2/events/*.json` for the receipts, dated inline. Schema
grounding (Node/Edge dataclasses, SEED_VERSION mechanism, current 173-node
graph) verified directly against `engine/ai_investing/brain/seed.py`,
`graph.py`, and `data/knowledge_graph.json`; re-verify field names against
those files before implementing, in case the schema has since evolved.*

## How to read this document

For each proposed node I give: the exact `Node` dataclass fields (per
`engine/ai_investing/brain/graph.py`), the digester-facing "+1 means"
definition (the format used in `SONNET_DIGEST_BRIEF.md` §7), and proposed
`Edge` entries in the same fields the graph actually uses (`src, dst, type,
sign, weight, confidence, note`). **All nodes below are considered
must-build** — none are optional or "nice to have." Each is backed by a
recurring pattern of real stories with no clean home, not a one-off. Where
a node's supporting evidence is currently thinner than another's, I say so
explicitly, but thinner evidence today just means "watch this node's
recurrence count as digestion continues" (see the Digestion Log at the
bottom, which I'm updating as I keep going) — it does not mean deprioritize
the design work now.

**Implementation path**: per `graph.py`'s `_merge_seed()`, the *only*
current mechanism for adding a genuinely new node is manual — bump
`SEED_VERSION` in `seed.py`, add the node to `SEED_NODES` and its edges to
`SEED_EDGES`, and the next `KnowledgeGraph.load()` merges it in while
preserving any LLM-proposed edges already recorded. The digester's
`proposed_edges` mechanism (§12 of the brief) **cannot** create new nodes —
`KnowledgeGraph.propose_edge()` requires both `src` and `dst` to already
exist (`graph.py`, `propose_edge()`: `if src not in self.nodes or dst not
in self.nodes ... return False`). Every node below therefore requires a
manual seed.py edit; the digester can only be *told* to use the new id once
it exists and is added to §7 of the brief.

---

## Political & macro nodes

### 1. `political_stability` — the single biggest fix available

**This is the actual root cause of the `geopolitical_tension` over-concentration
flagged in both audits** (47% at the 40-day headline-only checkpoint, still
43.6% after the v1.2 redo). `geopolitical_tension`'s own definition in the
brief is explicitly conflict-oriented — "Tension ESCALATING (strikes,
mobilization, ultimatums). De-escalation = −" — a war/inter-state framing.
But roughly half of what got tagged there this run was actually **domestic
institutional crisis**, a different phenomenon with different market
transmission (currency/capital-flight risk, EM sovereign risk, not
munitions and troop movements):

- Wagner mutiny aftermath (6 separate events, 2023-07-01 → 07-22): Putin
  admitting Wagner funding, Prigozhin's return, Girkin's arrest, a general
  fired for criticizing command — all Russian *regime* stability, zero
  battlefield content.
- Niger coup (7 events across the batch) — dual-tagged to `uranium_price`
  correctly, but the tension side is a coup, not a war.
- Dutch government collapse (2023-07-08), Spain's hung parliament
  (2023-07-23), France's riots (2023-07-01 → 07-04), Israel's judicial
  overhaul passing into law (2023-07-24) — all domestic governance crises
  in G7/G20 economies, none of them inter-state conflict.
- Navalny's 19-year sentence (2023-08-04), Qin Gang's disappearance from
  China's foreign ministry (mentioned but skipped for lack of a home) —
  authoritarian-regime elite instability.

None of these belong under a node whose worked example in the brief is "an
Iran launches direct missile attack on Israel." Splitting them out is the
single change most likely to move the novelty/magnitude distribution
health metrics the validator checks.

```python
{"id": "political_stability", "type": "factor", "label": "Political & institutional stability",
 "aliases": ["coup", "government collapse", "civil unrest", "political crisis",
             "leadership purge", "hung parliament", "state of emergency",
             "no-confidence vote", "mutiny"],
 "equilibrium": "stable governance and orderly transitions; deteriorating = "
                 "coups, mass unrest, contested power, purges"},
```

**+1 means** (for §7 of the brief): domestic political/institutional
stability DETERIORATING in a country that matters to markets — coups,
government collapse, mass civil unrest, contested elections, elite purges,
leadership crises. Stabilization/orderly resolution = −1. This is
origin-only exactly like `geopolitical_tension`: tag the country experiencing
the instability, not downstream markets that react to it.

**Disambiguation rule to add to the brief** alongside this node: if the
story is armed conflict between or threatened by state actors (invasions,
strikes, troop mobilizations, sanctions, alliance moves), it's
`geopolitical_tension`. If it's a government falling, a coup, mass unrest,
or elite-level regime instability with no active military conflict, it's
`political_stability`. Dual-tag when a story is genuinely both (e.g. a coup
that immediately triggers a military intervention threat, as Niger did on
2023-07-31 with Ecowas's ultimatum — that event legitimately carries both).

Proposed edges (curated, `provenance: "seed"`, confidence 1.0):

```python
{"src": "political_stability", "dst": "risk_appetite", "type": "influences",
 "sign": -1, "weight": 0.3, "confidence": 1.0,
 "note": "governance crises dampen broad risk appetite"},
{"src": "political_stability", "dst": "em_flows", "type": "influences",
 "sign": -1, "weight": 0.4, "confidence": 1.0,
 "note": "coups/unrest in EM and frontier economies drive capital flight"},
{"src": "political_stability", "dst": "usd_strength", "type": "influences",
 "sign": 1, "weight": 0.15, "confidence": 1.0,
 "note": "global instability drives modest dollar safe-haven demand"},
```

No direct asset edges — this node's job is macro propagation, same as
`geopolitical_tension` itself (which also has no direct `member_of` asset
children in the current graph).

---

### 2. `boe_rate` — UK's missing monetary-policy origin node

Every UK rate story this run — the BoE's July MPC decision, the August
5.25% hike with "high for two years" guidance, UK CPI prints, TUC calls to
halt hikes — got jammed into `credit_conditions`, which is meant to be a
**global lending-standards/spreads gauge**, not a country-specific
policy-rate node. The graph already has this exact pattern for three other
central banks (`fed_rate`, `ecb_policy`, `pboc_rate`) but nothing for the
BoE despite the UK being a G7 economy with its own currency, its own
10-year gilt market, and rate decisions that move GBP and gilts
independently of the Fed and ECB. This was the single node I reached for
`credit_conditions` as a substitute most often — 23 of 204 events in this
batch used `credit_conditions`, and a majority of those were really BoE
policy-cycle stories (the hikes themselves, hawkish guidance, CPI-driven
rate-expectation shifts) rather than credit-market-conditions stories
(mortgage arrears, approvals, insolvencies) that legitimately belong there.

```python
{"id": "boe_rate", "type": "factor", "label": "BoE policy rate",
 "aliases": ["bank of england", "boe", "mpc", "monetary policy committee",
             "uk interest rate", "bank rate", "andrew bailey", "uk rate rise",
             "uk rate cut"],
 "equilibrium": "neutral ~3-4%; far above = restrictive (mortgage/credit "
                 "stress), far below = stimulative"},
```

**+1 means**: BoE TIGHTENING (hike, hawkish guidance, hot UK CPI surprise
that raises rate expectations). Cut/dovish guidance/cooler-than-expected UK
CPI = −1. Same convention as `fed_rate`/`ecb_policy`/`pboc_rate` exactly.

With this node added, the division of labor becomes clean: `boe_rate` for
MPC decisions and UK CPI surprises (the *origin*); `credit_conditions`
stays for the *downstream* consequences — mortgage rate moves, approvals,
arrears, insolvencies, house-price data — since those are effects of
`boe_rate` (and of bank-level decisions), not the policy act itself. That
mirrors how `us_inflation` and `fed_rate` are already kept as siblings
rather than one node absorbing both the data and the policy reaction.

Proposed edges:

```python
{"src": "boe_rate", "dst": "credit_conditions", "type": "influences",
 "sign": 1, "weight": 0.6, "confidence": 1.0,
 "note": "BoE hikes/hawkish guidance tighten UK credit conditions with a lag"},
{"src": "boe_rate", "dst": "usd_strength", "type": "influences",
 "sign": -1, "weight": 0.15, "confidence": 1.0,
 "note": "GBP strength vs USD on hawkish BoE surprises is a modest drag on dollar-strength readings"},
{"src": "boe_rate", "dst": "uk_banks", "type": "influences",
 "sign": 1, "weight": 0.4, "confidence": 1.0,
 "note": "higher rates initially expand UK bank net interest margins (see node #3)"},
```

**Optional companion, lower priority**: a standalone `uk_inflation` factor
(mirroring the `us_inflation`/`fed_rate` split) is defensible for symmetry,
but Europe itself doesn't get this treatment either (`ecb_policy` alone
covers both ECB decisions and eurozone CPI reactions in current practice) —
so I'd only add `uk_inflation` if the trainer later finds `boe_rate` alone
is absorbing too many distinct signals. Don't add both up front.

---

## Financial-sector nodes

### 3. `uk_banks` — no home for a systemically important sector

The taxonomy has `sg_banks` (Singapore) and `us_financials` (US) but
nothing for UK banking, despite HSBC, Barclays, Lloyds, NatWest and
Standard Chartered being globally systemically important institutions.
This gap cost real signal, not administrative tidiness: the NatWest/Coutts
CEO scandal wiped **£1bn off NatWest's market cap** in a single week
(2023-07-25 → 07-27) and I skipped it every single day it recurred — Alison
Rose's resignation, Coutts CEO Peter Flavel's resignation, the Home Office
minister summoning bank bosses — because there was nowhere to put a story
whose entire content *is* "a UK bank's equity moved a billion pounds on
governance risk." Also skipped or force-tagged to `credit_conditions`:
HSBC's H1 profit doubling to £17bn, Lloyds setting aside £400m+ for
mortgage arrears, Wilko's near-collapse (not strictly a bank, but the same
"no UK company-distress node" problem), FCA's "robust action" threats
against banks over savings rates.

```python
{"id": "uk_banks", "type": "theme", "label": "UK banks",
 "aliases": ["hsbc", "barclays", "lloyds", "natwest", "standard chartered",
             "coutts", "nationwide", "santander uk", "royal bank of scotland",
             "rbs"]},
```

**+1 means**: UK banking sector business prospects improving — earnings
beats, capital returns, credit quality improving, resolved governance
crises. Deteriorating = −1 (earnings misses, governance/reputational
crises with quantified market impact, regulatory censure, capital-return
suspensions). Company-specific stories only qualify when they have a real,
stated market-cap or profit figure attached (the NatWest £1bn wipeout
qualifies; a single branch-closure story would not) — same
bellwether-framing discipline the brief already applies to single-company
theme tagging (§7, "Tag a theme as origin ONLY for industry-level news, or
company news that is a read-through for the whole industry").

Proposed edges:

```python
{"src": "boe_rate", "dst": "uk_banks", "type": "influences", "sign": 1,
 "weight": 0.4, "confidence": 1.0, "note": "see boe_rate entry above"},
{"src": "uk_banks", "dst": "risk_appetite", "type": "influences", "sign": -1,
 "weight": 0.15, "confidence": 1.0,
 "note": "systemic-bank distress is a mild risk-off signal"},
{"src": "uk_banks", "dst": "xlf", "type": "correlates_with", "sign": 1,
 "weight": 0.35, "confidence": 1.0,
 "note": "no UK bank asset exists yet in the graph; US financials ETF is the "
         "best available correlated proxy until UK/HK-listed bank assets are added (see Asset-Coverage Gap below)"},
```

---

## Consumer & travel nodes

### 4. `travel_leisure` — a whole macro-cyclical theme with no home

Post-COVID travel recovery was one of the defining 2023 consumer-discretionary
stories and it had nowhere to go. Skipped repeatedly: easyJet's record £200m
quarterly profit (2023-07-20), IAG/British Airways' record H1 profit
(2023-07-28), Ryanair's profit nearly quadrupling to €663m (2023-07-24),
Heathrow halving its losses on a 42% passenger rebound (2023-07-26), Tui's
return to profit (2023-08-09). Worse, I *mistagged* Rolls-Royce's earnings
twice (2023-07-26, 2023-08-03) to `defense_industry` because its
civil-aviation engine-servicing business — explicitly described in the
source headlines as riding a "boom in travel" — had no better home; that's
a real tagging error this node would fix, not just a coverage gap.

```python
{"id": "travel_leisure", "type": "theme", "label": "Travel & leisure",
 "aliases": ["airlines", "easyjet", "ryanair", "iag", "british airways",
             "heathrow", "tui", "aviation", "hotels", "cruise lines",
             "airbnb", "booking.com"]},
```

**+1 means**: travel/leisure industry business prospects improving —
passenger demand, fares, load factors, profits rising. Deteriorating = −1
(demand collapse, fare wars, capacity cuts, wildfire/strike-driven
cancellations with a quantified financial hit).

Proposed edges:

```python
{"src": "oil_price", "dst": "travel_leisure", "type": "influences", "sign": -1,
 "weight": 0.4, "confidence": 1.0,
 "note": "jet fuel is a major airline input cost"},
{"src": "us_consumer", "dst": "travel_leisure", "type": "influences", "sign": 1,
 "weight": 0.3, "confidence": 1.0,
 "note": "discretionary travel demand tracks consumer strength"},
{"src": "travel_leisure", "dst": "vgk", "type": "correlates_with", "sign": 1,
 "weight": 0.3, "confidence": 1.0,
 "note": "no dedicated travel asset in the graph; European equities ETF is the closest proxy"},
```

Also **reclassify** `rolls-royce-h1-2023-earnings` (both 2023-07-26 and
2023-08-03 events, currently tagged `defense_industry`) to
`["travel_leisure", "defense_industry"]` — Rolls-Royce genuinely straddles
both (civil aviation engines + military engines), and the July/August 2023
story was explicitly about civil-aviation-driven pricing power.

---

## Energy & industrial nodes

These four — `offshore_wind`, `telecom_equipment`, `freight_logistics`,
and strengthening `solar`'s existing edges — all address the same class of
problem: distinct, investable industrial supply chains that the current
graph flattens into a catchall (`energy_transition`, `europe_equities`, or
a labor-market node respectively) even though each has its own economics,
its own inputs, and its own bellwether companies. They are treated with
full first-class specs below, not as an afterthought.

### 5. `offshore_wind` — distinct economics from `solar`, no node of its own

Flagged in the prior (headline-only) 40-day audit and confirmed again in
the v1.2 redo: Vattenfall halting its giant Norfolk windfarm over costs
"up 40% due to rise in global gas prices" (2023-07-20), Hornsea Four's
approval after a five-month delay (2023-07-12), Dogger Bank's first
turbines going in at what will be the world's biggest offshore project
(2023-08-03), and UK energy firms warning offshore wind is at a funding
"tipping point" (2023-08-05) all went to `energy_transition`, the generic
transition-positive/negative catchall.

This is more than a labeling nicety. `solar` already exists as its own
theme with its own dedicated asset children (`fslr`, `jks`, `longi`, `tan`)
precisely *because* solar has different economics from other renewables —
polysilicon/silver input costs, a China-dominated supply chain, panel
pricing cycles. Offshore wind's economics are genuinely different again:
steel and turbine-component costs (not silicon), *gas-price-linked*
project economics (Vattenfall's own stated reason for halting Norfolk was
gas prices, not silver or polysilicon), multi-year permitting risk, and a
different set of bellwether companies (Ørsted, Vattenfall, Siemens Energy,
SSE) than solar's (First Solar, JinkoSolar, LONGi). Routing offshore-wind
news through `energy_transition` means a gas-price-driven wind-project
cancellation gets the same generic treatment as a subsidy announcement,
losing the actual causal mechanism a trader would want to see propagate.

```python
{"id": "offshore_wind", "type": "theme", "label": "Offshore wind",
 "aliases": ["wind farm", "windfarm", "vattenfall", "orsted", "ørsted",
             "dogger bank", "hornsea", "siemens energy", "sse renewables"]},
```

**+1 means**: offshore wind industry prospects improving — project
approvals, turbine installations, cost declines, capacity additions,
successful auctions. Deteriorating = −1 (project cancellations/delays,
cost overruns tied to input prices, failed subsidy auctions, funding
shortfalls).

Proposed edges (mirroring `solar`'s existing edge structure in the graph
— see `energy_transition → solar`, `silver_price → solar` — so the two
renewables themes are treated as structural siblings, not solar-plus-an-afterthought):

```python
{"src": "energy_transition", "dst": "offshore_wind", "type": "influences",
 "sign": 1, "weight": 0.6, "confidence": 1.0,
 "note": "mirrors the existing energy_transition -> solar edge weight exactly"},
{"src": "natural_gas", "dst": "offshore_wind", "type": "influences",
 "sign": -1, "weight": 0.4, "confidence": 1.0,
 "note": "turbine/project costs are gas-price-linked (Vattenfall's stated reason for halting Norfolk, 2023-07-20); "
         "also gas-price spikes make wind more competitive on the demand side, but the dominant 2023 story was the cost-side drag"},
{"src": "copper_price", "dst": "offshore_wind", "type": "influences",
 "sign": -1, "weight": 0.3, "confidence": 1.0,
 "note": "offshore wind is copper-intensive (subsea cabling, generators); mirrors energy_transition -> copper_price already in the graph"},
{"src": "offshore_wind", "dst": "solar", "type": "correlates_with", "sign": 1,
 "weight": 0.25, "confidence": 1.0,
 "note": "both are renewables-policy-sensitive, but weight is kept low precisely because their cost drivers diverge (gas/steel vs silicon/silver) — this is the whole point of splitting them"},
```

No current asset children — see the Asset-Coverage Gap section for
candidate additions (Ørsted, Vattenfall, Siemens Energy are all
foreign-listed without US ADRs I'm highly confident of, so I'm not
proposing tickers here without verification; flag for the data-provider
check rather than guessing).

---

### 6. `telecom_equipment` — Nokia/Ericsson's shared profit warning deserved a real node

Nokia and Ericsson's simultaneous profit warning (2023-07-14, "cost of
living crisis hits telecoms sales," Nokia cutting guidance, Ericsson
flagging flat-to-up margins at best) is a textbook industry-wide
read-through story — the brief's own bellwether-framing rule (§7: "one
company... unless it is a bellwether AND the story frames it that way")
is explicitly satisfied here, by *two* of the industry's three global
equipment makers reporting the same weakness the same day. I routed it to
`europe_equities` for lack of anything closer, which captures "this is bad
for European stocks broadly" but completely loses the actual mechanism —
this was a **5G capex-cycle slowdown** story (telcos delaying network
buildout spend as their own margins compress), not a generic European
macro story. `europe_equities` gets this signal diluted alongside
completely unrelated European sectors (luxury, autos, banks) instead of
isolated as its own capex-cycle indicator.

This matters more than a single incident suggests: telecom
infrastructure capex is a genuine macro-relevant cycle (5G rollout pacing,
carrier capex guidance, spectrum auctions) that sits structurally adjacent
to two cycles the graph *already* tracks carefully — `ai_capex_cycle` and
`power_demand` — since modern network buildout and datacenter/edge
infrastructure investment increasingly move together. A dedicated node
lets that adjacency actually propagate instead of being lost inside a
country-equities catchall.

```python
{"id": "telecom_equipment", "type": "theme", "label": "Telecom equipment",
 "aliases": ["nokia", "ericsson", "huawei", "zte", "5g", "network equipment",
             "base stations", "telecom infrastructure", "radio access network",
             "ran equipment"]},
```

**+1 means**: telecom/network equipment industry prospects improving —
carrier capex guidance rising, 5G rollout accelerating, order books
growing, margins expanding. Deteriorating = −1 (carrier capex cuts, profit
warnings, order deferrals, price competition from Chinese vendors
squeezing margins).

Proposed edges:

```python
{"src": "telecom_equipment", "dst": "europe_equities", "type": "correlates_with",
 "sign": 1, "weight": 0.3, "confidence": 1.0,
 "note": "Nokia/Ericsson are European-listed bellwethers; keeps a link to the existing catchall without the two being conflated"},
{"src": "ai_capex_cycle", "dst": "telecom_equipment", "type": "influences",
 "sign": 1, "weight": 0.25, "confidence": 1.0,
 "note": "network and AI/datacenter infrastructure capex cycles move together as edge-compute buildout scales"},
{"src": "power_demand", "dst": "telecom_equipment", "type": "influences",
 "sign": 1, "weight": 0.2, "confidence": 1.0,
 "note": "denser 5G networks and edge infrastructure add to grid-load buildout, same demand-side logic as the existing power_demand -> uranium_price edge"},
{"src": "china_export_controls", "dst": "telecom_equipment", "type": "influences",
 "sign": 1, "weight": 0.3, "confidence": 1.0,
 "note": "Huawei/ZTE export restrictions directly reshape market share for the Western equipment makers"},
```

No current asset children — Nokia and Ericsson both trade as US ADRs
(`NOK`, `ERIC`) and would be strong first candidates; see Asset-Coverage
Gap section.

---

### 7. `freight_logistics` — the capacity-side twin of `shipping_costs`

Yellow Corp's collapse (30,000 US jobs, one of the largest single-employer
shutdowns in US history, 2023-07-31) went to `us_employment`, which
captures the labor-market fact but misses the actually-tradeable
mechanism: a major freight carrier ceasing operations removes real
trucking/logistics *capacity* from the market, which is a supply-side
event with the same shape as an oil-supply cut — and the existing graph
already has exactly that pattern for oil (`oil_supply`, a factor tracking
*volume/capacity*, feeding into `oil_price`, a commodity tracking the
*price* effect, via `oil_supply -> oil_price, sign: -1, weight: 0.7`). My
original write-up suggested just stretching `shipping_costs`'s brief-text
guidance to cover capacity-destruction stories, but on reflection that
conflates two distinct measurable things the same way tagging oil-supply
news straight to `oil_price` would — the brief is explicit that the two
must stay separate ("Note the division of labor: OPEC/policy/supply news →
`oil_supply`... an oil PRICE move without a taggable cause → `oil_price`.
Never tag both for the same story"). Freight deserves the same
supply/price split, not a guidance patch onto the price side alone.

```python
{"id": "freight_logistics", "type": "factor", "label": "Freight & logistics capacity",
 "aliases": ["trucking", "freight", "logistics", "supply chain capacity",
             "port congestion", "rail freight", "teamsters", "ups", "fedex",
             "container shipping"],
 "equilibrium": "balanced capacity and throughput; deteriorating = carrier "
                 "bankruptcies, port/rail congestion, capacity-destroying strikes"},
```

**+1 means**: MORE freight/logistics capacity available — new carrier
entrants, capacity expansion, smooth port/rail throughput, resolved
strikes. LESS capacity = −1 (carrier bankruptcies like Yellow's, port
congestion, capacity-destroying strikes, rail service disruptions). This
mirrors `oil_supply`'s convention exactly (more supply = +1) so the
downstream price relationship reads the same way.

Proposed edges (mirroring `oil_supply → oil_price` exactly):

```python
{"src": "freight_logistics", "dst": "shipping_costs", "type": "influences",
 "sign": -1, "weight": 0.6, "confidence": 1.0,
 "note": "mirrors oil_supply -> oil_price (sign -1, weight 0.7): less freight capacity pushes freight rates up"},
{"src": "freight_logistics", "dst": "us_employment", "type": "influences",
 "sign": 1, "weight": 0.2, "confidence": 1.0,
 "note": "major carrier bankruptcies are also a direct, quantified labor-market event (Yellow: 30,000 jobs) — "
         "kept as a secondary link so the jobs angle isn't lost, without making freight_logistics itself an employment node"},
{"src": "freight_logistics", "dst": "global_growth", "type": "influences",
 "sign": 1, "weight": 0.2, "confidence": 1.0,
 "note": "smooth freight throughput is a mild growth tailwind, same direction as the existing shipping_costs -> global_growth edge (sign -1 there since that one is price-framed)"},
```

**Dual-tagging guidance for the brief**: a major carrier bankruptcy/capacity
event like Yellow's should be tagged `["freight_logistics", "us_employment"]`
— the capacity fact is the origin-side mechanism, the job-loss count is a
distinct, separately quantified fact worth carrying (same logic as the
brief's own worked example (e) for TSMC, where two nodes are legitimately
both origins of the same event).

No current asset children — no pure-play US-listed trucking/logistics name
was in the checked asset list (`UPS`/`FDX` are large-cap and liquid;
strong first candidates, see Asset-Coverage Gap section).

---

### 8. Strengthening `solar`'s existing relationships

`solar` already exists and is reasonably well-built — it has four asset
children (`fslr`, `jks`, `longi`, `tan`) and two inbound edges
(`energy_transition → solar`, `silver_price → solar`, the latter
correctly signed negative as an input-cost squeeze). It doesn't need
rescuing the way the other three nodes above did. But two structural gaps
are worth closing now that `offshore_wind` is being added as its sibling,
so the two nodes reinforce rather than compete with each other:

1. **No edge from `natural_gas` to `solar`.** Gas prices are a real
   demand-side driver for solar adoption (higher gas prices make solar
   more competitive), the mirror image of the `natural_gas → offshore_wind`
   cost-side edge proposed above. Missing this means the graph currently
   treats solar as insulated from the energy-price cycle that visibly
   drove wind-project economics in this exact period (summer 2023 gas
   prices).
2. **No `correlates_with` link between `solar` and `offshore_wind`**
   (added above, weight kept deliberately low at 0.25) so the two
   renewables themes move somewhat together on broad
   policy/subsidy/political-will news (e.g. a government "maxing out"
   fossil-fuel reserves, as Sunak did 2023-07-31, is bearish for *both*)
   without being conflated on the cost-driver news that should move them
   independently (gas prices for wind, silver/polysilicon for solar).

Proposed additional edge:

```python
{"src": "natural_gas", "dst": "solar", "type": "influences", "sign": 1,
 "weight": 0.2, "confidence": 1.0,
 "note": "higher gas prices improve solar's relative competitiveness on the demand side; "
         "mirror of the cost-side natural_gas -> offshore_wind edge, kept at lower weight since solar's own input-cost story (silver/polysilicon) dominates its price action more than gas does"},
```

---

## Asset-Coverage Gap — the deeper structural issue

Before any of the theme nodes above (`uk_banks`, `travel_leisure`,
`offshore_wind`, `telecom_equipment`, `freight_logistics`) can do more than
route signal through weak `correlates_with` proxies, it's worth being
honest about what they'd actually *drive*. I checked the live asset
universe in `data/knowledge_graph.json` (88 assets, `type: "asset"`):

```
US: 48   HK: 21   SG: 5   EU: 3 (adidas, lvmh, prosus)   JP: 2   KR: 2   TW: 1   CN: 3   CRYPTO: 3
```

**There are zero UK-listed or UK-domiciled assets in the graph today** —
not HSBC, not Shell, not BP, not AstraZeneca, nothing. The `EU` market
bucket has exactly three names (Adidas, LVMH, Prosus), none of them UK, and
nothing in telecom equipment or freight/logistics either. This means the
new nodes above would currently have no direct `member_of` children to
propagate impact onto — they'd only reach the portfolio via
`correlates_with` edges to `xlf`/`vgk`, a real but blunt instrument.

The good news: **most large UK and telecom/logistics blue-chips already
trade as US ADRs or are US-domiciled outright**, so closing this gap
doesn't require inventing a new `market` value or new data-provider
plumbing — it's the same pattern already used for `tsmc` (Taiwan Semi,
trades as a US ADR under symbol `TSM`, `market: "US"`). Candidate
additions, in the existing `Node` schema, grouped by which theme they'd
feed:

```python
# uk_banks
{"id": "hsbc", "type": "asset", "label": "HSBC", "symbol": "HSBC", "market": "US",
 "aliases": ["hsbc holdings"]},
{"id": "barclays", "type": "asset", "label": "Barclays", "symbol": "BCS", "market": "US"},
{"id": "lloyds", "type": "asset", "label": "Lloyds Banking Group", "symbol": "LYG", "market": "US"},
{"id": "natwest", "type": "asset", "label": "NatWest Group", "symbol": "NWG", "market": "US"},

# energy_sector (UK majors, not yet covered)
{"id": "shell", "type": "asset", "label": "Shell", "symbol": "SHEL", "market": "US",
 "aliases": ["royal dutch shell"]},
{"id": "bp", "type": "asset", "label": "BP", "symbol": "BP", "market": "US"},

# healthcare (UK majors, not yet covered)
{"id": "astrazeneca", "type": "asset", "label": "AstraZeneca", "symbol": "AZN", "market": "US"},
{"id": "gsk", "type": "asset", "label": "GSK", "symbol": "GSK", "market": "US",
 "aliases": ["glaxosmithkline"]},

# consumer_staples (UK majors, not yet covered)
{"id": "unilever", "type": "asset", "label": "Unilever", "symbol": "UL", "market": "US"},
{"id": "diageo", "type": "asset", "label": "Diageo", "symbol": "DEO", "market": "US"},

# defense_industry (UK, not yet covered)
{"id": "bae_systems", "type": "asset", "label": "BAE Systems", "symbol": "BAESY", "market": "US"},

# telecom_equipment — no current member_of children at all
{"id": "nokia", "type": "asset", "label": "Nokia", "symbol": "NOK", "market": "US"},
{"id": "ericsson", "type": "asset", "label": "Ericsson", "symbol": "ERIC", "market": "US"},

# freight_logistics — no current member_of children at all
{"id": "ups", "type": "asset", "label": "United Parcel Service", "symbol": "UPS", "market": "US"},
{"id": "fedex", "type": "asset", "label": "FedEx", "symbol": "FDX", "market": "US"},

# travel_leisure — no current member_of children at all
{"id": "delta", "type": "asset", "label": "Delta Air Lines", "symbol": "DAL", "market": "US"},
{"id": "booking_holdings", "type": "asset", "label": "Booking Holdings", "symbol": "BKNG", "market": "US"},
```

(Tickers as of my knowledge cutoff — verify against the live data provider
before adding; ADR programs occasionally change or get delisted. Ørsted,
Vattenfall and Siemens Energy — the natural `offshore_wind` bellwethers —
are deliberately omitted here because I'm not confident they carry liquid
US ADRs; check the data provider directly rather than trust my guess on
those three specifically.)

Companion `member_of` edges once these exist, e.g.:
```python
{"src": "hsbc", "dst": "uk_banks", "type": "member_of", "sign": 1, "weight": 0.8, "confidence": 1.0},
{"src": "barclays", "dst": "uk_banks", "type": "member_of", "sign": 1, "weight": 0.8, "confidence": 1.0},
{"src": "shell", "dst": "energy_sector", "type": "member_of", "sign": 1, "weight": 0.7, "confidence": 1.0},
{"src": "bp", "dst": "energy_sector", "type": "member_of", "sign": 1, "weight": 0.7, "confidence": 1.0},
{"src": "nokia", "dst": "telecom_equipment", "type": "member_of", "sign": 1, "weight": 0.85, "confidence": 1.0},
{"src": "ericsson", "dst": "telecom_equipment", "type": "member_of", "sign": 1, "weight": 0.85, "confidence": 1.0},
{"src": "ups", "dst": "freight_logistics", "type": "member_of", "sign": 1, "weight": 0.8, "confidence": 1.0},
{"src": "fedex", "dst": "freight_logistics", "type": "member_of", "sign": 1, "weight": 0.8, "confidence": 1.0},
{"src": "delta", "dst": "travel_leisure", "type": "member_of", "sign": 1, "weight": 0.7, "confidence": 1.0},
{"src": "booking_holdings", "dst": "travel_leisure", "type": "member_of", "sign": 1, "weight": 0.6, "confidence": 1.0},
```

I'd treat asset additions as a separate decision from the node additions
themselves — the nodes are worth building regardless (they fix real
tagging errors and concentration problems even with only
`correlates_with` propagation), but pairing each with at least 2 real
`member_of` children is what turns "correctly tagged" into "actually
moves a position."

---

## Sanctioned-economy stress

### 10. `sanctioned_economy_stress` — promoted from "watching" after a third recurrence

Flagged 2023-08-14 as a one-off (Russia's rouble hitting a 17-month low,
forcing an extraordinary central-bank meeting) and initially left as a
watch item rather than a full proposal. By 2023-08-16 it had recurred a
third time in the same week (the emergency 3.5pp hike to 12% on
2023-08-15, then Putin weighing capital controls on 2023-08-16) —
enough to draft a full spec now rather than keep deferring it. The
underlying phenomenon is distinct from every other node currently
available: it's not `geopolitical_tension` (no military content), not
`political_stability` (no governance-crisis content — Russia's
institutions aren't unstable, its *economy* is under external pressure),
not `sanctions` (that node tracks the sanctions *policy decisions*
themselves, not their *economic effect* on the target country), and not
`usd_strength` (that's the anchored dollar-index gauge, not a
country-specific currency crisis). It's also explicitly generalizable
beyond Russia — Iran and Venezuela both run comparable sanctioned-economy
dynamics and would tag the same node.

```python
{"id": "sanctioned_economy_stress", "type": "factor", "label": "Sanctioned-economy stress",
 "aliases": ["rouble", "ruble crisis", "russian economy", "capital controls",
             "central bank of russia", "iran economy", "venezuela economy",
             "sanctions evasion economics"],
 "equilibrium": "sanctioned economies function under external constraint but "
                 "without acute crisis; deteriorating = currency collapse, "
                 "emergency rate action, capital controls, reserve depletion"},
```

**+1 means**: economic stress WORSENING inside a heavily-sanctioned economy
— currency depreciation, emergency central-bank action, capital controls,
reserve depletion, budget strain from war/isolation spending. Easing = −1
(currency stabilization, successful evasion mechanisms restoring trade
flows, sanctions relief). Origin-only: tag the sanctioned country
experiencing the stress, not the sanctioning countries' own policy
decisions (that stays on `sanctions`).

Proposed edges:

```python
{"src": "sanctions", "dst": "sanctioned_economy_stress", "type": "influences",
 "sign": 1, "weight": 0.5, "confidence": 1.0,
 "note": "tightening sanctions is a primary driver of stress in the target economy, with a lag"},
{"src": "sanctioned_economy_stress", "dst": "oil_supply", "type": "influences",
 "sign": -1, "weight": 0.25, "confidence": 1.0,
 "note": "acute stress in a major producer (Russia, Iran, Venezuela) can force output/export "
         "disruptions independent of formal OPEC+ decisions"},
{"src": "sanctioned_economy_stress", "dst": "geopolitical_tension", "type": "influences",
 "sign": 1, "weight": 0.2, "confidence": 1.0,
 "note": "acute economic stress raises the odds of desperate/escalatory state behavior (weak but real coupling)"},
```

No asset children — same propagation-only role as `political_stability`
and `geopolitical_tension`.

---

## Narrower / lower-recurrence gaps — promoted and still-watching

### 9. `uk_utilities` — **promoted from "watching" to full proposal** (2023-12-03)
Thames Water's slow-motion crisis has now cleared the bar I set for
promotion in the previous version of this document ("the moment a second
distinct utility name shows up" — see the digestion log below for the
Southern Water/South East Water/water-sector-wide evidence that's
accumulated alongside it). The trigger for promoting it today is a step
change in severity, not just recurrence: on 2023-12-03, Thames Water's own
auditors formally warned the company **could run out of money by April
2024** — this is no longer "a company under financial pressure," it's a
going-concern warning on England's largest water utility (16 million
customers), one step from a Special Administration Regime (effectively
temporary nationalization). Currently fallback-tagged `credit_conditions`,
which is the wrong home for two reasons: (1) it conflates a
sector-specific solvency crisis with generic UK lending-conditions data
(mortgage arrears, insolvency rates), exactly the overloading problem
already flagged for `boe_rate` and `political_stability`; (2) it gives the
graph no way to distinguish "UK water sector is in crisis" from "UK banks
are in crisis" even though they're structurally unrelated (regulated
monopoly infrastructure debt vs. commercial lending), which matters for
anyone trying to size a UK-infrastructure-specific position.

```python
{"id": "uk_utilities", "type": "theme", "label": "UK regulated utilities",
 "aliases": ["thames water", "southern water", "south east water",
             "united utilities", "severn trent", "anglian water",
             "ofwat", "water company", "sewage spill", "special administration regime"]},
```

**+1 means**: UK regulated-utility sector financial health improving —
successful refinancing, credit rating upgrades, regulatory settlements
that improve cash flow, resolved solvency crises. Deteriorating = −1
(going-concern warnings, credit downgrades, missed debt covenants,
nationalization/Special Administration Regime triggers, large fines with
quantified financial impact). Company-specific stories qualify under the
same bellwether-framing discipline as `uk_banks` — a single customer
complaint doesn't count, a formal auditor warning or Ofwat enforcement
action with a quantified number does.

Proposed edges:

```python
{"src": "boe_rate", "dst": "uk_utilities", "type": "influences", "sign": 1,
 "weight": 0.35, "confidence": 1.0,
 "note": "regulated utilities carry heavy floating/refinanced debt loads; higher rates directly raise their distress risk, mirroring the boe_rate -> uk_banks edge"},
{"src": "uk_utilities", "dst": "credit_conditions", "type": "influences", "sign": 1,
 "weight": 0.2, "confidence": 1.0,
 "note": "a Special Administration Regime event at a utility of Thames Water's size would be a systemic UK credit-market shock, not just a sector story"},
{"src": "uk_utilities", "dst": "risk_appetite", "type": "influences", "sign": -1,
 "weight": 0.15, "confidence": 1.0,
 "note": "a large regulated-utility failure is a mild risk-off signal for UK-exposed portfolios generally"},
```

No asset children currently in the graph (none of Thames Water, Southern
Water, or United Utilities appear to be checked in `data/knowledge_graph.json`
as of this writing — flag for the data-provider check; United Utilities and
Severn Trent are both LSE-listed and would be the natural first additions
alongside the `member_of` edge pattern used for `uk_banks`).

### 10. Narrower items still just watching (no promotion yet)
- **CBI's "material uncertainty over future"** (2023-12-04, after the
  sexual-misconduct scandal and exceptional costs) — a single lobbying
  organization, not a sector; not node-worthy on its own but consistent
  with the broader "UK institutional-governance crisis" texture running
  through this project (NatWest/Coutts, Wilko, now CBI).
- **Sellafield's hack by Russia/China-linked groups** (2023-12-04) — a
  genuinely startling story (Europe's most hazardous nuclear site,
  malware potentially still present, cover-up allegations) but a
  single-site security/infrastructure story, not an economic one; no
  clean node fits and I don't think one should be built around it unless
  a pattern of UK critical-infrastructure cyberattacks emerges.

### 11. `commercial_aerospace` — **promoted from "watching" to full proposal** (2024-02-05)
Flagged as a watch item on 2024-01-06/07 (Alaska Airlines 737 MAX 9
door-plug blowout, FAA grounding) with an explicit note that a single
incident wasn't enough to promote — the trigger I set was recurrence, not
severity. That trigger has now fired. In the four weeks since: (1) the
FAA opened a formal inquiry (1-11); (2) United and Alaska found loose
bolts on multiple in-service MAX 9 aircraft during inspection (1-09); (3)
the fleet was cleared to fly (1-25) but Boeing's own CEO said the company
has "much to prove" and suspended financial guidance; (4) a former Boeing
manager publicly said he would "absolutely not" fly a MAX himself
(1-31); and now (5) Boeing may delay further MAX deliveries after
Spirit AeroSystems — its fuselage supplier — found **incorrectly drilled
holes**, a distinct new manufacturing defect unrelated to the door-plug
issue, prompting Emirates' president to call Boeing a company "in the
last chance saloon" (2-05). That's three independent defect types
(door-plug attachment, loose bolts, mis-drilled holes) surfacing across
one month from both Boeing and its key supplier — no longer a single
incident, a pattern of quality-control breakdown with repeated,
quantifiable market reactions (Boeing shares fell sharply on 1-08/1-09;
its Q4 earnings call saw guidance pulled entirely). No existing node
captures this: `defense_industry` is scoped to military
contractors/spending, not commercial aircraft manufacturing or airline
safety; `hardware_chain` is semiconductor/electronics-specific. This is a
distinct, real economic sector (commercial aircraft OEMs + their
first-tier suppliers) with its own shock profile (safety incidents,
regulatory grounding, delivery delays, order/cancellation risk) that is
structurally closer to `uk_utilities` or `freight_logistics` than to
anything already in the graph.

```python
{"id": "commercial_aerospace", "type": "theme", "label": "Commercial aerospace manufacturing & safety",
 "aliases": ["boeing", "737 max", "737 max 9", "airbus", "spirit aerosystems",
             "faa", "door plug", "fuselage", "aircraft grounding",
             "alaska airlines", "aviation safety", "aircraft delivery"]},
```

**+1 means**: sector conditions improving — deliveries resuming/accelerating,
grounding orders lifted, safety inquiries closed favorably, strong order
books, supplier quality issues resolved. Deteriorating = −1 (new safety
incidents, regulatory groundings, formal investigations opened, delivery
delays/guidance withdrawals, supplier defects, canceled orders). This
mirrors the +1/−1 convention already used for `uk_utilities` and
`freight_logistics` — a sector-health theme, not a single-company stock
proxy, even though in practice Boeing will dominate the tagging volume
the way Thames Water dominates `uk_utilities`.

Proposed edges:

```python
{"src": "commercial_aerospace", "dst": "risk_appetite", "type": "influences", "sign": -1,
 "weight": 0.15, "confidence": 0.8,
 "note": "a major OEM safety/quality crisis is a mild sector-specific risk-off signal, especially for industrials-heavy portfolios"},
{"src": "commercial_aerospace", "dst": "defense_industry", "type": "correlates_with", "sign": 1,
 "weight": 0.2, "confidence": 0.7,
 "note": "Boeing and other primes straddle commercial and defense production; supplier and workforce stress in one line of business bleeds into the other, but the shock mechanisms are distinct enough to warrant separate nodes"},
{"src": "geopolitical_tension", "dst": "commercial_aerospace", "type": "influences", "sign": 1,
 "weight": 0.1, "confidence": 0.6,
 "note": "export-control and sanctions regimes affect aircraft parts supply chains (see Boeing/Airbus exposure to Russian titanium historically); weak edge, mostly latent"},
```

No asset children currently in the graph — flag for the data-provider
check; Boeing (BA) and Airbus (AIR.PA) would be the natural first
additions, with Spirit AeroSystems (SPR) as a supplier-tier candidate if
the graph starts tracking suppliers explicitly elsewhere (it currently
doesn't, e.g. no `foxconn`-style supplier node exists for `tsmc` either,
so this may be out of scope for the current graph's granularity — worth
a broader design question for whoever implements this, not just an
aerospace-specific one).

### 12. `eurozone_political_risk` — no home for "can this government actually govern"

Flagged as a watch item at the end of batch #31 (2024-06-26) and explicitly
called out as overdue at the end of batch #32 (2024-07-10) after France
generated a full month of exactly the evidence this gap predicted.
Timeline: Macron calls a shock snap election after EU election losses
(06-09) → French bonds and stocks sell off, CAC 40 posts its worst week
since March 2022 (06-14) → Paris loses its spot as Europe's largest
equity market to London, a ~$258bn one-week swing (06-17) → the European
Commission opens a formal "excessive deficit procedure" against France
(06-19) → the risk premium on French debt hits its highest level since
2012 (06-28) → first-round results put the far right within reach of a
majority, and Goldman Sachs specifically warns a Le Pen win would push
up French debt costs (07-01) → BIS's head separately warns that "soaring
government debt could roil global financial markets" citing the
elections wave broadly (06-30) → the runoff produces a shock left-wing
win instead, but with no working majority for anyone (07-07) → France
now faces a hung parliament and potential "political paralysis," with no
clear path to passing a budget (07-08). That is nine distinct,
independently-reportable events over a single month, every one of which
had to be tagged to either `geopolitical_tension` (for the political
shock itself) or `risk_appetite` (for the generic market reaction) —
neither of which captures the specific, recurring mechanism actually at
work: *a eurozone member state's ability to pass a budget and service its
debt becomes acutely uncertain because of a domestic political outcome*.
This is a different animal from `europe_growth` (which tracks output
data, not fiscal-capacity uncertainty) and from `credit_conditions`
(which tracks monetary policy and bank-lending conditions, not sovereign
fiscal risk). The closest existing analogy in this graph is how
`sanctioned_economy_stress` was carved out from `em_flows` — a
recognizably distinct shock mechanism that happened to be getting
absorbed into a node built for something adjacent but not identical.

```python
{"id": "eurozone_political_risk", "type": "factor", "label": "Eurozone sovereign political/fiscal risk",
 "aliases": ["french debt", "OAT spread", "excessive deficit procedure", "snap election",
             "hung parliament", "sovereign risk premium", "government collapse",
             "coalition talks", "budget crisis", "confidence vote"]},
```

**+1 means**: fiscal-political risk easing — stable government formed,
budget passed, debt spreads narrowing, rating agencies affirming outlook,
market relief rallies. Deteriorating = −1 (snap elections, hung
parliaments, government collapse, widening sovereign spreads, EU
disciplinary procedures, credit-rating warnings or downgrades). Note the
sign convention here is the mirror image of how the same underlying
event gets tagged on `geopolitical_tension` in this project's existing
practice — e.g. Le Pen's first-round showing was correctly tagged +0.45
on `geopolitical_tension` (escalating political risk) but would be
tagged **negative** here (fiscal risk deteriorating), since this node's
"+1 = risk easing" convention runs the opposite direction from
`geopolitical_tension`'s "+1 = tension escalating." This is exactly the
kind of cross-node sign mismatch flagged in the 2024-04-13 and
subsequent methodology notes — worth flagging explicitly in this
proposal itself so whoever implements it doesn't recreate the bug this
project has now caught four times.

Proposed edges:

```python
{"src": "eurozone_political_risk", "dst": "risk_appetite", "type": "influences", "sign": 1,
 "weight": 0.25, "confidence": 0.75,
 "note": "fiscal-political risk easing in a major eurozone economy is broadly risk-on for European assets; deteriorating risk is the opposite"},
{"src": "eurozone_political_risk", "dst": "europe_growth", "type": "influences", "sign": 1,
 "weight": 0.15, "confidence": 0.6,
 "note": "prolonged fiscal-political uncertainty depresses business investment and confidence (seen directly in this project's own 'pre-election seize-up' PMI tagging for the UK equivalent), distinct from the growth data itself"},
{"src": "ecb_policy", "dst": "eurozone_political_risk", "type": "influences", "sign": -1,
 "weight": 0.1, "confidence": 0.5,
 "note": "ECB tightening raises debt-servicing costs for highly-indebted member states, mechanically worsening fiscal-political risk; weak edge, latent most of the time"},
```

No asset children proposed — this is a factor node like
`political_stability`, meant to explain co-movement across French/Italian/
Spanish sovereign bonds and eurozone bank equities rather than anchor to
a single ticker. If the graph later adds sovereign-bond assets (OATs,
BTPs) directly, this would be their natural parent node.

**Retroactive tagging note**: all nine events in the timeline above were
already tagged (correctly, under the discipline available at the time) to
`geopolitical_tension` or `risk_appetite` under the shared `event_key`
`france-macron-snap-election-2024` across batches #31 and #32 — this
proposal does not require re-tagging past events, since the existing tags
are defensible proxies and the ledger is append-only by design. It's
purely a forward-looking fix: the next time a eurozone member state hits
a fiscal-political crisis (plausible candidates: Italy given its debt
load and history of coalition instability, or France again if the
current hung parliament collapses), this node should be available rather
than reinventing the `geopolitical_tension`/`risk_appetite` workaround a
second time.

---

## Process/Documentation Gap — `proposed_edges` doesn't do what the docs say

Not a node gap, but directly relevant to trusting the `proposed_edges`
mechanism I'm asked to use sparingly (§12 of the brief) — worth flagging
since it affects how much weight to put on that feature going forward.

Both `docs/DIGESTION_SPEC.md` (§A10: *"Proposals are queued for
human/trainer review, never auto-applied"*) and `SONNET_DIGEST_BRIEF.md`
(§12: *"Proposals are reviewed by humans; they are never auto-applied"*)
describe a review queue. **The actual code has no queue** —
`KnowledgeGraph.propose_edge()` in `graph.py` appends the edge directly to
the live graph's edge list on the same cycle it's proposed, gated only by:
`src`/`dst` must already exist as nodes, `type` must be a valid
`EDGE_FLOW` key, no duplicate `(src, dst, type)` triple, and `confidence`
is soft-capped to `[0.05, 0.6]` (below curated edges' `1.0`) as the only
"this is unreviewed" marker. `data/knowledge_graph.json` already contains
live `provenance: "llm"` edges from this pathway today (e.g. a
`china_tech → us_megacap_tech` edge proposed 2026-07-26 from a DeepSeek
headline). This isn't necessarily wrong — capped-confidence
auto-apply is a defensible design — but the docs currently promise a human
gate that doesn't exist in code, which matters once real capital is behind
this. Worth either building the actual review queue or updating the docs
to describe the capped-confidence-auto-apply behavior accurately.

---

## Summary table

**Status column** is my read, as of 2023-12-04 (81 days into the project,
~4,000+ words of dated evidence below), of how ready each proposal is for
an implementer to act on without further digestion. **READY** means: spec
is fully written (Node/Edge dataclass fields, `+1 means` definition,
proposed edges), backed by 3+ independent, dated, high-magnitude real
events across multiple non-adjacent time windows, and I would not expect
more digestion to materially change the spec — an implementer should be
able to bump `SEED_VERSION` and add these directly. **BUILDING** means the
spec exists but the evidence base is thinner (1–2 data points, or all
clustered in one time window) — worth building, but double-check for more
evidence before finalizing weights. **NEW** means added this session,
evidence still accumulating.

| # | Node/asset id | Type | Status | Fixes |
|---|---|---|---|---|
| 1 | `political_stability` | factor | **READY** | Root cause of `geopolitical_tension` overconcentration; independently confirmed by Moody's Nov 2023 US outlook cut citing "political polarization" by name, plus 10+ dated events (coups, mutinies, the 3-week US House speakerless crisis) across Jul–Nov 2023 |
| 2 | `boe_rate` | factor | **READY** | UK's missing monetary-policy origin node; `credit_conditions` has absorbed 10+ distinct BoE decisions/guidance events by December, each cleanly separable from the credit-market-conditions stories the node was meant for |
| 3 | `uk_banks` | theme | **READY** | 7+ dated incidents by December (NatWest/Coutts £1bn wipeout, HSBC, Lloyds, Metro Bank's full crisis-to-rescue arc, Barclays/Staley, Barclays' 2,000-job cuts) — the single most recurrent gap in the whole project |
| 4 | `travel_leisure` | theme | **BUILDING** | Fixes a real Rolls-Royce mistag; strong Jul–Aug evidence (easyJet, IAG, Ryanair, Heathrow, Tui) but quiet since October — worth one more batch of confirmation before finalizing |
| 5 | `offshore_wind` | theme | **READY** | Six-plus major, independent bellwether events by mid-November (Ørsted's crash, its $3.3bn+ US cancellation, its leadership exodus, Siemens Energy's bailout, the UK's zero-bid AR5 auction, two rounds of UK subsidy hikes) — the strongest and most overdue case in this document |
| 6 | `telecom_equipment` | theme | **READY** | Nokia's July profit warning was confirmed and dwarfed by its 14,000-job cut in October; the 5G-capex-cycle mechanism (linked to `ai_capex_cycle`, `power_demand`) is real and currently invisible inside `europe_equities` |
| 7 | `freight_logistics` | factor | **READY** | Yellow's bankruptcy, Panama Canal drought, and Maersk's 16,500 cumulative job cuts (citing "global economic slowdown") are three independent bellwethers spanning three different mechanisms (US trucking, canal capacity, ocean shipping demand) — all currently invisible inside `shipping_costs`, which is price- not capacity-framed |
| 8 | (edges only) | — | **READY** | Strengthen `solar`'s existing edges: add `natural_gas → solar` and `solar ↔ offshore_wind`; low-risk, no new node required |
| 9 | `uk_utilities` | theme | **NEW — READY** | Promoted 2023-12-03 after Thames Water's formal "could run out of money by April" auditor warning; full spec now drafted above |
| 10 | `sanctioned_economy_stress` | factor | **READY** | Russia's rouble crisis (Aug 2023, 3x in one week) generalizes cleanly to Iran/Venezuela; no new evidence needed, spec is stable |
| 11 | `em_flows` (existing node) | — | **VALIDATED, no change needed** | Milei's Nov 2023 Argentina election win was tagged live to this existing valid node and it worked cleanly — confirms `political_stability`'s proposed edge to it is realistic, not just a plausible-sounding weight |
| — | Watch, not yet promoted | — | — | CBI "material uncertainty" (single lobbying body, not a sector); Sellafield hack (single-site security story, no economic mechanism) — see §10 |
| — | Red Sea shipping security | — | **RESOLVED — no new node needed** | Escalated five times over four weeks (Nov 20 → Nov 27 → Dec 4 → Dec 12 → Dec 16), culminating 2023-12-16 in Maersk and Hapag-Lloyd suspending Red Sea passage — the trigger condition I set was met, and the conclusion is the existing `geopolitical_tension` + `shipping_costs` dual-tag handled all five incidents cleanly. **Expect this to become a high-volume, sustained `shipping_costs` storyline** as rerouting shows up in freight rate data over the following weeks — not a gap, but a heads-up on tagging volume |
| — | 15 candidate assets (HSBC, Shell, Nokia, UPS, Delta, etc.) | asset | **READY** | Gives nodes #3, #4, #6, #7 real `member_of` children instead of only weak `correlates_with` proxies; add United Utilities/Severn Trent as candidates for node #9 |
| — | `proposed_edges` review queue | process | **FLAG ONLY** | Docs promise human review; code auto-applies at capped confidence — unchanged since first noted, still needs a decision from whoever owns this codebase |
| 12 | `commercial_aerospace` | theme | **NEW — READY** | Promoted 2024-02-05 after three independent Boeing/Spirit AeroSystems manufacturing-defect incidents (door plug, loose bolts, mis-drilled holes) across four weeks, plus FAA grounding, guidance suspension, and a customer airline calling Boeing "last chance saloon"; full spec above in §11 |
| 13 | `us_growth` | factor | **NEW — READY** | Flagged 2024-01-25, promoted 2024-04-25: no dedicated US GDP/growth node exists despite `china_growth`, `europe_growth`, `korea_growth`, `india_growth` all existing for other major economies. Three independent GDP-print events now on record, force-tagged inconsistently to two different existing nodes depending on framing (`fed_rate` once, `us_consumer` twice) — confirms both the gap and that the workaround is unstable, not just imperfect. Spec: `+1` = growth accelerating (GDP prints, ISM/PMI beats), `-1` = growth decelerating/recession risk |
| 14 | `uk_growth` | factor | **NEW — BUILDING (deep evidence)** | Flagged 2024-04-12: confirmed via grep that the 85-node graph has **zero** UK growth/output/equities nodes of any kind — not even an asset-level FTSE proxy — despite `boe_rate` (proposed #2, monetary policy) and `uk_banks` (proposed #3, financials theme) already covering the UK's other two dimensions. UK exiting recession (Feb GDP +0.1%, FTSE 100 at a 1-year high, 2024-04-12) had no node to tag and was left out of the event file entirely rather than force-fit to `credit_conditions`. This is the same shape of gap as `us_growth` — every other major economy (`china_growth`, `europe_growth`, `korea_growth`, `india_growth`) has a dedicated growth factor, the UK does not, and it is the single most frequently-covered economy in this Guardian-sourced archive. As of 2024-05-01: five more FTSE-record-high events plus a UK manufacturing PMI contraction plus a growing London-listing-exodus storyline (Flutter joining Shell/CRH/DS Smith/Darktrace) — evidence trail now deeper than several READY nodes; recommend promoting on the next spec-writing pass |
| 15 | `amzn` | asset | **NEW — READY** | Flagged 2024-04-30: `aapl` and `tsla` both exist as individual mega-cap asset nodes but `amzn` does not, despite Amazon being an equally significant Magnificent Seven constituent. Amazon's AI/AWS earnings beat (2024-04-30) had to be tagged to the sector-level `ai_capex_cycle` instead, losing company-specific signal. Pure parity fix, no spec judgment call — add `{"id": "amzn", "type": "asset", "label": "Amazon", "symbol": "AMZN", "market": "US"}` alongside the existing `aapl`/`tsla` cluster |
| 16 | `eurozone_political_risk` | factor | **NEW — READY** | Flagged 2024-06-26, promoted 2024-07-10 after a full month of evidence: France's snap election generated nine independent events (bond/equity selloffs, an EU excessive-deficit procedure, a debt risk-premium spike to a 2012 high, a hung-parliament outcome) all force-tagged to `geopolitical_tension` or `risk_appetite`, neither of which captures the specific "can this government pass a budget" mechanism. Full spec above in §12, including an explicit warning about this node's inverted sign convention relative to `geopolitical_tension` for the same underlying events |

**Bottom line for whoever implements this**: nodes #1, #2, #3, #5, #6, #7,
#9, #10, #12, #13, #15, and #16 are all implementation-ready today —
that's 12 of 16 proposals, each with a full `Node`/`Edge` spec above and
a multi-event, multi-week evidence trail. The main remaining work is a
single coordinated `seed.py` edit (bump `SEED_VERSION`, add these nodes
and their edges, optionally add the 15+ candidate assets), not further
digestion. `travel_leisure` (thin recent evidence) and `uk_growth` (deep
evidence trail as of 2024-05-01, but still one spec-writing pass away
from READY), and the Red Sea/shipping-security question (still evolving)
genuinely benefit from one more pass before finalizing.

---

## Digestion Log — evidence gathered while continuing past 2023-08-09

*Appended to as digestion proceeds. Each entry either reinforces a node
above (bumping it from "proposed" toward "confirmed by recurrence") or
surfaces a new gap not yet covered above.*

- **2023-08-09 baseline**: all evidence above is from days 2023-07-01 →
  2023-08-09 (40 days, 204 events). Continuing chronologically from
  2023-08-10.
- **2023-08-10**: Ecuadorian presidential candidate Fernando Villavicencio
  assassinated days before the election ("Ecuador's descent into violence
  reaches new low"). Clean `political_stability` case — electoral violence,
  zero inter-state content — currently tagged `geopolitical_tension` in the
  live event file since the node doesn't exist yet. Also: Wilko's formal
  collapse into administration (12,000 jobs) is now the 3rd distinct "UK
  company distress, no good node" story this project (after NatWest/Coutts,
  now covered by proposed `uk_banks`, and WeWork on 2023-08-09). Wilko isn't
  a bank so `uk_banks` wouldn't catch it either — tagged `credit_conditions`
  for now. Not yet proposing a `uk_corporate_distress` node on one more
  data point, but flagging: if a 4th distinct non-bank UK/company
  insolvency story recurs, that's the trigger to draft one.

- **2023-08-14**: Javier Milei's shock primary-election lead in Argentina
  ("far-right outsider... unsettling the political and economic
  establishment") — a second clean `political_stability` case in 4 days,
  reinforcing node #1 rather than a new gap. Also: Russia's rouble falling
  to a 16-17 month low, forcing an extraordinary central-bank meeting, is a
  genuinely distinct phenomenon from either `political_stability` or
  `geopolitical_tension` (currently tagged there as a fallback) — it's a
  war-cost-driven currency/economic-stress signal, not a governance crisis
  or a military escalation. Watching for recurrence; if Russia's economy
  keeps generating distinct currency/rate stories through the sanctions
  regime, a narrower `sanctioned_economy_stress` factor (generalizable
  beyond just Russia — Iran, Venezuela would also qualify) may be worth
  drafting.

- **2023-08-10 → 2023-08-23 batch summary** (14 days, 60 events): three more
  `political_stability`-shaped stories reinforced node #1 beyond Ecuador and
  Argentina — Guatemala's anti-corruption presidential upset (2023-08-21),
  and Prigozhin's death in a plane crash (2023-08-23, the cleanest possible
  phase-change case: mutiny → leader's death, tagged `geopolitical_tension`
  for now but really a `political_stability`/regime-instability story with
  zero battlefield content). `offshore_wind` gained a second, independent
  data point beyond the original three (the Great Lakes' first freshwater
  offshore project, 2023-08-16), reinforcing it's a recurring theme, not a
  one-off. `freight_logistics` gained a second, distinct data point: Panama
  Canal drought forcing shipping delays (2023-08-14) is capacity-destruction
  exactly like Yellow's bankruptcy, just weather-driven instead of
  corporate-failure-driven — same node, same `freight_logistics →
  shipping_costs` mechanism proposed above. New evidence also emerged for
  gaps not yet in the document: Evergrande's formal Chapter 15 bankruptcy
  filing and Country Garden's default risk (2023-08-18) confirm
  `china_property` needs no new node — it already exists and handled this
  correctly — but Russia's rouble crisis (2023-08-14/15/16, three separate
  events, all fallback-tagged to `geopolitical_tension`) is now a
  three-time recurrence of the `sanctioned_economy_stress` gap flagged
  2023-08-14; drafting a full spec is now warranted rather than just
  watching.

- **2023-08-29**: A US Gulf of Mexico offshore wind auction drew only two
  bidders — "a blow to Biden's green-energy agenda" — a third independent
  `offshore_wind` data point (after Vattenfall/Norfolk and the Great Lakes'
  Icebreaker project), and notably a *negative* one this time, showing the
  node needs to carry real downside cases too, not just capacity
  announcements. Currently tagged `energy_transition` for lack of the
  live node.

- **2023-08-30**: Ørsted — the world's *largest* offshore wind company —
  loses 25% of its share value (nearly £7bn) in a single day on a US
  business write-down. This is the strongest `offshore_wind` evidence yet:
  a clean, major, single-company event that a generic `energy_transition`
  tag flattens into noise alongside unrelated solar/nuclear/EV stories the
  same week. Also: Gabon's military coup (hours after a disputed election)
  is a second African coup in a month after Niger — another clean
  `political_stability` case, and notable that it's now recurring at a
  pace (roughly one new coup/government-crisis event per week across this
  project) that a single `geopolitical_tension` catchall cannot represent
  without diluting the signal for actual armed conflict.

- **2023-08-24 → 2023-09-06 batch summary** (14 days, 52 events):
  `geopolitical_tension` share dropped to 34.6% (from 48% the prior batch)
  as earnings season, China-property distress, and a run of energy/tech
  stories diversified the mix — the healthiest concentration reading yet.
  `energy_transition` carried 5 events this batch alone, split between
  `offshore_wind`-shaped stories (Ørsted's 25%/£7bn crash, the Gulf of
  Mexico auction failure) and `boe_rate`/onshore-wind-adjacent UK policy
  news — reinforcing that `energy_transition` is now doing real double
  duty as a catchall for at least two, arguably three, distinct proposed
  nodes. `china_property` (already a real node, working correctly)
  absorbed both Evergrande's bankruptcy filing and Country Garden's
  $6.7bn loss/debt-deal saga across four separate events — no gap there,
  just confirming the existing node handles serial developer distress
  well. New evidence for `political_stability`: Gabon's coup (a second
  African coup within a month of Niger's) and continued Zimbabwe
  election-fraud allegations.

- **2023-09-07**: The UK's flagship offshore wind auction (AR5) draws
  **zero bidders** — the single strongest `offshore_wind` case in the
  project so far (stronger even than Ørsted's 25% crash or the Gulf of
  Mexico auction failure), a complete, historic failure of a flagship
  government renewables mechanism that a generic `energy_transition` tag
  cannot distinguish from, say, a solar subsidy tweak the same week. Six
  independent `offshore_wind`-shaped events have now accumulated across
  three weeks (Vattenfall/Norfolk, Hornsea Four, Dogger Bank, Gulf of
  Mexico, Ørsted, UK AR5) — this is no longer a "watching" case by any
  reasonable bar, it is a clearly established recurring theme the graph
  currently has no way to represent distinctly from `solar`.

- **2023-09-20**: Rishi Sunak's net zero rollback (delaying the petrol/diesel
  car ban and the gas-boiler-to-heat-pump switch) is tagged `energy_transition`
  for now — it's UK climate *policy*, not an `offshore_wind`-shaped project
  story specifically, so it doesn't extend that node's count, but it is
  further confirmation that `energy_transition` is absorbing at least three
  distinct signal types this project (offshore-wind project economics,
  policy/subsidy decisions, and now outright climate-target reversals) that
  a single catchall node cannot distinguish for a trader who'd want to know
  *which* mechanism moved. Also: US/Brazil warnings that Guatemala's
  military or allied elites may try to block President-elect Arévalo from
  taking power is a clean new `political_stability` case (attempted
  anti-democratic power denial, zero inter-state conflict content) —
  currently skipped from live tagging entirely since neither
  `geopolitical_tension` nor any other valid node fits well enough to
  justify force-tagging it; recorded here as further recurrence evidence
  for node #1 instead.

- **2023-09-07 → 2023-09-20 batch summary** (14 days, 50 events):
  `geopolitical_tension` share continues to normalize, now 34.0% (was 34.6%
  the prior batch, down from 43–52% pre-`political_stability` baseline) —
  two consecutive batches under 35% suggests the earlier over-concentration
  was concentrated in the July/Wagner-mutiny period rather than a permanent
  feature of the tagging approach, though the underlying fix (splitting out
  `political_stability`) is still undone in the live graph. `credit_conditions`
  ran at 20% this batch, elevated by both the UK-inflation-surprise/BoE
  rate-expectations story (2023-09-20) and continuing mortgage/insolvency
  stories — exactly the `boe_rate` overload pattern flagged in node #2,
  still unresolved. `energy_transition` held at 12% (6 events), again mixing
  genuine `offshore_wind`-shaped stories with the Sunak net-zero-rollback
  policy story above — reinforcing rather than diluting the case for
  splitting the two. No new node-worthy gap surfaced this batch beyond
  reinforcing existing proposals; `freight_logistics` and `travel_leisure`
  had zero new data points in this window (a quiet two weeks for those
  specific themes, not evidence against them — see the six-week trend for
  the real signal).

- **2023-10-03**: Kevin McCarthy is voted out as US House speaker — the first
  time in US history a sitting speaker has been removed by his own chamber.
  Currently fallback-tagged `credit_conditions` (the story's live market
  angle is fiscal-negotiation uncertainty ahead of the November funding
  deadline), but this is really the cleanest `political_stability` case yet:
  a G7 country's own governing institution failing in an unprecedented way,
  zero inter-state content, exactly the domestic-governance-crisis pattern
  node #1 was designed for. It also directly reinforces node #2 (`boe_rate`)
  and node #1 together in a different way: the very next day (2023-10-04)
  UK 30-year gilt yields hit a 25-year high in a sell-off explicitly
  attributed in the coverage to *both* global inflation fears *and* "US
  political instability" — a domestic-governance shock in one G7 country
  transmitting directly into another G7 country's bond market. That
  cross-border transmission mechanism is exactly why `political_stability`
  needs its own node with its own `usd_strength`/`em_flows` edges rather
  than being buried inside `credit_conditions`, which currently absorbs
  both the UK gilt story and the US speaker crisis as if they were the same
  phenomenon.

- **2023-09-21 → 2023-10-04 batch summary** (14 days, 38 events):
  `geopolitical_tension` share held at 31.6% (down slightly from 34.0% the
  prior batch) — three consecutive batches under 35% now. `credit_conditions`
  stayed elevated at 21.1%, again absorbing what should be at least three
  distinct signals per the existing gap proposals: BoE policy decisions
  (the 5-4 hold vote), UK gilt-market stress (the 25-year-high sell-off),
  and now US institutional-crisis spillover (McCarthy's ouster) — a single
  node carrying monetary policy, sovereign bond risk, and political
  contagion simultaneously is the clearest evidence yet for splitting out
  both `boe_rate` and `political_stability`. Quieter batch than the last
  for the energy/industrial proposals — no new `offshore_wind`,
  `telecom_equipment`, or `freight_logistics` data points this window — but
  `solar` gained one more (Australian rooftop capacity, 2023-09-26) and
  `energy_transition` continued absorbing UK climate-policy reversals
  (Sunak's initial net zero U-turn and its partial EV-mandate walk-back)
  exactly as flagged in node #5-8's writeup.

- **2023-10-07**: Hamas launches a surprise attack on Israel, triggering the
  Israel-Hamas war — the highest-magnitude single event digested so far this
  project (magnitude 0.65 on day one, rising to 0.6 on the 2023-10-17 Gaza
  hospital blast). Worth noting explicitly: `geopolitical_tension` handled
  this correctly and needed no new node — this is exactly the "Iran launches
  direct missile attack on Israel"-shaped inter-state/armed-conflict event
  the node's own worked example describes, unlike the domestic-instability
  stories (Wagner mutiny, coups, McCarthy's ouster) that motivated proposing
  `political_stability`. The resulting concentration spike this batch
  (`geopolitical_tension` 40.4%, see batch summary below) is therefore a
  correct reflection of real news distribution during an actual war outbreak,
  not the mistagging artifact that drove the original 43-52% overconcentration
  finding — the two should not be conflated when reviewing health metrics.
  Also strengthened the case for keeping `oil_supply` and `oil_price` split
  (Exxon's $60bn Pioneer acquisition tagged cleanly to `oil_supply`, the
  Shell/Tamar-field/$100-approach stories to `oil_price`, without confusion).

- **2023-10-09**: The world's largest offshore windfarm (Dogger Bank, first
  of 277 turbines) begins powering the UK grid — the first unambiguously
  *positive, large-scale operational* `offshore_wind` data point in the
  project, distinct from the run of negative/cost-overrun stories (Ørsted's
  crash, the AR5 zero-bid auction, Vattenfall/Norfolk). Currently tagged
  `energy_transition` for lack of the live node; this is exactly the kind of
  story that node would isolate as its own positive signal instead of
  blending with unrelated transition news the same week.

- **Further `uk_banks` evidence**: Metro Bank's capital crisis and rescue
  (2023-10-05 → 10-08, shares falling ~30% then a £925m rescue deal) and
  ex-Barclays CEO Jes Staley's City ban plus ~£18m in cancelled pay over his
  Jeffrey Epstein ties (2023-10-12) are two more real, quantified UK banking
  stories with no home, both fallback-tagged `credit_conditions`. That's five
  distinct UK banking incidents now (NatWest/Coutts, HSBC, Lloyds, Metro Bank,
  Barclays/Staley) all sharing one node with mortgage-arrears and
  insolvency-rate stories that have nothing to do with bank-specific events.

- **Further `travel_leisure` evidence**: all UK-Israel flights suspended
  (2023-10-11, BA/Virgin/easyJet/Wizz) and Rolls-Royce's ~2,500 planned job
  cuts (2023-10-16, principally its civil-aviation servicing business) both
  skipped from live tagging for lack of a home — the latter is the third
  instance of the exact Rolls-Royce civil-aviation mistagging risk flagged
  under node #4 above.

- **2023-10-03/10-04 political_stability reinforcement carried forward**:
  McCarthy's historic ouster (logged above) was immediately followed by two
  full weeks of the House remaining speakerless (Jordan losing two floor
  votes, Scalise withdrawing) — a sustained US governance-paralysis story
  that ran in parallel with the Israel-Hamas war and is still fallback-tagged
  `credit_conditions` throughout. This is now less a one-off anomaly and more
  a multi-week case study in why `political_stability` needs its own
  `usd_strength`/`risk_appetite` propagation independent of monetary policy.

- **2023-10-05 → 2023-10-18 batch summary** (14 days, 43 events, 47 node
  tags): `geopolitical_tension` share jumped to 40.4% (up from 31.6% the
  prior batch) — expected and correct given the Israel-Hamas war broke out
  mid-batch (2023-10-07) and dominated real news flow for the rest of the
  window; see the note above distinguishing this from the earlier
  mistagging-driven overconcentration. `credit_conditions` held at 17.0%,
  still absorbing BoE decisions, UK gilt stress, Metro Bank, Barclays/Staley,
  and US House-speakerless fiscal risk simultaneously. `oil_price` (8.5%)
  and `oil_supply` (4.3%) both saw genuine new activity from the war and the
  Exxon-Pioneer deal — the split held up cleanly under real stress-testing
  for the first time this project. Novelty mix stayed healthy (25×1.0,
  18×0.5) despite the sustained single-story dominance, since each new
  phase of the war (siege declared, evacuation order, hospital blast, UN
  veto) was a genuine material development worth a fresh novelty=0.5 tag
  rather than pure recap.

- **2023-10-19**: Nokia announces up to 14,000 job cuts (nearly a quarter of
  its workforce) as demand for mobile network equipment slumps — a far
  larger, harder confirmation of the `telecom_equipment` case than July's
  profit warning that originally motivated node #6. Currently fallback-tagged
  `europe_equities`, which dilutes what is a very clean, very large
  capex-cycle-slowdown signal into a generic country-equities bucket.

- **2023-10-26 → 2023-11-01: `offshore_wind` case now overwhelming**. Two
  more major, independent data points landed in six days: Siemens Energy —
  one of the sector's biggest turbine makers — sought a German government
  bailout worth up to 80% of an initial €10bn tranche (2023-10-26), and
  Ørsted cancelled two US offshore windfarm projects outright at a **£3.3bn**
  cost, explicitly citing "escalating costs across the global offshore wind
  industry" (2023-11-01) — the single largest-magnitude `offshore_wind` data
  point in the project to date, larger even than Ørsted's 25% share-price
  crash in August. Between these two and the AR5 zero-bid auction
  (2023-09-07), the sector now has three of its most significant players
  independently confirming a structural cost crisis within about eight
  weeks. This is no longer a proposal that needs more evidence to justify
  building; it is a live, unfolding industry story the graph currently has
  no way to track as its own thread separate from generic `energy_transition`
  noise (UK policy U-turns, Rosebank, EV mandates, etc. all landed in the
  same node the same weeks).

- **2023-10-25**: The US House finally resolves its three-week-long
  speakerless crisis (Mike Johnson elected, unanimous Republican support),
  closing out the `political_stability`-shaped saga that ran in parallel
  with the Israel-Hamas war (McCarthy's ouster 10-03 → Scalise withdraws
  10-13 → Jordan fails three times 10-17/10-20 → Emmer withdraws 10-24 →
  Johnson elected 10-25). Six distinct, individually-newsworthy `credit_conditions`-fallback-tagged events over three weeks — probably the single
  clearest real-world "trailer" for why `political_stability` needs its own
  node: a G7 country's legislature was unable to conduct business, including
  on the exact $106bn Israel/Ukraine aid package this project was also
  digesting in parallel, and none of that institutional-paralysis signal
  had anywhere to go except a monetary-policy-flavoured catchall node.

- **2023-10-19 → 2023-11-01 batch summary** (14 days, 41 events, 42 node
  tags): `geopolitical_tension` eased slightly to 38.1% (from 40.4% the
  prior batch) — still elevated and correctly so, as the Israel-Hamas war
  entered its ground-invasion phase (siege, evacuation orders, the Jabalia
  refugee-camp strike, the Rafah crossing opening) while the Ukraine war and
  the Balticconnector sabotage story continued in parallel. `credit_conditions`
  held at 16.7%, still absorbing UK gilt stress, three separate UK bank
  earnings/crisis stories (Metro Bank, Barclays, NatWest, HSBC — the `uk_banks`
  case keeps compounding) and the entire US House-speakerless saga
  simultaneously. Two Fed decisions (Sept hold, Nov hold) and one ECB hold
  landed this batch without incident under `fed_rate`/`ecb_policy`, plus a
  clean `us_employment` resolution arc (Ford → Stellantis → GM all reaching
  UAW deals) — confirming those nodes handle even a very newsy multi-domain
  batch without needing new machinery. Novelty mix stayed healthy (24×1.0,
  17×0.5) and mean magnitude rose to 0.416 (from 0.390), reflecting the
  genuinely higher stakes of this batch's news rather than tagging inflation
  — Ørsted's £3.3bn cancellation and the Jabalia strike were both real 0.45+
  events, not inflated recaps.

- **2023-11-10**: Moody's cuts its outlook on US sovereign credit to negative,
  explicitly naming "continued political polarization" in Congress as a
  driver — a rating agency independently confirming, in its own methodology,
  the exact mechanism node #1 (`political_stability`) was designed to
  capture. This is now not just a pattern I'm observing in news flow; it's
  being priced by credit markets. Currently fallback-tagged `credit_conditions`,
  which is defensible (it is a credit-rating action) but obscures that the
  *cause* cited is a political-stability variable, not a monetary or
  balance-sheet one.

- **2023-11-03**: Maersk announces 10,000 more job cuts (16,500 total)
  citing a "global economic slowdown" — another top-tier freight/shipping
  bellwether confirming the exact demand-side signal `freight_logistics`
  (node #7) was designed to carry. Live-tagged to `shipping_costs` since
  that's the closest existing valid node, but this is a demand/capacity
  story (fewer goods moving) rather than a price story, which is precisely
  the split node #7's writeup argued for.

- **2023-11-01 → 2023-11-14: `offshore_wind` crisis reaches its endpoint**.
  Ørsted's US windfarm cancellations (11-01) were followed two weeks later
  by both of its top executives departing (11-14) — a leadership-accountability
  outcome, not just a project-level one. In the same window: Siemens Energy's
  bailout (prior batch), UK offshore wind subsidies rising ~40% in response
  to the same cost pressures (11-10), and SSE's boss publicly calling for
  government support while raising capex 14% to cope (11-15, not separately
  live-tagged but noted here). Six-plus independent, large-magnitude data
  points across three batches, from the sector's biggest names on both
  sides of the Atlantic, all pointing the same direction. This case has
  been "ready to build" for weeks; it is now arguably overdue.

- **2023-11-02 → 2023-11-15 batch summary** (14 days, 40 events, 42 node
  tags): `geopolitical_tension` held at 40.5% (from 38.1%) as the Gaza war
  reached its most intense phase (al-Shifa hospital siege and raid, the
  Lebanon front heating up, US strikes on Iran-linked targets in Iraq and
  Syria) — again a correct reflection of an actual war's worst weeks, not a
  tagging artifact. `credit_conditions` rose to 21.4%, now absorbing at
  least four genuinely distinct signal types simultaneously: BoE/Fed/rate
  decisions, UK mortgage/housing data, US sovereign credit action (Moody's),
  and a second US government-shutdown scare — the clearest evidence yet
  that this node is overloaded and that `boe_rate` and `political_stability`
  both need to exist. `energy_transition` jumped to 11.9%, driven almost
  entirely by the offshore_wind crisis documented above — a single proposed
  node's evidence base now accounts for nearly an eighth of all tags in this
  batch while having zero representation in the live graph. Magnitude mean
  eased slightly to 0.390 (from 0.416) as the batch's news, while still
  dominated by the war, included fewer single-day mega-events than the
  previous two batches (no repeat of the 7 October outbreak or the Jabalia
  strike's shock value), suggesting magnitude scoring is tracking real
  variation in stakes rather than drifting upward from habit.

- **2023-11-16 → 2023-11-29: the Gaza ceasefire saga and a honest concentration note**.
  This batch covered the war's most eventful diplomatic stretch — the first
  ceasefire (11-22), its implementation (11-24), and four separate extension/
  hostage-exchange updates (11-25, 11-26, 11-27, 11-28, 11-29) — each tagged
  as a fresh `geopolitical_tension` event since each carried genuinely new
  facts (specific hostage/prisoner counts, extension terms, the Kfir Bibas
  death report). That pushed `geopolitical_tension` to 44.7% this batch, the
  highest reading of the entire v1.2 redo. Worth being honest about: some of
  this is unavoidably real (a war de-escalating in daily increments *is* the
  story), but part of it is also a judgment call on my part — a trainer
  reviewing this batch might reasonably decide the day-5 and day-6 hostage-
  exchange updates were closer to recaps (novelty 0.2) than material
  developments (novelty 0.5, what I used). I kept novelty at 0.5 throughout
  because each update did carry a new, specific, quotable fact (a number of
  hostages, a new extension length) rather than pure repetition — but this
  is the batch where that judgment call is most exposed, and it's the
  reason the concentration number moved instead of holding steady like the
  last few batches.

- **New pattern: `ai_capex_cycle` earns real weight from a non-macro story**.
  The Sam Altman/OpenAI saga (fired 11-17, Microsoft hires him 11-20,
  reinstated 11-22) generated four separate live-tagged events under
  `ai_capex_cycle` — 10.5% of this batch's tags, second only to
  `geopolitical_tension`. This wasn't originally what the node's worked
  examples in the brief anticipated (capex announcements, chip export
  controls), but a governance crisis at the industry's most important lab
  is a legitimate `ai_capex_cycle`-relevant shock (it visibly moved
  Microsoft's competitive position and industry sentiment), and the node
  absorbed it without needing a new home — a useful data point on how
  robust the existing 85-node taxonomy is to genuinely novel story shapes.

- **`em_flows` gets its first real live use**: Milei's Argentina election
  win (11-19) was tagged there rather than skipped, testing whether that
  node (previously only referenced in `political_stability`'s proposed
  edges) works for a live EM political-shock story. It read cleanly — worth
  noting for whoever eventually implements `political_stability`, since the
  proposed `political_stability → em_flows` edge is now validated by a real
  example rather than just a plausible-sounding edge weight.

- **2023-11-16 → 2023-11-29 batch summary** (14 days, 36 events, 38 node
  tags): `geopolitical_tension` 44.7% (see note above — a real high-water
  mark, not a clean read). `ai_capex_cycle` 10.5% (OpenAI saga).
  `credit_conditions` eased to 10.5% (from 16-21% the last two batches) —
  the UK autumn statement, ECB bank-stress warning, and Barclays/Metro Bank
  stories kept it present but didn't dominate the way the US shutdown/Moody's/
  gilt-selloff cluster did in October. Two more `offshore_wind`-adjacent
  data points (UK subsidy increase confirmed, still fallback-tagged
  `energy_transition`) and one more `uk_banks` data point (Barclays' 2,000
  job cuts) continue accumulating evidence for those proposals without
  changing their status — both remain implementation-ready per the last two
  batches' notes.

- **2023-12-07 → 2023-12-12: `uk_utilities` case escalates from "promoted" to "urgent"**.
  South East Water's £2.25m shareholder dividend despite an £18m loss
  (12-07) and Ofwat's explicit on-record confirmation that it is "prepared
  to put [Thames Water] into administration" (12-12) both landed within a
  week of the node #9 promotion above. This isn't new evidence changing the
  spec — it's confirmation the spec was right the first time. Worth
  flagging for whoever implements this: a formal Special Administration
  Regime event at Thames Water (England's largest water utility, ~16m
  customers) looks live enough by mid-December 2023 that the node should be
  treated as time-sensitive, not just theoretically useful — if it
  materializes in early 2024, a trading system without this node would
  have no way to represent the single largest UK regulated-utility
  event in a decade.

- **2023-12-04 → 2023-12-12: Red Sea shipping crisis escalation continues**.
  Three more incidents landed this batch on top of the two flagged in the
  prior batch: a three-vessel Houthi attack with direct USS Carney
  engagement, explicitly described by US Central Command as "fully enabled
  by Iran" (12-04), and US diplomats warning the attacks now jeopardize a
  broader Yemen peace deal (12-12). That's five escalating incidents in
  three weeks (11-20, 11-27, 12-04, 12-12, plus the underlying Yemen peace
  deal risk). I'm maintaining the dual-tag (`geopolitical_tension` +
  `shipping_costs`) rather than drafting a new node yet, per the "flag for
  next review" status set last batch — but the trigger condition I set then
  (major carriers publicly rerouting away from the Red Sea/Suez) is worth
  watching closely in the next batch or two; historically this is the kind
  of pattern that turns into a major, sustained shipping-cost story once
  carriers start avoiding the route rather than just insuring against it.

- **`em_flows` now has two independent live uses**: Milei's election win
  (11-19) and Argentina's 50%+ peso devaluation under the new government
  (12-13) both tagged cleanly to this existing valid node. Between this and
  Milei's inauguration, `em_flows` has absorbed three genuinely
  EM-political-shock-shaped stories in one project without needing a new
  home — strong independent confirmation (beyond just the proposed edge
  weight) that `political_stability`'s design, once implemented, will have
  somewhere real to route its downstream EM effects.

- **2023-12-13: a historic day that stress-tested `fed_rate` and
  `energy_transition` simultaneously and both held up cleanly**. The Fed's
  December pivot (holding rates but signalling three 2024 cuts, sending the
  Dow to a record close) and Cop28's landmark "transition away from fossil
  fuels" deal — the first time any COP final text has named fossil fuels
  explicitly — landed on the same day as a UK GDP contraction and
  Argentina's peso devaluation. All four tagged cleanly to existing or
  already-proposed nodes (`fed_rate`, `energy_transition`, `europe_growth`,
  `em_flows`) with no forcing required. Worth noting for anyone auditing
  node design: on the single most macro-dense day of the whole project so
  far, nothing broke.

- **2023-11-30 → 2023-12-13 batch summary** (14 days, 42 events, 46 node
  tags): `geopolitical_tension` eased back to 34.8% (from 44.7% the prior
  batch) — the Gaza war's diplomatic phase (ceasefire → collapse → renewed
  fighting → UN votes) generated fewer per-day updates than the November
  hostage-exchange saga, and a genuinely diverse macro calendar (Fed
  pivot, three central bank decisions, Cop28, two sovereign credit-outlook
  cuts, an EM currency collapse) pulled weight onto other nodes. This is
  the most evenly distributed batch of the whole project — nine different
  nodes each carrying 2%+ of tags, none besides `geopolitical_tension`
  above 13%. Two new sovereign credit actions this batch (Moody's on China,
  after Moody's on the US in the prior batch) — worth noting as a pattern:
  major-power credit-outlook cuts are becoming a recurring 2023 Q4 story in
  their own right, currently absorbed cleanly by `china_property` and
  `credit_conditions` respectively without needing a shared "sovereign
  credit risk" node, but worth watching if a third one lands (UK? Japan?)
  in the next batch.

- **2023-12-16: the Red Sea trigger condition fires — resolution, not a new
  node**. The condition I set two batches ago ("if major carriers start
  publicly rerouting away from the Red Sea/Suez, that's the trigger to
  draft a dedicated node") has now been met: Maersk and Hapag-Lloyd, two of
  the world's largest container lines, suspended Red Sea passage after UK
  and US naval vessels shot down attack drones defending shipping. Having
  actually hit the trigger, my conclusion is **no new node is needed** —
  this is exactly the shape of event `shipping_costs` (the price/rate
  effect of carriers rerouting around the Cape of Good Hope, adding
  10+ days and real cost to Asia-Europe transit) and `geopolitical_tension`
  (the Houthi/Iran-linked origin conflict) were already built to jointly
  capture, and the six-week dual-tagging trial across five escalating
  incidents (11-20 seizure → 11-27 Gulf of Aden attack → 12-04 three-vessel
  attack → 12-12 Yemen-peace-deal risk warning → 12-16 carrier suspensions)
  worked cleanly every time. The lesson for whoever reads this next: not
  every escalating story needs a new node — sometimes the right outcome of
  "watching for the trigger" is confirming the existing two-node dual-tag
  was sufficient all along. I'm downgrading this from "flag for next
  review" to closed, with a note that this is likely to become one of the
  largest sustained `shipping_costs` storylines of whatever period this
  digest eventually reaches into 2024 — expect a high volume of
  `shipping_costs`-tagged events over the following weeks as carriers'
  rerouting shows up in freight rate data.

- **2023-12-27: China's gaming-regulation shock validates `china_tech` at full
  strength**. China's game regulator published sweeping draft rules —
  spending caps, a ban on daily-login reward mechanics, restrictions clearly
  aimed at reining in the sector's most effective monetisation tools — and
  triggered a sharp selloff in Chinese gaming and internet stocks on fears
  of a return to the 2021 tech-crackdown playbook. This is exactly the kind
  of single-day, high-magnitude, regulator-originated shock `china_tech`
  exists to catch, and it caught it cleanly with no forcing. Worth flagging
  for whoever tunes edge weights: this is the first *purely regulatory*
  (as opposed to macro/stimulus) shock to `china_tech` in the project so
  far — prior tags to this node were mostly China stimulus/growth-adjacent.
  If `china_tech`'s downstream edges are currently weighted assuming
  stimulus-style (supportive) shocks, this event is a reminder the node
  also needs to carry negative/regulatory shocks convincingly — worth a
  spot-check on `china_tech`'s edge signs and weights in `seed.py` before
  this digest reaches the actual 2021 crackdown era it echoes (already in
  the archive's past, but recurring regulatory episodes are clearly an
  ongoing pattern, not a one-off).

- **2023-12-14 → 2023-12-27 batch summary** (14 days, 32 events, 39 node
  tags, events/day 2.29 — the quietest batch of the project so far, as
  expected over the Christmas/Boxing Day news lull): `geopolitical_tension`
  at 41.0% (16/39) and `shipping_costs` at 20.5% (8/39) together account for
  over 60% of tags, driven almost entirely by the Red Sea crisis running
  hot exactly as flagged in the prior entry — Ikea publicly warning of
  supply disruption, continued Houthi/US naval incidents, and the
  Israel-Hamas war's continued escalation (100+ killed in a single strike
  on 12-25, Israel's "multi-front war" warning on 12-26). `credit_conditions`
  picked up 15.4% (6/39) from a cluster of UK fiscal/monetary stories (higher
  than expected public borrowing, the spring budget date announcement,
  Panama Canal / PCE / GDP prints). Magnitude mean 0.397, median 0.40 —
  the lowest average magnitude of any batch so far, consistent with a
  slow-news holiday period rather than any change in event-selection
  discipline. Novelty split 18×1.0 / 14×0.5, no 0.2-recap events selected
  at all this batch. One new event_key opened
  (`china-gaming-regulation-2023-12`) alongside continued use of
  `israel-hamas-war-2023`, `maersk-red-sea-suspension-2023`, and
  `russia-ukraine-war-attrition-2023`. No new node candidates surfaced this
  batch beyond the `china_tech` edge-weight note above — the two-week
  period was dominated by validating existing nodes (`geopolitical_tension`,
  `shipping_costs`, `china_tech`) under real stress rather than exposing new
  gaps, which is itself a useful data point: the graph's current node set is
  holding up well against sustained, compounding crises, not just discrete
  one-off shocks.

- **2024-01-06/07: Boeing 737 MAX 9 door-panel blowout exposes a genuine
  coverage gap — no aerospace/commercial-aviation node exists**. On 5
  January an Alaska Airlines 737 MAX 9 lost a door plug mid-flight,
  leaving a hole "the size of a refrigerator"; the FAA grounded the MAX 9
  fleet and investigators were still assessing design-flaw risk as of
  1-06/1-07. This is a real, high-magnitude, single-company shock (Boeing
  stock fell sharply in the following days in the actual historical
  record) with clear knock-on relevance for airlines, insurers, and
  Boeing's supply chain — but I did **not** tag it to any node, because
  none of the 85 fit: `defense_industry` is aimed at military
  contractors/spending, not commercial aircraft manufacturing/safety, and
  forcing this story onto it would misrepresent the mechanism (a safety
  and regulatory-grounding shock, not a defense-budget shock). Rather than
  force a bad-fit tag, I skipped the event entirely, per the project's
  standing discipline of only tagging events to nodes that actually
  capture their mechanism. Flagging this as a genuine, currently-unfillable
  gap rather than proposing a new node yet — this is a single-company
  story so far (no evidence of a sector-wide pattern), so it doesn't yet
  meet the project's own bar for promotion (which has consistently
  required 3+ independent dated events before drafting a full node
  proposal, per `uk_utilities` and `sanctioned_economy_stress` above). If
  Boeing safety/production issues keep recurring through 2024 — which is
  plausible given this is the same MAX family that had two fatal crashes
  in 2018-19 — that would be the trigger to draft a dedicated
  `commercial_aerospace` or similarly-scoped node covering Boeing/Airbus
  and the broader aircraft supply chain. Noting this now so whoever reads
  this next has the context if/when the pattern recurs, rather than
  re-discovering the gap from scratch.

- **2023-12-28 → 2024-01-10 batch summary** (14 days, 39 events, 44 node
  tags, events/day 2.79 — activity picked back up sharply from the
  Christmas lull as the new year opened with an unusually dense run of
  discrete geopolitical shocks): `geopolitical_tension` hit **47.7%**
  (21/44), the highest concentration of the entire project, edging past
  the previous high (44.7%, mid-November). Unlike that November spike —
  which I flagged at the time as partly a novelty-scoring judgment call on
  serial diplomatic recaps — this one is not a judgment-call artifact: the
  batch contained a genuinely unusual cluster of **distinct, high-novelty**
  origin shocks, each opening its own event_key rather than recapping an
  existing one: the Arouri assassination in Beirut (1-02), the Kerman
  bombing that killed ~84-100 people (1-03), a US strike on an Iran-backed
  militia leader in Baghdad (1-04), Hezbollah's "inevitable response" vow
  (1-05), confirmed Russian use of North Korean missiles (1-05), the
  Israel/Hezbollah drone-on-command-base incident (1-09), and the largest
  Houthi Red Sea attack yet (1-10) — seven separate new geopolitical
  event_keys opened in a 9-day span, versus roughly one every 2-3 days in
  prior batches. 29 of 39 events scored novelty=1.0 (74%), also the highest
  ratio of the project, consistent with a period of genuine escalation
  rather than grinding recap. `credit_conditions` (11.4%) and
  `shipping_costs` (4.5%, likely under-counting the Red Sea story's true
  weight since several Houthi-related events this batch were scored as
  pure `geopolitical_tension` rather than dual-tagged — worth a
  consistency check next batch) rounded out the rest. Two new event_keys
  worth flagging for whoever tunes edge weights: `israel-arouri-assassination-2024`
  and `israel-hezbollah-escalation-2024` are effectively a second front
  opening up in parallel to `israel-hamas-war-2023` — if this project's
  `geopolitical_tension` edge weights assume a single-conflict shock
  profile, the risk of simultaneous multi-front Middle East escalation
  (Gaza + Lebanon + Iran-proxy strikes in Iraq + Red Sea) is worth
  explicitly modelling, since by 1-10 all four were live simultaneously.
  One clean structural validation: the Japan Noto Peninsula earthquake
  (1-01) tagged cleanly to `japan_equities` despite being a natural
  disaster rather than a market/policy shock — worth noting this is a
  reasonable fallback pattern (country-equity node absorbing
  country-level catastrophe risk) but the Boeing 737 MAX 9 event the same
  week (1-06/1-07/1-09, door-plug blowout, FAA grounding, loose-bolt
  findings on inspection) had no equivalent fallback and was left
  untagged — see the dedicated gap note above. No new node candidates
  proposed this batch beyond the standing Boeing/aerospace watch item;
  the two-week period again validated existing node design under real
  stress (particularly `geopolitical_tension` absorbing genuinely novel,
  high-magnitude, multi-front escalation cleanly) rather than surfacing
  new structural gaps.

- **2024-01-11 → 2024-01-24 batch summary** (14 days, 46 events, 60 node
  tags, events/day 3.29 — the busiest batch of the project so far by
  event volume): This was the batch where the Red Sea crisis turned from
  threat into shooting war — the US and UK launched actual kinetic strikes
  on Houthi targets in Yemen on 1-12 (`us-uk-houthi-strikes-prep-2024`),
  followed by four further rounds of strikes through 1-20, two US Navy
  SEALs killed in a related raid (1-22), and Iran opening direct strikes
  on Pakistan and Iraq in the same window. `geopolitical_tension` eased
  somewhat to 31.7% (19/60) from the prior batch's record 47.7%, while
  `shipping_costs` climbed to 16.7% (10/60) — up sharply from 4.5% last
  batch — which directly validates the self-critique flagged in the prior
  batch summary (that Houthi events were being under-dual-tagged); I
  corrected course this batch by dual-tagging `geopolitical_tension` +
  `shipping_costs` on every Houthi/Red Sea strike event rather than
  defaulting to `geopolitical_tension` alone. `credit_conditions` (13.3%)
  picked up a cluster of UK data (inflation surprise to 4.0%, retail sales
  collapse, business insolvencies, bank default forecasts) alongside two
  genuinely new node validations: `china_stimulus` fired twice on
  independent, high-conviction shocks — the reported £222bn state rescue
  plan (1-23) and the PBOC's biggest reserve-ratio cut since Dec 2021
  (1-24) — landing one day apart, which is a clean real-world stress test
  of both `china_stimulus` and the newly-tagged `pboc_rate`. `us_elections`
  also got its first real workout this batch (Iowa caucus 1-16, DeSantis
  drop-out 1-21, New Hampshire primary 1-24), tagging cleanly across all
  three. One correction worth flagging for whoever reviews event quality:
  I again left the recurring Boeing 737 MAX 9 story (FAA formal inquiry
  1-11, loose-bolt findings, online travel agents letting customers filter
  out the model) untagged rather than force-fitting it — this is now a
  multi-week, multi-event pattern (first flagged 1-06/1-07 above) and is
  approaching the evidence bar this project has used elsewhere for
  promoting a "watching" item to a full node proposal; if it recurs into
  February I will draft a full `commercial_aerospace` proposal rather than
  continuing to note-and-skip. No other new node candidates surfaced this
  batch — the two-week period again exercised existing and recently-added
  nodes (`geopolitical_tension`, `shipping_costs`, `china_stimulus`,
  `pboc_rate`, `us_elections`) under real, high-volume stress rather than
  exposing fresh structural gaps.

- **2024-01-25: Boeing 737 MAX 9 grounding resolved after ~3 weeks — closing
  the watch item without a node proposal, but flagging a separate, cleaner
  gap it exposed**. The FAA cleared grounded MAX 9s to return to service
  on 1-25, closing the acute phase of the story first flagged on 1-06/1-07
  (door-plug blowout → grounding → loose-bolt findings → formal FAA inquiry
  1-11 → cleared to fly 1-25). Per the standing instruction to draft a full
  proposal if this kept recurring: it didn't escalate into a sustained
  pattern within this window (single aircraft family, single root cause,
  resolved in three weeks), so I'm not drafting `commercial_aerospace` yet
  — but the underlying gap (no node for commercial aviation
  safety/manufacturing shocks) remains real and untested against a bigger
  case; worth revisiting if Boeing has another incident later in 2024 (the
  MAX family's history suggests this is plausible) or if Airbus has a
  comparable one. **Separately**, today's US Q4 GDP print (3.3%
  annualized, beat expectations) exposed a cleaner, more clear-cut gap:
  there is no dedicated US growth/GDP node in the 85-node set. I tagged it
  to `fed_rate` as the best available proxy (GDP surprises are Fed-relevant),
  but that's a stretch — `fed_rate` is about the policy lever, not the
  growth data that feeds into it, and this project already has
  `china_growth`, `europe_growth`, `korea_growth`, `india_growth` as
  country-growth nodes but no `us_growth` counterpart. This is a more
  clear-cut, structural gap than the Boeing item: the omission isn't about
  novelty of evidence, it's a straightforward parity gap against nodes
  that already exist for other major economies. Recommending a `us_growth`
  node (GDP prints, ISM/PMI surveys, recession-risk headlines) be added
  alongside the existing country-growth family — this would also relieve
  `fed_rate` and `us_employment` from being overloaded as growth-data
  proxies, which has been happening informally throughout this digest.

**Correction/refinement, 2024-04-25**: the `us_growth` gap is real but the
fallback story is messier than the note above suggests. A grep of past
events turns up a *third* fallback in use: the 2023-11-29 Q3 GDP revision
was tagged to `us_consumer` (not `fed_rate`), and today's Q1 2024 GDP
slowdown (1.6% annualized, driven explicitly by weaker consumer spending)
was also tagged `us_consumer` for consistency with that precedent. So the
same underlying data type — a US GDP print — has now been tagged to
`fed_rate` once (Jan 2024, framed through the "Fed reaction function"
angle) and `us_consumer` twice (Nov 2023 and today, framed through the
"consumer spending strength" angle), purely depending on which framing
that day's article happened to use. Neither is wrong exactly — GDP
strength genuinely is both Fed-relevant and consumer-spending-driven —
but it means the *same economic fact* is currently routed to different
nodes depending on journalistic framing rather than the fact itself,
which is exactly the kind of inconsistency a dedicated `us_growth` node
would fix. This raises `us_growth`'s promotion case from "one dated event"
(the 2024-01-25 note) to at least three independent GDP-print events
across two different existing-node workarounds — this should now be
considered to have met the "second independent event" bar set in row #13
of the summary table above, and `us_growth` should be moved from
**BUILDING** to **READY** for the next full spec-writing pass.

- **2024-01-25 → 2024-02-07 batch summary** (14 days, 40 events, 48 node
  tags, events/day 2.86): `geopolitical_tension` at 35.4% (17/48), roughly
  back to its running average after the two prior batches' record highs —
  the US-Iran-proxy strike/counter-strike cycle (Jordan drone attack →
  85-target US retaliation → "just the beginning" → SDF base attack) and
  the Israel/Rafah escalation continued to dominate, but this batch's
  defining feature was breadth rather than concentration: this is the
  first batch where **earnings season and macro data genuinely competed
  with geopolitics for tagging share** — `us_megacap_tech` alone hit 8.3%
  (Meta, Amazon, Apple, Microsoft all reporting in one eight-day span),
  and `fed_rate`, `healthcare`, `credit_conditions`, `oil_price`,
  `tsla` each landed multiple independent tags. Two structural findings
  from this batch are recorded as full proposals elsewhere in this
  document rather than repeated here: **`commercial_aerospace`** (§11,
  promoted 2024-02-05 after three independent Boeing/Spirit AeroSystems
  defect types surfaced within a month) and **`us_growth`** (flagged
  2024-01-25, a clean parity gap against the existing `china_growth`/
  `europe_growth`/`korea_growth`/`india_growth` family). Two other
  validations worth noting briefly: `china_stimulus` and `china_property`
  both fired on genuinely major, independent events this batch — the
  PBOC's RRR cut (carried over from the prior batch) and, far more
  significantly, the Hong Kong court's liquidation order against
  Evergrande (2024-01-29), the single highest-magnitude China-property
  event tagged in this project to date. Novelty mix skewed heavily toward
  1.0 (31/40, 77.5%) — consistent with a batch full of discrete,
  first-occurrence shocks (earnings prints, the Evergrande ruling, the
  EU's €50bn Ukraine package, Novo Nordisk's Catalent acquisition) rather
  than recap chains. No other new node candidates surfaced.

- **2024-02-21: Boeing's 737 MAX program chief ousted — further evidence for
  `commercial_aerospace`, no action needed**. Ed Clark, the head of the 737
  MAX program, was pushed out following the door-plug blowout, roughly six
  weeks after the original incident and two weeks after this project
  promoted `commercial_aerospace` to a full proposal (§11, 2024-02-05).
  This is exactly the kind of follow-on evidence the proposal anticipated
  — noting it here for the record, but no further action is needed since
  the node spec is already drafted and marked READY in the summary table.

- **2024-02-08 → 2024-02-21 batch summary** (14 days, 39 events, 47 node
  tags, events/day 2.79): `geopolitical_tension` climbed back to 44.7%
  (21/47), tied with the November 2023 record, but for reasons that are
  genuinely structural rather than a novelty-scoring artifact this time —
  this batch contained an unusually dense run of **first-occurrence**
  shocks, each opening a new event_key: Alexei Navalny's death in prison
  (2-16, arguably the single highest-magnitude individual-death political
  story of the project so far), the fall of Avdiivka (2-17/18, Russia's
  biggest territorial gain since May 2023), Trump's remarks inviting
  Russia to attack under-spending Nato allies (2-11), reports of a Russian
  anti-satellite nuclear weapon in space (2-14), and a new China-Taiwan
  coastguard confrontation (2-20/21) — five distinct, independent,
  high-novelty geopolitical shocks in a two-week span, on top of the
  ongoing Gaza/Rafah and Red Sea threads. 27 of 39 events (69%) scored
  novelty=1.0, consistent with a batch of discrete new stories rather than
  recap chains. Away from geopolitics, this batch delivered two of the
  cleanest node validations of the project: **`ai_capex_cycle`** fired on
  both Arm's 50%+ earnings-day surge (2-08) and Nvidia's 250%+ revenue
  growth "AI tipping point" quarter (2-21), and **`china_financials`** /
  `china_property` both fired on the Evergrande-adjacent HSBC hit (2-21)
  alongside a standalone China shadow-banking distress story (2-18) —
  real confirmation that the existing node set handles a China-financial-
  contagion narrative without needing new nodes. `credit_conditions`
  picked up the UK's slide into technical recession (2-15) and Japan's
  loss of its rank as the world's third-largest economy (2-15, tagged to
  `japan_equities`) — two developed-economy recession prints landing the
  same day, a reminder that macro deterioration in Q4 2023/Q1 2024 was a
  genuinely global, not just UK-specific, story. No new node candidates
  surfaced this batch beyond the standing Boeing follow-up noted above.

- **2024-02-22 → 2024-03-06 batch summary** (14 days, 35 events, 44 node
  tags, events/day 2.5 — the quietest batch by volume since the holiday
  lull, but not a quiet batch by content): `geopolitical_tension` fell to
  **27.3%** (12/44), the lowest concentration recorded in this project to
  date, as markets and elections genuinely competed for narrative share —
  `us_elections` picked up its heaviest single-batch weight yet (9.1%,
  4/44: South Carolina, Michigan, the Colorado ballot SCOTUS ruling, and
  Super Tuesday), and `nvda`/`risk_appetite` together absorbed the AI-
  market-euphoria storyline (Nvidia's $2tn valuation, back-to-back S&P/
  Nasdaq record closes) as a genuinely distinct thread from geopolitics
  for the first time in the project. Two fresh record-high commodity/
  crypto prints landed in a single week — bitcoin's new all-time high
  above $69k (3-05, surpassing the Nov-2021 record) and gold's record
  high the same day — both driven by a mix of Fed rate-cut speculation
  and Gaza-war safe-haven demand, a clean example of one shock (rate-cut
  expectations) propagating through multiple asset nodes simultaneously
  without needing to be tagged to all of them. On the geopolitical side
  itself, the shocks that did land were unusually severe even if fewer in
  number: Macron's refusal to rule out Nato ground troops in Ukraine
  followed two days later by Putin's explicit nuclear-war warning to Nato
  (2-27/2-29) is the sharpest rhetorical escalation ladder logged in this
  project so far; the killing of 100+ Palestinians at a Gaza aid convoy
  (2-29) and the first commercial-shipping-crew fatalities of the Houthi
  campaign (3-06) both mark grim new severity thresholds within their
  respective ongoing event_keys rather than opening new ones. No new node
  candidates surfaced this batch — the two-week period validated the
  existing node set's ability to carry a genuinely mixed macro/geopolitical/
  markets narrative without forcing everything through `geopolitical_tension`,
  which is itself a useful signal that the over-concentration seen in
  several earlier batches was substantially event-driven (real-world
  crisis density) rather than a structural tagging-discipline problem.

- **2024-03-07 → 2024-03-20 batch summary** (14 days, 33 events, 39 node
  tags, events/day 2.36 — a return to the lower end of this project's
  volume range, but with unusually high macro-monetary-policy density):
  `geopolitical_tension` sat at 30.8% (12/39), roughly the project's
  long-run average, while `fed_rate` and `credit_conditions` each hit
  7.7% — this was the batch that finally delivered the long-awaited
  synchronized central-bank read: the Fed held (3-20, three cuts still
  signalled for later in 2024), the Bank of Japan raised rates for the
  first time since 2007 (3-19, ending eight years of negative rates,
  tagged cleanly to the existing `yen_carry` node — a clean validation
  that the node's original design premise, that BoJ policy shifts are
  the mechanism worth tracking, holds up under a real regime change), and
  UK CPI fell to a 2.5-year low (3-20) — three independent monetary-
  policy events from three different central banks landing within 24
  hours of each other. `china_property` also picked up a second
  Evergrande-adjacent event this batch (the $78bn fraud fine, 3-19),
  continuing to validate that node's coverage of the ongoing crisis
  without needing further expansion. No new node candidates surfaced —
  this was a batch of existing-node validation (`yen_carry`, `fed_rate`,
  `china_property`, `us_tech_regulation` via the TikTok divestment bill's
  progress through the House) rather than gap discovery, consistent with
  the pattern in recent batches where the marginal rate of new-node
  findings has slowed as the 85-node baseline plus the ~12 proposals
  already drafted in this document cover an increasing share of the
  archive's real-world shock types.

- **2024-03-21 → 2024-04-03 batch summary** (14 days, 35 events, 37 node
  tags, events/day 2.5): `geopolitical_tension` climbed back to 43.2%
  (16/37), close to this project's record, driven by an exceptionally
  dense run of independent, high-magnitude shocks rather than recap
  chains (24 of 35 events, 69%, scored novelty=1.0): the Moscow Crocus
  City Hall terror attack (3-23, 133+ dead, Russia's worst terror attack
  in two decades), the Israeli strike on Iran's Damascus consulate
  killing two IRGC generals (4-01, opening `israel-iran-consulate-strike-2024`
  — arguably the single most dangerous escalation event logged in this
  project, given the direct-state-to-state risk it carries into the next
  digestion window), the killing of seven World Central Kitchen aid
  workers in Gaza (4-02, `wck-aid-workers-killed-2024`, triggering a
  rare moment of direct US public criticism of Israel), and a
  UN-security-council ceasefire resolution actually *passing* (3-26,
  after five months of vetoes) as the US abstained rather than blocked
  it. Two genuinely new, non-geopolitical shocks are worth flagging for
  whoever tunes node coverage next: the **Baltimore Francis Scott Key
  Bridge collapse** (3-26, cargo ship collision, tagged to
  `shipping_costs` — appropriate given the Port of Baltimore closure and
  Lloyd's calling it a potential record marine-insurance loss, but this
  is a US domestic infrastructure disaster, not a shipping-rate story in
  the usual sense; worth a flag that `shipping_costs` is being asked to
  carry two structurally different mechanisms — Red Sea rerouting costs
  vs. US port-capacity shocks — and may need a closer look if more
  infrastructure-driven port disruptions occur) and the **Taiwan
  earthquake** (4-03, 7.2 magnitude, tagged to `semis`/`tsmc` — a clean
  parallel to the 1-01 Japan Noto earthquake→`japan_equities` pattern,
  reinforcing that country/sector-proxy tagging for natural-catastrophe
  risk is a workable convention worth documenting explicitly in the brief
  rather than continuing to reinvent it ad hoc each time). No new node
  candidates are being proposed from this batch, but the Damascus
  consulate strike deserves a flag for the next digestion session: if
  Iran retaliates directly against Israel in the immediate aftermath
  (plausible given the "vows revenge" framing across every source this
  batch), that would be a strong candidate for the single highest-
  magnitude event of the entire project so far and warrants an
  escalation-check pass at the start of the next batch rather than
  routine headline-only tagging.

**Methodology correction, 2024-04-13** (mid-batch #26): Iran's Revolutionary
Guards seizure of the MSC Aries in the Strait of Hormuz is the first event
this project has hit where a genuinely correct dual-tag has **opposite-sign
polarity conventions across its two nodes** — `geopolitical_tension` (+1 =
escalating, clearly positive here) vs. `oil_supply` (+1 = more barrels
available; a Hormuz chokepoint threat is a *risk to* supply, so correctly
signed it's negative). The established Houthi/Red Sea dual-tag convention
(`geopolitical_tension` + `shipping_costs`, single shared polarity) only
worked because both of those nodes happen to move in the same direction
under escalation (tension up → shipping costs up, both positive). That is
a coincidence of those two specific nodes, not a general property of dual-
tagging, and I was about to silently misapply it here — a single shared
`+0.6` polarity across `["geopolitical_tension", "oil_supply"]` would have
told the graph "oil supply is increasing" during a supply-risk event,
exactly backwards. **Fix applied**: split into two separate event objects
(same `ts`, different `event_key`s) sharing a common headline/timestamp,
each carrying the polarity sign appropriate to its own node's convention —
`geopolitical_tension` at +0.6 (reusing the ongoing
`israel-iran-consulate-strike-2024` key) and `oil_supply` at -0.2 under a
new `hormuz-oil-chokepoint-risk-2024` key (kept low-magnitude/low-
confidence since no actual tanker flow disruption has occurred yet — this
is a risk premium event, not a realized supply shock). **Recommendation
for the brief/spec**: document this explicitly as a rule — before dual-
tagging any event, check each candidate node's polarity convention
independently; only share a single polarity value across nodes when their
conventions are confirmed to move in the same direction for this event
type, otherwise split into parallel event objects. This should be added to
`docs/DIGESTION_SPEC.md` as a named rule, since it will recur any time a
single story touches both a sentiment/tension node and a priced-commodity-
supply node (e.g. future Taiwan Strait-China tension stories touching
`semis`/chip supply would have the same shape).

**Batch summary, 2024-04-04 → 2024-04-17 (batch #26)**: 14 days, 36 events
(2.57/day, in line with the project average), magnitude mean 0.369 /
median 0.35 — both slightly below the project's historical average,
reflecting that this batch, despite containing the single largest
geopolitical event of the entire archive so far (Iran's direct attack on
Israel), also spent several days on lower-magnitude data prints and
de-escalation signals. Novelty mix: 22 new (1.0), 12 material
developments in ledgered events (0.5), plus two intermediate values (0.7,
0.8) used for the first time this batch to mark the Hormuz ship seizure
and the Iranian attack itself — both were genuine phase changes within an
already-ledgered story (threat → action), which the strict 1.0/0.5 binary
underrepresents; worth considering formalizing 0.7-0.8 as a named
"materializes into action" tier in the spec rather than leaving it as an
ad hoc judgment call. `geopolitical_tension` concentration: 18 of 38 node
tags (47.4%) — the highest of any batch this project has logged,
entirely explained by the Iran-Israel escalation ladder running as the
dominant story for 10 of the 14 days (Zaporizhzhia drone strikes, Rafah
invasion date-setting, the Hormuz ship seizure, the attack itself, the
"operation concluded" de-escalation signal, Israel's "will respond"
reversal, and US sanctions on Iran — all correctly sharing the
`israel-iran-consulate-strike-2024` event_key). This is not a tagging
artifact; it is what a real six-day march from consulate strike to
direct state-on-state attack and back to uneasy de-escalation actually
looks like in event-count terms. `credit_conditions` (4 tags, UK and IMF
monetary-policy stories) and `risk_appetite` (2 tags) were the next most
common, both genuine. Notable single-instance validations this batch:
`oil_price` (first-ever live use — Brent's post-attack de-escalation
dip), `tsla` and `aapl` (first-ever live use of individual mega-cap
tickers as event nodes rather than sector themes — Tesla's 14,000-job
cut and Apple's China iPhone slide both cleanly fit their existing asset
nodes with no forcing required), `ecb_policy` (ECB hold-with-guidance,
clean parallel to the Fed/BoJ pattern already validated in prior
batches), and `us_china_tariffs` (Biden's steel-tariff escalation,
first live use since the node's initial seeding). Two new gap flags
opened this batch: **`uk_growth`** (§ table row #14 above — confirmed via
grep that zero UK growth/output/equities nodes exist in the 85-node
graph, surfaced when the UK's exit from recession and FTSE 100's
1-year high had no home) and the **dual-tag polarity-convention bug**
caught and fixed before it reached the ledger (documented above) — a
process finding as valuable as any node proposal, since it will recur.
Boeing whistleblower stories (FAA 787 Dreamliner investigation, "hundreds
could die" Senate testimony, United Airlines citing a $200m earnings hit
from the 737 Max 9 grounding) continued accumulating this batch,
further overdetermining the already-promoted `commercial_aerospace`
node (§11) — no new promotion action needed, just noting the evidence
keeps compounding. No escalation-check surprises: the Iran retaliation
risk flagged at the end of the previous batch materialized almost
exactly as anticipated, validating that flagging forward-looking
escalation risk at batch boundaries is a good habit to keep.

**Batch summary, 2024-04-18 → 2024-05-01 (batch #27)**: 14 days, 30 events
(2.14/day, the lowest of any batch so far), magnitude mean 0.322 / median
0.3 — both noticeably below batch #26's, consistent with this batch
being the "exhale" after the Iran-Israel direct-strike peak: the
escalation ladder resolved into a contained, muted Israeli response
(2024-04-19) and the story genuinely quieted rather than continuing to
generate high-magnitude events. Novelty mix: 21 new (1.0), 8 material
developments (0.5), one 0.7 (the muted-Israeli-response event, which is
a real de-escalation phase-change within the ledgered story, similar to
the 0.7/0.8 tier introduced last batch). `geopolitical_tension` fell to
29.0% (9/31 tags) — down sharply from batch #26's record 47.4%, and the
first batch since the Iran-Israel escalation began where it wasn't the
single dominant driver of the whole batch. **`tsla` was the standout of
this batch at 19.4% (6/31 tags)** — layoffs, the Cybertruck recall,
Autopilot's NHTSA investigation, sector-wide price cuts, the Q1 earnings
beat on affordable-EV timing, and the China/Baidu FSD deal all landed in
a two-week window, making Tesla the single most newsworthy individual
company this project has tagged to date. This is a legitimate reflection
of an unusually eventful stretch for one company, not over-tagging: each
of the six events is a distinct, independently-reportable story (recall
≠ layoffs ≠ regulatory probe ≠ pricing ≠ earnings ≠ partnership), and
each was verified against the node's existing convention before tagging.
Worth flagging as a pattern to watch, though: if single-ticker
concentration like this recurs for other Magnificent-Seven names, it's a
signal the digest is (correctly) capturing company-specific volatility
that the sector-theme nodes alone would miss — validates having
individual mega-cap tickers (`tsla`, `aapl`) available as tagging targets
alongside sector themes. `ai_capex_cycle` also had a strong showing
(3 tags: Meta's spend-more-warn-revenue selloff, Microsoft/Alphabet's
spend-more-beat-expectations rally, and Amazon's AWS/AI revenue beat) —
notable because the *same* underlying phenomenon (hyperscaler AI capex)
produced diverging stock reactions depending on whether revenue was
already showing up, a useful real-world confirmation that `ai_capex_cycle`
alone isn't sufficient signal without company-specific context, which is
exactly why `tsla`/`aapl`-style individual tickers matter alongside it.

**New gap flag, 2024-04-30**: Amazon's AI/AWS earnings beat had no
individual-ticker node to land on — a grep of `seed.py` confirms there is
no `amzn` node anywhere in the 85+88-node graph, despite `aapl` and `tsla`
both existing as individual asset nodes and Amazon being comparably
significant (a Magnificent Seven constituent, the story of the day being
explicitly about AWS/AI revenue, not a sector-wide theme). The event was
tagged to `ai_capex_cycle` instead, which is directionally correct but
loses the company-specific signal the same way `us_china_tariffs`-only
tagging would lose company-specific signal for a single steel producer.
Recommend adding `amzn` (asset, symbol AMZN) as a straightforward parity
fix alongside the `aapl`/`tsla`/`msft`/`googl` cluster — no spec judgment
call needed here, this is a pure oversight-style gap, not a
promotion-bar judgment call like the theme/factor proposals above.

**Continuing evidence, not yet promoted**: `uk_growth` (proposed #14)
picked up several more data points this batch that never got tagged
because no node fits — FTSE 100 hitting fresh record closes on five
separate days across this batch (04-22, 04-23, 04-24, a "sixth
consecutive session of gains" on 04-24, and again on 04-26), UK
manufacturing PMI contracting (05-01), and continued London-listing
exodus stories (Flutter's shareholder vote to move its primary listing
to New York, 05-01, joining Shell/CRH/DS Smith/Darktrace already noted
in earlier batches) that have no clean home either. This is now a very
deep evidence trail — arguably deeper than several nodes already marked
READY — and should be considered for promotion to READY once a spec for
the FTSE-exodus / "UK equities as an international laggard" angle is
drafted (a Guardian piece on 04-23 literally titled "FTSE 100 is an
international laggard despite its record high" makes the case better
than this document can).

**Self-correction, 2024-05-10**: while leaving UK GDP/FTSE stories
untagged throughout April (per the `uk_growth` gap notes above), a grep
of pre-2024 event files turns up an inconvenient fact: UK GDP prints
*were* tagged to `europe_growth` on at least three prior occasions
(2023-07-13, 2023-11-10, 2023-12-13), predating this session's
continuation. So there was already an established, if imperfect,
fallback in use — I simply stopped using it partway through this
project without realizing it, treating every UK growth data point since
roughly 2024-04-12 as untaggable rather than checking for precedent
first. Today's UK Q1 2024 GDP print (+0.6%, fastest since 2021, exiting
recession) has been tagged to `europe_growth` for consistency with that
earlier precedent, reversing the "leave untagged" approach used for the
several UK GDP/FTSE stories in between. This doesn't invalidate the
`uk_growth` proposal — `europe_growth` conflates a non-eurozone economy
with a currency union it isn't part of, which is exactly the kind of
imprecision a dedicated node would fix, and post-Brexit UK growth
dynamics have genuinely diverged from the eurozone's (see the OECD's
2024-05-02 forecast that the UK will be the *slowest*-growing G7 economy
in 2025, a divergence `europe_growth`-tagging would blur). But it does
mean the several untagged UK GDP/FTSE events between 2024-04-12 and
2024-05-09 are a real, avoidable gap in the ledger, not a principled
absence — worth a note for whoever eventually reviews ledger completeness,
and a reminder to check for existing tagging precedent (via the ledger
or a grep of past events) before concluding something is untaggable,
not just checking the current node list.

**Batch summary, 2024-05-02 → 2024-05-15 (batch #28)**: 14 days, 31 events
(2.21/day), magnitude mean 0.334 / median 0.3 — both in the normal range,
slightly above batch #27's low but still below batch #26's Iran-Israel
peak. Novelty mix: 19 new (1.0), 8 material developments (0.5), one 0.7
and three 0.8 — the 0.8 tier (introduced batch #26, used once in batch
#27) got real use this batch, all three marking genuine phase-changes
within ongoing stories rather than routine updates: the Rafah ground
offensive actually launching (05-07, after weeks of threat), Biden's
weapons-pause threat materializing into an actual halt (05-08), and the
China EV tariff threat becoming a formal 100% tariff (05-14). This
3-for-14-days rate suggests 0.7-0.8 is filling a real gap between "brand
new story" and "routine update" — worth formalizing in
`docs/DIGESTION_SPEC.md` as discussed in the 2024-04-13 methodology note.
`geopolitical_tension` hit 48.4% (15/31) — effectively tying batch #26's
record — driven by two simultaneous escalation ladders running in
parallel for the first time: the Israel-Rafah offensive (accept
ceasefire → strike anyway → US arms pause threat → actual pause → tanks
in residential areas) and a second, independent one (Putin's Shoigu
reshuffle, Russia-Belarus nuclear drills, Fico's shooting, Georgia's
"foreign agents" crackdown) that had nothing to do with the Middle East.
Two geopolitical storylines running hot simultaneously, rather than one
dominant thread, is a new pattern for this project and probably the
right explanation for the concentration rather than a tagging artifact.
`us_china_tariffs` had its strongest showing yet (3 tags: US sanctions on
China over Russia support, the tariff-expansion threat, and the formal
100% EV tariff) — a clean three-step escalation arc tagged consistently
to one node throughout. `aapl` appeared twice independently (iPhone
sales slump, Buffett/Berkshire stake sale) — good validation that the
individual-ticker nodes added to the graph are earning their keep the
way `tsla` did last batch. New node used for the first time: `arm`
(SoftBank/Arm's AI-driven earnings) and `uranium_price` (the Russian
uranium import ban) — both clean, unforced fits with no ambiguity.

**Batch-boundary escalation-check note**: two threads are live heading
into the next batch and deserve attention at the start of the next
session rather than routine treatment — (1) Israel's Rafah offensive was
still intensifying as of 2024-05-15 with no ceasefire resolution, and
Israel-Egypt relations were reportedly deteriorating over the border
crossing seizure, a new friction point worth watching; (2) Robert Fico's
shooting (05-15) has an unresolved outcome — his condition was described
as "fighting for his life" in the last event of this batch, so the very
first days of the next batch should check whether he survived, as that
materially changes the magnitude/framing of any follow-on Slovak
political-instability coverage.

**Batch summary, 2024-05-16 → 2024-05-29 (batch #29)**: 14 days, 32 events
(2.29/day), magnitude mean 0.325 / median 0.3 — both in the normal range.
Novelty mix: 18 new (1.0), 6 material developments (0.5), six 0.7 and two
0.8 — the highest-ever share of the intermediate "phase change" tier
(8 of 32 events, 25%), reflecting how much of this batch consisted of
existing threads escalating into new, more concrete stages rather than
either brand-new stories or routine updates: Russia's nuclear drills
threat becoming actual drills, China's Taiwan rhetoric becoming actual
"punishment" military exercises (twice — inauguration response, then a
second day testing "seize power" capability), the ICJ's Rafah ruling,
Israel defying it, and the Rafah tent-camp strike that followed. This
continues to validate the 0.7/0.8 tier introduced in batch #26 as filling
a real gap. **`geopolitical_tension` hit a new all-time high of 59.4%**
(19/32 tags), surpassing batch #26 and #28's ~48% records. Unlike
earlier concentration spikes, this one was not a single dominant thread
— it was **three simultaneous, independent escalation ladders**
running at once for the first time in this project's history: (1) the
Israel-Gaza war's most violent stretch yet (Rafah ground offensive →
ICJ ruling → Israel defying it → Hamas's first Tel Aviv missile strike
in months → the 45-death tent-camp strike → US declining to treat it as
a red line), (2) the Iran succession shock (Raisi's helicopter crash,
death, and funeral) compounding pre-existing Iran-Israel tension, and
(3) a China-Taiwan flare-up (Lai's inauguration, two days of PLA
"punishment" drills) running fully independently of the other two. Three
concurrent high-magnitude geopolitical threads, rather than one or two,
is a new pattern and the honest explanation for the record concentration
— not a tagging artifact. `europe_growth` had its strongest showing yet
(4 tags: UK Q1 GDP recession-exit, UK services PMI slowdown, UK retail
sales slump then rebound) — directly downstream of the 2024-05-10
self-correction to resume tagging UK growth data via this existing node
rather than leaving it out. Escalation-check from the prior batch
resolved cleanly: Fico confirmed stable and "will survive" on 2024-05-16,
the first day of this batch, allowing normal-priority treatment of
Slovak coverage for the rest of the batch as anticipated.

**Batch-boundary escalation-check note**: three threads remain live
heading into the next batch — (1) Israel's Rafah offensive continues
with no ceasefire and deepening international isolation (three more
countries recognizing Palestine, ICC arrest-warrant request against
Netanyahu, ICJ ruling defied); (2) Iran's presidential election process
is just beginning following Raisi's death, worth watching for succession
surprises; (3) the UK general election campaign (called 2024-05-22 for
2024-07-04) will generate a sustained stream of political-but-not-quite-
market-moving stories for the next six weeks — worth a light touch on
routine campaign-trail tagging so it doesn't crowd out genuine
market-relevant UK stories the way US campus-protest coverage has
largely been left untagged throughout these batches.

**Batch summary, 2024-05-30 → 2024-06-12 (batch #30)**: 13 days of data
(2024-06-11 is genuinely absent from the source archive — confirmed via
direct date scan of `news_archive_guardian.jsonl`, not a bug in
`_extract_day.py`; noting this explicitly since a missing day could
otherwise look like a skipped-digestion error to a future reader), 35
events, 2.69/day — the highest per-day rate of any batch so far. Magnitude
mean 0.344 / median 0.35, both slightly above the project's historical
average. Novelty mix: 20 new (1.0), 7 material developments (0.5), seven
0.7 and one 0.8 — the 0.7 tier saw its heaviest use yet (7 of 35 events,
20%), reflecting a batch dense with existing threads snapping into new
concrete phases: Gantz's resignation threat becoming real, the Hezbollah
front igniting from tension into an actual rocket salvo, GameStop's
speculative spike reversing into a 40% crash, India's coalition
uncertainty resolving, and the EU's "expected" China EV tariffs becoming
an actual 38% rate. `geopolitical_tension` normalized to 34.3% (12/35) —
down from batch #29's 59.4% record, consistent with the Israel-Iran/
Taiwan/Rafah triple-escalation cooling somewhat, even as two *new*
fronts opened (Israel-Hezbollah in the north; France's snap election).
Central-bank policy had an unusually busy batch: `fed_rate` (3 tags:
May PCE, the strong May jobs report cooling cut hopes, and the June
FOMC hold), `ecb_policy` (2 tags: the ECB's first cut since 2019, plus
the hot May eurozone CPI print that preceded it) — a clean two-step
sequence showing the ECB moving first among major western central
banks despite a inflation surprise the same week, a genuinely
newsworthy divergence from the Fed's continued hold.

**Correction applied mid-batch, 2024-05-30 and 2024-06-07**: caught and
fixed the same dual-tag polarity bug documented on 2024-04-13 twice more
this batch, before it reached the ledger — once for "Eurozone unemployment
falls to record low; US GDP growth revised down" (split into two events:
`europe_growth` positive, `us_consumer` negative) and once for "US adds
272,000 jobs... dollar rallies as jobs report dampens rate cut hopes"
(split into `us_employment` positive / `fed_rate` negative). Both cases
had the same shape as the original Hormuz/oil_supply bug: a single
headline covering two nodes whose polarity conventions move in opposite
directions for that event. This is now a recurring, predictable failure
mode — worth promoting from a one-off note to an actual pre-write
checklist item: *before finalizing any event with 2+ nodes, explicitly
state each node's polarity direction in a scratch note and confirm they
agree, or split.* Three occurrences across three different batches
(04-13, 05-30, 06-07) is enough evidence this should go in
`docs/DIGESTION_SPEC.md` as a named, mandatory check, not just documented
prose in this log that relies on remembering to re-read it.

**New/reinforced macro storylines this batch**: France's snap election
(Macron, 2024-06-09) introduced a new kind of event this project hasn't
tagged before — a developed-economy political-risk shock with no clean
dedicated node (tagged to `geopolitical_tension` and, for the market
reaction, `risk_appetite`, both defensible but imprecise). If French
political risk continues generating events through the snap election
(scheduled for early July), worth watching whether `europe_growth` or a
new node is needed for "eurozone political/fiscal risk" specifically,
distinct from the growth-data angle `europe_growth` already covers well.
`india_equities` validated cleanly across a three-event arc this batch
(shortfall shock → coalition secured → Modi sworn in), each with
correctly opposite-signed polarity as the uncertainty resolved — a good
model for how to handle multi-day political-resolution arcs generally.

**Batch summary, 2024-06-13 → 2024-06-26 (batch #31)**: 14 days, 40 events
(2.86/day, a new high), magnitude mean 0.338 / median 0.35, both in the
normal range. Novelty mix: 19 new (1.0), 8 material developments (0.5),
9 at 0.7 and 4 at 0.8 — the 0.7/0.8 "phase change" tier now consistently
accounts for roughly a third of every batch (13 of 40 here, 32.5%),
confirming it has settled into a stable, meaningful category rather than
a one-off experiment; this project should treat it as permanent going
forward rather than revisiting whether to keep it. `geopolitical_tension`
hit 53.7% (22/41 tags) — the second-highest concentration on record,
driven by an unusually large number of simultaneous fronts: Israel-Gaza
(Rafah, the tent-camp strike, Gantz's resignation, the war cabinet's
dissolution, the ultra-Orthodox draft ruling), Israel-Hezbollah (rocket
salvoes, Nasrallah's Cyprus threat, Iron Dome overwhelm warnings),
Russia-North Korea (the visit, the defence pact, western alarm), France's
snap election, and a new Dagestan-attacks and Bolivia-coup thread. Five-plus
concurrent geopolitical storylines is now the norm rather than the
exception for this stretch of 2024 — worth flagging to whoever eventually
reviews the ledger that mid-2024 genuinely was an unusually dense period
for global instability, not a sign this project over-tags. Two new
individual-ticker validations: `nvda` (Nvidia's ascent to world's most
valuable company, then a sharp $500bn three-day correction — both
tagged, showing the node handles volatility in both directions cleanly)
and continued strong use of `ev_supply_chain` (Fisker's bankruptcy,
Rivian's Volkswagen lifeline — a sector node capturing genuinely opposite
outcomes for two different EV makers in the same week, good evidence the
theme-level node is working as intended rather than needing to fragment
into more individual tickers).

**Process note**: the pre-write dual-tag polarity checklist introduced at
the end of batch #30 was applied throughout this batch with no violations
caught — either the discipline is working, or this batch simply had fewer
opportunities for the failure mode (most multi-node events this batch were
single-node `geopolitical_tension` stories). Worth continuing to watch
rather than declaring the bug fully resolved after one clean batch.

**New gap note**: this batch surfaced a story shape not yet clean under
the current node set — France's snap election generated `geopolitical_tension`
tags for the political shock itself and `risk_appetite`/`europe_growth`
tags for market and fiscal consequences, but no single node captures
"eurozone sovereign political-fiscal risk" the way `credit_conditions`
captures monetary policy or `europe_growth` captures output data. If
French political risk continues generating events through the first-round
vote (scheduled 2024-06-30, just after this batch's end) and a potential
second round, this is worth a full gap-analysis proposal in the next
batch rather than continuing ad hoc tagging.

**Batch summary, 2024-06-27 → 2024-07-10 (batch #32)**: 14 days, 37 events
(2.64/day), magnitude mean 0.338 / median 0.35 — both in the normal range
despite this batch containing an unusually dense run of scheduled,
market-moving political events (Biden-Trump debate, French first round,
UK general election, French runoff, NATO summit) — the calendar was
extraordinary but the tagging discipline held steady rather than
inflating magnitudes just because events were "newsworthy." Novelty mix:
20 new (1.0), 8 at 0.7, 5 at 0.8, 4 at 0.5 — the 0.7/0.8 tier (13 of 37,
35%) continues to track close to a third of every batch, now clearly the
stable pattern rather than noise. `geopolitical_tension` at 40.5% — back
down from batch #31's 53.7%, consistent with several fronts (Israel-
Hezbollah, Iran succession) partially resolving even as new ones (Kyiv
children's hospital strike, France's hung parliament) opened. Two
elections resolved in genuinely surprising directions this batch, both
correctly captured with sign reversals: France's runoff (first round
feared →far-right dominance, runoff delivered a shock left-wing win,
tagged with a full polarity flip on the same `france-macron-snap-election-2024`
key) and Iran's presidential runoff (reformist Pezeshkian's win tagged
distinctly de-escalatory relative to the hardline status quo). This
continues to validate the pattern established with India's election in
batch #30 — multi-day political-resolution arcs on a single event_key,
with polarity following the actual resolution rather than staying anchored
to the initial framing. **`us_elections` used for the first time this
project** (3 tags: Biden's debate collapse, the NYT's withdrawal call,
Trump's immunity ruling) — a historically significant stretch for this
node to debut on, capturing the actual week that later proved to be the
turning point toward Biden's eventual withdrawal from the race (a fact
this digestion doesn't yet know, since it is proceeding strictly
chronologically — worth remembering when reading this entry back later
that the "will Biden stay in" uncertainty was still fully live at the time
of writing).

**Process note**: two more dual-tag polarity conflicts were caught and
split before reaching the ledger this batch (the "Eurozone unemployment /
US GDP" pattern did not recur, but a fresh instance appeared in the June
jobs report — `us_employment` cooling tagged negative, `fed_rate`
cooling-therefore-more-likely-to-cut tagged positive, split into two
events under `us-june-2024-jobs-report`). Four occurrences now across
four different batches (04-13, 05-30, 06-07, 07-05) confirms this is a
structural feature of how this project's node conventions work, not a
one-off — the mandatory pre-write polarity-direction check recommended in
batch #30 should be treated as permanent, not provisional.

**Gap analysis still open**: the "eurozone sovereign political-fiscal
risk" node flagged at the end of batch #31 did not get a full spec this
batch despite France generating exactly the kind of evidence anticipated
(the debt risk premium hitting its highest level since 2012, the BIS
head's sovereign-debt warning, the European Commission's excessive-deficit
procedure, and now a hung parliament with no clear path to fiscal
policy). This is now genuinely overdue — recommend the next batch treat
drafting this spec as a priority rather than continuing to fold French
fiscal-risk stories into `risk_appetite` and `europe_growth`, neither of
which captures the specific "can this government actually pass a budget"
mechanism at play.

**2024-07-14 to 2024-07-17 — Trump assassination attempt, VP pick, Taiwan
remarks: three notable events**.

1. **Historic event, correctly tagged despite thin node fit**: the
   assassination attempt on Trump at the Butler, PA rally (2024-07-13
   evening, appearing in the Guardian's 2024-07-14 day-file) was tagged
   solely to `us_elections` at high confidence/magnitude given its
   historic nature (first attempt on a major US presidential candidate in
   decades) and direct campaign-dynamics relevance. New `event_key`
   `trump-assassination-attempt-2024` was established and has since been
   reused across four days (VP announcement, RNC nomination, bandaged-ear
   appearance, Musk PAC donation) as the political-momentum thread of this
   story continues. A distinct, related but separably-motivated market
   event — the "Trump trade" rally in Trump Media stock, broader equities,
   and crypto explicitly driven by markets pricing in higher Trump
   election odds — was correctly split into its own event tagged
   `risk_appetite` + `crypto_majors` with its own `event_key`
   (`trump-trade-market-rally-2024`), rather than folded into the
   assassination-attempt event_key, since the *cause* (assassination
   attempt) and the *node-relevant effect* (election-odds-driven market
   reaction) are conceptually distinct and may not always co-occur this
   cleanly again.

2. **Self-correction — event_key conflation, caught same-day**: on
   2024-07-15 I initially tagged the Florida judge's dismissal of Trump's
   classified-documents case to `event_key: trump-assassination-attempt-2024`,
   which is wrong — the documents case is a wholly separate legal thread
   unrelated to the assassination attempt; the two only appeared temporally
   adjacent by coincidence of the news cycle. Caught and fixed before
   moving to the next day: retroactively edited `events/2024-07-15.json` to
   use a new dedicated `event_key: trump-documents-case-2024`, novelty
   corrected from 0.5 to 1.0 (this is the first ledgered event for this
   thread, not a continuation of anything), and the 2024-07-17 appeal-of-
   dismissal event correctly reused `trump-documents-case-2024` at novelty
   0.5. **Lesson for future digestion**: adjacent-day Trump legal/political
   stories should not be defaulted into whatever Trump-related event_key is
   currently "hot" — pause and ask whether the *causal thread*, not just
   the subject person, actually matches before reusing a key.

3. **Second confirmed instance of the dual-tag polarity-conflict pattern,
   now spanning cross-asset-class nodes, not just macro pairs**: Trump's
   2024-07-17 Bloomberg remarks that Taiwan should "pay the US for its
   defence" was tagged to both `geopolitical_tension` (positive/escalating
   — the remarks raise doubt about the Taiwan Strait status-quo security
   guarantee) and `tsmc`/`semis` (negative — chip stocks sold off on the
   news). These moved in opposite polarity directions for the same
   underlying statement, so per the mandatory pre-write check the event was
   split into two objects sharing the same `ts` but different
   `event_keys` (`trump-taiwan-defense-payment-remarks-2024` for the
   geopolitical angle, `trump-taiwan-remarks-semis-selloff-2024` for the
   market angle). This is the first time the bug pattern has surfaced
   between a macro/geopolitical node and a specific equity/sector node
   (previous four instances were all macro-vs-macro pairs: oil/geopolitics,
   Eurozone unemployment/US GDP, US jobs/fed-rate twice) — worth explicitly
   generalizing the rule in `docs/DIGESTION_SPEC.md` to "any 2+ node tag,
   regardless of node type," not just macro-factor pairs.

4. **Renewed gap evidence — no UK/BoE-specific interest-rate node**: the
   2024-07-17 UK inflation print (stuck at 2%, killing August BoE cut
   hopes) had to be folded into `europe_growth` for lack of a better home,
   which is a real conceptual mismatch (inflation/rate-path data forced
   onto a growth node). This is the same gap flagged implicitly by the
   `boe_rate` proposal noted in the "Note on methodology" section below —
   that proposal still has no full spec. Given the UK's growing standalone
   relevance post-election (multiple BoE-relevant events already ledgered
   this session under `europe_growth` as a workaround), recommend drafting
   the `boe_rate` node spec at the next available gap-analysis slot; it
   would cleanly absorb this and prior UK inflation/rate events without the
   `europe_growth` mismatch.

**Batch #33 summary (2024-07-11 → 2024-07-24)**: rebuilt ledger now holds
672 event_keys across 389 days. This batch spans 46 events over 14 days
(3.29/day — lighter than recent batches, reflecting a stretch where most
days had 1-3 genuinely material stories rather than the usual 3-5), with
magnitude mean 0.327 / median 0.30 — in line with the established normal
range. Novelty mix: 22 new (1.0), 10 at 0.7, 2 at 0.8, 12 at 0.5 — the
0.7/0.8 tier again lands close to a quarter-to-a-third of tags (12 of 46,
26%), continuing to validate this as the stable pattern rather than an
artifact of any one story. Node concentration: `us_elections` 25.9% (14
tags) and `geopolitical_tension` 20.4% (11 tags) together account for
about half of all tags — this was an extraordinarily dense two weeks for
US political news specifically (Trump assassination attempt, JD Vance VP
pick, RNC, documents-case dismissal-then-appeal, Biden's Covid diagnosis,
and finally Biden's withdrawal and Harris's rapid delegate consolidation)
layered on top of an already-escalating Middle East picture (Houthi strike
on Tel Aviv, Israeli retaliation on Hodeidah, ICJ occupation ruling, Khan
Younis "humanitarian zone" re-invasion, Netanyahu's divisive Congress
address).

This batch contains two of the most significant single events digested so
far in this project:

1. **The Trump assassination attempt** (2024-07-13 evening, ledgered
   under `us_elections` given the complete absence of a dedicated
   political-violence/security-risk node) — tagged at high
   magnitude/confidence (0.55/0.85) reflecting its historic nature, with
   the follow-on VP announcement, RNC nomination, and Musk PAC-donation
   news correctly folded into the same `event_key` as continuing beats of
   one story rather than fragmenting into disconnected `event_key`s.
2. **Biden's withdrawal from the race** (2024-07-21), the terminal
   resolution of the `biden-debate-withdrawal-pressure-2024` thread first
   opened in batch #32 — correctly tagged at novelty 1.0 (not 0.7/0.8)
   despite reusing the existing `event_key`, on the reasoning that a
   sitting president's withdrawal is a full state-change equivalent to a
   new event for market-modeling purposes, not merely "more of the same
   pressure." Harris's unusually fast delegate consolidation over the
   following 48 hours (majority of delegates within 2 days, $100m+ raised)
   was tracked as a declining-uncertainty tail on the same key.

**New non-political node validated under real stress**: `crwd` (CrowdStrike)
and `cybersecurity` jointly absorbed the 2024-07-19 global IT outage — the
largest single-vendor IT failure event digested this session — across
four follow-on tags (initial outage, slow recovery, partial fix, $5.4bn
Fortune-500 cost estimate). This is the first live validation of `crwd` as
an asset node and confirms `cybersecurity` works well as the sector-level
complement for outage/breach-class events that don't cleanly belong to any
single company.

**Second confirmed cross-asset-class instance of the dual-tag polarity bug**
(see the 2024-07-17 entry above for full detail): Trump's Taiwan
defense-funding remarks moved `geopolitical_tension` and `tsmc`/`semis` in
opposite directions and were correctly split into two events sharing one
`ts`. Combined with the same-day self-caught event_key conflation (Trump
documents-case dismissal wrongly filed under the assassination-attempt
key, corrected same-day), this batch is a good illustration of the
digestion process's error-correction discipline actually working in
real time rather than only in retrospective batch summaries.

**Fresh gap evidence, not yet spec'd**: (a) no UK/BoE-specific
interest-rate node — UK inflation and jobs-market prints keep getting
folded into `europe_growth` as a workaround (see 2024-07-17 entry); (b) no
node for Alphabet/Google specifically — its Q2 earnings had to be proxied
through `ai_capex_cycle`, which worked reasonably (the earnings were
genuinely about AI capex ROI) but won't generalize to non-AI-related
Alphabet news (antitrust, Search share, YouTube); (c) the Alphabet earnings
episode also surfaced a subtler pattern worth naming — a single earnings
release was legitimately framed as a "beat" on its release day (07-23,
revenue outpaced expectations) and then as a contributor to a "worst day
since 2022" selloff the very next day (07-24, on capex-ROI skepticism) —
both tags were individually correct, but a reader scanning the ledger
without the full narrative arc could mistake this for an inconsistency
rather than a genuine overnight shift in market framing. Worth a
`docs/DIGESTION_SPEC.md` note that same-story polarity reversals across
adjacent days are expected and should be left as-is rather than
retroactively "smoothed."

**Batch #34 summary (2024-07-25 → 2024-08-07)**: rebuilt ledger now holds
693 event_keys across 403 days. This batch spans 49 events over 14 days
(3.5/day), magnitude mean 0.334 / median 0.30 — consistent with the
established normal range. Novelty mix: 23 new (1.0), 5 at 0.7, 4 at 0.8, 17
at 0.5 — the 0.7/0.8 tier (9 of 49, 18%) is lighter than recent batches,
reflecting a batch with an unusually large count of genuinely first-time
events (Haniyeh assassination, Kursk incursion, Bangladesh's Hasina
ouster, the Black Monday selloff, Harris's VP pick) rather than
incremental developments of already-ledgered threads. `geopolitical_tension`
at 29.8% remains the dominant node, but `risk_appetite` (14%) and the new
appearance of `yen_carry` (5.3%, first live use of this node) reflect a
batch where market-structure events briefly rivaled geopolitics for
attention.

This batch covers what is likely the single most eventful two-week
stretch of 2024 digested so far, containing three separate "most
significant single event" candidates:

1. **The Haniyeh assassination** (2024-07-31) — Israel killing Hamas's
   political leader on Iranian soil, hours after killing Hezbollah's top
   commander in Beirut — tagged at the highest magnitude/confidence
   combination used for any `geopolitical_tension` event this session
   (0.55/0.75), on the reasoning that an assassination on the sovereign
   territory of a state (not a proxy) during that state's own presidential
   inauguration is qualitatively different from — and more escalatory
   than — the many prior Gaza/Lebanon strikes ledgered under
   `israel-hamas-war-2023` and `israel-lebanon-hezbollah-tension-2024`.
   This correctly got its own new `event_key`
   (`haniyeh-assassination-tehran-2024`) rather than being folded into
   either existing war thread, since Iran's direct involvement makes this
   a structurally distinct escalation path (state-on-state, not
   state-on-proxy).
2. **The 2024-08-05 "Black Monday" global selloff** — Wall Street's worst
   day in nearly two years, Nikkei -12% (worst since 1987), yen carry
   trade unwind, ASX's worst two-day decline since the pandemic — was
   given its own dedicated `event_key` (`2024-08-05-black-monday-selloff`)
   distinct from the `us-2024-recession-fear-selloff` key used for the
   preceding week's jobs-data-driven selling, on the reasoning that the
   carry-trade unwind introduced a qualitatively different (technical,
   leverage-driven, cross-asset) transmission mechanism rather than being
   simply "more of the same" recession-fear selling. This is the first
   live validation of the `yen_carry` node, tagged jointly with
   `risk_appetite` across three consecutive days (crash, Tuesday's
   partial recovery, Wednesday's BoJ-driven further recovery) — a clean
   three-act arc that validates the node works well for carry-trade-unwind
   stories specifically, as distinct from generic risk-off moves.
3. **Biden's actual withdrawal aftermath consolidating fully**: Harris
   clinching the nomination, picking Tim Walz, and a poll showing her
   "erasing" Trump's lead all landed in this batch, completing the arc
   that began with the debate collapse in batch #32. `us_elections` usage
   this batch (3 tags) was lower than batch #33's spike (14 tags) —
   expected, since the acute daily-news-cycle phase of the story (VP
   drama, RNC, assassination attempt) had passed and only the Walz pick
   and a poll-movement data point remained genuinely new.

**Confirmed recurring pattern — AI-capex earnings divergence**: Meta's
positive market reception (2024-07-31) contrasted with Microsoft's and
Alphabet's negative-to-mixed reception (2024-07-30, 2024-07-24) for
similar heavy-AI-capex results, echoing the identical Meta-vs-Microsoft/
Alphabet divergence first flagged in batch #27. Two independent
occurrences four months apart is enough to call this a structural
market pattern rather than noise: investors are pricing Meta's AI capex
as more credibly tied to an existing high-margin ad business, while
Microsoft/Alphabet capex is read more skeptically as speculative
cloud/search-defense spending. Worth a permanent note in
`docs/DIGESTION_SPEC.md` that same-quarter AI-capex earnings across
megacap tech should be expected to diverge in market reaction even when
the underlying financials look similar — do not treat opposite-signed
`ai_capex_cycle` tags across companies in the same week as a tagging
error.

**Gap evidence reinforced**: the UK BoE-node gap flagged at the end of
batch #33 recurred twice more this batch (the 2024-07-28 "BoE set to
disappoint hopes of a cut" anticipation piece and the 2024-08-01 actual
first-cut-since-2020 decision), both folded into `europe_growth` as
before. With three UK monetary-policy events now folded into a growth
node across two batches, this has moved from "worth flagging" to
genuinely overdue — recommend drafting a `boe_rate` node spec at the next
available gap-analysis slot, mirroring `fed_rate`/`ecb_policy` but for
the UK, so BoE decisions stop being force-fit onto a node that is
conceptually about output, not policy rate.

**Batch #35 summary (2024-08-08 → 2024-08-21)**: rebuilt ledger now holds
709 event_keys across 417 days. This batch spans 47 events over 14 days
(3.36/day), magnitude mean 0.298 / median 0.30 — the lowest mean of any
batch this session, reflecting a genuinely calmer stretch after the
Haniyeh assassination / Black Monday peak that closed out batch #34: most
of this batch's events are continuations, diplomatic maneuvering, and
data prints rather than fresh shocks. Novelty mix: 19 new (1.0), 11 at
0.7, 17 at 0.5 (no 0.8 tags this batch) — the 0.7 tier at 23% is healthy
and the complete absence of 0.8 is notable; nothing this batch rose to
the "major materialization short of a full new event" level that 0.8 is
reserved for. `geopolitical_tension` hit 38.8% (19 of 49 tags) — the
highest concentration since batch #29's all-time high of 59.4% — driven
by three concurrent live threads (Iran-Israel retaliation countdown,
Ukraine's Kursk incursion, Israel-Hezbollah border escalation) all
running in parallel for the full two weeks without any of them resolving.

**The "Iran retaliation" thread never resolved within this batch** — a
rare and worth-flagging case where a story opened in the prior batch
(Haniyeh assassination, 2024-07-31) stayed live and unresolved through an
entire subsequent batch (14 more days) without a clean ending. The thread
was tracked with novelty 0.5-0.7 across six separate days
(08-08, 08-12, 08-13 x2, 08-17, 08-19 implicitly via the ceasefire
sub-thread) as it oscillated between "Iran may rethink" (de-escalatory)
and "US accelerates deployment" (escalatory) signals. This is a useful
stress-test of the event_key-reuse convention: a single sprawling
geopolitical event_key can legitimately span 3+ weeks of back-and-forth
signal without becoming stale, as long as each reuse genuinely reflects
new information rather than recapping. Recommend flagging at the start
of batch #36 to check whether Iran's retaliation has actually materialized
by then — if it stays unresolved much longer, consider whether the
underlying "attack is imminent" framing needs to be revised as a standing
assumption rather than restated every few days.

**Ukraine's Kursk incursion validated as a genuinely bidirectional
signal**: this batch tracked both Ukraine's continued territorial gains
(Sudzha captured, bridges destroyed, 1,000 sq km claimed) AND Russia's
simultaneous accelerating counter-offensive toward Pokrovsk in Donbas —
correctly tagged as two distinct sub-threads (`ukraine-kursk-incursion-2024`
vs. new key `russia-pokrovsk-advance-2024`) rather than forced onto one
event_key, since they represent opposite momentum on different fronts of
the same war. This is a cleaner resolution of the "one big war, many
sub-threads" problem than earlier batches achieved — worth carrying
forward as the template for handling multi-front conflicts generally.

**Macro data cluster validates several nodes under real stress**: the
2024-08-21 US payroll benchmark revision (-818,000 jobs, one of the
largest revisions in years) was correctly dual-tagged to `us_employment`
and `fed_rate` in the same negative direction (weaker labor market →
more dovish Fed) — a same-direction dual-tag, not the polarity-conflict
pattern, correctly left unsplit. `gold_price` (new live validation,
record high on rate-cut expectations), `usd_strength` (dollar jump on
strong retail sales), and `yen_carry` (three-day arc across the prior
batch's Black Monday event, referenced again this batch's recovery
continuation) all now have multiple real-world validations.

**Fresh gap evidence**: `googl`/Alphabet-specific node absence (flagged
batch #33) recurred implicitly — the 2024-08-06 Google antitrust ruling
and 2024-08-14 breakup-consideration follow-up had to be tagged to
`us_tech_regulation`, which works reasonably for regulatory/legal news but
would not capture an Alphabet earnings or product event the way a
dedicated ticker node would. No new node proposals are being drafted this
batch — per the batch #33 note, digestion effort continues to prioritize
event coverage now that 16 proposals are already logged; the `boe_rate`
gap (now reinforced a third time by the 2024-08-01 BoE cut and 2024-08-18
property-market reaction) remains the single most overdue item for the
next available gap-analysis slot.

**Batch #36 summary (2024-08-22 → 2024-09-04)**: rebuilt ledger now holds
730 event_keys across 431 days. This batch spans 45 events over 14 days
(3.21/day), magnitude mean 0.30 / median 0.30 — squarely in the normal
range. Novelty mix: 21 new (1.0), 10 at 0.7, 2 at 0.8, 12 at 0.5.
`geopolitical_tension` at 36.7% remains elevated but is finally starting
to resolve rather than merely accumulate: the Haniyeh-retaliation thread
opened 2024-07-31 escalated through Israel-Hezbollah's largest exchange
yet (2024-08-25, novelty 0.8) before the batch closed with the story still
technically unresolved — Iran's direct retaliation still had not
materialized by 2024-09-04, now five full weeks after the assassination.
This is now flagged for a second consecutive batch; if it remains
unresolved into batch #37, the standing "attack is imminent" framing used
in every reuse of `haniyeh-assassination-tehran-2024` should be revisited
rather than mechanically restated.

**One empty day (2024-08-31)** — the first day this session with zero
events written, logged deliberately with an empty `events` array rather
than skipped, to keep per-day file coverage complete and make the absence
auditable rather than ambiguous. Recommend this as the standard practice
going forward: an empty array with no entries is a positive statement
("nothing cleared the bar today"), not a gap in coverage.

**`nvda` stress-tested through a full boom-bust-antitrust arc within 8
days**: Nvidia's Q2 beat (08-28, positive) reversed into a slowing-growth/
production-delay selloff (08-29, negative, 0.7), then compounded into the
single largest one-day market-cap loss by any US company in history
(09-04, on antitrust-investigation reports) — three tags, three different
causal mechanisms (fundamentals, execution concerns, regulatory risk), all
correctly captured as distinct events rather than smoothed into one
storyline. This is good evidence the `nvda` node and the `ai_capex_cycle`
node both handle rapid sentiment reversal well.

**Second live case of the "beat-then-selloff" divergence pattern**
(first flagged for Alphabet in batch #34's summary): both Nvidia (08-28→
08-29) and Trump Media (09-04, non-earnings but same mechanic — extreme
gains fully round-tripping) demonstrate that a single asset's polarity can
legitimately flip sign within days without any tagging error. Recommend
finally converting this from a recurring batch-summary footnote into an
actual permanent rule in `docs/DIGESTION_SPEC.md`: *same-asset polarity
reversals across adjacent days are expected market behavior, not evidence
of a mistake — do not retroactively smooth them.*

**European auto/EV crisis validated as a multi-week, multi-company
thread**: Ford's SUV cancellation (batch #35, 07-21) → Volkswagen's
unprecedented plant-closure consideration (09-02) → VW's CFO warning of
"a year, maybe two to turn around" alongside Volvo's abandonment of its
2030 all-EV target (09-04) — three distinct companies across two
batches, all tagged consistently to `ev_supply_chain` with negative
polarity, tracing what is clearly a structural rather than one-off
story. This is a good template for how a slow-moving industrial story
should accumulate across event_keys (one per company/announcement) while
staying legible as a single sectoral narrative through the shared node.

**Fresh gap evidence**: the 2024-09-01 German state elections (AfD first
place in Thuringia, second in Saxony) is exactly the kind of event the
still-unspec'd `eurozone_political_risk`-adjacent political-risk gap would
capture, but was correctly left untagged in the live event stream since no
such node exists yet — noted here as further evidence rather than
force-fit onto `europe_growth`. The `boe_rate` gap did not recur this
batch (no UK monetary-policy-specific events fell in this window), but
remains the top-priority open item from the last two batch summaries.

**Batch #37 summary (2024-09-05 → 2024-09-18)**: rebuilt ledger now holds
742 event_keys across 445 days. This batch spans 40 events over 14 days
(2.86/day, the lightest events/day of any batch this session) but
magnitude mean 0.315 / median 0.30 stayed in the normal range — fewer but
not smaller events. Novelty mix: 16 new (1.0), 6 at 0.7, 6 at 0.8, 12 at
0.5 — the 0.8 tier (6 of 40, 15%) is unusually rich this batch, reflecting
several genuine phase-changes-within-threads (Hezbollah pager attack,
walkie-talkie second wave, Putin's NATO-war threat, Venezuela's González
fleeing to exile) rather than routine continuations.

**The Haniyeh-retaliation thread finally showed a resolution signal**:
after two full batches (28 days) of oscillating escalation/de-escalation
signals, Iran's president stated on 2024-09-16 that Iran had shown
"restraint" — the first explicit acknowledgment from Tehran itself that
the long-threatened direct strike is not imminent. Tagged at novelty 0.8
as the clearest de-escalation signal this thread has produced. Per the
batch #36 recommendation, this closes out the "check if resolved" flag —
future digestion should treat the acute assassination-retaliation phase
as over and downgrade `haniyeh-assassination-tehran-2024` reuses to
routine novelty unless a genuinely new strike materializes.

**A new, larger regional escalation opened to replace it**: the
2024-09-17/18 Hezbollah pager and walkie-talkie attacks — an
unprecedented supply-chain sabotage operation killing 32 and injuring
over 3,000 across two days — followed immediately by Israel expanding its
official war goals to include the Lebanon border corridor. This is
arguably the single most audacious tactical event tagged to
`israel-lebanon-hezbollah-tension-2024` all session, and closes the batch
with the Israel-Hezbollah front looking more likely to escalate to full
war than at any prior point, a genuine escalation in what to watch
entering batch #38.

**Two Fed-rate thread milestones landed in one batch**: Powell's Jackson
Hole "time has come" signal (batch #35) matured through the Jan-Werner
August jobs/inflation data into the actual first rate cut in four years
on 2024-09-18 — the clean terminal event of the `fed-2024-rate-cut-signal`
key that has been reused since 2024-07-16. This is a good illustration of
a long-running event_key arc resolving cleanly: signal → data confirmation
→ actual policy action, each correctly tagged with rising novelty as the
outcome became more concrete (0.5 → 0.7 → 1.0 at the terminal cut).

**`nvda`/`aapl` continue validating under regulatory and legal stress**:
Apple absorbed both the EU's final €13bn tax ruling and its iPhone 16/
Apple Intelligence launch in the same batch (opposite-signed, correctly
tagged as separate events) — the same "same-asset, different-direction,
different-day" pattern flagged as a permanent rule candidate in batch
#36's summary.

**No new node proposals this batch** — consistent with the standing
priority (established batch #33) of favoring event-coverage depth over
further gap-analysis drafting unless something genuinely new surfaces.
The `boe_rate` gap did not recur (no dedicated BoE-only prints fell in
this window beyond the routine UK inflation reads already tagged to
`europe_growth`), so it remains queued rather than newly reinforced.

**Batch #38 summary (2024-09-19 → 2024-10-02)**: rebuilt ledger now holds
757 event_keys across 459 days. This batch spans 39 events over 14 days
(2.79/day, another light-but-dense batch) with magnitude mean 0.365 /
median 0.35 — the highest mean of any batch this session, driven by an
extraordinary run of top-tier geopolitical shocks packed into two weeks.
Novelty mix: 19 new (1.0), 7 at 0.8, 7 at 0.7, 6 at 0.5 — the 0.8 tier at
18% and the near-total absence of routine 0.5 recaps (just 15%) both
confirm this was one of the highest-intensity stretches of the entire
digestion so far. `geopolitical_tension` hit 45.2%, the second-highest
concentration this session (behind only batch #29's 59.4% all-time high).

**This batch contains what may be the single most consequential
resolution of any open thread all session**: Iran's direct missile
attack on Israel (2024-10-01, ~180 ballistic missiles) finally resolved
the `haniyeh-assassination-tehran-2024` thread that had oscillated
between escalation and de-escalation signals across three full batches
(37 days) since 2024-07-31. The thread's final arc is a good case study
in the reuse-with-rising-novelty pattern working exactly as designed:
07-31 assassination (1.0) → weeks of oscillating 0.5-0.8 signals → 09-16
Iran "restraint" statement (0.8, apparent de-escalation) → 09-28 Nasrallah
killing reopens it → 10-01 actual missile attack (1.0, terminal
resolution). The lesson for future digestion: even a thread that seems to
have quieted down (as flagged "closed" in batch #37's summary) can
reignite without warning — the "check if resolved" discipline should
continue past an apparent resolution, not stop at it.

**Israel-Hezbollah escalated further and faster than any prior
projection**: from the pager/walkie-talkie attacks (batch #37 close) to
Nasrallah's assassination (09-27/28) to a ground invasion of Lebanon
(09-30) to direct Israeli-Hezbollah ground combat casualties (10-02) — a
five-stage escalation ladder climbed in under two weeks. Each stage was
correctly tagged as its own event under the shared
`israel-lebanon-hezbollah-tension-2024` key with rising or sustained-high
novelty (several 0.7-0.8 tags), rather than being compressed into fewer,
vaguer entries — this is the batch that most stress-tested the "how much
detail is too much for one fast-moving thread" question, and the answer
that emerged is: track every distinct escalation rung, since each one
carries genuinely different portfolio-risk information (air campaign →
targeted assassination → ground invasion → sustained ground combat are
different risk regimes, not degrees of the same one).

**First confirmed instance of a "same causal event, opposite node
convention" split driven by market mechanics rather than a tagging
error**: the 2024-09-26 Saudi Arabia price-target story split into
`oil_price` (negative — falling price) and `oil_supply` (positive — more
supply coming) events. Unlike the four prior dual-tag bug instances (all
corrections of an actual mistake), this is a case where the split was
correct *by design* from the start — the two node conventions were never
in tension, they simply measure different quantities that move in
naturally opposite directions when supply increases. Worth codifying in
`docs/DIGESTION_SPEC.md`: the mandatory split-check applies regardless of
*why* two nodes disagree in sign — mechanical/causal consistency between
the two real-world quantities does not exempt the tagger from splitting,
since the ledger format still only carries one polarity value per event
object.

**China stimulus thread validated across three distinct escalating
announcements** in one batch (rate cuts 09-24 → property-specific
measures 09-26 → stocks' best week since 2008 09-27), all correctly
sharing one event_key with rising novelty as the stimulus's real-economy
and market impact became clearer — a clean template for tracking a
policy-response arc.

**No new node proposals this batch**, consistent with the standing
priority on event-coverage depth. The `boe_rate` gap remains queued (no
BoE-specific events fell in this window). Given the sheer geopolitical
density of this batch, gap-analysis energy was entirely absorbed by
event coverage — appropriate given the standing instruction to prioritize
coverage over further proposal-drafting.

**Batch #39 summary (2024-10-03 → 2024-10-16)**: rebuilt ledger now holds
774 event_keys across 473 days. This batch spans 34 events over 14 days
(2.43/day, the lightest of the session) with magnitude mean 0.329 /
median 0.35 — still comfortably in range despite fewer events, meaning
this batch was selective rather than quiet. Novelty mix: 17 new (1.0), 3
at 0.8, 6 at 0.7, 8 at 0.5. `geopolitical_tension` eased to 33.3% (down
from 45.2% last batch) as `europe_growth` rose to second place at 17.9%,
reflecting a genuine pivot this batch toward UK/eurozone macro data
(BoE signals, gilt yields, GDP prints, the investment summit, the
below-target inflation surprise) alongside continued but slightly less
intense Middle East escalation.

**Israel's actual retaliation against Iran did not materialize within
this batch** — the thread opened 2024-10-01 (Iran's missile attack) and
tracked through oil-price/oil-supply risk discussion (10-03, 10-04),
Ehud Barak's "massive attack on oil facilities" comments, and finally
Israel's 10-16 conciliatory response to US pressure ("will address
concerns") — but no actual Israeli strike on Iran landed by batch close.
This is now the second time in the session a major anticipated
retaliation has stayed pending across a full batch boundary (the first
being the original Haniyeh-retaliation wait in batches #34-36) — flagged
for batch #40 to check resolution explicitly, per standing discipline.

**Oil price/supply split validated a second time under different
circumstances**: batch #38 established the Saudi price-target
oil_price/oil_supply split as a template; this batch reused it directly
for the Iran-strike-risk scenario (10-03/10-04) and then the mechanism
reversed cleanly when Middle East fears eased and Chinese demand
weakness took over as the dominant driver, pushing oil_price down again
by 10-15 — a full round-trip (fear-driven spike → data-driven collapse)
captured across two distinct event_keys within two weeks, a clean
validation that `oil_price` handles both geopolitical and macro demand
shocks without confusion.

**Israel-Hezbollah/Lebanon threads kept escalating but at a slightly
slower cadence than batch #38's five-stage ladder** — deadliest central
Beirut strike since the war began (10-11), a Hezbollah drone attack
killing 4 IDF soldiers alongside a rare direct US THAAD deployment
(10-13), and a strike killing a Lebanese mayor mid-aid-coordination
(10-16, noted but not separately event-tagged this cycle) — still a
serious, unresolved front but with novelty tags mostly 0.5-0.7 rather
than the 0.8s that dominated the previous batch, suggesting the market
has begun partially pricing in the "new normal" of this conflict's
intensity.

**Two new nodes validated for the first time this session**:
`global_luxury` (LVMH's China-driven sales miss, 10-16) and `uranium_price`
(paired with `ai_datacenter` for Google's nuclear-for-AI deal, 10-15) —
both clean, unambiguous fits with no dual-tag conflicts.

**No new node proposals drafted this batch**, consistent with the
standing event-coverage priority. The `boe_rate` gap continues to be
reinforced rather than resolved — this batch alone folded five distinct
UK monetary-adjacent events (Bailey's "activist cuts" hint, gilt yield
rise, wage-growth cooling, and the inflation-below-target surprise) into
`europe_growth`, now the single most evidence-backed gap in the entire
proposal backlog. If a future batch has bandwidth to draft one full node
spec, this should be first in line.

**Batch #40 summary (2024-10-17 → 2024-10-30)**: rebuilt ledger now holds
791 event_keys across 487 days. This batch spans 57 events over 14 days
(4.07/day, back up sharply from batch #39's 2.43 — this was an
exceptionally newsy fortnight) with magnitude mean 0.296 / median 0.3,
right in the established range. Novelty mix: 16 new (1.0), 4 at 0.8, 9 at
0.7, 6 at 0.6, 14 at 0.5, 4 at 0.4, 4 at 0.3 — a healthy skew toward
genuine phase-changes given how many long-open threads resolved this
batch. `geopolitical_tension` jumped back up to 45.8% of all node tags
(from 33.3% last batch), `europe_growth` held strong second at 22.0%
(UK fiscal-rules saga + actual budget + gilt yields + Eurozone/Germany
GDP + VW's profit collapse), with `gold_price`, `global_growth`, and
`oil_price` tied at 5.1% each, `japan_equities` at 3.4% (a brand-new
node validated this batch), and `ecb_policy`/`china_growth` at 1.7% each.

**Israel's retaliation against Iran finally materialized (2024-10-26),
resolving the session's longest-open escalation thread.** The
`haniyeh-assassination-tehran-2024` event_key had tracked this
retaliation-timing question since 2024-07-31 — through Nasrallah's
killing, Iran's 10-01 missile attack, the leaked-plans story (10-20),
and Gallant's repeated warnings — before Israel struck Iranian military,
missile, and drone-manufacturing sites while deliberately sparing oil
and nuclear infrastructure. Oil prices fell 5% two days later (10-28) as
the risk premium unwound, a clean confirmation of the market's read that
avoiding energy targets was the market-relevant signal. This is now the
**third** major anticipated-retaliation thread this session to resolve
only after spanning multiple batch boundaries (following the original
Haniyeh-wait and the Israel-Iran gap flagged at the close of batch #39),
reinforcing the standing lesson that these multi-week retaliation
threads should be tracked patiently rather than assumed resolved early.
**A new sub-thread immediately reopened**: Iran's foreign minister says
Tehran will respond "appropriately" (10-27) and hardliners call for
reprisal even as Iran's military signals it may prioritize a Gaza/
Lebanon ceasefire instead (10-26) — this is now the open question for
batch #41 to track at its open.

**Two new nodes validated for the first time this session**:
`japan_equities` (Japan's ruling LDP-coalition losing its parliamentary
majority for the first time in 15 years, 10-27/10-28 — a clean political-
risk fit) and a confirmed real-world stress test of `btc` (bitcoin
rallying alongside gold's record high on election-uncertainty/rate-cut
demand, 10-29) — the first time this session `btc` was used in a genuine
market-reaction context rather than left dormant. `msft`, `tsla`, and
`intc` were each also validated individually this batch (Tesla's Q3
earnings beat, Microsoft's Azure/AI-driven cloud growth, Intel's EU
antitrust-fine reversal) — single-company earnings/legal-event tagging
continues to work cleanly with no dual-tag conflicts.

**A `global_growth` overload risk surfaced this batch and should be
flagged for `DIGESTION_SPEC.md`**: the 10-30 US Q3 GDP print (+2.8%,
below the 3.1% consensus) had no clean US-economy-specific node to land
on, so it was tagged `global_growth` for lack of a better fit — the same
node also used for the IMF's global outlook and the "anxious times"
warning. This conflates US-domestic data with worldwide aggregates under
one node, which will matter more once the graph needs to distinguish
"US growth surprised down" from "global growth is slowing" as distinct
tradable signals. A dedicated `us_growth` node (parallel to
`europe_growth`, `china_growth`, `japan_equities`) is recommended — this
batch alone would have used it for the US GDP print and arguably the
US-manufacturing/jobs-report event_keys from earlier in the session that
were folded into other nodes for the same reason.

**Several other node gaps were freshly evidenced this batch and left
untagged, per the no-forced-tagging rule**: Meta's Q3 earnings beat (but
missed on daily-active-users) and Reddit's first profit as a public
company (AI-licensing deals with Google/OpenAI) both had no node to land
on (`meta`, `rddt` don't exist); BP's weakest quarterly profit in ~4
years and HSBC's $3bn buyback likewise had no ticker node (`bp`, `hsbc`
don't exist); the UK car-finance mis-selling ruling (Lloyds "assessing"
a potential multi-billion-pound hit via Black Horse, Santander delaying
results, Close Brothers exposure) reinforces the standing `uk_banks` gap
with its single largest evidentiary data point yet — this was a
landmark court ruling with sector-wide, billions-of-pounds implications
and literally nothing in the graph could carry it. **Spain's worst
floods in three decades (95+ confirmed dead, 10-30) also went untagged**
for lack of any natural-disaster/climate-catastrophe node — this is now
the third major weather disaster this session left untagged (after
Hurricanes Helene and Milton), suggesting a `climate_disaster` node
(insurance-loss and agricultural-supply-chain relevant) may deserve
consideration alongside `boe_rate` and `uk_banks` as a backlog item, if
a future batch has bandwidth to draft full node proposals. `boe_rate`
itself was reinforced yet again this batch (Goldman's 2.75%-by-autumn
call, the shop-price disinflation data, the mortgage-approvals rise) —
still the single most evidence-backed unaddressed gap in the entire
proposal backlog.

**The UK fiscal-rules saga played out as a complete multi-stage arc
within this single batch**, doubling as a clean demonstration of the
same-node-opposite-direction-within-days pattern: announcement (10-23,
+0.3) → gilt-yield selloff on the announcement (10-24, -0.3) → IMF
backing partially offsetting the market reaction (10-25, +0.25) → UK
consumer confidence despondency ahead of the budget (10-25, -0.25) →
the actual budget delivery (10-30, +0.15, deliberately muted since the
key details had already leaked). No dual-tag conflicts arose since each
stage was tagged `europe_growth` alone in its own event object — this is
the same pattern validated for Alphabet/Nvidia/Trump Media earlier in
the session, now confirmed at the macro-policy level too.

**Batch #41 summary (2024-10-31 → 2024-11-13)**: rebuilt ledger now holds
816 event_keys across 501 days. This batch spans 52 events over 14 days
(3.71/day) with magnitude mean 0.297 / median 0.3, right on the
established baseline despite covering the single highest-magnitude
event of the entire session (the US election itself, magnitude 0.7).
Novelty mix: 18 new (1.0), 1 at 0.8, 4 at 0.7, 15 at 0.6, 6 at 0.5, 8 at
0.4 — the 0.6 spike reflects how many distinct threads had a genuine,
non-recap development during election week. `geopolitical_tension`
held at 44.4% of all node tags, `europe_growth` second at 20.4%
(UK budget aftermath, gilt yields, jobs data, German coalition collapse
all landing here), with `fed_rate` at 7.4%, `btc` at 5.6% (bitcoin's
best-validated stretch of the session — five separate events across the
batch), `us_inflation` and `dollar` at 3.7% each, `renewables` at 3.7%,
and `aapl`/`global_growth`/`us_elections` at 1.9% each.

**The 2024 US election was digested as a deliberately granular, multi-
event arc rather than a single compressed entry, per the task brief's
explicit instruction for this batch.** The arc: pre-election dollar
weakening as polls shifted from Trump (11-04, `dollar` -0.35) → Trump's
decisive win itself, tagged to the newly-exercised `us_elections` node
at maximum polarity/magnitude (11-06, +1.0/0.7 — the single largest
event this session) → same-day "Trump trade" market reaction split
cleanly across five separate single-node events (`dollar` +0.45, `btc`
+0.5, `tsla` +0.5, `renewables` -0.4, `europe_growth` -0.35 for German
carmakers' tariff-fear selloff) → the Fed's rate cut the very next day,
with Powell publicly refusing to resign under Trump pressure (11-07)
→ a full week of cabinet-appointment signals read as forward-looking
geopolitical-risk information (Rubio/Waltz as China hawks 11-12, RFK
Jr, Hegseth) → bitcoin's continued climb through $87k (11-11) and
$93k (11-13) as the clearest multi-day node validation of the batch.
This is the clearest demonstration yet of the "split by node, not by
story" discipline paying off: a single causal event (Trump's win)
generated six cleanly separable, non-conflicting event objects on
11-06 alone, each carrying its own polarity/magnitude appropriate to
that specific asset's reaction — no dual-tag conflicts arose because
each node got its own object rather than being crammed into one.

**`us_elections` was finally exercised for the first time this session
at full strength** — previously only implied by proxy stories
(`harris-2024-vp-pick-walz`, debate coverage, etc.), this batch used it
directly for the terminal election-result event, validating the
polarity convention established early in the session ("+ = shifts
probability toward Trump / away from Democratic status quo") at its
logical extreme: a Trump win is +1.0 on this node by definition.

**A second G7 government collapsed this batch, one day after the
Fed/BoE both cut rates**: Germany's coalition fell apart on 11-07 when
Scholz sacked his finance minister, with a snap election now confirmed
for 2025-02-23 (11-13). Tagged `europe_growth` for lack of a dedicated
`germany_politics` or `de_growth` node — reinforcing, alongside the
`us_growth` gap flagged in batch #40, that the graph currently has no
way to distinguish a German-specific political shock from a broader
"Europe" signal. This is now the second major single-country political
shock (after Japan's LDP loss in batch #40) forced into a
geography-blended node this session.

**Two new nodes exercised for the first time this session**:
`us_elections` (above) and `us_inflation` (US October CPI, 11-13,
distinct from the `fed_rate`/`global_growth` proxies used for earlier
US macro prints) — both clean fits validated under real event pressure.
`aapl` was also independently validated (Q4 earnings, 10-31), joining
`msft`/`tsla`/`intc` as single-company tickers proven to work smoothly
this session with zero dual-tag conflicts across all four.

**The `us_growth` gap flagged at the close of batch #40 recurred
immediately**: the 11-01 shock US jobs report (only 12,000 added,
partly Boeing-strike/hurricane-distorted) again had no dedicated node
and was folded into `global_growth` alongside `fed_rate` — this is now
the second batch running this exact gap has forced a workaround,
making it the second-most evidence-backed unaddressed gap after
`boe_rate`. Additionally, `meta`, `rddt`, `bp`, `hsbc`, `azn`, and
ticker nodes for Amazon/Shell/Lloyds/NatWest continue to have zero
representation — this batch alone left Amazon's cloud-beat earnings,
AstraZeneca's China-linked share slide, and Lloyds' mounting car-
finance exposure untagged. No new node proposals were drafted this
batch (consistent with the standing event-coverage priority) but the
backlog is now, in priority order: `boe_rate` (most evidence, flagged
5+ times), `us_growth` (flagged twice), `uk_banks` (car-finance
mis-selling scandal, flagged 3+ times), `climate_disaster` (Spain
floods, Helene, Milton — flagged twice).

**Escalation-thread status at batch close, for batch #42 to pick up**:
(1) Israel-Iran retaliation cycle — Israel's 10-26 strike resolved the
original Haniyeh thread, but Iran's "appropriate response" (stated
10-27, reiterated via Khamenei's fresh threat 11-04) remains
unmaterialized as of 11-13; (2) North Korea-Russia alliance has now
progressed from troop deployment → first combat contact (11-06) →
formal mutual-defense-pact ratification (11-12) — a complete escalation
ladder, but Russia's still-expanding southern offensive (Zaporizhzhia,
flagged 11-13) is a fresh open thread; (3) Trump's actual policy moves
(tariffs, Ukraine funding posture, Israel policy) remain pure signal/
speculation as of inauguration is still ~2 months out — batch #42
should watch for the transition from "expected policy" event framing to
"actual policy" event framing once concrete announcements land.

**Batch #42 summary (2024-11-14 → 2024-11-27)**: rebuilt ledger now holds
846 event_keys across 515 days. This batch spans 54 events over 14 days
(3.86/day) with magnitude mean 0.298 / median 0.3, again right on the
established baseline. Novelty mix: 18 new (1.0), 1 at 0.8, 5 at 0.7, 17
at 0.6, 12 at 0.5, 1 at 0.4 — an unusually high concentration in the
0.5-0.6 band, reflecting a batch dominated by fast-moving escalation
sequences where almost nothing was a pure recap. `geopolitical_tension`
surged to 55.6% of all node tags (up from 44.4% last batch) — the
highest concentration this node has reached all session — while
`europe_growth` held steady at 20.4%. `dollar` rose to 7.4% (Bessent
Treasury pick, euro-parity risk, election-eve moves), with `btc`,
`natural_gas`, `aapl`, `pharma`, `nvda`, `renewables`, and `global_growth`
each in the 1.9-3.7% range — the widest single-batch spread of distinct
nodes touched this session, six of them for the first or second time.

**This was the most geopolitically dense two weeks of the entire
session**, driven by a genuine escalation spiral that then reversed
just as sharply. The core arc: Biden lifts the ban on Ukraine using
US long-range missiles (11-17) → Ukraine fires ATACMS into Russia for
the first time (11-19) → Putin updates Russia's nuclear doctrine,
lowering the threshold for nuclear weapons use, in direct response
(11-19, the batch's highest-magnitude single event at 0.45) → Ukraine
fires UK Storm Shadow missiles too (11-20) → Russia fires an entirely
new "experimental" ballistic missile (the Oreshnik) at Dnipro, which
Putin says can't be intercepted and will enter serial production
(11-21) → France adds itself as a third nation willing to let Ukraine
use its long-range missiles (11-24) → Russia threatens retaliation
after two more Kursk-region ATACMS strikes (11-26). This ladder was
then immediately followed by a genuine, unrelated de-escalation: the
Israel-Hezbollah ceasefire (announced 11-26, in force 11-27), ending a
conflict thread that had run since September — and a clarifying detail
that the Oreshnik missile itself carried no explosives (11-27),
tempering the strike's actual military severity even though its
signaling value stands. **This is the clearest evidence yet that the
graph's escalation/de-escalation tagging discipline handles compressed,
whiplash-fast sequences correctly** — each stage got its own event
object with an appropriately scaled polarity/magnitude, and the
Hezbollah ceasefire's arrival mid-Ukraine-escalation did not get
smoothed into a single "geopolitical mood" score.

**Six nodes were validated for the first time or reinforced under
genuinely new circumstances this batch**: `natural_gas` (European gas
prices hit a one-year high on a Gazprom-OMV legal dispute, 11-14),
`pharma` (RFK Jr's health-secretary nomination hitting Moderna/
AstraZeneca/GSK shares, 11-15), `nvda` (Nvidia's Q3 earnings beat,
11-20), `aapl` (a UK antitrust lawsuit, 11-14 — `aapl`'s second
validation this session after the 10-31 earnings), `dollar` (five
separate events, its most active stretch all session), and `china_growth`
(tagged independently from `global_growth` for the first time for a
US-China-specific tariff story, 11-26) — this last one directly
addresses part of the `us_growth`/geography-conflation gap flagged in
batch #40 and #41: when a China-specific angle exists, `china_growth`
now demonstrably can carry it separately from the broader US/global
tariff story.

**The Trump-administration transition produced this session's first
genuinely forward-looking "expected policy" event category**, distinct
from actual policy: cabinet-pick-as-signal events (Bessent for
Treasury, 11-23; Rubio/Waltz as China hawks, batch #41) sit alongside
the first real announced-not-yet-enacted policy shock (the 25% Mexico/
Canada and deeper China tariff threat, 11-26, tagged `global_growth`
and separately `china_growth`) — flagged at the close of batch #41 as
the thing to watch for, and it arrived on schedule. Future batches
should continue distinguishing "Trump said/nominated/threatened X"
(lower confidence, appropriately dampened magnitude) from "Trump's
administration actually did X" (full confidence) once inauguration
(2025-01-20) passes.

**A same-node self-correction is worth flagging explicitly**: the
11-23 Bessent-nomination event was initially tagged `dollar` +0.3 on an
anticipatory "market relief" read; the 11-25 follow-up, once the actual
market reaction landed (Wall Street record high, bonds rally, dollar
*dips*), corrected the direction to -0.3. This is not a new category of
error — it's the established "beat-then-reversal" pattern applied to a
policy-announcement event rather than an earnings event — but it's the
first time this session the reversal was driven by the digester's own
initial miscalibration (assuming a market direction before data
confirmed it) rather than a genuine subsequent market move. Recommend
`DIGESTION_SPEC.md` add a note: for personnel/policy-announcement
events without same-day market data, prefer a lower-confidence,
smaller-magnitude tag and wait for the next day's actual price action
rather than assuming a directional read.

**New node gaps evidenced this batch, none tagged per the no-forced-
tagging rule**: Russia's rouble collapsing to its weakest level since
the war's early weeks after Gazprombank sanctions (11-27) had no
`rouble`/`russia_economy` node to land on — a notable gap given the
session has now tracked Russia-linked geopolitical events dozens of
times without ever being able to tag Russia's own currency/economy
directly. Amazon, Shell, Meta, Reddit, and UK-bank tickers remain
untagged as previously noted. The backlog, in priority order, is
unchanged in composition but the rouble gap is a new, distinct entry:
`boe_rate` (most evidence), `us_growth`/`china_growth` split (partially
addressed this batch — see above), `uk_banks`, `climate_disaster`,
`russia_economy`/`rouble` (new).

**Batch #43 summary (2024-11-28 → 2024-12-11)**: rebuilt ledger now holds
863 event_keys across 529 days. This batch spans 50 events over 14 days
(3.57/day) with magnitude mean 0.275 / median 0.25 — the lowest of the
session so far, below the ~0.3 baseline held across the prior six
batches. This is not a sign of a quiet batch (it was arguably the
opposite — Syria's regime collapsed, France's government fell, South
Korea had a martial-law crisis) but a sign that a larger share of events
this batch were continuations/color on already-open threads (novelty
0.5-0.7 dominant, only 9 of 50 at full 1.0) rather than fresh
standalone stories, which correctly earned lower magnitude under the
established convention. Novelty mix: 9 new (1.0), 1 at 0.9, 2 at 0.8, 9
at 0.7, 14 at 0.6, 12 at 0.5, 3 at 0.4. `geopolitical_tension` rose
again to 52.0% of all tags, `europe_growth` to 24.0% (its highest
share this session, driven by the France/Germany political-fiscal
crises), `global_growth` at 8.0%, with `dollar`, `tsla`, `china_growth`,
`japan_equities`, `btc`, `oil_price`, and `gold_price` each around 2%.

**Two country-collapse events defined this batch, both textbook
"terminal resolution of a fast-building thread" cases**: Syria's Assad
regime fell in an 11-day rebel offensive (Aleppo 11-29 → Hama 12-05 →
Damascus 12-08), ending 50+ years of dynastic rule and triggering
immediate multi-power intervention (Israel's 350+ strikes and Golan
Heights land-grab, Turkey bombing Kurdish targets, Russia's Syria
foothold collapsing, Iran's "axis of resistance" exposed) — the
`syria-2024-aleppo-rebel-offensive` key now carries nine events across
the batch, the single most active thread. Separately, France's Barnier
government fell to a no-confidence vote in record time (first in 60+
years, 12-05), tagged `europe_growth` at high magnitude (0.4) given its
direct fiscal-policy implications. Both cases validate that fast-moving
multi-stage collapses can be tracked as a coherent event_key without
needing a dedicated "regime change" node — `geopolitical_tension` and
`europe_growth` respectively absorbed the full arc cleanly.

**The single largest node gap of the entire session surfaced this
batch and was left deliberately untagged**: South Korea's president
declared martial law, reversed it six hours later, survived one
impeachment vote (ruling-party boycott), then faced a second attempt,
a travel ban, and a police raid on his office — all while the won
crashed to a two-year low. This is arguably the highest-magnitude
domestic political shock of the whole session with zero node
representation (no `south_korea`, `krw`, or equivalent exists in
`data/knowledge_graph.json`). Unlike `geopolitical_tension` (reserved
for interstate conflict) or `europe_growth`/`china_growth`/
`japan_equities` (geography-specific growth proxies), there is no
"domestic political-shock" node for a G20 economy outside the ones
already covered — this should be considered alongside `us_growth` and
`germany_politics`(flagged batches #40-42) as evidence that the graph
currently has no way to represent "a major non-US, non-China, non-EU
economy just had a shock" as a first-class signal. Recommend a
`south_korea` or generic `asia_pacific_growth`-style node be evaluated
alongside the `boe_rate` backlog item.

**A `rouble`/`russia_economy` node gap (flagged in batch #42) recurred
identically**: sanctions forcing Putin to scrap the Gazprombank
monopoly, and Russia's rouble weakness, both went untagged again this
batch for the same reason — no node exists.

**Two nodes were validated under fresh circumstances**: `tsla` for a
second, unrelated event type (Musk's Tesla pay package rejected again
by a Delaware judge, 12-02 — a corporate-governance/legal story,
distinct from its earlier earnings and "Trump trade" validations) and
`japan_equities` for a cross-border M&A-block story (Trump blocking
Nippon Steel's bid for US Steel, 12-03) rather than its prior political-
risk use case — both clean fits, reinforcing that single-asset nodes
generalize well across event *types*, not just the story that first
validated them.

**Batch #44 summary (2024-12-12 → 2024-12-25)**: rebuilt ledger now holds
877 event_keys across 543 days. This batch spans 46 events over 14 days
(3.29/day, the lowest of the session) with magnitude mean 0.266 /
median 0.25 — continuing the decline from batch #43 (0.275). Novelty
mix: 7 new (1.0), 7 at 0.8, 7 at 0.7, 11 at 0.6, 13 at 0.5, 1 at 0.4.
`geopolitical_tension` reached 60.9% of all node tags — the highest
concentration this node has hit all session — with `europe_growth` at
21.7%, `global_growth` at 8.7%, and `japan_equities`/`china_growth`/
`fed_rate` each in the low single digits. The declining magnitude/
events-per-day trend across batches #42→#43→#44 reflects a holiday-
period mix: fewer brand-new standalone stories, more continuations and
color on an unusually large number of already-open threads (Syria's
post-Assad carve-up, the Ukraine long-range-missile/Oreshnik/Kirillov
sequence, France's government crisis, multiple Trump-transition
threads) rather than a genuinely quiet fortnight.

**South Korea's presidential impeachment actually passed this batch
(2024-12-14)** — the martial-law crisis flagged as the session's
largest node gap in batch #43 reached its legislative climax (200,000
protesters outside parliament, Yoon suspended pending constitutional
court review) and was, consistent with that batch's finding, left
untagged for lack of any `south_korea`/`krw`-equivalent node. This is
now the second consecutive batch this specific gap has forced a
non-tag on a genuinely major event; it should be considered a firm
candidate for the next node-proposal drafting session, alongside
`boe_rate`.

**Trump's expansionist territorial rhetoric emerged as a distinct new
pattern this batch**, worth watching as a category through the
transition: threatening to "take back" the Panama Canal over fees and
reviving the suggestion the US should own Greenland (both 12-23),
following the tariff threats against Mexico/Canada/China/Brics from
batches #42-43. Tagged `geopolitical_tension` for lack of a better fit,
but flagged with a wide confidence band (manipulation_likelihood 0.2)
since this is rhetoric rather than policy — the same "expected policy"
vs "actual policy" distinction flagged in batch #43 applies here with
extra force given how far outside normal diplomatic practice these
claims sit. Batch #45 should watch whether any of this hardens into
concrete action once inauguration (2025-01-20) actually arrives.

**The Fed's December decision was a clean "hawkish cut" case, useful
precedent for future decisions of this shape**: markets had fully priced
the quarter-point cut itself, so the entire negative market reaction
(Wall Street's sharp fall, 12-18) came from the forward guidance
(fewer 2025 cuts than hoped) rather than the decision — tagged
`fed_rate` positive/hawkish direction despite the cut itself being a
dovish action in isolation, since the *net* signal to markets was
hawkish. This is a useful template: when a central bank both cuts and
guides hawkish in the same event, tag the net directional market
surprise, not the mechanical action.

**A second G7-adjacent economy's political crisis (Germany's snap
election, France's new PM under Bayrou, 12-23) sits alongside two new
node-worthy escalation threads**: Ukraine's SBU assassination of
General Kirillov in Moscow (12-17, arguably the war's most audacious
covert operation to date) and Trump's incoming administration
absorbing Musk as a de facto co-negotiator in the US government
shutdown drama (12-18 to 12-21) — the latter a preview, flagged
explicitly in the reporting itself, of the Musk-Trump governing
dynamic to expect after inauguration.

**Batch #45 summary (2024-12-26 → 2025-01-08)**: rebuilt ledger now holds
898 event_keys across 557 days. This batch spans 47 events over 14 days
(3.36/day) with magnitude mean 0.262 / median 0.25. This is the fourth
consecutive batch of declining magnitude mean (batches #42-45: 0.298 →
0.275 → 0.266 → 0.262) — flagged here explicitly as a trend worth a
deliberate check rather than letting it continue unexamined. It does
not appear to reflect genuinely quieter news (this batch alone covered
a G7 PM's resignation, a market-moving gilt crisis, Trump's territorial-
threat escalation, and the LA wildfires' opening days) so much as a
growing share of continuation/color events on long-running threads
(Syria aftermath, Ukraine, tariffs) earning appropriately dampened
magnitude under the established convention, plus a holiday-period mix
of lower-tempo trading days. Recommend the next batch explicitly
sense-check whether this is correct calibration or a drift toward
under-weighting — if events/day and magnitude both keep falling next
batch without an obvious news-volume explanation, that would suggest a
scoring problem rather than a real signal. Novelty mix: 9 new (1.0), 7
at 0.8, 9 at 0.7, 15 at 0.6, 6 at 0.5, 1 at 0.4. `geopolitical_tension`
eased slightly to 46.8% of tags (from 60.9%), with node diversity
notably higher than recent batches: `europe_growth` 12.8%,
`natural_gas` 8.5% (a new high for this node, validated three times
this batch alone), `china_growth`/`japan_equities`/`global_growth` each
6.4%, `tsla` 4.3%.

**`natural_gas` had its best-validated stretch this session**: European
gas prices spiking on the Gazprom-Moldova halt (12-28), the formal end
of the Russia-Ukraine transit deal (12-31/1-1), and the resulting
14-month-high wholesale price (1-2) — three distinct, cleanly-tagged
events tracing one causal chain from threat to termination to market
consequence, a template for how a slow-building energy-security story
should be staged across several event objects rather than compressed.

**The LA wildfires began at the very end of this batch (1-8) and go
untagged for the same reason as every other climate disaster this
session** (Helene, Milton, Cyclone Chido) — no `climate_disaster` node
exists. This is now the fourth major weather/climate catastrophe this
session forced into a non-tag, and given the fires' scale was still
escalating as the batch closed, batch #46 should expect to carry
several more untagged high-magnitude days here unless this gap is
addressed. Combined with the persistent `south_korea` gap (Yoon's
arrest-warrant standoff continued all batch, still untagged), the
backlog now has two "recurring, high-magnitude, zero-representation"
items alongside the longer-standing `boe_rate`/`uk_banks` gaps.

**Trump's transition produced two genuinely new signal categories this
batch worth tracking distinctly through inauguration**: (1) territorial-
threat escalation from suggestion (Panama/Greenland, batch #44) to
explicit non-denial of military force (1-7) — tagged with a wide
confidence band given how far outside normal diplomatic practice this
sits; (2) the first explicit Fed acknowledgment that incoming Trump
policy is a named risk to its own inflation-fighting effort (1-8 minutes)
and the first instance of Trump publicly taking Russia's side on a
substantive Ukraine-war question (opposing Nato membership, 1-8) — both
concrete data points for the "expected policy" → "actual policy"
transition to keep watching as 2025-01-20 approaches.

**Batch #46 summary (2025-01-09 → 2025-01-22)**: rebuilt ledger now holds
912 event_keys across 571 days. This batch spans 45 events over 14 days
(3.21/day) with magnitude mean 0.277 / median 0.25. This **breaks the
four-batch magnitude-decline streak flagged in batch #45** (0.298 →
0.275 → 0.266 → 0.262 → **0.277**), and the batch #45 note's proposed
diagnostic resolves cleanly: this batch contained two of the highest-
magnitude terminal-resolution events of the entire session (the Gaza
ceasefire ending the 15-month `israel-hamas-war-2023` thread, and
Trump's actual inauguration completing the election-to-power arc), and
both scored appropriately high (0.5 and 0.6 magnitude respectively).
The prior decline was real news-mix variation (more continuations,
fewer fresh terminal events), not scoring drift — confirmed now that a
batch with genuine terminal events pushed the mean back up exactly as
the convention predicts. Novelty mix skewed unusually high this batch:
8 at 1.0, 1 at 0.9, 13 at 0.8, 8 at 0.7, 9 at 0.6, 6 at 0.5 — zero
entries below 0.5, the first batch this session with no low-novelty
recap events at all, reflecting how much of this fortnight was
genuinely new (ceasefire, inauguration, day-one executive orders).
`geopolitical_tension` eased further to 42.2% (from 46.8%, continuing
its gradual decline from the 60.9% peak in batch #44), `europe_growth`
22.2%, and `renewables` reached a new high of 8.9% — its most validated
stretch of the session.

**Two of the session's longest-running event_key threads reached
terminal resolution in the same batch**: `israel-hamas-war-2023`
(open since the archive's earliest coverage, ~15 months) resolved via
the phased ceasefire (announced 1-15, ratified 1-17, implementation
began 1-19), and `us-2024-presidential-election`/the broader Trump-
transition arc (open since mid-2024) resolved via the actual
inauguration (1-20). Both were tagged at their respective maximum
appropriate magnitude/polarity per the established convention for
terminal events, validating that the "reserve maximum signal for true
thread-closing events" discipline continues to work correctly even
when two such events land in the same two-week window.

**`renewables` was validated across four genuinely distinct mechanisms
this batch**, the clearest evidence yet that the node generalizes well:
Trump's Paris Agreement withdrawal (1-20, policy/treaty), his EV-target
revocation (1-21, regulatory rollback), the broader global financial
sector dropping net-zero pledges (1-20, corporate/capital-allocation),
and the EU generating more electricity from solar than coal for the
first time (1-22, a genuinely positive-direction datapoint proving the
node isn't one-directionally bearish). `ai_datacenter` was also
validated for the first time this session via Trump's $500bn Stargate
AI infrastructure announcement (1-21).

**The LA wildfires produced this session's first dollar-quantified
climate-disaster figure** ($200bn+ estimated losses, forecast to be the
costliest fire in US history, reported 1-14) and remained untagged for
the same reason as Helene, Milton, and Chido — no `climate_disaster`
node exists. This is now unambiguously the strongest evidence case for
that gap: a concrete, sourced economic-loss figure larger than most
tracked GDP-relevant events this session. South Korea's Yoon was
actually arrested this batch (1-15), the terminal event of the
martial-law saga tracked since batch #43 — also left untagged per the
same persistent gap. Both should be considered priority candidates
alongside `boe_rate` if a future batch drafts new node proposals.

**The LA wildfires' final cost figure lands at $250bn+ upon full
containment** (Palisades and Eaton fires declared fully contained
2-1, 29 dead), up from the $200bn+ estimate reported three weeks
earlier — the number only grew as containment proceeded, reinforcing
this as the single strongest quantified case for the `climate_disaster`
gap of the whole session so far. It remains completely untagged in
`events/2025-02-01.json` for the same structural reason as Helene,
Milton, Chido, and the initial LA estimate: no node exists to receive
the signal, and forcing it onto `global_growth` or any other proxy
would violate the origin-only tagging discipline (the loss is
insurance/rebuilding-sector-concentrated, not a macro growth signal in
its own right — it needs its own home). **UK banking-sector evidence
also thickened this batch**: a Barclays IT glitch locked customers out
of accounts for almost 24 hours (2-1), landing on both HMRC's
self-assessment tax deadline and a payday for many workers — the
second distinct `uk_banks`-relevant incident this session after the
Lloyds branch-closure wave (1-29/1-30, 136 branches), still with no
node to receive either. `boe_rate`, `climate_disaster`, and `uk_banks`
now stand as the three best-evidenced gap candidates and should be
prioritized in that order if seed.py is next extended.

### Batch #47 checkpoint (2025-01-23 to 2025-02-05)

Ledger rebuilt to **937 event_keys across 585 days**. This batch: 59
events over 14 days (4.21/day, the highest per-day density of any
batch so far). Magnitude mean 0.243 / median 0.2 — a further step down
from batch #46's 0.277, continuing the multi-batch decline flagged in
batch #45 (0.298→0.275→0.266→0.262→0.277→**0.243**). Novelty mix: 7
terminal/new (12%), 23 phase-change (39%), 24 material-development
(41%), 5 recap/color (8%). Node concentration: `geopolitical_tension`
52.5% (31/59), `global_growth` 6.8%, `oil_price` 5.1%, `europe_growth`
5.1%, `ai_datacenter` 5.1%, `nvda` 3.4%, `fed_rate` 3.4%, `pharma`
3.4%. Type mix: geopolitics 31, markets 13, politics 6, monetary_policy
4, macro 2, energy 2, business 1.

**Diagnosing the magnitude decline, again**: unlike batch #45's
false-alarm (which self-corrected the following batch via terminal
events), this drop looks structurally real and explainable rather than
a scoring-drift symptom. The batch did contain several appropriately
high-magnitude terminal events (DeepSeek's $465bn Nvidia rout at 0.45,
Trump's actual Canada/Mexico/China tariff imposition at 0.45, the
Gaza-takeover shock announcement at 0.5) — so the ceiling is being used
correctly. What's pulling the mean down is breadth: this was an
unusually fast-moving fortnight (tariff threat → imposition →
retaliation → partial reversal → new EU front, all within six days)
that generated many legitimate lower-magnitude continuation/color
events tracking each twist, rather than a failure to recognize
high-magnitude moments. The right read is that magnitude and
event-density are inversely correlated during high-frequency-whiplash
news periods, not that the digester is under-scoring. Worth
re-examining if the decline continues past batch #48 without a
density-driven explanation.

**The `geopolitical_tension` concentration (52.5%) is the most
actionable finding of this batch.** Six genuinely distinct
macro-economic phenomena were all funneled through this single node
for lack of alternatives: (1) the US-Canada-Mexico-China-EU tariff war,
(2) the Gaza ceasefire/ownership-plan saga, (3) the DRC/M23/Rwanda
conflict, (4) the Russia-Ukraine war and its rare-earths-for-aid
twist, (5) Trump's territorial rhetoric (Greenland/Panama/South
Africa), and (6) domestic US immigration-crackdown actions
(Guantánamo, TPS revocations). These are not interchangeable signals —
a trade-war escalation and a humanitarian-ceasefire violation have
completely different transmission mechanisms into markets, yet they
currently share one node and one polarity convention ("+1 =
escalating"). This strongly reinforces a proposal not yet logged
earlier: a dedicated **`trade_policy`** node (distinct from generic
`geopolitical_tension`) to isolate tariff/trade-war signal, which
would immediately have de-concentrated roughly a third of this batch's
`geopolitical_tension` tags and given the model a cleaner economic
channel for tariff-driven inflation/growth effects instead of blending
them into a generic escalation score.

**Two clean "beat-then-reverse" pairs validated the same-node
opposite-direction discipline again**: the Canada/Mexico tariff
imposition (2-1, polarity +0.5) followed two days later by Trump
pausing those same tariffs for 30 days (2-3, polarity -0.35, same
event_key) while *simultaneously* opening a new EU-specific escalation
the same day (+0.3) — three event objects, one event_key, one day,
correctly split rather than averaged or overwritten. Similarly the DRC
thread ran capture (1-27, +0.45) → aid-threat leverage (1-29, +0.2) →
unilateral ceasefire (2-4, -0.3) inside eight days, a full
escalation-to-de-escalation arc.

**`climate_disaster` gap evidence reached its strongest point yet**:
the LA wildfires' final contained cost came in at $250bn+ (2-1), up
from the $200bn+ estimate three weeks earlier, plus State Farm's
emergency 22% California rate-hike request citing wildfire strain
(2-3) — a second, insurance-sector-specific data point for the same
gap. `uk_banks` also gained a second incident (Barclays 24-hour outage,
2-1, landing on the tax deadline) beyond the Lloyds branch closures.
`germany_politics` gained its most dramatic evidence yet: an
AfD-enabled immigration motion actually passed (1-29, "historic day"
per AfD's own leader) only for the full bill to be rejected by
parliament two days later (1-31) after Merkel publicly rebuked her
successor Merz — a complete escalation-then-defeat arc with zero
nodes available to receive any of it. `boe_rate` continues to
accumulate silently (BoE rate decision pressure mentioned 2-2, still
untagged).

### Batch #48 checkpoint (2025-02-06 to 2025-02-19)

Ledger rebuilt to **957 event_keys across 599 days**. This batch: 52
events over 14 days (3.71/day). Magnitude mean 0.249 / median 0.25 —
essentially flat versus batch #47's 0.243, confirming last batch's
diagnosis that the multi-batch decline had a density-driven
explanation rather than being genuine scoring drift: event-density fell
back toward the historical average (3.71/day vs. 4.21/day) and
magnitude promptly stabilized. Novelty mix: 5 terminal/new (10%), 22
phase-change (42%), 24 material-development (46%), only 1 recap/color
(2%) — the leanest recap share of any batch this session, reflecting
how much of this fortnight was genuine escalation rather than color.
Node concentration: `geopolitical_tension` 53.8% (28/52), `europe_growth`
11.5%, `global_growth` 5.8%, `renewables` 5.8%, `us_inflation` 3.8%,
`chips` 3.8%, `natural_gas` 3.8%, plus singles. Type mix: geopolitics 29,
markets 12, macro 4, energy 3, monetary_policy 1, politics 2, business 1.

**`geopolitical_tension` concentration held at 53.8%, essentially
unchanged from batch #47's 52.5%** — the proposed `trade_policy` node
split has not yet been implemented, so the same six-phenomena blending
problem persists and, if anything, deepened: this batch added a
seventh distinct sub-thread (the Vance Munich speech / transatlantic
alliance rupture, `us-2025-vance-munich-speech`) that is neither a
trade dispute, a ceasefire, nor a territorial threat, but a fourth
completely distinct category (intra-alliance ideological rift) now
also sharing the same single node. The case for decomposing
`geopolitical_tension` is now stronger than a single `trade_policy`
carve-out — this batch suggests at minimum three siblings:
`trade_policy` (tariffs), `alliance_cohesion` (Vance/Munich-style
rifts between traditionally aligned powers, distinct from adversarial
tension), and the existing catch-all for adversarial/military
conflict. Without this split, a portfolio model consuming
`geopolitical_tension` cannot distinguish "the US and EU are
tariffing each other" from "the US publicly sided with Russia's war
narrative" from "M23 captured a second Congolese city" — three
completely different risk transmission channels currently registering
as the same scalar.

**The `europe_growth` node absorbed unrelated signal types this
batch, another concentration artifact worth flagging**: it was used
for the BoE's stagflation-warning rate cut (2-6), UK gilt-yield
normalization (2-5), UK Q4 GDP surprise (2-13), UK CPI surprise (2-19),
Glencore's listing-exodus threat (2-19), *and* the European
defense-stocks/BAE-earnings rally (2-17, 2-19) — six genuinely
different economic phenomena (monetary policy, bond yields, GDP,
inflation, equity-listing flight, and a specific-sector earnings
story) sharing one node purely because no more granular alternative
exists. The defense-spending story in particular is arguably
mistagged: European rearmament is a `geopolitical_tension`-driven
capital-allocation shift, not a "UK/EU growth" data point, but no
`defense_stocks` or `european_equities` node exists to receive it
cleanly. Flagging this as a new gap candidate: a narrow
**`defense_spending`** node would cleanly capture the
Denmark/BAE/Rheinmetall/Saab rearmament thread that is likely to keep
recurring as the Ukraine peace process plays out.

**The Ukraine diplomatic thread underwent a complete reversal within
the batch, correctly captured via same-event_key polarity splits**:
opened with Trump-Putin direct contact (2-9, -0.2, de-escalating) →
Trump conceding no-NATO-for-Ukraine (2-13, -0.35) → Vance's Munich
rupture with Europe (2-14, own event_key, +0.35) → US-Russia Riyadh
talks excluding Ukraine (2-16, +0.3, escalating-via-exclusion) →
US-Russia "tectonic shift" agreement (2-18, -0.35, de-escalating
between US/Russia specifically) → Trump blaming Ukraine for starting
the war (2-19, +0.4, the sharpest rupture yet). Six tag-worthy
inflection points in eleven days on the same event_key, alternating
sign twice — a textbook case for why the same-node
opposite-direction-within-days discipline exists, and why event_key
continuity (rather than forcing one node-average per story) is the
right unit of analysis for a fast-moving diplomatic thread.

**DRC/M23 evidence undermines the ceasefire the model itself flagged
as a de-escalation two batches ago**: the unilateral ceasefire M23
declared 2-4 (tagged -0.3) was followed just 11 days later by the
capture of Bukavu, DRC's second-largest city (2-15, +0.4) — a
concrete lesson that self-declared ceasefires by an advancing militia
should be treated with wider confidence bands / smaller magnitude than
government-to-government truces (contrast with the Gaza ceasefire's
relative durability across the same batch), since they carry no
enforcement mechanism and may simply reflect a tactical pause before
the next objective.

**`germany_politics` gap evidence reached its decisive point (2-23):
the actual federal election took place**, with AfD projected to finish
second at ~20% of the vote — the strongest possible evidence for this
long-flagged gap, since it is no longer a mid-cycle motion or a
polling trend but a completed national election result for the EU's
largest economy, with weeks of coalition-formation consequences to
follow (Merz/CDU almost certain to be chancellor, exact coalition
math still open). This landed completely untagged, same as every
prior AfD/Merz/Merkel data point this session. If only one new node
proposal from the session gets prioritized for implementation, this
batch's evidence makes `germany_politics` (or a broader `eu_politics`)
as strong a candidate as `boe_rate` — both now have a "the event
literally already happened at maximum stakes and we still couldn't
tag it" case on record.

### Batch #49 checkpoint (2025-02-20 to 2025-03-05)

Ledger rebuilt to **974 event_keys across 613 days**. This batch: 61
events over 14 days (4.36/day, the highest density since batch #47).
Magnitude mean 0.267 / median 0.25 — up from batch #48's 0.249,
continuing to track density rather than showing any independent trend.
Novelty mix: 5 terminal/new (8%), 32 phase-change (52%), 24
material-development (39%), **zero recap/color** — the first batch
this entire session with no events below 0.45 novelty. This is the
starkest possible confirmation that this fortnight was a genuine
historical inflection point (the Trump-Zelenskyy Oval Office rupture,
the US military-aid and intelligence-sharing suspension, Germany's
debt-brake reversal, the EU's €800bn rearmament plan) rather than
routine news flow — there was no color/recap left to tag because
almost nothing was mere continuation. Node concentration:
`geopolitical_tension` 55.7% (34/61) — a new high — `europe_growth`
11.5%, `btc` 6.6%, `global_growth` 4.9%, `renewables` 3.3%,
`china_growth` 3.3%, `dollar` 3.3%, plus singles. Type mix: geopolitics
37, markets 17, macro 4, energy 3 (zero politics/business/monetary_policy
this batch, reflecting how completely the Ukraine/tariff story
dominated the news cycle).

**`geopolitical_tension`'s 55.7% concentration is now a three-batch
trend (52.5% → 53.8% → 55.7%)**, and this batch supplies the starkest
possible case for the `trade_policy`/`alliance_cohesion` split proposed
in batches #47-48: within this single node this fortnight sat the
Trump-Zelenskyy Oval Office meltdown (alliance/personal), the US
military aid and intel-sharing suspension (alliance/material), the EU's
€800bn rearmament response (alliance/fiscal), Germany's debt-brake
reversal (fiscal/domestic-political), the steel/EU/car/semiconductor
tariff escalation-and-exemption cycle (trade), the PKK-Turkey
ceasefire (adversarial/domestic), the DRC/M23 Bukavu violence
(adversarial/humanitarian), and the Gaza aid-cutoff/ceasefire-renegotiation
(adversarial/humanitarian) — eight distinct sub-phenomena, several of
which have no plausible shared transmission mechanism into markets,
now numbering enough that the "one node, one polarity convention"
approach is closer to lossy compression than signal. This is the
strongest evidenced case yet for prioritizing the node-graph split
over any single new node addition.

**`btc` earned its first sustained multi-event thread this session**:
Bybit hack (2-23, -0.3) → NK attribution (2-27, -0.15) → broader
selloff below $90k (2-25, -0.3) → 17.5% monthly loss into bear-market
territory (3-2, -0.35) — four connected events over eight days
showing a clean cascade from a single exchange-security incident into
a market-wide risk-off move, a good real-world test of the
event_key-continuity discipline operating on a fast-moving markets
thread rather than a slow-moving geopolitical one.

**The Trump-Zelenskyy Oval Office rupture (2-28) is the strongest
single-day novelty=1.0 case of the entire session to date** — a
scripted, televised, unrepeatable diplomatic event rather than a
gradual escalation, immediately followed one thread-day later by the
US suspending all military aid (3-4, its own 0.95) and then
intelligence-sharing (3-5, 0.8). Three genuinely maximal-tier events on
the same event_key within a single week is unprecedented for this
session and validates reserving 1.0 exclusively for irreversible,
singular moments — if this thread is ever re-scored, these three
timestamps are the calibration anchor.

**`europe_growth` absorbed yet another distinct phenomenon this
batch — European defense-sector market rallies (BAE 2-19, stocks
2-17/3-3, Germany's €800bn+debt-brake reversal 3-4/3-5) — reinforcing
the `defense_spending` node proposal from batch #48 with three more
data points, including the single largest fiscal number of the
session (Germany's debt-brake reversal, uncapped defense borrowing for
Europe's largest economy).** This concentration is now impossible to
ignore: `europe_growth` has carried monetary policy, GDP, gilt yields,
CPI, equity-listing exodus, AND defense-sector capital flows across
three consecutive batches.

### Batch #50 checkpoint (2025-03-06 to 2025-03-19)

Ledger rebuilt to **995 event_keys across 627 days**. This batch: 64
events over 14 days (4.57/day, a new high). Magnitude mean 0.251 /
median 0.25 — essentially flat versus batch #49's 0.267, holding
steady despite this being the single busiest batch of the session.
Novelty mix: only 2 terminal/new (3%), 35 phase-change (55%), 27
material-development (42%), zero recap/color for the second batch
running. Node concentration: `geopolitical_tension` 50.0% (32/64) —
the first *decline* in three batches (55.7%→53.8%→50.0%… actually
55.7%→50.0%, reversing the trend) — `europe_growth` 14.1%,
`global_growth` 14.1% (a new entrant at scale), `tsla` 6.2%,
`us_inflation` 4.7%, plus singles. Type mix: geopolitics 37, markets
13, macro 9, monetary_policy 3, energy 1, politics 1.

**The `geopolitical_tension` concentration finally dropped**, not
because the underlying story diversified but because this batch
contained an unusually large amount of hard macro/markets data
(S&P 500 correction, Fed growth/inflation revisions, OECD stagflation
warning, dollar weakness, Tesla's cratering) that properly belongs on
`global_growth`, `us_inflation`, `dollar` and `tsla` instead. This is
a good sign for tagging discipline — when genuine market-moving macro
data exists, it is being routed to the correct specific node rather
than getting swept into the geopolitics catch-all by association. The
`trade_policy`/`alliance_cohesion` split proposal from batches #47-49
remains valid but this batch is evidence that *some* of the
concentration problem self-corrects naturally when the news cycle
generates enough independently-tagladable market data.

**This was the most whiplash-heavy fortnight of the session for a
single event_key**: `ukraine-kursk-incursion-2024` recorded twelve
separate entries oscillating between escalation and de-escalation
inside fourteen days — Trump defending Putin's strikes (3-8, +0.35) →
Russia sanctions considered (3-7, +0.25) → Kursk pocket nearly
encircled (3-8, +0.35) → US-Ukraine ceasefire agreed (3-12, -0.4) →
Putin questions/sets conditions (3-13, +0.35) → Kursk incursion
terminally ends (3-14, +0.3) → Trump-Putin call/partial energy
ceasefire (3-18, -0.25) → Russia strikes hours later (3-19, +0.3).
The event_key-continuity-with-per-event-polarity model held up under
real stress-testing; a single averaged score across this period would
have been meaningless, while the eight-plus individual tags preserve
the genuine back-and-forth for any downstream consumer.

**Two clean terminal-resolution events bookended the batch**: Ukraine's
Kursk incursion (opened in the prior session, resolved 3-14 at
novelty 0.85) and the Gaza ceasefire's collapse (3-18, novelty 1.0 —
only the second true 1.0 this batch, alongside the S&P correction's
adjacent 0.85). The Gaza collapse in particular validates the
terminal-resolution convention cleanly: it was tagged at maximum
magnitude/polarity (0.5/+0.6) specifically because it represented an
irreversible phase change (ceasefire → active war) rather than
another skirmish within an already-fragile truce.

**`tsla` earned a second consecutive batch of sustained multi-event
coverage** (15% single-day drop 3-10, 50%-from-peak confirmation same
day, "no longer Musk's most valuable asset" 3-18, tariff-harm warning
3-14) — the node is proving robust to tracking a genuinely
multi-causal story (Musk political backlash + broader market
correction + tariff exposure) without needing a split, unlike
`geopolitical_tension`. This is a useful contrast case: `tsla` handles
multi-causality fine because all the causes point the same direction
on the same underlying quantity (the stock price); `geopolitical_tension`
struggles because its multi-causality spans phenomena with different
transmission mechanisms into markets.

### Batch #51 checkpoint (2025-03-20 to 2025-04-02)

Ledger rebuilt to **1,017 event_keys across 641 days**. This batch: 55
events over 14 days (3.93/day, back toward the historical average
after batch #50's 4.57 high). Magnitude mean 0.236 / median 0.25 —
the lowest mean of the session, continuing to confirm the
density-correlation diagnosis from batches #48-49: lower event count
this batch, lower mean magnitude, exactly as the density/magnitude
relationship would predict. Novelty mix: only 2 terminal/new (4%), 26
phase-change (47%), 27 material-development (49%) — again zero
recap/color, the third consecutive batch with none. Node
concentration: `geopolitical_tension` 56.4% (31/55) — a new session
high, reversing batch #50's dip back upward — `europe_growth` 16.4%
(also a new high), `global_growth` 9.1%, `tsla` 5.5%, plus singles.
Type mix: geopolitics 32, markets 10, macro 9, monetary_policy 1,
politics 2, energy 1.

**This batch delivered the session's cleanest possible terminal
event: "Liberation Day" (4-2), tagged at the maximum 1.0 novelty /
0.5 polarity / 0.45 magnitude ceiling.** Unlike most "terminal"
events this session (which resolve a single ongoing thread), this one
is unusual in that it terminally resolves a *pattern* — the
escalate/delay/exempt/re-escalate whipsaw on tariffs that ran
continuously from January through early April — by converting it into
the broadest global trade action of the modern era, applied
simultaneously to every trading partner rather than country-by-country.
This is a good template for how to handle "slow-motion inevitability"
threads: novelty should stay in the 0.5-0.8 phase-change band through
every intermediate escalation/pause, reserving 1.0 specifically for
the moment the pattern itself resolves into policy.

**`geopolitical_tension`'s renewed climb to 56.4% (a new session high,
up from batch #50's 50.0%) reopens the case for the `trade_policy`
split proposed across batches #47-50 with the strongest evidence yet**:
this batch alone funneled the following distinct phenomena through
one node — the entire "Liberation Day" tariff saga (car tariffs 3-27,
EU threats 3-31, all-nations reciprocal tariffs 4-1/4-2), the
Trump-Putin oscillation (anger 3-31, Russia's plan rejection 4-1,
secondary-sanctions push 4-2), the Gaza war's territorial escalation
(Netanyahu's "divide up Gaza" plan 4-2), a new Taiwan military-drill
flashpoint (4-1), the Le Pen conviction's transatlantic-right ripple
(3-31), and continuing Turkey/İmamoğlu unrest. Six-plus independent
stories, each with a genuinely different transmission mechanism into
markets, now sharing one polarity convention. No batch this session
has produced a stronger case for prioritizing this split in the next
seed.py revision.

**`europe_growth` also hit a new high (16.4%)**, again for the
reason flagged in batch #49: it remains the only available node for
UK-specific macro data (BoE hold 3-20, borrowing overshoot 3-21,
spring-statement growth downgrade 3-26, CPI decline 3-26, PMI
six-month high 3-24, British Steel closure 3-27, OBR planning-reform
GDP boost 3-30) *and* the European rearmament/defense-spending thread
this batch chose not to touch (no new defense-spending events landed
in this particular fortnight, unusually, after five consecutive
batches of coverage) *and* France's Le Pen political shock. The
`defense_spending` node proposal from batch #48 remains valid but this
batch's absence of defense-thread events is itself informative: the
rearmament story has entered a quieter implementation phase after the
dramatic February-March announcements, suggesting future batches
should watch for renewed data (weapons deliveries, budget execution)
rather than assuming continued high-frequency coverage.

**New gap candidate from this batch: no node exists for French
domestic politics** (Le Pen's conviction and five-year office ban,
tagged to `geopolitical_tension` as the closest available proxy despite
being a domestic legal/political story with only indirect market
transmission via National Rally's 2027 prospects) — joining
`germany_politics` and `turkey_politics` (from batch #50) as
un-tagged major-European-economy domestic political gaps. A single
broader **`eu_politics`** node might be more efficient than three
country-specific ones, since all three cases this session (Germany's
AfD surge, Turkey's İmamoğlu arrest, France's Le Pen ban) are
functionally similar signals: populist/opposition-politics shocks in
major economies with unclear near-term market transmission but
significant medium-term policy-direction implications.

**`south_korea`/`krw` gap reached its terminal point (4-4): the
Constitutional Court upheld Yoon Suk Yeol's impeachment and formally
removed him from office**, ending the martial-law saga tracked since
batch #43 (declaration → reversal → impeachment vote → arrest →
detention-cancellation → now removal). This is the single longest-running
untagged thread of the entire session — a sitting president's
declaration of martial law, arrest, and formal removal, none of it
touchable by any existing node. If seed.py implementation work is ever
prioritized by "most dramatic single story with zero node coverage,"
this is the strongest candidate in the whole digestion log to date,
ahead even of the German election.

**`germany_politics`/`eu_politics` gap gained its terminal data point (4-9): Germany's CDU/CSU and SPD formally form a coalition government**, freezing out the AfD despite its continued polling strength — the resolution of the government-formation process that began with the 2-23 election. Another complete story arc (AfD historic second place → weeks of coalition talks → Merz's debt-brake reform passing in parallel → final coalition agreement) with zero node coverage from election to government formation.

### Batch #52 checkpoint (2025-04-03 to 2025-04-16)

Ledger rebuilt to **1,043 event_keys across 655 days**. This batch: 60
events over 14 days (4.29/day). Magnitude mean 0.26 / median 0.25 —
in line with the session average, holding steady through what was
arguably the single most consequential fortnight of the year
("Liberation Day" 4-2 fell in batch #51, but its market and diplomatic
aftermath — the biggest Wall Street falls since 2020/Covid, the bond-market
revolt that forced Trump's 90-day pause, the China-specific escalation
to 145%, and the chip-export curbs — played out entirely within this
batch). Novelty mix: 2 terminal/new (3%), 31 phase-change (52%), 27
material-development (45%), zero recap/color for the fourth batch
running. Node concentration: `geopolitical_tension` 43.3% (26/60) — a
sharp *drop* from batch #51's 56.4%, the lowest in five batches —
`global_growth` 23.3% (a new all-time high, more than double any
prior batch), `europe_growth` 11.7%, `dollar` 5.0%, `chips` 5.0%, plus
singles. Type mix: markets 18, geopolitics 28, macro 10, monetary_policy
1, politics 2, energy 1.

**This batch is the clearest validation yet of the batch #50-51
hypothesis that `geopolitical_tension` concentration self-corrects
when the news cycle generates enough independently-tagable market
data.** The tariff saga's market *consequences* this fortnight —
Wall Street's worst days since Covid, the Treasury bond selloff that
by multiple accounts directly forced Trump's tariff pause, the dollar's
safe-haven crisis, Nvidia's chip-export hit, gold's repeated record
highs — generated a genuinely large `global_growth`/`dollar`/`chips`/`gold_price`
tagging volume for the first time this session, pulling `geopolitical_tension`
down to 43.3% without any change in tagging methodology. This strongly
suggests the concentration problem is *substantially* a function of
which specific fortnight is being covered (diplomacy-heavy vs.
market-reaction-heavy) rather than a pure structural flaw requiring
an immediate node split — though the `trade_policy` split proposal
from batches #47-51 remains valid or even higher-value now that this
batch demonstrates a `global_growth` node absorbing genuinely
tariff-specific market reactions that arguably belong on a more
targeted node too.

**The bond-market story (4-9 through 4-11) is this session's cleanest
example of a market signal directly and verifiably causing a policy
reversal**: the Treasury sell-off (4-9, "loss of financial confidence
in US") was widely reported as the actual trigger for Trump's 90-day
tariff pause the same day, with dollar safe-haven status explicitly
described as "in jeopardy" (4-11). This is a rare case where the
causal chain from market node to policy event is well-documented in
contemporaneous reporting rather than inferred after the fact — worth
flagging as a template for how a `dollar`/bond-market signal can
function as a genuine leading indicator for tariff-policy risk in this
graph, distinct from its usual role as a lagging confirmation of
other events.

**China's tariff figure climbed through five discrete levels within
eleven days** (20%→34%→84%→104%/125%→145%), each one tagged as its own
event on the same event_key with appropriately declining novelty as
the pattern became familiar (0.7→0.7→0.6) until the 125% match (0.7,
a genuine new peak) — a good illustration of novelty correctly
tracking "is this actually new information" rather than "is this a
round number" once a ratcheting pattern is established.

### Batch #53 checkpoint (2025-04-17 to 2025-04-30)

Ledger now at 1068 event_keys / 669 days. This batch: 14 days, 67 events
(4.79/day). Magnitude mean/median: 0.226/0.2 — continuing the
density-correlated decline pattern first diagnosed in batch #48-49 and
reconfirmed in #52; this fortnight's mix was diplomacy/de-escalation-heavy
(many "ease," "pause," "defy," "restore" events at 0.15-0.25 magnitude)
rather than shock-heavy, which mechanically pulls the mean down without
indicating any drift in calibration. Novelty mean/median: 0.636/0.6.
Novelty mix: 1 terminal/new (1.5%), 28 intermediate 0.7-0.8 (41.8%), 34
material-dev 0.5 (50.7%), 4 recap/color ≤0.4 (6.0%) — a healthy
distribution with the terminal slot reserved for the single most
consequential resolution of the period (see below). Node concentration:
`geopolitical_tension` 58.2% (39/67), `global_growth` 13.4%, `europe_growth`
10.4%, `fed_rate` 4.5%, `ai_datacenter` 3.0%, plus five singles (`chips`,
`gold_price`, `pharma`, `renewables`, `japan_equities`). Type mix:
geopolitics 40, macro 10, markets 9, monetary_policy 4, energy 4.

**`geopolitical_tension` concentration rebounded to 58.2%, reversing the
batch #52 dip to 43.3%.** This fortnight's dominant threads — the
tail end of the Trump-Zelenskyy/Putin ceasefire dance (five more entries
on the `ukraine-kursk-incursion-2024` event_key alone), Canada's full
election arc (called-in-response-to-tariffs → campaign → Carney win,
three entries), the Spain/Portugal blackout (onset + resolution), and
the new UK Yemen-strikes thread — were almost entirely diplomatic/
political rather than market-reactive, unlike batch #52's tariff-crash
aftermath. This is exactly the mechanism flagged in batch #52's summary:
concentration swings hard between fortnights depending on whether the
news cycle is producing diplomacy or market consequences, which continues
to argue for the `trade_policy`/`alliance_cohesion` split proposals as a
structural fix rather than waiting for lucky fortnights.

**The batch's single terminal-novelty (0.9) event is the US Q1 2025 GDP
contraction (4-30)** — the first negative growth print of the tariff era,
converting the "Trumpcession" narrative that had been building since
February from a market/sentiment story into an actual hard-data
confirmation. This lands on the `global_growth` node rather than a new
node, but is a good test case for whether `global_growth` alone can carry
both "soft" sentiment signals (consumer confidence, PMI surveys) and
"hard" GDP prints with proportionally scaled novelty/magnitude — this
batch suggests yes, since the terminal GDP print correctly out-scaled
every preceding soft-data event on the same thread (port shipment slump
4-28 at 0.6, HSBC provisioning 4-29 at 0.6, consumer sentiment collapse
folded into the 4-30 event itself).

**Big Tech earnings (Meta, Microsoft, both 4-30) reinforce the
`ai_datacenter` node's resilience to broader macro deterioration**: both
beat expectations and both raised or held AI capex guidance ($80bn from
Microsoft) on the same day the US printed negative GDP — a clean
same-day divergence between the AI-investment thread and the
tariff-driven broader economy that's worth watching as a recurring
pattern (AI capex as a partially insulated sub-cycle) rather than a
one-off.

**China's manufacturing PMI collapse and the 65% e-commerce export
plunge (4-30) mark a reversal from the resilience narrative** carried
in earlier batches (China's GDP growth-spurt data, "sky won't fall"
commentary) — the trade war's hard-data bite is now visible on both
sides of the Pacific in the same 48-hour window (US GDP contraction,
China PMI collapse), a useful cross-checkable pair for any future
model validation exercise.

**New node-existence gap confirmed this batch: none** — all events
tagged cleanly to existing nodes (`geopolitical_tension`, `global_growth`,
`europe_growth`, `fed_rate`, `ai_datacenter`, `chips`, `gold_price`,
`pharma`, `renewables`, `japan_equities`). The UK Yemen-strikes event
(4-30) was tagged to `geopolitical_tension` per origin-only convention;
no dedicated `middle_east_conflict` or `alliance_cohesion` node exists
yet to carry it more precisely, adding one more data point to the
`alliance_cohesion` split-proposal backlog (this event is specifically
about alliance participation/burden-sharing, not tension escalation per
se — a clean illustration of the proposed split's value).

### Batch #54 checkpoint (2025-05-01 to 2025-05-14)

Ledger now at 1103 event_keys / 683 days. This batch: 14 days, 72 events
(5.14/day, the highest density since batch #52's tariff-crash aftermath).
Magnitude mean/median: 0.217/0.2 — flat versus batch #53, continuing to
confirm the density-correlated pattern (more events per day slightly
dilutes per-event average magnitude even when several individual events
are genuinely major). Novelty mean/median: 0.611/0.6. Novelty mix: 3
terminal/new 0.9-1.0 (4.2%), 19 intermediate 0.7-0.8 (26.4%), 45
material-dev 0.5 (62.5%), 5 recap/color ≤0.4 (6.9%) — three separate
terminal-novelty events in one fortnight is unusually high, reflecting
a period with multiple genuinely concluding threads rather than one.
Node concentration: `geopolitical_tension` 61.1% (44/72) — the highest
of the whole session — `europe_growth` 19.4%, `global_growth` 5.6%,
`pharma` 4.2%, plus five singles. Type mix: geopolitics 46, markets 15,
macro 8, monetary_policy 2, energy 1.

**This fortnight contains the single most consequential de-escalation of
the entire tariff saga: the US-China 90-day tariff pause (5-12), which
earned this session's rare 1.0 novelty score alongside the India-Pakistan
ceasefire's steepest-escalation-then-truce pair (5-10) and the UK
services PMI/Q1 GDP threads.** The pause was the terminal point of a
tightly-documented five-day de-escalation arc: China "evaluating" talks
(5-2) → Trump floating an 80% rate (5-9) → the Geneva meeting →
"important first steps" (5-11) → the full 115-point pause with Trump's
"total reset" framing and a Wall Street surge (5-12). This is a clean
worked example of the novelty convention functioning exactly as intended
across a multi-day thread: each intermediate step scored 0.5-0.8 as
genuinely new information arrived, reserving 1.0 for the actual
resolution.

**The India-Pakistan crisis (5-7 through 5-11) is the sharpest
escalation-to-de-escalation swing tracked this session**: missile
strikes killing dozens (5-7) → conflicting drone-strike claims (5-8-9)
→ the steepest escalation yet, cross-border strikes on military bases
deep inside both countries (5-10 morning) → a US-mediated ceasefire
the same day (5-10 evening) → both sides claiming victory a day later
(5-11). The same-day escalation-then-ceasefire pair required the
dual-tag/same-event_key discipline at its most extreme this session —
opposite-polarity events roughly eight hours apart on the same
event_key, which the schema and novelty convention handled cleanly
(0.7 escalation novelty, 0.85 ceasefire novelty reflecting its greater
informational significance as the arc's actual resolution point).

**`geopolitical_tension` concentration hit a new session high of
61.1%**, exceeding even batch #53's 58.2% and approaching batch #46's
historical peak. This fortnight had an unusual density of *simultaneous*
major geopolitical threads — US-China tariffs, India-Pakistan,
Ukraine-Russia Turkey-talks diplomacy, Gaza's escalation toward full
occupation, the Yemen/Houthi ceasefire, Romania's election, the PKK
disarmament, Syria's sanctions relief, and China-Russia's Victory Day
summit — all cresting in the same two weeks. This is the strongest
evidence yet for the `trade_policy`/`alliance_cohesion` split proposals:
a single node is being asked to carry US-China trade dynamics, a
nuclear-armed-neighbor military crisis, a European land war's ceasefire
diplomacy, a Middle East occupation, and Great Power alignment signals
simultaneously, with no way to distinguish these qualitatively different
"tension" phenomena from the tag alone. Notably, this is also the first
batch where a purely diplomacy-heavy fortnight *still* failed to produce
low concentration, undercutting the batch #52-hypothesis that the swings
are mostly a function of diplomacy-vs-market-consequence balance — this
fortnight had substantial market-relevant volume too (`europe_growth` at
19.4%, its second-highest share this session) and concentration still
climbed. The split proposals should now be considered high-priority
rather than speculative.

**`europe_growth` at 19.4% is its second-highest concentration this
session**, driven by a genuinely rich fortnight of UK-specific data: the
BoE rate cut, UK-US and UK-India trade deals, consumer confidence and
services PMI deterioration, unemployment hitting a four-year high, and
company-specific layoffs (BMW, Burberry) and investments (AESC
gigafactory, Mansion House pension accord) landing almost daily. This
is a good illustration of `europe_growth` correctly absorbing
UK-specific macro signal even though the node name suggests a
continental scope — worth flagging as a naming-clarity issue: the node
functions as "Europe ex-Eurozone-specific, UK-heavy growth", which may
warrant a rename or split if UK data continues to dominate its tag
volume at this rate.

**Strongest-yet evidence for the `boe_rate` gap**: the Bank of England's
quarter-point cut to 4.25% (5-8, a 5-2-2 split vote) is arguably the
single most consequential UK monetary-policy event of the entire
session, occurring the same week as two major UK trade deals and a
record unemployment print — yet it could only be described in prose in
this doc, not tagged to any node, because no BoE/UK-rate node exists.
Given the UK's outsized event volume this fortnight (`europe_growth` at
19.4%), the case for adding `boe_rate` as a real node (mirroring
`fed_rate`) is now stronger than at any prior checkpoint.

**New node-existence gaps confirmed this batch**: none beyond the
already-flagged backlog (`boe_rate`, `climate_disaster`, `uk_banks`).
All events tagged cleanly to existing nodes. Media/entertainment-sector
market reactions (Netflix/Warner Bros/Paramount sliding on the movie-
tariff threat, 5-5) were deliberately left untagged per origin-only
discipline, since no `media` or `entertainment` node exists and forcing
the tag onto `global_growth` would have diluted a node whose polarity
already carries multiple distinct macro signals this fortnight.

### Batch #55 checkpoint (2025-05-15 to 2025-05-28)

Ledger now at 1125 event_keys / 697 days. This batch: 14 days, 67 events
(4.79/day). Magnitude mean/median: 0.224/0.2, essentially flat versus
batch #54's 0.217/0.2. Novelty mean/median: 0.615/0.6. Novelty mix: 0
terminal/new at ≥0.9 (0%), 22 intermediate 0.7-0.8 (32.8%), 44
material-dev 0.5 (65.7%), only 1 recap/color ≤0.4 (1.5%) — this is the
first batch this session with effectively zero low-novelty recap
filler; nearly every event carried genuine incremental information,
reflecting how fast-moving this fortnight's several parallel threads
were. The absence of any 1.0-novelty event is notable given batch #54
had three — this fortnight's biggest developments (UK-EU deal, US-EU
tariff escalation/delay, Nvidia earnings) all scored 0.7-0.85 rather
than 1.0, correctly reflecting that none was a fully terminal resolution
so much as a major step in an ongoing thread. Node concentration:
`geopolitical_tension` 62.7% (42/67) — a new session-high, exceeding
even batch #54's 61.1% — `europe_growth` 16.4%, `chips` 6.0%,
`us_inflation` 6.0%, `dollar` 4.5%, plus two singles. Type mix:
geopolitics 48, macro 9, markets 9, energy 1.

**`geopolitical_tension` concentration set a new session-high for the
second batch running (62.7%, up from 61.1%)**, driven by an
extraordinarily dense simultaneous-threads fortnight: the India-Pakistan
ceasefire's aftermath, the full Ukraine-Russia arc (failed Trump-Putin
call → sanctions → prisoner swap → Germany's long-range-weapons deal →
Russia's biggest-ever drone attack, all within 10 days), Gaza's
escalation into full occupation with UK/France/Canada/EU diplomatic
rupture with Israel, the US-EU 50%-tariff cycle (threat → delay →
positive talks), Romania's election resolution, Portugal's Chega surge,
the DC Israeli-embassy shooting, and Iran-US nuclear talks progressing
in parallel. Two consecutive batches above 60% concentration is the
strongest quantitative case yet in this session for treating the
`trade_policy`/`alliance_cohesion` split proposals as high-priority
rather than exploratory — a single node is absorbing at least five
qualitatively distinct tension categories (trade wars, active
interstate war, occupation/humanitarian catastrophe, election-driven
alliance fragmentation, and domestic political violence) simultaneously,
and volume keeps climbing rather than mean-reverting.

**Strongest-yet illustration of the UK-inflation/`boe_rate` gap
compounding**: this fortnight saw UK "awful April" inflation jump to
3.5% (5-21, "bigger than expected... worsens Bank of England dilemma"),
followed by UK grocery inflation hitting a 15-month high of 4.1% (5-28)
— both concrete, market-moving UK price data landing in the same
fortnight as the BoE's chief economist warning rate cuts were "too
rapid" (5-21) and risked fueling an inflation resurgence. None of this
could be tagged, because the graph has `fed_rate`/`us_inflation` for
the US but no UK equivalent for either quantity. This is now the
clearest evidence across the whole session that `boe_rate` should be
paired with a companion `uk_inflation` node (or a single combined
UK-monetary-policy node) rather than proposed alone — the events keep
arriving as tightly coupled pairs (inflation print → BoE dilemma
commentary) that a lone rate node would only half-capture.

**`dollar` emerges as a recurring node this fortnight (4.5%, its highest
share yet)**, carrying the Moody's US credit-rating downgrade (5-18)
through its market aftermath (5-19) and into the bond-market fallout
from Trump's tax bill (5-24) — a clean three-part thread showing the
node correctly absorbing a slow-building sovereign-credibility story
distinct from the tariff-driven `global_growth`/`geopolitical_tension`
narrative running in parallel. This is a good validation that `dollar`
functions well as intended (a bond/currency/credibility signal
node) rather than needing to compete with `global_growth` for the same
events.

**The `chips` node picked up unusually rich, well-differentiated volume
this fortnight** (Apple/Samsung tariff threat 5-23, UAE AI campus deal
5-16, Nvidia's chip-control criticism 5-21, Nvidia earnings beat 5-28) —
four distinct chip-policy and chip-earnings events in two weeks, the
richest `chips` volume of the session, suggesting the node is well-
positioned as tariff/export-control policy increasingly targets
semiconductors specifically rather than goods broadly.

**New node-existence gaps confirmed this batch**: none beyond the
already-flagged backlog. The UK inflation/`boe_rate` pairing (above) is
now the single highest-priority gap in the entire backlog given two
consecutive batches of direct, unavoidable evidence.

### Batch #56 checkpoint (2025-05-29 to 2025-06-11)

Ledger now at 1144 event_keys / 711 days. This batch: 14 days, 65 events
(4.64/day). Magnitude mean/median: 0.228/0.2, essentially flat across
three consecutive batches now (0.217 → 0.224 → 0.228). Novelty
mean/median: 0.623/0.6. Novelty mix: 2 terminal/new at ≥0.9 (3.1% — the
US federal court blocking Trump's tariffs 5-29, and Operation Spiderweb
6-2), 20 intermediate 0.7-0.8 (30.8%), 42 material-dev 0.5 (64.6%), only
1 recap/color ≤0.4 (1.5%) — the second batch running with almost no
low-novelty filler. Node concentration: `geopolitical_tension` hit
**70.8%** (46/65) — a dramatic new session-high, up sharply from batch
#55's already-elevated 62.7% — `europe_growth` 15.4%, `global_growth`
4.6%, `fed_rate` 3.1%, `us_inflation` 3.1%, plus two singles. Type mix:
geopolitics 48, macro 10, monetary_policy 3, markets 3, energy 1.

**`geopolitical_tension` concentration crossed 70% for the first time
this session**, driven by an extraordinary density of simultaneous
major threads that would each individually justify a full batch's worth
of coverage: Operation Spiderweb and its aftermath (Kerch bridge strike,
Putin's nuclear-tinged retaliation threat, the actual Kyiv bombardment
revenge, Trump's 'let them fight' disengagement), the India-adjacent
Kashmir ceasefire holding, four separate European elections/government
crises in three weeks (Romania resolved, Poland's Nawrocki upset,
Portugal's Chega surge, the Dutch coalition collapsing), the US federal
court blocking and then un-blocking Trump's entire tariff regime, a
fresh US-China rupture-then-reconciliation cycle (violation accusations
→ Trump-Xi call → London framework deal), the Gaza catastrophe's
continued daily-casualty pattern culminating in direct Western sanctions
on sitting Israeli ministers, South Korea's presidential succession, and
two domestic-terror incidents tied to the conflict spilling into the US
(DC embassy shooting spillover continuing via the Boulder attack). This
is now unambiguous, overwhelming evidence — three consecutive batches
above 60%, this one nearly 71% — that a single node cannot adequately
carry this much qualitatively distinct information. The
`trade_policy`/`alliance_cohesion` split proposals should be treated as
effectively confirmed-necessary rather than merely evidenced; the open
question is no longer *whether* to split but *how* (this batch alone
suggests at least four candidate sub-categories: trade/tariff policy,
active interstate war, occupation/humanitarian-crisis diplomacy, and
domestic-election-driven alliance cohesion).

**The US federal trade court's tariff block (5-29) is this session's
cleanest illustration of institutional/judicial-branch risk as a
distinct node-worthy phenomenon**: a three-judge panel ruled Trump's
entire 'Liberation Day' tariff regime illegal, triggering an immediate
worldwide stock rally, only for an appeals court to pause the ruling
hours later — a legal-system shock with the same magnitude as a major
policy announcement, but originating from neither the executive nor a
foreign government. This event, along with the earlier Moody's
downgrade and the recurring Fed-independence friction, continues to
build the case that `dollar`/institutional-credibility dynamics deserve
first-class treatment distinct from the tariff-policy narrative itself.

**Operation Spiderweb (6-2) is arguably the single most novelty-dense
event of the entire session** — an 18-month-planned Ukrainian operation
destroying $7bn of Russian strategic bombers across four airbases,
correctly scored at 0.9 novelty given its scale and the multi-day
retaliation cycle it triggered (Kerch bridge strike, Putin's nuclear
rhetoric, the actual Kyiv bombardment). This is a good stress-test of
the terminal-resolution convention: the operation itself scored 0.9
(not 1.0, since the war continues and Russia's retaliation was still
unfolding), correctly reserving 1.0 for the US-China London framework
deal's eventual resolution rather than any single military operation
mid-war.

**New node-existence gaps confirmed this batch**: the UK
inflation/`boe_rate` pairing flagged in batch #55 did not recur with
new evidence this fortnight (a rare quiet spell for UK monetary data),
but a new gap emerged clearly: **`defense_spending`** continues to
accumulate evidence (NATO's 5%-of-GDP target discussions, Germany's
Lithuania deployment, UK's £2bn drone investment and 'battle-ready'
defence review, Denmark's US-airbase-access vote) without any node to
carry it, and the **AUKUS review** and Pentagon's 'America first'
alliance reassessment this batch add a concrete new data point to the
`alliance_cohesion` case specifically (alliances being actively
reviewed/downgraded, not just fragmenting via elections).

### Batch #57 checkpoint (2025-06-12 to 2025-06-25)

Ledger now at 1152 event_keys / 725 days. This batch: 14 days, 56 events
(4.0/day, the lowest density since batch #47, but with the highest mean
magnitude of the entire session). Magnitude mean/median: 0.254/0.25 —
a clear jump from the 0.217-0.228 range sustained across the previous
three batches, driven by the Israel-Iran-US war's cluster of 0.35-0.5
magnitude events. Novelty mean/median: 0.628/0.6. Novelty mix: 3
terminal/new at ≥0.9 (5.4% — Israel's opening strikes on Iran 6-13, the
US bombing of Iran's nuclear sites 6-22, and the ceasefire announcement
6-24), 14 intermediate 0.7-0.8 (25.0%), 37 material-dev 0.5 (66.1%), 2
recap/color ≤0.4 (3.6%). Node concentration: `geopolitical_tension`
67.9% (38/56) — still extremely elevated though down slightly from
batch #56's 70.8% — `europe_growth` 10.7%, `oil_supply` 10.7% (its
highest share this session by far), `dollar` 3.6%, plus four singles.
Type mix: geopolitics 41, markets 6, macro 4, energy 4, monetary_policy 1.

**This batch contains the sharpest, most self-contained war arc of the
entire session: the Israel-Iran-US conflict, opening and closing within
the batch's own 14 days.** Unlike the Ukraine-Russia war (now past
day 1,200, a slow-moving multi-year grind) or the Gaza occupation (a
grinding humanitarian catastrophe with no resolution in sight), this
thread had a clean beginning (Israel's surprise strikes, 6-13), a
clear escalation ladder (Iranian retaliation → Trump's unconditional-
surrender demand → the two-week deadline → direct US bombing of three
nuclear sites → Iran's retaliatory strike on a US base in Qatar), and
a clean if fragile end (Trump's ceasefire announcement, 6-24). This
is the best worked example this session of the novelty convention
handling an entire war's lifecycle within a single batch: three
separate 1.0 scores for three genuinely distinct terminal moments
(the war's start, the US's entry, and the war's end) rather than
over-using 1.0 for every escalatory step in between.

**`oil_supply` reached its highest concentration of the session
(10.7%)**, carrying a coherent five-event sub-thread: Brent crude's
initial spike (6-13) → Shell's Hormuz warning (6-19) → Iran's
parliamentary vote to close the strait (6-22) → Goldman's $100/barrel
warning (6-23) → oil paring back losses as the ceasefire took hold
(6-24). This is a clean illustration of the graph correctly using
`oil_supply` as a live, fast-moving geopolitical-risk gauge distinct
from the slower-moving `geopolitical_tension` node — worth highlighting
as a template for how physical-commodity nodes should absorb war-driven
supply-shock threads even when the underlying conflict is tagged
primarily to `geopolitical_tension`.

**The Fed-Trump confrontation continued as a recurring subplot**: the
Fed held rates in mid-June (6-18) directly defying Trump's demand for
cuts, with Powell publicly defending the hold days later (6-24) — a
second consecutive batch of overt central-bank-independence friction,
reinforcing the `fed_rate` node's role in capturing this distinct
institutional-conflict story rather than pure rate-path signal.

**New node-existence gaps confirmed this batch**: NATO's actual 5%-of-
GDP defence spending commitment (6-25, all members bar Spain's partial
opt-out) is the strongest possible evidence yet for the
`defense_spending` proposal — this is no longer a discussion or a
target under negotiation but a signed commitment with a 2035 deadline,
covered in this batch only as prose commentary since no node exists to
carry it. The domestic-political-violence thread (Minnesota lawmaker
assassination 6-14, LA National Guard/marines deployment, mass 'No
Kings' protests) continues to accumulate as evidence for a
`political_stability` node covering the US specifically, a category
distinct from the `geopolitical_tension` node's international-relations
focus.

### Batch #58 checkpoint (2025-06-26 to 2025-07-09)

Ledger now at 1161 event_keys / 739 days. This batch: 14 days, 60 events
(4.29/day). Magnitude mean/median: 0.227/0.2, in line with the
0.217-0.254 band sustained across the last four batches. Novelty
mean/median: 0.613/0.6. Novelty mix: 1 terminal/new at ≥0.9 (1.7% —
Trump's tax bill passing Congress, 7-3), 17 intermediate 0.7-0.8
(28.3%), 42 material-dev 0.5 (70.0%), 0 recap/color ≤0.4 — the first
batch this session with zero events scored at or below 0.4, meaning
literally every event captured carried at least material incremental
information. Node concentration: `geopolitical_tension` 68.3% (41/60),
`europe_growth` 16.7% (its second-highest share this session),
`us_inflation` 6.7%, `dollar` 3.3%, plus three singles. Type mix:
geopolitics 41, markets 7, macro 7, politics 3, monetary_policy 2.

**This batch confirms `geopolitical_tension` concentration has now
stabilized in a persistent 60-70%+ band across four consecutive
batches** (61.1% → 62.7% → 70.8% → 67.9% → 68.3%), rather than the
earlier session pattern of swinging between 40% and 70% depending on
the fortnight's news mix. This is a structural signal, not fortnight
noise: the current news cycle (Israel-Iran-US war aftermath, Ukraine's
continuing escalation, Gaza's grinding catastrophe, the US-EU/China/
Canada tariff multi-front) has simply produced a sustained high-tension
period across an entire quarter. This further strengthens rather than
undercuts the `trade_policy`/`alliance_cohesion` split case — a
persistent structural concentration is arguably worse for graph utility
than an occasional spike, since it means the single node has carried
the bulk of this session's information for over two months running.

**The US-China-Canada-EU tariff saga completed a full mini-cycle within
this batch**: Canada's talks ended over a tech tax (6-27) → Canada
'caved' and talks resumed within three days (6-30) → the EU raced
toward a framework deal (7-3) → Trump abruptly threatened new 17%
EU tariffs the very next day (7-4) → the 9 July deadline was delayed to
1 August with new unilateral letters (7-7) → sector-specific 200%/50%
tariffs on drugs and copper were threatened hours later (7-8). This
compressed, multi-reversal arc is one of the clearest illustrations
yet of why a single `geopolitical_tension` tag struggles to convey
the tariff thread's actual texture — the same event_key
(`us-2025-unilateral-tariff-letters`) had to carry escalation,
de-escalation, and re-escalation within a five-day span, each correctly
scored via polarity direction and novelty, but a dedicated
`trade_policy` node would let a reader track this sub-thread's net
trajectory far more legibly than scanning `geopolitical_tension` prose.

**The `europe_growth` node's second-highest concentration this session
(16.7%) reflects an unusually eventful UK fiscal fortnight**: the
Reeves bond-market scare and recovery (7-2/7-3), the OBR's 'unsustainable'
270%-of-GDP debt warning (7-8), the welfare bill's costly climbdown and
final passage (6-27 through 7-9), and the BoE's mortgage-rule loosening
(7-9) all landed inside two weeks — a genuinely rich UK domestic-policy
fortnight independent of the tariff/war narrative dominating
`geopolitical_tension`.

**Nvidia crossing $4tn in market value (7-9) is a good marker of the AI
capex thread's continued resilience** independent of the macro
turbulence — the `chips` node has now carried Nvidia's earnings beat
(5-28), the chip-export-control criticism (5-21), the Apple/Samsung
tariff threat (5-23), and now this historic valuation milestone,
confirming the node's value as a distinct running narrative.

**New node-existence gaps confirmed this batch**: none beyond the
already-flagged backlog. The recurring UK inflation/`boe_rate` pairing
did not resurface with new evidence this fortnight.

### Batch #59 checkpoint (2025-07-10 to 2025-07-23)

Ledger now at 1172 event_keys / 753 days. This batch: 14 days, 56 events
(4.0/day). Magnitude mean/median: 0.229/0.2, in line with the recent
range. Novelty mean/median: 0.589/0.6 — the lowest mean novelty of the
last five batches, with zero events scored ≥0.9 for the first time in
several batches (0 terminal/new, 13 intermediate 0.7-0.8 at 23.2%, 43
material-dev 0.5 at 76.8%). This absence of any terminal-novelty event
is itself informative: this fortnight was dense with genuine
developments (Fed-Powell conflict, tariff whiplash, Gaza's continuing
descent) but contained no single moment that resolved a major thread
outright — every thread continued rather than concluded. Node
concentration: `geopolitical_tension` 64.3% (36/56), `europe_growth`
16.1%, `fed_rate` 7.1% (its highest share this session by a wide
margin), `us_inflation` 3.6%, plus four singles. Type mix: geopolitics
37, markets 6, macro 6, monetary_policy 5, energy 2.

**The Fed-Trump confrontation escalated into this session's richest
`fed_rate` fortnight (7.1% concentration, up from a typical 1-3%)**:
Trump privately drafting a letter to fire Powell (7-16) → the White
House inspecting the Fed building over renovation costs (7-17) → Trump
calling Powell 'a numbskull' (7-18) → the Fed publicly rebutting the
renovation claims (7-21). This is a clean four-part escalation-and-
rebuttal arc within a single node, a good demonstration that `fed_rate`
can carry an institutional-conflict narrative distinct from pure
rate-path signal — worth flagging as a template for how the node
should be used when Fed independence itself (rather than the rate
decision) is the story.

**The tariff saga completed its most dramatic whiplash cycle of the
entire session within this single batch**: Trump's Brazil tariff
tied explicitly to Bolsonaro's trial (7-10) → 30% tariffs sprung on
EU and Mexico just as a framework deal seemed close (7-12) → drug/chip
tariffs threatened for 1 August (7-16) → and then, within the batch's
final two days, a sudden cascade of resolutions: the Japan deal at 15%
(7-23) immediately followed by the EU converging on the same 15% rate
(7-23) — a full escalation-to-resolution arc compressed into two
weeks. This is the clearest evidence yet that `geopolitical_tension`
alone cannot convey the *shape* of the tariff story (whiplash followed
by sudden multilateral convergence); a dedicated `trade_policy` node
would let a reader see this pattern (multiple simultaneous
bilateral tracks converging on a similar ~15% baseline rate) far more
readily than scanning prose across a dozen entries.

**Gaza's humanitarian catastrophe reached new institutional and
numerical peaks this batch**: single-day aid-point death tolls climbed
from 32 (7-19) to 93 (7-20) to 72 (7-22), the WHO explicitly declared
'man-made mass starvation' (7-23), and Israel opened a new front by
assaulting Deir al-Balah, a previously relatively unscathed
humanitarian hub (7-21). The absence of any terminal-novelty score
for Gaza this batch is itself a finding: there was no single moment of
resolution, only a continuously worsening baseline — a graph-modeling
challenge, since novelty scoring rewards *change* but a steadily
worsening humanitarian catastrophe without a discrete breaking point
risks being under-weighted by the convention as each new atrocity
becomes marginally less 'novel' even as the absolute scale grows.
Worth flagging as a possible refinement: consider whether sustained
monotonic worsening of a humanitarian metric (aggregate death toll,
WHO/UN institutional language escalation) deserves its own novelty
treatment distinct from single-incident news events.

**New node-existence gaps confirmed this batch**: none beyond the
backlog. The UK inflation/`boe_rate` gap recurred once more (3.6%
inflation, 7-16) but was not tagged, per established discipline.

### Batch #60 checkpoint (2025-07-24 to 2025-08-06)

Ledger now at 1186 event_keys / 767 days. This batch: 14 days, 66
events (4.71/day) — the highest events/day rate of the last several
batches, driven by an unusually dense final week (Aug 1 tariff
implementation, Fed-Trump escalation to "seize control," India tariff
escalation, Gaza occupation-plan reports). Magnitude mean/median:
0.242/0.25, in line with the recent range. Novelty mean: 0.609 — the
highest of the last several batches — with only 2 terminal (≥0.9,
3.0%) events (the Aug-1 sweeping tariff implementation and, at the
tail, none reaching a full 1.0), 19 intermediate phase-change (0.7-0.8,
28.8%), 42 material-development (0.5, 63.6%), and 3 recap/color (≤0.4,
4.5%). Node concentration: `geopolitical_tension` 69.7% (46/66) — the
highest concentration recorded this session, continuing and extending
the six-batch structural plateau (61.1% → 62.7% → 70.8% → 67.9% →
68.3% → 64.3% → **69.7%**) — `europe_growth` 12.1%, `global_growth`
7.6%, `fed_rate` 4.5%, plus four singles (`dollar`, `chips`,
`us_inflation`, `oil_supply`). Type mix: geopolitics 46 (69.7%), markets
9 (13.6%), macro 6 (9.1%), monetary_policy 5 (7.6%).

**The tariff-implementation saga reached its terminal moment this
batch**: 1 August's sweeping tariffs (10-41% on dozens of countries)
converted 15 months of threats, letters, and bilateral deals into an
actually-enforced global regime — scored novelty 0.9, the batch's
single clearest terminal-resolution event. New fronts opened
immediately in its wake: Canada raised to 35% (8-1), Switzerland hit
with a shock 39% rate tied to a single presidential phone call (8-4),
a new pharma-tariff threat sent European drug shares to a four-month
low (8-6), and India's Russian-oil penalty escalated from 25% toward a
threatened 50% (8-6) — confirming the `trade_policy` split-node
proposal's evidentiary case has moved from "recommended" to
effectively unavoidable: a single `geopolitical_tension` tag is now
absorbing at least five simultaneous, independently-evolving bilateral
tariff tracks in addition to three active wars/conflicts, at nearly
70% concentration.

**A new escalation vector emerged and immediately institutionalized**:
a Belarus-launched explosive-carrying drone crossed into Lithuanian
(NATO) airspace (8-5), prompting calls for a formal Nato response
within 24 hours (8-6) — assigned its own event_key
(`russia-2025-nato-airspace-incursion`) since it is geographically and
diplomatically distinct from the Ukraine war proper, representing the
first direct NATO-territory incident tracked this session. This is a
good stress test of the `alliance_cohesion` split proposal: the
story's core question (will Nato respond collectively, and how) is
exactly the kind of thread a dedicated alliance-cohesion node would
let a reader follow independent of the Ukraine war's own event_key.

**The Fed-Trump conflict continued its arc but decelerated in intensity
this batch** (4.5% concentration, down from 7.1% last batch): Trump's
"seize control" escalation (8-2) was the batch's sole `fed_rate` peak;
no new institutional-conflict developments (no fresh Powell meetings,
no further renovation-cost disputes) landed in the remaining days,
suggesting this sub-thread may be entering a lull rather than a
resolution — worth continued tracking for the actual September/October
Fed decision and any further chair-succession news.

**Gaza's trajectory took a sharper turn than in prior batches**: rather
than only continuing to worsen along the same axes (death toll, aid-
site violence), this batch introduced a genuine scope-escalation
signal — Netanyahu reportedly leaning toward full occupation of Gaza
(8-5, novelty 0.7), followed a day later by concrete forced-displacement
orders (8-6, novelty 0.55) — with Israeli military leaders reportedly
opposing the plan, introducing a notable internal-dissent angle absent
from earlier batches. This is scored as a genuine phase-change (not
mere recap) since it represents an actual proposed change in the war's
scope, distinct from the continuously-worsening humanitarian metrics
flagged as a novelty-convention stress test in the previous two
batches.

**New node-existence gaps confirmed this batch**: none beyond the
backlog. The UK inflation/`boe_rate` pairing recurred twice more (UK
services-sector order collapse 8-5, construction activity's steepest
fall since Covid 8-6, both tagged instead to `europe_growth` ahead of
Thursday's BoE decision) — now the single most frequently recurring
gap-evidence item across the last four consecutive batches, reinforcing
its position as the highest-priority node-pair addition for the next
implementation pass.

### Batch #61 checkpoint (2025-08-07 to 2025-08-20)

Ledger now at 1200 event_keys / 781 days. This batch: 14 days, 60
events (4.29/day). Magnitude mean/median: 0.266/0.25, the highest
magnitude mean of the last several batches, reflecting an unusually
high density of genuinely consequential events (a BoE rate decision,
a Trump-Putin summit, a Washington war-summit, a Gaza ceasefire
proposal). Novelty mean: 0.605, in line with the recent range, with
1 terminal event (1.7%, the Alaska summit's no-deal outcome), 20
intermediate phase-change (33.3%), 36 material-development (60.0%),
and 3 recap/color (5.0%). Node concentration: `geopolitical_tension`
64.5% (40/62) — continuing the six-batch structural plateau at a
still-elevated level, though modestly below batch #60's 69.7% peak —
`chips` 11.3% (its highest share this session by a wide margin),
`europe_growth` 9.7%, `gold_price` 3.2%, `global_growth` 3.2%,
`us_inflation` 3.2%, `fed_rate` 3.2%, `dollar` 1.6%. Type mix:
geopolitics 42 (70.0%), markets 8 (13.3%), macro 7 (11.7%),
monetary_policy 3 (5.0%).

**This batch contained the session's first genuine, scheduled,
head-of-state summit sequence on Ukraine**: the Trump-Putin Alaska
summit (8-15/8-16) ended with no ceasefire, no deal, and no sanctions
— scored as this batch's sole terminal-novelty event (0.85) since it
is the clean resolution of a multi-day anticipation arc, even though
the resolution itself was "nothing happened." This was immediately
followed by the Washington meeting (8-18) where Zelenskyy, flanked by
European leaders as diplomatic "bodyguards", emerged without incident
but with Trump's substantive concessions (ruling out Nato membership
and Crimea's return) left intact. This two-summit sequence is a strong
argument for the `alliance_cohesion` split-node proposal: the story of
whether Europe can keep Trump from freelancing a deal with Putin is
distinct from, and arguably more consequential for markets than, the
Ukraine war's own battlefield event_key, yet both are currently forced
into the same `geopolitical_tension` tag.

**`chips` reached its highest concentration of the session (11.3%,
7 events)**, driven by a genuinely new sub-narrative: the Nvidia/AMD
15%-revenue-share deal with the US government to resume China chip
sales (8-11), Trump floating downgraded-Blackwell sales to China
(8-12), the "dangerous precedent" analysis of export tariffs (8-17),
Intel's CEO-resignation pressure and chip-tariff threat (8-7), and two
separate concrete capital-injection stories — Apple's $100bn US
manufacturing pledge (8-7) and Intel's SoftBank $2bn lifeline plus
reported US government equity-stake interest (8-15, 8-19). This is the
richest `chips` fortnight this session and suggests the node is now
carrying a distinct "US industrial policy meets chip geopolitics"
narrative thread worth watching independently of the Ukraine/tariff
storylines.

**The Gaza thread produced this batch's most consequential swing**:
from Netanyahu's cabinet approving the Gaza City occupation plan
(8-8, novelty 0.85) and Israel calling up 60,000 reservists (8-20),
to Hamas's acceptance of a 60-day ceasefire-and-hostage-exchange
proposal (8-18, novelty 0.8) — a genuine good-news development, the
first in this thread since it began, scored with negative polarity to
reflect de-escalation. The juxtaposition of Israel simultaneously
mobilizing reservists for offensive action *and* awaiting its own
response deadline on the ceasefire it has not yet accepted (due
Friday 8-22, beyond this batch's window) is a clean illustration of
why this event_key has needed dual-tracked, sometimes contradictory
entries within the same week — a real feature of the underlying
situation, not a tagging inconsistency.

**The Fed-Trump conflict escalated again after last batch's lull**:
from Bessent's explicit half-point rate-cut demand (8-13) to Trump's
attempt to remove Fed governor Lisa Cook via an unrelated mortgage-
fraud allegation (8-20) — the first attack targeting a specific sitting
governor (rather than Powell personally) with a concrete legal pretext,
a meaningfully different and more legally-consequential escalation
vector than the "numbskull"-style rhetoric from earlier batches.

**New node-existence gaps confirmed this batch**: the UK inflation gap
recurred with its sharpest evidence yet — UK inflation jumping to 3.8%
in July (8-20), explicitly described as reducing the likelihood of
further BoE cuts — landing less than two weeks after the BoE's own
split rate-cut decision (8-7) that this batch also had to tag to
`europe_growth` for lack of a dedicated monetary-policy node. This
batch alone produced four separate UK-monetary-policy-adjacent events
(the rate decision itself, hiring intentions, services-sector orders,
and the inflation report) all forced into the same generic growth
node, now the single strongest evidentiary case across the whole
session for prioritizing the `boe_rate`/`uk_inflation` node pair in
the next implementation pass.

### Batch #62 checkpoint (2025-08-21 to 2025-09-03)

Ledger now at 1219 event_keys / 795 days. This batch: 14 days, 58
events (4.14/day). Magnitude mean/median: 0.267/0.25, essentially
unchanged from batch #61's 0.266/0.25 — the second consecutive batch
at this elevated magnitude level. Novelty mean: 0.603, in line with
the recent range, though for the first time this session **zero
events scored at recap/color (≤0.4) or terminal (≥0.9)** — every
single event fell in the intermediate 0.5-0.8 band (42 material-dev
at 0.5, 72.4%; 16 phase-change at 0.7-0.8, 27.6%). This is itself a
finding: this fortnight was dense with genuine, ongoing developments
(Fed-Cook legal fight, Gaza City offensive, tariff-court ruling,
gilt-yield rout) but each individual event was a step in a longer
unresolved arc rather than either pure color or a clean resolution —
worth flagging as evidence the novelty distribution can meaningfully
shift shape batch-to-batch, not just its mean. Node concentration:
`geopolitical_tension` 65.5% (38/58) — continuing the plateau —
`europe_growth` 15.5% (its second-highest share this session),
`fed_rate` 10.3% (the richest `fed_rate` fortnight yet, surpassing
batch #60's 7.1%), `chips` 3.4%, plus three singles (`oil_supply`,
`global_growth`, `gold_price`). Type mix: geopolitics 42 (72.4%),
monetary_policy 7 (12.1%), macro 6 (10.3%), markets 3 (5.2%) — notably
zero pure `markets`-type events beyond three, the lowest markets
share this session, reflecting how thoroughly geopolitics dominated
the fortnight's genuinely new information.

**The Fed's independence crisis escalated from rhetoric to an actual
constitutional-style test this batch**: Trump moved from urging Cook
to resign (8-21), to officially announcing her firing (8-26), to Cook
suing the administration (8-28), to the ECB's Lagarde calling it a
'serious danger' to the world economy (9-1) — a clean four-step
escalation ladder that makes `fed_rate` this batch's second-richest
node purely on an institutional-independence story rather than any
actual rate decision. This is the strongest evidence yet that
`fed_rate` is carrying two genuinely distinct narratives (the rate-path
signal itself, and the independence-of-the-institution fight) that
happen to share a node — worth flagging as a possible future split
question, though less urgent than the `trade_policy`/`uk_inflation`
backlog since both sub-stories at least share the same underlying
actor (the Fed) and directional logic (dovish pressure correlates with
anti-independence pressure).

**The tariff saga hit its most significant legal setback of the entire
session**: a federal appeals court ruled most of Trump's global
tariffs illegal (8-30), a genuine, if not-yet-final, blow to the
14-month tariff-implementation arc that had only just reached its
'terminal' 1 August implementation moment in batch #60. This is a
good illustration of why 'terminal' novelty scores should be
understood as terminal-for-that-specific-thread-shape rather than
permanent: the same underlying event_key can and did re-escalate to
a new phase-change moment weeks after its prior 'terminal' resolution,
via an entirely different mechanism (judicial rather than diplomatic
or economic).

**A visually and symbolically dense non-Western-alignment thread
crystallized this batch**: India's Modi meeting Xi and Putin in China
(8-29/8-31), the Shanghai Cooperation Organisation summit gathering
20+ leaders (8-31/9-1), and finally the Beijing Victory Day military
parade with Xi, Putin and Kim together (9-3) — three escalating steps
culminating in what commentary universally described as a deliberate
visual rebuke to the West. Assigned its own event_key
(`india-2025-china-russia-pivot`) distinct from the Ukraine war proper,
since its core throughline (a hardening multipolar bloc responding to
US tariff/sanctions pressure) is a different story than the war's own
battlefield or diplomatic developments, even though Putin is a shared
actor. This is a strong argument that the `alliance_cohesion` proposal
should explicitly cover *non-Western* alliance formation, not only
Nato/EU cohesion — the gap cuts both ways.

**UK fiscal stress produced its most acute single data point of the
session**: 30-year gilt yields hit their highest level since 1998
(9-2) amid an explicitly-labeled 'worldwide bond market rout', before
BoE governor Bailey partially talked the panic back down the very next
day (9-3) — a clean two-day spike-and-partial-reversal pattern. Combined
with the French PM Bayrou confidence-vote crisis (8-25/8-26) and the
UK food-inflation/energy-price/gilt-yield cluster, this batch produced
the richest concentration of European fiscal/monetary events (11 of
58 events, spanning `europe_growth` and `fed_rate`-adjacent commentary)
of the entire session — none of which had a natural home beyond the
generic `europe_growth` node, again reinforcing the `boe_rate`/
`uk_inflation` gap's priority, and newly suggesting a possible
`france_politics` or broader `eu_fiscal_stress` gap given Bayrou's
crisis had no node-level home at all this batch.

**New node-existence gaps confirmed this batch**: none beyond the
backlog, though the Bayrou/French-fiscal-crisis events (8-25, 8-26,
9-3) are the first this session forced to use ad hoc event_keys
without any node beyond generic `europe_growth`, despite France being
a distinct economy from the UK — worth flagging as a possible argument
for a dedicated `france_growth` or pan-eurozone-politics node if French
fiscal/political events continue recurring at this rate.

### Batch #63 checkpoint (2025-09-04 to 2025-09-17)

Ledger now at 1232 event_keys / 809 days. This batch: 14 days, 58
events (4.14/day). Magnitude mean/median: 0.283/0.3 — the highest of
the entire session, reflecting a fortnight with an unusually high
density of genuinely consequential, high-magnitude events (a NATO-
territory drone incursion, a Fed rate cut, a Gaza City ground
invasion, a UN genocide finding). Novelty mean: 0.639, also among the
highest this session, with 1 terminal event (1.7%), 22 intermediate
phase-change (37.9% — the highest phase-change share this session),
and 35 material-development (60.3%), and for the first time in three
batches a nonzero terminal count. Node concentration:
`geopolitical_tension` 64.4% (38/59), continuing the plateau,
`europe_growth` 13.6%, `global_growth` 8.5%, `fed_rate` 6.8%,
`us_inflation` 3.4%, plus two singles (`china_growth`, `chips`). Type
mix: geopolitics 40 (69.0%), macro 10 (17.2%), monetary_policy 5
(8.6%), markets 3 (5.2%).

**This batch contained the session's most significant single security
escalation to date**: Russian drones entered Polish airspace and were
shot down by Nato member forces for the first time in the war (9-10),
prompting Tusk's 'closer to military conflict than any time since
WW2' warning, an emergency UN Security Council meeting, a new Nato air-
defence mission with UK Typhoons flying missions from RAF Lincolnshire
(9-15), and — critically — the incursion pattern *repeating* in Romania
(9-14) and being explicitly characterized by Polish officials as a
deliberate 'Kremlin test on Nato' (9-15) rather than a one-off
accident. This event_key (`russia-2025-nato-airspace-incursion`)
carried seven events across the batch, a genuinely distinct escalation
ladder from the Ukraine war's own event_key that this session's
tagging discipline correctly kept separate throughout.

**The Fed-independence saga reached its two cleanest terminal
resolutions of the entire session in immediate succession**: a court
blocked Trump's attempted firing of governor Lisa Cook (9-16), and the
Fed then cut rates by a quarter point the very next day (9-17) — the
actual FOMC decision this multi-month escalation ladder (Bessent's
demand, Cook's firing, DOJ criminal inquiry, ECB's Lagarde warning)
had been building toward. Both scored high novelty (0.85) as clean
terminal events, a rare case this batch of the novelty distribution's
lone terminal-tier score materializing exactly where expected.

**Gaza's occupation thread also reached its terminal moment this
batch**: after weeks of cabinet approvals, reservist call-ups, and
evacuation ultimatums, Israel's ground offensive into Gaza City
actually began (9-16, novelty 0.85), landing the same day as a UN
commission of inquiry's formal genocide finding — a substantially
stronger institutional determination than the earlier academic
scholars' resolution (batch #62), now explicitly citing 'direct
evidence of genocidal intent' and accusing Netanyahu personally of
incitement. The Israeli strike on Hamas leadership in Doha, Qatar
(9-9) — extending the war onto the soil of a Gulf mediator state for
the first time — was this batch's other clear phase-change moment,
triggering a cascade of diplomatic fallout (Gulf emergency summit,
EU calls to suspend Israel free-trade, Rubio's damage-control trip)
that ran through the rest of the fortnight.

**New node-existence gaps confirmed this batch**: the France/Bayrou
fiscal-political crisis concluded its arc (PM ousted 9-8, Lecornu
appointed successor 9-9), reinforcing last batch's flag that French
political-fiscal events have no node-level home beyond generic
`europe_growth`. Additionally, this batch introduced the first
`china_growth`-tagged event of the session (Chinese economic slowdown,
9-15) confirming that node exists and is usable — worth noting since
prior batches had described China-related growth events as lacking a
home; the node was simply underused, not absent.

**Note on methodology**: none of the proposed node ids above (`political_stability`,
`boe_rate`, `uk_banks`, `travel_leisure`, `offshore_wind`,
`telecom_equipment`, `freight_logistics`) are used in the actual
`events/*.json` output during continued digestion — they don't exist in
`data/knowledge_graph.json` yet, and tagging live events with invalid ids
would get them silently dropped by the validator per the brief's own
warning (§7: "Wrong/unknown ids are dropped by the validator — wasted
signal"). Continued digestion uses only the 85 currently-valid ids; this
log exists purely to accumulate recurrence evidence for whoever implements
the seed.py changes.
