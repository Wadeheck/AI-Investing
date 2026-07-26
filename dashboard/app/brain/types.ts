/* ---------- shared graph types (mirror the engine's JSON) ---------- */
export type GNode = {
  id: string; type: string; label: string; symbol?: string; market?: string;
  equilibrium?: string; state?: string; aliases?: string[];
};
export type GEdge = {
  src: string; dst: string; type: string; sign?: number; weight?: number;
  provenance?: string; note?: string;
};
export type Graph = { nodes: GNode[]; edges: GEdge[] };
export type TraceStep = { from: string; to: string; edge_type: string; hop: number; contribution: number };
