# NNv5 — residual challenger

NNv5 is an isolated research lane. It does not replace the linear brain and
cannot place broker orders.

## Model

The model predicts an incremental residual:

```text
NNv5 prediction = linear brain prediction + gated NN residual
```

The residual network receives the same point-in-time feature vector as the
linear brain plus the linear prediction, conviction, and target weight. The
gate is bounded, so an uncertain NN falls back continuously to the incumbent.

## Training

`nn_v5_runner.py` fetches up to 4,000 bars per configured asset when a full
training run is requested, or consumes the engine's point-in-time stock cache
on the always-on host. It builds the same forward-return samples used by the
linear backtester and trains a small residual MLP. Training uses a
chronological purged split. The candidate is rejected unless its validation
Huber loss beats the zero-residual incumbent on the untouched validation
slice. The GPU workstation may use CUDA; the ProDesk uses the deterministic
CPU fallback.

Artifacts are written only to `data/nn_v5/formula.json`. The GPU workstation
can retrain all challenger lanes. The ProDesk's daily service deliberately
retrains only NNv5, while NNv3 and NNv4 continue as paper inference lanes.
This keeps the daily CPU job bounded and avoids three competing trainers.

## ProDesk schedule and power-cycle contract

The ProDesk owns the recurring NNv5 training schedule, so the GPU workstation
does not need to remain powered on:

- `nn_retrain.timer`: daily at 04:30 Singapore time, with up to 15 minutes of
  randomized delay; `Persistent=true` catches up after downtime.
- `nightly-rest.timer`: poweroff at 05:00 and RTC wake after 9,000 seconds,
  approximately 07:30. The normal training window therefore ends before the
  scheduled poweroff.
- The user service manager has lingering enabled, so the timer remains active
  without an SSH or desktop session.

If training is still active at shutdown, systemd terminates the oneshot cleanly
and the next persistent timer activation retries it. A rejected candidate does
not replace the incumbent artifact; the live linear brain and all NN lanes
remain available after the daily power cycle.

## Evidence

The lane records one primary `(symbol, Singapore day)` decision, settles it at
the five-day horizon through `OutcomeLedger`, and stores the linear brain's
same-row decision beside it. Raw cycle rows are replicas, not independent
observations. NNv5 remains paper-only until it beats the linear brain on
paired, cost-adjusted, walk-forward evidence across multiple regimes.
