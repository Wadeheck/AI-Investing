#!/usr/bin/env bash
# Start the engine loop AND the dashboard together. Ctrl-C stops both.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1
say() { printf "\033[1;34m▸ %s\033[0m\n" "$1"; }

# Use the project venv's Python when it exists (has yfinance/ccxt/etc. installed
# by `make setup`); otherwise fall back to the system python3.
PY="python3"
[ -x "$(pwd)/.venv/bin/python" ] && PY="$(pwd)/.venv/bin/python"

if [ ! -d dashboard/node_modules ]; then
  say "Dashboard deps missing — run 'make setup' first."
  exit 1
fi

# .env isn't valid shell (some values have unescaped spaces/parens), so pull
# out just the dashboard-facing vars instead of sourcing the whole file.
# The engine loads .env itself directly and doesn't need this.
if [ -f .env ]; then
  export DASHBOARD_USER="$(sed -nE 's/^DASHBOARD_USER=(.*)$/\1/p' .env | tail -1)"
  export DASHBOARD_PASSWORD="$(sed -nE 's/^DASHBOARD_PASSWORD=(.*)$/\1/p' .env | tail -1)"
fi

# Seed one cycle if there's no data yet, so the dashboard isn't blank on first load.
if [ ! -f data/state.json ]; then
  say "First run — seeding one cycle"
  ( cd engine && "$PY" -m ai_investing.main --once --no-news >/dev/null 2>&1 ) || true
fi

# SELF-HEAL: cron does not catch up on jobs missed while the machine was off,
# and crypto trades through the gap. Refresh anything stale BEFORE the engine
# makes its first decision, and record the blind window in the journals.
# SINGLETON GUARD: two engines on one set of books corrupts the record.
if pgrep -f "ai_investing.main" >/dev/null 2>&1; then
  say "An engine is ALREADY running (pgrep ai_investing.main)."
  say "Stop it first, or use the dashboard alone. Refusing to start a second."
  exit 1
fi

say "Self-healing after downtime (refreshing anything stale)"
"$PY" scripts/startup_heal.py || say "self-heal had problems — continuing anyway"

say "Starting engine loop + dashboard  —  Ctrl-C stops everything"
( cd engine && exec "$PY" -m ai_investing.main ) &
ENGINE=$!
( cd dashboard && exec npm run dev ) &
DASH=$!

# Telegram chat bot (answers your taps/questions) — only if the bot is configured.
CHAT=""
if grep -qE '^TELEGRAM_BOT_TOKEN=.+' .env 2>/dev/null && grep -qE '^TELEGRAM_CHAT_ID=.+' .env 2>/dev/null; then
  say "Starting Telegram chat bot (approve/skip buttons + questions)"
  ( cd engine && exec "$PY" -m ai_investing.main --chat ) &
  CHAT=$!
fi

cleanup() {
  echo
  say "Stopping…"
  kill -INT "$ENGINE" 2>/dev/null || true
  kill "$DASH" 2>/dev/null || true
  [ -n "$CHAT" ] && kill "$CHAT" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

say "Dashboard will be at  http://localhost:4300  (give it a few seconds)"
wait
