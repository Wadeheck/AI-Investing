#!/usr/bin/env bash
# Boot recovery: heal, then bring the engine back — automatically, after any
# shutdown (planned, crash, or power loss). Paper mode only; the engine refuses
# LIVE with config errors regardless.
#
# SINGLETON: never start a second engine on the same books. Two engines sharing
# data/paper_state.json would corrupt the record.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1
PY="$(pwd)/.venv/bin/python"
[ -x "$PY" ] || PY="python3"

if bash scripts/engine_pid.sh >/dev/null; then
  echo "[boot] engine already running — nothing to do"
  exit 0
fi

echo "[boot] $(date -u +'%Y-%m-%d %H:%M UTC') recovering"
"$PY" scripts/startup_heal.py

echo "[boot] starting engine loop (paper)"
cd engine && exec "$PY" -m ai_investing.main
