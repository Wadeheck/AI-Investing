# Dashboard

Next.js control room for the AI-Investing engine. Reads the engine's JSON output
(no database driver) and polls every 5s.

## Run
```bash
npm install
npm run dev      # http://localhost:4300
```
It reads `../data/{state.json,history.json,backtest.json}` relative to `dashboard/`.
Override the location with `DATA_DIR=/abs/path npm run dev`.

Populate the data first by running the engine:
```bash
cd ../engine
python3 -m ai_investing.backtest.main --optimize --save   # -> data/backtest.json + formula
python3 -m ai_investing.main --once                        # -> data/state.json + history.json
```

## Views
- **Stat tiles** — equity, cash, formula version, trades learned.
- **Equity chart** — live equity if the loop has run, else the backtest default-vs-chosen curves (hover for values).
- **Decision formula** — the θ weight bars + hyperparameters, updating as the formula matures.
- **Backtest & walk-forward** — default vs chosen metrics, per-window out-of-sample Sharpe, adopt/keep.
- **Positions**, **Decisions feed** (with E[r] + conviction), **Global briefing**.

## Stack
Next.js 14 (App Router) + React 18, TypeScript, hand-rolled SVG charts (no chart lib),
palette from the validated data-viz reference. Dark + light via `prefers-color-scheme`.

## Notes
- The API route (`app/api/data/route.ts`) is the only server touchpoint; swap it for a
  websocket later for push updates.
- Read-only today. A future version can POST controls (pause/resume, flip live↔paper,
  edit risk limits) back to the engine.
