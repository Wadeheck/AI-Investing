"use client";

import { useEffect, useState } from "react";
import { EquityChart, type Series } from "@/components/charts";
import {
  BacktestPanel,
  Briefing,
  DecisionsFeed,
  FormulaPanel,
  PositionsTable,
  StatTiles,
} from "@/components/panels";
import type { DashboardData } from "@/lib/types";

export default function Page() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [updated, setUpdated] = useState<string>("");

  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const r = await fetch("/api/data", { cache: "no-store" });
        const j = (await r.json()) as DashboardData;
        if (active) {
          setData(j);
          setUpdated(new Date().toLocaleTimeString());
        }
      } catch {
        /* transient; keep last good data */
      }
    };
    load();
    const id = setInterval(load, 5000);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, []);

  const state = data?.state ?? null;
  const history = data?.history ?? null;
  const backtest = data?.backtest ?? null;

  const livePts = history?.points ?? [];
  let equitySeries: Series[] = [];
  let equityTitle = "Equity";
  if (livePts.length >= 2) {
    equitySeries = [{ label: "equity", color: "var(--series-1)", values: livePts.map((p) => p.equity) }];
    equityTitle = "Equity — live";
  } else if (backtest) {
    equitySeries = [
      { label: "default", color: "var(--series-1)", values: backtest.equity_curve_default },
      { label: "chosen", color: "var(--series-2)", values: backtest.equity_curve_chosen },
    ];
    equityTitle = "Equity — backtest (default vs chosen formula)";
  }

  const mode = state?.mode ?? "—";
  const halted = state?.halted;

  return (
    <div className="wrap">
      <header className="top">
        <h1>AI-Investing</h1>
        <span className="sub">autonomous · stocks + crypto · self-tuning formula</span>
        <span className="spacer" />
        {state && (
          <span className={`badge ${mode === "live" ? "live" : "paper"}`}>
            <span className="dot" />
            {mode.toUpperCase()}
          </span>
        )}
        {halted ? (
          <span className="badge halt"><span className="dot" />HALTED</span>
        ) : state ? (
          <span className="badge ok"><span className="dot" />running</span>
        ) : null}
        {updated && <span className="sub">updated {updated}</span>}
      </header>

      {!data && (
        <div className="empty">
          Loading… start the dashboard with <code className="inline">npm run dev</code> and run the engine.
        </div>
      )}

      <StatTiles state={state} history={history} />

      <div className="grid" style={{ marginTop: 16 }}>
        <div className="card">
          <h2>{equityTitle}</h2>
          <EquityChart series={equitySeries} />
        </div>
      </div>

      <div className="grid cols-2" style={{ marginTop: 16 }}>
        <FormulaPanel state={state} backtest={backtest} />
        <BacktestPanel backtest={backtest} />
      </div>

      <div className="grid cols-2" style={{ marginTop: 16 }}>
        <PositionsTable state={state} />
        <DecisionsFeed state={state} />
      </div>

      <div className="grid" style={{ marginTop: 16 }}>
        <Briefing state={state} />
      </div>
    </div>
  );
}
