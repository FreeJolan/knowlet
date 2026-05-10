/**
 * Phase 1 D / D1 — tab strip above NoteView.
 *
 * Each tab shows the open note's title (truncated, tooltip carries
 * the full title) with a ✕ close button. Clicking a tab activates
 * it. Click in the file tree opens a new tab (or activates if the
 * note is already open) — that wiring is in AppShell.
 *
 * v1 styling matches the byline register: paper-toned card stock for
 * the active tab, transparent for inactive, ink-mute for both;
 * 1px line below traces the body's top edge so the strip reads as
 * "tabs ON paper" rather than "tabs ATTACHED to a section".
 *
 * Hidden when 0 tabs (the AppShell falls back to its empty state).
 */

import { useQuery } from "@tanstack/react-query";
import { Pin, PinOff, X } from "lucide-react";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { getTree } from "@/api/client";
import type { TreeFolder, TreeNote } from "@/api/types";
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuShortcut,
  ContextMenuTrigger,
} from "@/components/ui/context-menu";
import { QK } from "@/lib/queryClient";

interface Props {
  /** Display-order tab list — pinned first, then unpinned. The owner
   *  computes this; TabStrip just renders. */
  tabs: string[];
  activeId: string | null;
  /** Set of pinned ids; renders the pin affordance + survives "Close
   *  All". */
  pinnedSet: Set<string>;
  onActivate: (id: string) => void;
  onClose: (id: string) => void;
  /** Close every tab except `keepId` (and any pinned). */
  onCloseOthers: (keepId: string) => void;
  /** Close all unpinned tabs (pinned survive). */
  onCloseAll: () => void;
  /** Toggle pin state of `id`. */
  onTogglePin: (id: string) => void;
  /** Drop-and-reorder. Owner enforces the same-section invariant. */
  onReorder: (
    sourceId: string,
    targetId: string,
    position: "before" | "after",
  ) => void;
}

interface DragState {
  sourceId: string;
  targetId: string | null;
  side: "before" | "after" | null;
  /** True if source and target are in different sections — DnD will
   *  reject. We keep the state alive (so the indicator can render
   *  with a "no-drop" tone) but skip the actual reorder on drop. */
  invalid: boolean;
}

/** Walk the tree once to produce a `noteId → title` map. The tree
 *  query is already in the cache (FileTree mounts it on app boot),
 *  so this is just a synchronous map-build, not a fetch. */
function indexTreeTitles(root: TreeFolder | undefined): Map<string, string> {
  const out = new Map<string, string>();
  if (!root) return out;
  const walk = (folder: TreeFolder) => {
    for (const note of folder.notes) out.set(note.id, note.title);
    for (const sub of folder.folders) walk(sub);
  };
  walk(root);
  return out;
}

export function TabStrip({
  tabs,
  activeId,
  pinnedSet,
  onActivate,
  onClose,
  onCloseOthers,
  onCloseAll,
  onTogglePin,
  onReorder,
}: Props) {
  const { t } = useTranslation();
  const tree = useQuery<TreeFolder>({ queryKey: QK.tree, queryFn: getTree });
  const titles = indexTreeTitles(tree.data);
  const [drag, setDrag] = useState<DragState | null>(null);
  // useRef mirror so onDragOver / onDrop can read the source id
  // synchronously — setState lag means consecutive native events
  // (in tests, or rapid real drags) can fire before React has
  // committed the state update from onDragStart.
  const dragRef = useRef<DragState | null>(null);
  const writeDrag = (next: DragState | null) => {
    dragRef.current = next;
    setDrag(next);
  };

  if (tabs.length === 0) return null;

  // Track where the pinned section ends so we can render a hairline
  // separator between pinned and unpinned tabs.
  const pinnedCount = tabs.filter((id) => pinnedSet.has(id)).length;
  const onlyOne = tabs.length === 1;

  const computeSide = (
    e: React.DragEvent<HTMLDivElement>,
  ): "before" | "after" => {
    const rect = e.currentTarget.getBoundingClientRect();
    return e.clientX < rect.left + rect.width / 2 ? "before" : "after";
  };

  return (
    <div
      data-testid="tab-strip"
      className="flex shrink-0 items-stretch overflow-x-auto"
      style={{
        background: "var(--bg-1)",
        borderBottom: "1px solid var(--line)",
      }}
    >
      {tabs.map((id, idx) => {
        const active = id === activeId;
        const title = titles.get(id) ?? "(missing)";
        const isPinned = pinnedSet.has(id);
        const isLastPinned = isPinned && idx === pinnedCount - 1;
        return (
          <ContextMenu key={id}>
            <ContextMenuTrigger asChild>
              <div
                role="tab"
                aria-selected={active}
                data-testid="tab"
                data-note-id={id}
                data-active={active}
                data-pinned={isPinned}
                draggable
                onDragStart={(e) => {
                  e.dataTransfer.effectAllowed = "move";
                  e.dataTransfer.setData("text/plain", id);
                  writeDrag({
                    sourceId: id,
                    targetId: null,
                    side: null,
                    invalid: false,
                  });
                }}
                onDragOver={(e) => {
                  const cur = dragRef.current;
                  if (!cur) return;
                  e.preventDefault();
                  const sameSection =
                    pinnedSet.has(cur.sourceId) === pinnedSet.has(id);
                  const isSelf = cur.sourceId === id;
                  e.dataTransfer.dropEffect =
                    sameSection && !isSelf ? "move" : "none";
                  const side = computeSide(e);
                  writeDrag({
                    sourceId: cur.sourceId,
                    targetId: id,
                    side,
                    invalid: !sameSection || isSelf,
                  });
                }}
                onDragLeave={(e) => {
                  // Only blank the indicator if the cursor truly left
                  // *this* tab — relatedTarget is the next element to
                  // receive enter, and Radix-managed children can fire
                  // spurious leaves on the parent.
                  const next = e.relatedTarget as Node | null;
                  if (next && e.currentTarget.contains(next)) return;
                  const cur = dragRef.current;
                  if (cur?.targetId === id) {
                    writeDrag({
                      ...cur,
                      targetId: null,
                      side: null,
                      invalid: false,
                    });
                  }
                }}
                onDrop={(e) => {
                  e.preventDefault();
                  const cur = dragRef.current;
                  if (cur && cur.targetId === id && !cur.invalid && cur.side) {
                    onReorder(cur.sourceId, id, cur.side);
                  }
                  writeDrag(null);
                }}
                onDragEnd={() => writeDrag(null)}
                onClick={() => onActivate(id)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onActivate(id);
                  }
                }}
                tabIndex={0}
                className="group relative flex min-w-0 cursor-pointer items-center gap-2 px-3 py-1.5 text-[12px] transition-colors"
                style={{
                  maxWidth: 200,
                  borderRight: isLastPinned
                    ? "1px solid var(--line)"
                    : "1px solid var(--line-soft)",
                  background: active ? "var(--bg)" : "transparent",
                  color: active ? "var(--ink)" : "var(--ink-mute)",
                  fontWeight: active ? 500 : 400,
                  borderTop: active
                    ? "2px solid var(--accent)"
                    : "2px solid transparent",
                  // Source-of-the-drag is dimmed slightly so the user
                  // sees what they're dragging.
                  opacity: drag?.sourceId === id ? 0.5 : 1,
                }}
                title={title}
              >
                {/* Drop indicator — vertical bar on the side the
                 *  cursor is on. Hidden when the drop would be a
                 *  no-op (cross-section or self). */}
                {drag &&
                  drag.targetId === id &&
                  !drag.invalid &&
                  drag.side && (
                    <div
                      data-testid="tab-drop-indicator"
                      className="absolute top-0 bottom-0 w-[2px]"
                      style={{
                        background: "var(--accent)",
                        left: drag.side === "before" ? -1 : undefined,
                        right: drag.side === "after" ? -1 : undefined,
                      }}
                      aria-hidden="true"
                    />
                  )}
                <span
                  className="min-w-0 truncate"
                  style={{ flex: 1, lineHeight: 1.2 }}
                >
                  {title}
                </span>
                {/* Right-side button — VS Code parity. For unpinned
                 *  tabs it's × → close. For pinned tabs it's a pin
                 *  icon → unpin (one extra click before the × that
                 *  appears post-unpin can close it). Same slot, same
                 *  affordance position; only the icon + behavior
                 *  changes. */}
                {isPinned ? (
                  <button
                    type="button"
                    data-testid="tab-unpin"
                    data-note-id={id}
                    onClick={(e) => {
                      e.stopPropagation();
                      onTogglePin(id);
                    }}
                    onContextMenu={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                    }}
                    aria-label={`Unpin ${title}`}
                    className="flex size-4 shrink-0 items-center justify-center rounded-sm transition-opacity hover:bg-accent/30"
                    style={{ color: "var(--accent)" }}
                  >
                    <Pin size={11} className="rotate-45 fill-current" />
                  </button>
                ) : (
                  <button
                    type="button"
                    data-testid="tab-close"
                    data-note-id={id}
                    onClick={(e) => {
                      e.stopPropagation();
                      onClose(id);
                    }}
                    onContextMenu={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                    }}
                    aria-label={`Close ${title}`}
                    className="flex size-4 shrink-0 items-center justify-center rounded-sm opacity-50 transition-opacity hover:bg-accent/30 hover:opacity-100 group-hover:opacity-80"
                    style={{ color: "var(--ink-mute)" }}
                  >
                    <X size={11} />
                  </button>
                )}
              </div>
            </ContextMenuTrigger>
            <ContextMenuContent data-testid="tab-context-menu">
              <ContextMenuItem
                data-testid="tab-context-pin"
                onSelect={() => onTogglePin(id)}
              >
                {isPinned ? (
                  <>
                    <PinOff />
                    {t("tabs.unpin")}
                  </>
                ) : (
                  <>
                    <Pin />
                    {t("tabs.pin")}
                  </>
                )}
              </ContextMenuItem>
              <ContextMenuSeparator />
              <ContextMenuItem
                data-testid="tab-context-close"
                onSelect={() => onClose(id)}
              >
                {t("tabs.close")}
                <ContextMenuShortcut>⌘W</ContextMenuShortcut>
              </ContextMenuItem>
              <ContextMenuItem
                data-testid="tab-context-close-others"
                disabled={onlyOne}
                onSelect={() => onCloseOthers(id)}
              >
                {t("tabs.closeOthers")}
              </ContextMenuItem>
              <ContextMenuItem
                data-testid="tab-context-close-all"
                onSelect={() => onCloseAll()}
              >
                {t("tabs.closeAll")}
              </ContextMenuItem>
            </ContextMenuContent>
          </ContextMenu>
        );
      })}
    </div>
  );
}

// Re-export for convenience — callers can use `import type { TreeNote }`
// without re-mapping. Currently unused outside this file but cheap.
export type { TreeNote };
