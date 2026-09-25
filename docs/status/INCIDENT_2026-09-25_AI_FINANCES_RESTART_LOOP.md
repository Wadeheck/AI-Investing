# Incident: AI Finances app restart loop

**Date:** 2026-09-25  
**Host:** ProDesk (`eugene-HP-ProDesk-400-G6-Desktop-Mini-PC`)  
**Component:** Docker container `ai_finances_app`  
**Status:** Resolved

## Symptom

The app repeatedly restarted on the ProDesk, consuming unnecessary process and
logging resources. Docker reported the container as `Restarting (1)` with an
`unless-stopped` restart policy. The restart count reached 394 during the
investigation.

The AI-Investing systemd engine was also checked and was not in a restart loop:
it was active with `NRestarts=0`. Its daily stop/start was the expected ProDesk
power-cycle schedule, not the incident described here.

## Root cause

`ai_finances_app` was configured to use the external Docker network
`personal_db_net`, with `DATABASE_URL` pointing at the database service name
`db`. The container had lost its live network endpoint, while
`personal_db_postgres` remained attached to `personal_db_net` at
`172.19.0.2`.

Without the network endpoint, the app failed during import-time database
initialization with:

```text
psycopg.OperationalError: failed to resolve host 'db'
```

Because the container used `restart: unless-stopped`, Docker relaunched it
continuously after each exit.

## Fix

On the ProDesk, the failing container was briefly stopped to break the restart
loop. It was then attached to the existing `personal_db_net`, its original
`unless-stopped` policy was restored, and the container was started again.

No application source, database data, credentials, or AI-Investing services
were changed.

## Verification

After the repair:

- `ai_finances_app` remained `running` with `restarting=false`.
- No Docker restart events occurred after the repair.
- The container's restart count was `0` after the clean start.
- The app resolved the database network and completed Uvicorn startup.
- `http://100.64.113.103:8000/` returned `200 OK`.
- The app used approximately 47 MiB of memory during the follow-up check.
- A later check at 14:10 SGT confirmed the container was still stable.

## Follow-up

If this recurs, check the container's Docker network membership before changing
the restart policy or application code:

```bash
docker inspect ai_finances_app --format '{{json .NetworkSettings.Networks}}'
docker network inspect personal_db_net
docker logs --tail 100 ai_finances_app
```

The expected state is that both `ai_finances_app` and
`personal_db_postgres` are attached to `personal_db_net`, and that the app can
resolve the hostname `db`.
