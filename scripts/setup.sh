#!/usr/bin/env bash
# One-time setup: create .env, seed data so the dashboard isn't empty, install dashboard deps.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1
say() { printf "\033[1;34m▸ %s\033[0m\n" "$1"; }
err() { printf "\033[1;31m✗ %s\033[0m\n" "$1"; }

say "Checking prerequisites"
command -v python3 >/dev/null || { err "python3 not found — install Python 3.11+"; exit 1; }
command -v node    >/dev/null || { err "node not found — install Node 18+ (for the dashboard)"; exit 1; }
python3 --version; node --version

if [ ! -f .env ]; then
  cp .env.example .env
  say "Created .env (paper mode works with no keys; edit it later to go further)"
else
  say ".env already exists — leaving it as is"
fi

say "Creating virtualenv (.venv) and installing engine dependencies"
if [ ! -d .venv ]; then
  python3 -m venv .venv || { err "python3 -m venv failed — install the venv module (e.g. python3-venv)"; exit 1; }
fi
PY="$(pwd)/.venv/bin/python"
"$PY" -m pip install --quiet --upgrade pip
"$PY" -m pip install --quiet -r engine/requirements.txt || {
  err "pip install failed — live market data (yfinance/ccxt) won't be available; paper trading with synthetic data still works"
}

say "Seeding data so the dashboard has something to show"
( cd engine && "$PY" -m ai_investing.backtest.main --optimize --save >/dev/null 2>&1 ) || say "(backtest seed skipped)"
( cd engine && "$PY" -m ai_investing.main --once --no-news >/dev/null 2>&1 ) || say "(cycle seed skipped)"
( cd engine && "$PY" -m ai_investing.main --once --no-news >/dev/null 2>&1 ) || true

say "Installing dashboard dependencies (npm) — this can take a minute"
( cd dashboard && npm install --no-audit --no-fund ) || { err "npm install failed"; exit 1; }

echo
say "Setup complete."
echo "   Start everything with:   make run      (then open http://localhost:4300)"
echo "   Or just the engine:      make once"
