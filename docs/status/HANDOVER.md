# Handover — resume here

**Written 2026-08-22. HEAD `2b24e58`, deployed and running on the ProDesk.**

This is the *resume-here* document. It is deliberately short and it points at
the detail rather than repeating it.

| If you want | Read |
|---|---|
| **What is broken right now** | [`STATE_OF_THE_SYSTEM.md`](STATE_OF_THE_SYSTEM.md) **§4A** — the live open list. §4 is history. |
| **When each open item is ready to act on** | Same file, **§4B** — every row names a number, a date, or an event. |
| **Why any of it was done** | [`BRAIN_REVIEW_2026-08-21.md`](BRAIN_REVIEW_2026-08-21.md) — the analysis. |
| **What was done, and what I got wrong** | [`SESSION_REVIEW_2026-08-21.md`](SESSION_REVIEW_2026-08-21.md) — the work record. §2 is the mistakes, §7 is the open split, §11 is the delegated decision. |
| **How to measure any of this yourself** | [`../design/AUDITING.md`](../design/AUDITING.md), then `scripts/brain_audit.py`. |

---

## 1. Deploy state — CURRENT, nothing pending

The ProDesk woke on schedule at **07:30 SGT on 2026-08-22**, pulled, and is
running **`2b24e58`**. Engine `active`, no failed units.

*(Historical note, because the correction is the useful part: the deploy was
left pending overnight when the box powered off mid-session. On the resume, one
prediction I had written here was wrong in wording — `brain_audit.py` showed as
`M` in `git status`, not clean. The content was byte-identical to the committed
version; it read as modified only because the box's HEAD predated that commit.
Verified by comparing sha256 on both sides before discarding the working copy.
**Compare the hash, do not trust the prediction.**)*

Both post-deploy checks were run, and **the second one failed, correctly** —
see §1.1.

```bash
# the routine health check, any time
ssh prodesk 'cd ~/Projects/AI-Investing && systemctl --user is-active ai-investing.service'
ssh prodesk 'cd ~/Projects/AI-Investing && .venv/bin/python scripts/brain_audit.py --section learning'
```

### 1.1 The basis cue fired NEGATIVE, and it was right — §4.52

The one open cue was: *does the next daily mark carry a `basis` field?* It did
not. That row had said in advance what a missing field would mean — **a live
defect, not a timing artefact** — so there was nothing to argue about.

```
stock_journal.jsonl   "event": "mark", "equity": 10001.71 ...      no basis
invest_journal.jsonl  "event": "mark", "basis": "BookBroker:book"  DECLARED
```

The second line is what made it real: the investing book declared its basis on
the **same cycle**, so the mixin demonstrably worked — the missing one was a
path, not a delay. `stock_journal.jsonl` is written by the **runner**, not by a
book: a fifth journal nobody counted, and the one the watchdog and
`daily_status.py` actually read.

Fixed, three mutations verified, closed. **Sixth instance of
one-of-N-paths-fixed.**

**The transferable lesson is about the cue, not the code:** a cue is only worth
writing if its *negative* answer is written down too. "No basis yet" was true
the evening before and false the morning after, and only the pre-written
verdict told them apart.

---

## 2. What this session actually did

```
                     START (e327d65)      NOW (2b24e58)
register entries          §4.36               §4.52        (16 new)
§4A open rows              19                  15
test files                 54                  65
tests                  one runner only     682, BOTH runners, BOTH machines
```

**Sixteen defects found and fixed (§4.37–§4.52).** Five of them were found only
because an earlier one taught us where to look. Four false alarms are recorded
at the same length as the fixes, because a review that records only its hits is
not a measurement.

**Two of the sixteen I caused myself, during this session:**
- **§4.48** — my `parse_args(argv)` refactor killed the X capture channel for
  two hours, and the guard written in the same commit passed the whole time.
- **§4.50** — a cleanup rule I wrote deleted **Procter & Gamble** from the live
  graph. Restored.

Both are written up in full. They are the two most useful entries in the file.

### The recurring shapes, which matter more than any single fix

1. **One-of-N-paths-fixed — six times** (§4.14, §4.23, §4.36, §4.49, §4.51,
   §4.52). A defect gets fixed where it was *observed* and nowhere else. The
   0.0 price sentinel was removed from the live path in the morning and left
   standing in the shadow path, in the same file, eight hours later. **This is
   the single most productive question to ask of any fix in this codebase:
   where else does this pattern live?**
2. **A ratio without its null is not a measurement — three times** (§4.6 needed
   a benchmark, §4.44 a control group, §4.51 a noise floor). Same question
   every time: *compared with what?*
3. **A test is not evidence until you have watched it fail.** Eight tests this
   session passed with the bug reintroduced. Mutation testing is now the
   standing rule in `AUDITING.md`.

---

## 3. Decisions you delegated, and what I did with them

You gave me two calls. Recording both, because the reasoning is the part worth
keeping.

### 3.1 The gain ceilings — **DECIDED: hold. Do not raise.**

Full reasoning in [`SESSION_REVIEW_2026-08-21.md`](SESSION_REVIEW_2026-08-21.md)
§11 and register §4.51.

**The short version, and it reverses what I told you earlier in the session.**
I had called the saturated gains *"the single largest open risk to returns"* on
the strength of §4.45's finding that realised moves ran 14× the expectation.
Before acting I ran the control §4.45 never had:

```
median |realised / expected|             14.4
median  own-5d-volatility / expected     15.5   <-- what PURE NOISE produces
directional hit rate                      0.526  (n=19 — a coin flip)
```

Indistinguishable. `expected_move` is the move **attributable to the event**;
`realized_move` is the asset's **total** five-day move, which its own volatility
dominates. The ratio measures signal-to-noise, not calibration error.

Raising the gain to close it would need a gain above 13, at which point every
`expected_move` asserts the model predicts the asset's **entire five-day
range** — and that number feeds position sizing, the sleeve's risk/reward and
stop distances. It would have inflated all three on a 52.6% hit rate.

**This is now enforced, not just recorded.** `brain_audit.py` prints the ratio,
the noise floor, the hit rate and the conclusion together, and a test refuses to
let the ratio be published without its control.

**What would re-open it:** the observed ratio falling **below** its noise floor
while the hit rate rises. That is a graph-wiring outcome, not a sample-size one
— which is why the old cue ("revisit at 50 settled claims") was also wrong and
has been corrected.

### 3.2 `O39.SI` — **NOT PLACED, and this one is still yours**

The single qualifying long, blocked only because the live slice is USD-only.

I did not place it, deliberately: **SGX was closed for this entire session.** A
first-ever order on an unproven market path would have rested overnight and
filled unattended at an open nobody was watching — the opposite of what the
order is for. Its whole value is proving submit → fill → stop → exit *while
someone is watching it*.

**It needs SGT market hours (09:00–17:00 SGT), and it is a live-ish order on a
routed paper account, so I want you to say go before I place it.**

### 3.3 Judgement calls I made inside the work, for the record

| Call | What I decided |
|---|---|
| Formula refit | **Hold.** Refitting on a 26-day single-regime sample whose measurement layer was only just corrected is how you get a confidently wrong model. |
| Orphan-node collection age | **30 days.** A node minted today may be wired tomorrow; one unwired for a month is vocabulary. Shorter would fight the digester and re-open §4.24 from the other side. |
| `_and_` as a non-entity marker | **Declined.** `larsen_and_toubro` is one company. Pinned by a test so nobody adds it later — and then I shipped a *different* rule with the same failure mode anyway (§4.50). |
| `allow_nan=False` on every state write | **Yes**, after scanning all 99 live state files to confirm nothing legitimately writes one. |
| Tombstones on collected orphans | **No.** A tombstone records a rejected *claim*; nothing was ever asserted about these nodes. |

---

## 4. What is outstanding — 16 open rows, by what they actually need

§4A is the authority. This is the same list grouped by *what kind of thing it
is*, because "still open" was hiding four different situations.

### 4.1 Needs a decision from you (2)

| Item | What it turns on |
|---|---|
| **`O39.SI` / non-USD trading** | §3.2 above. Not data-gated — one small order in SGT hours proves the path, exactly as `F` proved the US leg. |
| **The self-wiring BAR** (not the budget) | The 6/day budget caps the *rate*; nothing caps *quality*. 320 LLM edges, **all 320 unreviewed**, and the calibrator cannot reach them (none terminates on a tradable symbol). How much self-wiring do you actually want? |

### 4.2 Waiting, each with a cue that fires on its own (5)

| Waiting on | Cue |
|---|---|
| **First edge verdicts** (§4.47) | ~2 months, `MIN_N = 60`. **Read the first batch by hand** — a bar chosen by reasoning is still a bar nobody has watched fire. |
| **Formula refit** (§4.28) | Deliberate hold. Let clean observations accumulate, then let the Deflated-Sharpe gate decide. |
| **Adviser gate** | n=90, hit 62.2%, **15 of the 30 days** required. Self-checking on a timer. |
| **Sleeve's true risk/reward** | Re-derive from `ratio_true`, **not** `expected_move`. And note §4.51: the 32:1 was always a measurement artefact. |
| **`602035` rejects** | Instrumented. Next occurrence will say why. §4.23 tick-snapping is ruled out. |

### 4.3 Curation — real work, no cleverness available (3)

| Item | Note |
|---|---|
| **200 inert assets** | Now has a *mechanism* (shape refusal + 30-day collector), but the collector removes nothing until ~2026-09-04: all 31 unwired nodes are under 30 days old. This is **churn**, ~2/day, not an accumulation — which corrected my own framing. |
| **104 assets duplicating a peer** | The graph tells apart 202 objects and holds 464. |
| **320 unreviewed LLM edges** | `review_edges.py`. The queue was built in §4.22 and has **never been used once, on any edge, ever.** Unlike the node work, no rule substitutes for judgement here. |

### 4.4 Known and accepted, or low priority (5)

`θ` reset to v1 · three dormant candidate signals · the digest brief's golden
set (narrowed — needs an Anthropic key neither machine has) · new-company
discovery's manual sweep · the LLM endpoint free-tier cap · git history still
contains the revoked string · one dangling ledger claim · no venue stops (mostly
by design; the real item is gap risk on ~$4,800 across the trading book).

---

## 5. The honest summary of what changed

**What moves money:** the crypto book can transact again (§4.41, it was frozen
at 100% cash); 40% of thesis capacity redirected to positions that can actually
open (§4.42); the routed book's equity is correct under margin (§4.36) — the
circuit breaker acts on that number and it was reading −$4,265 on a flat book.

**What prevents losing money:** a total feed outage stays loud (§4A); six
relationships not halved on three weeks of data (§4.47); expectations no longer
corrected in the wrong direction (§4.45); **and the gain ceilings not raised on
a number that was noise (§4.51)** — which on the day may be the most valuable
single decision in this session, because it is the one that would have been
irreversible and invisible.

**What did NOT change, and say it plainly:** the graph's *judgement*. No weight
was hand-tuned, the formula still runs on priors, and 200 assets are still inert
to every macro shock. What changed is that **the brain can now grade itself
honestly** — and every learning loop it has was reading corrupted grades.

**That is the precondition for improvement, not the improvement.**

**And the thing that should make you trust it less, not more:** fifteen defects
in one system that had 645 passing tests, two of them introduced by me during
the session itself. The defect rate is a function of how hard anyone looks. The
well is not dry.
