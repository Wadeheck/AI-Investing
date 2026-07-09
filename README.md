# AI-Investing

An autonomous, signal-driven trading engine for **stocks + crypto**. It ingests
market data, news, and sentiment; scores each asset through a stack of signals
(including a **political/pump hype detector** that *fades* manipulated spikes);
sizes positions through a hard risk layer; and executes — fully automated — through
paper or live brokers. It also produces a **global briefing** to keep you informed.

> ⚠️ **Risk warning.** Autonomous trading can lose money quickly. Most retail algos
> underperform a plain index fund. This software is provided as-is, is **not
> financial advice**, and ships **paper-first** — it trades simulated money until you
> explicitly set `LIVE_TRADING=true`. Prove your strategy on paper for weeks, then
> risk only what you can afford to lose. In Singapore, prefer MAS-regulated venues
> (see below).

---

## What it does

```
                 ┌─────────────┐   ┌──────────────┐   ┌───────────────┐
  market data ─► │  SIGNALS    │   │  DECISION    │   │  RISK LAYER   │
  news + LLM  ─► │ momentum    │─► │  blend into  │─► │ sizing, stops │─► broker ─► journal
  sentiment   ─► │ mean-revert │   │  conviction  │   │ drawdown kill │     │        (SQLite)
  hype flags  ─► │ sentiment   │   │  per asset   │   │ exposure caps │     ▼
                 │ hype-fade   │   └──────────────┘   └───────────────┘  state.json ─► dashboard
                 └─────────────┘
```

### The signals (`engine/ai_investing/signals/`)
- **momentum** — fast vs slow SMA trend, tempered by RSI extremes.
- **mean_reversion** — fades statistical extremes (z-score vs a volatility band).
- **sentiment** — per-asset news sentiment scored by Claude.
- **political_hype** — **the anti-manipulation edge.** Detects sharp price+volume
  pumps, *especially* when they coincide with promotional or political news (a
  president/official hyping an asset, meme-coin launches), and returns a **negative
  (fade/avoid)** score because those spikes tend to revert.

### The risk layer (`engine/ai_investing/strategy/risk.py`)
Per-asset weight cap · gross-exposure cap · per-trade stop-loss & take-profit ·
minimum-confidence filter · max open positions · **daily-drawdown kill switch** that
flattens everything and halts for the day. Every order passes through it.

---

## Quick start

Two commands (needs Python 3.11+ and Node 18+):

```bash
make setup     # one-time: creates .env, seeds data, installs the dashboard
make run       # engine loop + dashboard together  →  http://localhost:4300
```

Open the dashboard, set your views, and watch it trade paper money. Run `make` on its own
to list every command (`once`, `backtest`, `compare`, `views`, `test`, `clean`, …).

Prefer the engine alone? Its core is **Python-stdlib-only** — no `pip install` to start:

```bash
cd engine
python3 -m ai_investing.main --once --no-news   # one offline paper cycle
python3 tests/test_smoke.py                      # sanity checks
```

Then add real data + a global briefing:

```bash
cp ../.env.example ../.env        # then edit ../.env
pip install -r requirements.txt   # optional: real data / live brokers
python3 -m ai_investing.main --briefing         # AI world briefing (needs ANTHROPIC_API_KEY)
python3 -m ai_investing.main                     # autonomous loop (fully automated)
```

Artifacts land in `data/`: `journal.db` (auditable decisions/orders/equity) and
`state.json` (latest snapshot for the dashboard).

---

## Configuration

Everything is in `.env` (copy from `.env.example`). Key switches:

| Variable | Default | Meaning |
|---|---|---|
| `LIVE_TRADING` | `false` | **Keep false until proven.** `true` routes real orders. |
| `DATA_PROVIDER` | `synthetic` | `synthetic` \| `stooq` \| `yfinance` \| `ccxt` |
| `STOCK_BROKER` | `paper` | `paper` \| `longbridge` \| `moomoo` |
| `CRYPTO_EXCHANGE` | `coinbase` | any ccxt id: `coinbase`/`gemini`/`binance`/`kraken` |
| `ANTHROPIC_API_KEY` | – | enables news sentiment, hype detection, briefing |
| `RISK_*` | see file | the guardrails (stops, drawdown kill switch, caps) |

---

## Singapore broker guide (researched July 2026)

Every broker you use has an API. Recommended regulated starter pair: **Longbridge
(stocks) + Coinbase (crypto)**.

| Venue | Asset | API | MAS status |
|---|---|---|---|
| **Longbridge** | stocks (SG/HK/US/CN) | LongPort OpenAPI, `pip install longbridge` (cloud, key+secret) | ✅ regulated |
| **moomoo** | stocks/options/futures | moomoo OpenAPI + local **OpenD** gateway, `moomoo-api` | ✅ regulated |
| **Coinbase** | crypto | Advanced Trade API (via `ccxt`) | ✅ full MPI licence |
| **Gemini** | crypto | REST + **sandbox** (via `ccxt`) | 🟡 MAS in-principle approval |
| **Binance** | crypto | best API + testnet (via `ccxt`) | ⚠️ **not** licensed; on MAS alert list |

Live adapters live in `engine/ai_investing/brokers/live.py` (ccxt is partly wired;
Longbridge/moomoo are structured stubs with SDK sketches and a `NotImplementedError`
guard until you finish + test them against a sandbox/paper endpoint).

Docs: [moomoo](https://openapi.moomoo.com/moomoo-api-doc/en/) ·
[LongPort](https://open.longbridge.com/) ·
[Coinbase MPI](https://www.coinbase.com/blog/coinbase-obtains-major-payment-institution-licence-from-the-monetary) ·
[ccxt](https://docs.ccxt.com/)

---

## Going live (the careful path)
1. Run **paper mode for weeks**; review `journal.db` and equity curve.
2. Wire ONE live adapter; test against its **sandbox / SIMULATE** endpoint.
3. Fund a small amount. Set tight `RISK_*` limits. Set `LIVE_TRADING=true`.
4. Watch it daily. The kill switch is your seatbelt, not your strategy.

---

## The adaptive formula (see `docs/FORMULA.md`)
Decisions come from a learned formula `conviction = tanh(gain · θ·φ)` whose weights `θ`
are **curated offline** (walk-forward ridge fit + champion/challenger) and **matured
online** (regularized RLS from realized P&L). It targets long-run Sharpe, not last-trade
reactions. Curate and inspect it:

```bash
cd engine
python3 -m ai_investing.backtest.main --optimize --save   # walk-forward curate θ, persist winner
python3 -m ai_investing.main --formula                     # show the current formula
```

## Your input — the decisive factor
The formula blends signals + news + sentiment into a `model_conviction`; **your view then
tilts it, and can override it**:

```
final = (1 − w)·model_conviction + w·your_view ,  w = decisiveness × |your view|
        then scaled by your risk stance × risk appetite
```

Set it the easy way in the **dashboard** — per-asset bullish↔bearish sliders, a risk-stance
selector, decisiveness + **risk-appetite** dials, and block toggles. It writes `data/views.json`,
which the engine re-reads **every cycle** (live). Or from the CLI:

```bash
python3 -m ai_investing.main --view NVDA=0.8 --view TSLA=-0.5   # bullish NVDA, bearish TSLA
python3 -m ai_investing.main --stance cautious                  # aggressive|normal|cautious|defensive|cash
python3 -m ai_investing.main --risk-appetite 0.3               # 0..1 — scales your position sizing
python3 -m ai_investing.main --block DOGE/USD                   # never trade it
python3 -m ai_investing.main --show-views
```

A strong view with high decisiveness wins; no view means the model runs untouched.
**Safety limits (circuit breaker, caps) always override your input** — you can't tell it to
keep losing.

### Your input vs. the formula
The engine runs a **shadow "formula-only" portfolio** in parallel that ignores your input, so
you can see whether your overrides help or hurt. The dashboard shows both equity curves plus a
per-override table; from the CLI:

```bash
python3 -m ai_investing.main --compare
# You (with your input):   $100,000.00
# Formula-only (no input): $99,998.78
# Value of your input:     $1.22   (your input is AHEAD)   ← e.g. you skipped a TSLA trade that lost
```

So when you say "don't trade TSLA" but the formula buys it, you see exactly what that trade did
and whether skipping it was right.

## Dashboard (`dashboard/`)
A Next.js control room: equity curve (live or backtest), stat tiles, the **evolving
formula weights** (θ bars), the walk-forward comparison, open positions, the decisions
feed, and the global briefing. Reads the engine's JSON (`state.json`, `history.json`,
`backtest.json`) — no database driver needed. Polls every 5s.

```bash
cd dashboard
npm install
npm run dev          # http://localhost:4300  (reads ../data)
```

## Live trading (the careful path)
Live adapters are implemented for **ccxt** (Coinbase/Gemini/Binance/Kraken), **Longbridge**,
and **moomoo**, and route automatically (stocks → Longbridge/moomoo, crypto → ccxt). They
are written to each SDK's API but **not yet tested against funded accounts** — validate first:

```bash
cd engine
python3 -m ai_investing.main --check-broker   # read-only: checks credentials/connectivity
```
Then trade tiny against each venue's **sandbox / SIMULATE** endpoint before setting
`LIVE_TRADING=true`. moomoo defaults to `SIMULATE`; set `MOOMOO_TRD_ENV=REAL` only when proven.

## Realism, risk & statistical honesty (M7)
The things that stop a good-looking backtest from losing money live:

- **Transaction costs** (`execution/costs.py`) — commission + half-spread + square-root
  market impact (`~coef·vol·√(Q/ADV)`) penalize every fill, in backtest and paper. The
  optimizer can no longer select fantasy high-churn strategies.
- **Purged/embargoed walk-forward + Deflated Sharpe** (`learning/objective.py`) — an
  embargo gap stops label leakage, and the winner's Sharpe is deflated by the number of
  trials searched. It **only adopts if the Deflated Sharpe clears a threshold** — i.e.
  the edge survives the multiple-testing bias, not just the max of noise.
- **Volatility-targeted sizing + ATR stops** — equal-risk position sizing (∝ 1/vol) and
  stops that scale with each asset's true range, not a flat %.
- **Portfolio risk** (`strategy/risk.py`) — correlation penalty (correlated longs ≠
  independent bets), a portfolio-vol target, and gross exposure that shrinks as drawdown
  from the peak grows.
- **Regime / out-of-distribution gate** (`strategy/regime.py`) — cut size in high-vol
  regimes or when today's features are far from the data θ was fit on.
- **Broker reconciliation + idempotent orders** (`runner.py`) — every cycle checks the
  engine's position model against the broker and halts on drift; client order IDs stop a
  crash-restart from double-firing.
- **Validate before you size** (`research/event_study.py`) — measure whether fading pumps
  actually pays *before* trusting the hype signal: `python3 -m ai_investing.research.event_study`.

## Alerts & alt-data
- **Telegram alerts** (`alerts/telegram.py`) — startup, every fill, kill-switch,
  reconciliation drift, and errors, via the Bot API (stdlib, no SDK). Configure
  `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`; test with
  `python3 -m ai_investing.main --test-alert`. No token → silently no-ops.
- **Alt-data** (`data/altdata.py`) — the manipulation edge, folded into the hype/sentiment
  signals when `ALTDATA_ENABLED=true`. Probe it: `python3 -m ai_investing.main --altdata`.
  - `crypto_hype` (CoinGecko) — **live, keyless** (24h move, volume/mcap churn, vote skew).
  - `options_flow` (Polygon) — call/put skew + volume-vs-OI; needs `POLYGON_API_KEY`.
  - `social_velocity` (Reddit) — mention count + upvote ratio; public endpoint is often
    rate-limited/blocked, so treat as best-effort until you add proper auth.

## Hard safety layer (M8) — bounds the worst case
`safety/` turns "a bug or a gap can quietly ruin you overnight" into "the damage is
capped and you get paged":
- **Persistent circuit breaker** (`safety/circuit_breaker.py`) — **daily** (auto-clears),
  **trailing** (from peak, latched), and **inception** (from day one, latched) drawdown
  halts. State is written to `data/breaker.json`, so **a restart can't reset your loss
  limits** (the old kill switch's hole). Inspect/clear: `--breaker-status` / `--breaker-reset`.
- **Per-day hard caps** — max trades/day and max traded-notional/day stop it opening more.
- **Slippage guard** — refuses to *open* a position whose modeled cost exceeds
  `SAFETY_MAX_SLIPPAGE_BPS` (illiquid/oversized); protective exits are never blocked.
- **Data sanity guard** (`safety/data_guard.py`) — excludes symbols with non-positive,
  stale, or absurdly-jumped prices so bad data can't trigger a trade.
- **Config preflight** (`safety/preflight.py`) — validates `.env` on startup and
  **refuses to run LIVE with config errors**.
- **Dead-man's switch** — the loop writes a heartbeat; run `--watchdog` (e.g. via cron)
  to alert and optionally flatten if the engine hangs/dies. `SAFETY_FLATTEN_ON_EXIT`
  closes out on shutdown.

> These bound losses; they don't create profit. Pair them with tiny capital,
> trade-only API keys, and paper/sandbox proof first.

## Execution price protection (M9)
- **Limit orders by default** (`EXECUTION_ORDER_TYPE=limit`) — every opening trade is a
  limit at `mid ± EXECUTION_LIMIT_BAND_BPS`, so you never fill worse than the band (a
  too-tight band correctly rejects). Protective exits stay market so they always get you out.
- **Intraday data** — set `DATA_TIMEFRAME=1h`/`15m`/`5m` (yfinance/ccxt) and lower
  `POLL_SECONDS` so stops react intraday instead of once a day.
- **Native exchange stops** (`EXECUTION_STOP_AT_EXCHANGE=true`; ccxt, long-only,
  *experimental/untested*) — rest a stop at the venue after opening, so protection survives
  a crash and triggers on an intraday gap between cycles.
- **Operational security** — [`SECURITY.md`](SECURITY.md): trade-only keys, regulated
  venues, host hardening, and an independent exchange-level backstop.

## Roadmap
- [x] **M1 — Engine core** (data, signals, decision, risk, paper broker, journal, loop) ✅
- [x] **M3 — Backtesting + adaptive learning engine** (walk-forward, ridge + online RLS,
      champion/challenger, versioned θ) ✅
- [x] **M2 — Next.js dashboard** (equity, evolving θ, backtest, positions, decisions, briefing) ✅
- [x] **M4 — Live adapters** routed + `--check-broker` + sandbox mode (⚠️ need sandbox validation) ✅
- [x] **M7 — Execution realism, portfolio risk, statistical validation, ops safety** ✅
- [x] **M6 — Telegram alerts** (startup / trades / kill-switch / reconcile / errors) ✅
- [x] **M8 — Hard safety layer** (persistent circuit breaker, per-day caps, slippage +
      data guards, config preflight, dead-man's switch) ✅
- [x] **M9 — Execution price protection** (limit orders, intraday timeframe, native
      exchange stops) + SECURITY.md ✅
- [x] **M10 — Your input as the decisive factor** (per-asset views, risk stance, blocklist;
      dashboard controls + CLI; safety still overrides) ✅
- [x] **M11 — Risk appetite + you-vs-formula comparison** (shadow "formula-only" portfolio,
      per-override table, dual equity curve, `--compare`) ✅
- [~] **M5 — Alt-data live**: CoinGecko crypto-hype working; Polygon options (key) + Reddit
      social (best-effort) wired into hype/sentiment. Next: paid options/social + on-chain flows.

## Layout
```
engine/ai_investing/
  config.py  models.py  indicators.py  runner.py  main.py
  signals/   momentum · mean_reversion · sentiment · political_hype
  data/      providers (synthetic/stooq/yfinance/ccxt) · news (RSS + Claude)
  brokers/   base · paper · live (ccxt/longbridge/moomoo)
  strategy/  decision · risk
  storage/   journal (SQLite)
dashboard/   (Next.js — Milestone 2)
```

*Not financial advice. Trade at your own risk.*
