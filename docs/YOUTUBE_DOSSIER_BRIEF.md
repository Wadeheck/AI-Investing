# Operational Briefing — YouTube Transcript Dossier Pass (Claude Sonnet 5)

*Version 1.0, 2026-07-31. Companion to `docs/SONNET_DIGEST_BRIEF.md` (v1.4).
This is a SEPARATE, ONE-TIME pass over `data/youtube_transcripts/` — it is
NOT news digestion, and its output is never events or impulses.*

## Why this pass exists — and the one hard rule

The transcript corpus (see `data/youtube_transcripts/README.md`) is 158
manually-curated, cleaned transcripts of reputable financial-media videos,
one file per knowledge-graph node. It is analysis and mechanism knowledge
spanning 2023–2026 — not a chronological news stream.

**The hard rule: transcripts must NEVER enter the event pipeline.** The
event digester's entire value rests on temporal integrity — the web
experiences history strictly in order. A 2024 video digested as if it were
news would inject hindsight into the trajectory. Therefore this pass emits
only STATIC graph enrichment, reviewed by a human before anything is
applied. No `events`, no `magnitude`, no `novelty`, no ledger interaction.

## Input

One node file per call: `data/youtube_transcripts/<node_id>.json`, plus the
node's current definition from `data/knowledge_graph.json` (id, type, label,
aliases) and its existing edge list (src/dst/sign/weight of every edge
touching the node). Skip `found: false` files (return an empty dossier).

## Dating discipline

Every video carries `published_date` (`YYYY-MM-DD`, the real upload date).
Treat the transcript as a snapshot of what was believed AS OF that date:

- Prefix every extracted claim with its vintage: `as_of: <published_date>`.
- A 2023 video's numbers (capacity, market share, policy stance) may be
  superseded — mark any quantitative claim older than ~12 months
  `stale_risk: true` rather than asserting it as current.
- Never emit a claim about "now" from an old video. Mechanisms age well;
  numbers do not. Extract the mechanism, date the number.
- If `notes` says the transcript was reconstructed from chapters/description,
  cap every claim's confidence at 0.5.

## Output — one JSON dossier per node, nothing else

```json
{
  "node_id": "uranium_price",
  "as_of": "2025-03-14",
  "mechanism_notes": [
    {"claim": "utilities contract 2-3y ahead; spot is thin — price spikes are inventory-driven",
     "as_of": "2025-03-14", "confidence": 0.8, "stale_risk": false}
  ],
  "proposed_edges": [
    {"src": "power_demand", "dst": "uranium_price", "type": "influences",
     "sign": 1, "weight": 0.3,
     "why": "datacenter load driving nuclear restarts (video: utility panel)",
     "as_of": "2025-03-14"}
  ],
  "alias_suggestions": ["U3O8", "yellowcake"],
  "integrity_patterns": [
    {"pattern": "producers reporting 'contracted volumes' that are options, not commitments",
     "as_of": "2025-03-14"}
  ],
  "contradicts_graph": [
    {"edge": "oil_price -> uranium_price", "video_says": "no linkage since 2011",
     "as_of": "2025-03-14"}
  ]
}
```

Field discipline:

- `mechanism_notes` — HOW the node's economics work (supply chains, lags,
  who sets marginal price, what historically breaks it). 2–6 per node max;
  only what a graph engineer could act on. No summaries of the video.
- `proposed_edges` — same schema and the same rarity bar as the digest
  brief §12: only mechanisms the CURRENT graph (check the provided edge
  list first) does not already encode, expressible entirely in existing
  node ids. Expect ZERO for most nodes.
- `alias_suggestions` — tickers, industry jargon, non-English names the
  node's alias list lacks (aliases drive CJK/entity matching downstream).
- `integrity_patterns` — recurring manipulation/fraud mechanisms the video
  describes for this sector (digest brief §11b costumes). Patterns, not
  accusations against named companies.
- `contradicts_graph` — where the video's mechanism disagrees with an
  existing edge's sign or weight. Report; never propose a fix yourself.

Empty arrays are honest and expected. A thin dossier from a thin video is
correct output; padding is corruption.

## Coverage note for the operator (not the model)

The corpus covers the pre-v20 graph (173 nodes). 42 taggable seed-v20 nodes
and 91 new assets have no transcript yet — the sourcing shopping list is in
the corpus README workflow; highest-value gaps are the fraud-family factors
(`financial_engineering`, `custody_risk`, `market_intervention`,
`currency_peg_stress`, `financial_fraud`) and the BOM tiers, since those
carry the most mechanism knowledge per transcript.

## Grading

Human review of every dossier before anything touches the graph. Spot-check
standard: every claim traceable to the transcript text, every `as_of`
matching the video's `published_date`, zero events emitted. A dossier that
invents a claim not in the transcript fails the whole pass for that node.
