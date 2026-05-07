/**
 * Phase 1 C slice 3 — Graph rail-tab panel (ego 1-hop).
 *
 * Per Q1 of the design spec, the rail-tab variant ALWAYS shows ego
 * 1-hop around the current note. It's a navigation aid, not a survey.
 * The full-vault view is the focus mode (Cmd+Shift+G).
 */

import { useQuery } from "@tanstack/react-query";
import { Compass, Maximize2 } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { getGraph } from "@/api/client";
import type { GraphNodeRow, GraphPayload } from "@/api/types";
import { QK } from "@/lib/queryClient";

import { GraphCanvas } from "./GraphCanvas";
import { egoSubgraph } from "./graphData";

interface Props {
  noteId: string | null;
  onOpenNote: (noteId: string) => void;
  /** Click "expand" / Cmd+Shift+G to enter focus mode. */
  onEnterFocus: () => void;
}

export function GraphPanel({ noteId, onOpenNote, onEnterFocus }: Props) {
  const { t } = useTranslation();

  const graphQuery = useQuery<GraphPayload>({
    queryKey: QK.graph,
    queryFn: getGraph,
    staleTime: 10_000,
  });

  const ego = useMemo(() => {
    if (!graphQuery.data || !noteId) return null;
    return egoSubgraph(graphQuery.data, noteId, 1);
  }, [graphQuery.data, noteId]);

  const [hovered, setHovered] = useState<GraphNodeRow | null>(null);

  // -------------------------------------------------- empty / loading

  if (!noteId) {
    return (
      <div
        className="flex h-full min-h-0 flex-col items-center justify-center px-4 py-8 text-center text-xs"
        style={{ color: "var(--ink-mute)" }}
      >
        {t("rail.graph.noNote")}
      </div>
    );
  }
  if (graphQuery.isLoading || !graphQuery.data) {
    return (
      <div className="px-3 py-3 text-xs" style={{ color: "var(--ink-mute)" }}>
        {t("rail.graph.loading")}
      </div>
    );
  }
  if (graphQuery.isError) {
    return (
      <div className="px-3 py-3 text-xs" style={{ color: "var(--ink-mute)" }}>
        {t("rail.graph.loadFailed", {
          error: (graphQuery.error as { detail?: string })?.detail ?? "unknown",
        })}
      </div>
    );
  }
  if (!ego || ego.nodes.length <= 1) {
    return (
      <div
        className="flex h-full min-h-0 flex-col items-center justify-center px-4 py-8 text-center"
        style={{ color: "var(--ink-mute)" }}
      >
        <div className="mb-2 text-xs">{t("rail.graph.empty")}</div>
        <div
          className="font-mono text-[10.5px]"
          style={{ color: "var(--ink-faint, #8e857a)" }}
        >
          {t("rail.graph.emptyHint")}
        </div>
      </div>
    );
  }

  const total = graphQuery.data.nodes.length;

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* Header */}
      <div
        className="flex shrink-0 items-center gap-2 px-3 py-1.5"
        style={{
          borderBottom: "1px solid var(--line-soft, #e2dac9)",
          background: "var(--panel)",
        }}
      >
        <Compass size={11} style={{ color: "var(--ink-mute)" }} />
        <span className="text-[11.5px]" style={{ color: "var(--ink-soft)" }}>
          {t("rail.graph.subtitle")}
        </span>
        <span
          className="font-mono text-[10.5px]"
          style={{ color: "var(--ink-mute)", marginLeft: "auto" }}
        >
          {ego.nodes.length} / {total}
        </span>
      </div>

      {/* Canvas */}
      <div className="relative min-h-0 flex-1" style={{ background: "var(--bg)" }}>
        <CanvasFiller>
          {(w, h) => (
            <GraphCanvas
              nodes={ego.nodes}
              edges={ego.edges}
              width={w}
              height={h}
              centerId={noteId}
              onNodeClick={onOpenNote}
              onNodeHover={setHovered}
            />
          )}
        </CanvasFiller>
        {hovered && (
          <NodeTooltip
            node={hovered}
            currentId={noteId}
          />
        )}
        <div
          className="pointer-events-none absolute bottom-2 left-3 flex gap-1.5 font-mono text-[10px]"
          style={{ color: "var(--ink-mute)" }}
        >
          <span>{t("rail.graph.hintScroll")}</span>
          <span style={{ color: "var(--ink-faint, #8e857a)" }}>·</span>
          <span>{t("rail.graph.hintDrag")}</span>
        </div>
      </div>

      {/* Footer */}
      <div
        className="flex shrink-0 items-center gap-3 px-3 py-1.5"
        style={{
          borderTop: "1px solid var(--line)",
          background: "var(--panel-2, #e7e0d0)",
          color: "var(--ink-soft)",
        }}
      >
        <span className="text-[11px]">
          <strong className="font-mono" style={{ color: "var(--ink)" }}>
            {ego.edges.filter((e) => e.source === noteId).length}
          </strong>{" "}
          {t("rail.graph.outbound")}
        </span>
        <span style={{ color: "var(--ink-faint, #8e857a)" }}>·</span>
        <span className="text-[11px]">
          <strong className="font-mono" style={{ color: "var(--ink)" }}>
            {ego.edges.filter((e) => e.target === noteId).length}
          </strong>{" "}
          {t("rail.graph.inbound")}
        </span>
        <span style={{ flex: 1 }} />
        <button
          type="button"
          onClick={onEnterFocus}
          data-testid="graph-enter-focus"
          className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10.5px] transition-colors hover:bg-accent/30"
          style={{ color: "var(--ink-soft)" }}
        >
          <Maximize2 size={9} />
          <span>{t("rail.graph.fullScreen")}</span>
        </button>
      </div>
    </div>
  );
}

interface FillerProps {
  children: (width: number, height: number) => React.ReactNode;
}

/** Measure container size + render children with explicit w/h —
 *  react-force-graph-2d requires concrete pixel dimensions. */
function CanvasFiller({ children }: FillerProps) {
  const [size, setSize] = useState({ w: 360, h: 360 });
  return (
    <div
      ref={(el) => {
        if (!el) return;
        if (size.w === el.clientWidth && size.h === el.clientHeight) return;
        // Use a microtask to avoid layout thrash.
        queueMicrotask(() => {
          setSize({ w: el.clientWidth, h: el.clientHeight });
        });
      }}
      className="absolute inset-0"
    >
      {children(size.w, size.h)}
    </div>
  );
}

interface TooltipProps {
  node: GraphNodeRow;
  currentId: string;
}

function NodeTooltip({ node, currentId }: TooltipProps) {
  const isCurrent = node.id === currentId;
  return (
    <div
      className="pointer-events-none absolute right-3 top-3 max-w-[260px] rounded border px-3 py-2 shadow-md"
      style={{
        background: "var(--card, #fbf8f1)",
        borderColor: "var(--line)",
        color: "var(--ink)",
      }}
    >
      <div
        className="text-[12px] font-medium"
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
