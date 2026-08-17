"""The autonomous loop: data -> signals -> formula -> risk -> execute -> journal, with
online learning, cost-adjusted fills, a regime gate, broker reconciliation, and
idempotent orders.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone

from ai_investing.alerts import get_notifier
from ai_investing.util import atomic
from ai_investing.brokers import PaperBroker, get_broker
from ai_investing.config import Settings
from ai_investing.data import get_provider
from ai_investing.data import news as news_mod
from ai_investing.execution.costs import CostModel
from ai_investing.learning import OutcomeTracker, ParamStore, RLSLearner
from ai_investing.models import (Asset, AssetClass, Order, OrderStatus, OrderType, Side,
                                 mark_price)
from ai_investing.safety import CircuitBreaker, DataGuard, validate_settings, write_heartbeat
from ai_investing.signals import default_signals
from ai_investing.storage import Journal
from ai_investing.strategy import (DecisionEngine, RegimeGate, RiskManager, UserViews,
                                   build_market_stats)


# How long the engine must have been DOWN before a start is worth a notification.
# Below this it is a deploy or a quick bounce, and saying so on Telegram trains the
# user to ignore the channel every safeguard reports through (STATE §4.16).
START_ALERT_GAP_S = 900.0        # 15 minutes


def foreign_positions(position_keys, universe) -> set[str]:
    """Positions this engine has no mandate over: present in the account, absent
    from the watchlist it trades.

    A paper broker only ever holds what the engine opened, so this is empty and
    always has been. A LIVE exchange adapter is different in kind:
    `CcxtBroker.get_positions()` turns every non-zero balance into a Position, so
    the engine inherits the entire account — 19 currencies against a 3-symbol
    watchlist, in the case that prompted this. It has no cost basis for them (the
    adapter substitutes the last price), no thesis, and no instruction to hold
    them.

    Deliberately a function and not an inline set comprehension: this is the only
    thing standing between a focus list and a liquidated account, so it gets a
    name and a test rather than being mirrored in one.
    """
    return {k for k in position_keys if k not in universe}


class Runner:
    def __init__(self, settings: Settings, use_news: bool = True):
        self.settings = settings
        self.use_news = use_news
        self.provider = get_provider(settings)
        self.broker = get_broker(settings)
        # paper book persistence: restore holdings/cash across engine restarts
        # (PC-off overnight must not amnesia the portfolio)
        self._paper_path = os.path.join(
            os.path.dirname(os.path.abspath(settings.state_path)), "paper_state.json")
        if not settings.live and isinstance(self.broker, PaperBroker):
            try:
                with open(self._paper_path) as fh:
                    self.broker = PaperBroker.from_state(
                        json.load(fh), allow_short=settings.risk.allow_short)
            except (OSError, json.JSONDecodeError, KeyError):
                pass
        self.journal = Journal(settings.db_path)
        self.assets = self._build_watchlist()
        # Board lots, cached on disk. Loaded before anything asks what the live
        # universe is, because "do we know this symbol's quantity unit" is now
        # part of that answer.
        from ai_investing.brokers.lots import LotBook
        self.lots = LotBook.load(os.path.dirname(os.path.abspath(settings.state_path)))
        self._refresh_lot_sizes()
        self._first_cycle = True
        self._cycles = 0
        self._last_mark_day = None      # None = not yet seeded from the journal
        self._run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self._submitted: set[str] = set()      # idempotency: client order IDs sent this run
        self._last_positions: dict[str, float] | None = None
        self._stats: dict = {}
        # Set by `_reconcile_shared()` when the books and the shared account
        # disagree; halts the next cycle until an operator clears it.
        self._shared_drift: str | None = None

        # --- learning engine ---
        self.store = ParamStore(settings.params_path)
        self.model, rls = self.store.load()
        self.user_views = UserViews.load(settings.user_views_path)
        self.engine = DecisionEngine(default_signals(), model=self.model, user_views=self.user_views)
        lc = settings.learning
        self.rls = rls or RLSLearner.initialize(
            self.model.weights, prior_confidence=lc.prior_confidence,
            mu=lc.forgetting_mu, trust_region=lc.trust_region)
        # The open-claims ledger: which φ opened which position. Persisted
        # because the engine restarts daily and this book holds for weeks — see
        # the module docstring in learning/attribution.py for what a fresh
        # tracker taught the model instead.
        self._claims_path = os.path.join(
            os.path.dirname(os.path.abspath(settings.state_path)), "open_claims.json")
        try:
            with open(self._claims_path) as fh:
                self.tracker = OutcomeTracker.from_state(json.load(fh))
        except (OSError, json.JSONDecodeError, TypeError, AttributeError):
            self.tracker = OutcomeTracker()
        self.samples_seen = self.rls.updates
        # SAY WHETHER THE FORMULA IS ACTUALLY LEARNING. "θv1 (learned from 0
        # trades)" has been in every cycle header for sixteen days and reads as
        # a version string, not as an alarm. Zero samples has two very different
        # causes — nothing has closed yet, or closes are not being credited —
        # and only the open claims distinguish them.
        ages = self.tracker.pending_ages()
        if self.samples_seen == 0:
            oldest = f"{max(ages.values()):.1f}d" if ages else "none"
            print(f"  LEARNING   the formula has NEVER updated (0 samples). "
                  f"{len(ages)} position(s) awaiting a close, oldest {oldest} — "
                  f"θ is still its hand-set priors")
        else:
            print(f"  LEARNING   {self.samples_seen} sample(s) so far, "
                  f"{len(ages)} claim(s) open")

        # --- execution realism + safety ---
        c = settings.cost
        self.costs = CostModel(enabled=c.enabled, commission_bps=c.commission_bps,
                               spread_bps=c.spread_bps, slippage_coef=c.slippage_coef)
        # per-market frictions: HK stamp duty, Asia taxes, crypto taker fees —
        # every fill is charged what REAL money would lose in that market
        from ai_investing.execution.costs import MARKET_COSTS_BPS, market_cost_model
        self._market_costs = {m: market_cost_model(self.costs, m) for m in MARKET_COSTS_BPS}
        rg = settings.regime
        self.regime = RegimeGate(high_vol=rg.high_vol, ood_z=rg.ood_z, min_mult=rg.min_mult,
                                 feature_mean=self.model.feature_mean,
                                 feature_std=self.model.feature_std) if rg.enabled else None
        self.risk = RiskManager(settings.risk, regime_gate=self.regime, lots=self.lots)

        # --- alerts ---
        self.notifier = get_notifier(settings)
        # ANNOUNCE A RECOVERY, NOT A RESTART (2026-08-05).
        #
        # This used to message on every start. A deploy restart is not news, and a
        # crash loop turned it into eighteen identical "started (LIVE)" alerts in
        # thirteen minutes — which BURIED the one message that mattered, the
        # watchdog's "restarted 10x since last check — crash loop, not a blip". The
        # noise did not merely annoy; it hid the diagnosis.
        #
        # So: alert only when the engine was actually DOWN long enough to matter,
        # judged from the heartbeat rather than from a counter, and say how long.
        # Restarting a healthy engine now says nothing at all. Silence is the
        # correct report for "nothing happened".
        mode = "LIVE" if settings.live else "paper"
        down_s = None
        try:
            from ai_investing.safety import heartbeat as _hb
            hb = _hb.read_heartbeat(settings.heartbeat_path)
            down_s = _hb.age_seconds(hb) if hb else None
        except Exception:
            down_s = None
        print(f"  started ({mode}) — θv{self.model.version}; "
              f"last heartbeat {f'{down_s / 60:.0f} min ago' if down_s else 'none'}")
        if self.notifier.enabled and (down_s is None or down_s > START_ALERT_GAP_S):
            gap = (f"after {down_s / 3600:.1f}h down" if down_s
                   else "first start (no prior heartbeat)")
            self.notifier.send(f"🟢 AI-Investing recovered — {mode}, {gap}, "
                               f"θv{self.model.version}")

        # --- safety layer ---
        errors, warnings = validate_settings(settings)
        for w in warnings:
            print(f"  [config warning] {w}")
        for e in errors:
            print(f"  [config ERROR] {e}")
        if errors and settings.live:
            raise RuntimeError("refusing to start LIVE with config errors: " + "; ".join(errors))
        self.breaker = CircuitBreaker(settings.safety, settings.risk.max_daily_drawdown, settings.breaker_path)
        self.guard = DataGuard(settings.safety)
        self._last_prices: dict[str, float] = {}
        # Symbols the data guard flagged on the previous cycle, so an ongoing fault
        # is announced once instead of every cycle. Shipping the USE of this without
        # the initialisation crash-looped the engine 18 times (see STATE §4.16).
        self._flagged_symbols: set[str] = set()
        # last news/context failure signature, so a persistent provider outage is
        # one alert rather than one per cycle (the 4th announce-the-state instance)
        self._last_news_error: str | None = None

        # --- shadow "formula-only" portfolio (ignores your input) for the comparison ---
        self._shadow_path = os.path.join(
            os.path.dirname(os.path.abspath(settings.state_path)), "shadow.json")
        self.shadow_broker = self._load_shadow(settings.starting_cash)
        self.shadow_engine = DecisionEngine(default_signals(), model=self.model, user_views=UserViews())
        self.shadow_risk = RiskManager(settings.risk, regime_gate=self.regime)

        # --- bounded slice of a live account (LIVE_CAPITAL_BASE) ---------------
        self._ledger = None
        self._ledger_path = os.path.join(
            os.path.dirname(os.path.abspath(settings.state_path)), "live_book.json")
        # `self.book` is what the MAIN book trades and reads through; `self.broker`
        # stays the raw venue and is only for things that are genuinely about the
        # account (resting stops, the paper-mode state file, reconciliation).
        # They are the same object unless the account is being shared.
        self.book = self.broker
        if settings.live and settings.live_capital_base > 0:
            from ai_investing.execution.capital import BookLedger
            saved = {}
            try:
                with open(self._ledger_path) as fh:
                    saved = json.load(fh) or {}
            except (OSError, json.JSONDecodeError, TypeError):
                saved = {}
            # Two shapes live here: the flat ledger dict this file has always
            # held, and — once the account is shared — `{"ledger":…, "pending":…}`,
            # because unconfirmed orders have to survive a restart too.
            nested = saved.get("ledger") if isinstance(saved.get("ledger"), dict) else None
            try:
                self._ledger = BookLedger.from_dict(nested or saved, settings.live_capital_base)
            except (KeyError, TypeError, ValueError):
                self._ledger = BookLedger(base=settings.live_capital_base)
            if settings.shared_stock_account:
                # THE MAIN BOOK MUST BE WRAPPED TOO, not just the new ones. Its
                # ledger reads `broker.get_positions()` — the raw account — as its
                # own holdings, which is exactly right while it is the account's
                # only user and exactly wrong the moment it is not: the sleeve's
                # NVDA would become the trading book's NVDA, its P&L would be
                # booked here, and `_reconcile` would halt on the difference.
                from ai_investing.brokers.shared import BookBroker
                stock = getattr(self.broker, "stock", None)
                self.book = BookBroker("main", self._ledger,
                                       stock_broker=stock if getattr(stock, "live", False) else None,
                                       pending=saved.get("pending") or [],
                                       base_currency=settings.base_currency,
                                       lots=self.lots)
            print(f"  LIVE BOOK  ${settings.live_capital_base:,.0f} slice of the account, "
                  f"realised so far ${self._ledger.realized:,.2f} — "
                  f"{len(self._live_universe())} USD symbols tradable"
                  + ("  [SHARED ACCOUNT]" if settings.shared_stock_account else ""))
        self._check_shared_ceilings()

    def _refresh_lot_sizes(self) -> None:
        """Ask Longbridge for board lots once at start-up, and cache them.

        Once, not per cycle: a listing's lot size changes about as often as its
        ticker does, and a network call between deciding to trade and sizing the
        trade is a call that can fail at the worst moment. A symbol whose lot is
        unknown stays out of `_live_universe()` until a later start-up learns
        it — untradable is recoverable, a wrong quantity unit is not.
        """
        if not (self.settings.live and self.settings.stock_broker == "longbridge"):
            return
        want = [a.symbol for a in self.assets if a.asset_class is AssetClass.STOCK]
        missing = [x for x in want if self.lots.lot_size(x) is None]
        if not missing:
            return
        try:
            import os as _os
            from longport.openapi import Config, QuoteContext  # type: ignore
            from ai_investing.brokers.lots import fetch_lot_sizes
            qc = QuoteContext(Config.from_apikey(
                app_key=_os.environ["LONGPORT_APP_KEY"],
                app_secret=_os.environ["LONGPORT_APP_SECRET"],
                access_token=_os.environ["LONGPORT_ACCESS_TOKEN"]))
            found = fetch_lot_sizes(missing, qc)
        except Exception as exc:                                  # noqa: BLE001
            print(f"  [lots] could not refresh board lots: "
                  f"{type(exc).__name__}: {str(exc)[:90]}")
            return
        added = self.lots.update(found)
        if added:
            self.lots.save()
        unknown = [x for x in missing if x not in found]
        print(f"  LOTS       {len(self.lots.known())} board lots cached "
              f"(+{added} this start); {len(unknown)} symbol(s) the venue does "
              f"not carry, held out of the tradable universe")

    def _check_shared_ceilings(self) -> None:
        """Do the three books' ceilings actually fit inside the account?

        Each book's ceiling is a promise about how much it may spend. Nothing
        checks those promises against each other, so three $100k books against a
        $150k account is a config that looks fine, starts fine, and fails on
        whichever book happens to trade last — with a venue rejection rather than
        an explanation.

        WARNS, never shrinks and never refuses. Auto-shrinking a ceiling would
        silently change the size of a book the operator sized deliberately, and
        the per-order real-cash ceiling in `BookBroker.submit` already makes
        over-allocation safe rather than merely detectable. This exists so the
        first symptom is a sentence at startup instead of a reject at 3am.
        """
        if not (self.settings.shared_stock_account and self.settings.live):
            return
        stock = getattr(self.broker, "stock", None)
        if not getattr(stock, "live", False):
            return
        from ai_investing.strategy.event_sleeve import START_CASH as EVENT_CASH
        ceilings = {"trading": self.settings.live_capital_base,
                    "event sleeve": EVENT_CASH,
                    "investing": float(getattr(self.settings, "invest_starting_cash", 0.0))}
        try:
            cash = float(stock.get_cash())
            value = sum(abs(float(p.qty)) * float(p.avg_price)
                        for p in stock.get_positions().values())
        except Exception as exc:                                  # noqa: BLE001
            print(f"  [shared account] could not size the account: {exc}")
            return
        total, account = sum(ceilings.values()), cash + value
        detail = ", ".join(f"{k} ${v:,.0f}" for k, v in ceilings.items())
        if total > account:
            msg = (f"the books are allowed ${total:,.0f} between them ({detail}) but "
                   f"the shared account is worth ${account:,.0f}. No order can "
                   f"overspend it, but the books will start refusing entries.")
            print(f"  [shared account] OVER-ALLOCATED — {msg}")
            self.journal.record_event("shared_over_allocated", msg[:300])
            if self.notifier.enabled:
                self.notifier.send(f"⚠️ *Shared account over-allocated* — {msg}")
        else:
            print(f"  [shared account] ${account:,.0f} available, ${total:,.0f} "
                  f"allocated ({detail})")

    def _shared_stock_broker(self):
        """The ONE live stock adapter the other books may share, or None.

        `LongbridgeBroker.__init__` builds a TradeContext and makes a live channel
        assertion, so a second instance is a second API session, not a free
        object — the books get the instance this runner already holds. Reached
        through `RoutingBroker.stock` because that is where `build_live_broker`
        put it; anything else (paper mode, a bare adapter) yields None and every
        book stays exactly as it is today.
        """
        if not (self.settings.shared_stock_account and self.settings.live):
            return None
        stock = getattr(self.broker, "stock", None)
        return stock if getattr(stock, "live", False) else None

    def _load_shadow(self, starting_cash: float) -> PaperBroker:
        # Persist in ALL modes: the paper track record (and its formula-only
        # A/B twin) must survive restarts — the brain REMEMBERS what it holds.
        # Fresh start = delete data/shadow.json + data/paper_state.json.
        try:
            with open(self._shadow_path) as fh:
                return PaperBroker.from_state(json.load(fh), allow_short=self.settings.risk.allow_short)
        except (OSError, json.JSONDecodeError, KeyError):
            pass
        return PaperBroker(starting_cash, allow_short=self.settings.risk.allow_short)

    def _live_universe(self) -> set[str]:
        """What the live-routed book may trade: every stock the venue can reach
        AND whose board lot we actually know.

        This was USD-listed stocks only, on two stated grounds that both turned
        out to be wrong when probed (2026-08-17). `cost_price` currency was
        already converted at the adapter boundary — the docstring saying
        otherwise was stale. And the symbol format did not "only round-trip for
        `.US`"; the watchlist simply speaks Yahoo (`D05.SI`, `600519.SS`) while
        Longbridge speaks its own dialect (`D05.SG`, `600519.SH`) and answers an
        unknown string with an empty list rather than an error. Translated, the
        venue resolves 116 of the 126 non-USD names, and the account holds SGD
        1,000,000 and HKD 1,000,000 to trade them with.

        So the gate is now the two things that are actually true: can the symbol
        be expressed at the venue, and do we know the quantity unit it trades in.
        A name whose board lot is unknown is excluded rather than guessed — see
        brokers/lots.py on why there is no safe default.

        Crypto stays out for a plainer reason that IS still true: the segregated
        Gemini account holds $0, so those orders can only reject. The ₿ book
        trades them on paper and is untouched by this.
        """
        from ai_investing.brokers.symbols import reachable
        return {a.key for a in self.assets
                if a.asset_class is AssetClass.STOCK
                and reachable(a.symbol)
                and self.lots.lot_size(a.symbol)}

    def _tradable_universe(self) -> set[str]:
        """Keys this book has a mandate over — the gate on every exit path."""
        if self._ledger is not None:
            return self._live_universe()
        return {a.key for a in self.assets}

    def _book_basis(self) -> str:
        """Identity of the book the breaker's marks belong to.

        "paper" for the simulated book — deliberately without the cash amount, so
        an existing paper record is never re-based by an unrelated edit to
        STARTING_CASH. A live slice carries its size, because changing the size IS
        changing the book.
        """
        if self._ledger is not None:
            return f"live:{self.settings.live_capital_base:.0f}"
        return "live:account" if self.settings.live else "paper"

    def _book_portfolio(self):
        """The book, as the rest of the engine should see it.

        THE ONE BOUNDARY. With LIVE_CAPITAL_BASE set, the account holds far more
        than the engine may risk, so everything downstream — sizing, exposure,
        stops, all three breakers — must reason about the slice instead. Convert
        here, once, and no consumer needs to know. Same reasoning as fixing FX at
        the data layer in §4.2: a cap applied at each use site is a cap you will
        eventually forget at one of them.
        """
        if self.book is not self.broker:
            # A wrapped book already IS the slice: its cash is the ledger's and
            # its positions are the ones it claims. Nothing to filter, because
            # nothing foreign can get in.
            return self.book.portfolio()
        p = self.broker.portfolio()
        if self._ledger is None:
            return p
        from ai_investing.execution.capital import own_positions
        return self._ledger.book_portfolio(own_positions(p.positions, self._live_universe()))

    def _costs_for(self, asset) -> CostModel:
        from ai_investing.execution.costs import market_of_symbol
        mkt = market_of_symbol(asset.symbol, asset.asset_class.value)
        return self._market_costs.get(mkt, self.costs)

    def _mark_crypto_to_spot(self, prices: dict) -> None:
        """Re-mark crypto to the live price before any risk decision.

        Crypto runs 24/7 on daily bars, so overnight a position can be valued at
        a close many hours old — and a 10% hard stop measured against a stale
        mark is not a 10% stop. Only the MARK moves here: signals, sizing and
        entries all still read the daily bars the gauntlet validated, so this
        tightens protection without altering what the books choose to trade.

        A tick more than 35% from the last close is treated as bad data, not as
        a crash: the whole point is to make stops fire honestly, so a garbage
        quote must never be the thing that fires one.
        """
        spot_fn = getattr(self.provider, "spot", None)
        if not spot_fn:
            return
        crypto = [a for a in self.assets if a.asset_class is AssetClass.CRYPTO]
        if not crypto:
            return
        try:
            live = spot_fn([a.symbol for a in crypto])
        except Exception as exc:
            self.journal.record_event("spot_error", str(exc)[:200])
            return
        moved = 0
        for a in crypto:
            px = live.get(a.symbol)
            prev = prices.get(a.key, 0.0)
            if not px or px <= 0:
                continue
            if prev > 0 and abs(px - prev) / prev > 0.35:
                self.journal.record_event(
                    "spot_rejected", f"{a.symbol} spot {px:.2f} vs close {prev:.2f}")
                continue
            prices[a.key] = px
            moved += 1
        if moved:
            # counted for the log line below; deliberately not stored. It used to be
            # written to self._spot_marked, which nothing ever read.
            #
            # "symbol(s)", not "position(s)": this walks the crypto WATCHLIST, not
            # the crypto book's holdings. It read "spot-marked 13 crypto
            # position(s)" while the book held three, which invites exactly the
            # wrong conclusion during an incident — that a book has positions
            # nobody can account for.
            print(f"  spot-marked {moved} crypto symbol(s) to live price")

    def _mark_books(self, px_by_sym: dict) -> None:
        """Mark every book to market, independent of its trading logic.

        Each book decides for itself when to TRADE (daily, on shocks, always),
        but they must all be VALUED every cycle or their persisted equity goes
        stale. Failures are per-book and non-fatal: an unmarkable book must not
        stop the others, and must never stop the engine.
        """
        from ai_investing.strategy.crypto_book import CryptoBook
        from ai_investing.strategy.event_sleeve import EventSleeve
        from ai_investing.strategy.investor import Investor
        # The sleeve and the investing book take the shared stock adapter; the
        # crypto book never touches it (Longbridge is stock-only) and its
        # constructor does not accept one.
        shared = self._shared_stock_broker()
        for name, cls, kw in (("crypto", CryptoBook, {}),
                              ("event sleeve", EventSleeve,
                               {"stock_broker": shared, "lots": self.lots}),
                              ("investor", Investor,
                               {"stock_broker": shared, "lots": self.lots})):
            try:
                cls(self.settings, **kw).mark(px_by_sym)
            except Exception as exc:                    # noqa: BLE001
                print(f"  [mark:{name}] skipped: {type(exc).__name__}: {exc}")

    def _build_watchlist(self) -> list[Asset]:
        stocks = [Asset(s, AssetClass.STOCK) for s in self.settings.stock_watchlist]
        crypto = [Asset(s, AssetClass.CRYPTO, exchange=self.settings.crypto_exchange)
                  for s in self.settings.crypto_watchlist]
        return stocks + crypto

    # -- one full evaluation/execution/learning pass ------------------------
    def run_cycle(self) -> dict:
        self._cycles += 1
        self.user_views = UserViews.load(self.settings.user_views_path)   # live edits take effect
        self.engine.user_views = self.user_views
        bars_by_key = {a.key: self.provider.get_bars(a, limit=250) for a in self.assets}
        prices = {k: (b[-1].close if b else 0.0) for k, b in bars_by_key.items()}
        self._mark_crypto_to_spot(prices)
        self._stats = build_market_stats(bars_by_key, lookback=20)
        self._last_prices = prices

        # Data sanity guard: drop symbols with bad/stale/absurd prices this cycle.
        bad_data, data_msgs = self.guard.check(prices, bars_by_key)
        if bad_data:
            detail = "; ".join(data_msgs)
            self.journal.record_event("data_anomaly", detail)
            print(f"!! DATA GUARD flagged: {detail}")
        # ALERT ON THE CHANGE, NOT THE STATE (2026-08-05). This sent a Telegram on
        # every cycle a symbol stayed flagged. 2800.HK went stale because yfinance
        # has no 2026-08-03 bar for it and the current session's Close is NaN — a
        # real upstream gap that will persist for hours or days, producing an
        # identical alert every ~7 minutes until it clears.
        #
        # Exactly the §4.7 mistake in a second place: a latched CONDITION announced
        # as if it were an EVENT, training you to ignore the channel every other
        # safeguard reports through. The log line above still fires every cycle,
        # because a log is free and a notification is not.
        newly = bad_data - self._flagged_symbols
        cleared = self._flagged_symbols - bad_data
        if self.settings.alerts.on_error and (newly or cleared):
            parts = []
            if newly:
                parts.append("⚠️ *DATA GUARD*: " +
                             "; ".join(m for m in data_msgs
                                       if any(s in m for s in newly)))
            if cleared:
                parts.append(f"✅ data recovered: {', '.join(sorted(cleared))}")
            self.notifier.send("\n".join(parts))
        self._flagged_symbols = set(bad_data)

        # Prices the guard did NOT reject. Valuation must use these, not the raw
        # feed: equity is the number the circuit breaker judges, and judging it
        # on a tick the guard just called absurd is how a data fault becomes a
        # liquidation. Falling back to cost basis (Portfolio._px) makes an outage
        # read as "no change" instead of as a 13.8% collapse.
        safe_prices = ({k: v for k, v in prices.items() if k not in bad_data}
                       if bad_data else prices)

        # Claim any order the venue confirmed after the last cycle ended, BEFORE
        # the book is valued or reconciled. `LongbridgeBroker.submit` returns
        # PENDING far more often than FILLED — it will not invent a fill — so
        # without this the book is valued without positions it actually holds.
        if hasattr(self.book, "resolve_pending"):
            for note in self.book.resolve_pending():
                print(f"  LIVE BOOK  {note}")
                self.journal.record_event("late_fill", note[:200])

        portfolio = self._book_portfolio()
        equity = portfolio.equity(safe_prices)
        mode = "LIVE" if self.settings.live else "PAPER"
        print(f"\n=== cycle {datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S}Z  [{mode}]  "
              f"equity ${equity:,.0f}  cash ${portfolio.cash:,.0f}  "
              f"θv{self.model.version} (learned from {self.samples_seen} trades) ===")

        # 0) Reconcile the engine's world with the broker's before doing anything.
        if not self._reconcile(portfolio):
            self._snapshot(prices, [], {}, halted=True)
            return {"halted": True, "reason": "reconcile_drift", "equity": equity}

        if self._first_cycle:
            self.risk.mark_day_start(equity)
            self._first_cycle = False

        context: dict = {}
        if self.use_news:
            # yesterday->today price moves pulse the web once a day (assets are
            # nodes too: the market's own action is part of the world model)
            price_moves: dict = {}
            try:
                from ai_investing.brain.scorecard import Scorecard
                _sc = Scorecard(self.settings)
                price_moves = _sc.day_moves({a.symbol: prices.get(a.key, 0.0)
                                             for a in self.assets})
                _sc.close()
            except Exception:
                pass
            try:
                context = news_mod.build_market_context(self.settings, self.assets,
                                                        price_moves)
            except Exception as exc:
                self.journal.record_event("news_error", str(exc))
                # THE FOURTH announce-the-state instance, found by finally sweeping
                # every notifier.send() in the codebase rather than waiting for the
                # user to complain again. A provider outage lasts hours, and this
                # fired every cycle — ~12 identical alerts an hour. Report the same
                # failure once, and report recovery, so a persistent outage is one
                # message and not a wall of them.
                sig = f"{type(exc).__name__}: {exc}"[:200]
                if self.settings.alerts.on_error and sig != self._last_news_error:
                    self.notifier.send(f"⚠️ news/context error: {exc}")
                self._last_news_error = sig
            else:
                if self._last_news_error and self.settings.alerts.on_error:
                    self.notifier.send("✅ news/context recovered.")
                self._last_news_error = None
        if context.get("briefing"):
            print(f"[briefing] {context['briefing']}")

        # Once a day (SGT): plain-language overview — strongest ripples, the
        # standing 6-month strategy (challenged, not rewritten), then the ideas.
        # THE ONE THING THE BOT ASKS YOU (brain/consult.py). Not "approve this
        # order" — "do you agree with this read of the news". Sent before the
        # books trade, so a tap that lands quickly still shapes today's sizing.
        # Overrides go FIRST: being outvoted is the more urgent message, and
        # burying it under a new question is how it becomes invisible.
        if context.get("brain"):
            try:
                from ai_investing.brain import consult
                for notice in context["brain"].get("consult_overrides") or []:
                    self.notifier.send(consult.override_text(notice),
                                       consult.override_buttons(notice))
                for rec in context["brain"].get("consult_asks") or []:
                    self.notifier.send(consult.ask_text(rec), consult.ask_buttons(rec))
                    print(f"  [consult] asked: {rec['claim'][:70]}")
            except Exception as exc:
                print(f"  [consult] send skipped: {type(exc).__name__}: {exc}")

        if context.get("brain"):
            # SAFE prices only. A guard-flagged tick stamped with today's date is
            # worse than a missing one: 2800.HK is the HK/CN benchmark, so a frozen
            # close gives every HK and CN call an excess return measured against a
            # market that appears not to have moved — and unlike a MISSING benchmark,
            # that fires no warning. The price history the scorecard grades against
            # must contain only prices the guard accepted.
            px_by_sym = {a.symbol: safe_prices.get(a.key, 0.0) for a in self.assets}
            # scorecard: snapshot prices, judge every call ≥5 days old, learn
            track = learn_notes = None
            try:
                from ai_investing.brain.scorecard import Scorecard
                sc = Scorecard(self.settings)
                vol_by_sym = {a.symbol: (bars_by_key[a.key][-1].volume
                                         if bars_by_key.get(a.key) else 0.0)
                              for a in self.assets}
                sc.snapshot_prices(px_by_sym, vol_by_sym)
                outcomes = sc.score_due()
                learn_notes = sc.update_reliability(outcomes)
                track = sc.track_record()
                sc.close()
                if outcomes:
                    print(f"  [scorecard] judged {len(outcomes)} past calls; "
                          f"30d hit-rate {track.get('hit_rate')}")
            except Exception as exc:
                print(f"  [scorecard] skipped: {type(exc).__name__}: {exc}")
            try:
                from ai_investing.brain.strategist import maybe_daily_overview
                maybe_daily_overview(self.settings, context["brain"],
                                     context.get("briefing", ""), self.notifier,
                                     track=track, learn_notes=learn_notes)
            except Exception as exc:
                print(f"  [strategist] skipped: {type(exc).__name__}: {exc}")
            # the 🏛 investing book: express the 6-month theses (daily, gated inside)
            try:
                from ai_investing.brain.strategist import load_strategy, _labels
                from ai_investing.strategy.investor import Investor
                Investor(self.settings, self._shared_stock_broker(),
                         lots=self.lots).daily_manage(
                    px_by_sym, load_strategy(self.settings), self.notifier,
                    _labels(self.settings))
            except Exception as exc:
                print(f"  [investor] skipped: {type(exc).__name__}: {exc}")

        # Shadow "formula-only" portfolio — what the model would do ignoring your input.
        self._run_shadow(prices, context, bars_by_key, bad_data)

        # Value EVERY book every cycle, whatever its trading logic did. The
        # investing book gates to once a day and the sleeve only wakes on fresh
        # shocks, so without this their saved value goes stale while positions
        # move — and a reader falling back to cash overstates any book holding
        # shorts (the portfolio read $409k against a real $400k).
        self._mark_books({a.symbol: prices.get(a.key, 0.0) for a in self.assets})

        executed: list[Order] = []

        # 1) Circuit breaker: daily / trailing / inception drawdown + per-day caps.
        # First: if the BOOK changed size (paper $100k -> a $10,000 live slice),
        # re-base the marks. Otherwise the first honest reading of the new book
        # registers as a catastrophic drawdown against the old one — which is
        # exactly what happened on 2026-08-04, latching the breaker at a fictional
        # 90%. Declared, never inferred; see CircuitBreaker.ensure_basis.
        rebased = self.breaker.ensure_basis(self._book_basis(), equity)
        if rebased:
            print(f"  BREAKER    {rebased}")
            if self.notifier.enabled:
                self.notifier.send(f"📐 Book re-based — {rebased}")
        breaker = self.breaker.check(equity)
        if breaker.flatten:
            print(f"!! CIRCUIT BREAKER — {breaker.reason}. Flattening and halting.")
            # Journal the event once, on the latching cycle. A latched breaker
            # reports flatten=True on every cycle forever; recording each one
            # buried the actual moment of failure under hundreds of copies and
            # sent an identical Telegram alert every five minutes overnight.
            if breaker.announce:
                self.journal.record_event("circuit_breaker", breaker.reason)
                if self.settings.alerts.on_kill:
                    self.notifier.send(
                        f"🛑 *CIRCUIT BREAKER* — {breaker.reason}. "
                        f"Flattened & halted. equity ${equity:,.0f}\n"
                        f"Stays halted until reviewed: "
                        f"`python3 scripts/breaker.py --status`")
            executed += self._flatten(prices)
            self._finish(prices, [], context, halted=True)
            return {"halted": True, "reason": breaker.reason, "equity": equity}

        # name risk: refresh per-symbol integrity/distress charges BEFORE stops
        # so a flagged holding gets its tightened leash this very cycle
        try:
            from ai_investing.brain.integrity import current_flags
            self.risk.set_name_risk(current_flags(self.settings))
        except Exception:
            pass

        # 2) Protective exits always run (even at caps / bad data); never blocked by slippage.
        # Stops must never act on a price the guard just rejected. A total feed
        # failure marks every holding at 0 and only survives today because
        # stop_orders happens to skip falsy prices; a STALE or absurd-but-
        # POSITIVE tick would sail straight through and liquidate the book at a
        # fabricated loss. Flagged symbols keep their stops until the data is
        # trustworthy again -- an unfired stop is recoverable, a phantom
        # liquidation is not. (safe_prices is built up at valuation time, because
        # equity needs exactly the same protection and needs it earlier.)
        # FOREIGN HOLDINGS (2026-08-04). A live exchange adapter reports the whole
        # account, not just what this engine opened: CcxtBroker.get_positions()
        # turns EVERY non-zero balance into a Position. A real Gemini account here
        # held 19 currencies against a 3-symbol watchlist. The engine must not
        # trade what it did not open — it has no cost basis for it (the adapter
        # substitutes the last price), no thesis for it, and no mandate over it.
        #
        # Nothing below is hypothetical: 2b executes with guard_slippage=False and
        # does not require a price, so a focus list — an innocuous-looking
        # preference like "focus on BTC and ETH" — would have market-sold every
        # other holding in the account under reason="user blocked".
        #
        # 2a was safe only by accident: stop_orders skips falsy prices, and
        # foreign symbols have no price because prices are built from the
        # watchlist. Accident is not a guarantee, so both paths are gated here
        # explicitly. Refusing to act strands a position the engine can no longer
        # exit if you remove a held symbol from the watchlist — reported below, and
        # the better failure of the two.
        universe = self._tradable_universe()
        foreign = foreign_positions(self.book.get_positions(), universe)
        if foreign:
            print(f"  !! {len(foreign)} position(s) not in this engine's universe — "
                  f"left untouched: {', '.join(sorted(foreign)[:8])}"
                  f"{' ...' if len(foreign) > 8 else ''}")

        for o in self.risk.stop_orders(portfolio, safe_prices, market=self._stats):
            if o.asset.key in foreign:
                continue
            executed.append(self._execute(o, prices, guard_slippage=False))

        # 2b) Exit any position you've blocked / de-focused (your input, applied).
        for key, pos in list(self.book.get_positions().items()):
            if key not in universe:
                continue          # re-checked against the universe, not the set
            if not self.user_views.is_allowed(pos.asset.symbol):
                side = Side.SELL if pos.qty > 0 else Side.BUY
                executed.append(self._execute(
                    Order(pos.asset, side, abs(pos.qty), reason="user blocked"), prices, guard_slippage=False))

        # 3) Decisions — excluding data-guard-flagged and user-blocked symbols.
        portfolio = self._book_portfolio()
        equity = portfolio.equity(prices)
        # DECIDE ON EVERYTHING, EXECUTE ONLY WHERE ALLOWED. These are two different
        # questions and conflating them cost a day: the live slice can only trade
        # USD stocks, so an earlier version filtered `active` down to that — which
        # also stripped crypto out of state.json's decisions, and the adviser reads
        # its formula leg from there. Result: zero crypto in 96 considered names,
        # and no way to learn whether the model's crypto view was any good.
        #
        # A prediction costs nothing and is the point of the exercise. The venue
        # restriction belongs on the ORDER, not on the opinion — see step 4.
        active = [a for a in self.assets
                  if a.key not in bad_data and self.user_views.is_allowed(a.symbol)]
        decisions = [self.engine.decide(a, bars_by_key[a.key], context) for a in active]
        features_by_key = {d.asset.key: d.features for d in decisions}
        # Adviser gate: a bounded, EVIDENCE-GATED nudge from the adviser's own
        # (separately measured) conviction -- inert until scripts/adviser_gate_check.py
        # has independently confirmed the adviser's long-side calls clear their bar.
        # Applied AFTER features_by_key is captured so the RLS learning loop keeps
        # training on the model's own pure signal, not on an adviser-nudged target.
        from ai_investing.brain.adviser_gate import apply_adviser_gate
        decisions = apply_adviser_gate(decisions, self.settings)
        for d in decisions:
            self.journal.record_decision(d)

        # 4) Size and open new positions — only if the breaker allows it.
        # With TRADE_APPROVAL on, entries first go to you on Telegram and only
        # execute once approved (exits above are never gated).
        if breaker.allow_new:
            entries = self.risk.size_orders(decisions, portfolio, prices, equity,
                                            market=self._stats, model=self.model)
            # The venue gate, applied to the ORDER. Predictions above cover every
            # watched asset; only what this book can actually trade gets sent.
            if self._ledger is not None:
                blocked = [o for o in entries if o.asset.key not in universe]
                if blocked:
                    print(f"  (not tradable in the live slice, decision recorded only: "
                          f"{', '.join(sorted({o.asset.symbol for o in blocked}))})")
                entries = [o for o in entries if o.asset.key in universe]
            # AN ORDER IN FLIGHT IS NOT A FREE SLOT. `size_orders` computes
            # `delta = target - current_notional` from POSITIONS, and a queued
            # order holds none — so while Longbridge sits on an order
            # (`NotReported`, routine outside US market hours) this book would
            # size the same entry again every cycle. That is what emptied the
            # event sleeve's book on 2026-08-17; the trading book reaches it by a
            # different route and the same door.
            in_flight = (self.book.pending_symbols()
                         if hasattr(self.book, "pending_symbols") else set())
            if in_flight:
                waiting = [o for o in entries if o.asset.symbol in in_flight]
                if waiting:
                    print(f"  (already working at the venue, not re-sent: "
                          f"{', '.join(sorted({o.asset.symbol for o in waiting}))})")
                entries = [o for o in entries if o.asset.symbol not in in_flight]
            if self.settings.trade_approval:
                entries = self._gate_entries(entries, prices)
            for o in entries:
                executed.append(self._execute(o, prices))
        elif breaker.reason:
            print(f"  (no new positions — {breaker.reason})")

        # 4a) The ₿ crypto book: crypto traded on its OWN policy, every cycle,
        # 24/7 — hard stops and the bear exit run even when stock markets are
        # shut, because that is when crypto crashes.
        try:
            from ai_investing.strategy.crypto_book import CryptoBook
            px_by_sym = {a.symbol: prices.get(a.key, 0.0) for a in self.assets}
            bars_by_sym = {a.symbol: bars_by_key.get(a.key, []) for a in self.assets}
            b_assets = (context.get("brain") or {}).get("asset_impacts") or {}
            cb = CryptoBook(self.settings).cycle(b_assets, bars_by_sym, px_by_sym,
                                                 self.notifier)
            if cb["opened"] or cb["closed"]:
                print(f"  [crypto book] +{len(cb['opened'])} -{len(cb['closed'])} | "
                      f"equity ${cb['equity']:,.0f} | "
                      f"{'BEAR — in cash' if cb['bear'] else 'risk-on'}")
        except Exception as exc:
            print(f"  [crypto book] skipped: {type(exc).__name__}: {exc}")

        # 4b) The ⚡ event sleeve (third policy): trade TODAY's fresh news shock,
        # time-boxed, own capital. Exits never wait; entries are its own book.
        if context.get("brain") and context["brain"].get("shock_assets"):
            try:
                from ai_investing.strategy.event_sleeve import EventSleeve
                px_by_sym = {a.symbol: prices.get(a.key, 0.0) for a in self.assets}
                from ai_investing.learning.spine import regime_of
                ra = ((context.get("brain") or {}).get("regime") or {}).get("risk_appetite")
                # R38/R39 gate inputs, from data the engine already pulls every
                # cycle/day: the live risk field, and BTC vs its 100d average.
                winter = False
                btc_bars = next((bars_by_key.get(a.key) or [] for a in self.assets
                                 if a.symbol == "BTC/USD"), [])
                if len(btc_bars) >= 100:
                    closes = [b.close for b in btc_bars[-100:]]
                    winter = btc_bars[-1].close < sum(closes) / len(closes)
                ev_res = EventSleeve(self.settings, self._shared_stock_broker(),
                                     lots=self.lots).cycle(
                    context["brain"]["shock_assets"], px_by_sym, self.notifier,
                    regime=regime_of(ra), risk=float(ra or 0.0), winter=winter)
                if ev_res["opened"] or ev_res["closed"]:
                    print(f"  [event sleeve] +{len(ev_res['opened'])} "
                          f"-{len(ev_res['closed'])} | equity ${ev_res['equity']:,.0f}")
            except Exception as exc:
                print(f"  [event sleeve] skipped: {type(exc).__name__}: {exc}")

        # 4c) Book realised P&L into the live slice, AFTER this cycle's fills and
        # BEFORE anything reports equity. The account tells us position quantities;
        # only the ledger knows what they cost, and only until they are reduced —
        # so this must run every cycle or a closed trade's P&L is lost for good.
        if self._ledger is not None:
            if self.book is not self.broker:
                # Its OWN claims, not a raw account read — the account is shared
                # now, so a raw read is the sleeve's and the investing book's
                # positions as well as this one's.
                booked = self._ledger.observe(
                    {k: p for k, p in self.book.get_positions().items() if k in universe},
                    prices)
                state = self.book.ledger_state()
            else:
                booked = self._ledger.observe(
                    {k: p for k, p in self.broker.get_positions().items() if k in universe},
                    prices)
                state = self._ledger.to_dict()
            if abs(booked) > 0.005:
                print(f"  LIVE BOOK  realised ${booked:+,.2f} this cycle "
                      f"(total ${self._ledger.realized:+,.2f})")
            atomic.write_json(self._ledger_path, state)
            self._reconcile_shared()

        # 5) Learn from trades that just closed.
        self._learn(prices, features_by_key)

        # 6) Record + report.
        self._finish(prices, decisions, context, halted=False)
        book = self._book_portfolio()
        self._print_positions(book, prices)
        return {"halted": False, "equity": book.equity(prices), "orders": len(executed)}

    def run_forever(self) -> None:
        print(f"Autonomous loop started (every {self.settings.poll_seconds}s). Ctrl-C to stop.")
        print(self.model.describe())
        try:
            while True:
                if self.run_cycle().get("halted"):
                    print("Halted. Sleeping until next session / manual check.")
                time.sleep(self.settings.poll_seconds)
        except KeyboardInterrupt:
            print("\nStopped by user.")
        finally:
            if self.settings.safety.flatten_on_exit and self.settings.live and self._last_prices:
                print("flatten_on_exit — closing positions.")
                self._flatten(self._last_prices)
            self.store.save(self.model, self.rls, journal=self.journal)
            self.journal.close()

    # -- safety: reconciliation ---------------------------------------------
    def _reconcile(self, portfolio) -> bool:
        """Compare current broker positions with what we left last cycle. Any drift
        (external trade, async/partial fill, rejected order we assumed filled) means our
        world model is wrong — halt in live mode rather than trade on bad state."""
        if self._shared_drift:
            print(f"!! SHARED ACCOUNT DRIFT (unresolved): {self._shared_drift}")
            print("   Refusing to trade until the books and the account agree. "
                  "Fix, then restart.")
            return False
        current = {k: p.qty for k, p in portfolio.positions.items()}
        if self._last_positions is None:
            self._last_positions = current
            return True
        # A LATE FILL IS NOT DRIFT. `resolve_pending()` runs just above and can
        # legitimately add shares that were not in last cycle's snapshot — the
        # order was ours, the venue simply confirmed it after we stopped looking.
        # Re-baseline exactly those keys, so the check still catches everything
        # it is for (an external trade, a fill we never asked for) without
        # halting on the one asynchronous outcome the design expects.
        for key in getattr(self.book, "resolved_keys", ()) or ():
            if key in current:
                self._last_positions[key] = current[key]
            else:
                self._last_positions.pop(key, None)
        drift = []
        for key in set(current) | set(self._last_positions):
            a, b = current.get(key, 0.0), self._last_positions.get(key, 0.0)
            if abs(a - b) > max(1e-6, 1e-3 * abs(b)):
                drift.append(f"{key}: expected {b:.4f} got {a:.4f}")
        if drift:
            detail = "; ".join(drift)
            self.journal.record_event("reconcile_drift", detail)
            print(f"!! RECONCILE DRIFT: {detail}")
            if self.settings.alerts.on_error:
                self.notifier.send(f"⚠️ *RECONCILE DRIFT*: {detail}")
            if self.settings.live:
                print("   Live mode — halting for manual review.")
                return False
        self._last_positions = current
        return True

    def _reconcile_shared(self) -> bool:
        """Do all the books' claims add up to what the account actually holds?

        `_reconcile()` above asks a different and now-insufficient question: "did
        MY positions change behind my back". Once three books write to one
        account that is answered "yes" every time another book trades, which is
        normal. The question that still has a right answer is whether the SUM of
        what every book claims matches the account — and that one catches
        everything the per-book rules cannot see: a trade placed by hand in the
        Longbridge app, a fill nobody claimed, a book that died mid-cycle with
        half its state written.

        Read from each book's state file rather than from live objects, because
        these books are constructed per-use and none of them is in memory by the
        time this runs. That is also the stricter test: it verifies what was
        actually PERSISTED, which is what the next cycle will act on.
        """
        if self.book is self.broker or not self.settings.shared_stock_account:
            return True
        from ai_investing.brokers.shared import reconcile_claims
        from ai_investing.execution.capital import BookLedger

        claims = {"main": self.book.working_positions()}
        data_dir = os.path.dirname(os.path.abspath(self.settings.state_path))
        for name, fname in (("event", "event_state.json"),
                            ("investor", "invest_state.json")):
            path = os.path.join(data_dir, fname)
            if not os.path.exists(path):
                # A book that has never traded has no file, and no claims. That
                # is a real answer, not a missing one — treating it as unreadable
                # would disable this check permanently on a fresh install.
                claims[name] = {}
                continue
            try:
                with open(path) as fh:
                    saved = (json.load(fh) or {}).get("stock_ledger") or {}
                claims[name] = BookLedger.from_dict(saved.get("ledger") or {}, 0.0).positions()
            except (OSError, json.JSONDecodeError, TypeError, ValueError, AttributeError):
                # A file that EXISTS but cannot be parsed is different: the book
                # holds something and we cannot tell what. Treating it as empty
                # would report every share it owns as unclaimed drift and halt
                # the engine on a half-written file.
                print(f"  [reconcile] {name}'s book is unreadable — skipping the "
                      f"aggregate check this cycle rather than guessing")
                return True

        stock = getattr(self.broker, "stock", None)
        try:
            real = stock.get_positions() if stock is not None else {}
        except Exception as exc:                                  # noqa: BLE001
            print(f"  [reconcile] cannot read the shared account: {exc}")
            return True
        drift = reconcile_claims(claims, real,
                                 base_currency=self.settings.base_currency, lots=self.lots)
        if not drift:
            return True
        detail = "; ".join(drift)
        self.journal.record_event("shared_claim_drift", detail[:500])
        print(f"!! SHARED ACCOUNT DRIFT: {detail}")
        if self.settings.alerts.on_error:
            self.notifier.send(f"⚠️ *SHARED ACCOUNT DRIFT* — the books and the "
                               f"account disagree:\n{detail}")
        if self.settings.live:
            # This check runs late in the cycle — after every book has traded —
            # so it cannot stop the cycle it detected the drift in. It stops the
            # NEXT one, which is checked at the top of `run_cycle` alongside the
            # per-book reconciliation. Cleared only by an operator: a disagreement
            # about who owns which shares does not resolve itself.
            self._shared_drift = detail
            print("   Live mode — halting the next cycle for manual review.")
        return False

    # -- learning -----------------------------------------------------------
    def _learn(self, prices: dict[str, float], features_by_key: dict[str, dict]) -> None:
        lc = self.settings.learning
        samples = self.tracker.sync(self.book.get_positions(), features_by_key, prices)
        # Written EVERY cycle, before the online-learning gate: the claims ledger
        # records which φ opened which position, and that has to survive a
        # restart whether or not the learner is switched on. Writing it after the
        # `enable_online` return would leave it permanently empty for anyone
        # running with LEARN_ONLINE=false, and silently break their learning the
        # day they turned it on.
        try:
            atomic.write_json(self._claims_path, self.tracker.state())
        except OSError:
            pass
        if not lc.enable_online:
            return
        for s in samples:
            phi = [s.features.get(n, 0.0) for n in self.model.feature_names]
            err = self.rls.update(phi, s.realized_return)
            self.samples_seen += 1
            self.journal.record_outcome(s.symbol, s.realized_return, s.features, err)
            print(f"  LEARN   {s.symbol:<10} realized {s.realized_return * 100:+.2f}%  "
                  f"pred_err {err * 100:+.2f}%  (sample #{self.samples_seen})")
        if self.samples_seen >= lc.min_samples and samples:
            self.model.weights = list(self.rls.theta)
        if samples and self._cycles % lc.save_every == 0:
            self.store.save(self.model, self.rls, journal=self.journal)

    # -- shadow "formula-only" portfolio (the comparison baseline) ----------
    def _run_shadow(self, prices, context, bars_by_key, bad_data) -> None:
        """Trade a parallel paper portfolio on pure model conviction (no user input),
        so we can measure whether YOUR input helped or hurt vs. following the formula."""
        b = self.shadow_broker
        for o in self.shadow_risk.stop_orders(b.portfolio(), prices, market=self._stats):
            self._shadow_fill(o, prices)
        port = b.portfolio()
        equity = port.equity(prices)
        active = [a for a in self.assets if a.key not in bad_data]
        decisions = [self.shadow_engine.decide(a, bars_by_key[a.key], context) for a in active]
        for o in self.shadow_risk.size_orders(decisions, port, prices, equity,
                                              market=self._stats, model=self.model):
            self._shadow_fill(o, prices)
        try:   # persist in ALL modes: the A/B must survive engine restarts
            atomic.write_json(self._shadow_path, b.state())
        except OSError:
            pass

    def _shadow_fill(self, order: Order, prices: dict[str, float]) -> None:
        mid = prices.get(order.asset.key, 0.0)
        ms = self._stats.get(order.asset.key)
        eff = self._costs_for(order.asset).effective_price(order.side, mid, order.qty,
                                                           ms.adv if ms else None, ms.vol if ms else None)
        self.shadow_broker.submit(order, eff)

    def _comparison(self, real_portfolio, prices) -> dict:
        shadow = self.shadow_broker.portfolio()
        real_pos = {p.asset.symbol: p for p in real_portfolio.positions.values()}
        shad_pos = {p.asset.symbol: p for p in shadow.positions.values()}
        assets = []
        for s in sorted(set(real_pos) | set(shad_pos)):
            rp, sp = real_pos.get(s), shad_pos.get(s)
            ref = rp or sp
            px = prices.get(ref.asset.key, ref.avg_price)
            assets.append({
                "symbol": s,
                "your_qty": round(rp.qty, 4) if rp else 0.0,
                "your_pnl": round(rp.unrealized_pnl(px), 2) if rp else 0.0,
                "formula_qty": round(sp.qty, 4) if sp else 0.0,
                "formula_pnl": round(sp.unrealized_pnl(px), 2) if sp else 0.0,
            })
        your_eq = real_portfolio.equity(prices)
        formula_eq = shadow.equity(prices)
        return {"your_equity": round(your_eq, 2), "formula_equity": round(formula_eq, 2),
                "input_value": round(your_eq - formula_eq, 2), "assets": assets}

    # -- execution helpers --------------------------------------------------
    def _gate_entries(self, entries: list[Order], prices: dict[str, float]) -> list[Order]:
        """Human-in-the-loop: an entry executes only against a fresh approval.
        Unseen entries become proposals pushed to Telegram with tap buttons;
        pending/rejected ones wait silently until decided or expired."""
        from ai_investing.execution.approvals import ProposalBook
        book = ProposalBook(self.settings.proposals_path, self.settings.approval_ttl_hours)
        book.prune()
        allowed: list[Order] = []
        asked: list[dict] = []
        for o in entries:
            sym = o.asset.symbol
            p = book.get(sym, o.side.value)
            if p and p["status"] == "approved":
                book.consume(p["id"])          # one approval buys one entry
                allowed.append(o)
            elif p:                            # pending or rejected: wait, don't nag
                continue
            else:
                price = prices.get(o.asset.key, 0.0)
                # ATR-scaled stop/take, same math the risk layer will apply
                ms = (self._stats or {}).get(o.asset.key)
                stop_pct, take_pct = self.settings.risk.per_trade_stop_loss, self.settings.risk.take_profit
                if self.settings.risk.use_atr_stops and ms is not None and ms.atr > 0 and price > 0:
                    stop_pct = self.settings.risk.atr_stop_mult * ms.atr / price
                    take_pct = self.settings.risk.atr_take_mult * ms.atr / price
                stop_pct = min(stop_pct, self.settings.risk.max_loss_per_position)
                from ai_investing.execution.explain import explain_entry
                equity = self._book_portfolio().equity(prices)
                extra = explain_entry(self.settings, sym, o.side.value, o.qty, price,
                                      o.reason, equity, stop_pct, take_pct)
                extra["horizon"] = "short"
                asked.append(book.propose(sym, o.side.value, o.qty, price, o.reason, extra))
        if asked:
            from ai_investing.execution.explain import graph_map_notes
            map_notes = graph_map_notes(self.settings,
                                        [(p["symbol"], p["side"]) for p in asked])
            sent = True
            for p in asked:      # one message per stock — easy to answer one by one
                verb = "Buy" if p["side"] == "buy" else "Bet against"
                text = (
                    f"⚡ *Trading book — approval needed* (pretend money)\n\n"
                    f"*{verb}: {p.get('label', p['symbol'])}* ({p['symbol']}"
                    f"{', ' + p['market'] if p.get('market') else ''}) — "
                    f"about *${p.get('notional', 0):,.0f}* ({p.get('pct', 0):.1%} of the trading pot)\n"
                    f"💡 *Why:* {p.get('why', p['reason'])}\n"
                    f"🤔 *This assumes:* {p.get('assumptions', 'the current picture holds')}\n"
                    f"🗺 *The plan:* {p.get('plan', 'hold while the reasons hold; automatic safety stop')}\n"
                    + (f"{map_notes[p['symbol']]}\n" if map_notes.get(p["symbol"]) else "")
                    + (f"{p['bubble_note']}\n" if p.get("bubble_note") else "")
                    + f"_No answer = it quietly expires in {self.settings.approval_ttl_hours:g}h. "
                    f"Selling to protect you never waits for approval._")
                buttons = [[(f"✅ yes, {verb.lower()} {p['symbol']}", f"ap:{p['id']}"),
                            ("❌ skip", f"rj:{p['id']}"),
                            ("🚫 never", f"b:{p['symbol']}")]]
                sent = self.notifier.send(text, buttons) and sent
            if not sent:
                print("  !! TRADE_APPROVAL is on but Telegram is not configured — "
                      f"{len(asked)} entries will wait unheard (set the bot up or unset TRADE_APPROVAL)")
            print(f"  (awaiting your approval: {', '.join(p['symbol'] for p in asked)})")
        waiting = [p["symbol"] for p in book.pending() if p["symbol"] not in {q["symbol"] for q in asked}]
        if waiting:
            print(f"  (still awaiting approval: {', '.join(waiting)})")
        return allowed

    def _execute(self, order: Order, prices: dict[str, float], guard_slippage: bool = True) -> Order:
        cid = f"{self._run_id}-{self._cycles}-{order.asset.key}-{order.side.value}"
        if cid in self._submitted:
            print(f"  SKIP     duplicate order {cid}")
            order.reason = "duplicate (idempotency)"
            return order

        key = order.asset.key
        mid = prices.get(key, 0.0)
        ms = self._stats.get(key)

        # Slippage guard: refuse to OPEN a position whose modeled cost is too high
        # (illiquid / oversized). Protective exits pass guard_slippage=False.
        if guard_slippage and mid > 0:
            frac = self._costs_for(order.asset).cost_fraction(order.qty, mid, ms.adv if ms else None, ms.vol if ms else None)
            if frac * 1e4 > self.settings.safety.max_slippage_bps:
                print(f"  SKIP     {order.asset.symbol} — modeled slippage {frac * 1e4:.0f}bps "
                      f"> {self.settings.safety.max_slippage_bps:.0f}bps cap")
                order.reason = "slippage cap"
                order.status = OrderStatus.REJECTED
                return order

        # Limit-order price protection on opening trades (protective exits stay market).
        if guard_slippage and mid > 0 and self.settings.execution.order_type == "limit":
            # the band is protection ON TOP of the market's normal frictions —
            # a flat band tighter than HK stamp duty would reject every HK fill
            cm = self._costs_for(order.asset)
            band = (self.settings.execution.limit_band_bps
                    + cm.commission_bps + cm.spread_bps) / 1e4
            order.order_type = OrderType.LIMIT
            order.limit_price = mid * (1 + band) if order.side is Side.BUY else mid * (1 - band)

        order.client_order_id = cid
        eff = self._costs_for(order.asset).effective_price(order.side, mid, order.qty,
                                                           ms.adv if ms else None, ms.vol if ms else None)
        filled = self.book.submit(order, eff)
        self._submitted.add(cid)
        self.journal.record_order(filled, self.settings.live)

        slip = (eff / mid - 1) * 100 if mid else 0.0
        print(f"  {filled.status.value.upper():8} {filled.side.value:4} "
              f"{filled.filled_qty or filled.qty:>10.4f} {order.asset.symbol:<10} "
              f"@ ${eff:,.2f} ({slip:+.2f}% cost)  ({order.reason})")

        if filled.status is OrderStatus.FILLED:
            notional = (filled.filled_qty or 0.0) * (filled.filled_price or 0.0)
            self.breaker.register_trade(notional)
            if guard_slippage and self.settings.live and self.settings.execution.stop_at_exchange:
                self._place_exchange_stop(order.asset, filled, ms)
            # Live: alert if the real fill deviated far from the mark we sized against.
            if (self.settings.live and mid
                    and abs((filled.filled_price or mid) / mid - 1) * 1e4 > 2 * self.settings.safety.max_slippage_bps):
                self.journal.record_event("slippage_alert", f"{key} fill {filled.filled_price} vs mid {mid}")
                if self.settings.alerts.on_error:
                    self.notifier.send(f"⚠️ large slippage on {order.asset.symbol}: "
                                       f"fill ${filled.filled_price} vs mid ${mid:.2f}")
            if self.settings.alerts.on_trade and notional >= self.settings.alerts.min_notional:
                emoji = "🟩" if filled.side is Side.BUY else "🟥"
                self.notifier.send(f"{emoji} *{filled.side.value.upper()}* {filled.filled_qty:.4f} "
                                   f"{order.asset.symbol} @ ${eff:,.2f}  (_{order.reason}_)")
        return filled

    def _place_exchange_stop(self, asset, filled, ms) -> None:
        """Rest a protective stop AT THE VENUE after opening a long — survives a crash and
        triggers on an intraday gap between cycles. Long-only case; experimental (untested
        vs. funded accounts). Requires a broker that implements place_stop (ccxt today)."""
        if filled.side is not Side.BUY or self.settings.risk.allow_short:
            return
        if self.book is not self.broker:
            # A VENUE-SIDE STOP CANNOT BE ATTRIBUTED. It fires hours later, with
            # no book in the loop, and reduces the account by shares that every
            # book still claims — which reads as reconciliation drift and halts
            # the engine, punishing a safety feature for working. The in-engine
            # stop (step 4 of the cycle) still runs and still protects the
            # position; what is lost is only protection BETWEEN cycles, and that
            # is a smaller loss than an accounting model nobody can trust.
            self.journal.record_event(
                "exchange_stop_skipped",
                f"{asset.symbol}: shared account — a venue-side fill cannot be "
                f"attributed to a book")
            return
        entry = filled.filled_price or 0.0
        if entry <= 0:
            return
        stop_frac = self.settings.risk.per_trade_stop_loss
        if self.settings.risk.use_atr_stops and ms and ms.atr > 0:
            stop_frac = self.settings.risk.atr_stop_mult * (ms.atr / entry)
        # The hard rule wins: whatever the ATR suggests, no position may risk more
        # than max_loss_per_position. The in-engine stop path already clamps this
        # (runner step 4); the venue-side stop must agree or the two disagree about
        # where the exit is, and the tighter one is the honest answer.
        stop_frac = min(stop_frac, self.settings.risk.max_loss_per_position)
        stop_price = entry * (1 - stop_frac)
        qty = filled.filled_qty
        if self.broker.place_stop(asset, Side.SELL, qty, stop_price):
            print(f"  STOP-SET  {asset.symbol} @ ${stop_price:,.2f} "
                  f"(-{stop_frac:.1%}, resting at the venue)")
        else:
            # WITH THE REASON. "unsupported" alone is what this recorded when the
            # live AAPL stop failed on 2026-08-05, and the position has sat
            # unprotected since with no record of why.
            why = getattr(self.broker, "last_stop_error", "") or "no reason reported"
            self.journal.record_event(
                "exchange_stop_unsupported",
                f"{asset.symbol} @ {stop_price:.4f}: {why}"[:400])
            # An open position with no stop is a risk state, not a footnote.
            print(f"  !! NO VENUE STOP for {asset.symbol} — position is unprotected "
                  f"at the venue ({why})")

        # TAKE-PROFIT, resting too. Without it the exchange holds only the downside
        # leg, so a gap UP between cycles is left entirely to the next poll — the
        # asymmetry the stop exists to remove, reintroduced on the other side.
        tp_frac = self.settings.risk.take_profit
        if self.settings.risk.use_atr_stops and ms and ms.atr > 0:
            tp_frac = self.settings.risk.atr_take_mult * (ms.atr / entry)
        if tp_frac > 0 and hasattr(self.broker, "place_take_profit"):
            tp_price = entry * (1 + tp_frac)
            if self.broker.place_take_profit(asset, Side.SELL, qty, tp_price):
                print(f"  TP-SET    {asset.symbol} @ ${tp_price:,.2f} "
                      f"(+{tp_frac:.1%}, resting at the venue)")
            else:
                self.journal.record_event("exchange_take_profit_unsupported", asset.symbol)

    def _flatten(self, prices: dict[str, float]) -> list[Order]:
        out: list[Order] = []
        for key, pos in list(self.book.get_positions().items()):
            side = Side.SELL if pos.qty > 0 else Side.BUY
            out.append(self._execute(Order(pos.asset, side, abs(pos.qty), reason="flatten"),
                                     prices, guard_slippage=False))
        return out

    def _finish(self, prices, decisions, context, halted: bool) -> None:
        portfolio = self._book_portfolio()
        self.journal.record_equity(portfolio.equity(prices), portfolio.cash, len(portfolio.positions))
        self._last_positions = {k: p.qty for k, p in portfolio.positions.items()}
        self._snapshot(prices, decisions, context, halted)

    def _print_positions(self, portfolio, prices) -> None:
        if not portfolio.positions:
            print("  (no open positions)")
            return
        for key, pos in portfolio.positions.items():
            px = mark_price(prices.get(key), pos.avg_price)   # see _snapshot
            stale = "" if mark_price(prices.get(key), 0.0) > 0.0 else "  (stale mark)"
            print(f"  HELD    {pos.qty:>10.4f} {pos.asset.symbol:<10} "
                  f"@ ${pos.avg_price:,.2f} -> ${px:,.2f}  "
                  f"PnL ${pos.unrealized_pnl(px):,.0f}{stale}")

    def _snapshot(self, prices, decisions, context, halted: bool) -> None:
        portfolio = self._book_portfolio()
        state = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "mode": "live" if self.settings.live else "paper",
            "halted": halted,
            "equity": portfolio.equity(prices),
            "cash": portfolio.cash,
            "briefing": context.get("briefing", ""),
            "formula": {
                "version": self.model.version,
                "trades_learned": self.samples_seen,
                "fitted": self.model.fitted,
                "weights": dict(zip(self.model.feature_names, self.model.weights)),
                "gain": self.model.gain,
                "entry_threshold": self.model.entry_threshold,
            },
            "controls": {
                "stance": self.user_views.stance,
                "decisiveness": self.user_views.decisiveness,
                "views": self.user_views.views,
                "blocklist": self.user_views.blocklist,
                "focus": self.user_views.focus,
            },
            # mark_price, NOT prices.get(k, avg). The dict default only covers a
            # MISSING key, and the runner writes a missing bar as `prices[k] = 0.0`
            # (§4A, still open at the source) — so a present-but-zero price sailed
            # straight through this and wrote price 0, value 0, pnl = minus the
            # entire cost basis. `equity` above survives it because Portfolio._px
            # already applies the §4.7 rule, which made this WORSE, not better:
            # the file would carry an honest equity beside positions claiming a
            # total loss, and /assets and /portfolio both read the positions. A
            # routine feed outage would have displayed a wipeout.
            "positions": [
                {"symbol": p.asset.symbol, "qty": p.qty, "avg_price": p.avg_price,
                 "price": mark_price(prices.get(k), p.avg_price),
                 "value": p.market_value(mark_price(prices.get(k), p.avg_price)),
                 "pnl": p.unrealized_pnl(mark_price(prices.get(k), p.avg_price)),
                 "stale_mark": not (mark_price(prices.get(k), 0.0) > 0.0)}
                for k, p in portfolio.positions.items()
            ],
            # The live book was the only one of the four with no staleness count,
            # which is backwards: it is the one routing real orders.
            "stale_marks": sum(1 for k in portfolio.positions
                               if not (mark_price(prices.get(k), 0.0) > 0.0)),
            "marked_at": datetime.now(timezone.utc).isoformat(),
            "decisions": [
                {"symbol": d.asset.symbol, "direction": d.direction.value,
                 "score": round(d.score, 3), "confidence": round(d.confidence, 3),
                 "expected_return": round(d.expected_return, 5),
                 "user_view": round(d.user_view, 3), "rationale": d.rationale}
                for d in decisions
            ],
        }
        state["comparison"] = self._comparison(portfolio, prices)
        data_dir = os.path.dirname(os.path.abspath(self.settings.state_path))
        try:
            os.makedirs(data_dir, exist_ok=True)
            atomic.write_json(self.settings.state_path, state, indent=2)
            # the brain REMEMBERS its holdings: persist the paper book every cycle
            if not self.settings.live and isinstance(self.broker, PaperBroker):
                atomic.write_json(self._paper_path, self.broker.state())
            self._append_history(data_dir, state)
            self._append_daily_mark(data_dir, state, halted)
            write_heartbeat(self.settings.heartbeat_path,
                            {"equity": state["equity"], "cash": state["cash"],
                             "halted": halted, "cycle": self._cycles, "mode": state["mode"]})
        except OSError:
            pass

    def _append_daily_mark(self, data_dir: str, state: dict, halted: bool) -> None:
        """One append-only equity line per SGT day for the LIVE STOCK book.

        WHY (2026-08-12). The other three books each journal a daily `mark`
        line; the live book — the one routing real orders — had none. Its only
        time series was history.json, which is a rolling 500-point INTRADAY
        buffer written every cycle, so it holds about 2.5 days and silently
        drops everything older. When the cross-book rebalancing question came
        up, per-book equity had to be reconstructed by unpacking nine nightly
        tarballs, and still yielded only 6 usable daily returns.

        Append-only and never truncated: this is the record correlation,
        per-book Sharpe and any future allocation decision get built on, and
        those need months, not 2.5 days. One line a day is ~40 bytes.
        """
        from datetime import timedelta as _td
        today = (datetime.now(timezone.utc) + _td(hours=8)).date().isoformat()
        path = os.path.join(data_dir, "stock_journal.jsonl")
        if self._last_mark_day is None:
            # Seed from the FILE, not from memory. An in-memory-only flag is
            # exactly the bug this fixes in investor.py: every restart forgets
            # it and re-logs the day. The nightly poweroff makes restarts a
            # daily event here, so this has to survive one.
            try:
                with open(path) as fh:
                    last = ""
                    for last in fh:
                        pass
                if last:
                    # read the SGT `day` field, never ts[:10] — ts is UTC, and
                    # the two disagree for the 8h that SGT is already tomorrow
                    self._last_mark_day = json.loads(last).get("day", "")
            except (OSError, json.JSONDecodeError):
                self._last_mark_day = ""
        if self._last_mark_day == today:
            return
        try:
            with open(path, "a") as fh:
                fh.write(json.dumps({
                    "ts": state["ts"], "day": today, "event": "mark",
                    "equity": round(state["equity"], 2),
                    "cash": round(state["cash"], 2),
                    "positions": len(state.get("positions") or []),
                    "stale_marks": state.get("stale_marks"),
                    "trades_learned": self.samples_seen,
                    "halted": bool(halted),
                }) + "\n")
            self._last_mark_day = today
        except OSError:
            pass          # the record is never worth failing a cycle over

    def _append_history(self, data_dir: str, state: dict) -> None:
        path = os.path.join(data_dir, "history.json")
        points = []
        if os.path.exists(path):
            try:
                with open(path) as fh:
                    points = json.load(fh).get("points", [])
            except (OSError, json.JSONDecodeError):
                points = []
        points.append({
            "ts": state["ts"], "equity": round(state["equity"], 2), "cash": round(state["cash"], 2),
            "version": self.model.version, "trades_learned": self.samples_seen,
            "shadow_equity": round(state.get("comparison", {}).get("formula_equity", state["equity"]), 2),
        })
        with open(path, "w") as fh:
            json.dump({"updated": state["ts"], "points": points[-500:]}, fh)
