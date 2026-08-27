# NNv3 Challenger

## Purpose

NNv3 is an isolated, parallel challenger for the live investing engine. It makes
independent decisions and maintains a paper book; it never submits broker orders
and cannot change the live brain, `data/formula.json`, or NNv2 state.

## Components

- `engine/ai_investing/learning/nn_v3.py`: deterministic 10→8→8→1 GELU model,
  normalized features, L2 regularization, purged time split, early stopping, and
  a 1,000-sample minimum.
- `nn_v3_runner.py`: fetches the configured full universe, requests long daily
  history, filters invalid/short instruments, computes aligned samples, and saves
  only a fitted challenger.
- `nn_v3_live.py`: loads `data/nn_v3/formula.json`, refreshes when its mtime
  changes, makes decisions on the engine's current inputs, and journals a separate
  paper book.
- `runner.py`: invokes the live lane inside a hard failure guard after the normal
  engine decisions. NNv3 errors cannot stop a live cycle.
- `systemd/nn_v3.service` and `systemd/nn_v3.timer`: weekly Monday 04:00 SGT
  retraining. Inference occurs during normal engine cycles; retraining is not a
  15-minute activity.

## Data and safety

Daily yfinance requests with `limit >= 1000` use `period="max"`; ordinary engine
requests retain their existing one-year behavior. The challenger uses all
configured instruments, retaining only those with usable overlapping history.
Unsupported symbols are excluded rather than padded or repeated. The model is
written atomically, so a failed run leaves the prior valid model intact.

The current NNv3 model is market-feature based. Existing digested news files are
not silently backfilled into old training rows. Future news integration must use
timestamped point-in-time snapshots, preserve missingness, and pass no-lookahead
tests before changing the model input schema.

## Runtime files

All challenger state is under `data/nn_v3/`, notably `formula.json`,
`nn_decisions.jsonl`, `nn_book.json`, and future feature snapshots. The model
wrapper contains `model_type: "nn3"` and is loaded independently of the live
formula.

## Verification

```bash
PYTHONPATH=engine .venv/bin/python -c \
  'import json; from ai_investing.learning.nn_v3 import NN3FormulaModel; p=json.load(open("data/nn_v3/formula.json")); print(p["model_type"], NN3FormulaModel.from_dict(p["model"]).fitted)'
systemctl --user status nn_v3.timer
journalctl --user -u nn_v3.service -n 100 --no-pager
grep -E "nn3-live" data/engine.log
```

The full-universe ProDesk run produced 243 eligible assets, 1,096 aligned bars,
250,533 samples, and a valid 97-parameter NN3 model. The obsolete NNv3 shadow
implementation was removed; NNv3 now has one authoritative live paper lane.
