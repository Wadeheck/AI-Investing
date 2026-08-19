# Session review — both live crypto sleeves now trade real Binance Futures testnet accounts

*Written 2026-08-20 by an AI pair-programming session (Claude), for human
review. All code below is committed on this machine; deployment to the
ProDesk (the box that actually runs the engine) happened separately — see
§5 for whether that landed.*

5 files changed, ~260 insertions. `git diff` against the previous commit
(`ce819fa`) covers all of it.

---

## 1. Why this exists

The user provided a Binance Futures **testnet** API key and asked for the
crypto sleeve (`strategy/crypto_book.py`) to trade against it live instead of
its default in-memory `PaperBroker`. That grew into two pieces of work once
it became clear the codebase actually has two separate crypto strategies,
and that shorting — recently added to the second one — needed the same
treatment.

---

## 2. New broker: `BinanceFuturesBroker` (`brokers/live.py`)

Built specifically for USDⓈ-M perpetual futures — `CcxtBroker` (already in
this file) is spot-only and reads `fetch_balance()`, which has no concept of
a short or of margin/leverage; futures needs `fetch_positions()` instead.

Key properties:
- Refuses to construct unless `CRYPTO_SANDBOX=true` — has only ever run
  against `testnet.binancefuture.com`, and production Binance keys will not
  even authenticate against that host, so there's no accidental path to a
  funded account.
- 1x leverage, isolated margin by default — the exchange's own liquidation
  engine can't act before the strategy's own 10% hard stop gets a cycle to
  fire.
- `long_only: bool = True` constructor flag. When `True` (the crypto sleeve's
  case), every SELL is sent `reduceOnly=True` — a sizing bug can close a
  long early but never open a short. When `False` (the event sleeve), only
  orders that are actually closing an existing position get `reduceOnly`;
  Binance's one-way netting handles opening a long or a short correctly on
  its own.
- Never fabricates a fill — same discipline as every other adapter in this
  file (`confirm_or_pend`, the fix for STATE §4.15).

**A real ccxt regression had to be worked around first**: ccxt ≥4.5 hard-
refuses `set_sandbox_mode(True)` for `binanceusdm`, raising `NotSupported`
and pointing at Binance's newer "demo trading" feature — a different product
from the classic `testnet.binancefuture.com` this key is for. Fixed by
manually copying ccxt's still-present `urls["test"]` endpoints onto
`urls["api"]`, and disabling `options.fetchCurrencies` (its default value
calls a spot-only endpoint that doesn't exist on the futures testnet host
and fails auth outright against a futures-only key).

## 3. Wiring: two sleeves, two separate testnet accounts

- `strategy/crypto_book.py` — the original long-only sleeve (HODL core +
  tactical). New `Settings.crypto_book_live` (`CRYPTO_BOOK_LIVE`) switches
  its broker from `PaperBroker` to `BinanceFuturesBroker(long_only=True)`.
- `strategy/crypto_event_sleeve.py` — the fast-execution, shock-reaction
  sleeve that can short (`CRYPTO_EVENT_SHORT`, mechanically supported for a
  while, off by default because the shape was gauntlet-tested and rejected
  twice — see the module's own docstring). New
  `Settings.crypto_event_live` (`CRYPTO_EVENT_LIVE`) switches it to
  `BinanceFuturesBroker(long_only=False)`.

These two **must not share one Binance account**: positions are tracked
per-symbol at the account level, not per-strategy, and both sleeves can
independently hold majors (BTC/ETH/SOL). If they shared an account, one
sleeve's order would silently net into the other's position, and each
sleeve's internal bookkeeping (`held[sym]`, entry price, P&L) assumes it
fully owns whatever position exists for a symbol it's tracking. So the event
sleeve runs on a **second, separate testnet account** (different login),
with its own key pair under new settings
`crypto_event_binance_api_key`/`_api_secret`
(`CRYPTO_EVENT_BINANCE_TESTNET_API_KEY`/`_SECRET`).

Also fixed in both sleeves' `_save()`: a live broker has no `.state()` (its
positions live at the venue, not locally), and the code was silently
skipping the write entirely, leaving `_stamp_marks()` — the code that feeds
equity into dashboards/journals — reading an empty positions list and
reporting $0 equity for a live sleeve. Added `BrokerAdapter.snapshot()`
(`brokers/base.py`), a read-only cash+positions view built fresh from the
venue every save, used only for stamping — never fed back into
`from_state()` on restart, so it can't fight the venue's own view of the
account.

## 4. What's actually running, and what isn't

| | Venue | Status |
|---|---|---|
| Crypto sleeve (`crypto_book.py`) | Binance Futures testnet, account 1 | **Live.** Verified: read $5,000 balance, placed and closed a real 0.002 BTC long that filled. |
| Event sleeve (`crypto_event_sleeve.py`) | Binance Futures testnet, account 2 | **Live.** Verified: read its own separate $5,000 balance, opened and closed a real 0.002 BTC short that filled. |
| Event sleeve shorting | — | **On**, all-weather (`CRYPTO_EVENT_SHORT=true`, `CRYPTO_EVENT_SHORT_WINTER=false`), at the user's explicit request — **against** the strategy's own tested evidence (this exact shape, "R37", was gauntlet-tested and rejected; the narrower winter-gated version, "R39", was also rejected, most recently re-audited 2026-08-17). Flagged in `.env` with the date, so it isn't silently forgotten if it underperforms. |
| Everything else crypto (general engine exposure via `RoutingBroker`/`CcxtBroker`/Gemini) | Gemini sandbox | Untouched, and was never live anyway — `LIVE_TRADING=false` means `get_broker()` returns a plain `PaperBroker`, so the (apparently broken) Gemini sandbox is simply never called. |

All existing test suites (`test_crypto_book.py`, `test_crypto_event_sleeve.py`,
18 tests total) pass unchanged — both default to `PaperBroker` unless the new
settings are explicitly turned on.

## 5. Deploy status

Local-only until this session pushed and pulled it onto the ProDesk — see the
top of this file / commit log for whether that step completed. `.env` is
gitignored and per-machine, so the new keys/flags needed adding to the
ProDesk's own `.env` by hand over SSH; they do not travel with `git pull`.

## 6. Open items

- `CRYPTO_EVENT_SHORT` is live against the strategy's own negative evidence —
  worth watching and revisiting if it underperforms, per the note in `.env`.
- Spot execution was discussed and explicitly not pursued — nothing right now
  needs it; the crypto sleeve's HODL core is running long-only 1x-leverage
  futures, which is economically close to spot custody (same price exposure,
  no leverage) minus small periodic funding payments and actual coin custody.
  Worth reconsidering only if either sleeve ever moves off testnet.
