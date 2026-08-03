# Digestion Status & Continuation Orders

*Rewritten 2026-07-31 (night) — all six marching orders below are now
COMPLETE. Read together with `docs/data-pipeline/SONNET_DIGEST_BRIEF.md` (**v1.4** — the
operating instructions) and `data/digest_v2/README.md` (workspace layout +
retention rules).*

## Current state (verified 2026-07-31 night)

- **Full corpus digested and merged, 2023-07-01 → 2026-07-30 (1,126 days,
  5,052 events), all under v1.4 discipline.** `events/` (1,124 days) is the
  untouched original corpus (retention rule); `events_amend_v14/` (608
  files) holds the append-only node-gap/asset-fix amendments; the two are
  folded together by `_merge_amendments.py` into `ledger.jsonl` (2,056
  event_keys) and `../news_impulses_v2.jsonl` (1,126 days). Re-run
  `_merge_amendments.py` any time the amendment set changes — it is
  idempotent and safe to re-run.
- `validation_report.md` has the full distribution audit: magnitude median
  0.30, only 3 events ≥0.8 across 3 years, 100% `ts` coverage, all 42
  previously-zero nodes now populated (`uk_banks` 96, `commercial_aerospace`
  76, `financial_fraud` 94, etc. — see the report for the full table).
- The 91 illegally asset-tagged events (`tsla`/`btc`/`nvda`/`aapl`/`msft`/
  `crwd`/`tsmc`/`arm`) are fixed: 75 remapped to a correct §7 node, 16
  dropped (no legal origin, single-stock-only story).
- Guardian archive: gapless through 2026-07-30. Live multi-source archive
  (`../news_archive_live.jsonl`) covers 2026-07-30 onward; 2026-07-29 was
  digested from Guardian, 2026-07-30 from the live archive per §2.2.
- **YouTube dossier pass complete**: 172/173 nodes have a static dossier
  in `youtube_dossiers/` (one node had a count edge-case, worth a spot
  check). No events were emitted — enrichment only, per the hard rule.

## Known residual items for human review (not auto-applied)

- **`proposed_edges`** surfaced across the amendment pass and the YouTube
  dossiers (e.g. `power_demand→uranium_price`, `ai_datacenter→copper_price`,
  `bond_stress→ai_capex_cycle`, `robotics→power_demand`,
  `china_government→gold_price`, `berkshire→googl`) — these are proposals
  only (capped confidence, `provenance: llm` per brief §12), not applied to
  the graph. Review before accepting.
- **`integrity`/`integrity_patterns`** flags from both passes (circular AI
  financing, China's paper-gold market, DRAM antitrust signaling,
  memecoin-as-bribery-vehicle, CATL/Tesla supply-exclusivity risk, etc.) —
  same: flagged, not auto-applied to any asset veto.
- A handful of amendment agents used slightly different `event_key` slugs
  for the same real-world story (only one alias — Thames Water — was
  reconciled in the merge script's `ALIASES` dict). Worth a broader
  near-duplicate sweep of `ledger.jsonl` before trainer use.
- The node-gap amendment pass was a parallel best-effort scan, not a second
  full line-by-line read of all 1,124 days — high-recall on material misses,
  not an exhaustiveness guarantee.
- `news_impulses_v2.jsonl`'s aggregation formula (`polarity * magnitude *
  novelty * confidence * (1-manipulation_likelihood)`, summed per node per
  day) is a reasonable first cut consistent with the brief's fields, but
  not itself specified by the brief — downstream code may want a different
  formula.

## CRYPTO BACKFILL CAMPAIGN — WAVE 1 + WAVE 2 COMPLETE (2026-08-01)

`crypto_backfill/` staged 1,417 dated day-files (2022-05 → 2026-07-31,
9,620 items) from the GDELT crypto sweep, the Wu Blockchain newsletter
archive, and Binance/Upbit listing announcements.

**Wave 1** (8 parallel agents, date-range chunks, 1,089 in-window days
2023-07-01 → 2026-07-31): 479 day-files, 927 events + 5 amendments.

**Wave 2** (`crypto_backfill/WAVE2_BACKLOG.md`, 12 parallel agents — 6 on
the dense 2025-12 → 2026-06 bear-era GDELT zone, 6 batching the thin
2023-07 → 2025-11 Wu-Blockchain-only zone; 607 backlog days, 7,299
headlines): dense zone alone produced ~920 events across 129 days;
thin zone mostly confirmed "nothing new" (as expected for single-headline
days) with occasional gap-fills. Combined `events_amend_crypto/` now has
**630 day-files, 1,957 events + 12 amendments** (cumulative across both
waves — Wave 2 agents checked for and extended Wave-1 files rather than
overwriting).

`_merge_amendments.py` re-run after each wave, both clean:
- Post-Wave-1: base 4,483 → 5,088 events.
- Post-Wave-2 (current): base 4,483 → **7,036 total events** (2,574 new
  events, 365 `add_nodes`, 91 `replace_nodes`, 171 `add_deals`, 21 dropped
  for no legal origin; 5 amendments skipped — referenced event_keys not
  in the ledger, e.g. `crypto-2025-bybit-hack`, `us-venezuela-2025-drug-boat-strike`
  — sample logged in the run output, worth a look if those stories matter).
  Ledger rebuilt to **3,753 event_keys**; `news_impulses_v2.jsonl`
  regenerated for all 1,128 days (989 noise events excluded at the 0.35
  threshold — note this jumped a lot from Wave 1's 37, consistent with
  many more low-confidence GDELT-sourced events now in the pool).
  `validation_report.md` rewritten — **not yet reviewed**; check it
  before trusting the new crypto-node distribution, especially given the
  much larger noise-exclusion count.

One-off fixes applied during merges (schema drift from some sub-agents,
not a script bug): 25 files missing the `amendments` key after Wave 1,
5 more after Wave 2 — all backfilled to `[]` in place before merging.

**Not yet done, still open**: the `_stage.py` re-run to pick up further
GDELT crawler progress (paused at 268/1,127 days when Wave 2 was staged
2026-08-01) — regenerate `WAVE2_BACKLOG.md` and run a Wave 3 if the
crawler advanced materially. Final trainer run with exit-form crypto
rounds is still pending (next step below).

## What REMAINS (next steps, none of them Sonnet's job per the brief)

- **Live daily continuation**: from 2026-07-31 onward, run the same §2.2
  live-archive protocol day by day as new dates become eligible. Live
  inputs now come from THREE files: `../news_archive_live.jsonl` (RSS,
  ~44 feeds incl. crypto press added 2026-07-31),
  `../news_archive_guardian.jsonl` (still appending), and
  `../news_archive_x.jsonl` — curated-X captures from browser sessions
  reading the user's crypto Following feed (same day-record schema;
  `source` is `x.com/<handle>`, per-handle trust priors live in
  `events.py`; timestamps are snowflake-exact where a status id was
  captured, capture-relative otherwise). X capture protocol: single tab,
  human pacing, chronological Following/list feed, ads and pure-promo
  posts skipped, sentiment posts kept but labeled as gauges in their
  summaries — the digester treats them per §2.2's StockTwits rule.
- **Human review** of the proposed_edges/integrity backlog above before
  anything touches the graph.
- **Event-study calibration (B2) and trainer rounds** — see
  `docs/data-pipeline/DIGESTION_SPEC.md` §B6.
- **Edge re-weighting from data** — its own gated round
  (`DIGESTION_SPEC.md` B3/R21-learned-edges), code-side, not digester work.

## History (kept for the record)

- v1.2 redo of days 2023-07-01 → 2023-08-09 completed 2026-07-29 (204
  events; superseded by the v1.4 amendment pass above, which layered
  additional node coverage on top without touching the originals).
- Full backfill through 2026-07-28 completed by 9 parallel agents, merged
  in commit `658444d` (`docs/archive/NODE_GRAPH_GAP_ANALYSIS.md`).
- 2026-07-31: v1.4 node-gap amendment pass (8 parallel date-chunk agents),
  asset-tag fix, sequential 2026-07-29/30 digestion, merge/rebuild, and the
  full YouTube dossier pass — all completed in one session.

## Retention guarantee (permanent)

Raw news archives are **never deleted or overwritten**:
`news_archive_guardian.jsonl` (bodies+ts), the `.bak` headlines-only pull,
GDELT/wiki archives, and every `events*/` generation (including
`events_amend_v14/`) are all kept — we must always be able to re-run
digestion from scratch.
