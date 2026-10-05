# ProDesk LLM queue

## Purpose

The ProDesk engine can continue collecting news and making non-LLM progress
without waking or repeatedly calling the Mac Mini/Ollama service. LLM work is
persisted locally and released by a scheduled worker. Ollama keep-alive and Mac
Mini power policy are intentionally outside this project.

## Flow

1. The engine stores headlines that need deferred extraction in the
   `pending_news` table in `data/inference_control.sqlite3`.
2. Each extraction request is split into the normal ten-headline batches. The
   request key includes the task, provider/model fingerprint, and full prompt,
   so retries and repeated engine cycles are idempotent.
3. `ai_investing.llm_queue` materializes every pending headline batch before a
   drain. Materialization only writes SQLite rows; it does not contact an LLM.
4. The worker claims one job at a time, preferring fast-tier work, and sends it
   through the existing local-first provider chain.
5. Successful JSON responses are written to the normal inference cache for 48
   hours. A later engine cycle consumes the cached result and marks the source
   headlines digested.
6. Empty, invalid, or failed responses are retained and retried with bounded
   backoff. A lease makes an interrupted job eligible again after a worker
   failure or power loss.

The queue is therefore serial by design. “Batching” refers to keeping several
headlines in one prompt and keeping the model resident across a drain; it does
not mean sending many simultaneous requests.

## Schedule and power-off behavior

`deploy/systemd/ai-investing-llm-queue.timer` releases the queue at:

- 00:00 SGT
- 08:00 SGT
- 18:00 SGT

The ProDesk host should use Singapore/Kuala Lumpur time. `Persistent=true`
causes a missed timer event to be caught up when the user systemd manager comes
back after a scheduled power-off. The queue database itself is durable, so
headlines and unfinished jobs survive either a ProDesk shutdown or a provider
failure.

There is no per-window job cap by default. `LLM_QUEUE_MAX_JOBS` can be set when
a deliberately bounded release is needed. The service has a 12-hour timeout;
unfinished work remains queued for the next release window.

## Operations

Install or refresh the units with `deploy/install.sh`, then reload and enable
the timer through the user systemd manager. The queue worker can be inspected
without sending work:

```bash
cd /home/eugene/Projects/AI-Investing/engine
python -m ai_investing.llm_queue --status
```

For a deliberate one-off release, start the oneshot service directly. This
uses exactly the same serial drain as a timer event:

```bash
systemctl --user start ai-investing-llm-queue.service
```

`--materialize-only` is available when the backlog should be prepared without
contacting a provider. The worker log is written to
`data/llm_queue.log`; the durable counts in SQLite are the source of truth.

## Configuration

- `LLM_QUEUE_ENABLED=true` enables deferred provider work in the engine.
- `LLM_QUEUE_LEASE_SECONDS` controls recovery of a running job; the default is
  900 seconds.
- `LLM_QUEUE_MAX_JOBS=0` means no per-run limit.
- `LLM_QUEUE_CACHE_HOURS=48` controls the queued-result cache lifetime.

The service unit sets `LLM_QUEUE_ENABLED=true`. Provider credentials and local
gateway settings continue to come from the project `.env` through the normal
configuration loader. No credentials or prompts are logged by the queue.

## Verification

The queue-specific tests cover deferred persistence, serial draining, cache
reuse, and requeueing after failure:

```bash
python -m pytest engine/tests/test_llm_queue.py -q
```
