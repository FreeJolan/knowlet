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
}: Props) {
  const { t } = useTranslation();
  const tree = useQuery<TreeFolder>({ queryKey: QK.tree, queryFn: getTree });
  const titles = indexTreeTitles(tree.data);

  if (tabs.length === 0) return null;

  // Track where the pinned section ends so we can render a hairline
  // separator between pinned and unpinned tabs.
  const pinnedCount = tabs.filter((id) => pinnedSet.has(id)).length;
  const onlyOne = tabs.length === 1;

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
                onClick={() => onActivate(id)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onActivate(id);
                  }
                }}
                tabIndex={0}
                className="group flex min-w-0 cursor-pointer items-center gap-2 px-3 py-1.5 text-[12px] transition-colors"
                style={{
                  maxWidth: 200,
                  // Stronger separator after the last pinned tab so
                  // the strip reads as "[pinned] | [unpinned]".
                  borderRight: isLastPinned
                    ? "1px solid var(--line)"
                    : "1px solid var(--line-soft)",
                  background: active ? "var(--bg)" : "transparent",
                  color: active ? "var(--ink)" : "var(--ink-mute)",
                  fontWeight: active ? 500 : 400,
                  borderTop: active
                    ? "2px solid var(--accent)"
                    : "2px solid transparent",
                }}
                title={title}
              >
                {isPinned && (
                  <Pin
                    className="size-3 shrink-0 rotate-45"
                    style={{ color: "var(--accent)", opacity: 0.85 }}
                    aria-label="pinned"
                  />
                )}
                <span
                  className="min-w-0 truncate"
                  style={{ flex: 1, lineHeight: 1.2 }}
                >
                  {title}
                </span>
                {isPinned ? (
                  // Pinned tabs hide × so the user can't accidentally
                  // close them with a click. Right-click → Unpin first
                  // (or click the pin icon area itself — falls through
                  // to the tab activate; that's fine, unpin is a
                  // deliberate action).
                  <span
                    className="size-4 shrink-0"
                    aria-hidden="true"
                  />
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
