# Documentation index

Organised by **what you are trying to do**, not by when it was written.

---

## Start here

| Read | When |
|---|---|
| **[status/STATE_OF_THE_SYSTEM.md](status/STATE_OF_THE_SYSTEM.md)** | Always first. Current state, every defect found and how, and — the part that matters — what is still **unverified**. |
| **[status/OPERATIONS.md](status/OPERATIONS.md)** | Running it. Which host owns the books, the SSH develop→deploy loop, systemd units, watchdog, backups. |

> **The books run on the ProDesk, not this machine.** `ssh -i ~/.ssh/prodesk_ed25519 eugene@100.64.113.103`.
> `data/` on a dev box is a stale snapshot — never read the portfolio from it.
> Deploy by committing here, pushing, and `git pull` there (needs `ssh -A`).
> See OPERATIONS.md → *Developing against it over SSH*.

Everything else explains *how a part works*. Those two explain *how much of it
is proven* and *how to keep it alive*.

**Is something known-broken?** `STATE_OF_THE_SYSTEM.md` **§4A — Open defects** is
the live list of what is wrong and not yet fixed. §4 is history; §4A is now. Before
2026-08-05 there was no such list and the honest answer to "how are the bugs
tracked" was *commit messages* — which had drifted thirteen commits behind.

**If something is wrong right now**, in this order:

```bash
python3 scripts/daily_status.py      # every channel, and whether it reaches the brain
python3 scripts/breaker.py           # is a book halted, and should it be
python3 scripts/needs_you.py --show  # what is waiting on you
python3 scripts/watchdog.py --test   # prove alerts still reach you
python3 scripts/review_edges.py --stats   # wiring the brain added to itself
```

The last one is periodic rather than urgent, and it is the only control over 18%
of the graph: llm-proposed edges are applied automatically (DIGESTION_SPEC §A10)
and the evidence calibrator cannot reach them. `--stats` reports the proposal
**rate** as well as the backlog — the rate is the number that says whether §A10's
design premise still holds, and it currently does not (§4A).

The two most likely alerts have their own runbook sections in OPERATIONS.md:
**🛑 CIRCUIT BREAKER** (do not just clear it — cross-check the marks first) and
**prices going to zero across the board** (usually do nothing; do *not* restart).

---

## `status/` — what is true right now

Kept current. If reality changes, these change with it.

- **STATE_OF_THE_SYSTEM.md** — architecture, the failure register, and the
  ranked list of what has never been verified.
- **OPERATIONS.md** — the runbook.
- **SCORECARD_REVIEW_2026-08-12.md**, **SCORECARD_REVIEW_2026-08-15.md** —
  periodic post-mortems of the live scorecard: is the brain's edge real or
  beta, per-book P&L pulled apart from the market it traded in, missed
  opportunities, what's confirmed working on a large enough sample to trust.
  Read the newest one first; each names what changed since the last.

## `design/` — how the system is built and why

Durable design intent. Changes only when the design changes.

- **BRAIN.md** — knowledge-graph semantics: origin-node tagging, propagation,
  decay, regime gating.
- **LEARNING.md** — the learning spine. Reward/penalty contract, uncertainty as
  the governor, regime conditioning, capital allocation. Read before touching
  anything that adapts.
- **FORMULA.md** — the adaptive scoring formula.
- **STRATEGY.md** — policy design across the four books.
- **SHARED_ACCOUNT.md** — `SHARED_STOCK_ACCOUNT`: several books safely sharing
  the one real Longbridge account. **Built and tested; still switched off.**
  Read before turning it on — it lists what changes and in what order.
- **PIPELINE.md** — how data flows end to end.

## `data-pipeline/` — getting the world into the brain

- **SONNET_DIGEST_BRIEF.md** — ⭐ the live operational prompt for the corpus
  digester, injected verbatim. **v1.5, 128 taggable nodes / 51 themes —
  verified against seed v25 on 2026-08-03.** If this changes, re-run the
  golden-set audit (§15) before trusting any output.
- **DIGESTION_SPEC.md** — the *design* behind digestion: division of labour
  between the tagging AI and the maths. The brief above is what actually runs;
  this is why it looks the way it does.
- **DAILY_LOOP.md** — data cadence: what the timers pull, when, and recovery.
- **X_BROWSER_CAPTURE.md** — X/Twitter harvesting. Rule 1: one session, ever.
- **YOUTUBE_DOSSIER_BRIEF.md** — turning video transcripts into dossiers.

> **Two taggers, do not confuse them.** The *corpus digester* (Sonnet, offline,
> spec'd here) scores 100% on the golden set. The *live tagger* runs in-engine
> every cycle and is a different component — it was unaudited for the life of
> the project and was discarding 57% of the news. Its audit lives in
> `scripts/audit_live_tagger.py`; its history is in the failure register.

## `research/` — models studied, tested, and mostly rejected

Evidence for decisions. Not descriptions of running code — **most of what is
here was tested and NOT adopted**, which is exactly why it is worth keeping.

- Trader dossiers: `FABIO_VALENTINO_ORDERFLOW`, `MARCO_TRADES_DA_VINCI_LIQUIDITY`,
  `GALA_TRADES_PRICE_ACTION`, `STEVEN_DUX_SMALL_CAP_SHORT`,
  `JEFF_HOLDEN_SMB_MOMENTUM`, `TED_ZACK_STAGE_ANALYSIS`.
- **SHORT_STRATEGY.md** — shorts have failed six independent tests here. Read
  before proposing them again.
- **SCALP_MODEL.md** — scalping research and its pre-committed kill rule.
- **TECHNICAL_RULES_TESTS.md** — technical rules put through the gauntlet.

## `archive/` — historical, superseded, kept for provenance

Every file carries an ARCHIVED banner saying what replaced it. They record
*why* a decision was made at the time; they do **not** describe the system
today.

- `HANDOFF_2026-07-31.md`, `HANDOFF_2026-08-02.md` — session snapshots.
- `UPGRADE_LOG_2026-07-30.md` — one upgrade round.
- `NODE_GRAPH_GAP_ANALYSIS.md` — drove seed expansion from 173 nodes; the graph
  is now 321.
- `TRAINING_RECORD.md` — stops before R22–R37, the rounds that produced the
  current system.

---

## Conventions

- **Root docs**: `README.md` (what it does), `SECURITY.md`.
- Archived docs are marked, never silently deleted — git history is not a
  substitute for a banner someone will actually see.
- Doc paths are referenced from code and other docs. If you move one,
  grep for it: `grep -rn "docs/.*\.md" --include="*.py" --include="*.md" .`
