import { WeightBars } from "@/components/charts";
import type { BacktestData, HistoryData, StateData } from "@/lib/types";

function money(v: number): string {
  return `$${Math.round(v).toLocaleString()}`;
}
function pct(v: number): string {
  return `${v >= 0 ? "+" : ""}${(v * 100).toFixed(2)}%`;
}
function cls(v: number): string {
  return v >= 0 ? "pos" : "neg";
}

export function StatTiles({ state, history }: { state: StateData | null; history: HistoryData | null }) {
  const pts = history?.points ?? [];
  const sessionChange = pts.length >= 2 && pts[0].equity ? pts[pts.length - 1].equity / pts[0].equity - 1 : 0;
  const equity = state?.equity ?? (pts.length ? pts[pts.length - 1].equity : 0);
  const cash = state?.cash ?? (pts.length ? pts[pts.length - 1].cash : 0);
  const trades = state?.formula?.trades_learned ?? (pts.length ? pts[pts.length - 1].trades_learned : 0);

  return (
    <div className="grid cols-4">
      <div className="card kpi">
        <div className="label">Equity</div>
        <div className="value">{money(equity)}</div>
        <div className={`delta ${cls(sessionChange)}`}>{pct(sessionChange)} session</div>
      </div>
      <div className="card kpi">
        <div className="label">Cash</div>
        <div className="value">{money(cash)}</div>
        <div className="delta muted">{equity ? ((cash / equity) * 100).toFixed(0) : 0}% of equity</div>
      </div>
      <div className="card kpi">
        <div className="label">Formula version</div>
        <div className="value">v{state?.formula?.version ?? 0}</div>
        <div className="delta muted">{state?.formula?.fitted ? "curated + live" : "default"}</div>
      </div>
      <div className="card kpi">
        <div className="label">Trades learned</div>
        <div className="value">{trades ?? 0}</div>
        <div className="delta muted">online RLS updates</div>
      </div>
    </div>
  );
}

export function PositionsTable({ state }: { state: StateData | null }) {
  const positions = state?.positions ?? [];
  return (
    <div className="card">
      <h2>Open positions</h2>
      {positions.length === 0 ? (
        <div className="empty">Flat — no open positions.</div>
      ) : (
        <table>
          <thead>
            <tr><th>Symbol</th><th>Qty</th><th>Avg</th><th>Price</th><th>Value</th><th>P&amp;L</th></tr>
          </thead>
          <tbody>
            {positions.map((p) => (
              <tr key={p.symbol}>
                <td>{p.symbol}</td>
                <td>{p.qty.toFixed(3)}</td>
                <td>${p.avg_price.toFixed(2)}</td>
                <td>${p.price.toFixed(2)}</td>
                <td>{money(p.value)}</td>
                <td className={cls(p.pnl)}>{p.pnl >= 0 ? "+" : ""}{money(p.pnl)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export function DecisionsFeed({ state }: { state: StateData | null }) {
  const decisions = state?.decisions ?? [];
  return (
    <div className="card">
      <h2>Latest decisions</h2>
      {decisions.length === 0 ? (
        <div className="empty">No decisions yet.</div>
      ) : (
        <div className="feed">
          {decisions.map((d) => (
            <div className="row" key={d.symbol}>
              <span className="sym">{d.symbol}</span>
              <span className={`dir ${d.direction}`}>{d.direction}</span>
              <span className="why">
                {typeof d.expected_return === "number" ? `E[r] ${pct(d.expected_return)} · ` : ""}
                conv {d.score >= 0 ? "+" : ""}{d.score.toFixed(2)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function FormulaPanel({ state, backtest }: { state: StateData | null; backtest: BacktestData | null }) {
  const f = state?.formula ?? backtest?.formula;
  if (!f) return <div className="card"><h2>Decision formula</h2><div className="empty">No formula yet.</div></div>;
  return (
    <div className="card">
      <h2>Decision formula θ · φ &nbsp;(v{f.version}{f.fitted ? " · fitted" : ""})</h2>
      <WeightBars weights={f.weights} />
      <div className="legend" style={{ marginTop: 12 }}>
        <span className="muted">gain {f.gain}</span>
        <span className="muted">entry τ {f.entry_threshold}</span>
        {typeof f.size_scale === "number" && <span className="muted">scale {f.size_scale}</span>}
        {typeof f.stop_loss === "number" && <span className="muted">stop {(f.stop_loss * 100).toFixed(0)}%</span>}
        {typeof f.take_profit === "number" && <span className="muted">take {(f.take_profit * 100).toFixed(0)}%</span>}
      </div>
    </div>
  );
}

export function Briefing({ state }: { state: StateData | null }) {
  const text = state?.briefing?.trim();
  return (
    <div className="card">
      <h2>Global briefing</h2>
      {text ? <div className="briefing">{text}</div> : <div className="empty">Set ANTHROPIC_API_KEY and run with news enabled for the AI briefing.</div>}
    </div>
  );
}

function metricRow(label: string, m: Record<string, number> | undefined) {
  if (!m) return null;
  return (
    <tr>
      <td>{label}</td>
      <td>{m.sharpe}</td>
      <td className={cls(m.total_return ?? 0)}>{pct(m.total_return ?? 0)}</td>
      <td>{((m.max_drawdown ?? 0) * 100).toFixed(1)}%</td>
      <td>{m.n_trades}</td>
      <td>{money(m.final_equity ?? 0)}</td>
    </tr>
  );
}

export function BacktestPanel({ backtest }: { backtest: BacktestData | null }) {
  if (!backtest) {
    return (
      <div className="card">
        <h2>Backtest &amp; walk-forward</h2>
        <div className="empty">Run <code className="inline">python3 -m ai_investing.backtest.main --optimize --save</code>.</div>
      </div>
    );
  }
  return (
    <div className="card">
      <h2>
        Backtest &amp; walk-forward{" "}
        {backtest.adopted ? <span className="badge ok"><span className="dot" />ADOPTED</span> : <span className="badge">kept incumbent</span>}
      </h2>
      <table>
        <thead>
          <tr><th>Formula</th><th>Sharpe</th><th>Return</th><th>MaxDD</th><th>Trades</th><th>Final</th></tr>
        </thead>
        <tbody>
          {metricRow("default", backtest.metrics_default)}
          {metricRow("chosen", backtest.metrics_chosen)}
        </tbody>
      </table>
      {backtest.windows?.length > 0 && (
        <table style={{ marginTop: 14 }}>
          <thead>
            <tr><th>Window (OOS)</th><th>default Sharpe</th><th>challenger Sharpe</th></tr>
          </thead>
          <tbody>
            {backtest.windows.map((w) => (
              <tr key={w.window}>
                <td>bars {w.train_end}–{w.val_end}</td>
                <td>{w.default_sharpe}</td>
                <td className={cls(w.challenger_sharpe - w.default_sharpe)}>{w.challenger_sharpe}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="legend" style={{ marginTop: 10 }}>
        <span className="muted">provider: {backtest.provider}</span>
        <span className="muted">assets: {backtest.assets?.join(", ")}</span>
      </div>
    </div>
  );
}
