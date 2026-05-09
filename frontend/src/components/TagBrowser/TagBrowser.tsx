/**
 * Phase 1 C slice 2 (+ polish D) — Tag browser, peer of FileTree on the
 * left rail.
 *
 * File-tree style:
 *   - `/` in tag names is treated as path separator (Bear / Obsidian
 *     convention). `#design/ui` becomes node `design > ui`.
 *   - Tag nodes are expandable; children are sub-tag nodes (more `/`
 *     levels) followed by the notes carrying that exact tag.
 *   - Click a note → opens it in the editor.
 *   - Click a tag → toggles expand/collapse (same as folder in
 *     FileTree).
 *
 * Per ADR-0013 §3 Layer B — no taxonomy enforcement. The hierarchy is
 * derived from what the user wrote; it isn't a separate registry.
 */

import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, FileText, Hash } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Tree,
  type NodeRendererProps,
  type TreeApi,
} from "react-arborist";

import { listTagsWithNotes } from "@/api/client";
import type { TagWithNotes } from "@/api/types";
import { QK } from "@/lib/queryClient";

import { buildTagTree, type TagTreeNode } from "./tagTree";

type Kind = "tag" | "note";

interface RowData {
  id: string;
  /** Tag node label (last segment) or note title. */
  name: string;
  kind: Kind;
  /** Tag-only: own count for the chip. */
  ownCount?: number;
  /** Tag-only: subtree count for the chip. */
  subtreeCount?: number;
  /** Tag-only: synthetic parents have no notes of their own. */
  synthetic?: boolean;
  /** Tag-only: full path used for filter/expand-state stability. */
  fullTag?: string;
  /** Note-only: backend note id for `onSelectNote`. */
  noteId?: string;
  children?: RowData[];
}

function toArborist(nodes: TagTreeNode[]): RowData[] {
  return nodes.map((n) => {
    const tagRow: RowData = {
      id: `tag:${n.fullTag}`,
      name: n.name,
      kind: "tag",
      ownCount: n.ownCount,
      subtreeCount: n.subtreeCount,
      synthetic: n.synthetic,
      fullTag: n.fullTag,
      children: [
        ...toArborist(n.children),
        ...n.ownNotes.map((note) => ({
          id: `tag:${n.fullTag}|note:${note.id}`,
          name: note.title || "(untitled)",
          kind: "note" as const,
          noteId: note.id,
        })),
      ],
    };
    return tagRow;
  });
}

interface Props {
  onSelectNote: (id: string) => void;
  /** When AppShell is asked to open a specific tag (e.g. via a #tag
   *  click in preview), the host sets this and TagBrowser drills in. */
  pendingTag?: string | null;
  onPendingTagConsumed?: () => void;
}

export function TagBrowser({
  onSelectNote,
  pendingTag,
  onPendingTagConsumed,
}: Props) {
  const { t } = useTranslation();

  const tagsQuery = useQuery<TagWithNotes[]>({
    queryKey: QK.tagsWithNotes,
    queryFn: listTagsWithNotes,
    staleTime: 10_000,
  });

  const data = useMemo<RowData[]>(() => {
    if (!tagsQuery.data) return [];
    return toArborist(buildTagTree(tagsQuery.data));
  }, [tagsQuery.data]);

  const treeRef = useRef<TreeApi<RowData> | null>(null);
  // Track container size so react-arborist (which is virtualized) gets
  // explicit width / height. The browser-default `100%` doesn't satisfy
  // its sizing API.
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [size, setSize] = useState({ width: 240, height: 600 });

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => {
      setSize({ width: el.clientWidth, height: el.clientHeight });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Honor pendingTag: open the tag (and its parents on the path), select
  // it, scroll into view. We need to expand each path segment first
  // because arborist won't auto-open ancestors.
  useEffect(() => {
    if (!pendingTag || !treeRef.current) return;
    const segments = pendingTag.split("/").filter(Boolean);
    if (segments.length === 0) return;
    const tree = treeRef.current;
    let runningPath = "";
    for (const seg of segments) {
      runningPath = runningPath ? `${runningPath}/${seg}` : seg;
      const id = `tag:${runningPath}`;
      tree.open(id);
    }
    const finalId = `tag:${segments.join("/")}`;
    tree.select(finalId);
    onPendingTagConsumed?.();
  }, [pendingTag, data, onPendingTagConsumed]);

  // ----------------------------------------------------------- empty / errors

  // 2026-05-10: shared header bar — keeps Tags tab visually aligned
  // with Notes / Templates tabs (label at top-left, blank top-right
  // since tags can't be created standalone).
  const headerBar = (
    <div
      className="flex shrink-0 items-center justify-between border-b py-1.5 pr-1 pl-3"
      style={{ borderColor: "var(--line)" }}
    >
      <span
        data-testid="tag-browser-heading"
        className="text-[11px] font-semibold uppercase tracking-wide text-foreground/80"
      >
        {t("tree.tabTags")}
      </span>
    </div>
  );

  if (tagsQuery.isLoading) {
    return (
      <div className="flex h-full flex-col">
        {headerBar}
        <div
          className="px-3 py-3 text-xs"
          style={{ color: "var(--ink-mute)" }}
        >
          {t("tags.loading")}
        </div>
      </div>
    );
  }
  if (tagsQuery.isError) {
    return (
      <div className="flex h-full flex-col">
        {headerBar}
        <div
          className="px-3 py-3 text-xs"
          style={{ color: "var(--ink-mute)" }}
        >
          {t("tags.loadFailed", {
            error: (tagsQuery.error as { detail?: string })?.detail ?? "unknown",
          })}
        </div>
      </div>
    );
  }
  if (data.length === 0) {
    return (
      <div className="flex h-full flex-col">
        {headerBar}
        <div
          className="px-3 py-4 text-xs"
          style={{ color: "var(--ink-mute)" }}
        >
          {t("tags.empty")}
        </div>
      </div>
    );
  }

  // ------------------------------------------------------------------- render

  return (
    <div ref={containerRef} className="flex h-full min-h-0 flex-col">
      {headerBar}
      <Tree<RowData>
        ref={treeRef}
        data={data}
        openByDefault={false}
        rowHeight={28}
        width={size.width}
        height={size.height}
        // arborist's drag-drop is irrelevant for this view; disable.
        disableDrag
        disableDrop
        onActivate={(node) => {
          if (node.data.kind === "note" && node.data.noteId) {
            onSelectNote(node.data.noteId);
          }
        }}
      >
        {Row}
      </Tree>
    </div>
  );
}

function Row({ node, style, dragHandle }: NodeRendererProps<RowData>) {
  const isTag = node.data.kind === "tag";
  const handleClick = (e: React.MouseEvent) => {
    if (isTag) {
      // Expand/collapse on click anywhere on the tag row.
      e.preventDefault();
      node.toggle();
    } else {
      // Note rows: arborist's onActivate path runs on Enter / dblclick;
      // single-click should also open. Activate explicitly.
      node.activate();
    }
  };
  return (
    <div
      ref={dragHandle}
      style={style}
      onClick={handleClick}
      data-testid={isTag ? "tag-row" : "tag-note-row"}
      data-tag={isTag ? node.data.fullTag : undefined}
      data-note-id={isTag ? undefined : node.data.noteId}
      data-synthetic={node.data.synthetic ? "1" : undefined}
      // 2026-05-10: outer keeps the left-rail's pl-1 pr-3 gutter so
      // the inner rounded highlight has breathing room from the
      // panel edge, mirroring FileTree's two-layer pattern. Inner
      // div carries the actual hover / selection chrome.
      className="group flex h-full cursor-pointer items-center pr-3 pl-1 select-none"
    >
      <div
        className={[
          "flex h-[calc(100%-2px)] w-full items-center gap-1.5 rounded-md px-2 text-sm transition-colors",
          node.isSelected
            ? "bg-secondary text-foreground"
            : "hover:bg-muted/60",
        ].join(" ")}
      >
      {/* Indent caret only when there are children. Otherwise reserve
       *  the same width so labels align across rows. */}
      {isTag && node.children && node.children.length > 0 ? (
        node.isOpen ? (
          <ChevronDown size={11} style={{ color: "var(--ink-mute)" }} />
        ) : (
          <ChevronRight size={11} style={{ color: "var(--ink-mute)" }} />
        )
      ) : (
        <span style={{ display: "inline-block", width: 11 }} />
      )}
      {isTag ? (
        // 2026-05-10: always Hash icon. Was previously branching to
        // Folder for "tag with sub-tag children" but that suggested
        // tags-as-folders, which they aren't — the chevron already
        // expresses expandability, and treating leaf vs parent the
        // same makes the rail visually homogeneous.
        <Hash size={12} style={{ color: "var(--ink-soft)" }} />
      ) : (
        <FileText size={12} style={{ color: "var(--ink-soft)" }} />
      )}
      <span
        className="flex-1 truncate"
        style={{
          color: "var(--ink, #2a2823)",
          fontStyle: node.data.synthetic ? "italic" : undefined,
          opacity: node.data.synthetic ? 0.85 : 1,
        }}
      >
        {node.data.name}
      </span>
      {isTag && (
        <span
          className="font-mono text-[10.5px]"
          style={{ color: "var(--ink-mute)" }}
        >
          {/* Show the subtree total for nodes with children, own count
           *  otherwise. Visually consistent with how Obsidian's tag pane
           *  reads. */}
          {node.children && node.children.length > 0 && node.data.subtreeCount
            ? node.data.subtreeCount
            : node.data.ownCount}
        </span>
      )}
      </div>
    </div>
  );
}

