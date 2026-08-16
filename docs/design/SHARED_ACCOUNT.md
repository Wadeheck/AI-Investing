# One account, four books

`SHARED_STOCK_ACCOUNT` routes the ⚡ event sleeve's and the 🏛 investing book's
**stock** orders through the same real Longbridge account the 📈 trading book
already uses, instead of each pretending against its own simulator.

**Status: built, unit- and integration-tested, and OFF.** Nothing in this
document has been exercised against Longbridge. Off is byte-for-byte the old
behaviour, so it is safe to deploy long before it is switched on. See
*Turning it on* at the end — that part is an operator job on the ProDesk.

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

## Turning it on (operator, on the ProDesk)

Not done. In order:

1. Deploy with the flag off and let it run a few cycles. Confirm the books look
   exactly as before and no `stock_ledger` key appears anywhere.
2. Set `LIVE_CAPITAL_BASE` if it is not already set — the flag will not start
   without it.
3. Dry run: `SHARED_STOCK_ACCOUNT=true` with `LIVE_TRADING=false`. The books keep
   real ledgers, migrate their state, and reach no venue. Check
   `event_state.json` / `invest_state.json` for a `migrated_to_shared_account`
   line in each journal, and that each book's cash is unchanged across the
   migration.
4. Compare `reconcile_claims()`'s view against the Demo A/C's actual
   `stock_positions()` by hand, **before** trusting it to gate a halt.
5. Flip `SHARED_STOCK_ACCOUNT=true` with `LIVE_TRADING=true` and soak. Watch for:
   `shared_claim_drift` (should never appear), `late_fill` notes (should appear
   and resolve), `shared_account` notes (books competing for cash), and fees
   showing up in `event_journal.jsonl` / `invest_journal.jsonl`.
6. Only after a deliberate soak should a funded account be discussed.

## Tests

- `tests/test_shared_account.py` — the rules, against a fake venue.
- `tests/test_shared_books.py` — the sleeve and investing book end to end.
- `tests/test_shared_main_book.py` — the trading book on a shared account,
  reconciliation, and the old `live_book.json` shape still loading.
