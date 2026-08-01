"use client";

import { useEffect, useState } from "react";
import { EquityChart, type Series } from "@/components/charts";
import { Controls } from "@/components/controls";
import {
  BacktestPanel,
  Briefing,
  ComparisonPanel,
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
  let equityTitle = "Portfolio value over time";
  if (livePts.length >= 2) {
    equitySeries = [{ label: "you", color: "var(--series-1)", values: livePts.map((p) => p.equity) }];
    if (livePts.some((p) => typeof p.shadow_equity === "number")) {
      equitySeries.push({
        label: "formula only",
        color: "var(--series-2)",
        values: livePts.map((p) => p.shadow_equity ?? p.equity),
      });
    }
    equityTitle = "Portfolio value — you vs formula-only";
  } else if (backtest) {
    equitySeries = [
      { label: "old formula", color: "var(--series-1)", values: backtest.equity_curve_default },
      { label: "new formula", color: "var(--series-2)", values: backtest.equity_curve_chosen },
    ];
    equityTitle = "Backtest — old vs new formula";
  }

  const mode = state?.mode ?? "—";
  const halted = state?.halted;
  const symbols = Array.from(new Set([
    ...(state?.decisions?.map((d) => d.symbol) ?? []),
    ...(state?.positions?.map((p) => p.symbol) ?? []),
  ]));

  return (
    <div className="wrap">
      <header className="top">
        <h1>AI-Investing</h1>
        <a href="/brain" className="navlink">🧠 the brain</a>
        <a href="/scalp" className="navlink">⚡ scalp</a>
        <span className="spacer" />
        {state && (
          <span className={`badge ${mode === "live" ? "live" : "paper"}`}>
            <span className="dot" />{mode === "live" ? "LIVE" : "PAPER"}
          </span>
        )}
        {halted ? (
          <span className="badge halt"><span className="dot" />halted</span>
        ) : state ? (
          <span className="badge ok"><span className="dot" />running</span>
        ) : null}
        {updated && <span className="sub">updated {updated}</span>}
      </header>
      <div className="tagline">
        An autonomous stocks &amp; crypto trader you steer — the formula weighs the signals, your input decides.
      </div>

      <div className="howto">
        <div className="step"><b><span className="n">1.</span> The formula scores each asset</b> from price signals, news &amp; sentiment — weights learned from past results.</div>
        <div className="step"><b><span className="n">2.</span> You steer it</b> — a view per asset, your risk stance &amp; appetite. Your input is the decisive factor.</div>
        <div className="step"><b><span className="n">3.</span> Safety caps losses</b> — circuit breaker, position limits &amp; a kill switch you can&apos;t override.</div>
      </div>

      {!data && (
        <div className="empty">
          Loading… run the engine with <code className="inline">python3 -m ai_investing.main --once</code> to populate this.
        </div>
      )}

      <div className="section">Overview</div>
      <StatTiles state={state} history={history} />

      <div className="section">Steer it — your input</div>
      <Controls symbols={symbols} />

      <div className="section">Performance</div>
      <div className="grid">
        <div className="card">
          <h2>{equityTitle}</h2>
          <EquityChart series={equitySeries} />
        </div>
      </div>
      <div className="grid" style={{ marginTop: 16 }}>
        <ComparisonPanel state={state} />
      </div>

      <div className="section">What it&apos;s doing now</div>
      <div className="grid cols-2">
        <PositionsTable state={state} />
        <DecisionsFeed state={state} />
      </div>

      <details className="adv" open>
        <summary>Under the hood — the formula &amp; its backtest</summary>
        <div className="grid cols-2">
          <FormulaPanel state={state} backtest={backtest} />
          <BacktestPanel backtest={backtest} />
        </div>
      </details>

      <div className="section">World briefing</div>
      <Briefing state={state} />

      <footer className="foot">
        <span>{mode === "live" ? "⚠️ LIVE — real money" : "Paper simulation — no real money"}</span>
        <span>Not financial advice</span>
        <span>Refreshes every 5s</span>
      </footer>
    </div>
  );
}
