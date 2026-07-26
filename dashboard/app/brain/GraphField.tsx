"use client";

/*
 * GraphField — canvas-rendered interactive knowledge-graph.
 *
 * Interactions: scroll/pinch zoom (to cursor), drag pan, shift-drag rotate,
 * drag a node to reposition it (live physics), click to focus, double-click
 * to zoom, search with fly-to, type filter chips, hover tooltips.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Graph, GNode, GEdge, TraceStep } from "./types";

export const TYPE_COLOR: Record<string, string> = {
  factor: "#8a63d2", commodity: "#b8860b", actor: "#d05c8c",
  theme: "#2a78d6", sector: "#2a78d6", asset: "#1baf7a",
};
const TYPE_R: Record<string, number> = {
  factor: 11, commodity: 10, actor: 10, theme: 9, sector: 9, asset: 7,
};
const TYPE_RING: Record<string, number> = {
  factor: 150, commodity: 280, actor: 280, theme: 420, sector: 420, asset: 620,
};

type SimNode = GNode & { x: number; y: number; vx: number; vy: number };
type Cam = { x: number; y: number; k: number; theta: number };

type Props = {
  graph: Graph | null;
  impacts: Record<string, number>;
  centrality: Record<string, number>;
  trace: TraceStep[];
  selected: string | null;
  onSelect: (id: string | null) => void;
  fieldTs?: string;
};

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));
const ease = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

export default function GraphField({ graph, impacts, centrality, trace, selected, onSelect, fieldTs }: Props) {
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const tipRef = useRef<HTMLDivElement | null>(null);

  /* ----- simulation state (refs: read by the rAF loop) ----- */
  const nodesRef = useRef<SimNode[]>([]);
  const byIdRef = useRef<Map<string, SimNode>>(new Map());
  const edgesRef = useRef<GEdge[]>([]);
  const adjRef = useRef<Map<string, Set<string>>>(new Map());
  const alphaRef = useRef(0);

  /* ----- camera / gesture state ----- */
  const camRef = useRef<Cam>({ x: 0, y: 0, k: 0.6, theta: 0 });
  const fitKRef = useRef(0.6);
  const sizeRef = useRef({ w: 800, h: 600 });
  const animRef = useRef<{ t0: number; from: Cam; to: Cam } | null>(null);
  const gestureRef = useRef<
    | { mode: "pan"; world: [number, number]; moved: number; hitNode: string | null }
    | { mode: "node"; id: string; moved: number }
    | { mode: "rotate"; angle0: number; theta0: number; moved: number }
    | { mode: "pinch"; d0: number; a0: number; k0: number; theta0: number; world: [number, number] }
    | null
  >(null);
  const pointersRef = useRef<Map<number, { x: number; y: number }>>(new Map());
  const mouseRef = useRef<{ x: number; y: number } | null>(null);
  const interactedRef = useRef(false);

  /* ----- data flowing into the draw loop ----- */
  const liveRef = useRef<{
    impacts: Record<string, number>;
    centrality: Record<string, number>;
    hot: Map<string, number>;
    selected: string | null;
    neighbors: Set<string>;
    hover: string | null;
    hidden: Set<string>;
  }>({ impacts: {}, centrality: {}, hot: new Map(), selected: null, neighbors: new Set(), hover: null, hidden: new Set() });

  const themeRef = useRef<Record<string, string>>({});

  /* ----- react-level UI state ----- */
  const [hover, setHover] = useState<string | null>(null);
  const [hiddenTypes, setHiddenTypes] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchIdx, setSearchIdx] = useState(0);
  const [rotated, setRotated] = useState(false);
  const searchRef = useRef<HTMLInputElement | null>(null);

  /* ---------- theme colors from CSS vars ---------- */
  const refreshTheme = useCallback(() => {
    const cs = getComputedStyle(document.documentElement);
    const get = (v: string) => cs.getPropertyValue(v).trim();
    themeRef.current = {
      plane: get("--plane") || "#0d0d0d",
      surface: get("--surface") || "#1a1a19",
      ink: get("--ink") || "#fff",
      ink2: get("--ink-2") || "#c3c2b7",
      muted: get("--muted") || "#898781",
      axis: get("--axis") || "#383835",
      pos: get("--pos") || "#0ca30c",
      neg: get("--neg") || "#e66767",
    };
  }, []);
  useEffect(() => {
    refreshTheme();
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const fn = () => refreshTheme();
    mq.addEventListener("change", fn);
    return () => mq.removeEventListener("change", fn);
  }, [refreshTheme]);

  /* ---------- seed nodes when the graph arrives ---------- */
  useEffect(() => {
    if (!graph) return;
    const prev = byIdRef.current;
    const n = graph.nodes.length;
    const nodes: SimNode[] = graph.nodes.map((nd, i) => {
      const old = prev.get(nd.id);
      if (old) return { ...nd, x: old.x, y: old.y, vx: 0, vy: 0 };
      const angle = (2 * Math.PI * i) / Math.max(1, n) + (i % 3) * 0.7;
      const ring = TYPE_RING[nd.type] ?? 420;
      return {
        ...nd,
        x: ring * Math.cos(angle) + ((i * 37) % 60) - 30,
        y: ring * Math.sin(angle) + ((i * 53) % 60) - 30,
        vx: 0, vy: 0,
      };
    });
    nodesRef.current = nodes;
    const map = new Map(nodes.map((nd) => [nd.id, nd]));
    byIdRef.current = map;
    edgesRef.current = graph.edges.filter((e) => map.has(e.src) && map.has(e.dst));
    const adj = new Map<string, Set<string>>();
    for (const e of edgesRef.current) {
      if (!adj.has(e.src)) adj.set(e.src, new Set());
      if (!adj.has(e.dst)) adj.set(e.dst, new Set());
      adj.get(e.src)!.add(e.dst);
      adj.get(e.dst)!.add(e.src);
    }
    adjRef.current = adj;
    alphaRef.current = 1;
    // fit once the layout has had a moment to breathe, again once it settles
    const t1 = setTimeout(() => { if (!interactedRef.current) fitView(true); }, 900);
    const t2 = setTimeout(() => { if (!interactedRef.current) fitView(); }, 2800);
    return () => { clearTimeout(t1); clearTimeout(t2); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graph]);

  /* ---------- keep live data in the loop's refs ---------- */
  useEffect(() => {
    const hot = new Map<string, number>();
    for (const t of trace) {
      hot.set(`${t.from}|${t.to}`, t.contribution);
      hot.set(`${t.to}|${t.from}`, t.contribution);
    }
    const neighbors = new Set<string>();
    if (selected) {
      neighbors.add(selected);
      for (const nb of adjRef.current.get(selected) ?? []) neighbors.add(nb);
    }
    liveRef.current = { impacts, centrality, hot, selected, neighbors, hover, hidden: hiddenTypes };
  }, [impacts, centrality, trace, selected, hover, hiddenTypes, graph]);

  /* ---------- camera helpers ---------- */
  const screenFromWorld = (wx: number, wy: number) => {
    const { x, y, k, theta } = camRef.current;
    const { w, h } = sizeRef.current;
    const cos = Math.cos(theta), sin = Math.sin(theta);
    const dx = wx - x, dy = wy - y;
    return [w / 2 + (dx * cos - dy * sin) * k, h / 2 + (dx * sin + dy * cos) * k] as [number, number];
  };
  const worldFromScreen = (sx: number, sy: number) => {
    const { x, y, k, theta } = camRef.current;
    const { w, h } = sizeRef.current;
    const cos = Math.cos(theta), sin = Math.sin(theta);
    const px = (sx - w / 2) / k, py = (sy - h / 2) / k;
    return [x + px * cos + py * sin, y - px * sin + py * cos] as [number, number];
  };
  /** move the camera so world point (wx,wy) lands on screen point (sx,sy) at zoom k / angle theta */
  const anchorCamera = (wx: number, wy: number, sx: number, sy: number, k: number, theta: number) => {
    const { w, h } = sizeRef.current;
    const cos = Math.cos(theta), sin = Math.sin(theta);
    const px = (sx - w / 2) / k, py = (sy - h / 2) / k;
    camRef.current = { x: wx - (px * cos + py * sin), y: wy - (-px * sin + py * cos), k, theta };
  };

  const fitView = useCallback((instant = false) => {
    const nodes = nodesRef.current;
    if (!nodes.length) return;
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    for (const n of nodes) {
      if (n.x < minX) minX = n.x; if (n.x > maxX) maxX = n.x;
      if (n.y < minY) minY = n.y; if (n.y > maxY) maxY = n.y;
    }
    const { w, h } = sizeRef.current;
    const bw = Math.max(80, maxX - minX), bh = Math.max(80, maxY - minY);
    const k = clamp(Math.min((w - 90) / bw, (h - 90) / bh), 0.08, 2.5);
    fitKRef.current = k;
    const to: Cam = { x: (minX + maxX) / 2, y: (minY + maxY) / 2, k, theta: 0 };
    if (instant) { camRef.current = to; animRef.current = null; }
    else animRef.current = { t0: performance.now(), from: { ...camRef.current }, to };
    setRotated(false);
  }, []);

  const flyTo = useCallback((id: string) => {
    const n = byIdRef.current.get(id);
    if (!n) return;
    const cam = camRef.current;
    animRef.current = {
      t0: performance.now(),
      from: { ...cam },
      to: { x: n.x, y: n.y, k: Math.max(cam.k, fitKRef.current * 2.6), theta: cam.theta },
    };
  }, []);

  const zoomBy = useCallback((factor: number, sx?: number, sy?: number) => {
    const { w, h } = sizeRef.current;
    const px = sx ?? w / 2, py = sy ?? h / 2;
    const [wx, wy] = worldFromScreen(px, py);
    const k = clamp(camRef.current.k * factor, fitKRef.current * 0.55, 9);
    animRef.current = null;
    anchorCamera(wx, wy, px, py, k, camRef.current.theta);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /* ---------- node radius (screen px, semi-constant across zoom) ---------- */
  const nodeR = (n: SimNode, live: typeof liveRef.current, k: number) => {
    const mag = Math.min(1, Math.abs(live.impacts[n.id] ?? 0));
    const base = (TYPE_R[n.type] ?? 8) + (live.centrality[n.id] ?? 0) * 10 + mag * 10;
    return Math.max(3.5, base * Math.pow(k, 0.45) * 0.95);
  };

  /* ---------- hit testing ---------- */
  const pickNode = (sx: number, sy: number): SimNode | null => {
    const live = liveRef.current;
    const k = camRef.current.k;
    let best: SimNode | null = null, bestD = Infinity;
    for (const n of nodesRef.current) {
      if (live.hidden.has(n.type)) continue;
      const [px, py] = screenFromWorld(n.x, n.y);
      const r = nodeR(n, live, k) + 5;
      const d = (px - sx) ** 2 + (py - sy) ** 2;
      if (d < r * r && d < bestD) { best = n; bestD = d; }
    }
    return best;
  };

  /* ---------- physics tick ---------- */
  const tick = () => {
    const nodes = nodesRef.current;
    const edges = edgesRef.current;
    const g = gestureRef.current;
    const dragId = g?.mode === "node" ? g.id : null;
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i], b = nodes[j];
        let dx = a.x - b.x, dy = a.y - b.y;
        let d2 = dx * dx + dy * dy;
        if (d2 < 1) { dx = (i % 2 ? 1 : -1) * 0.5; dy = 0.5; d2 = 1; }
        if (d2 > 260000) continue;
        const f = 9000 / d2;
        const d = Math.sqrt(d2);
        const fx = (dx / d) * f, fy = (dy / d) * f;
        a.vx += fx; a.vy += fy; b.vx -= fx; b.vy -= fy;
      }
    }
    for (const e of edges) {
      const a = byIdRef.current.get(e.src)!, b = byIdRef.current.get(e.dst)!;
      const dx = b.x - a.x, dy = b.y - a.y;
      const d = Math.max(1, Math.sqrt(dx * dx + dy * dy));
      const f = 0.015 * (d - 175) * (e.weight ?? 0.5);
      a.vx += (dx / d) * f; a.vy += (dy / d) * f;
      b.vx -= (dx / d) * f; b.vy -= (dy / d) * f;
    }
    for (const n of nodes) {
      if (n.id === dragId) { n.vx = 0; n.vy = 0; continue; }
      n.vx += -n.x * 0.0035; n.vy += -n.y * 0.0035;
      n.vx = clamp(n.vx * 0.83, -60, 60);
      n.vy = clamp(n.vy * 0.83, -60, 60);
      n.x += n.vx; n.y += n.vy;
    }
    alphaRef.current *= 0.988;
  };

  /* ---------- render loop ---------- */
  useEffect(() => {
    let raf = 0;
    const loop = (now: number) => {
      raf = requestAnimationFrame(loop);
      const canvas = canvasRef.current;
      if (!canvas) return;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;

      // camera animation
      const anim = animRef.current;
      if (anim) {
        const t = clamp((now - anim.t0) / 620, 0, 1);
        const e = ease(t);
        camRef.current = {
          x: anim.from.x + (anim.to.x - anim.from.x) * e,
          y: anim.from.y + (anim.to.y - anim.from.y) * e,
          k: anim.from.k + (anim.to.k - anim.from.k) * e,
          theta: anim.from.theta + (anim.to.theta - anim.from.theta) * e,
        };
        if (t >= 1) animRef.current = null;
      }

      if (alphaRef.current > 0.02) { tick(); tick(); }

      const { w, h } = sizeRef.current;
      const dpr = window.devicePixelRatio || 1;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const th = themeRef.current;
      ctx.clearRect(0, 0, w, h);

      const live = liveRef.current;
      const cam = camRef.current;
      const k = cam.k;
      const focus = live.selected !== null;

      // precompute screen positions
      const nodes = nodesRef.current;
      const sp = new Map<string, [number, number]>();
      for (const n of nodes) sp.set(n.id, screenFromWorld(n.x, n.y));

      /* --- edges --- */
      const hotEdges: { a: [number, number]; b: [number, number]; c: number }[] = [];
      for (const e of edgesRef.current) {
        const a = sp.get(e.src)!, b = sp.get(e.dst)!;
        const hidden = live.hidden.has(byIdRef.current.get(e.src)!.type) || live.hidden.has(byIdRef.current.get(e.dst)!.type);
        const contribution = live.hot.get(`${e.src}|${e.dst}`);
        const isHot = contribution !== undefined && !hidden;
        const touchesFocus = focus && (e.src === live.selected || e.dst === live.selected);
        const touchesHover = live.hover && (e.src === live.hover || e.dst === live.hover);
        const wgt = e.weight ?? 0.5;
        let alpha = 0.18 + wgt * 0.25;
        if (hidden) alpha = 0.03;
        else if (focus && !touchesFocus && !isHot) alpha = 0.05;
        else if (touchesFocus || touchesHover) alpha = 0.75;
        ctx.beginPath();
        ctx.moveTo(a[0], a[1]);
        ctx.lineTo(b[0], b[1]);
        if (isHot) {
          ctx.strokeStyle = contribution! >= 0 ? th.pos : th.neg;
          ctx.globalAlpha = 0.9;
          ctx.lineWidth = 2.4;
          hotEdges.push({ a, b, c: contribution! });
        } else {
          ctx.strokeStyle = touchesFocus || touchesHover ? th.ink2 : th.axis;
          ctx.globalAlpha = alpha;
          ctx.lineWidth = touchesFocus || touchesHover ? 1.6 : 0.5 + wgt * 1.1;
        }
        if (e.provenance === "llm") ctx.setLineDash([5, 4]); else ctx.setLineDash([]);
        ctx.stroke();
      }
      ctx.setLineDash([]);

      /* --- ripple particles on hot edges --- */
      for (let i = 0; i < hotEdges.length; i++) {
        const { a, b, c } = hotEdges[i];
        const t = ((now / 1400) + i * 0.31) % 1;
        const px = a[0] + (b[0] - a[0]) * t, py = a[1] + (b[1] - a[1]) * t;
        ctx.beginPath();
        ctx.arc(px, py, 2.6, 0, Math.PI * 2);
        ctx.fillStyle = c >= 0 ? th.pos : th.neg;
        ctx.globalAlpha = 0.9;
        ctx.fill();
      }

      /* --- nodes --- */
      const labels: { n: SimNode; p: [number, number]; r: number; imp: number; strong: boolean }[] = [];
      for (const n of nodes) {
        const p = sp.get(n.id)!;
        if (p[0] < -60 || p[0] > w + 60 || p[1] < -60 || p[1] > h + 60) continue;
        const hidden = live.hidden.has(n.type);
        const imp = live.impacts[n.id] ?? 0;
        const mag = Math.min(1, Math.abs(imp));
        const r = nodeR(n, live, k);
        const inFocus = !focus || live.neighbors.has(n.id);
        const isSel = live.selected === n.id;
        const isHover = live.hover === n.id;
        let alpha = hidden ? 0.05 : inFocus ? 0.95 : 0.15;

        // glow for charged nodes
        if (mag > 0.02 && !hidden) {
          const pulse = 1 + 0.12 * Math.sin(now / 300 + p[0]);
          const glowR = (r + 7) * pulse;
          const grad = ctx.createRadialGradient(p[0], p[1], r * 0.4, p[0], p[1], glowR + 6);
          const gc = imp > 0 ? th.pos : th.neg;
          grad.addColorStop(0, gc);
          grad.addColorStop(1, "transparent");
          ctx.globalAlpha = (0.25 + mag * 0.4) * (inFocus ? 1 : 0.25);
          ctx.beginPath();
          ctx.arc(p[0], p[1], glowR + 6, 0, Math.PI * 2);
          ctx.fillStyle = grad;
          ctx.fill();
        }

        ctx.beginPath();
        ctx.arc(p[0], p[1], r, 0, Math.PI * 2);
        ctx.fillStyle = TYPE_COLOR[n.type] ?? "#888";
        ctx.globalAlpha = alpha;
        ctx.fill();
        if (isSel || isHover) {
          ctx.beginPath();
          ctx.arc(p[0], p[1], r + 2.5, 0, Math.PI * 2);
          ctx.strokeStyle = th.ink;
          ctx.globalAlpha = isSel ? 0.95 : 0.55;
          ctx.lineWidth = 2;
          ctx.stroke();
        } else if (mag > 0.02 && !hidden) {
          ctx.beginPath();
          ctx.arc(p[0], p[1], r + 1.5, 0, Math.PI * 2);
          ctx.strokeStyle = imp > 0 ? th.pos : th.neg;
          ctx.globalAlpha = 0.8 * (inFocus ? 1 : 0.3);
          ctx.lineWidth = 1.8;
          ctx.stroke();
        }

        const showLabel =
          !hidden &&
          (isSel || isHover || mag > 0.02 ||
            (focus && live.neighbors.has(n.id)) ||
            (n.type !== "asset" ? k >= fitKRef.current * 0.85 : k >= fitKRef.current * 2.1));
        if (showLabel) labels.push({ n, p, r, imp, strong: isSel || isHover || mag > 0.02 });
      }

      /* --- labels (drawn last, upright regardless of rotation, collision-pruned) --- */
      ctx.textAlign = "center";
      const prio = (l: (typeof labels)[number]) =>
        (live.selected === l.n.id ? 1000 : 0) + (live.hover === l.n.id ? 900 : 0) +
        Math.abs(l.imp) * 100 + (live.centrality[l.n.id] ?? 0) * 20 +
        (l.n.type !== "asset" ? 5 : 0);
      labels.sort((a, b) => prio(b) - prio(a));
      const placed: [number, number, number, number][] = [];
      for (const { n, p, r, imp, strong } of labels) {
        const inFocus = !focus || live.neighbors.has(n.id) || live.hover === n.id;
        const mag = Math.abs(imp);
        const text = n.label + (mag > 0.02 ? ` ${imp > 0 ? "+" : ""}${imp.toFixed(2)}` : "");
        ctx.font = strong ? "600 12px system-ui, sans-serif" : "11px system-ui, sans-serif";
        const tw = ctx.measureText(text).width;
        const bx0 = p[0] - tw / 2 - 3, bx1 = p[0] + tw / 2 + 3;
        const by1 = p[1] - r - 3, by0 = by1 - 14;
        const mustShow = live.selected === n.id || live.hover === n.id;
        if (!mustShow && placed.some(([x0, y0, x1, y1]) => bx0 < x1 && bx1 > x0 && by0 < y1 && by1 > y0)) continue;
        placed.push([bx0, by0, bx1, by1]);
        ctx.globalAlpha = inFocus ? 1 : 0.25;
        ctx.lineWidth = 3;
        ctx.strokeStyle = th.plane;
        ctx.strokeText(text, p[0], p[1] - r - 6);
        ctx.fillStyle = strong ? th.ink : th.ink2;
        ctx.fillText(text, p[0], p[1] - r - 6);
      }
      ctx.globalAlpha = 1;

      // tooltip follows the cursor
      const tip = tipRef.current;
      if (tip && mouseRef.current && live.hover && !gestureRef.current) {
        tip.style.transform = `translate(${mouseRef.current.x + 14}px, ${mouseRef.current.y + 14}px)`;
      }
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /* ---------- resize ---------- */
  useEffect(() => {
    const wrap = wrapRef.current, canvas = canvasRef.current;
    if (!wrap || !canvas) return;
    const ro = new ResizeObserver(() => {
      const rect = wrap.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      sizeRef.current = { w: rect.width, h: rect.height };
      canvas.width = Math.round(rect.width * dpr);
      canvas.height = Math.round(rect.height * dpr);
      canvas.style.width = `${rect.width}px`;
      canvas.style.height = `${rect.height}px`;
    });
    ro.observe(wrap);
    return () => ro.disconnect();
  }, []);

  /* ---------- pointer gestures ---------- */
  const localXY = (e: { clientX: number; clientY: number }) => {
    const rect = canvasRef.current!.getBoundingClientRect();
    return [e.clientX - rect.left, e.clientY - rect.top] as [number, number];
  };

  const onPointerDown = (e: React.PointerEvent) => {
    canvasRef.current!.setPointerCapture(e.pointerId);
    interactedRef.current = true;
    const [sx, sy] = localXY(e);
    pointersRef.current.set(e.pointerId, { x: sx, y: sy });
    animRef.current = null;
    setSearchOpen(false);

    if (pointersRef.current.size === 2) {
      const [p1, p2] = [...pointersRef.current.values()];
      const mid: [number, number] = [(p1.x + p2.x) / 2, (p1.y + p2.y) / 2];
      gestureRef.current = {
        mode: "pinch",
        d0: Math.hypot(p2.x - p1.x, p2.y - p1.y),
        a0: Math.atan2(p2.y - p1.y, p2.x - p1.x),
        k0: camRef.current.k,
        theta0: camRef.current.theta,
        world: worldFromScreen(mid[0], mid[1]),
      };
      return;
    }

    const hit = pickNode(sx, sy);
    if (e.shiftKey && !hit) {
      const { w, h } = sizeRef.current;
      gestureRef.current = {
        mode: "rotate",
        angle0: Math.atan2(sy - h / 2, sx - w / 2),
        theta0: camRef.current.theta,
        moved: 0,
      };
    } else if (hit && !e.shiftKey) {
      gestureRef.current = { mode: "node", id: hit.id, moved: 0 };
    } else {
      gestureRef.current = { mode: "pan", world: worldFromScreen(sx, sy), moved: 0, hitNode: hit?.id ?? null };
    }
  };

  const onPointerMove = (e: React.PointerEvent) => {
    const [sx, sy] = localXY(e);
    mouseRef.current = { x: sx, y: sy };
    const prev = pointersRef.current.get(e.pointerId);
    if (prev) pointersRef.current.set(e.pointerId, { x: sx, y: sy });
    const g = gestureRef.current;

    if (!g) {
      const hit = pickNode(sx, sy);
      setHover(hit?.id ?? null);
      return;
    }
    if (g.mode === "pinch") {
      if (pointersRef.current.size < 2) return;
      const [p1, p2] = [...pointersRef.current.values()];
      const d = Math.hypot(p2.x - p1.x, p2.y - p1.y);
      const a = Math.atan2(p2.y - p1.y, p2.x - p1.x);
      const k = clamp(g.k0 * (d / Math.max(1, g.d0)), fitKRef.current * 0.55, 9);
      const theta = g.theta0 + (a - g.a0);
      anchorCamera(g.world[0], g.world[1], (p1.x + p2.x) / 2, (p1.y + p2.y) / 2, k, theta);
      setRotated(Math.abs(theta) > 0.02);
      return;
    }
    const dx = prev ? sx - prev.x : 0, dy = prev ? sy - prev.y : 0;
    g.moved += Math.abs(dx) + Math.abs(dy);
    if (g.mode === "pan") {
      anchorCamera(g.world[0], g.world[1], sx, sy, camRef.current.k, camRef.current.theta);
    } else if (g.mode === "node") {
      const n = byIdRef.current.get(g.id);
      if (n) {
        const [wx, wy] = worldFromScreen(sx, sy);
        n.x = wx; n.y = wy; n.vx = 0; n.vy = 0;
        alphaRef.current = Math.max(alphaRef.current, 0.3);
      }
    } else if (g.mode === "rotate") {
      const { w, h } = sizeRef.current;
      const a = Math.atan2(sy - h / 2, sx - w / 2);
      camRef.current.theta = g.theta0 + (a - g.angle0);
      setRotated(Math.abs(camRef.current.theta) > 0.02);
    }
  };

  const onPointerUp = (e: React.PointerEvent) => {
    pointersRef.current.delete(e.pointerId);
    const g = gestureRef.current;
    gestureRef.current = null;
    if (!g || pointersRef.current.size > 0) return;
    if (g.mode === "node" && g.moved < 5) {
      onSelect(g.id === selected ? null : g.id);
    } else if (g.mode === "pan" && g.moved < 5) {
      onSelect(null);
    }
  };

  /* wheel zoom needs a native non-passive listener, else the page scrolls */
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const fn = (e: WheelEvent) => {
      e.preventDefault();
      interactedRef.current = true;
      const rect = canvas.getBoundingClientRect();
      zoomBy(Math.exp(-e.deltaY * 0.0014), e.clientX - rect.left, e.clientY - rect.top);
    };
    canvas.addEventListener("wheel", fn, { passive: false });
    return () => canvas.removeEventListener("wheel", fn);
  }, [zoomBy]);

  const onDoubleClick = (e: React.MouseEvent) => {
    const [sx, sy] = localXY(e);
    const hit = pickNode(sx, sy);
    if (hit) { onSelect(hit.id); flyTo(hit.id); }
    else zoomBy(1.7, sx, sy);
  };

  /* ---------- keyboard ---------- */
  useEffect(() => {
    const fn = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (e.key === "/" && tag !== "INPUT" && tag !== "TEXTAREA") {
        e.preventDefault();
        searchRef.current?.focus();
      } else if (e.key === "Escape") {
        setQuery(""); setSearchOpen(false); onSelect(null);
      }
    };
    window.addEventListener("keydown", fn);
    return () => window.removeEventListener("keydown", fn);
  }, [onSelect]);

  /* ---------- search ---------- */
  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q || !graph) return [];
    const scored: { n: GNode; s: number }[] = [];
    for (const n of graph.nodes) {
      const label = n.label.toLowerCase();
      const sym = (n.symbol ?? "").toLowerCase();
      let s = -1;
      if (label.startsWith(q) || sym.startsWith(q)) s = 3;
      else if (label.includes(q) || sym.includes(q) || n.id.toLowerCase().includes(q)) s = 2;
      else if ((n.aliases ?? []).some((a) => a.toLowerCase().includes(q))) s = 1;
      if (s > 0) scored.push({ n, s });
    }
    scored.sort((a, b) => b.s - a.s || a.n.label.length - b.n.label.length);
    return scored.slice(0, 8).map((r) => r.n);
  }, [query, graph]);

  const chooseResult = (n: GNode) => {
    onSelect(n.id);
    flyTo(n.id);
    setQuery(""); setSearchOpen(false);
  };

  /* ---------- selected-node panel data ---------- */
  const selNode = selected ? byIdRef.current.get(selected) ?? null : null;
  const selEdges = useMemo(() => {
    if (!selNode) return [] as GEdge[];
    return edgesRef.current
      .filter((e) => e.src === selNode.id || e.dst === selNode.id)
      .sort((a, b) => (b.weight ?? 0.5) - (a.weight ?? 0.5));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selNode, graph]);

  const typeCounts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const n of graph?.nodes ?? []) c[n.type] = (c[n.type] ?? 0) + 1;
    return c;
  }, [graph]);

  const hoverNode = hover ? byIdRef.current.get(hover) : null;

  return (
    <div ref={wrapRef} className="gf-wrap">
      <canvas
        ref={canvasRef}
        className="gf-canvas"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onPointerLeave={() => { setHover(null); mouseRef.current = null; }}
        onDoubleClick={onDoubleClick}
        style={{ cursor: gestureRef.current?.mode === "pan" ? "grabbing" : hover ? "pointer" : "grab" }}
      />

      {/* search */}
      <div className="gf-search">
        <input
          ref={searchRef}
          value={query}
          placeholder="Search nodes…  ( / )"
          onChange={(e) => { setQuery(e.target.value); setSearchOpen(true); setSearchIdx(0); }}
          onFocus={() => setSearchOpen(true)}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") { e.preventDefault(); setSearchIdx((i) => Math.min(i + 1, results.length - 1)); }
            else if (e.key === "ArrowUp") { e.preventDefault(); setSearchIdx((i) => Math.max(i - 1, 0)); }
            else if (e.key === "Enter" && results[searchIdx]) chooseResult(results[searchIdx]);
            else if (e.key === "Escape") { setQuery(""); setSearchOpen(false); (e.target as HTMLInputElement).blur(); }
          }}
        />
        {searchOpen && results.length > 0 && (
          <div className="gf-results">
            {results.map((n, i) => (
              <button
                key={n.id}
                className={i === searchIdx ? "on" : ""}
                onMouseEnter={() => setSearchIdx(i)}
                onClick={() => chooseResult(n)}
              >
                <i style={{ background: TYPE_COLOR[n.type] ?? "#888" }} />
                <span>{n.label}</span>
                <em>{n.symbol ? `${n.symbol} · ` : ""}{n.type}</em>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* zoom / view controls */}
      <div className="gf-controls">
        <button title="zoom in" onClick={() => zoomBy(1.45)}>+</button>
        <button title="zoom out" onClick={() => zoomBy(1 / 1.45)}>−</button>
        <button title="fit everything" onClick={() => fitView()}>⛶</button>
        {rotated && <button title="reset rotation (shift-drag rotates)" onClick={() => {
          animRef.current = { t0: performance.now(), from: { ...camRef.current }, to: { ...camRef.current, theta: 0 } };
          setRotated(false);
        }}>⇧N</button>}
      </div>

      {/* type filter chips */}
      <div className="gf-chips">
        {Object.keys(TYPE_COLOR).filter((t) => t !== "sector" && (typeCounts[t] ?? 0) > 0).map((t) => {
          const off = hiddenTypes.has(t);
          return (
            <button
              key={t}
              className={`gf-chip ${off ? "off" : ""}`}
              onClick={() => setHiddenTypes((s) => {
                const next = new Set(s);
                const targets = t === "theme" ? ["theme", "sector"] : [t];
                for (const tt of targets) { if (next.has(tt)) next.delete(tt); else next.add(tt); }
                return next;
              })}
              title={off ? `show ${t}s` : `hide ${t}s`}
            >
              <i style={{ background: TYPE_COLOR[t] }} />
              {t} <em>{(typeCounts[t] ?? 0) + (t === "theme" ? typeCounts["sector"] ?? 0 : 0)}</em>
            </button>
          );
        })}
        <span className="gf-hint">drag node to move · scroll to zoom · double-click to dive · shift-drag rotates</span>
      </div>

      {/* hover tooltip */}
      {hoverNode && hover !== selected && (
        <div ref={tipRef} className="gf-tip">
          <b>{hoverNode.label}</b>
          <span>{hoverNode.type}{hoverNode.symbol ? ` · ${hoverNode.symbol}` : ""}</span>
          <span>
            charge {(impacts[hoverNode.id] ?? 0) >= 0 ? "+" : ""}{(impacts[hoverNode.id] ?? 0).toFixed(2)}
            {" · "}influence {((centrality[hoverNode.id] ?? 0) * 100).toFixed(0)}
            {" · "}{(adjRef.current.get(hoverNode.id)?.size ?? 0)} links
          </span>
        </div>
      )}

      {/* selected node panel */}
      {selNode && (
        <div className="gf-panel">
          <div className="gf-panel-head">
            <i style={{ background: TYPE_COLOR[selNode.type] ?? "#888" }} />
            <b>{selNode.label}</b>
            <button className="gf-x" onClick={() => onSelect(null)} title="close">×</button>
          </div>
          <div className="gf-panel-sub">
            {selNode.type}{selNode.symbol ? ` · ${selNode.symbol}` : ""}{selNode.market ? ` · ${selNode.market}` : ""}
          </div>
          <div className="gf-panel-stats">
            <span>
              charge{" "}
              <b style={{ color: (impacts[selNode.id] ?? 0) >= 0 ? "var(--pos)" : "var(--neg)" }}>
                {(impacts[selNode.id] ?? 0) >= 0 ? "+" : ""}{(impacts[selNode.id] ?? 0).toFixed(3)}
              </b>
            </span>
            <span>influence <b>{((centrality[selNode.id] ?? 0) * 100).toFixed(0)}/100</b></span>
            <span>links <b>{selEdges.length}</b></span>
          </div>
          {selNode.equilibrium && <div className="gf-panel-eq">stable point: {selNode.equilibrium}</div>}
          <div className="gf-panel-edges">
            {selEdges.map((e, i) => {
              const otherId = e.src === selNode.id ? e.dst : e.src;
              const other = byIdRef.current.get(otherId);
              return (
                <button key={i} onClick={() => { onSelect(otherId); flyTo(otherId); }}>
                  <span className="dir">{e.src === selNode.id ? "→" : "←"}</span>
                  <i style={{ background: TYPE_COLOR[other?.type ?? ""] ?? "#888" }} />
                  <span className="who">{other?.label ?? otherId}</span>
                  <em>
                    {e.type}{(e.sign ?? 1) < 0 ? " · inverse" : ""} · w{(e.weight ?? 0.5).toFixed(1)}
                    {e.provenance === "llm" ? " · llm" : ""}
                  </em>
                  {e.note && <span className="note">{e.note}</span>}
                </button>
              );
            })}
          </div>
          {fieldTs && <div className="gf-panel-ts">field updated {fieldTs.slice(0, 16)}Z</div>}
        </div>
      )}
    </div>
  );
}
