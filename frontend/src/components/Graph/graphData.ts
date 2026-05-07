/**
 * Phase 1 C slice 3 — graph filtering helpers.
 *
 * Backend `/api/graph` returns the full vault snapshot. The rail-tab
 * variant always shows ego (1-hop) around the current note; the
 * focus-mode variant shows the full graph at <300 nodes, ego (2-hop)
 * + "expand" button at ≥300 (Q1 of the design spec).
 *
 * Edges in the API are directed `[source → target]`. Ego scoping is
 * undirected — a node is "in ego" if it's reachable in either
 * direction from the center within `hops` steps.
 */

import type { GraphEdgeRow, GraphNodeRow, GraphPayload } from "@/api/types";

export interface FilteredGraph {
  nodes: GraphNodeRow[];
  edges: GraphEdgeRow[];
}

/**
 * Compute the ego subgraph around `centerId` within `hops`. Both source
 * and target nodes of any edge in the subset are included (so a node
 * one hop away brings its edges to the center, but its OTHER neighbors
 * aren't included unless within hops too). Self-edges are dropped
 * upstream by the backend already.
 */
export function egoSubgraph(
  payload: GraphPayload,
  centerId: string,
  hops: number,
): FilteredGraph {
  if (hops < 1) {
    const center = payload.nodes.find((n) => n.id === centerId);
    return { nodes: center ? [center] : [], edges: [] };
  }
  const adj = new Map<string, Set<string>>();
  for (const e of payload.edges) {
    if (!adj.has(e.source)) adj.set(e.source, new Set());
    adj.get(e.source)!.add(e.target);
    if (!adj.has(e.target)) adj.set(e.target, new Set());
    adj.get(e.target)!.add(e.source);
  }

  const visited = new Set<string>([centerId]);
  let frontier = new Set<string>([centerId]);
  for (let i = 0; i < hops; i++) {
    const next = new Set<string>();
    for (const id of frontier) {
      const ns = adj.get(id);
      if (!ns) continue;
      for (const n of ns) {
        if (!visited.has(n)) {
          visited.add(n);
          next.add(n);
        }
      }
    }
    if (next.size === 0) break;
    frontier = next;
  }

  const nodes = payload.nodes.filter((n) => visited.has(n.id));
  const edges = payload.edges.filter(
    (e) => visited.has(e.source) && visited.has(e.target),
  );
  return { nodes, edges };
}

/**
 * Drop orphan nodes (deg=0) from a snapshot. Used by the focus-mode
 * to render a separate "orphans pile" rather than letting them get
 * shoved to the corners of the force layout (per design spec frame 5).
 */
export function splitOrphans(payload: GraphPayload): {
  connected: FilteredGraph;
  orphans: GraphNodeRow[];
} {
  const orphans: GraphNodeRow[] = [];
  const connectedIds = new Set<string>();
  for (const n of payload.nodes) {
    if (n.in_degree === 0 && n.out_degree === 0) {
      orphans.push(n);
    } else {
      connectedIds.add(n.id);
    }
  }
  const nodes = payload.nodes.filter((n) => connectedIds.has(n.id));
  const edges = payload.edges.filter(
    (e) => connectedIds.has(e.source) && connectedIds.has(e.target),
  );
  return { connected: { nodes, edges }, orphans };
}

/**
 * Node radius per design spec Q2:
 *   `clamp(4, 4 + √(in+out_degree) × 2.4, 14)`
 */
export function nodeRadius(node: GraphNodeRow): number {
  const deg = node.in_degree + node.out_degree;
  const r = 4 + Math.sqrt(deg) * 2.4;
  return Math.max(4, Math.min(14, r));
}
