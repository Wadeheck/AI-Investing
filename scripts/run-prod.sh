#!/usr/bin/env bash
# Production-mode run: builds the dashboard and serves it with `next start`
# instead of the dev server. Use this for any always-on / unattended /
# beyond-localhost deployment. For fast local iteration, use `make run` instead.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1
say() { printf "\033[1;34m▸ %s\033[0m\n" "$1"; }

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
  ( cd engine && python3 -m ai_investing.main --once --no-news >/dev/null 2>&1 ) || true
fi

say "Building dashboard for production"
( cd dashboard && npm run build ) || { echo "Dashboard build failed"; exit 1; }

say "Starting engine loop + dashboard (production)  —  Ctrl-C stops both"
( cd engine && exec python3 -m ai_investing.main ) &
ENGINE=$!
( cd dashboard && exec npm run start ) &
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
