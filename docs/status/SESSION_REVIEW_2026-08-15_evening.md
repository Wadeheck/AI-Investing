# Session review — three commits, none deployed, for a coworker to check

*Written 2026-08-15 evening by an AI pair-programming session (Claude), for
human review before anything here reaches the ProDesk. Everything below is
**committed locally on this machine only** — `git log` shows these three
commits sitting on top of `d03a24c` (today's earlier commit, already live).
Nothing has been pushed or pulled onto the box that actually trades. That is
deliberate: this review is the gate before that happens, not after.*

```
134fdcb  Fix: adviser_gate graded formula 'short' on absolute return, not excess
b0b7599  Automate the adviser-sizing decision; give 6 live-watchlist coins graph nodes
f18dbb0  Add two dormant candidate signals: trend z-score and Binance positioning crowding
```

21 files changed, 1,020 insertions, 36 deletions. Full diff: `git diff d03a24c..HEAD`.

**Test status:** 359 passed. 8 failing, all pre-existing on `d03a24c` before any
of this started (verified via `git stash` + rerun before touching anything) —
`test_alert_storm.py` (2) and `test_bullshit_layer.py` (6), unrelated to
anything in this diff.

---

## 1. Why this exists

Started from a Reddit post claiming a 65.92% CAGR crypto strategy. Independent
replication on real BTC data reproduced the CAGR but not the claimed drawdown,
and the strategy lost to buy-and-hold over the last 4 years — so the immediate
question ("should we run this") was no, but it led to three follow-on threads
that turned into real, evidence-gated additions to the actual system:

1. Is there a *validated* version of "trend continuation" worth having as a
   candidate signal? → §2
2. Is there free alt-data as good as the paid liquidation-map tools that got
   asked about separately? → §3
3. While auditing "why does the trading book barely trade," found two real,
   independent things worth fixing → §4, §5

Every piece below follows the same rule, stated explicitly because it's the
thing this whole session was testing: **nothing gets to influence a real
decision until it's cleared an evidence bar it didn't get to set for itself.**
Where that bar hasn't been cleared yet, the code is present but inert, and
says so.

---

## 2. `trend_zscore` — dormant candidate signal

**Files:** `signals/trend_zscore.py` (new), `learning/features.py`,
`learning/formula.py`, `signals/__init__.py`, `tests/test_trend_zscore.py` (new).

EMA(65)/stdev(65) z-score trend filter, added to the formula's feature vector
`φ` at **weight 0**. Runs every cycle, gets logged, cannot move `θ·φ` — `0 ×
anything = 0` — until it earns a nonzero weight through one of two existing,
already-built mechanisms:

- **Online RLS** (automatic): every closed trade nudges the weight. No action
  needed for this to work, but see §4 — it's currently near-inert for the
  trading book specifically, for unrelated reasons.
- **Offline walk-forward** (manual): `backtest.main --optimize --save`
  re-fits and only adopts if Deflated Sharpe clears 0.60. Run once already
  (crypto-only universe, real Gemini/ccxt data): **rejected**, DSR 0.001.

**Deliberately excluded from the `consensus` feature** — an earlier version of
this diff had it folded into `consensus` (which already carries a live
nonzero weight), which would have let it influence conviction even at weight
0. Caught and fixed before commit; `test_feature_reaches_formula_but_not_consensus`
pins it down.

**What a reviewer should check:** the EMA/stdev math itself (`indicators.ema`,
`indicators.stdev`, both pre-existing, reused not written) and whether
excluding it from `consensus` is the right call long-term or just the safe
one for now.

---

## 3. `positioning_crowding_z` — dormant alt-data

**Files:** `research/crypto_signals.py`, `config.py`, `brain/core.py`,
`tests/test_crypto_positioning.py` (new).

Binance long/short account-ratio crowding, covering all 17 watchlist coins
(funding rate only ever covered BTC/ETH/SOL). Verified live against the real
API — seeded 30 days of real history same-day. Gated by
`CRYPTO_POSITIONING_ENABLED` (default **false**) before it can move a brain
resting level in `_crypto_anchors()`.

**Why it can't be validated further right now, structurally, not by choice:**
Binance retains only 30 days of this endpoint's history server-side — checked
by requesting `startTime` back to 2020 and getting the same 30 days back
regardless. There is no way to backfill deeper history for this one; it has
to accumulate from whenever it first runs.

**What a reviewer should check:** whether the crowding formula (z-score >
1.0 → `-0.15 * min(1, z/2.5)` resting-level drag, same shape as the existing
funding-rate anchor) is a reasonable prior, or whether it should be tuned
before it's ever turned on. It currently ships as an unvalidated *prior*, the
same honesty flag other recent altcoin edges in `seed.py` use
("weight is a prior, not measured").

---

## 4. `adviser_gate.py` — automatic evidence gate for adviser→sizing wiring

**Files:** `brain/adviser_gate.py` (new), `runner.py`,
`scripts/adviser_gate_check.py` (new), `deploy/systemd/ai-investing-adviser-gate.{service,timer}`
(new), `tests/test_adviser_gate.py` (new).

**The problem this replaces:** `STATE_OF_THE_SYSTEM.md` had an open item —
the adviser's long-side calls are measurably more accurate than the formula
engine's own short/avoid calls, but nothing acts on that; it required a human
to notice a documented cue fired and manually decide whether to wire adviser
conviction into position sizing. Asked explicitly not to leave this as
something a person has to decide.

**What it does:** a daily systemd timer runs `evaluate()`, which measures,
against the real databases:
- adviser long-side hit-rate (`brain.db` → `advice_outcomes`,
  `direction='long' AND is_conviction=1`)
- formula-engine short/avoid hit-rate — **this required writing new grading
  logic that didn't exist anywhere before**: dedupe `journal.db.decisions` to
  one call per (symbol, calendar day) — the last decision issued that day —
  then grade each against `brain.db.price_history` at a 5-day horizon vs. a
  benchmark, reusing `scorecard.py`'s existing `benchmark_for`/`verdict`.

Eligible only if **all four** hold: adviser hit >0.60, formula-short hit
<0.35, both n≥500, both over 30+ distinct days. Writes the verdict to
`data/adviser_gate.json`. `runner.py` reads that cached file once per cycle
(no live DB query in the hot path) and, only if `eligible: true`, applies a
**bounded nudge** (`BLEND_WEIGHT=0.25`, final result capped to ±1.0 target
weight, never an override) to that cycle's decisions, *after*
`features_by_key` is captured so the RLS learning loop keeps training on the
model's own signal rather than an adviser-nudged one.

**Checked against real production data before building the consumption
side** (copied `journal.db`/`brain.db` down from the ProDesk, read-only, not
touching the live box): **not eligible today** — adviser n=1,361, hit 0.558,
10 days; formula-short n=359, hit 0.415, 11 days (numbers below are post-fix,
see §5). So today this changes zero trades. It's built to change that answer
on its own, once the evidence does.

### What a reviewer should scrutinize hardest here

- **`BLEND_WEIGHT = 0.25`** — chosen, not fitted. No backtest validates this
  specific number; it's a "meaningful but not dominant" guess. Worth an
  opinion on whether it should be walk-forward-fit instead of hand-set once
  the gate is closer to firing.
- **The dedupe rule** (last decision of the calendar day) — a defensible
  choice, not verified against whatever produced the original
  `SCORECARD_REVIEW` "deduped: long calls hit 0.672 (n=102)..." figures,
  because that methodology isn't written down anywhere I could find. If a
  different dedupe rule was actually used historically, this gate's adviser-side
  number won't exactly match old review documents (it will still be internally
  consistent, just not identical to a number computed a different way).
- **Where the nudge is applied** — I put it in `runner.py`'s cycle
  (post-`DecisionEngine`, pre-`RiskManager`), specifically to avoid touching
  `DecisionEngine`/`FormulaModel`, which the backtester also uses. That keeps
  backtests deterministic and unaffected, but it does mean live and backtest
  decisioning now diverge slightly in a way they didn't before. Worth a second
  opinion on whether that boundary is the right one.
- **Grading formula "short" as "avoid"** applies uniformly, including to
  crypto pairs the formula engine scores but this book has *never once*
  executed (confirmed via `journal.db.orders` — zero crypto orders in its
  entire history). That's currently harmless because those decisions are
  inert either way, but it's a real assumption baked into the measurement —
  if crypto execution through this path is ever turned on, this needs
  revisiting.

---

## 5. Bug found and fixed same day: `verdict("short", …)` vs `verdict("avoid", …)`

**Files:** `brain/adviser_gate.py`, `tests/test_adviser_gate.py`.

`scorecard.py`'s `verdict()` has two branches: `"short"` grades on **absolute**
return (the literal "will fall" claim), everything else grades on **excess vs.
benchmark**. `_formula_short_stats`'s docstring said it should use the excess
rule (since nothing here can actually short stocks, a formula "short" is
functionally an "avoid" claim) — but the code called
`verdict("short", ret, excess)`, hitting the wrong branch. This is the *exact*
category error `STATE_OF_THE_SYSTEM.md` row 6 already documents being fixed
for the adviser's own label on 2026-08-04 — reintroduced here, on the formula
side, in the same session.

**How it was found:** asked directly "do you need another smarter person to
look at your work" and went back to actually check rather than defend it.
Every test in the first version of `test_adviser_gate.py` used a flat
benchmark, where absolute return and excess return are numerically identical
— the two code paths could never produce different answers in those tests, so
the bug was invisible to the suite that shipped alongside it.

**Fix:** `verdict("avoid", ret, excess)`. Added
`test_formula_short_stats_diverges_from_absolute_fall_rule`, which uses a
benchmark that moves *more* than the stock specifically so the two rules
disagree, and pins down which one is correct.

**Effect on the numbers already reported:** formula-short n 418→359, hit
0.404→0.415. The gate's eligibility verdict is unchanged (still far below
every threshold either way) — but the number itself was wrong for the
lifetime of one commit before being caught and corrected same-day.

**What a reviewer should check:** this is exactly the kind of thing worth an
independent re-derivation — pick a handful of real rows from `journal.db`,
grade them by hand against `brain.db.price_history`, and confirm the "avoid"
rule (not "short") gives the number you'd expect.

---

## 6. Six new graph nodes: `uni`, `atom`, `aave`, `dot`, `ltc`, `bch`

**Files:** `brain/seed.py` (`SEED_VERSION` 37→38), `brain/adviser.py`
(comment only), `tests/test_brain.py`.

Found while tracing why `UNI/USD long` stayed miscalibrated (n=1,096, hit
6.3%, per `SCORECARD_REVIEW_2026-08-15`) even after `adviser.py`'s
`CONFIRMED_MISCALIBRATED` zeroed its score in the adviser's ranking: **six
coins on the ProDesk's live `CRYPTO_WATCHLIST` had no graph node at all**
(UNI, ATOM, AAVE, DOT, LTC, BCH). A nodeless symbol skips every
general-purpose haircut (crowding, priced-in, integrity, bubble froth)
everywhere in the system, and `calibration.py` can't score an edge that
doesn't exist — so nothing was ever going to correct these on its own.

Added one `member_of crypto_majors` edge each, weight 0.5–0.6, explicitly
flagged in-line as **priors, not measured** — same honesty convention as the
`io_net`/`akt` edges already in the file. Verified the graph still loads,
propagates, and resolves all six symbols (426 nodes / 802 edges, up from
420/796) — `test_six_live_watchlist_coins_have_graph_nodes`.

**`CONFIRMED_MISCALIBRATED` override was deliberately left in place.** Its
documented removal criteria are (a) a real graph node — now true — **and**
(b) a `calibration.py` verdict at n≥20 realized-return observations on the
new edge — not yet true, and can't be sped up; it needs real elapsed trading
days. Comment in `adviser.py` updated to say exactly this, so nobody removes
the override on the graph-node condition alone.

**What a reviewer should check:** the five weight priors (0.5–0.6) — I
matched each to the nearest already-calibrated peer on the list (UNI/AAVE →
DeFi blue-chip tier like `link`; ATOM/DOT → established-L1 tier like
`avax`/`near`; LTC/BCH → lower weight, "thinner independent narrative" like
older BTC forks) but these are judgment calls, not measurements, same as
every other unmeasured edge already in this file.

---

## 7. Suggested review order

1. `engine/ai_investing/brain/adviser_gate.py` — the highest-stakes file; it's
   the one piece of this diff that, once eligible, changes what a real order
   looks like.
2. `engine/tests/test_adviser_gate.py`, specifically
   `test_formula_short_stats_diverges_from_absolute_fall_rule` — confirm this
   actually would have caught the bug in §5, and that the fix is right.
3. `engine/ai_investing/runner.py`'s single new block (search
   `apply_adviser_gate`) — confirm the insertion point relative to
   `features_by_key` capture and `RiskManager.size_orders` is correct.
4. `engine/ai_investing/brain/seed.py`'s six new node/edge blocks — sanity
   check the `crypto_majors` membership weights.
5. Everything else (`trend_zscore.py`, `crypto_signals.py`'s positioning
   addition) is lower-stakes: both are inert by construction (weight 0 /
   flag off) and would need a second, separate change to ever affect a
   trade.

**Nothing here should be deployed to the ProDesk until this review is done.**
