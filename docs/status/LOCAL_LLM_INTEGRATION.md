# AI-Investing local LLM integration

Updated: 2026-09-30

## Purpose

AI-Investing now uses the Mac mini's local Ollama models as its primary LLM provider. The paid BytePlus/DeepSeek path remains configured as a resilience fallback, so a Mac mini or Tailscale outage degrades the system rather than silently removing all news understanding.

The integration is for news sentiment, event tagging, hype detection, and global briefings. It does not replace the trading decision model, risk controls, broker integration, or paper/live-trading safeguards.

## ProDesk configuration

The live ProDesk checkout is configured with these non-secret settings:

```text
LLM_PREFER_LOCAL=true
LOCAL_LLM_MODE=gateway
LOCAL_LLM_URL=https://selfs-mac-mini.taila9c02b.ts.net
LOCAL_LLM_MODEL=qwen3.5:27b
LOCAL_LLM_MODEL_FAST=qwen3.5:9b
```

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

With `LLM_PREFER_LOCAL=true`, provider order is:

1. Mac mini local gateway / Ollama.
2. Direct DeepSeek, if `DEEPSEEK_API_KEY` is configured.
3. BytePlus's configured SMART chain, whose live primary endpoint is the DeepSeek-V3.2 deployment, followed by its authorized failover endpoints.
4. Anthropic, if configured.
5. Neutral/keyword degradation when no provider is available.

The ProDesk currently uses the BytePlus DeepSeek-V3.2 endpoint as its paid backup; it does not need a separate direct DeepSeek key. Cloud endpoint usage remains metered against the configured free allowance and is refused rather than allowed to cross the hard cap.

## Mac mini queue path

The Mac mini local-ai-system project provides the authenticated gateway and a PostgreSQL-backed queue worker. AI-Investing requests are tagged with the project and task headers above so the gateway can apply the correct routing and audit them.

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
