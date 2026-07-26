"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

/* ---------- types mirroring the engine's JSON ---------- */
type GNode = {
  id: string; type: string; label: string; symbol?: string; market?: string;
  equilibrium?: string; state?: string; aliases?: string[];
};
type GEdge = {
  src: string; dst: string; type: string; sign?: number; weight?: number;
  provenance?: string; note?: string;
};
type Graph = { nodes: GNode[]; edges: GEdge[] };
type TraceStep = { from: string; to: string; edge_type: string; hop: number; contribution: number };
type BrainEvent = {
  summary: string; source?: string; type?: string; nodes?: string[]; polarity?: number;
  magnitude?: number; credibility?: number; is_noise?: boolean; emotion?: string;
  emotion_intensity?: number; impulse?: number; fallback?: boolean;
};
type Scenario = { id: string; implication: string; fired_by?: string; strength?: number };
type Regime = {
  risk_appetite: number; rate_trajectory: number; dollar_trend: number; inflation_trend: number;
  china_stance: number; geopolitical_tension: number; stability: number; fragility?: number;
  fear: number; greed: number; emotion_label: string;
  mood_confidence: number; mood_caution: number; mood_label: string; updated?: string;
  labels?: Record<string, string>;
};
type Pending = { node: string; contribution: number; due?: string; via?: string; delay_days?: number };
type Trade = {
  rank: number; symbol: string; market?: string; label?: string; direction: string;
  score: number; weight_suggestion: number; chain: string; invalidation: string;
  drivers?: Record<string, number>;
};
type Advice = {
  ts?: string; trades?: Trade[]; considered?: number; mood?: string;
  conviction_multiplier?: number; regime_note?: string;
};
type BrainState = {
  ts?: string; simulated?: boolean; events?: BrainEvent[]; impulses?: Record<string, number>;
  impacts?: Record<string, number>; trace?: TraceStep[];
  asset_impacts?: Record<string, { impact: number; label?: string; market?: string; scenarios?: string[] }>;
  scenarios_fired?: Scenario[]; regime?: Regime; conviction_multiplier?: number;
  signal_events?: number; noise_events?: number;
  activations?: Record<string, number>;      // persistent field (live view)
  pending_effects?: Pending[];               // τ-queue: effects landing later
  delayed_preview?: Pending[];               // simulation: what WOULD land later
  centrality?: Record<string, number>;       // systemic importance, max=1
};

/* ---------- node visual encoding ---------- */
const TYPE_COLOR: Record<string, string> = {
  factor: "#8a63d2", commodity: "#b8860b", actor: "#d05c8c",
  theme: "#2a78d6", sector: "#2a78d6", asset: "#1baf7a",
};
const TYPE_R: Record<string, number> = {
  factor: 11, commodity: 10, actor: 10, theme: 9, sector: 9, asset: 7,
};

/* ---------- tiny force layout (no deps) ---------- */
type P = { x: number; y: number; vx: number; vy: number };

function useForceLayout(graph: Graph | null, w: number, h: number) {
  const [pos, setPos] = useState<Record<string, P>>({});
  const posRef = useRef<Record<string, P>>({});
  useEffect(() => {
    if (!graph) return;
    const p: Record<string, P> = {};
    const n = graph.nodes.length;
    graph.nodes.forEach((nd, i) => {
      const angle = (2 * Math.PI * i) / Math.max(1, n);
      // start factors near center, assets on the rim — matches the field metaphor
      const rBase = nd.type === "asset" ? 0.42 : nd.type === "theme" || nd.type === "sector" ? 0.28 : 0.15;
      p[nd.id] = {
        x: w / 2 + rBase * w * Math.cos(angle) + (i % 7) * 3,
        y: h / 2 + rBase * h * Math.sin(angle) + (i % 5) * 3,
        vx: 0, vy: 0,
      };
    });
    posRef.current = p;
    const edges = graph.edges.filter((e) => p[e.src] && p[e.dst]);
    let tick = 0;
    const id = setInterval(() => {
      const cur = posRef.current;
      const ids = Object.keys(cur);
      // repulsion
      for (let i = 0; i < ids.length; i++) {
        for (let j = i + 1; j < ids.length; j++) {
          const a = cur[ids[i]], b = cur[ids[j]];
          let dx = a.x - b.x, dy = a.y - b.y;
          let d2 = dx * dx + dy * dy;
          if (d2 < 1) { dx = Math.random() - 0.5; dy = Math.random() - 0.5; d2 = 1; }
          const f = 7000 / d2;
          const d = Math.sqrt(d2);
          a.vx += (dx / d) * f; a.vy += (dy / d) * f;
          b.vx -= (dx / d) * f; b.vy -= (dy / d) * f;
        }
      }
      // springs
      for (const e of edges) {
        const a = cur[e.src], b = cur[e.dst];
        const dx = b.x - a.x, dy = b.y - a.y;
        const d = Math.max(1, Math.sqrt(dx * dx + dy * dy));
        const f = 0.008 * (d - 170) * (e.weight ?? 0.5);
        a.vx += (dx / d) * f * d * 0.02; a.vy += (dy / d) * f * d * 0.02;
        b.vx -= (dx / d) * f * d * 0.02; b.vy -= (dy / d) * f * d * 0.02;
      }
      // centering + integrate
      for (const k of ids) {
        const q = cur[k];
        q.vx += (w / 2 - q.x) * 0.004; q.vy += (h / 2 - q.y) * 0.004;
        q.vx *= 0.82; q.vy *= 0.82;
        q.x = Math.max(40, Math.min(w - 40, q.x + q.vx));
        q.y = Math.max(30, Math.min(h - 30, q.y + q.vy));
      }
      tick++;
      setPos({ ...cur });
      if (tick > 140) clearInterval(id);
    }, 30);
    return () => clearInterval(id);
  }, [graph, w, h]);
  return pos;
}

/* ---------- small UI bits ---------- */
function Dial({ label, value, left, right }: { label: string; value: number; left: string; right: string }) {
  const pct = Math.round(((value + 1) / 2) * 100);
  return (
    <div className="dial">
      <div className="dial-head"><span>{label}</span><b>{value >= 0 ? "+" : ""}{value.toFixed(2)}</b></div>
      <div className="dial-track"><div className="dial-mark" style={{ left: `${pct}%` }} /></div>
      <div className="dial-ends"><span>{left}</span><span>{right}</span></div>
    </div>
  );
}

function Meter({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className="dial">
      <div className="dial-head"><span>{label}</span><b>{(value * 100).toFixed(0)}%</b></div>
      <div className="dial-track"><div className="dial-fill" style={{ width: `${value * 100}%`, background: color }} /></div>
    </div>
  );
}

/* ---------- the page ---------- */
export default function BrainPage() {
  const [graph, setGraph] = useState<Graph | null>(null);
  const [live, setLive] = useState<BrainState | null>(null);
  const [regime, setRegime] = useState<Regime | null>(null);
  const [advice, setAdvice] = useState<Advice | null>(null);
  const [sim, setSim] = useState<BrainState | null>(null);
  const [headline, setHeadline] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [visibleHop, setVisibleHop] = useState(99);
  // zoom & pan: k = scale, (tx, ty) = translation in view units
  const [view, setView] = useState({ k: 1, tx: 0, ty: 0 });
  const dragRef = useRef<{ x: number; y: number; tx: number; ty: number } | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);

  const W = 1700, H = 1050;
  const pos = useForceLayout(graph, W, H);

  const onWheel = (e: React.WheelEvent) => {
    const factor = Math.exp(-e.deltaY * 0.0012);
    setView((v) => {
      const k = Math.min(5, Math.max(0.5, v.k * factor));
      if (!svgRef.current) return { ...v, k };
      // zoom toward the cursor
      const rect = svgRef.current.getBoundingClientRect();
      const mx = ((e.clientX - rect.left) / rect.width) * W;
      const my = ((e.clientY - rect.top) / rect.height) * H;
      const wx = (mx - v.tx) / v.k, wy = (my - v.ty) / v.k;
      return { k, tx: mx - wx * k, ty: my - wy * k };
    });
  };
  const onMouseDown = (e: React.MouseEvent) => {
    dragRef.current = { x: e.clientX, y: e.clientY, tx: view.tx, ty: view.ty };
  };
  const onMouseMove = (e: React.MouseEvent) => {
    const d = dragRef.current;
    if (!d || !svgRef.current) return;
    const rect = svgRef.current.getBoundingClientRect();
    const sx = W / rect.width, sy = H / rect.height;
    setView((v) => ({ ...v, tx: d.tx + (e.clientX - d.x) * sx, ty: d.ty + (e.clientY - d.y) * sy }));
  };
  const endDrag = () => { dragRef.current = null; };

  const load = useCallback(async () => {
    try {
      const r = await fetch("/api/brain", { cache: "no-store" });
      const j = await r.json();
      if (j.graph) setGraph(j.graph as Graph);
      if (j.brain) setLive(j.brain as BrainState);
      if (j.regime) setRegime(j.regime as Regime);
      if (j.advice) setAdvice(j.advice as Advice);
    } catch { /* keep last good */ }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 15000);
    return () => clearInterval(id);
  }, [load]);

  const active: BrainState | null = sim ?? live;
  // live view shows the persistent FIELD (activations decay over hours/days);
  // a simulation shows the instantaneous ripple of the injected headline
  const impacts = sim ? sim.impacts ?? {} : live?.activations ?? live?.impacts ?? {};
  const centrality = active?.centrality ?? {};
  const trace = useMemo(
    () => (active?.trace ?? []).filter((t) => t.hop <= visibleHop),
    [active, visibleHop]
  );

  // ripple animation: reveal hop by hop after a simulation lands
  useEffect(() => {
    if (!sim) { setVisibleHop(99); return; }
    setVisibleHop(0);
    const maxHop = Math.max(0, ...(sim.trace ?? []).map((t) => t.hop));
    let hop = 0;
    const id = setInterval(() => {
      hop++;
      setVisibleHop(hop);
      if (hop > maxHop) clearInterval(id);
    }, 650);
    return () => clearInterval(id);
  }, [sim]);

  const visibleImpacts = useMemo(() => {
    if (!sim || visibleHop >= 99) return impacts;
    const shown: Record<string, number> = {};
    for (const [k, v] of Object.entries(sim.impulses ?? {})) shown[k] = v;
    for (const t of trace) shown[t.to] = impacts[t.to] ?? 0;
    return shown;
  }, [sim, impacts, trace, visibleHop]);

  const simulate = async () => {
    if (!headline.trim() || busy) return;
    setBusy(true); setError("");
    try {
      const r = await fetch("/api/brain/simulate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ headline }),
      });
      const j = await r.json();
      if (j.error) setError(String(j.error));
      else setSim(j as BrainState);
    } catch (e) {
      setError("simulation request failed");
    } finally {
      setBusy(false);
    }
  };

  const reg = (sim?.regime ?? live?.regime ?? regime) as Regime | null;
  const events = active?.events ?? [];
  const fired = active?.scenarios_fired ?? [];
  const assetRows = Object.entries(active?.asset_impacts ?? {}).sort(
    (a, b) => Math.abs(b[1].impact) - Math.abs(a[1].impact)
  );
  const pendingRows: Pending[] = sim ? sim.delayed_preview ?? [] : live?.pending_effects ?? [];
  const selNode = selected && graph ? graph.nodes.find((n) => n.id === selected) : null;
  const selEdges = selNode && graph
    ? graph.edges.filter((e) => e.src === selNode.id || e.dst === selNode.id)
    : [];

  return (
    <div className="wrap wrap-wide">
      <header className="top">
        <h1>The Brain</h1>
        <span className="sub">macro field · relationships · signal vs noise · emotions</span>
        <div className="spacer" />
        <a href="/" className="navlink">← control room</a>
      </header>

      {/* headline injector */}
      <div className="card inject">
        <input
          value={headline}
          onChange={(e) => setHeadline(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && simulate()}
          placeholder='Inject a headline and watch it ripple — e.g. "PBOC cuts rates by 25bps" or "US bans next-gen AI chip exports to China"'
        />
        <button onClick={simulate} disabled={busy}>{busy ? "thinking…" : "ripple it"}</button>
        {sim && <button className="ghost" onClick={() => { setSim(null); setError(""); }}>back to live</button>}
        {error && <span className="err">{error}</span>}
        {sim && !error && (
          <span className="simtag">
            simulation — {sim.events?.[0]?.is_noise ? "judged NOISE (won't move positions)" : "judged signal"}
            {typeof sim.events?.[0]?.credibility === "number" && ` · credibility ${(sim.events![0].credibility! * 100).toFixed(0)}%`}
          </span>
        )}
      </div>

      <div className="brain-grid">
        {/* ---------- the field ---------- */}
        <div className="card">
          <svg
            ref={svgRef}
            viewBox={`0 0 ${W} ${H}`}
            className="field"
            onWheel={onWheel}
            onMouseDown={onMouseDown}
            onMouseMove={onMouseMove}
            onMouseUp={endDrag}
            onMouseLeave={endDrag}
            style={{ cursor: dragRef.current ? "grabbing" : "grab" }}
          >
            <g transform={`translate(${view.tx},${view.ty}) scale(${view.k})`}>
            {graph?.edges.map((e, i) => {
              const a = pos[e.src], b = pos[e.dst];
              if (!a || !b) return null;
              const hot = trace.find(
                (t) => (t.from === e.src && t.to === e.dst) || (t.from === e.dst && t.to === e.src)
              );
              const w = e.weight ?? 0.5;
              return (
                <line
                  key={i}
                  x1={a.x} y1={a.y} x2={b.x} y2={b.y}
                  stroke={hot ? (hot.contribution >= 0 ? "var(--pos)" : "var(--neg)") : "var(--axis)"}
                  strokeWidth={hot ? 2.4 : 0.3 + w * 1.4}
                  strokeOpacity={hot ? 0.95 : 0.2 + w * 0.3}
                  strokeDasharray={e.provenance === "llm" ? "4 3" : undefined}
                />
              );
            })}
            {graph?.nodes.map((n) => {
              const p = pos[n.id];
              if (!p) return null;
              const imp = visibleImpacts[n.id] ?? 0;
              const mag = Math.min(1, Math.abs(imp));
              // influence = size: systemically central nodes render visually heavier
              const baseR = (TYPE_R[n.type] ?? 8) + (centrality[n.id] ?? 0) * 10;
              const r = baseR + mag * 14;
              const impColor = imp > 0 ? "var(--pos)" : "var(--neg)";
              return (
                <g key={n.id} onClick={() => setSelected(n.id === selected ? null : n.id)} style={{ cursor: "pointer" }}>
                  {mag > 0.02 && (
                    <circle cx={p.x} cy={p.y} r={r + 5} fill={impColor} opacity={0.18 + mag * 0.3} />
                  )}
                  <circle
                    cx={p.x} cy={p.y} r={baseR}
                    fill={TYPE_COLOR[n.type] ?? "#888"}
                    stroke={selected === n.id ? "var(--ink)" : mag > 0.02 ? impColor : "var(--surface)"}
                    strokeWidth={selected === n.id ? 2.5 : mag > 0.02 ? 2 : 1}
                    opacity={0.92}
                  />
                  {(n.type !== "asset" || mag > 0.02 || selected === n.id || view.k > 1.6) && (
                    <text x={p.x} y={p.y - baseR - 5} textAnchor="middle" className="nlabel">
                      {n.label}{mag > 0.02 ? ` ${imp > 0 ? "+" : ""}${imp.toFixed(2)}` : ""}
                    </text>
                  )}
                </g>
              );
            })}
            </g>
          </svg>
          <div className="legend">
            {Object.entries(TYPE_COLOR).filter(([t]) => t !== "sector").map(([t, c]) => (
              <span key={t}><i style={{ background: c }} />{t}</span>
            ))}
            <span><i className="dash" />LLM-proposed edge</span>
            <span className="sub">scroll to zoom · drag to pan · click a node for its wiring &amp; stable point</span>
            {view.k !== 1 && (
              <button className="resetview" onClick={() => setView({ k: 1, tx: 0, ty: 0 })}>
                reset view
              </button>
            )}
          </div>
          {selNode && (
            <div className="nodecard">
              <b>{selNode.label}</b> <span className="sub">({selNode.type}{selNode.symbol ? ` · ${selNode.symbol} · ${selNode.market}` : ""})</span>
              <div className="sub">
                charge now: <b style={{ color: (impacts[selNode.id] ?? 0) >= 0 ? "var(--pos)" : "var(--neg)" }}>
                  {(impacts[selNode.id] ?? 0) >= 0 ? "+" : ""}{(impacts[selNode.id] ?? 0).toFixed(3)}
                </b>
                {" "}· systemic influence: {((centrality[selNode.id] ?? 0) * 100).toFixed(0)}/100
                {active?.ts ? ` · field updated ${active.ts.slice(0, 16)}Z` : ""}
              </div>
              {selNode.equilibrium && <div className="sub">stable point: {selNode.equilibrium}</div>}
              <div className="edgelist">
                {selEdges.map((e, i) => (
                  <div key={i} className="sub">
                    {e.src === selNode.id ? "→" : "←"} {e.src === selNode.id ? e.dst : e.src}
                    {" "}({e.type}{(e.sign ?? 1) < 0 ? ", inverse" : ""}, w{(e.weight ?? 0.5).toFixed(1)}
                    {e.provenance === "llm" ? ", llm-proposed" : ""}){e.note ? ` — ${e.note}` : ""}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* ---------- right rail ---------- */}
        <div className="rail">
          {reg && (
            <div className="card">
              <h3>Regime — what world are we in</h3>
              <Dial label="risk appetite" value={reg.risk_appetite} left="risk-off" right="risk-on" />
              <Dial label="rates" value={reg.rate_trajectory} left="easing" right="tightening" />
              <Dial label="US dollar" value={reg.dollar_trend} left="weakening" right="strengthening" />
              <Dial label="inflation" value={reg.inflation_trend} left="cooling" right="heating" />
              <Dial label="China stance" value={reg.china_stance} left="crackdown" right="stimulus" />
              <Meter label="geopolitical tension" value={reg.geopolitical_tension} color="var(--warn)" />
              <Meter label="field stability" value={reg.stability} color="var(--series-1)" />
              <Meter label="portfolio fragility" value={reg.fragility ?? 0} color="var(--neg)" />
            </div>
          )}
          {reg && (
            <div className="card">
              <h3>Emotions</h3>
              <div className="sub">crowd: <b>{reg.emotion_label}</b></div>
              <Meter label="fear" value={reg.fear} color="var(--neg)" />
              <Meter label="greed" value={reg.greed} color="var(--pos)" />
              <div className="sub" style={{ marginTop: 8 }}>
                brain&apos;s own mood: <b>{reg.mood_label}</b>
              </div>
              <Meter label="confidence" value={reg.mood_confidence} color="var(--series-1)" />
              <Meter label="caution" value={reg.mood_caution} color="var(--warn)" />
              <div className="sub">conviction multiplier ×{(active?.conviction_multiplier ?? 1).toFixed(2)}</div>
            </div>
          )}
          {fired.length > 0 && (
            <div className="card">
              <h3>Scenarios fired</h3>
              {fired.map((s, i) => (
                <div key={i} className="scen">
                  <b>{s.id}</b>
                  <div className="sub">{s.implication}</div>
                  {s.fired_by && <div className="sub">trigger: {s.fired_by}</div>}
                </div>
              ))}
            </div>
          )}
          {pendingRows.length > 0 && (
            <div className="card">
              <h3>{sim ? "Would land later (τ-edges)" : "Delayed effects in the pipe"}</h3>
              {pendingRows.slice(0, 8).map((p, i) => (
                <div key={i} className="arow">
                  <span>{p.via ? `${p.via} → ` : ""}{p.node}</span>
                  <span className="sub">
                    <b style={{ color: p.contribution >= 0 ? "var(--pos)" : "var(--neg)" }}>
                      {p.contribution >= 0 ? "+" : ""}{p.contribution.toFixed(2)}
                    </b>
                    {" "}{p.due ? `due ${p.due.slice(0, 10)}` : `in ~${p.delay_days ?? "?"}d`}
                  </span>
                </div>
              ))}
            </div>
          )}
          {assetRows.length > 0 && (
            <div className="card">
              <h3>Asset impacts</h3>
              {assetRows.slice(0, 12).map(([sym, a]) => (
                <div key={sym} className="arow">
                  <span>{sym}{a.market ? ` · ${a.market}` : ""}</span>
                  <b style={{ color: a.impact >= 0 ? "var(--pos)" : "var(--neg)" }}>
                    {a.impact >= 0 ? "+" : ""}{a.impact.toFixed(2)}
                  </b>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* ---------- the adviser: top trades from the field ---------- */}
      {advice?.trades && advice.trades.length > 0 && (
        <div className="card" style={{ marginBottom: 16 }}>
          <h3>
            Top trades — from the field, not a black box
            <span className="sub">
              {" "}· mood {advice.mood} · conviction ×{(advice.conviction_multiplier ?? 1).toFixed(2)}
              {advice.regime_note ? ` · ${advice.regime_note}` : ""}
            </span>
          </h3>
          <div className="trades">
            {advice.trades.map((t) => (
              <div key={t.symbol} className="trade">
                <span className="trank">#{t.rank}</span>
                <span className={`tdir ${t.direction === "long" ? "tlong" : "tshort"}`}>
                  {t.direction === "long" ? "LONG" : "SHORT/AVOID"}
                </span>
                <b>{t.symbol}</b>
                <span className="sub">{t.market}</span>
                <span className="tscore" style={{ color: t.score >= 0 ? "var(--pos)" : "var(--neg)" }}>
                  {t.score >= 0 ? "+" : ""}{t.score.toFixed(3)}
                </span>
                <span className="sub">wt ≤ {(t.weight_suggestion * 100).toFixed(1)}%</span>
                <div className="tchain">{t.chain}</div>
                <div className="sub">invalidated by: {t.invalidation}</div>
              </div>
            ))}
          </div>
          <div className="sub" style={{ marginTop: 8 }}>
            Decision support, not orders — the engine still trades through formula + risk + safety.
            Feed convictions you agree with into your views.
          </div>
        </div>
      )}

      {/* ---------- events: signal vs noise ---------- */}
      {events.length > 0 && (
        <div className="card">
          <h3>
            Events this cycle — {active?.signal_events ?? events.filter((e) => !e.is_noise).length} signal
            {" / "}{active?.noise_events ?? events.filter((e) => e.is_noise).length} noise
            {active?.ts && <span className="sub"> · {active.ts}{active?.simulated ? " (simulation)" : ""}</span>}
          </h3>
          <div className="events">
            {events.map((e, i) => (
              <div key={i} className={`event ${e.is_noise ? "noise" : "signal"}`}>
                <span className={`badge ${e.is_noise ? "b-noise" : "b-signal"}`}>
                  {e.is_noise ? "NOISE" : "SIGNAL"}
                </span>
                <span className="etext">{e.summary}</span>
                <span className="sub">
                  {e.source && `${e.source} · `}
                  cred {((e.credibility ?? 0) * 100).toFixed(0)}%
                  {typeof e.impulse === "number" && ` · impulse ${e.impulse >= 0 ? "+" : ""}${e.impulse.toFixed(2)}`}
                  {e.emotion && e.emotion !== "neutral" && ` · ${e.emotion}`}
                  {e.fallback && " · offline read"}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
