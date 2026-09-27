# ProDesk review implementation — 27 September 2026

Implemented the correctness and containment work from `PRODESK_REVIEW_2026-09-27.md`.

- Added an idempotent append-only execution ledger for shared-book fills, including incremental cumulative partial-fill economics, fees, currencies, and available attribution IDs.
- Added versioned outcome rows with explicit `model_id`, `prediction_id`, prediction payload, feature cutoff, scheduled horizon, benchmark identity, and incomplete-label recording. Legacy rows remain unchanged and are excluded from repaired settlement.
- Fixed NNv5 comparator extraction, feature normalization, CPU/GPU loss parity, incumbent baseline comparison, and scoring of the deployed gate/clipping policy.
- Fixed NNv4 volatility units, cross-sectional relative strength, post-demeaning positivity targets, and paper execution-cost treatment.
- Quarantined the current NNv4 artifact by default; only a separately repaired artifact can be enabled with `NN4_ALLOW_CURRENT=1`.
- Replaced positional backtest alignment with exact timestamp alignment.
- Quarantined new crypto-event entries by default while preserving existing exit handling.
- Frozen automatic LLM and deal graph-edge admission by default while retaining proposed edges in stored event evidence; explicit opt-in is `BRAIN_ALLOW_LLM_EDGE_ADMISSION=1`.

Validation passed on ProDesk: 98 focused tests, one expected optional dependency skip, 65 deterministic brain/graph/deal tests, and Python compilation of all changed modules. One separate adviser test remains dependent on the current live graph state and failed its existing circular-financing assertion. The brain and chat user services were restarted after both the NN and graph guard changes; both are active. The first post-restart cycle wrote repaired rows to all four NN journals.

The deployment checkout retains its pre-existing unrelated NNv5/retraining modifications. Historical rounded text-only fills remain marked unreconstructable; exact economics must come from broker execution history before historical P&L is backfilled. A common executable simulator/comparator, broker-history backfill, calendar-aware as-of joins, and the longer graph/macro/portfolio research program remain follow-up work.
