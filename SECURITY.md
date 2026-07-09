# Security & operational safety

The code guards can bound *market* losses; they cannot protect you from a stolen key, a
hacked host, or an unregulated venue. Those are on you. Do all of this **before** live.

## API keys (the biggest avoidable loss)
- **Trade-only, never withdrawal.** Create exchange/broker API keys scoped to *trading*
  with **withdrawals disabled**. If a key with withdrawal rights leaks, your funds are gone.
- **IP-whitelist** the key to the host running the engine.
- Keep keys in `.env` only (git-ignored). Never commit them; never paste them anywhere.
- **Rotate** keys periodically and immediately if the host is ever exposed.
- Give the account only the capital you're actively trading.

## Where your money sits
- **Prefer MAS-regulated venues** (Coinbase, Longbridge). Binance is *not* regulated for
  Singapore — using it means zero local protection if it freezes or fails.
- **Keep most funds off the exchange.** Exchanges get hacked or go insolvent (FTX). Only
  keep what the strategy needs to trade; sweep profits out.
- Understand each venue's custody, insurance, and withdrawal terms.

## The host
- Run on a machine you control and keep patched; restrict SSH; full-disk encryption.
- Don't run the engine on a shared/untrusted box — it holds live trading keys.
- Back up `data/` (journal, formula, breaker state) but **exclude `.env`**.

## Independent backstop
- The circuit breaker is *software*; a bug in it fails exactly when needed. Set an
  **exchange-level max-loss / stop** that does **not** depend on this code, where the
  venue supports it. `EXECUTION_STOP_AT_EXCHANGE=true` also rests venue-side stops (ccxt,
  experimental — verify they actually appear on the exchange).

## Before going live — checklist
- [ ] Paper/sandbox traded for weeks; beats buy-and-hold **net of costs**.
- [ ] `--check-broker` passes; placed one tiny manual-sized order and it landed correctly.
- [ ] API keys are trade-only, no withdrawal, IP-whitelisted.
- [ ] `SAFETY_MAX_NOTIONAL_PER_DAY`, trailing/inception drawdown limits set sensibly.
- [ ] `--watchdog` scheduled (cron) with alerts configured; tested with `--test-alert`.
- [ ] Capital is money you can afford to lose entirely, started small.
- [ ] You understand the tax/reporting and pattern-day-trading implications of frequent trading.

## If something looks wrong
- `python3 -m ai_investing.main --breaker-status` — see halts / daily usage.
- `--breaker-reset` — clear a latched halt after you've reviewed.
- Kill the process; the account's real positions are the source of truth (reconciliation
  halts the engine on any drift).

*Nothing here is financial, legal, or tax advice.*
