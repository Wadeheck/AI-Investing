# Incident — digest observability and RSS ingestion

Date: 2026-08-28  
System: live ProDesk (`ai-investing.service`)

## Summary

The daily status alert correctly detected stale brain-food data, but the
underlying digest service reported success after its impulse rebuild failed.
The live trading brain did not stop: it continued cycling independently on its
last known-good state.

## Root cause

`data/digest_v2/_merge_amendments.py` crashed while calculating impulses because
event data contained non-numeric `polarity` values. The affected records
included numeric strings such as `"+0.7"` and one structurally invalid list,
`[-0.4, 0.4]`.

The digest wrapper captured stderr, ignored the subprocess exit code, and let
systemd report the oneshot service as successful. This left the derived impulse
artifact stale through 2024-06-28 even though event files were current through
2026-08-27.

There was also an artifact-path inconsistency: the merger wrote
`data/news_impulses_v2.jsonl`, while the trainer consumed
`data/digest_v2/news_impulses_v2.jsonl`.

The RSS warning has two causes. Blockworks has not contributed a new article
since 2026-08-16. `gov.cn` responds successfully and its cache contains items
through 2026-08-25, but the shared accumulator could mark cached headlines as
brain-digested before the live runner consumed them.

## Remediation implemented

- Normalize numeric-string event fields during impulse derivation.
- Exclude structurally invalid impulse records with an explicit warning while
  retaining the source event and ledger record for review.
- Write the impulse artifact through a temporary file and atomic replacement;
  calculation failure cannot destroy the last-known-good artifact.
- Use `data/digest_v2/news_impulses_v2.jsonl` consistently.
- Make digest rebuild failures visible and non-successful to the caller.
- Keep digest failure isolated from `ai-investing.service`; the live engine is
  not stopped or restarted by this pipeline failure.
- Give the accumulator its own archive deduplication and stop using the shared
  brain `digested` flag as an archive marker.

## Verification

The corrected rebuild completed with 1 malformed event explicitly excluded and
produced 1,154 impulse days through 2026-08-27. After deployment:

```text
impulses (brain food): current through 2026-08-27
engine cycling: OK
ai-investing.service: active
```

The remaining RSS warning is source-level coverage: Blockworks appears frozen,
while `gov.cn` requires observation of the next accumulation cycles after the
deduplication change. Neither warning is permitted to halt the brain.

## Operating rule

Derived-data jobs may fail loudly and preserve their last valid output. They
must not be a dependency that systemd uses to stop or gate the live trading
engine.
