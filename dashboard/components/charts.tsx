"use client";

import { useRef, useState } from "react";

export interface Series {
  label: string;
  color: string;
  values: number[];
}

function money(v: number): string {
  return v >= 1000 ? `$${Math.round(v).toLocaleString()}` : `$${v.toFixed(2)}`;
}

export function EquityChart({ series }: { series: Series[] }) {
  const W = 820, H = 250, padL = 6, padR = 66, padT = 12, padB = 20;
  const [idx, setIdx] = useState<number | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  const nonEmpty = series.filter((s) => s.values.length > 0);
  if (nonEmpty.length === 0) {
    return (
      <div className="empty">
        No equity data yet — run <code className="inline">python3 -m ai_investing.main --once</code> or a backtest.
      </div>
    );
  }

  const all = nonEmpty.flatMap((s) => s.values);
  const min = Math.min(...all), max = Math.max(...all);
  const span = max - min || 1;
  const n = Math.max(...nonEmpty.map((s) => s.values.length));
  const X = (i: number) => padL + (n <= 1 ? 0 : i / (n - 1)) * (W - padL - padR);
  const Y = (v: number) => padT + (1 - (v - min) / span) * (H - padT - padB);
  const line = (vals: number[]) =>
    vals.map((v, i) => `${i === 0 ? "M" : "L"}${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(" ");

  const onMove = (e: React.MouseEvent) => {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect) return;
    const ratio = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
    setIdx(Math.round(ratio * (n - 1)));
  };

  const ticks = [max, min + span / 2, min];

  return (
    <div>
      {nonEmpty.length > 1 && (
        <div className="legend">
          {nonEmpty.map((s) => (
            <span className="k" key={s.label}>
              <span className="swatch" style={{ background: s.color }} />
              {s.label}
            </span>
          ))}
        </div>
      )}
      <svg
        ref={svgRef}
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        role="img"
        aria-label="Equity over time"
        onMouseMove={onMove}
        onMouseLeave={() => setIdx(null)}
        style={{ display: "block" }}
      >
        {ticks.map((t, i) => (
          <g key={i}>
            <line x1={padL} x2={W - padR} y1={Y(t)} y2={Y(t)} stroke="var(--grid)" strokeWidth={1} />
            <text x={W - padR + 6} y={Y(t) + 4} fill="var(--muted)" fontSize={11}>{money(t)}</text>
          </g>
        ))}
        {nonEmpty.map((s, si) => (
          <path key={si} d={line(s.values)} fill="none" stroke={s.color} strokeWidth={2} strokeLinejoin="round" />
        ))}
        {idx !== null && (
          <g>
            <line x1={X(idx)} x2={X(idx)} y1={padT} y2={H - padB} stroke="var(--axis)" strokeWidth={1} />
            {nonEmpty.map((s, si) => {
              const v = s.values[Math.min(idx, s.values.length - 1)];
              if (v === undefined) return null;
              const left = X(idx) < W / 2;
              return (
                <g key={si}>
                  <circle cx={X(idx)} cy={Y(v)} r={3.5} fill={s.color} />
                  <text
                    x={left ? X(idx) + 8 : X(idx) - 8}
                    y={Y(v) - 6}
                    textAnchor={left ? "start" : "end"}
                    fill="var(--ink)"
                    fontSize={11}
                    fontWeight={600}
                  >
                    {money(v)}
                  </text>
                </g>
              );
            })}
          </g>
        )}
      </svg>
    </div>
  );
}

export function WeightBars({ weights }: { weights: Record<string, number> }) {
  const entries = Object.entries(weights);
  const maxAbs = Math.max(1e-9, ...entries.map(([, v]) => Math.abs(v)));
  return (
    <div className="weights">
      {entries.map(([name, v]) => {
        const widthPct = (Math.abs(v) / maxAbs) * 50;
        const positive = v >= 0;
        return (
          <div className="wrow" key={name}>
            <div className="wname">{name}</div>
            <div className="track">
              <div className="zero" />
              <div
                className="bar"
                style={{
                  background: positive ? "var(--series-1)" : "var(--neg)",
                  left: positive ? "50%" : `${50 - widthPct}%`,
                  width: `${widthPct}%`,
                }}
              />
            </div>
            <div className="wval">{v >= 0 ? "+" : ""}{v.toFixed(4)}</div>
          </div>
        );
      })}
    </div>
  );
}
