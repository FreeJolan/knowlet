/**
 * Phase 1 C slice 3 — cursor-tethered hover tooltip.
 *
 * Mirrors the design's `NodeTooltip` positioning: anchor at
 * `cursor + (16, 12)`; flip to the left or above if the tooltip
 * would overflow the container's right or bottom edge.
 */

import type { GraphNodeRow } from "@/api/types";

const TOOLTIP_W = 240;
const TOOLTIP_H = 72;
const EDGE_PAD = 8;

interface Props {
  node: GraphNodeRow;
  /** Cursor position in container-local coords (`onMouseMove`). */
  cursor: { x: number; y: number };
  /** Container width / height for edge-flip math. */
  paneW: number;
  paneH: number;
  /** When the hovered node is the current note, mark with `current`. */
  currentId: string | null;
}

export function GraphTooltip({ node, cursor, paneW, paneH, currentId }: Props) {
  let left = cursor.x + 16;
  let top = cursor.y + 12;
  if (left + TOOLTIP_W > paneW - EDGE_PAD) left = cursor.x - TOOLTIP_W - 16;
  if (top + TOOLTIP_H > paneH - EDGE_PAD) top = cursor.y - TOOLTIP_H - 16;
  if (left < EDGE_PAD) left = EDGE_PAD;
  if (top < EDGE_PAD) top = EDGE_PAD;
  const isCurrent = node.id === currentId;
  return (
    <div
      className="pointer-events-none absolute rounded border px-3 py-2 shadow-md"
      style={{
        left,
        top,
        width: TOOLTIP_W,
        // Semi-transparent + backdrop blur so neighbor nodes/edges
        // behind the tooltip stay legible. Solid card bg blocked too
        // much of the surrounding graph, especially in dense clusters.
        background: "rgba(251, 248, 241, 0.86)",
        backdropFilter: "blur(3px)",
        WebkitBackdropFilter: "blur(3px)",
        borderColor: "var(--line)",
        color: "var(--ink)",
        zIndex: 10,
      }}
      data-testid="graph-tooltip"
    >
      <div
        className="text-[12.5px] font-medium leading-tight"
        style={{ fontFamily: "var(--font-serif, Source Serif 4, Georgia, serif)" }}
      >
        {node.title}
      </div>
      <div
        className="mt-1 flex items-center gap-1.5 font-mono text-[10px]"
        style={{ color: "var(--ink-mute)" }}
      >
        {node.folder ? <span>{node.folder}</span> : <span>(root)</span>}
        <span style={{ color: "var(--ink-faint, #8e857a)" }}>·</span>
        <span>↘ {node.in_degree + node.out_degree}</span>
        {isCurrent && (
          <>
            <span style={{ color: "var(--ink-faint, #8e857a)" }}>·</span>
            <span style={{ color: "var(--accent-2, #34495e)" }}>current</span>
          </>
        )}
      </div>
    </div>
  );
}
