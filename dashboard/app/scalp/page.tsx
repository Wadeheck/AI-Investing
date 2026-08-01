"use client";

import { useCallback, useEffect, useState } from "react";
import ScalpChart, { Candle, Level, Signal } from "./ScalpChart";

type SymState = {
  candles: Candle[]; ema9: (number | null)[]; vwap24: (number | null)[];
  cvd: number[]; levels: Level[]; last: number;
  value_area: { va_lo: number; va_hi: number; poc: number; in_value: boolean };
  signals_active: Signal[];
};
type State = {
  updated: string; mode: string; equity: number;
  verdicts: Record<string, boolean>;
  symbols: Record<string, SymState>;
  signal_log: ({ ts: string; sym: string } & Signal)[];
  positions: Record<string, unknown>[]; pending: Record<string, unknown>[];
  trades: { sym: string; tag: string; how: string; pnl: number; ts: string }[];
  curve: { ts: string; equity: number }[];
};
type Backtest = { families: Record<string, { ships: boolean; holdout?: { net_avg: number; trades: number } }> };

const fmtT = (s: string) => s.slice(11, 16);

export default function ScalpPage() {
  const [state, setState] = useState<State | null>(null);
  const [backtest, setBacktest] = useState<Backtest | null>(null);
  const [sym, setSym] = useState("BTCUSDT");

  const load = useCallback(async () => {
    try {
      const r = await fetch("/api/scalp", { cache: "no-store" });
      const j = await r.json();
      if (j.state) setState(j.state);
      if (j.backtest) setBacktest(j.backtest);
    } catch { /* offline is fine */ }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 10_000);
    return () => clearInterval(t);
  }, [load]);

  if (!state)
    return (
      <main style={{ padding: 24, fontFamily: "monospace" }}>
        <h1>⚡ Scalp</h1>
        <p>No scalp state yet. Start the loop:</p>
        <pre>cd engine && ../.venv/bin/python -m ai_investing.scalp.live</pre>
      </main>
    );

  const s = state.symbols[sym];
  const stale = Date.now() - Date.parse(state.updated) > 5 * 60_000;
  return (
    <main style={{ padding: 16, fontFamily: "monospace", maxWidth: 1400, margin: "0 auto" }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 16, flexWrap: "wrap" }}>
        <h1 style={{ margin: 0 }}>⚡ Scalp</h1>
        <span>paper ${state.equity?.toLocaleString()}</span>
        <span style={{ opacity: 0.7 }}>{fmtT(state.updated)} UTC{stale ? " ⚠ STALE" : ""}</span>
        <span style={{ marginLeft: "auto" }}>
          {Object.keys(state.symbols).map(k => (
            <button key={k} onClick={() => setSym(k)}
              style={{ marginLeft: 6, padding: "4px 10px", background: k === sym ? "#334" : "#181c24",
                       color: "#dde", border: "1px solid #445", borderRadius: 6, cursor: "pointer" }}>
              {k.replace("USDT", "")} {state.symbols[k]?.last}
            </button>
          ))}
        </span>
      </div>

      <p style={{ background: "#2a2320", border: "1px solid #665", borderRadius: 6, padding: 8, fontSize: 12 }}>
        {state.mode}
        {backtest && (
          <>
            {" — 60d holdout: "}
            {Object.entries(backtest.families).map(([f, v]) => (
              <span key={f} style={{ marginRight: 10, color: v.ships ? "#2ecc71" : "#e74c3c" }}>
                {f} {v.ships ? "✓" : "✗"}{v.holdout ? ` (${(v.holdout.net_avg * 100).toFixed(1)}%)` : ""}
              </span>
            ))}
          </>
        )}
      </p>

      {s && (
        <>
          <ScalpChart candles={s.candles} ema9={s.ema9} vwap24={s.vwap24}
            levels={s.levels} valueArea={s.value_area} signals={s.signals_active} />
          <div style={{ fontSize: 12, opacity: 0.85, marginTop: 4 }}>
            <span style={{ color: "#f39c12" }}>— EMA9</span>{"  "}
            <span style={{ color: "#9b59b6" }}>— VWAP24h</span>{"  "}
            <span style={{ color: "#5a78c8" }}>▒ value area / POC</span>{"  "}
            <span style={{ color: "#2ecc71" }}>-- support</span>{"  "}
            <span style={{ color: "#e74c3c" }}>-- resistance</span>{"  "}
            {s.value_area && <b>{s.value_area.in_value ? "IN VALUE (balance)" : "OUT OF VALUE (imbalance)"}</b>}
            {"  ·  CVD Δ150bars: "}<b>{s.cvd?.length ? s.cvd[s.cvd.length - 1].toFixed(0) : "-"}</b>
          </div>
        </>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12, marginTop: 16 }}>
        <section>
          <h3>Active signals</h3>
          {(s?.signals_active?.length || 0) === 0 && <p style={{ opacity: 0.6 }}>none this bar</p>}
          {s?.signals_active?.map((x, i) => (
            <div key={i} style={{ fontSize: 12 }}>
              {x.side > 0 ? "🟢 LONG" : "🔴 SHORT"} <b>{x.tag}</b> @{x.entry} stop {x.stop} tgt {x.target}
            </div>
          ))}
          <h3 style={{ marginTop: 12 }}>Recent signals</h3>
          {state.signal_log?.slice(-8).reverse().map((x, i) => (
            <div key={i} style={{ fontSize: 11, opacity: 0.8 }}>
              {fmtT(x.ts)} {x.sym.replace("USDT", "")} {x.tag} {x.side > 0 ? "L" : "S"} @{x.entry}
            </div>
          ))}
        </section>
        <section>
          <h3>Positions / pending</h3>
          {(state.positions?.length || 0) + (state.pending?.length || 0) === 0 &&
            <p style={{ opacity: 0.6 }}>flat</p>}
          {state.positions?.map((p: Record<string, unknown>, i: number) => (
            <div key={i} style={{ fontSize: 12 }}>
              📌 {String(p.sym).replace("USDT", "")} {Number(p.side) > 0 ? "L" : "S"} {String(p.tag)} @{String(p.entry)}
            </div>
          ))}
          {state.pending?.map((p: Record<string, unknown>, i: number) => (
            <div key={i} style={{ fontSize: 12, opacity: 0.7 }}>
              ⏳ limit {String(p.sym).replace("USDT", "")} {String(p.tag)} @{String(p.entry)} (ttl {String(p.ttl)})
            </div>
          ))}
        </section>
        <section>
          <h3>Closed trades (paper)</h3>
          {(state.trades?.length || 0) === 0 && <p style={{ opacity: 0.6 }}>none yet — forward test just started</p>}
          {state.trades?.slice(-10).reverse().map((t, i) => (
            <div key={i} style={{ fontSize: 12, color: t.pnl >= 0 ? "#2ecc71" : "#e74c3c" }}>
              {fmtT(t.ts)} {t.sym.replace("USDT", "")} {t.tag} {t.how} {t.pnl >= 0 ? "+" : ""}{t.pnl.toFixed(2)}
            </div>
          ))}
        </section>
      </div>
    </main>
  );
}
