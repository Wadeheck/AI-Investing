import type { ReactNode } from "react";
import { WeightBars } from "@/components/charts";
import type { BacktestData, DecisionRow, HistoryData, StateData } from "@/lib/types";

function money(v: number): string {
  return `${v < 0 ? "-" : ""}$${Math.round(Math.abs(v)).toLocaleString()}`;
}
function usd(v: number): string {
  return `${v < 0 ? "-" : ""}$${Math.abs(v).toFixed(2)}`;
}
function pct(v: number): string {
  return `${v >= 0 ? "+" : ""}${(v * 100).toFixed(2)}%`;
}
function cls(v: number): string {
  return v >= 0 ? "pos" : "neg";
}

function Info({ text }: { text: string }) {
  return <span className="info" title={text}>i</span>;
}
function Hint({ text, children }: { text: string; children: ReactNode }) {
  return <span className="hint" title={text}>{children}</span>;
}

// Plain-language names for the formula's features.
const FEATURE_LABELS: Record<string, string> = {
  bias: "Baseline",
  momentum: "Momentum",
  mean_reversion: "Mean-revert",
  sentiment: "News sentiment",
  political_hype: "Hype-fade",
  consensus: "Signal agreement",
  mom_lowvol: "Trend · calm",
};

function Tile({ label, value, valueCls, sub, subCls, hint }: {
  label: string; value: string; valueCls?: string; sub: string; subCls?: string; hint?: string;
}) {
  return (
    <div className="card kpi">
      <div className="label">{label}{hint && <Info text={hint} />}</div>
      <div className={`value ${valueCls ?? ""}`}>{value}</div>
      <div className={`delta ${subCls ?? "muted"}`}>{sub}</div>
    </div>
  );
}

export function StatTiles({ state, history }: { state: StateData | null; history: HistoryData | null }) {
  const pts = history?.points ?? [];
  const equity = state?.equity ?? (pts.length ? pts[pts.length - 1].equity : 0);
  const first = pts.length ? pts[0].equity : equity;
  const sessionChange = first ? equity / first - 1 : 0;
  const sessionPnl = equity - first;
  const edge = state?.comparison?.input_value ?? 0;
  const positions = state?.positions?.length ?? 0;
  const live = state?.mode === "live";

  return (
    <div className="grid cols-4">
      <Tile label="Portfolio value" value={money(equity)}
            sub={`${pct(sessionChange)} this session`} subCls={cls(sessionChange)} />
      <Tile label="Session P&L" value={`${sessionPnl >= 0 ? "+" : ""}${money(sessionPnl)}`}
            valueCls={cls(sessionPnl)} sub="since the loop started" />
      <Tile label="Your edge vs formula" value={`${edge >= 0 ? "+" : ""}${usd(edge)}`}
            valueCls={cls(edge)} sub={edge >= 0 ? "your input is helping" : "your input is hurting"}
            hint="Your portfolio minus a 'formula-only' portfolio that ignores your input." />
      <Tile label="Open positions" value={String(positions)}
            sub={live ? "LIVE — real money" : "paper (simulated)"} />
    </div>
  );
}

export function PositionsTable({ state }: { state: StateData | null }) {
  const positions = state?.positions ?? [];
  return (
    <div className="card">
      <h2>Holdings</h2>
      {positions.length === 0 ? (
        <div className="empty">Not holding anything right now.</div>
      ) : (
        <table>
          <thead>
            <tr><th>Symbol</th><th>Shares</th><th>Bought at</th><th>Now</th><th>Value</th><th>Profit</th></tr>
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

function action(d: DecisionRow): { label: string; cls: string } {
  // ~0.35 mirrors the engine's default min-confidence to trade; weaker = just a lean.
  const strong = Math.abs(d.score) >= 0.35;
  if (d.direction === "long") return strong ? { label: "Buy / long", cls: "buy" } : { label: "Lean bullish", cls: "hold" };
  if (d.direction === "short") return strong ? { label: "Sell / short", cls: "sell" } : { label: "Lean bearish", cls: "hold" };
  // "avoid" claims UNDERPERFORMANCE, not a fall — it is graded against the market,
  // so the label must not read like a short call.
  if (d.direction === "avoid") return strong ? { label: "Avoid / expect to lag", cls: "sell" } : { label: "Lean avoid", cls: "hold" };
  return { label: "Stay out", cls: "hold" };
}

export function DecisionsFeed({ state }: { state: StateData | null }) {
  const decisions = state?.decisions ?? [];
  return (
    <div className="card">
      <h2>What it wants to do now</h2>
      <div className="subtitle">The engine&apos;s current call per asset. Hover a row for the full reasoning.</div>
      {decisions.length === 0 ? (
        <div className="empty">No decisions yet — run a cycle.</div>
      ) : (
        <div className="feed">
          {decisions.map((d) => {
            const a = action(d);
            return (
              <div className="drow" key={d.symbol} title={d.rationale}>
                <div className="dtop">
                  <span className="sym">{d.symbol}</span>
                  <span className={`act ${a.cls}`}>{a.label}</span>
                  {typeof d.expected_return === "number" && (
                    <span className="muted" style={{ fontSize: 12 }}>expected {pct(d.expected_return)}</span>
                  )}
                </div>
                <div className="dsub">
                  conviction {d.score >= 0 ? "+" : ""}{d.score.toFixed(2)}
                  {d.user_view
                    ? ` · your view: ${d.user_view > 0 ? "bullish" : "bearish"} ${Math.round(Math.abs(d.user_view) * 100)}%`
                    : ""}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export function FormulaPanel({ state, backtest }: { state: StateData | null; backtest: BacktestData | null }) {
  const f = state?.formula ?? backtest?.formula;
  if (!f) return <div className="card"><h2>What the engine weighs</h2><div className="empty">No formula yet.</div></div>;
  const labeled = Object.fromEntries(Object.entries(f.weights).map(([k, v]) => [FEATURE_LABELS[k] ?? k, v]));
  return (
    <div className="card">
      <h2>What the engine weighs
        <Info text="The formula scores each asset as a weighted blend of signals + news + sentiment. These weights are learned from past profit &amp; loss." />
      </h2>
      <div className="subtitle">
        Longer bar = trusted more right now. {f.fitted ? "Curated + learning from results." : "Starting defaults."} (v{f.version})
      </div>
      <WeightBars weights={labeled} />
      <div className="legend" style={{ marginTop: 12 }}>
        <span className="muted"><Hint text="Minimum conviction before it will trade">min conviction {f.entry_threshold}</Hint></span>
        {typeof f.stop_loss === "number" && <span className="muted"><Hint text="Auto-sell if a position falls this much">stop {(f.stop_loss * 100).toFixed(0)}%</Hint></span>}
        {typeof f.take_profit === "number" && <span className="muted"><Hint text="Auto-sell to lock in this much gain">take {(f.take_profit * 100).toFixed(0)}%</Hint></span>}
      </div>
    </div>
  );
}

export function Briefing({ state }: { state: StateData | null }) {
  const text = state?.briefing?.trim();
  return (
    <div className="card">
      <h2>What&apos;s happening in the world</h2>
      {text ? <div className="briefing">{text}</div>
        : <div className="empty">Add an Anthropic API key and enable news for an AI market briefing.</div>}
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
        <h2>Backtest — is the formula any good?</h2>
        <div className="empty">Run <code className="inline">python3 -m ai_investing.backtest.main --optimize --save</code>.</div>
      </div>
    );
  }
  return (
    <div className="card">
      <h2>Backtest — is the formula any good?{" "}
        {backtest.adopted
          ? <span className="badge ok"><span className="dot" />adopted</span>
          : <span className="badge">kept the old one</span>}
      </h2>
      <div className="subtitle">Tested on history the model never trained on.</div>
      <table>
        <thead>
          <tr>
            <th>Formula</th>
            <th><Hint text="Return per unit of risk. Higher is better; above 1 is decent.">Sharpe</Hint></th>
            <th>Return</th>
            <th><Hint text="Worst peak-to-trough drop.">Max drop</Hint></th>
            <th>Trades</th><th>Final</th>
          </tr>
        </thead>
        <tbody>
          {metricRow("default", backtest.metrics_default)}
          {metricRow("chosen", backtest.metrics_chosen)}
        </tbody>
      </table>
      <div className="legend" style={{ marginTop: 10 }}>
        {typeof backtest.dsr === "number" && (
          <span className="muted">
            <Hint text="Confidence the edge is real after accounting for how many variants were tried. Only adopts if ≥ 0.60 — this is why it often keeps the old formula.">
              confidence {backtest.dsr}{typeof backtest.n_trials === "number" ? ` (of ${backtest.n_trials} tried)` : ""}
            </Hint>
          </span>
        )}
        <span className="muted">data: {backtest.provider}</span>
      </div>
    </div>
  );
}

export function ComparisonPanel({ state }: { state: StateData | null }) {
  const c = state?.comparison;
  if (!c) {
    return (
      <div className="card">
        <h2>You vs the formula</h2>
        <div className="empty">Run a cycle — this compares your decisions with a formula-only portfolio.</div>
      </div>
    );
  }
  const overrides = c.assets.filter((a) => Math.abs(a.your_qty - a.formula_qty) > 1e-6);
  const ahead = c.input_value >= 0;
  return (
    <div className="card">
      <h2>You vs the formula{" "}
        {overrides.length > 0 && <span className="badge">{overrides.length} override{overrides.length > 1 ? "s" : ""}</span>}
      </h2>
      <div className="subtitle">Same engine, minus your input — so you can see if your calls help or hurt.</div>
      <div className="grid cols-2" style={{ gap: 12 }}>
        <div className="kpi"><div className="label">You (with your input)</div><div className="value">{money(c.your_equity)}</div></div>
        <div className="kpi"><div className="label">Formula only</div><div className="value">{money(c.formula_equity)}</div></div>
      </div>
      <div className={`delta ${ahead ? "pos" : "neg"}`} style={{ marginTop: 10, fontSize: 15, fontWeight: 600 }}>
        Your input is {ahead ? "+" : ""}{usd(c.input_value)} {ahead ? "ahead of" : "behind"} the formula
      </div>
      {overrides.length > 0 && (
        <table style={{ marginTop: 12 }}>
          <thead>
            <tr><th>Symbol</th><th>Your shares</th><th>Your P&amp;L</th><th>Formula shares</th><th>Formula P&amp;L</th></tr>
          </thead>
          <tbody>
            {overrides.map((a) => (
              <tr key={a.symbol}>
                <td>{a.symbol}</td>
                <td>{a.your_qty.toFixed(3)}</td>
                <td className={cls(a.your_pnl)}>{usd(a.your_pnl)}</td>
                <td>{a.formula_qty.toFixed(3)}</td>
                <td className={cls(a.formula_pnl)}>{usd(a.formula_pnl)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
