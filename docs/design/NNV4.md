# NNv4 — calibrated multi-head neural challenger

**Status: built, deployed as an isolated paper lane, 2026-08-28.** NNv4 runs
beside NNv2/NNv3 and cannot submit broker orders or alter the linear brain. It
is a research model, not an approved trading model.

The first full one-off P40 retraining completed successfully on 2026-08-28:
NNv3 was promoted at 11:29 SGT and NNv4 at 11:32 SGT. NNv4's promoted artifact
has 327 parameters and held-out validation loss `0.694185`. Both artifacts were
then copied to the ProDesk and its inference service was restarted.

## Objective

NNv4 predicts three related quantities for each symbol/day: expected
market-relative forward return, probability that the relative return is
positive, and forward adverse-movement risk. Its score is:

```text
expected return × calibrated probability ÷ risk × OOD multiplier
```

## Input contract

The model has 18 point-in-time features, explicitly constructed in this order:

`bias, momentum, mean_reversion, sentiment, political_hype, macro_linkage,
trend_zscore, consensus, mom_lowvol, regime_persistence, return_1d, return_5d,
return_20d, return_60d, realized_vol, vol_change, drawdown_60d,
relative_strength`.

Features use only information available at the decision timestamp. Historical
training uses aligned bars and a purged time split. The explicit vector order
prevents the old shorter legacy feature vector from silently training the wrong
input schema.

## Network and training

```text
18 inputs → Linear(12) → tanh → Linear(6) → tanh → Linear(3)
                                      ├─ expected return
                                      ├─ positive-return logit
                                      └─ risk magnitude
```

The model persists 327 parameters. PyTorch is used with `NN4_DEVICE=cuda` on
the ThinkStation P520 Tesla P40 and CPU fallback is available. The ProDesk is
inference-only. Training uses AdamW, deterministic seeding, early stopping,
Huber loss for return, binary cross-entropy for the probability head, and
Huber loss on absolute predicted risk.

Historical return labels are relative to the same-date cross-sectional median;
risk uses future adverse movement. Rows from the same date are grouped during
validation and are not treated as fully independent evidence.

## Calibration and OOD protection

The probability head is calibrated on held-out logits with regularized Platt
scaling (`calibration_slope`, `calibration_intercept`). The normalized input's
largest absolute z-score is compared with `ood_z_limit` (4.0 by default). The
OOD multiplier declines from 1 toward 0 as the input leaves the training
distribution, reducing both score and sizing. NNv4 paper targets are capped at
±25% while the live record matures. Saturated zero-feature diagnostics are not
accepted as conviction; they remain subject to OOD and calibration checks.

## Live paper lane and outcomes

`nn_v4_live.py` evaluates the same current inputs as the engine and maintains
its own `PaperBroker` under `data/nn_v4/`. Every cycle is journaled, but only
one primary row per `(symbol, Singapore calendar day)` is evidence; replicas
are never counted independently.

Primary rows store the asset key, price, feature vector, prediction heads,
target, OOD multiplier, and model version. After five days, an append-only,
idempotent ledger records entry/exit prices, realized return, equal-weight
cross-sectional benchmark return, excess return, direction hit, and original
features. This is the feedback record used for NN review and future fitting.

Files are `data/nn_v4/formula.json`, `nn_decisions.jsonl`, `outcomes.jsonl`,
`nn_book.json`, and `validation.json`.

## Improvement and promotion loop

`learning/nn_retrain.py` runs NNv3 and NNv4 on the ThinkStation with
`CUDA_VISIBLE_DEVICES=0`, `NN3_DEVICE=cuda`, and `NN4_DEVICE=cuda`. The enabled
user timer runs daily around 04:30 SGT with a randomized delay. NNv4 is
retrained, recalibrated, and purged-validated; its candidate replaces the
incumbent only when held-out validation loss improves. NNv3 additionally
requires improved walk-forward DSR. A failed or rejected candidate leaves the
incumbent untouched. The ProDesk never runs this job.

The linear brain has a separate `data/linear_brain/` evidence stream only. Its
existing RLS/relearning implementation is deliberately unchanged.

## Review schedule

- **10–14 days:** pipeline health — primary deduplication, finite values,
  five-day settlement, OOD behavior, and P40/ProDesk separation.
- **30 days:** first meaningful performance review after about five or six
  mature five-day cohorts; compare all NNs and the linear brain on excess
  return, calibration/Brier score, hit rate, costs, drawdown, and regimes.
- **60–90 days:** stronger model-selection review across more regimes.

Use distinct primary `(symbol, day)` observations, not raw cycle rows. Do not
promote on one good week; retain walk-forward and deflated-Sharpe safeguards.
NNv4 remains paper-only until the evidence supports a change.
