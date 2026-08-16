# One account, four books

`SHARED_STOCK_ACCOUNT` routes the ⚡ event sleeve's and the 🏛 investing book's
**stock** orders through the same real Longbridge account the 📈 trading book
already uses, instead of each pretending against its own simulator.

**Status: LIVE on the ProDesk since 2026-08-16 14:24 UTC.** Cut over against the
demo account (`LBPT10097995`, `lb_papertrading` channel — real orders, not funded
money). Migration matched its dry run to the cent; zero reconciliation drift
since. See *The cutover* at the end for what actually happened and what to watch.

Off remains byte-for-byte the old behaviour, so `SHARED_STOCK_ACCOUNT=false` is a
complete rollback — though the books' `stock_ledger` state would then be ignored
rather than reverted, so a rollback needs the pre-cutover backup
(`~/ai-investing-presharedaccount-20260816-183118`), not just the flag.

---

## Why

The sleeve "bought" NVDA/TSM/AMD on a Sunday. It trades `brokers/paper.py` — an
in-memory simulator with instant fills at whatever price it is handed, no fees,
no market-hours check, no lot size, and no rounding at all. `notional / px` went
straight through as a raw float.

There is no second Longbridge account to move it to: the dashboard only toggles
between the one demo account (`LBPT10097995`) and the real funded one. And a
funded account will be exactly **one** account too — so "several books, one
account" has to be solved regardless. Solving it now, against the demo account,
is the cheap version of a problem that otherwise gets solved for the first time
with real money.

Crypto is out of scope throughout: Longbridge is stock-only, so crypto keeps
filling locally exactly as it does today.

---

## The problem, stated precisely

Longbridge has no concept of a book. One account, one cash balance, one blended
position per symbol. "How much NVDA does the sleeve hold" has no answer — only
"the account holds 40 NVDA", which is the sleeve's 10 plus the trading book's 30,
indistinguishable.

Shared naively, that breaks in two directions at once:

- every book reads the blended total as its own, so each books the others' P&L;
- every book can sell shares it never bought, because a SELL of 40 is valid
  against an account holding 40. The trading book's position is closed by the
  sleeve's exit and neither one notices.

## The rules (`brokers/shared.py`)

1. A book only ever **sees** its own claimed positions, held locally in its own
   `BookLedger`. A raw account read is never a book's own view.
2. A book only ever **sells** what it has locally claimed.
3. Stock **shorts are refused entirely**. This one is subtle: at the venue,
   "open a 10-share short" and "sell another book's 10 shares" are *the same
   order*. Netting-aware shorting would need every book to read every other
   book's state at submit time and would still be wrong mid-cycle. Crypto shorts
   are unaffected — that is a local pot nobody shares.
4. Real account cash is read **fresh before every buy**, as a hard ceiling on top
   of the book's own ceiling.

Rule 4 needs no locking because every book runs sequentially, single-threaded,
inside one `Runner.run_cycle()` call. By the time book N submits, Longbridge's
`get_cash()` already reflects every fill the earlier books made this cycle.

## One pot per book, not two

A book trades stocks *and* crypto — the sleeve reacts to a `UNI/USD` shock the
same way it reacts to `NVDA`. The obvious split (keep `PaperBroker` for crypto,
add a ledger for stocks) quietly **doubles** each book's capital: a $100k sleeve
becomes a $100k crypto pot plus a $100k stock pot, and the sleeve sizes entries
at `equity / EVENT_N`, so every position doubles too.

So there is **one `BookLedger` per book covering both asset classes**:

```
cash = base + realized + adjust − fees − Σ(avg·qty)
```

Stock orders go to the real venue; crypto fills locally at the reference price.

`realized`, `fees` and `adjust` are separate on purpose. All three move cash
identically, but "did this strategy pick winners", "what did the venue charge to
find out" and "what changed when the bookkeeping changed" are three different
questions, and folding them together makes the first unanswerable. The learning
spine reads `realized`.

## Asynchronous fills

`LongbridgeBroker.submit()` polls briefly and returns **PENDING** rather than
inventing a fill (the contract in `brokers/base.py`). That is correct, and it is
also the one thing that would make local claims drift permanently: an order that
returns PENDING and fills a minute later is real shares no book ever claimed.

So pending orders are **persisted with their venue order id** and re-queried at
the start of every cycle. Attribution is by order id, so a late fill lands in the
book that placed it, however many cycles later. Cumulative quantity is diffed, so
a partial that completes over three cycles is booked once. Nothing is ever
abandoned on age alone — an abandoned claim is precisely the drift this exists to
prevent.

## Reconciliation

Two checks, asking different questions:

- `Runner._reconcile()` — "did MY positions change behind my back". Still runs.
  Late fills are re-baselined out of it (`resolved_keys`), because an
  asynchronous fill the design expects must not read as a fault.
- `Runner._reconcile_shared()` — "do all the books' claims **sum** to what the
  account holds". This is the only check that can catch what lives *between*
  books: a trade placed by hand in the Longbridge app, a fill nobody claimed, a
  book that died mid-cycle with half its state written. Read from the state
  *files*, because the books are constructed per-use and none is in memory —
  which is also the stricter test, since it verifies what the next cycle will
  act on.

Drift halts the **next** cycle (this check runs after every book has traded, so
it cannot stop the one it found the drift in) and stays latched until an operator
clears it. A book whose file is missing claims nothing; a book whose file exists
but cannot be parsed skips the check rather than reporting every share it owns as
unclaimed.

## What turning it on changes, deliberately

| | Before | After |
|---|---|---|
| Stock order size | any float | whole shares, floored |
| Stock shorts (sleeve, investor) | simulated | **refused** |
| Fills | instant, guaranteed | real, often PENDING for a cycle or more |
| Fees | none | Longbridge's real schedule, per leg (`execution/fees.py`) |
| Venue-side resting stops | placed | **skipped** — a stop that fires hours later cannot be attributed to a book. The in-engine stop still runs; what is lost is protection *between* cycles |
| Telegram wording | "(pretend money)" | "(real orders on the shared account)" |
| `LIVE_CAPITAL_BASE` | optional | **required** — preflight refuses to start without it |

State: each book's file grows a `stock_ledger` key (the authoritative record).
The existing `broker` key stays, in `PaperBroker`'s exact shape, purely so the
Telegram portfolio, the dashboard and `_stamp_marks` keep working — they read
`state["broker"]["positions"]`, and a storage change would have made them all
report a book holding nothing.

## Migration

Automatic and one-time, on the first construction after the flag is set. No
special cycle to run.

- Simulated **stock** positions are **dropped**, closed at their own cost basis.
  They were bought at whatever price a simulator was handed, fractionally, on a
  Sunday. Making them real retroactively would put shares in a real account no
  real order ever bought. Closing at cost preserves cash exactly and books no
  fictional P&L, so nothing reaches the learning spine.
- Simulated **crypto** positions carry over untouched.
- Whatever cash the book had is preserved to the cent, through `adjust` — not
  `realized`. A book whose track record jumps because its bookkeeping changed
  has no track record.

---

## The cutover (2026-08-16)

Backup taken first: `~/ai-investing-presharedaccount-20260816-183118` (89 files,
books + `brain.db` + `journal.db`). `.env` backed up to `.env.bak-presharedaccount`.

The migration was dry-run locally against a copy of the real books before the
flag was touched, and the live result matched it exactly:

| Book | cash before | cash after | closed at cost (became real) | kept simulated |
|---|---|---|---|---|
| ⚡ sleeve | $408.81 | **$11,096.18** | NVDA 15.8219, TSM 8.3557, AMD 6.9256 | — |
| 🏛 investor | $6,913.07 | **$5,655.04** | TSLA −2.7983, PDD 16.6371, JKS −57.0307, INTC −8.8496 | PRX.AS, 2331.HK, 2097.HK |

The investing book's cash **falls** because three of those four were shorts:
closing at cost returns the proceeds opening them had raised. That is correct,
not a loss. `realized` stayed $0.00 in both books — the whole correction went to
`adjust`, so nothing fictional reached the learning spine.

Account at cutover: $999,557.88 cash + AAPL 1 + USO 1 ≈ $1.00M, against $30,000
allocated across the three books ($10k each). The trading book's claims already
matched the account exactly, so reconciliation was clean from the first cycle.

### What to watch

- `shared_claim_drift` in `engine.log` / the journal — **should never appear**.
  It halts the next cycle and stays latched until an operator clears it.
- `late fill` notes — should appear once real orders start flowing, and resolve.
- `shared_account` notes — books competing for the same cash. Harmless at $30k
  against $1M; the signal to watch if the allocation ever grows.
- Fees appearing in `event_journal.jsonl` / `invest_journal.jsonl`. Zero fees
  after the books have traded would mean the fee model is not wired.

### Known cosmetic artefact

`invest_journal.jsonl` carries **two** `migrated_to_shared_account` lines for the
one migration, 52ms apart, both from the cutover. Only the second reached disk,
so the state is right; the record is the part that lied. Fixed in `e1e7d41`
(journal from `_save()`, after the write). The two historical lines are left
alone — a journal is not rewritten.

### If it needs to come back off

`SHARED_STOCK_ACCOUNT=false` restores the old code path immediately, but the
books' pre-cutover *positions* are gone (closed at cost, deliberately). A true
rollback restores `data/` from the backup above **and** flattens whatever the
books have since opened at the venue. Decide which you want before doing either.

## Tests

- `tests/test_shared_account.py` — the rules, against a fake venue.
- `tests/test_shared_books.py` — the sleeve and investing book end to end.
- `tests/test_shared_main_book.py` — the trading book on a shared account,
  reconciliation, and the old `live_book.json` shape still loading.
