# Digestion Status & Continuation Orders

*Updated 2026-07-29 after completing the v1.2 redo of the first 40 days.
Read together with `docs/SONNET_DIGEST_BRIEF.md` (v1.2 — the operating
instructions) and `data/digest_v2/README.md` (workspace layout + retention
rules).*

## What is DONE

- **Input archive: COMPLETE.** `data/news_archive_guardian.jsonl` holds
  all **1,123 days** (2023-07-01 → 2026-07-28), ~80K articles, every record
  with title, summary, section, full UTC timestamp, and body text.
- **v1.2 redo: COMPLETE.** Days 2023-07-01 → 2023-08-09 (40 days, matching
  parity with the original headline-only batch) have been fully
  re-digested against the current body+ts archive under brief v1.2:
  every event carries `ts`; the escalation pass (§2.1) was applied to
  events with confidence<0.6 or magnitude≥0.5; cold-start (§3.6) and
  anchored-node (§7a) rules were in force from day one.
  The old headline-only output lives in `events_v0_headlines/` as a
  permanent audit record (never deleted, per the retention rule).

## v1.2 redo audit — 40 days, 204 events

| Check | Target | Measured | |
|---|---|---|---|
| Events/day | 5–15 weekdays, 3–6 weekends | 5.1 avg (range 3–8) | ✅ |
| Magnitude median | 0.2–0.4 | 0.30 | ✅ |
| Magnitude ≥0.8 | rare | 0% | ✅ |
| risk_appetite share | ≤15% | 0% | ✅ |
| Invalid node ids | 0 | 0 | ✅ |
| Novelty mix | ~50/35/15 | 49.5/48.0/2.5 | ⚠️ 0.2-tier still thin |
| `ts` present | 100% | 204/204 | ✅ |
| Ledger keys | — | 100 | — |

`geopolitical_tension` improved from 52% (day-14 checkpoint) to 43.6% over
the full 40 days as earnings season, Fed/ECB/BoE decisions, and commodity
shocks (Black Sea grain collapse, India rice ban, Niger coup, Fitch US
downgrade) diversified the mix. Remaining concentration reflects a
genuinely geopolitics-dense month (Niger coup, Israel judicial overhaul,
Wagner mutiny aftermath, Poland-Belarus tension, Sudan) rather than
under-diversified tagging — confirmed with the user mid-batch.

**Discovered node-map gap:** no dedicated UK-banks node exists. Several
genuinely market-moving UK bank stories were skipped for lack of a clean
node home: the NatWest/Coutts CEO resignations (£1bn wiped off NatWest
shares), Wilko's collapse, WeWork's near-bankruptcy. Also no UK-specific
growth/inflation node (UK GDP/CPI/PMI events were routed through the
`europe_growth`/`credit_conditions` catchalls as an approximation) and no
wind-energy-specific node distinct from `solar` (Vattenfall/Dogger
Bank/Hornsea stories routed through `energy_transition`). Flag these for
consideration if the node graph is revised.

**proposed_edges: still zero.** No genuinely new causal mechanism outside
the existing 85-node map surfaced in this batch that warranted a proposal
(the Niger→uranium and Poland-Belarus stories used existing dual-node
tagging, not new edges).

## What REMAINS

- Continue chronologically from **2023-08-10** through **2023-07-28**...
  correction: through the full archive to **2026-07-28** — ~1,083 further
  days. `ready_days.txt` already lists the full 1,123-day contiguous
  prefix; resume by digesting the next undigested date after 2023-08-09.
- Per ~14 digested days: emit the distribution report (§14/§15); halt only
  on a distribution-prior violation or a zero-event day from 30+ headlines.
- On completion: the validation report, then event-study calibration (B2)
  and trainer rounds — see `docs/DIGESTION_SPEC.md` §B6.
- Separately, code-side (not Sonnet's job): edge re-weighting from data is
  planned as its own gated round (`DIGESTION_SPEC.md` B3/R21-learned-edges).

## Retention guarantee (permanent)

Raw news archives are **never deleted or overwritten**:
`news_archive_guardian.jsonl` (bodies+ts), the `.bak` headlines-only pull,
GDELT/wiki archives, and every `events*/` generation are all kept — we must
always be able to re-run digestion from scratch.
