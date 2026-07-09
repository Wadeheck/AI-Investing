"use client";

import { useEffect, useState } from "react";

const STANCES = ["aggressive", "normal", "cautious", "defensive", "cash"];

interface Views {
  decisiveness: number;
  risk_appetite: number;
  stance: string;
  views: Record<string, number>;
  blocklist: string[];
  focus: string[];
}

const DEFAULT: Views = { decisiveness: 0.7, risk_appetite: 0.5, stance: "normal", views: {}, blocklist: [], focus: [] };

export function Controls({ symbols }: { symbols: string[] }) {
  const [v, setV] = useState<Views>(DEFAULT);
  const [saved, setSaved] = useState("");

  useEffect(() => {
    fetch("/api/views")
      .then((r) => r.json())
      .then((d) => setV({ ...DEFAULT, ...d }))
      .catch(() => {});
  }, []);

  const save = async (next: Views) => {
    setV(next);
    try {
      await fetch("/api/views", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(next),
      });
      setSaved(new Date().toLocaleTimeString());
    } catch {
      /* keep local state */
    }
  };

  const setView = (sym: string, val: number) => {
    const views = { ...v.views };
    if (val === 0) delete views[sym];
    else views[sym] = val;
    save({ ...v, views });
  };

  const toggleBlock = (sym: string) => {
    const blocklist = v.blocklist.includes(sym) ? v.blocklist.filter((x) => x !== sym) : [...v.blocklist, sym];
    save({ ...v, blocklist });
  };

  return (
    <div className="card">
      <h2>Your input — the decisive factor</h2>

      <div className="ctrl-row">
        <span className="muted" style={{ width: 96 }}>Risk stance</span>
        <div className="chips">
          {STANCES.map((s) => (
            <button key={s} className={`chip ${v.stance === s ? "on" : ""}`} onClick={() => save({ ...v, stance: s })}>
              {s}
            </button>
          ))}
        </div>
      </div>

      <div className="ctrl-row">
        <span className="muted" style={{ width: 96 }}>Decisiveness</span>
        <input
          type="range" min={0} max={100} value={Math.round(v.decisiveness * 100)}
          onChange={(e) => save({ ...v, decisiveness: Number(e.target.value) / 100 })}
          style={{ flex: 1 }}
        />
        <span className="wval">{Math.round(v.decisiveness * 100)}%</span>
      </div>

      <div className="ctrl-row">
        <span className="muted" style={{ width: 96 }}>Risk appetite</span>
        <input
          type="range" min={0} max={100} value={Math.round((v.risk_appetite ?? 0.5) * 100)}
          onChange={(e) => save({ ...v, risk_appetite: Number(e.target.value) / 100 })}
          style={{ flex: 1 }}
        />
        <span className="wval">{Math.round((v.risk_appetite ?? 0.5) * 100)}%</span>
      </div>

      <div className="muted" style={{ fontSize: 12, margin: "10px 0 6px" }}>
        Your view per asset — bearish ← → bullish (0 = let the model decide)
      </div>
      <div className="views-list">
        {symbols.length === 0 && <div className="empty">Run the engine to populate the watchlist.</div>}
        {symbols.map((sym) => {
          const val = v.views[sym] ?? 0;
          const blocked = v.blocklist.includes(sym);
          return (
            <div className="vrow" key={sym}>
              <span className="sym">{sym}</span>
              <input
                type="range" min={-100} max={100} value={Math.round(val * 100)} disabled={blocked}
                onChange={(e) => setView(sym, Number(e.target.value) / 100)} style={{ flex: 1 }}
              />
              <span className={`wval ${val > 0 ? "pos" : val < 0 ? "neg" : "muted"}`}>
                {val > 0 ? "bull" : val < 0 ? "bear" : "—"} {val ? Math.round(Math.abs(val) * 100) : ""}
              </span>
              <button className={`chip ${blocked ? "on-block" : ""}`} onClick={() => toggleBlock(sym)}>
                {blocked ? "blocked" : "block"}
              </button>
            </div>
          );
        })}
      </div>

      {saved && <div className="muted" style={{ marginTop: 10, fontSize: 12 }}>saved {saved} — applies next cycle</div>}
    </div>
  );
}
