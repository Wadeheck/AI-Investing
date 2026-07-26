# AI-Investing — one-command control. Run `make` to see all commands.
.DEFAULT_GOAL := help
.RECIPEPREFIX := >
SHELL := /bin/bash

# Use the project venv's Python when it exists (has yfinance/ccxt/etc. installed
# by `make setup`); otherwise fall back to the system python3, which only has
# the stdlib core (paper trading with synthetic data still works, live data won't).
PYTHON := $(shell test -x $(CURDIR)/.venv/bin/python && echo $(CURDIR)/.venv/bin/python || echo python3)

help:  ## Show this help
> @echo "AI-Investing — commands:"
> @grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN{FS=":.*?## "}{printf "  make %-11s %s\n", $$1, $$2}'

setup:  ## One-time: create .env, seed data, install dashboard deps
> @bash scripts/setup.sh

run:  ## Start the engine loop + dashboard together (http://localhost:4300)
> @bash scripts/run.sh

run-prod:  ## Like `run`, but builds + serves the dashboard in production mode
> @bash scripts/run-prod.sh

dashboard:  ## Start only the dashboard
> @cd dashboard && npm run dev

engine:  ## Start only the autonomous engine loop
> @cd engine && $(PYTHON) -m ai_investing.main

once:  ## Run a single engine cycle
> @cd engine && $(PYTHON) -m ai_investing.main --once

backtest:  ## Walk-forward optimize + save the formula
> @cd engine && $(PYTHON) -m ai_investing.backtest.main --optimize --save

compare:  ## Show you vs the formula-only portfolio
> @cd engine && $(PYTHON) -m ai_investing.main --compare

views:  ## Show your current inputs (views / stance / appetite)
> @cd engine && $(PYTHON) -m ai_investing.main --show-views

test:  ## Run the engine test suite
> @cd engine && for t in tests/test_*.py; do echo "→ $$t"; $(PYTHON) "$$t" || exit 1; done

stop:  ## Stop the dashboard server
> @-pkill -f "next-server" >/dev/null 2>&1; echo "stopped"

clean:  ## Delete generated paper data (journal / state / formula / views)
> @rm -f data/*.db data/*.json && echo "cleaned data/"
