/**
 * Phase 1 C slice 3 — shared force-directed canvas.
 *
 * Wraps `react-force-graph-2d` with the Q3 force tuning from the
 * design spec:
 *   - charge.strength(-180)
 *   - link.distance(d => 50 + min(deg_sum, 12) * 4)
 *   - center.strength(0.04)
 *   - x/y forces strength 0.02
 *   - alphaDecay 0.04, velocityDecay 0.5
 *
 * Both the rail-tab and focus-mode entries use this component; only
 * the framing differs.
 */

import {
  forceCenter,
  forceManyBody,
  forceX,
  forceY,
} from "d3-force";
import { useEffect, useMemo, useRef } from "react";
import ForceGraph2D, { type ForceGraphMethods } from "react-force-graph-2d";

import type { GraphEdgeRow, GraphNodeRow } from "@/api/types";

import { nodeRadius } from "./graphData";

interface CanvasNode extends GraphNodeRow {
  /** react-force-graph mutates these in place; mark optional. */
  x?: number;
  y?: number;
  vx?: number;
  vy?: number;
  /** When user drags a node, fix its position via fx/fy (session pin
   *  per Q3 of the design spec). */
  fx?: number;
  fy?: number;
}

interface CanvasLink {
  source: string | CanvasNode;
  target: string | CanvasNode;
}

interface Props {
  nodes: GraphNodeRow[];
  edges: GraphEdgeRow[];
  width: number;
  height: number;
  /** Note id of the "center" — gets accent fill; used for ego framing. */
  centerId: string | null;
  /** Brighten matching nodes; dim non-matching to 20% (per spec). */
  searchQuery?: string;
  onNodeClick?: (id: string) => void;
  /** Hover callback fires with the node row or null. */
  onNodeHover?: (node: GraphNodeRow | null) => void;
}

export function GraphCanvas({
  nodes,
  edges,
  width,
  height,
  centerId,
  searchQuery = "",
  onNodeClick,
  onNodeHover,
}: Props) {
  // react-force-graph-2d types its ref as MutableRefObject (no null);
  // we initialize to undefined and check before use.
  const fgRef = useRef<ForceGraphMethods<CanvasNode, CanvasLink> | undefined>(undefined);

  const data = useMemo(() => {
    // react-force-graph mutates the data; clone shallowly so adjacent
    // renders don't accumulate fx/fy from a previous filter.
    return {
      nodes: nodes.map((n) => ({ ...n }) as CanvasNode),
      links: edges.map((e) => ({ source: e.source, target: e.target }) as CanvasLink),
    };
  }, [nodes, edges]);

  // Apply the Q3 force tuning ONCE per dataset. Re-running on every
  // hover would interrupt the simulation.
  useEffect(() => {
    const fg = fgRef.current;
    if (!fg) return;
    const charge = forceManyBody().strength(-180);
    fg.d3Force("charge", charge);
    const linkForce = fg.d3Force("link") as unknown as {
      distance(fn: (l: CanvasLink) => number): unknown;
    } | undefined;
    if (linkForce && typeof linkForce.distance === "function") {
      linkForce.distance((l: CanvasLink) => {
        const src = typeof l.source === "string" ? null : l.source;
        const tgt = typeof l.target === "string" ? null : l.target;
        const sumDeg =
          ((src?.in_degree ?? 0) + (src?.out_degree ?? 0) +
            (tgt?.in_degree ?? 0) + (tgt?.out_degree ?? 0)) /
          2;
        return 50 + Math.min(sumDeg, 12) * 4;
      });
    }
    fg.d3Force("center", forceCenter(0, 0).strength(0.04));
    fg.d3Force("x", forceX(0).strength(0.02));
    fg.d3Force("y", forceY(0).strength(0.02));
    fg.d3ReheatSimulation();
  }, [data]);

  const matchesSearch = (node: CanvasNode): boolean => {
    if (!searchQuery.trim()) return true;
    const q = searchQuery.toLowerCase();
    return (
      node.title.toLowerCase().includes(q) ||
      node.folder.toLowerCase().includes(q)
    );
  };

  return (
    <ForceGraph2D
      ref={fgRef}
      graphData={data}
      width={width}
      height={height}
      backgroundColor="rgba(0,0,0,0)"
      cooldownTicks={120}
      d3AlphaDecay={0.04}
      d3VelocityDecay={0.5}
      // We paint links ourselves (line + arrow head with explicit
      // target-radius clipping) — the built-in arrow placement via
      // `linkDirectionalArrowRelPos` lands inconsistently for short
      // edges. Custom painter mirrors the static-SVG reference's
      // approach: line endpoint at `target_center - (radius + 4)px`,
      // arrow triangle at that endpoint pointing along the edge.
      linkCanvasObjectMode={() => "replace"}
      linkCanvasObject={(l, ctx) => {
        const link = l as CanvasLink;
        const src =
          typeof link.source === "string" ? null : (link.source as CanvasNode);
        const tgt =
          typeof link.target === "string" ? null : (link.target as CanvasNode);
        if (!src || !tgt || src.x == null || tgt.x == null) return;
        const sx = src.x;
        const sy = src.y ?? 0;
        const tx = tgt.x;
        const ty = tgt.y ?? 0;
        const dx = tx - sx;
        const dy = ty - sy;
        const dist = Math.hypot(dx, dy);
        if (dist <= 0.5) return;
        const targetR = nodeRadius(tgt);
        // Clip line at target boundary + 3 px so the arrow tip sits
        // visually adjacent to the target, never inside it. Source
        // side gets a small padding too so the line doesn't visually
        // overlap the source's circle outline.
        const sourceR = nodeRadius(src);
        const startPad = sourceR + 1;
        const endPad = targetR + 3;
        if (dist < startPad + endPad) return; // overlapping nodes — skip
        const ux = dx / dist;
        const uy = dy / dist;
        const x1 = sx + ux * startPad;
        const y1 = sy + uy * startPad;
        const x2 = tx - ux * endPad;
        const y2 = ty - uy * endPad;
        const dim =
          searchQuery.trim() &&
          !matchesSearch(src) &&
          !matchesSearch(tgt);
        ctx.save();
        ctx.lineWidth = 1.4;
        ctx.strokeStyle = dim
          ? "rgba(120, 110, 95, 0.18)"
          : "rgba(120, 110, 95, 0.85)";
        ctx.beginPath();
        ctx.moveTo(x1, y1);
        ctx.lineTo(x2, y2);
        ctx.stroke();
        // Arrow head — small filled triangle at (x2, y2).
        const arrowLen = 6;
        const arrowWide = 4;
        const ang = Math.atan2(uy, ux);
        ctx.fillStyle = dim
          ? "rgba(120, 110, 95, 0.25)"
          : "rgba(120, 110, 95, 0.9)";
        ctx.beginPath();
        ctx.moveTo(x2, y2);
        ctx.lineTo(
          x2 - arrowLen * Math.cos(ang) + arrowWide * Math.sin(ang),
          y2 - arrowLen * Math.sin(ang) - arrowWide * Math.cos(ang),
        );
        ctx.lineTo(
          x2 - arrowLen * Math.cos(ang) - arrowWide * Math.sin(ang),
          y2 - arrowLen * Math.sin(ang) + arrowWide * Math.cos(ang),
        );
        ctx.closePath();
        ctx.fill();
        ctx.restore();
      }}
      // Node renderer per Q2 (radius from degree, fill --card,
      // stroke --ink-mute or --accent for center). Custom canvas paint
      // because the lib's stock node is a small dot.
      nodeCanvasObjectMode={() => "replace"}
      nodeCanvasObject={(node, ctx, globalScale) => {
        const n = node as CanvasNode;
        const r = nodeRadius(n);
        const isCenter = n.id === centerId;
        const dim = !!searchQuery.trim() && !matchesSearch(n);
        ctx.save();
        ctx.globalAlpha = dim ? 0.2 : 1;
        ctx.beginPath();
        ctx.arc(n.x ?? 0, n.y ?? 0, r, 0, Math.PI * 2);
        ctx.fillStyle = isCenter
          ? "rgba(91, 122, 156, 0.22)" // --accent-soft
          : "rgba(251, 248, 241, 1)"; // --card
        ctx.fill();
        ctx.lineWidth = isCenter ? 2 : 1.5;
        ctx.strokeStyle = isCenter
          ? "rgba(91, 122, 156, 1)" // --accent
          : "rgba(120, 110, 95, 1)"; // --ink-mute
        ctx.stroke();
        // Labels: only for "hot" nodes (deg ≥ 4) OR matching when
        // search is active. The CENTER node is the user's current
        // open note — they already see its title in the editor; a
        // duplicate label on the graph is redundant. The accent fill
        // already says "this one is the center."
        const isHot = (n.in_degree + n.out_degree) >= 4;
        const showLabel =
          (!isCenter && isHot && globalScale >= 0.6) ||
          (!isCenter && !!searchQuery.trim() && matchesSearch(n));
        if (showLabel) {
          ctx.fillStyle = "rgba(42, 40, 35, 1)"; // --ink
          ctx.font = `500 11px 'Source Serif 4', Georgia, serif`;
          ctx.textAlign = "center";
          ctx.textBaseline = "bottom";
          const t =
            n.title.length > 16 ? n.title.slice(0, 14) + "…" : n.title;
          ctx.fillText(t, n.x ?? 0, (n.y ?? 0) - r - 4);
        }
        ctx.restore();
      }}
      nodePointerAreaPaint={(node, color, ctx) => {
        const n = node as CanvasNode;
        const r = nodeRadius(n);
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.arc(n.x ?? 0, n.y ?? 0, r + 4, 0, Math.PI * 2);
        ctx.fill();
      }}
      onNodeClick={(node) => {
        if (onNodeClick) onNodeClick((node as CanvasNode).id);
      }}
      onNodeHover={(node) => {
        if (onNodeHover) onNodeHover((node as CanvasNode | null) ?? null);
      }}
      onNodeDragEnd={(node) => {
        // Session-pin the node where the user dropped it (Q3 spec
        // for vaults 500-2000 — works fine at all sizes too).
        const n = node as CanvasNode;
        n.fx = n.x;
        n.fy = n.y;
      }}
    />
  );
}
