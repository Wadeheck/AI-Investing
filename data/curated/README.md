# Drop research here

Files in this directory are read by the brain as **curated** content — the
highest-authority tier there is. See `docs/data-pipeline/DIGESTION_SPEC.md`
**§A12**.

```bash
scp piece.md prodesk:~/Projects/AI-Investing/data/curated/
```

`.md`, `.txt`, `.markdown`. The first non-blank line becomes the title (a
leading `#` is stripped); the whole file becomes the body.

## What happens to it

It is digested on the engine's **next cycle**, once, and then skipped forever
(`BrainStore.filter_new` keys on title + source). The file is never moved,
renamed or deleted — it is yours, and it doubles as the provenance record for
whatever wiring it produced.

Unlike a news feed, it is **not** credibility-scored, **never** marked noise,
**not** rate-limited to two relationships, and **not** subject to the 6/day
proposal budget. Relationships it asserts enter the graph at full confidence
with `provenance: "user"`, may create nodes the graph has never heard of, and
the calibrator may strengthen them but never demote them.

Write for a reader who will act on it: say what changed, what it causes, in
which direction, and over what lag. The extractor is looking for **mechanism** —
"A raises B, which lowers C after about six weeks" — not sentiment.

## Checking it landed

```bash
python3 scripts/brain_audit.py --section graph    # user_edges, user_nodes
```

`user_sources` lists the pieces the current wiring came from.

## Housekeeping

The newest 40 files are offered each cycle. Past that the reader emits a loud
`_overflow` notice rather than going quiet — move digested pieces into a
subdirectory (subdirectories are not read) to clear it.

This README is skipped by name (`_CURATED_SKIP`), not by hoping the extractor
notices it has no origin node. A document explaining what high-authority
ingestion does, fed through high-authority ingestion, is exactly how something
absurd gets wired at confidence 1.0.
