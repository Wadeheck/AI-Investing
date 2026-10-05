# AI-Investing local LLM integration

Updated: 2026-10-05

## Purpose

The Mac mini's local Ollama models remain available as the no-cost fallback,
while the live ProDesk currently runs in immediate BytePlus-first mode. BytePlus
is restricted to the metered free allowance; when all configured endpoints
reach the 90% safety threshold, subsequent calls fall back synchronously to the
Mac mini. The durable queue and its scheduled timer remain installed for future
use, but the live engine/chat path is not currently deferred.

The integration is for news sentiment, event tagging, hype detection, and global briefings. It does not replace the trading decision model, risk controls, broker integration, or paper/live-trading safeguards.

## ProDesk configuration

The live ProDesk checkout is configured with these non-secret settings:

```text
LLM_PREFER_LOCAL=false
LOCAL_LLM_MODE=gateway
LOCAL_LLM_URL=https://selfs-mac-mini.taila9c02b.ts.net
LOCAL_LLM_MODEL=qwen3.5:27b
LOCAL_LLM_MODEL_FAST=qwen3.5:9b
LLM_DAILY_FREE_TOKENS=5000000
```

The live engine and chat systemd overrides currently set
`LLM_QUEUE_ENABLED=false`. The queue worker itself retains
`LLM_QUEUE_ENABLED=true` so an existing backlog can be drained deliberately.
The scheduled queue timer is disabled in the current immediate mode.

`LOCAL_LLM_API_KEY` is present in the ProDesk `.env` and is intentionally not recorded here. The ProDesk `.env` is permission-restricted and the key is sent only as a bearer token over the private Tailscale path.

## Model assignment

| AI-Investing task | Local model | Reason |
| --- | --- | --- |
| Event tagging / structured JSON | `qwen3.5:9b` | Fast per-cycle volume and lower memory/latency cost |
| Per-article sentiment | `qwen3.5:9b` | Fast repeated classification |
| Global briefing / smart analysis | `qwen3.5:27b` | Higher-quality synthesis for lower-volume work |

The Mac mini also has `qwen3-coder:30b` installed for optional repository-agent work. AI-Investing does not select it for normal inference.

## API and routing

The project supports native Ollama and an authenticated OpenAI-compatible gateway. In production it uses the gateway:

```text
GET  https://selfs-mac-mini.taila9c02b.ts.net/v1/models
POST https://selfs-mac-mini.taila9c02b.ts.net/v1/chat/completions
```

Requests include:

```text
Authorization: Bearer <local gateway key>
x-local-ai-project: ai_investing
x-local-ai-task: event_tagging | sentiment | briefing
```

The local provider is probed with a ten-minute cache to avoid unnecessary health traffic. Requests are non-streaming, use a low temperature, and suppress Qwen reasoning output so the useful answer is returned in `message.content`. Structured JSON requests retry without `response_format` if a model rejects that optional field.

In the current immediate mode, provider order is:

1. BytePlus's configured endpoint chain, while each request remains below the
   90% free-budget safety threshold.
2. Mac mini local gateway / Ollama once all eligible BytePlus endpoints reach
   that threshold, or when BytePlus is unavailable.
3. Neutral/keyword degradation when no provider is available.

The ProDesk currently uses the configured BytePlus DeepSeek-V3.2 and Dola-Seed
endpoints. It does not use a direct DeepSeek key in this path. Cloud usage is
metered per endpoint and the free-only gate prevents calls from entering the
potentially billable 90%-100% band.

The newly authorized DeepSeek-V4-Flash endpoint is not part of the live ProDesk
chain until its generated endpoint ID is added to the configuration.

## Mac mini queue path

The Mac mini local-ai-system project provides the authenticated gateway and a
PostgreSQL-backed queue worker. AI-Investing requests are tagged with the
project and task headers above so the gateway can apply the correct routing and
audit them. In immediate mode, AI-Investing calls this gateway synchronously;
the ProDesk-side SQLite queue remains available for a later scheduled mode.

## 2026-10-05 operational update

- Changed the live engine/chat path from deferred queue release to immediate
  inference.
- Reused the queue's free-only BytePlus gate for immediate calls, with local
  fallback at the 90% threshold.
- Started a one-off serial drain for the accumulated queue; it continues in the
  background while immediate calls remain enabled.
- Disabled the scheduled queue timer without deleting its service or timer
  units.
- Verified new event extraction and sign-resolution calls were recorded as
  `inferred`, not `queued`.
- At verification, ProDesk's local usage meter recorded 190,625 DeepSeek-V3.2
  tokens and 280,684 Dola-Seed tokens for the UTC day.

The verified service layout is:

| Service | Address | Function |
| --- | --- | --- |
| PostgreSQL queue database | `127.0.0.1:5432` | Leases, results, and worker heartbeat |
| Local gateway | `127.0.0.1:8787` | Authenticated OpenAI-compatible API |
| Ollama | `127.0.0.1:11434` | Local model runtime |
| Repo agent | `127.0.0.1:8788` | Optional; normally stopped |

The gateway is exposed only through Tailscale Serve and is tailnet-only. No public listener or Funnel is enabled. On the Mac mini, paid fallback is disabled for the local queue worker so the local queue cannot unexpectedly generate paid-provider spend.

## Verification completed

On 2026-09-30:

- Confirmed the Mac mini gateway health and Ollama availability.
- Confirmed all three installed models were visible through Ollama and `/v1/models`.
- Confirmed queue routing: `event_tagging` and `sentiment` selected `qwen3.5:9b`; `briefing` selected `qwen3.5:27b`.
- Confirmed successful queue processing and a healthy worker heartbeat; no pending/running backlog was present at the audit point.
- Ran an authenticated local-provider smoke request through the ProDesk configuration.
- Ran the paid fallback path and received the expected BytePlus DeepSeek backup response.
- Passed the focused live-provider and LLM hard-cap tests: `26 passed`.
- Confirmed the live ProDesk services `ai-investing.service` and `ai-investing-chat.service` were active after deployment.

## Operational checks

On the ProDesk:

```bash
cd ~/Projects/AI-Investing
systemctl --user is-active ai-investing.service ai-investing-chat.service
.venv/bin/python scripts/daily_status.py | tail -20
journalctl --user -u ai-investing -n 100 --no-pager
```

On the Mac mini:

```bash
ssh macmini
curl -fsS http://127.0.0.1:8787/health
curl -fsS -H "Authorization: Bearer <key>" http://127.0.0.1:8787/admin/queue
ollama list
```

The required local services are started with:

```bash
/Users/selfmacmini/Projects/local-ai-system/scripts/start-local-ai.sh
```

The repo agent is deliberately not started by default. It is enabled only for an explicit repository task with `START_REPO_AGENT=true`.

Never put API keys in this document, source control, or shell history.
