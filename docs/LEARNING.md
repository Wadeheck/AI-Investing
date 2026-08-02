# The learning architecture

*How this system improves itself while running 24/7 unattended. Written
2026-08-02, replacing six independently-invented feedback mechanisms with one
coherent design.*

---

## 1. The problem with what came before

Six learning loops existed, each added when a need appeared: RLS formula
weights, per-symbol reliability, source trust, edge calibration, emotion
coefficients, and (today) an expectation ledger. Each had its own update rule,
its own hand-picked minimum sample, its own bounds. None of them knew about
each other, none knew what regime it was learning in, and none could answer the
only question that matters for an unattended system: **how much capital should
this policy be trusted with tomorrow?**

That is not a learning system. It is a pile of thermostats.

## 2. What can actually be learned, and how fast

Learning must be separated by *timescale and sample availability*, because the
binding constraint here is data, not cleverness. The books close roughly 20-40
trades a month between them. Anything requiring hundreds of samples to be
significant cannot be learned online — it must go through the offline gauntlet.

| Level | What it learns | Sample need | Where it happens |
|---|---|---|---|
| **L0 Perception** | do the graph's edges predict? which sources are honest? | 30+ per edge | in-cycle calibrators (exists) |
| **L1 Calibration** | when we say "+2% in 3 days", is that the right size? | ~10 per policy | **the spine (fast loop)** |
| **L2 Policy skill** | does this policy have directional edge, in THIS regime? | ~20 per policy×regime | **the spine (fast loop)** |
| **L3 Allocation** | how much capital does each policy deserve? | derived from L2 | **the spine (weekly)** |
| **L4 Structure** | new nodes, new rules, new features | hundreds | offline gauntlet only |

The split that matters: **the fast loop adjusts sizing and expectations; only
the slow loop (walk-forward gauntlet, train/holdout/Pareto/preservation) may
change structure.** A live system that rewrites its own rules from a handful of
trades will destroy itself. A live system that adjusts *how much it bets* on
rules that were validated offline will not.

## 3. Reward and penalty — the exact contract

**Not raw P&L.** P&L rewards luck and size, and punishes good decisions that
met bad luck. The system grades *skill*, in three components, per settled trade:

1. **Direction** — was the sign right? This is the only true mistake, and it is
   weighted by conviction: being confidently wrong costs more than being
   tentatively wrong.
2. **Calibration** — realized ÷ expected. Systematic over-prediction is
   *corrected* (future expectations shrink), not punished. A policy can be
   perfectly skilled and badly scaled; those are different faults with
   different fixes.
3. **Cost-awareness** — a "win" smaller than its own frictions is not a win.
   The trade must clear its costs to score positive.

Score per trade ∈ [−1, +1]:

```
  +1   right direction, cleared costs, reached >= half the expected move
   0   right direction but undersized, or inside the cost noise
  -1   wrong direction  (scaled by conviction: -0.5 .. -1.0)
```

**Reward** = a larger share of risk budget and a higher size multiplier.
**Penalty** = a smaller share, down to a floor — never to zero, because a
policy at zero can never earn its way back, and a regime it is bad at will end.

## 4. Uncertainty is the governor

The dangerous failure of adaptive sizing is over-reacting to noise: eight lucky
trades is not evidence. So the spine never uses a point estimate. It keeps a
**Beta posterior** over "this policy gets the direction right" and shrinks every
adjustment by sample weight:

```
  p̂       = Beta posterior mean (Jeffreys prior — an untested policy is 50/50)
  shrink  = n / (n + N₀)          N₀ = 12   (half-influence at 12 trades)
  edge    = (p̂ − 0.5) × 2                    ∈ [−1, +1]
  size×   = clip(1 + shrink × edge × 0.8, 0.5, 1.4)
```

At n=0 the multiplier is **exactly 1.0** — a new policy trades its untested
prior honestly, neither favoured nor punished. Influence grows with evidence,
never exceeds the bounds, and one outlier cannot move it far because ratios are
clipped before averaging.

## 5. Regime conditioning — the thing that was missing

A policy that makes money in risk-on and loses it in risk-off does not have
"mediocre average skill"; it has **conditional skill**. Averaging across regimes
destroys exactly the information that would make it useful. So every claim is
tagged with the regime it was made in (`risk_on` / `neutral` / `risk_off`), and
skill is tracked per policy **and** per policy×regime. Sizing uses the
regime-specific posterior when it has enough samples, falling back to the
pooled one when it does not.

This is what lets the system learn "the event sleeve works in calm tape and
should stand down in panic" without anyone telling it.

## 6. Capital allocation — the meta-learner (L3)

Each policy's *risk budget* — its share of total capital — is recomputed weekly
from its skill posterior:

```
  weight_i  ∝ 1 + edge_i × shrink_i
  budget_i  = normalize(weight_i), clipped to [10%, 50%] of the total
  change    ≤ 5 percentage points per week
```

Floors, ceilings, and a rate limit, because the point is gradual reallocation
toward what works — not a scramble every time a week goes badly. This is the
mechanism by which the system genuinely *improves* rather than merely
persisting: capital drifts toward demonstrated skill, continuously, without
anyone watching.

## 7. Self-defence

An unattended learner needs to notice when it is broken:

- **Drift detection** — recent 20-trade calibration compared against the
  long-run. A policy whose live behaviour departs sharply from its own history
  is flagged `degraded`, cut to its floor budget, and reported.
- **Regime break** — if *all* policies degrade simultaneously, that is not six
  broken policies, it is a changed world: the system flags `regime_break` and
  requests offline revalidation rather than quietly re-fitting.
- **Existing hard limits stay above all of it** — 10% max loss per position,
  monthly high-water-mark ratchet, circuit breaker, per-book drawdown caps.
  Learning may *reduce* risk freely; it may only *increase* it inside bounds
  that learning cannot touch.
- **Nothing is ever deleted** — every claim and outcome persists in
  `data/expectations.jsonl`, so any adjustment can be audited or replayed.

## 8. The two clocks

```
  FAST (every trade)      calibration, skill posteriors, size multipliers
  WEEKLY                  capital reallocation across policies
  MONTHLY (offline)       the gauntlet re-runs on accumulated live data;
                          structure changes ONLY through train/holdout/Pareto/
                          preservation, exactly as today
```

The fast loop makes the system responsive. The slow loop keeps it honest. Live
performance is never used to tune structure directly — that is the same
discipline as the burned lockbox, applied continuously.

## 9. What it looks like in operation

`python3 scripts/book_report.py` shows, per policy: sample count, posterior
skill with its uncertainty, calibration factor, current size multiplier, risk
budget and any drift flags — plus which *drivers* (graph nodes) actually
predicted. That report is the answer to "how is it learning?" at any moment,
and it is designed to be readable by someone who has not been watching.
