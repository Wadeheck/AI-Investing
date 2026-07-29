# Digestion Status & Continuation Orders

*Updated 2026-07-29 after auditing the first 40 digested days. Read together
with `docs/SONNET_DIGEST_BRIEF.md` (v1.2 — the operating instructions) and
`data/digest_v2/README.md` (workspace layout + retention rules).*

## What is DONE

- **Input archive: COMPLETE.** `data/news_archive_guardian.jsonl` now holds
  all **1,123 days** (2023-07-01 → 2026-07-27), ~80K articles, every record
  with title, summary, section, **full UTC timestamp, and body text**.
  Nothing is waiting on the fetcher anymore.
- **Digested so far: 40 days** (2023-07-01 → 2023-08-09), 223 events, in
  `events/YYYY-MM-DD.json`, ledger maintained.

## Audit of the first 40 days — verdict: good discipline, REDO required

What passed (and genuinely well):

| Check | Target | Measured | |
|---|---|---|---|
| Events/day | 5–15 weekdays, 3–6 weekends | 5.6 avg | ✅ |
| Magnitude median | 0.2–0.4 | 0.35 | ✅ |
| Magnitude ≥0.8 | rare | 0 | ✅ |
| risk_appetite share | ≤15% | 0% | ✅ (excellent restraint) |
| Invalid node ids | 0 | 0 | ✅ |
| Event chaining | ledger keys reused | 103 new / 119 dev | ✅ |

Why the 40 days must nonetheless be RE-DIGESTED (cheap — one session):

1. **They were digested from the OLD headlines-only archive**, before the
   body+timestamp re-fetch existed: every event is missing `ts` (223/223),
   and none could use the escalation pass (§2.1) because there were no
   bodies to escalate to.
2. **They predate brief rules §3.6 (cold start) and §7a (anchored nodes)**.
3. Trajectory purity: the ledger built on the old inputs would leave a
   permanent seam at day 41. Rebuilding 40 days now costs minutes;
   carrying the seam costs trust in the whole 1,123-day trajectory.

**Order: delete nothing, but restart digestion from 2023-07-01 against the
current archive under brief v1.2.** Move the existing `events/` to
`events_v0_headlines/` as an audit record; rebuild `ledger.jsonl` fresh.

## Calibration corrections (now codified in brief v1.2 — apply from day 1)

- **Long-war concentration:** `geopolitical_tension` carried 47% of all
  events (105/223) — Ukraine/Niger coverage was over-digested. Continuation
  coverage with no material change is novelty **0.2** (only ONE 0.2 was
  issued in six weeks — that is the miscalibration), and routine daily war
  coverage that changes nothing should often be SKIPPED entirely.
- **proposed_edges: zero in six weeks** is slightly under-proposing; the
  Niger-coup → `uranium_price` chain was a textbook candidate. Propose when
  a genuinely new mechanism appears (still ≤~1/week).

## What REMAINS

- Re-digest days 1–40 (fresh, v1.2 rules), then continue chronologically
  through **2026-07-27** — the full contiguous prefix is now eligible; no
  gaps, no waiting. ~1,083 further days.
- Per ~14 digested days: emit the distribution report (§14/§15); the
  runner/harness validates and halts on prior violations.
- On completion: the validation report, then event-study calibration (B2)
  and trainer rounds — see `docs/DIGESTION_SPEC.md` §B6.

## Discovered relationships / node gaps (audit answer)

- No `proposed_edges` were emitted yet (see correction above), so nothing
  is queued for graph review. The node set held up: zero unknown-node
  rejections in 223 events, and no recurring orphan topic was observed in
  the first 40 days. Candidates to watch as 2024–2026 approaches:
  AI-datacenter power chains (`power_demand` ↔ `uranium_price`/`natural_gas`),
  and any new mechanism the coverage reveals — propose, don't assume.
- Separately, code-side (not Sonnet's job): edge re-weighting from data is
  planned as its own gated round (`DIGESTION_SPEC.md` B3/R21-learned-edges).

## Retention guarantee (permanent)

Raw news archives are **never deleted or overwritten**:
`news_archive_guardian.jsonl` (bodies+ts), the `.bak` headlines-only pull,
GDELT/wiki archives, and every `events*/` generation are all kept — we must
always be able to re-run digestion from scratch.
