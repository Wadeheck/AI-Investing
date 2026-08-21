# Brain review — the model, the math, and what 26 days of live record actually supports

*Written 2026-08-21 against the ProDesk's live state (`data/brain.db` 194MB,
`data/journal.db` 514MB, `data/knowledge_graph.json`, the five per-book
journals, and the running engine's own JSON state files), pulled read-only over
SSH. No re-fitting, no simulation. Where a number contradicts an earlier
review, the earlier number is quoted alongside it.*

**Scope.** This is not a P&L review — `SCORECARD_REVIEW_2026-08-15` did that.
This asks the structural question: is the brain *modelled* correctly, is there
now enough evidence to update it, and what has it missed. The answer to the
first question is "in most places yes, in four places no, and one of those four
invalidates the evidence base every previous review was built on."

---

## 1. The headline: the measurement layer counts the same call 65 times

`advice_outcomes` holds 42,674 rows. It holds **598 distinct
(symbol, issue-day) observations.**

```
rows (hit is not null)                 38,900
distinct (symbol, issue-day)              598
inflation factor                          65.1x
```

**Mechanism, and it is by design rather than by accident.** `advice_log` is
written every cycle — 3,273 rows over 26 days, ~126/day at a ~10-minute
cadence. `scorecard.py`'s SCORE pass grades *every advice list ever issued*
once it is `HORIZON_DAYS` old, and `advice_outcomes`'s primary key is
`(advice_id, symbol)`. So a single standing view — "long NVDA today" — is
frozen, graded, and counted **126 times that day**, against the same forward
return, from the same 5-day window. The docstring's promise ("nothing is ever
deleted, mistakes stay on the record") is being honoured; the statistics
built on top of it are not.

Every `n` in `SCORECARD_REVIEW_2026-08-12`, `SCORECARD_REVIEW_2026-08-15`, and
`data/adviser_gate.json` is inflated by this factor. Every t-statistic derived
from those `n`s is inflated by **√65 ≈ 8×**.

### 1.1 What the record looks like after deduplication

One observation per (symbol, direction, issue-day):

```
direction        conv   n_eff     hit   avg_exc   t(hit−0.5)
long                1     105   0.611    +2.03%      +2.39
long                0     138   0.446    −0.16%      −1.34
avoid               1     169   0.541    +0.47%      +1.15
avoid               0      92   0.497    +0.19%      −0.07
short_or_avoid      1      55   0.414    +3.00%      −1.29
short_or_avoid      0      78   0.462    +1.69%      −0.68
```

Compare against the 08-15 review's version of the same table, which reported
`avoid/1 n=10,329 hit 0.602` and concluded *"the specific claim 'conviction is
inverted on the short side' no longer holds on the full sample."*

**Deduplicated, that conclusion reverses back.** High-conviction `avoid` is
0.541 at t=+1.15 — indistinguishable from a coin. High-conviction
`short_or_avoid` is 0.414 and *below* its own low-conviction cousin (0.462),
which is the original "conviction is inverted on the short side" finding,
intact. It never went away; it was buried under 65× replication of four days
of a rising tape.

**One result survives, and only one:** high-conviction longs, hit 0.611,
+2.03% excess, t=+2.39.

### 1.2 And that one result is weaker than t=2.39 suggests

The deduplicated observations are daily samples of **5-day overlapping forward
returns**. Consecutive days share four-fifths of their window, so they are not
independent either. A standard overlap correction deflates the t-statistic by
roughly √5:

```
t = 2.39 / √5 ≈ 1.07
```

**Honest verdict: after 26 days, the brain has not yet produced a single
directional claim that clears a conventional significance bar.** The
conviction-long result is the most promising thing in the record and it is
*suggestive*, not established. It points the same way as two independent
corroborations (§3), which is why I would keep trading it — but it should not
be described as proven, and `adviser_gate.py` should not be allowed to flip a
live sizing multiplier on it.

### 1.3 This has a live consequence today, not just a documentation one

`data/adviser_gate.json`, as of 01:35 today:

```json
{"eligible": false,
 "adviser_long":  {"n": 4040, "hit": 0.703, "days": 15},
 "formula_short": {"n":  680, "hit": 0.535, "days": 17},
 "threshold": {"adviser_long_hit": 0.60, "formula_short_hit": 0.35,
               "min_n": 500, "min_days": 30}}
```

`min_n: 500` was chosen as an anti-overfitting guard. At 65× replication,
**500 rows is 7.7 independent observations.** The gate's `min_days: 30` is the
only bar actually doing work, and it clears in ~15 days on the adviser side —
at which point a real sizing nudge (`BLEND_WEIGHT=0.25`) turns on, justified by
an `n` that is fiction.

The file already carries a `formula_short_alt_dedupe` field, so someone
suspected duplication before. That rule removed 8 rows of 680. It is not
catching this.

**This is the single most urgent item in the review** — not because the gate is
wrong today, but because it is an *automated* control that will flip itself on
in a fortnight on evidence it cannot see is 65× thinner than it reads.

---

## 2. The graph can distinguish 202 objects, and it holds 476

I probed the live graph with each of its 81 factor/commodity/actor nodes
individually shocked at +0.6, `max_hops=3`, and recorded every asset's response
vector.

```
assets                                             476
distinct response signatures                       202   (42.4%)
assets inert to ALL 81 shocks                      212
assets whose signature EXACTLY equals a peer's     104
```

**212 assets never move, for any macro shock the graph can generate.** These
are overwhelmingly LLM-added entity nodes harvested from news copy — `boeing`,
`chevron`, `blackrock`, `procter__gamble`, `warner_bros`, `kenya`,
`saudi_led_investor__affinity_partners` — nodes that exist as graph vocabulary
without ever being wired into the causal field.

**104 assets are exact duplicates of a peer.** The graph literally cannot tell
them apart:

```
x5  nio, xpeng, liauto, gotion, sanhua
x4  ccb, boc, abc, cmb
x4  nike, adidas, anta, lining
x4  atom, aave, dot, ltc
x3  dbs, ocbc, uob
x3  amat, lrcx, klac
x3  crwd, panw, cibr
x3  barclays, lloyds, natwest
x3  avax, near, link
```

### 2.1 Why this matters more than it looks

BRAIN.md §4d claims the propagation is a **path-sum**, and that "converging
medium-strength paths add, which is how clusters actually move." That property
is real for the ~90 richly-wired names (NVDA reaches 76 distinct origins over
572 paths). For the co-member groups above, every member hangs off the same
single `member_of` edge into the same theme, so the path-sum has exactly one
term and the "cluster" reduces to a sector lookup.

The record shows this costing money directly. `crwd`, `panw` and `cibr` have
**identical** graph signatures. Over the same window:

```
PANW  long             hit 1.00   +7.66%
CRWD  short_or_avoid   hit 0.00   +7.16%
```

Same read from the graph, opposite calls, opposite outcomes. Whatever
differentiated them was not the causal model — and the outcomes say it was a
coin flip.

The crypto book is the pure case. 13 of 17 watchlist coins reach the identical
41 origins over the identical 62 paths, and propagation confirms identical
landed impacts (`uni` and `bch` both +0.0690; `xrp`/`bnb`/`avax`/`near`/`link`
all +0.1204). Against that:

```
LINK/USD  long   hit 0.88   +4.41%
UNI/USD   long   hit 0.09   −6.99%
FET/USD   long   hit 0.00   −8.71%
BCH/USD   long   hit 0.00   −4.87%
HYPE/USD  avoid  hit 0.00   +8.71%
ATOM/USD  avoid  hit 0.27   +1.41%
```

**The 08-15 fix for UNI/USD treated a symptom of this.** Its root cause was
recorded as "no graph node, so no causal haircuts applied" — but UNI *does*
have a node (`uni`, degree 1, `member_of crypto_majors`). The real cause is
that the node carries no information the other twelve alts don't also carry.
`CONFIRMED_MISCALIBRATED` correctly stopped UNI (0 calls issued since 08-16,
verified), and left FET, BCH, HYPE and ATOM — the same defect, same magnitude —
running.

### 2.2 A node named `none` is the 17th most connected node in the graph

```json
{"id": "none", "type": "asset", "label": "None (private)", "aliases": ["none"],
 "state": "llm-proposed 2026-08-07: SK Hynix board approved 54 trillion won..."}
```

23 edges into it, all `provenance: llm`, all created when the extractor was
asked for a counterparty and answered "none":

```
skhynix -owns->  none   0.241
tsmc    -owns->  none   0.500
avgo    -owns->  none   0.350
amazon_alphabet_microsoft -owns-> none  0.500
googl   -owns->  none   0.200      googl -supplies-> none  0.100
xrp     -owns->  none   0.051
```

`owns` edges flow **rev** (`EDGE_FLOW`), so a shock landing on `none` flows
back into TSMC at 0.5, Broadcom at 0.35, and Alphabet, Amazon and Microsoft as
a merged fictional entity at 0.5. It is a junk collector wired as a
transmission hub between semiconductors, megacap tech and XRP.

Also present: 6 fully orphaned LLM nodes (`quest_global`,
`milky_mist_dairy_foods`, `redotpay`, `molbio_diagnostics`, `shiprocket`,
`kakao_mobility`) — Indian and Korean private-company names harvested from
funding stories.

### 2.3 LLM wiring has outgrown its stated bound

STATE_OF_THE_SYSTEM §2 records the graph at **420 nodes / 796 edges**, and §4A
describes LLM edges as "18% of the graph" with an unreviewed backlog of 140.
Live today:

```
nodes  616   (+196)
edges 1156   —   802 seed, 354 llm  (30.6%, not 18%)
```

§4B's cue was "revisit when LLM edges cross 328, ~2026-09-19." **It crossed at
354 already.** I ran the check the cue names, and it is worse than the cue
anticipated:

```
$ python3 scripts/review_edges.py --stats
  edges            1156  (802 curated, 354 llm — 31% self-added)
  pending review   354
  reviewed & kept  0
  rejected         2
  proposed last 7d   131
  proposed last 28d  354   (88.5/week)
  §A10 expects       <=1/week
  RATE IS 88x THE SPEC.
```

Three things at once. The rate is **88/week, not the 35/week** §4A records —
it has more than doubled. **131 edges were proposed in the last 7 days alone.**
And `reviewed & kept: 0` — the review mechanism built in §4.22 to be the
control surface for this has **never been used once**, on any edge, ever. The
cue fired early and silently because checking it requires a human to run a
script, and the script's own output says the queue can no longer be cleared by
hand.

Seed edges carry mean weight 0.546 at confidence 0.997; LLM edges mean 0.338 at
confidence 0.500 — so the damping is working as designed. The problem is not
per-edge strength, it is that 196 of the 616 nodes are now news-vocabulary
rather than modelled objects, and they are what drives §2's 212 inert nodes and
the `none` hub.

---

## 3. What the brain genuinely does well — and it is narrower than advertised

Three claims survive deduplication and are corroborated by a *second,
independent* measurement, which is the only reason I'd trust them at this
sample size.

**(a) Catching fresh positive shocks.** `event_outcomes`, graded independently
of the advice scorecard:

```
impact_sign   noise    n      hit    avg_ret
     +1         0    1406    0.671    +1.55%
     +1         1    1112    0.652    +1.76%
     −1         0     513    0.442    +1.10%
     −1         1     322    0.366    +2.07%
```

Positive-shock calls hit 0.671. Negative-shock calls hit 0.442 — worse than
chance, with *positive* realized returns. This is the same long/short asymmetry
§1.1 found in the advice record, arrived at from completely different data.
**Two independent instruments agree the negative side of the model is not just
weak but anti-predictive.**

**(b) The event sleeve, on realized cash.** 16 completed legs, **+$1,146.21
realized**, win-rate 0.62, equity $11,230.86 (+12.3%). Still **zero stop-outs**
— so §4A's 32:1 risk/reward asymmetry remains completely untested, exactly as
the 08-15 review warned. This is the best result in the system and its central
risk has still never been asked to prove itself.

**(c) Nine symbol-level calls that clear a real bar.** Of 170 (symbol, call)
pairs, **9** have ≥8 distinct issuance days *and* |t| ≥ 2:

```
DEO      avoid   days=12  hit 1.00  −1.32%   t=+99.5
DOT/USD  avoid   days=10  hit 0.96  −3.04%   t=+15.8
O39.SI   long    days= 8  hit 0.88  +2.59%   t= +3.0
GLD      long    days=12  hit 0.77  +2.67%   t= +2.3
--- and four that are significantly WRONG ---
TSLA     avoid   days=10  hit 0.03  +2.13%   t=−13.6
9880.HK  avoid   days= 9  hit 0.15  +1.99%   t= −4.7
UNI/USD  long    days=12  hit 0.18  −5.72%   t= −3.5
MP       avoid   days=13  hit 0.25  +4.68%   t= −2.1
ETH/USD  avoid   days=13  hit 0.22  +1.82%   t= −2.7
```

Note the composition: **5 of the 9 significant calls are significantly wrong,
and 4 of those 5 are `avoid` calls.** The 08-15 review's "confirmed working"
list (2899.HK n=255, GLD n=192, O39.SI n=287, SOL n=170, PANW n=53…) shrinks to
GLD and O39.SI once the replication is removed. The rest were 4–8 days of one
standing view counted many times over.

---

## 4. Four learning loops that have never produced an output

BRAIN.md and FORMULA.md describe a system that curates its own weights from
evidence. In production, every one of those loops is either frozen, saturated,
or measuring something other than what it claims.

### 4.1 The formula has never been fitted, and RLS has moved θ by exactly zero

`data/formula.json`, last written **2026-08-13**:

```json
"weights": [0.0, 0.02, 0.015, 0.02, 0.03, 0.015, 0.01, 0.008],
"version": 1, "fitted": false,
"rls": {"n": 8, "theta": [0.0, 0.02, 0.015, 0.02, 0.03, 0.015, 0.01, 0.008]}
```

`θ_rls` is bit-identical to the hand-set prior. `journal.db.outcomes` holds
**0 rows** — the table RLS learns from. §4.28 recorded this on 08-17; four days
later it is unchanged. `params` holds 20 rows, all from 2026-08-04, all
identical.

The feature vector is also **stale**: 8 features, missing both `trend_zscore`
(added 08-15) and `regime_persistence` (added 08-18). FORMULA.md §8 states
`regime_persistence` is "deployed at weight 0, computing and logging on every
cycle." It is computing; it is not in the saved model, because the model has
not been saved since before it existed.

So the whole two-loop architecture in FORMULA.md §4 — ridge walk-forward
curation plus online RLS maturation — has produced **no weight change in the
26 days the system has been live.** The engine is running on hand-set priors
and always has been. That is not a defect in the design; it is a defect in the
claim that the design is operating.

### 4.2 The calibrator has issued zero verdicts on 643 scored relationships

`data/edge_calibration.json`, generated 02:40 today:

```json
"summary": {"scored": 343, "paths_scored": 300,
            "supported": 0, "contradicted": 0, "unproven": 343}
```

Every edge and every path is `unproven`. `MIN_N = 20` and the typical edge sits
at n=16–17 — because an edge only scores on days its source node was
*activated* above `MIN_ACT`, so ~26 calendar days yields ~16 scoring days.

BRAIN.md §4d answers the "hand-set weights" limitation with: *"Addressed in v3:
`brain/calibration.py` scores every curated influences-edge against realized
forward returns and demotes the contradicted ones."* **After 26 days it has
demoted nothing and promoted nothing.** The mechanism is built and correct; it
has simply never reached its own threshold. It will start issuing verdicts in
roughly 4–8 days — at n=20, where a t-test has almost no power, and where
§1's overlapping-window problem applies to `_score_pair` too.

### 4.2b The expected-move gain is pinned at its ceiling

`data/edge_calibration.json` reports `"gain": 2.0`. In `calibration.py`:

```python
gain = max(0.25, min(2.0, rm / pm))     # rm = median realized, pm = median predicted
```

**2.0 is the clamp, not an estimate.** Realized moves are at least twice the
size the graph predicts, and the calibrator is saturated so it cannot say by
how much — the same blind-spot shape as §4A's `RATIO_CLIP` entry, in a
different module.

This lands directly on the sleeve. §4A's "32:1 risk/reward is inverted" rests
on `expected_move ≈ 0.3–0.5%` against a 10% stop. If the model systematically
under-predicts magnitude by ≥2×, then either the true expected move is larger
than the ratio assumes (the asymmetry is less bad than filed), or the gain
correction is silently rescaling every `expected_move_pct` the adviser
publishes by a clipped constant. Today's advice shows `expected_move_pct:
−4.79` on A17U.SI against `vol_daily: 0.013` — a 3.7σ five-day move as a
routine top-ranked call, which suggests the second reading. Worth resolving
before the sleeve's risk/reward is judged either way.

### 4.3 The per-symbol reliability weight has no memory and is pinned at its bounds

`scorecard.py`:

```python
R_MIN, R_MAX, R_ALPHA = 0.5, 1.4, 0.12
for o in outcomes:                    # <-- every row, not every call
    target = R_MAX if o["hit"] else R_MIN
    new_r = r + R_ALPHA * (target - r)
```

The loop steps once per **outcome row**. With 65 rows per symbol-day, the EMA
takes 65 steps a day, retaining `0.88^65 = 0.00026` of yesterday. It is not an
exponential moving average; it is a **same-day step function** that slams to
0.5 or 1.4 depending on the last day's result.

Live confirmation — 122 symbols in `data/reliability.json`:

```
pinned at ceiling 1.40    27
pinned at floor   0.50    29
                          --
46% at a bound
```

`NVDA: {"r": 0.506, "n": 244}` — the adviser is currently multiplying its
conviction on NVDA by 0.51, near the hard floor, on a name the event sleeve has
traded profitably and which the graph reaches over 572 paths. This weight feeds
`reliability_weights()` → adviser conviction → `weight_suggestion`. It is
actively distorting sizing today, in favour of nothing.

### 4.4 The emotion calibration is measuring drift, not emotion

`data/emotion_calibration.json`:

```json
"panic_rebound":  {"coef": 1.0, "basis": "measured", "n": 922, "mean": +0.01192, "tstat": 10.75}
"euphoria_fade":  {"coef": 1.0, "basis": "measured", "n": 360, "mean": +0.01118, "tstat":  5.17}
```

BRAIN.md §4f.4 says *"'Be greedy when others are fearful' is tested, not
assumed."* The test returns **+1.19% after panic events and +1.12% after
euphoria events** — the same answer, to within noise, for opposite emotions.
It has found the sample's average forward return, not an emotion effect.

Three reasons it cannot find one as built:
1. **No benchmark.** `event_outcomes` stores `realized_ret` only; `hit` is
   defined against zero, not against the market. The advice scorecard learned
   this lesson explicitly in its own `_BENCH` comment ("a blended 0.404 hit
   rate sat unexplained in the docs for days because of it"). `event_outcomes`
   never got the same treatment.
2. **No control group.** Post-panic return is compared against a fixed prior,
   never against the unconditional post-*any*-event return (+1.39%). Against
   that baseline, both effects are ~0.
3. **The t-stats are inflated** by the same replication as everything else.

Both coefficients are clamped at 1.0, so the contrarian composer currently
applies its maximum boost to *buying panic* and its maximum boost to *fading
euphoria* simultaneously, on evidence that distinguishes neither. Meanwhile
`event_outcomes` by emotion shows euphoria as the **highest**-hitting tag
(0.659, +2.45%) — i.e. what the layer is built to fade.

### 4.5 A minor one: learned source trust is fragmented by a formatting bug

232 of 36,161 events store `source` bracketed — `[scmp.com]`, `[theguardian.com]`
— so `learned_trust.json` carries both variants and splits each feed's
evidence across two buckets:

```
"rss.panewslab.com":   {"n": 200, "hit_rate": 0.650, "trust": 0.702}
"[rss.panewslab.com]": {"n":   2, "hit_rate": 1.000, "trust": 0.7}
```

Small today (0.6% of events), and it inflates trust for the bracketed twin off
n=1–2 samples. Worth a normalization at write time.

---

## 5. Missed opportunities — where the money actually went

### 5.1 The brain's best calls are in the markets it cannot trade

Conviction-long calls by market, and whether the symbol was ever held in *any*
book's journal:

```
market      n      hit     avg_exc     tradable?
KS        815    0.983      +9.39%     no  (Korea — never reachable)
T         265    0.985      +6.77%     no  (Tokyo — never reachable)
SI        287    0.986      +3.61%     reachable since 08-17, never ordered
HK        476    0.464      +3.04%     reachable, 1 order placed
US       2076    0.584      +1.46%     yes — and its WORST market
```

Eleven conviction-long symbols were never held in any book: weighted hit
**0.750**, weighted excess **+3.77%**. The largest are `005930.KS` (Samsung,
hit 1.00, +9.83%), `9984.T` (SoftBank, 0.98, +6.77%), `2899.HK` (Zijin, 0.67,
+5.77%), `O39.SI` (OCBC, 0.99, +3.61%), `MU` (1.00, +12.79%).

**Two honest caveats, and they cut hard.** First, these `n`s carry the same 65×
replication — deduplicated, `005930.KS` is 4 distinct issuance days, not 396.
Second, Korea and Japan are one trade, not many: Samsung, SK Hynix and SoftBank
are the same AI-memory supercycle, and getting it right once in April looks
like 1,480 correct calls in this table.

What is *not* an artifact is the ordering. The brain's hit-rate is highest in
Korea and Tokyo (0.98), middling in Singapore, and lowest in the US (0.584) —
**inversely ranked with its ability to place the order.** Its edge is
concentrated in exactly the names that get the least Western analyst attention,
which is where you would expect a cross-asset macro model to have an edge, and
those are the ones the venue restriction blocks.

`O39.SI` is the cleanest single case: 8 distinct days, hit 0.88, +2.59%
excess, t=+3.0 — one of only 9 statistically real calls in the whole record,
in a market that has been reachable since 08-17 and where **no order has ever
been sent**. §4B files this as "not data-gated — this is a deliberate action,
not a wait." It has been waiting since 08-15.

### 5.2 The short side has cost real money and is still on

Deduplicated, `short_or_avoid` conviction hits **0.414 against 0.462 for
low-conviction** — the more sure the brain is, the more wrong it is. Corroborated
by `event_outcomes` sign=−1 at 0.442. Five of the nine statistically significant
symbol calls are significantly-wrong `avoid` calls (TSLA, 9880.HK, MP, ETH/USD,
plus UNI long).

Meanwhile `CRYPTO_EVENT_SHORT` was turned on 2026-08-20 at the user's explicit
request, against the strategy's own twice-rejected gauntlet evidence. Its first
result:

```
crypto_event_journal: 2 sells, realized −$201.52, win-rate 0.00
equity 10,000 -> (basis change to 4,999.89) -> 4,790.52
```

Two trades, both losers, −4.2% of the book in one day. Two trades prove
nothing — but they are pointing the same direction as the gauntlet, the
advice record, and the event record. Flagged per the `.env` note rather than
left to be forgotten.

### 5.3 43% of live orders are being rejected

`journal.db.orders`: **39 filled, 34 rejected, 6 pending.** 21 of the rejects
are `qty < 1 share`; **10 are `code=602035 Wrong bid size, please change the
price`** — the code §4.23 was about.

**It is not §4.23 recurring, and it took reading `submitted_price` to see
that.** On 2026-08-20 three `1024.HK` orders went out at HK$34.05, HK$34.15 and
HK$34.10; the first two were rejected and the third filled. All three are legal
multiples of the HK$0.05 spread `tick_size()` correctly returns for a HK$34
name, and all three were snapped correctly on the way out. **The cause is
unknown** — snapping harder would fix nothing, and the obvious diagnosis is the
wrong one.

Two `pending` orders from 08-19 (`USO`, `1810.HK`) still sit
`[unconfirmed after 4 checks]`.

### 5.4 A quarter of every cycle's decisions are structurally unexecutable

```
2026-08-20   flat 18,139   short 10,633   long 10,278
```

~10.6k short decisions a day, none of which can execute — stock shorts are off
at the venue for all three books (`SHARED_ACCOUNT.md`). This is §2's
"uniformly bearish model that cannot short" still true, now measured: roughly
27% of all decision work is discarded on arrival.

### 5.5 The crypto book's equity dropped 10,052 → 4,999.89 with no declared basis

```
crypto_journal.jsonl:  2026-08-19  10,052.20
                       2026-08-20   4,999.89
```

This is not a loss — it is the switch to the live Binance Futures testnet
account, which holds $5,000. But it is written into the equity journal as a
mark, so anything reading that curve sees **−50.3% in one day**. This is
precisely §4.14 ("a change of book size read as a 90% crash"), whose fix was
"declared basis, never inferred." The declaration did not happen on this
transition. Drawdown logic, the circuit breaker (`scripts/breaker.py`) and the
watchdog all read this curve.

---

## 6. What could have been avoided

Ranked by cost, not by blame. The through-line is the one the failure register
already names — **every item here was silent and passed its own health checks.**

| # | What | Could it have been caught? |
|---|---|---|
| 1 | Two full scorecard reviews reached opposite conclusions about the short side, because both read 65×-replicated `n` | Yes, cheaply: one `count(distinct symbol‖day)` next to every `count(*)`. The 08-12 → 08-15 reversal on the *same underlying mechanism* was itself the warning sign, and was noted ("it reversed direction between the two reviews") without the replication being suspected. |
| 2 | `UNI/USD` root-caused as "no graph node" when the node exists; four identical cases left running | Yes. The fix was verified on the symptom (0 calls since 08-16 — confirmed) but never on the stated cause. `FET`, `BCH`, `HYPE`, `ATOM` were visible in the same query that found UNI. |
| 3 | The formula's learning loop has never run, for 26 days | Partly. §4.28 recorded `outcomes = 0 rows` on 08-17. It was filed as an observation, not as "the central claim of FORMULA.md is not operating." |
| 4 | 212 inert nodes, 104 duplicate signatures, and a `none` transmission hub | Yes — this is exactly what `graph_gap_scan.py` and `cluster_gap_scan.py` were built for, and `cluster_gap_scan.py` was committed *yesterday*. Neither has been run against the live graph. |
| 5 | The LLM-edge cue (328) fired ~5 days early, at double the assumed rate, with 0 edges ever reviewed | Yes, structurally: §4B's cue requires a human to run `review_edges.py --stats`, and the review queue built in §4.22 has never been used once. Every cue in §4B except the adviser gate has this same property — it fires only if someone remembers to look. |
| 6 | 10 orders rejected `602035`, cause still unknown | **No — and the obvious answer is the wrong one.** The natural read is "§4.23's tick defect, on a board it was never proven against". It is not: the prices sent were legal ticks. What *could* have been avoided is being unable to tell — the request context a diagnosis needs was never journalled, which is the same reason §4.23 itself cost eight orders before anyone could see it. |
| 7 | The crypto book's basis change written as a −50% equity mark | Yes. §4.14's own lesson is "declared basis, never inferred," and the broker migration on 08-20 was a deliberate, planned basis change. |

---

## 7. So — is there enough data to update the brain?

Directly, per question, because the answer differs sharply by layer:

| Question | Enough data? |
|---|---|
| Is the long side real? | **Nearly.** t=2.39 deduplicated, t≈1.07 after overlap correction, corroborated by `event_outcomes` (+1 at 0.671) and by $1,146 realized in the sleeve. Three independent instruments agreeing at marginal significance each is worth acting on cautiously; it is not worth calling proven. |
| Is the short/avoid side broken? | **Yes — this one is now settled enough to act on.** Deduplicated advice (conviction 0.414 < non-conviction 0.462), event outcomes (−1 at 0.442 vs +1 at 0.671), and five of nine significant symbol calls being wrong `avoid`s all agree. Three instruments, same conclusion, opposite direction from the noise. |
| Can per-edge weights be calibrated? | **No, and not for another ~4–8 days.** 0 of 643 verdicts. Even then, n=20 with overlapping windows will not support the ×1.15/×0.5 adjustments it is designed to apply. `MIN_N` needs raising, not waiting on. |
| Can per-symbol reliability be learned? | **Not as built.** The estimator is broken (§4.3) independently of sample size. Fix the estimator first; the data is fine. |
| Is the contrarian/emotion layer validated? | **No, and more data will not help.** The measurement has no benchmark and no control group (§4.4). It would return the same non-answer at n=10,000. |
| Should the sleeve's 32:1 be revisited? | **Not yet, and this is the one place to be patient.** 16 legs, 0 stop-outs, §4B's cue is 15 *cycles* (≈5–6 so far) or the first stop-out. The +$1,146 is real and the tail risk is untouched. |
| Cross-book capital allocation? | **No.** §4B dates a loose read at ~2026-10-05. Nothing here changes that. |

---

## 8. Recommended updates, in priority order

Ordered by (evidence strength × live impact). Items 1–5 are measurement and
data-integrity fixes — they change what the system *knows*, not what it
believes. Items 6–8 change decisions and should go through the project's own
gauntlet discipline before deploy.

**1. Deduplicate the scorecard at the source.** Grade one advice row per
(symbol, direction, calendar day) — the latest, or the first. Backfill a
`dedupe_key` and rebuild the derived stats. This is prerequisite to everything
below, and it *lowers* every reported n by ~65×, which will look alarming and
is correct.

**2. Raise `adviser_gate.min_n` in the same commit.** With deduplication,
`min_n: 500` becomes unreachable; the honest bar is ~60–100 deduplicated
observations *and* an overlap-corrected t. Do not let the gate flip on the
old arithmetic — it is ~15 days from doing so.

**3. Fix the reliability EMA (§4.3).** Step once per (symbol, day), not once
per row. Consider re-seeding `reliability.json` to 1.0 — 46% of it is currently
pinned at a bound on ~1 day of memory and is distorting live sizing.

**4. Give `event_outcomes` a benchmark.** Reuse `scorecard.benchmark_for()` —
the logic exists and is well-reasoned. Then re-run the emotion calibration
against a proper control (post-any-event return), and expect both
coefficients to collapse toward 0.

**5. Clean the graph, and bound the digester.** Delete the `none` node and its
23 edges — and note that a shape-based filter run against the live graph found
**14** such placeholder nodes carrying 37 edges, not the one visible by eye
(`6_unnamed_financial_institutions`, `unnamed_international_bank_syndicate`,
`undisclosed_client`, `private_investors`, two Bezos consortia…). Triage the
212 inert nodes —
wire the real companies, delete the news-vocabulary ones. Then deal with the
cause rather than the queue: at **88 proposals/week with 0 ever reviewed**, the
review mechanism is not a control surface, it is a backlog. §4A already
identifies the fix as "the digester's proposal bar" and correctly calls it a
judgement about how much self-wiring is wanted. That judgement is now overdue —
LLM wiring reaches parity with curated wiring in ~5 weeks at this rate, not the
~14 weeks §4B projected.

**6. Stop sizing indistinguishable names as independent bets.** 13 of 17
coins, and 104 assets overall, are exact duplicates of a peer. The real fix is
differentiating wiring (L1 vs DeFi vs AI-token vs payments; ETH-beta vs
BTC-beta) and that is a curation project. The immediate fix is honesty about
what the graph knows: field conviction scaled by 1/√(group size), the standard
correlated-positions adjustment and the same reasoning as the fragility dial's
√HHI. A view held identically across N names is one view, not N — and sizing
each as independent is how a "diversified" book ends up holding one position
five times.

**Explicitly NOT recommended, on second look:** adding FET/BCH/HYPE/ATOM to
`CONFIRMED_MISCALIBRATED`. Their raw records look damning (`FET/USD` long
n=526, hit 0.00) — but deduplicated they are **5, 3, 2 and 13 distinct days**,
none significant. Acting on those numbers would be committing the exact error
§1 of this review is about. `UNI/USD` stays because it survives the correction:
12 days, hit 0.17, t=−2.97.

**7. Act on the short side.** Three instruments agree conviction is
anti-predictive there. The cheapest correct response is to stop *sizing* on
short conviction (treat `short_or_avoid` conviction as flat) rather than to
invert it — inverting a 0.414 is fitting to 55 observations. Note this also
frees the ~27% of daily decisions currently discarded.

**8. Place one non-USD order.** `O39.SI` is one of nine statistically real
calls in the entire record, hit 0.88, and the market has been reachable for
four days. §4B says this is a decision, not a wait. The same applies to the
10 outstanding `602035` rejects, whose cause is now instrumented but not yet known.

**9. Make the §4B cues self-checking.** Two cues fired unnoticed in this review
(LLM edges at 354 vs 328; the sleeve's cycle count) because they are checked by
a human running a script. The adviser gate is the only cue in that table that
watches itself, and it is the only one that has never been missed. The pattern
already exists (`ai-investing-adviser-gate.timer`); extend it to the cues that
are pure arithmetic — edge counts, cycle counts, distinct-issuance-days,
PRX.AS's −8.5% line — and leave only the genuine judgement calls to a person.

**Not recommended:** re-running `--optimize --save` to unfreeze the formula.
The learning loop being dead (§4.1) is a real defect, but fitting θ on a
26-day, 65×-replicated, single-regime sample is how you get a confidently
wrong model. Fix the measurement layer first, then let the Deflated-Sharpe gate
do its job on clean data.

---

## 9. What this review is not

It is 26 days of one regime — SPY +0.64% then −0.77%, never the ≤−3% down-week
§4B asks for. The graph probe in §2 used single-node shocks without regime
gates, τ-delays or the persistent field, so the real system differentiates
somewhat more than 42.4% — but only 18 of 1,156 edges carry gates, so not much
more, and co-members with identical wiring will still track together by
construction.

Nothing here was re-fit and nothing was simulated. Where the evidence is thin
the review says so, and the thinnest evidence of all is the thing this system
most wants to be true: that its long side is real.

---

## 10. What was implemented, and what it changed on the live box

*All eight recommendations were applied the same day, in five commits
(`bfb77d2`, `3039b95`, `44585db`, `27f7d2f`, `8049432`), deployed to the
ProDesk, and verified against the live state. All 57 test files pass on both
machines under the project's own runner.*

**The counting unit** (`bfb77d2`). `advice_outcomes` gains `issue_date` and
`is_primary`; every row is still written and auditable, and exactly one per
(day, symbol) — the first call of that day — may be counted. The migration ran
on the live 194MB database in 0.1s:

```
scorecard: labelled the counting unit — 42,882 graded rows collapse to 634
distinct (day, symbol) observations (67.6x replication, now excluded from stats)
```

`adviser_gate` now counts observations on both sides. It had two code paths that
first disagreed by 8 of 90 — one partitioned before filtering and the other
after — which is the same defect in miniature; they now agree exactly. `min_n`
moved 500 → 80, in the new unit. The measured effect on the live gate:

```
                 before          after
adviser_long     n=4,040         n=90      hit 0.622, 15 days
```

Still not eligible, and now for an honest reason: `min_days: 30` is the binding
constraint, as it always was in practice.

**The reliability EMA** now steps once per (symbol, day). `reliability.json` was
re-seeded to neutral — the old file is kept at
`data/retired_reliability_saturated_20260821.json`. It had **56 of 122 symbols
pinned at a bound**; it now has zero, and the weights it accumulates from here
carry a ~5–6 day half-life instead of a same-day one.

**The emotion layer, measured against a control group** (`8049432`). This is the
single largest change to a live sizing input, and the answer came from the
system's own record:

```
before   panic_rebound   coef  1.000   mean +1.192%   tstat 10.75
         euphoria_fade   coef  1.000   mean +1.118%   tstat  5.17

after    panic_rebound   coef  0.000   lift −0.00038  t −0.24   measured-contradicted
         euphoria_fade   coef −0.167   lift −0.00115  t −0.50   measured
```

Panic events return +1.192% against an ordinary event's **+1.230%**. "Be greedy
when others are fearful" was running at its clamped maximum on a lift of
−0.0004. Measured against a control it is **zero**. The euphoria fade survives,
correctly signed, shrunk from a clamped −1.0 to −0.167.

`event_outcomes` also gained the benchmark columns it never had. Note what the
report honestly says today — `return_basis: "absolute (excess column empty)"` —
because the 25,372 existing rows predate the migration and only new rows carry a
benchmark. The numbers above will move again as market-relative rows accumulate,
and the label will say so.

**The graph** (`3039b95`). A shape-based filter (not a blocklist — a blocklist
catches `none` and misses `unnamed_acquirer`) found **14 placeholder nodes
carrying 37 edges**, not the one visible by eye:

```
none                                23 edges
saudi_led_investor                   2
6_unnamed_financial_institutions     1
unnamed_international_bank_syndicate 1
undisclosed_client                   1
private_investors                    1
multiple_banks                       1
... and 7 more
```

All pruned and every edge tombstoned, so the next digest cannot re-add the same
wiring. Propagation is unchanged (`ai_capex_cycle` still reaches nvda 0.7581,
tsmc 0.5858, avgo 0.5488). The live graph is **602 nodes / 1,119 edges** with 39
tombstones. Self-wiring now carries a **6/day budget** — a control on volume,
which unlike review needs no human; budget-refused edges are deferred, not
tombstoned, because nothing about them was judged wrong.

**Sizing** (`44585db`). Field conviction is scaled by 1/√(group size) for names
the graph gave an identical impact — the standard correlated-positions
adjustment. On a `crypto_liquidity` shock that is 28 of 34 touched assets.

**The short side.** A bearish adviser score can no longer add size to a short.
It may still shrink one. It is not inverted.

**Book basis** (`44585db`). All four books now declare which book a mark belongs
to, via one shared rule rather than four copies (§4.10's lesson). A venue change
is stamped on the mark where it happens, so the next 10,052 → 4,999 step arrives
already explained instead of reading as −50% to the breaker and the watchdog.

**Self-checking cues** (`27f7d2f`). `scripts/cue_check.py` +
`ai-investing-cue-check.timer`, installed and enabled (next fire 09:40 SGT).
Four cues that need no judgement to *evaluate*, notifying only on a state
change. First run:

```
  --  llm_edges_vs_curated             317 llm vs 802 curated (110/wk)
  --  sleeve_risk_reward               16 clock exits, 0 stop-outs, $1,146.21 realized
  --  reliability_issuance_days        17 distinct issuance days, 634 observations
  --  edge_calibration_first_verdict   0 decided of 343 scored (gain=2.0)
```

### 10.1 Two recommendations deliberately not followed

**FET, BCH, HYPE and ATOM were NOT added to `CONFIRMED_MISCALIBRATED`**, which
§8 item 6 originally proposed. Deduplicated, they are **5, 3, 2 and 13 distinct
days** — none significant. Acting on their raw records (`FET/USD` long n=526,
hit 0.00) would have been the exact error §1 of this review is about. `UNI/USD`
stays because it survives the correction: 12 days, hit 0.17, t=−2.97. The
structural fix (the 1/√group discount) covers the class without asserting a
per-symbol verdict the evidence cannot support.

**The 602035 order rejects were instrumented, not "fixed."** The obvious
diagnosis — §4.23's tick defect on a board it was never proven against — is
wrong: the prices sent were legal ticks. The cause is unknown, so the rejection
now carries the tick and reference price a diagnosis needs, rather than a change
that would have looked like a fix and done nothing.

### 10.2 Still open after this pass

- **The formula has still never learned anything.** `journal.db.outcomes` is
  still 0 rows and θ is still the hand-set prior. Deliberately untouched: §8's
  "not recommended" stands — fitting on a 26-day single-regime sample is how you
  get a confidently wrong model, and now that the measurement layer is fixed,
  the right move is to let clean data accumulate first.
- **The calibrator has still issued 0 verdicts** and `gain` is still pinned at
  its 2.0 ceiling. `MIN_N=20` will start producing verdicts within days, at a
  sample size that cannot support them; raising it is a judgement call left
  open rather than made silently here.
- **212 inert nodes** remain. The 14 placeholders are gone; triaging the rest
  (wire the real companies, delete the news vocabulary) is curation work, not a
  code change.
- **`O39.SI` still has no order.** That one is a decision, not a wait.
