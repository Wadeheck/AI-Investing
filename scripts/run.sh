#!/usr/bin/env bash
# Start the engine loop AND the dashboard together. Ctrl-C stops both.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1
say() { printf "\033[1;34m▸ %s\033[0m\n" "$1"; }

if [ ! -d dashboard/node_modules ]; then
  say "Dashboard deps missing — run 'make setup' first."
  exit 1
fi

# Seed one cycle if there's no data yet, so the dashboard isn't blank on first load.
if [ ! -f data/state.json ]; then
  say "First run — seeding one cycle"
  ( cd engine && python3 -m ai_investing.main --once --no-news >/dev/null 2>&1 ) || true
fi

say "Starting engine loop + dashboard  —  Ctrl-C stops both"
( cd engine && exec python3 -m ai_investing.main ) &
ENGINE=$!
( cd dashboard && exec npm run dev ) &
DASH=$!

cleanup() {
  echo
  say "Stopping…"
  kill -INT "$ENGINE" 2>/dev/null || true
  kill "$DASH" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

say "Dashboard will be at  http://localhost:4300  (give it a few seconds)"
wait
