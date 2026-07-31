/* ---------- shared graph types (mirror the engine's JSON) ---------- */
export type GNode = {
  id: string; type: string; label: string; symbol?: string; market?: string;
  equilibrium?: string; state?: string; aliases?: string[];
};
export type GEdge = {
  src: string; dst: string; type: string; sign?: number; weight?: number;
  weight_rev?: number; confidence?: number; delay_days?: number;
  regime_gate?: { dial: string; lo?: number; hi?: number; outside?: string };
  provenance?: string; note?: string;
};
export type Graph = { nodes: GNode[]; edges: GEdge[] };
export type TraceStep = {
  from: string; to: string; edge_type: string; hop: number; contribution: number;
  anticipated?: boolean;
};
export type NodeEmotion = { fear?: number; greed?: number };
export type PendingEffect = {
  node: string; contribution: number; due?: string; via?: string; delay_days?: number;
};
