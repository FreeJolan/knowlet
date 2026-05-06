/**
 * Phase 1 A app shell — left tree | right note view.
 *
 * Tree mutates the vault, NoteView reads from it. Selection state lives
 * here so a future palette / Cmd+P can also drive it.
 */

import { useQueryClient } from "@tanstack/react-query";
import { LayoutTemplate, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { getTree } from "@/api/client";
import type { TreeFolder, TreeNote } from "@/api/types";
import { FileTree } from "@/components/FileTree/FileTree";
import { NoteView } from "@/components/NoteView/NoteView";
import { CommandPalette } from "@/components/Palette/CommandPalette";
import { TemplatesDialog } from "@/components/Templates/TemplatesDialog";
import { TrashPanel } from "@/components/Trash/TrashPanel";
import { Button } from "@/components/ui/button";
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from "@/components/ui/resizable";
import { QK } from "@/lib/queryClient";

/**
 * react-resizable-panels v2 only accepts percent values for defaultSize /
 * minSize / maxSize. We want a px-anchored sidebar (280 px default,
 * 160 px floor) so the tree column doesn't get squeezed unreadable on
 * small windows. Compute the percentage from the live window width and
 * re-derive on resize.
 */
const DEFAULT_SIDEBAR_PX = 280;
const MIN_SIDEBAR_PX = 160;
const MAX_SIDEBAR_PERCENT = 40;

function pxToPercent(px: number, windowWidth: number): number {
  if (windowWidth <= 0) return 18;
  return (px / windowWidth) * 100;
}

/**
 * Walk the tree depth-first, picking the first note whose title matches
 * `target` case-insensitively. Returns null if nothing matches — for a
 * `[[Title]]` link to a missing note we silently swallow the click; the
 * `kn-wikilink-broken` styling already cues the user.
 */
function findNoteByTitle(root: TreeFolder, target: string): TreeNote | null {
  const lower = target.toLowerCase();
  const stack: TreeFolder[] = [root];
  while (stack.length) {
    const folder = stack.pop();
    if (!folder) continue;
    for (const n of folder.notes) {
      if (n.title.toLowerCase() === lower) return n;
    }
    for (const sub of folder.folders) stack.push(sub);
  }
  return null;
}

export function AppShell() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [selectedNoteId, setSelectedNoteId] = useState<string | null>(null);
  const [trashOpen, setTrashOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [templatesOpen, setTemplatesOpen] = useState(false);
  // When a wikilink request includes a #heading anchor, NoteView remounts
  // for the new note; we stash the hash here so the freshly-mounted
  // preview can scroll to it once headings have ids assigned.
  const [pendingHash, setPendingHash] = useState<string | null>(null);
  const [windowWidth, setWindowWidth] = useState(() =>
    typeof window === "undefined" ? 1400 : window.innerWidth,
  );

  useEffect(() => {
    const onResize = () => setWindowWidth(window.innerWidth);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const sidebarSizes = useMemo(() => {
    // Clamp into a sane band so a tiny window doesn't try to ask for
    // more than max%, and a huge window doesn't pin to 1%.
    const defaultSize = Math.max(
      pxToPercent(MIN_SIDEBAR_PX, windowWidth),
      Math.min(MAX_SIDEBAR_PERCENT, pxToPercent(DEFAULT_SIDEBAR_PX, windowWidth)),
    );
    const minSize = Math.min(
      MAX_SIDEBAR_PERCENT,
      pxToPercent(MIN_SIDEBAR_PX, windowWidth),
    );
    return { defaultSize, minSize };
  }, [windowWidth]);
  // Reserved for Phase 1 B — when a tree mutation is in flight we may want
  // to mark the editor read-only so the user doesn't type into a stale
  // note that's about to be moved out from under them.
  const [, setTreeBusy] = useState(false);

  useEffect(() => {
    const openPalette = () => setPaletteOpen(true);
    const openTrash = () => setTrashOpen(true);
    const openWikilink = (e: Event) => {
      const detail = (e as CustomEvent<{ title: string; hash: string }>).detail;
      if (!detail || !detail.title) return;
      // Resolve title against the cached tree, fetching if absent.
      void (async () => {
        let tree = qc.getQueryData<TreeFolder>(QK.tree);
        if (!tree) {
          tree = await qc.fetchQuery({
            queryKey: QK.tree,
            queryFn: getTree,
          });
        }
        const hit = tree ? findNoteByTitle(tree, detail.title) : null;
        if (!hit) return;
        // If we're already on this note, skip the swap so the preview's
        // scroll position isn't reset; just navigate the hash.
        if (hit.id !== selectedNoteId) setSelectedNoteId(hit.id);
        setPendingHash(detail.hash || null);
      })();
    };
    window.addEventListener("knowlet:open-palette", openPalette);
    window.addEventListener("knowlet:open-trash", openTrash);
    window.addEventListener("knowlet:open-wikilink", openWikilink);
    return () => {
      window.removeEventListener("knowlet:open-palette", openPalette);
      window.removeEventListener("knowlet:open-trash", openTrash);
      window.removeEventListener("knowlet:open-wikilink", openWikilink);
    };
  }, [qc, selectedNoteId]);

  return (
    <>
      <div
        className="flex h-screen flex-col"
        style={{ background: "var(--bg)" }}
      >
        <header
          className="flex shrink-0 items-center justify-between border-b px-4 py-2"
          style={{ borderColor: "var(--line)", background: "var(--panel)" }}
        >
          <div
            className="font-mono text-xs uppercase tracking-widest"
            style={{ color: "var(--ink-mute)" }}
          >
            {t("app.title")}
          </div>
          <div className="flex items-center gap-1">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setPaletteOpen(true)}
              className="font-mono text-xs"
            >
              <span style={{ color: "var(--ink-mute)" }}>⌘P</span>
              <span className="ml-2">{t("app.quickSwitch")}</span>
            </Button>
            <Button
              variant="ghost"
              size="icon"
              aria-label={t("app.templates")}
              onClick={() => setTemplatesOpen(true)}
              data-testid="templates-button"
            >
              <LayoutTemplate className="size-4" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              aria-label={t("app.trash")}
              onClick={() => setTrashOpen(true)}
            >
              <Trash2 className="size-4" />
            </Button>
          </div>
        </header>
        <div className="min-h-0 flex-1">
          <ResizablePanelGroup direction="horizontal">
            <ResizablePanel
              defaultSize={sidebarSizes.defaultSize}
              minSize={sidebarSizes.minSize}
              maxSize={MAX_SIDEBAR_PERCENT}
            >
              <FileTree
                selectedNoteId={selectedNoteId}
                onSelectNote={(id) => {
                  setSelectedNoteId(id);
                  setPendingHash(null);
                }}
                onMutating={setTreeBusy}
              />
            </ResizablePanel>
            <ResizableHandle />
            <ResizablePanel defaultSize={100 - sidebarSizes.defaultSize} minSize={30}>
              <NoteView
                noteId={selectedNoteId}
                pendingHash={pendingHash}
                onPendingHashConsumed={() => setPendingHash(null)}
              />
            </ResizablePanel>
          </ResizablePanelGroup>
        </div>
      </div>
      <TrashPanel
        open={trashOpen}
        onClose={() => setTrashOpen(false)}
        onRestored={(restoredId) => setSelectedNoteId(restoredId)}
      />
      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        onSelectNote={(id) => {
          setSelectedNoteId(id);
          setPaletteOpen(false);
        }}
      />
      <TemplatesDialog
        open={templatesOpen}
        onClose={() => setTemplatesOpen(false)}
        onUseTemplate={(templateId) => {
          // Close dialog first, then trigger the FileTree's
          // inline-create flow so the user types a title for the new
          // note exactly like they would for "+ note".
          setTemplatesOpen(false);
          window.dispatchEvent(
            new CustomEvent("knowlet:start-create-from-template", {
              detail: { templateId },
            }),
          );
        }}
        onEditTemplate={(noteId) => {
          setTemplatesOpen(false);
          setSelectedNoteId(noteId);
        }}
      />
    </>
  );
}
