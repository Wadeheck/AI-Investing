# Crypto-backfill digestion campaign — orders for the Sonnet digester

*Created 2026-08-01. Companion to `docs/SONNET_DIGEST_BRIEF.md` (v1.4 —
every rule there applies unchanged; this file only adds campaign-specific
protocol, exactly as the node-gap amendment pass did). Operator context in
`../STATUS.md`.*

## What this campaign is

The 1,124-day historical corpus was digested from the Guardian — thin on
crypto. This campaign layers CRYPTO news history on top as APPEND-ONLY
AMENDMENTS. The staged input lives in `days/YYYY-MM-DD.jsonl` (one dated
headline per line: title, summary, exact-or-noon UTC `ts`, source, url),
built by `_stage.py` from three archives: the GDELT crypto sweep, the Wu
Blockchain newsletter archive, and Binance/Upbit listing announcements.
`_stage.py` is idempotent — re-run it as the GDELT crawler fills more days,
then digest the newly staged days.

## Protocol (per digested day)

1. **Window**: digest only days `2023-07-01` and later (the corpus window).
   Staged files before that date are historical context — SKIP them.
2. **Amendment discipline** (the anti-double-count rule, §12-grade
   importance): each day you process ALREADY has events from the Guardian
   corpus. You will be shown that day's existing events alongside the
   staged headlines. Emit:
   - a NEW event only for a story the existing events do not cover;
   - an `{"amend": "add_nodes", "event_key": ..., "nodes": [...]}` record
     when a staged story shows an EXISTING event also belongs on a crypto
     node it lacks;
   - nothing at all when the story is already covered correctly.
3. **Output**: `../events_amend_crypto/YYYY-MM-DD.json` —
   `{"events": [...], "amendments": [...]}`. Never touch `../events/`.
4. **Chunked parallelism is allowed** (date-range chunks, as in previous
   campaigns): novelty/event_key discipline holds within your chunk; the
   merge script reconciles across chunks. Chain to the provided ledger
   extract where a key exists; otherwise mint per the brief §9 and keep
   slugs reproducible.
5. **Temporal integrity is absolute** (brief §3): you live on the day you
   are digesting. GDELT headlines carry their real publication `ts`;
   Wu newsletter items are WEEKLY DIGESTS — treat each item as coverage
   (novelty 0.5/0.2 if the underlying event is ledgered or plainly older
   than the post date), never as a fresh event just because the post is.

## Per-source guidance (extends brief §2.2 — same spirit)

| Source class | Treatment |
|---|---|
| GDELT domains (many small crypto sites) | Headline-only, mixed quality. Confidence ≤ 0.6 unless the domain is a known outlet; promotional/price-prediction headlines are §4 fluff — skip silently. Whale-movement and "market cap reaches X" wire noise: skip unless genuinely material |
| `wublock.substack.com` | Curated weekly digest of real events (trust 0.6). Each bullet may be its own event if material and uncovered; date it by the underlying event when the text makes that clear, else by post date with confidence ≤ 0.6 |
| `binance.com/announcements`, `upbit.com/notices` | PRIMARY-SOURCE exchange actions. A listing/delisting of a graph asset is a real event: type `market_flow`, origin node = the listed asset's theme (`crypto_majors`) — magnitude 0.2-0.3, novelty 1.0, manipulation ≤ 0.1 (the announcement is fact; the pump it causes is the graph's job). Non-graph-asset listings: skip |
| Anything about our 15 crypto assets or the 9 crypto-relevant factor nodes | This is the campaign's PURPOSE — err toward digesting borderline-material crypto stories you would skip in a general-news pass, at honest low magnitudes (0.15-0.25), rather than losing crypto signal density again |

## After the campaign

Code-side (not Sonnet's job): `_merge_amendments.py` folds
`events_amend_crypto/` into the working set with the other amendment
layers, rebuilds `ledger.jsonl` + `news_impulses_v2.jsonl`, and re-emits
the validation report. Then the final trainer run (exit-form crypto rounds
+ majors-only variant) answers whether crypto news history closes the gap.
