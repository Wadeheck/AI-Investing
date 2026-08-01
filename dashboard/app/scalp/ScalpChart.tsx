"use client";

import { useEffect, useRef } from "react";

export type Candle = [string, number, number, number, number, number];
export type Level = { kind: string; price: number };
export type Signal = { tag: string; side: number; entry: number; stop: number; target: number };

type Props = {
  candles: Candle[];
  ema9: (number | null)[];
  vwap24: (number | null)[];
  levels: Level[];
  valueArea: { va_lo: number; va_hi: number; poc: number };
  signals: Signal[];
  height?: number;
};

export default function ScalpChart({ candles, ema9, vwap24, levels, valueArea, signals, height = 380 }: Props) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const cv = ref.current;
    if (!cv || !candles.length) return;
    const dpr = window.devicePixelRatio || 1;
    const W = cv.clientWidth, H = height;
    cv.width = W * dpr; cv.height = H * dpr;
    const g = cv.getContext("2d")!;
    g.scale(dpr, dpr);
    g.clearRect(0, 0, W, H);

    const lows = candles.map(c => c[3]), highs = candles.map(c => c[2]);
    let lo = Math.min(...lows), hi = Math.max(...highs);
    const pad = (hi - lo) * 0.06 || 1;
    lo -= pad; hi += pad;
    const px = (p: number) => H - ((p - lo) / (hi - lo)) * (H - 22) - 12;
    const bx = (i: number) => (i + 0.5) * (W - 54) / candles.length;

    // value area shading + POC
    if (valueArea && isFinite(valueArea.va_lo)) {
      g.fillStyle = "rgba(90,120,200,0.08)";
      g.fillRect(0, px(valueArea.va_hi), W - 54, px(valueArea.va_lo) - px(valueArea.va_hi));
      g.strokeStyle = "rgba(90,120,200,0.5)"; g.setLineDash([4, 4]);
      g.beginPath(); g.moveTo(0, px(valueArea.poc)); g.lineTo(W - 54, px(valueArea.poc)); g.stroke();
      g.setLineDash([]);
    }
    // confirmed levels
    for (const lv of levels || []) {
      g.strokeStyle = lv.kind === "sup" ? "rgba(80,200,120,0.55)" : "rgba(230,90,90,0.55)";
      g.setLineDash([6, 3]);
      g.beginPath(); g.moveTo(0, px(lv.price)); g.lineTo(W - 54, px(lv.price)); g.stroke();
      g.setLineDash([]);
    }
    // candles
    const cw = Math.max(1.5, (W - 54) / candles.length * 0.65);
    candles.forEach((c, i) => {
      const [, o, h, l, cl] = c;
      const up = cl >= o;
      g.strokeStyle = g.fillStyle = up ? "#2ecc71" : "#e74c3c";
      g.beginPath(); g.moveTo(bx(i), px(h)); g.lineTo(bx(i), px(l)); g.stroke();
      g.fillRect(bx(i) - cw / 2, px(Math.max(o, cl)), cw, Math.max(1, Math.abs(px(o) - px(cl))));
    });
    // overlays
    const line = (arr: (number | null)[], color: string) => {
      g.strokeStyle = color; g.lineWidth = 1.3; g.beginPath();
      let started = false;
      arr.forEach((v, i) => {
        if (v == null || !isFinite(v)) return;
        if (!started) { g.moveTo(bx(i), px(v)); started = true; } else g.lineTo(bx(i), px(v));
      });
      g.stroke(); g.lineWidth = 1;
    };
    line(ema9, "#f39c12");
    line(vwap24, "#9b59b6");
    // active signal markers on the right edge
    for (const s of signals || []) {
      for (const [p, col, lab] of [[s.entry, "#f1c40f", "E"], [s.stop, "#e74c3c", "S"], [s.target, "#2ecc71", "T"]] as [number, string, string][]) {
        g.fillStyle = col;
        g.fillRect(W - 52, px(p) - 1, 10, 2);
        g.font = "9px monospace"; g.fillText(lab, W - 40, px(p) + 3);
      }
    }
    // price axis
    g.fillStyle = "#8a93a6"; g.font = "10px monospace";
    for (let k = 0; k <= 4; k++) {
      const p = lo + (hi - lo) * k / 4;
      g.fillText(p >= 1000 ? p.toFixed(0) : p.toFixed(2), W - 50, px(p) + 3);
    }
    const last = candles[candles.length - 1][4];
    g.fillStyle = "#ffffff"; g.fillRect(W - 54, px(last) - 8, 54, 14);
    g.fillStyle = "#111"; g.fillText(last >= 1000 ? last.toFixed(0) : last.toFixed(2), W - 50, px(last) + 3);
  }, [candles, ema9, vwap24, levels, valueArea, signals, height]);

  return <canvas ref={ref} style={{ width: "100%", height }} />;
}
