# A neural-net challenger for the decision formula

**Status: BUILT and DEPLOYED (shadow only), 2026-08-22.** Commits `6ad02de`
(implementation) and `e65c78c` (report fix). Running on ProDesk as a weekly
shadow job that structurally cannot change what trades. It has never been
adopted, and on the evidence available it should not be — see §7.

Read `docs/design/FORMULA.md` and `docs/design/LEARNING.md` first; this
document assumes both. This file was originally an implementation plan. It has
been rewritten as an as-built record: §0-§2 are the reasoning (largely
unchanged, because it survived contact), §3-§6 are what exists and how to
operate it, §7 is what it has actually measured, and §8 is what is deliberately
still missing.

## 0. Why this exists

We were asked "can the brain be upgraded with a neural network." The honest
answer: the current linear formula (`θ·φ`, 10 features, fit by ridge + online
RLS) isn't linear because linear is inherently better than a neural net — it's
linear because that's what the amount of independent evidence this system
produces can support without overfitting (`docs/status/BRAIN_REVIEW_2026-08-21.md`
§4h: the live audit found the whole track record yields on the order of a few
hundred independent (symbol, day) observations; a single graph edge needs
60-120 of those just to get one calibration verdict on a **1-parameter** test).
A neural net has far more parameters than the 10-weight linear formula, so with
today's data it would fit noise and *look* more authoritative while being
worse.

The resolution is not to argue about which architecture is better in the
abstract. It's to let the walk-forward gate — the same one `FormulaModel`
already has to clear — decide, on real out-of-sample evidence, whether a small
NN beats the linear champion. If it never clears the gate, that's the answer,
and it cost nothing but compute. If it does, it earned it.

The first live run is exactly this argument in miniature: the net's
out-of-sample Sharpe **beat** the linear model's, and the gate refused it
anyway, because deflated across the number of trials that ran, the edge was
indistinguishable from the best-of-N noise you would expect from random
strategies. See §7. **The refusal is the feature.** Anyone reading this later
who is tempted to lower `nn_min_dsr` to get an adoption should read §7 twice.

## 1. Track A — grow the labeled-outcome count (NOT DONE)

This remains the actual bottleneck and it has **no code deliverable in this
change**. It is listed here because it is the only thing that will ever let the
NN win, and because building the challenger did not address it at all.

Read `docs/status/BRAIN_REVIEW_2026-08-21.md` before touching this — it
documents exactly how the last attempt to read "the record" overcounted by 65x.
Any work here must respect the counting discipline already built
(`advice_outcomes.is_primary`, `(symbol, day)` as the unit, embargo gaps,
binomial not t-tests). In priority order:

1. **Widen the tradable/observed universe** (`docs/design/BRAIN.md` §3.1, §4c).
   Confirm `scripts/brain_audit.py --section graph`'s `resolution_pct` doesn't
   regress — adding symbols that duplicate an existing theme's signature
   doesn't help.
2. **Backfill history where possible.** yfinance/FRED go back years; the
   constraint has been *when the brain started running*, not data availability.
3. **Do not shortcut this by lowering `MIN_N` or embargo requirements.** That's
   the failure mode the 2026-08-21 review fixed. Growing `n` must mean growing
   genuine independent observations, not relaxing what counts as one.

**A blocker found while building the challenger:** `Backtester._aligned()` truncates every
price series to the length of the **shortest** one. On the production
watchlist, one recently-listed symbol (CRCL, SPCX, HYPE/USD) collapses the
entire backtest to **3 bars**, and walk-forward returns "insufficient data"
before either candidate fits. Measured 2026-08-22 on the real 248-symbol
universe. Until `_aligned` intersects on dates instead of truncating to the
minimum, no curation — linear or NN — can run on the real universe at all.
This is the highest-value fix in this document and it helps the linear model
exactly as much as the NN.

## 2. The interface, and why it drops in unchanged

Nothing in `Backtester.run()` or `DecisionEngine.decide()` is hardcoded to
`FormulaModel` — both duck-type against it. Verified call sites:

- `strategy/decision.py: DecisionEngine.decide()` → `model.raw(feats)`,
  `model.conviction(feats)`, `model.target_from_conviction(final_conv)`.
- `backtest/engine.py: Backtester.run()` → `model.stop_loss`,
  `model.take_profit` (via `dataclasses.replace(self.risk_cfg, ...)`), and
  passes `model=model` into `RiskManager.size_orders()`.
- `strategy/risk.py: RiskManager.size_orders()` → `model.feature_names` to
  build `phi` for the OOD gate (`RegimeGate.ood_multiplier`, which reads
  `model.feature_mean` / `model.feature_std`).

`NNFormulaModel` exposes that whole surface, and
`test_interface_matches_formula_model` asserts the two classes agree on it so
the duck-typing claim is checked rather than believed.

`weight_of()` returns **0.0 for every name** rather than raising, so anything
reading per-feature attribution degrades to "none available" instead of
crashing. Grepped before shipping: **nothing currently calls `weight_of` at
all**, so this costs nothing today.

## 3. What was built

### 3.1 `engine/ai_investing/learning/nn_formula.py`

`NNFormulaModel`: a 10 → 4 (tanh) → 1 (linear) MLP. `10*4 + 4 + 4*1 + 1 = 49`
parameters, ~5x the linear model's 10 — deliberately not 10x or 100x.

Pure Python, `math` and `random` only. `engine/requirements.txt` states the core
engine runs on the standard library alone, and this does not become the first
thing to break that. At 49 parameters and a few thousand rows a hand-rolled
loop is fast enough: measured on ProDesk, `fit_nn` takes ~1s at 500 rows, ~4s at
2000, ~16s at 8000, scaling linearly.

Fields beyond the `FormulaModel` set: `hidden`, `W1` (hidden × n_features),
`b1`, `W2` (the single output row), `b2`, and an `n_params` property.

`feature_mean` / `feature_std` are typed `Optional` to mirror `FormulaModel`,
but are **required in practice** for this model in a way they are not for the
linear one: an unnormalized input saturates the tanh units and the net predicts
a constant. `fit_nn` always sets them.

`raw()` returns `0.0` when `W1` is empty, so an unfit net is inert rather than
throwing — the same safe default as an all-zero θ.

### 3.2 Training: `fit_nn()`

```
fit_nn(X, y, hidden=4, lr=0.05, epochs=300, l2=1e-2, seed=7,
       min_samples=MIN_SAMPLES) -> tuple[NNFormulaModel | None, str]
```

Returns `(model, "")` or `(None, reason)`. Full-batch gradient descent, MSE
loss, tanh hidden activation (derivative `1 - tanh(z)²`), deterministic given
`seed` (asserted by `test_training_is_deterministic_given_a_seed`).

- **Feature normalization** from the training slice's own mean/std.
- **L2 weight decay on weights only, never biases.** Penalizing the intercept
  just shrinks the mean prediction toward zero without buying capacity control.
  With ~49 params and a few thousand rows, decay — not early stopping alone —
  is the main defense against memorization.
- **Early stopping on the last 20% of the training slice**, patience 20. Note
  *training* slice: the walk-forward validation window is reserved for the
  outer champion/challenger comparison, exactly as it is for the linear model.
  Using it here would leak.
- **Divergence guard**: a non-finite validation loss breaks the loop and keeps
  the best state so far, if any.
- **`min_samples` floor** (`MIN_SAMPLES = 500`): below it, return
  `(None, "insufficient data for NN challenger")` without training, mirroring
  `optimize()`'s existing `"insufficient data for walk-forward"` early return.

**Read `MIN_SAMPLES` as a floor, not a licence — this is the most misreadable
number in the system.** A "sample" is one `(symbol, day)` row out of
`Backtester.build_samples`. Twenty symbols on the same day are one market
moving, not twenty independent draws. The first live run reported 2992 rows
against 49 params — a comfortable-looking 61x — but that is 22 symbols × ~136
days, cross-correlated. Clearing 500 is **necessary, not sufficient**. This is
the 2026-08-21 overcounting pattern pointed at the NN's own guard instead of at
the track record. `scripts/nn_challenger_report.py` prints this caveat on every
run, pass or fail, and the deflated-Sharpe gate — not this constant — is what
actually stops an overfit net.

### 3.3 The adoption rule (`backtest/walkforward.py`)

Extracted as a **pure function** so it is testable without running a backtest,
which is why it is the most-tested thing in this change:

```python
adoption_decision(linear_ok, nn_ok, sharpe_linear, sharpe_nn, margin)
    -> "linear" | "nn" | "none"
```

The five cases:

1. The linear candidate clears `min_dsr` (0.60, unchanged) — today's behavior.
2. The NN candidate must clear `nn_min_dsr` (**0.75**, higher) to be eligible.
   More complexity earns a *higher* evidentiary bar, not an equal one — the
   same asymmetry `brain/calibration.py` already applies between causal
   `influences` and structural `member_of` edges.
3. Neither clears → keep `prior_model`. Unchanged behavior.
4. Exactly one clears → it wins. Note this holds **even when the loser's raw
   Sharpe is higher**: an uncleared DSR bar means that Sharpe is not believable
   in the first place.
5. Both clear → the NN wins **only if** it beats the linear model by
   `nn_adoption_margin` (default 0.20). Ties and anything inside the margin go
   to the linear model, the one you can read.

The margin is computed as `sharpe_linear + margin * abs(sharpe_linear)`, **not**
`sharpe_linear * (1 + margin)`. With a negative linear Sharpe the naive form
*lowers* the bar — at linear = −1.0 it would let a net adopt at −1.2, i.e. while
being strictly worse. `test_adoption_margin_is_a_hurdle_when_linear_sharpe_is_negative`
pins this. At linear = 0.0 the margin is 0, so a strict `>` still requires the
net to be genuinely better.

`ADOPTION_CASE_TEXT` maps the outcome to plain language for the report. When
the NN never fit at all, the text says so, rather than reporting a linear win
over an opponent that never showed up.

### 3.4 The second candidate track

`WalkForwardOptimizer.optimize()` gained:

```python
optimize(assets, bars_by_key, prior_model=None, min_dsr=0.60,
         try_nn=False, nn_min_dsr=0.75, nn_adoption_margin=0.20,
         nn_hidden=4, nn_min_samples=MIN_SAMPLES)
```

With `try_nn=False` (the default) this is the code that shipped before the
change — same result keys, same early return, no NN import touched at runtime.
`test_walkforward_default_path_is_unchanged_without_try_nn` guards it.

`_optimize_nn()` mirrors the linear per-window loop: same windows, same
embargoed validation slices, same `self._val(...)` scoring. Differences:

- One fit per `NN_L2_OPTIONS` entry per window (3 fits), then `search` random
  draws from `HYPER_SPACE` paired with a fitted net. The decision-layer
  hyperparameters (`gain`, `entry_threshold`, …) do not affect training, so
  refitting per draw would be waste.
- Seeded from `(window, l2 index)` rather than `self.rng`, so the NN track is
  reproducible independently of how many draws the linear search consumed.
- **Its own `n_trials`.** Not pooled with the linear count — pooling would
  understate the multiple-comparisons penalty each candidate owes its own
  deflated Sharpe.
- A window with too few rows contributes the default score and is recorded with
  `nn_sharpe: None`, so a partial run is visible rather than averaged away.

Extra result keys when `try_nn=True`: `model_type`, `adoption_case`,
`linear_ok`, `nn_ok`, `nn_challenger_avg`, `nn_dsr`, `nn_n_trials`,
`nn_windows`, `nn_reason`, `nn_train_samples`, `nn_windows_fit`, `nn_n_params`,
`nn_min_dsr`, `nn_adoption_margin`.

`nn_reason` is only meaningful next to `nn_windows_fit`: it holds the last
refusal seen, which can come from an early short window while later ones fit.
It is blanked when every window fit.

### 3.5 Config (`engine/ai_investing/config.py`, `LearningConfig`)

| field | env var | default |
|---|---|---|
| `nn_challenger_enabled` | `LEARN_NN_ENABLED` | `False` |
| `nn_min_dsr` | `LEARN_NN_MIN_DSR` | `0.75` |
| `nn_adoption_margin` | `LEARN_NN_ADOPTION_MARGIN` | `0.20` |
| `nn_hidden` | `LEARN_NN_HIDDEN` | `4` |
| `nn_min_samples` | `LEARN_NN_MIN_SAMPLES` | `500` |

`backtest/main.py` passes all five through. With the flag off — the default —
nothing in this document runs.

### 3.6 Persistence

`ParamStore` writes a top-level `model_type` tag (`"linear"` | `"nn"`) and
dispatches on load. **A missing tag means linear**, so every `formula.json`
written before this change loads unchanged.

- Loading an `"nn"` payload returns `(model, None)` — any saved RLS state is
  dropped rather than misapplied, because RLS's update rule does not apply to a
  nonlinear model.
- `_migrate` (new features appended since the model was saved) works for both:
  a new input enters the net at **zero weight into every hidden unit**, the
  same "starts inert and earns trust" contract the linear branch has.
- `_weights_changed` compares flattened parameters via `_params_of`, and treats
  a linear ↔ NN swap as a change. The version counter exists to let you watch
  the formula mature, so it has to see a net whose weights moved — not just a
  file that was rewritten.
- The append-only params log records an NN adoption too. `journal.record_params`
  stores `{"model_type": "nn", "hidden": …, "params": [...]}` rather than
  pretending an MLP has per-feature weights.

### 3.7 The runner (a gap the plan did not cover)

**The plan specified `ParamStore` round-tripping both types but not its
consumer, and the live runner would have crashed at boot on an adopted net.**
`runner.py` calls `RLSLearner.initialize(self.model.weights)` in `__init__` and
`self.rls.update(...)` every cycle; an MLP has no `.weights`. The moment anyone
enabled the flag and ran `--optimize --save`, the engine would not have started.

Fixed: when the loaded model is a net, `self.rls` is `None` and every use is
guarded. Outcomes are **still journaled** — labeled rows are the scarce
resource this whole effort is bottlenecked on (§1), and discarding them because
today's model cannot consume them online would be backwards. The per-sample log
line says `[logged only -- NN has no online update]` so the absence is visible
rather than silent. `_dump` and the dashboard payload emit an empty weights
dict for a net instead of a fabricated attribution.

### 3.8 Reporting

`scripts/nn_challenger_report.py` reads `data/backtest.json` and
`settings.params_path`, and prints **both candidates, win or lose** — per
window and in aggregate — plus `n_params`, training rows, their ratio, the
independence caveat, both DSRs against their own bars, the margin, and which
adoption case fired in plain language.

A report showing only the winner would be the brochure `brain_audit.py`'s own
"HOW TO READ THIS" warns about. It also reads `settings.params_path` rather
than building `data_dir/formula.json` by hand — the first version did the
latter and, under the shadow job's redirected `PARAMS_PATH`, read an absent
file and announced "live model on disk: linear (version None)": wrong on both
halves, with no way for a reader to tell (fixed in `e65c78c`).

`scripts/brain_audit.py`'s `learning` section reports `model_type`, and for a
net also `nn_params` / `nn_hidden` and a pointer to the report.

## 4. Tests — `engine/tests/test_nn_formula.py`

24 tests, with a `__main__` block (project convention: `engine/tests/` files
without one silently report green on the box). Run:
`cd engine && python3 tests/test_nn_formula.py`.

The **six adoption-rule tests come first** and are the ones that matter: they
cover all five cases plus the negative-Sharpe and zero-Sharpe margin traps.
Everything else can be right and the system still be wrong if a 49-parameter
model can displace the linear formula without clearing a higher bar *and*
beating it by a margin.

The rest: exact `to_dict`/`from_dict` round-trip; unfit model inert; `weight_of`
never raises; interface parity with `FormulaModel`; `clone` overrides
hyperparameters without touching weights; refusal below `min_samples`; genuine
learning (validation MSE beats predicting the mean by 2x on a synthetic linear
relationship); determinism per seed; the 49-parameter guard; walk-forward
degrading safely below `nn_min_samples`; the `try_nn=False` path unchanged; the
NN track running when it has the rows; a net actually driving `Backtester.run`
end to end; `ParamStore` round-trip and RLS drop; pre-NN files loading as
linear; version bumping on a type swap but not a rewrite; feature migration into
`W1`; and the runner surviving a net on disk.

## 5. How it is deployed on ProDesk

Systemd **user** units (this box is user-scoped; the engine logs to
`data/engine.log`, not journalctl):

- `~/.config/systemd/user/ai-investing-nn-challenger.service`
- `~/.config/systemd/user/ai-investing-nn-challenger.timer` — weekly,
  `Sun *-*-* 20:00:00 UTC` = Mon 04:00 SGT, `Persistent=true`.

Weekly because the input that decides this — independent `(symbol, day)`
observations — grows by days, not by how often you refit.

**Four independent reasons the job cannot change what trades**, all verified by
observation and not merely by design:

1. It runs `--optimize` with **no `--save`**, so `ParamStore.save()` is never
   called.
2. `PARAMS_PATH` is redirected to `data/nn_shadow/formula.json`, so even an
   accidental `--save` could not reach the live formula.
3. `STATE_PATH` is redirected, so `_dump`'s `backtest.json` lands in
   `data/nn_shadow/` instead of clobbering the panel the dashboard reads.
4. Nothing else on the box runs `--optimize` — every systemd timer and cron
   entry was checked.

After the first live run, `data/formula.json` and `data/backtest.json` were
**byte-identical** (md5 `3d44d0af…` before and after), and no `formula.json`
was written in the shadow dir at all.

`BRAIN_DB_PATH` and `DB_PATH` are deliberately **not** redirected: the
challenger is meant to see exactly the information the live brain sees.

The job pins an explicit 22-symbol `STOCK_WATCHLIST` / 2-symbol
`CRYPTO_WATCHLIST` rather than the graph-derived universe, forced by the
`_aligned` defect in §1. Widen it only after `_aligned` intersects on dates.
Note this means **the challenger is currently measured on a different universe
than the brain trades** — a real caveat on §7's numbers, not a detail.

Systemd `Environment=` beats `.env`: `_load_dotenv` uses
`os.environ.setdefault`, so real environment variables always win.

Operating it:

```sh
systemctl --user start ai-investing-nn-challenger.service   # run now
systemctl --user list-timers ai-investing-nn-challenger.timer
tail -n 200 ~/Projects/AI-Investing/data/nn_shadow/nn_challenger.log
```

## 6. Running it by hand

```sh
cd engine
LEARN_NN_ENABLED=true python3 -m ai_investing.backtest.main --optimize
python3 ../scripts/nn_challenger_report.py            # add --json for the raw dict
```

Omit `--save` unless you intend to adopt the result. On the production
watchlist expect "insufficient data for walk-forward" until `_aligned` is
fixed (§1).

## 7. What it has actually measured

First live shadow run on ProDesk, 2026-08-22, 22 symbols, 251 aligned bars,
3 windows, 48 trials per track:

```
per window (both candidates, win or lose):
  win   train_rows   default    linear     NN
  0            924    -1.478       0.0    -0.621
  1           1958    -1.794       0.0     2.634
  2           2992     1.026     4.762     4.019

linear : avg Sharpe 1.587   DSR 0.076 over 48 trials              -> cleared=False
NN     : avg Sharpe 2.011   DSR 0.034 over 48 trials (need 0.75)  -> cleared=False

outcome: case 3: neither candidate cleared its DSR bar -- kept the incumbent
```

An earlier run on the same day (before the universe was pinned) recorded the
NN at avg Sharpe **3.901** against the linear model's 1.442 — a 2.7x edge — with
a DSR of 0.283 against its 0.75 bar. Refused.

**This is the entire point of the mechanism, so read it carefully.** On raw
out-of-sample Sharpe the net won both times, comfortably. Deflated by the
number of trials, neither candidate is distinguishable from the best of 48
random strategies, so neither was adopted and the hand-set θ still trades.
"Insufficient data" and "did not clear the bar" are **successful outcomes** for
this phase: it means the gate is doing its job. The fix is more independent
observations (§1). It is **not** a bigger network, and it is **not** a lower
`nn_min_dsr`.

## 8. Explicit non-goals, still in force

- **No trainable/backprop mechanism on `brain/graph.py` edge weights.** A
  weight per graph edge needs even more independent samples than this
  10-feature MLP, and the univariate calibrator in `brain/calibration.py` is
  already data-starved at `MIN_N=60-120` per edge (BRAIN.md §4d).
- **No online/live update path for the NN.** Walk-forward-curated only. RLS's
  linear update rule doesn't apply, and a safe online update for an MLP is a
  separate, harder problem. The NN does not mature between offline runs the way
  `RLSLearner` matures the linear θ.
- **Do not scale the network up.** More hidden units or layers is not "the next
  experiment if this one wins" — it is a strictly worse bet against the same
  scarcity. Re-check §1's sample count against the `n_samples / 10 >= n_params`
  rule first. Bigger is not the next experiment; more data is.
- **No change to default behavior.** `nn_challenger_enabled` defaults `False`
  and every new path is gated behind it.

### ~~Not built: a live per-cycle shadow book~~ — BUILT 2026-08-22

This section previously said the live shadow was not built and named what it
would take. It now exists, following the `_run_shadow` pattern this section
recommended: `engine/ai_investing/learning/nn_shadow.py`, wired into
`runner.py` after the live `decisions` are formed.

**What it does.** Every cycle the net sees exactly the context the live engine
just used — same signals, same news, same brain field, same curated wiring —
forms its own view on every asset, trades a paper book on it, and journals each
call **beside the brain's own call for the same asset on the same cycle**. The
comparison is therefore a row lookup, not a join across two systems on a
timestamp, which is where this kind of comparison usually rots.

**The counting unit is (symbol, day), not the row.** The engine cycles every
~8 minutes, so one row per decision per cycle would re-log a standing view ~65
times a day against the same forward return — the exact defect
`BRAIN_REVIEW_2026-08-21` found inflating the evidence base 65× (§4.37). Every
row is written and auditable; exactly one per (symbol, SGT day) carries
`is_primary`, and only those are graded. `_primary_symbols_for` reads **disk**,
not memory, so a mid-day restart cannot mint a second primary.

**Four outcomes, because a record that counts only what it took is a brochure:**

| | |
|---|---|
| `captured` | positioned, move went its way |
| `wrong` | positioned, it did not |
| `missed` | **FLAT while the asset moved >2%** — the opportunity cost a P&L-only record cannot show |
| `avoided` | FLAT and the move was small, or would have lost |

`missed` is the half normally absent. A book that never trades has no losses and
looks disciplined; counting its misses is what separates discipline from
paralysis. The 2% threshold matters: without it every FLAT call scores as a miss
and the net is pushed to be permanently long everything.

**Isolation is structural, not conventional** — five independent reasons:

1. Its own `PaperBroker`; it never sees the real broker or the live books.
2. Its own state, under `data/nn_shadow/` only. A test pins that a cycle writes
   nothing else in the data directory.
3. Its own model object; it never touches `runner.model` or `runner.rls`.
4. `UserViews()` empty by construction — judged on its own read.
5. The runner calls it inside a hard `try/except`. Note `_run_shadow` is **not**
   guarded that way; a second shadow lane must never be able to cost a live
   cycle.

**Persisting the net is not adoption.** `result["nn_model"]` now exposes the
fitted net win or lose, and `--save-nn-shadow` writes it for the shadow book to
trade. Previously a net the gate refused was unreachable — meaning the one
candidate most worth watching was the one nobody could watch. The flag **refuses
in code** any destination outside an `nn_shadow` directory, so the systemd
`PARAMS_PATH` redirect is belt *and* braces rather than the only guard. Adoption
still requires clearing `nn_min_dsr`, unchanged.

```bash
python3 scripts/nn_shadow_report.py     # the record, beside the brain's
```

**Still not built, and deliberately: online learning for the net.** The journal
accumulates the labelled record a future refit can consume, but the net does not
update from its own shadow outcomes between weekly runs. §8's first bullet still
applies — a safe online update for an MLP is a separate, harder problem, and at
this sample size an online-updated MLP would fit noise while *looking* like it
was learning. The net learns weekly from history; the shadow book records
whether that learning was any good.
