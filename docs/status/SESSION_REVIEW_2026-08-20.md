# Session review — all three of the engine's crypto legs now trade real Binance Futures testnet accounts

*Written 2026-08-20 by an AI pair-programming session (Claude), for human
review. Two commits: `a3551e0` (the two sleeves) and `8a9bc63` (the core
trading book's crypto leg). Both are deployed and running on the ProDesk —
see §6.*

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

## 4. A third broker: the core trading book's crypto leg (Gemini -> Binance)

Corrected assumption, mid-session: this session initially believed nothing on
the ProDesk was live except the two sleeves above, because `LIVE_TRADING=false`
*on this local machine*. The ProDesk's own `.env` was never actually checked
until later in the session — it has `LIVE_TRADING=true`, a real $1,001,902
Longbridge account, and 6 real stock positions with real P&L. That's a
pre-existing, unrelated deployment this session did not create, but it means
the earlier in-conversation claim "nothing but the crypto sleeve is live" was
wrong for the ProDesk specifically.

That live engine's core "trading book" (`RoutingBroker`, built by
`brokers/__init__.py`'s `build_live_broker`) routes crypto orders through
`_make_crypto_broker()`, which was `CcxtBroker` against Gemini — apparently
not a working venue (the user reported the Gemini sandbox doesn't work).
Replaced with `BinanceFuturesBroker`, `long_only` mirroring
`RISK_ALLOW_SHORT`, on a **third** separate testnet account/key
(`crypto_trading_binance_api_key`/`_secret`,
`CRYPTO_TRADING_BINANCE_TESTNET_API_KEY`/`_SECRET`) — same reasoning as the
two sleeves: this book trades the full crypto watchlist (17 symbols, not
just majors), so sharing an account with either sleeve would net positions
together and corrupt bookkeeping.

Note this coupling, since it nearly caused a real problem: `CRYPTO_SANDBOX`
is a single flag. Before this change it *also* controlled whether `CcxtBroker`
used production or sandbox Gemini keys — flipping it to `true` (needed to
unblock the Binance brokers) silently would have moved the live trading
book's Gemini crypto path from production to sandbox keys. Removing
`CcxtBroker`/Gemini from this path entirely (this section) resolves that
coupling — `CRYPTO_SANDBOX` now only gates the Binance brokers.

## 5. What's actually running, and what isn't

| | Venue | Status |
|---|---|---|
| Crypto sleeve (`crypto_book.py`) | Binance Futures testnet, account 1 | **Live**, on the ProDesk. Verified locally: read $5,000 balance, placed and closed a real 0.002 BTC long that filled. Verified on the ProDesk: state file cash matches that exact test balance after redeploy. |
| Event sleeve (`crypto_event_sleeve.py`) | Binance Futures testnet, account 2 | **Live**, on the ProDesk. Verified locally: opened and closed a real 0.002 BTC short that filled. Verified on the ProDesk: state file cash matches that exact test balance after redeploy. |
| Core trading book's crypto leg | Binance Futures testnet, account 3 | **Live**, on the ProDesk. Verified locally: full `build_live_broker`/`_make_crypto_broker` path, a real 0.02 ETH buy+sell round trip filled. Verified on the ProDesk: deployed, restarted, `daily_status.py` shows all 3 books reconciling, no crypto errors in the log. |
| Event sleeve shorting | — | **On**, all-weather (`CRYPTO_EVENT_SHORT=true`, `CRYPTO_EVENT_SHORT_WINTER=false`), at the user's explicit request — **against** the strategy's own tested evidence (this exact shape, "R37", was gauntlet-tested and rejected; the narrower winter-gated version, "R39", was also rejected, most recently re-audited 2026-08-17). Flagged in `.env` with the date, so it isn't silently forgotten if it underperforms. |

All existing test suites pass unchanged on both machines — everything here
defaults to the old behavior unless the new settings are explicitly turned on.

## 6. Deploy status: done, with one real incident along the way

Both commits (`a3551e0`, `8a9bc63`) are pushed and pulled onto the ProDesk;
`git rev-parse HEAD` matches on both machines. `.env` is gitignored and
per-machine, so every new key/flag was added to the ProDesk's `.env` by hand
over SSH — they do not travel with `git pull`.

**Incident during the first deploy:** after the first restart, both sleeves
silently failed on *every* cycle for ~45 minutes — `BinanceFuturesBroker`
refused to construct because the ProDesk's `.env` had `CRYPTO_SANDBOX=false`
(this session added the new key blocks but never checked that pre-existing
flag). Caught by explicitly waiting for and diffing the state files'
timestamps/content against known values rather than assuming the restart
alone was sufficient proof. Fixed by flipping the flag and restarting once
more (a second restart of the box, deliberately — not the "restart to
verify" pattern OPERATIONS.md warns against, a genuine fix-forward).

## 7. Open items

- `CRYPTO_EVENT_SHORT` is live against the strategy's own negative evidence —
  worth watching and revisiting if it underperforms, per the note in `.env`.
- Spot execution was discussed and explicitly not pursued — nothing right now
  needs it; all three crypto legs run long-only (or long-only + optional
  short for the event sleeve) 1x-leverage futures, which is economically
  close to spot custody (same price exposure, no leverage) minus small
  periodic funding payments and actual coin custody. Worth reconsidering only
  if any of this ever moves off testnet.
- `ANTHROPIC_MODEL` is correctly set to the current model ID on both machines,
  but `ANTHROPIC_API_KEY` is blank on both — the "brain"'s LLM calls actually
  run on BytePlus ModelArk today, not Claude. Not fixed (no key to give it),
  just surfaced — see the memory note `ai-investing-brain-llm-provider`.
