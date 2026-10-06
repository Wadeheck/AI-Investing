# Root-cause repairs — 2026-10-06

## Durable headline backlog

The inference queue had drained successfully; the remaining work lived in
`pending_news`. The live brain was capped at 30 headlines per normal
20-minute extraction window, so a multi-day backlog could persist even with an
empty LLM queue.

`extraction_due()` now enters bounded catch-up when immediate mode has at least
120 durable headlines: it claims at most one extraction window every 300 seconds
(the normal engine cadence), while `Brain.think()` retains its 30-headline batch
cap. Queue mode keeps its existing scheduled behavior. This is serial catch-up,
not concurrent release.

## Frozen RSS sources

The reader cannot repair a publisher that still returns an old valid feed. The
configuration now supports `NEWS_RSS_DISABLED`, matching exact URLs or hosts,
so a frozen source is removed from polling, cache replay, and health reporting
without replacing the complete feed list. The live deployment retires
`blockworks.co` and `gov.cn`; other China/crypto wires remain active.

## Allowance forecast

The watchdog now understands the active free-only policy: a raw end-of-day
projection above 100% is not an overrun when the 90% endpoint guard will route
to the healthy local gateway. It still reports stale if that fallback is not
reachable.

## BAESY liquidity rejection

Longbridge error 603059 means the market has no opposing liquidity for the
market order. The shared broker now suppresses repeated SELL submissions for a
bounded one-hour cooldown after that exact rejection. The original rejection
remains journalled; cooldown cycles are printed as local skips and do not call
the venue again. No forced limit order or aggressive price change was added.

The unrelated desktop portal systemd failures were not changed.
