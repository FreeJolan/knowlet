/**
 * Phase 1 C slice 3 — Graph focus mode (Cmd+Shift+G).
 *
 * Per Q1 of the design spec:
 *   - <300 nodes: full graph
 *   - ≥300: ego 2-hop default + "expand to full" button
 *
 * Per Q2: orphans (deg=0) are NOT shoved into the force layout — they
 * render in a separate grid panel on the right.
 *
 * Per Q3: force tuning lives in GraphCanvas; this surface just wraps
 * with chrome (header, search, info rail, zoom controls — most of
 * those are placeholder hooks for follow-up polish).
 */

import { useQuery } from "@tanstack/react-query";
import { Network, Search, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { getGraph } from "@/api/client";
import type { GraphNodeRow, GraphPayload } from "@/api/types";
import { QK } from "@/lib/queryClient";

import { GraphCanvas } from "./GraphCanvas";
import { GraphTooltip } from "./GraphTooltip";
import { egoSubgraph, splitOrphans } from "./graphData";

const FULL_GRAPH_NODE_THRESHOLD = 300;

interface Props {
  open: boolean;
  /** Center for the ego scope when ≥threshold; null = full vault. */
  noteId: string | null;
  onClose: () => void;
  onOpenNote: (noteId: string) => void;
}

export function GraphFocusMode({ open, noteId, onClose, onOpenNote }: Props) {
  const { t } = useTranslation();

  // Esc closes (in addition to the X button).
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const graphQuery = useQuery<GraphPayload>({
    queryKey: QK.graph,
    queryFn: getGraph,
    staleTime: 10_000,
    enabled: open,
  });

  // Per Q1: auto-pick by vault size.
  const [expandedToFull, setExpandedToFull] = useState(false);
  const useFull = !graphQuery.data
    ? true
    : graphQuery.data.nodes.length < FULL_GRAPH_NODE_THRESHOLD || expandedToFull;

  const visible = useMemo(() => {
    if (!graphQuery.data) return null;
    if (useFull) return splitOrphans(graphQuery.data);
    if (!noteId) {
      // No center note + ≥threshold: still render full but capped via
      // dropping orphans (keeps the canvas cleaner).
      return splitOrphans(graphQuery.data);
    }
    const ego = egoSubgraph(graphQuery.data, noteId, 2);
    return splitOrphans({ nodes: ego.nodes, edges: ego.edges });
  }, [graphQuery.data, useFull, noteId]);

  const [searchQuery, setSearchQuery] = useState("");
  const [hovered, setHovered] = useState<GraphNodeRow | null>(null);
  const [cursor, setCursor] = useState<{ x: number; y: number }>({ x: 0, y: 0 });
  const canvasContainerRef = useRef<HTMLDivElement | null>(null);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex flex-col"
      style={{
        background: "var(--bg, #f4f0e8)",
      }}
      data-testid="graph-focus-mode"
    >
      {/* Header */}
      <header
        className="flex shrink-0 items-center gap-3 border-b px-4 py-2"
        style={{ borderColor: "var(--line)", background: "var(--panel)" }}
      >
        <span
          className="inline-flex items-center gap-1.5 rounded px-2 py-0.5 text-[11px] font-medium"
          style={{
            background: "var(--accent-soft, rgba(91, 122, 156, 0.18))",
            color: "var(--accent-2, #34495e)",
          }}
        >
          <Network size={11} />
          {useFull ? t("graph.focus.titleFull") : t("graph.focus.titleEgo")}
        </span>
        <span
          className="font-serif text-sm"
          style={{ color: "var(--ink)", fontWeight: 500 }}
        >
          {graphQuery.data
            ? t("graph.focus.summary", {
                notes: graphQuery.data.nodes.length,
                edges: graphQuery.data.edges.length,
              })
            : "…"}
        </span>
        <span style={{ flex: 1 }} />
        {/* Search box */}
        <div
          className="flex h-7 items-center gap-1.5 rounded border px-2"
          style={{
            borderColor: searchQuery
              ? "var(--accent, #5b7a9c)"
              : "var(--line)",
            background: "var(--card, #fbf8f1)",
            width: 220,
          }}
        >
          <Search size={11} style={{ color: "var(--ink-mute)" }} />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder={t("graph.focus.searchPlaceholder") as string}
            data-testid="graph-search-input"
            className="flex-1 bg-transparent text-xs outline-none"
            style={{ color: "var(--ink)" }}
          />
        </div>
        {/* Switch ego ↔ full when vault is large */}
        {graphQuery.data &&
          graphQuery.data.nodes.length >= FULL_GRAPH_NODE_THRESHOLD && (
            <button
              type="button"
              onClick={() => setExpandedToFull((v) => !v)}
              data-testid="graph-toggle-full"
              className="rounded border px-2 py-0.5 text-[11px] transition-colors hover:bg-accent/30"
              style={{ borderColor: "var(--line)", color: "var(--ink-soft)" }}
            >
              {expandedToFull
                ? t("graph.focus.collapseToEgo")
                : t("graph.focus.expandToFull")}
            </button>
          )}
        <span
          className="font-mono text-[10.5px]"
          style={{ color: "var(--ink-mute)" }}
        >
          ⌘⇧G
        </span>
        <button
          type="button"
          onClick={onClose}
          aria-label={t("graph.focus.close")}
          data-testid="graph-focus-close"
          className="flex size-7 items-center justify-center rounded transition-colors hover:bg-accent/30"
          style={{ color: "var(--ink-mute)" }}
        >
          <X size={14} />
        </button>
      </header>

      {/* Body */}
      <div className="flex min-h-0 flex-1">
        {/* Main canvas */}
        <div
          ref={canvasContainerRef}
          className="relative flex-1"
          style={{ background: "var(--bg)" }}
          onMouseMove={(e) => {
            const rect = e.currentTarget.getBoundingClientRect();
            setCursor({ x: e.clientX - rect.left, y: e.clientY - rect.top });
          }}
          onMouseLeave={() => setHovered(null)}
        >
          {graphQuery.isLoading && (
            <div
              className="absolute inset-0 flex items-center justify-center text-xs"
              style={{ color: "var(--ink-mute)" }}
            >
              {t("graph.focus.loading")}
            </div>
          )}
          {visible && visible.connected.nodes.length === 0 && (
            <EmptyState />
          )}
          {visible && visible.connected.nodes.length > 0 && (
            <CanvasFiller>
              {(w, h) => (
                <GraphCanvas
                  nodes={visible.connected.nodes}
                  edges={visible.connected.edges}
                  width={w}
                  height={h}
                  centerId={noteId}
                  searchQuery={searchQuery}
                  onNodeClick={(id) => {
                    onOpenNote(id);
                    onClose();
                  }}
                  onNodeHover={setHovered}
                />
              )}
            </CanvasFiller>
          )}
          {hovered && canvasContainerRef.current && (
            <GraphTooltip
              node={hovered}
              cursor={cursor}
              paneW={canvasContainerRef.current.clientWidth}
              paneH={canvasContainerRef.current.clientHeight}
              currentId={noteId}
            />
          )}
        </div>

        {/* Right info rail — degree-sorted list (a11y fallback +
         *  power-user list view per the design spec). */}
        {visible && (
          <aside
            className="flex w-60 flex-col"
            style={{
              background: "var(--panel)",
              borderLeft: "1px solid var(--line)",
            }}
          >
            <div
              className="px-3 py-2 font-mono text-[10.5px] tracking-wider"
              style={{
                color: "var(--ink-mute)",
                borderBottom: "1px solid var(--line)",
                background: "var(--panel-2, #e7e0d0)",
              }}
            >
              {t("graph.focus.byDegree")}
            </div>
            <div className="flex-1 overflow-y-auto" data-testid="graph-degree-list">
              {[...visible.connected.nodes]
                .sort(
                  (a, b) =>
                    b.in_degree + b.out_degree - (a.in_degree + a.out_degree),
                )
                .slice(0, 14)
                .map((n) => (
                  <button
                    key={n.id}
                    type="button"
                    onClick={() => {
                      onOpenNote(n.id);
                      onClose();
                    }}
                    className="flex w-full items-center gap-2 px-3 py-1 text-left transition-colors hover:bg-accent/20"
                    style={{ color: "var(--ink)" }}
                    data-testid="graph-degree-row"
                  >
                    <span
                      className="w-6 text-right font-mono text-[10px]"
                      style={{ color: "var(--ink-mute)" }}
                    >
                      {n.in_degree + n.out_degree}
                    </span>
                    <span
                      className="flex-1 truncate text-[11.5px]"
                      style={{ minWidth: 0 }}
                    >
                      {n.title}
                    </span>
                  </button>
                ))}
            </div>
            {visible.orphans.length > 0 && (
              <div
                className="border-t px-3 py-2 text-[11px]"
                style={{
                  borderColor: "var(--line)",
                  background: "var(--panel-2, #e7e0d0)",
                  color: "var(--ink-soft)",
                }}
              >
                <div className="font-mono text-[10px] uppercase tracking-wider" style={{ color: "var(--ink-mute)" }}>
                  {t("graph.focus.orphansTitle", { count: visible.orphans.length })}
                </div>
                <div className="mt-1 line-clamp-3 text-[10.5px]" style={{ color: "var(--ink-mute)" }}>
                  {t("graph.focus.orphansHint")}
                </div>
              </div>
            )}
          </aside>
        )}
      </div>
    </div>
  );
}

interface FillerProps {
  children: (width: number, height: number) => React.ReactNode;
}
function CanvasFiller({ children }: FillerProps) {
  const [size, setSize] = useState({ w: 800, h: 600 });
  return (
    <div
      ref={(el) => {
        if (!el) return;
        if (size.w === el.clientWidth && size.h === el.clientHeight) return;
        queueMicrotask(() => setSize({ w: el.clientWidth, h: el.clientHeight }));
      }}
      className="absolute inset-0"
    >
      {children(size.w, size.h)}
    </div>
  );
}


function EmptyState() {
  const { t } = useTranslation();
  return (
    <div className="absolute inset-0 flex items-center justify-center px-12">
      <div className="max-w-md text-center">
        <svg width="180" height="120" viewBox="0 0 180 120" className="mx-auto mb-4">
          <defs>
            <marker
              id="ghost-arrow"
              viewBox="0 0 10 10"
              refX="8"
              refY="5"
              markerWidth="5"
              markerHeight="5"
              orient="auto"
            >
              <path d="M 0 0 L 10 5 L 0 10 Z" fill="rgba(142, 133, 122, 0.7)" />
            </marker>
          </defs>
          <circle cx="40" cy="40" r="14" fill="var(--card, #fbf8f1)" stroke="rgba(142, 133, 122, 0.7)" strokeWidth="1.5" />
          <circle cx="140" cy="40" r="11" fill="var(--card, #fbf8f1)" stroke="rgba(142, 133, 122, 0.7)" strokeWidth="1.5" />
          <circle cx="90" cy="90" r="13" fill="var(--card, #fbf8f1)" stroke="rgba(142, 133, 122, 0.7)" strokeWidth="1.5" />
          <line x1="54" y1="42" x2="126" y2="42" stroke="rgba(142, 133, 122, 0.7)" strokeWidth="1" strokeDasharray="3 4" markerEnd="url(#ghost-arrow)" />
          <line x1="48" y1="52" x2="80" y2="80" stroke="rgba(142, 133, 122, 0.7)" strokeWidth="1" strokeDasharray="3 4" markerEnd="url(#ghost-arrow)" />
        </svg>
        <h2
          className="font-serif text-2xl font-semibold"
          style={{ color: "var(--ink)" }}
        >
          {t("graph.focus.emptyTitle")}
        </h2>
        <p
          className="mx-auto mt-3 max-w-sm text-sm leading-relaxed"
          style={{ color: "var(--ink-soft)" }}
        >
          {t("graph.focus.emptyBody")}
        </p>
      </div>
    </div>
  );
}
