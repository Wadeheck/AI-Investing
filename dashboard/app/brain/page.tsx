"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import GraphField, { TYPE_COLOR } from "./GraphField";
import type { Graph, TraceStep } from "./types";

/* ---------- types mirroring the engine's JSON ---------- */
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
  circular_financing?: { investor: string; counterparty: string; labels: string; pattern: string; note?: string }[];
  activations?: Record<string, number>;      // persistent field (live view)
  pending_effects?: Pending[];               // τ-queue: effects landing later
  delayed_preview?: Pending[];               // simulation: what WOULD land later
  centrality?: Record<string, number>;       // systemic importance, max=1
};

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
        <div className="card card-field">
          <GraphField
            graph={graph}
            impacts={visibleImpacts}
            centrality={centrality}
            trace={trace}
            selected={selected}
            onSelect={setSelected}
            fieldTs={active?.ts}
          />
          <div className="legend">
            {Object.entries(TYPE_COLOR).filter(([t]) => t !== "sector").map(([t, c]) => (
              <span key={t}><i style={{ background: c }} />{t}</span>
            ))}
            <span><i className="dash" />LLM-proposed edge</span>
          </div>
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
          {(live?.circular_financing?.length ?? 0) > 0 && (
            <div className="card">
              <h3>⚠ Circular financing watch</h3>
              {live!.circular_financing!.map((l, i) => (
                <div key={i} className="scen">
                  <b>{l.labels}</b>
                  <div className="sub">{l.pattern} — {l.note}</div>
                  <div className="sub">long conviction on both parties is haircut 40%</div>
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
