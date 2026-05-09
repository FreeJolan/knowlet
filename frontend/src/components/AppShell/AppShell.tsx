/**
 * Phase 1 A app shell — left tree | right note view.
 *
 * Tree mutates the vault, NoteView reads from it. Selection state lives
 * here so a future palette / Cmd+P can also drive it.
 */

import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CalendarDays,
  LayoutTemplate,
  Network,
  PanelRight,
  PanelRightOpen,
  Settings as SettingsIcon,
  Trash2,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { getTree } from "@/api/client";
import type { TreeFolder, TreeNote } from "@/api/types";
import { FileTree } from "@/components/FileTree/FileTree";
import { GraphFocusMode } from "@/components/Graph/GraphFocusMode";
import { NoteView } from "@/components/NoteView/NoteView";
import { CommandPalette } from "@/components/Palette/CommandPalette";
import { RightRail } from "@/components/RightRail/RightRail";
import { SearchFocusMode } from "@/components/Search/SearchFocusMode";
import { SettingsDialog } from "@/components/Settings/SettingsDialog";
import { NewDocDialog } from "@/components/NewDoc/NewDocDialog";
import { TabStrip } from "@/components/TabStrip/TabStrip";
import { TagBrowser } from "@/components/TagBrowser/TagBrowser";
import { TemplatesDialog } from "@/components/Templates/TemplatesDialog";
import { TrashPanel } from "@/components/Trash/TrashPanel";
import { Button } from "@/components/ui/button";
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from "@/components/ui/resizable";
import { openOrCreateTodayDailyNote } from "@/lib/daily";
import { QK } from "@/lib/queryClient";
import { useTabs } from "@/hooks/useTabs";

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
const DEFAULT_RAIL_PX = 340;
const MIN_RAIL_PX = 240;
const MAX_RAIL_PERCENT = 35;
const RAIL_COLLAPSE_KEY = "knowlet.rail.collapsed.v1";

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
  // Phase 1 D / D1 — multi-tab basic. The single `selectedNoteId` is
  // now derived from the active tab in `tabsApi`. `setSelectedNoteId`
  // is wrapped in `openNoteInTab` below so every existing call site
  // creates / activates a tab transparently.
  const tabsApi = useTabs();
  const selectedNoteId = tabsApi.activeId;
  const setSelectedNoteId = tabsApi.openNote;
  const [trashOpen, setTrashOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [templatesOpen, setTemplatesOpen] = useState(false);
  // When a wikilink request includes a #heading anchor, NoteView remounts
  // for the new note; we stash the hash here so the freshly-mounted
  // preview can scroll to it once headings have ids assigned.
  const [pendingHash, setPendingHash] = useState<string | null>(null);
  // Phase 1 C slice 1: clicking a backlink row asks NoteView to scroll
  // its CodeMirror view to a specific 1-based line.
  const [pendingLine, setPendingLine] = useState<number | null>(null);
  // Phase 1 D slice 1: outline-driven jumps are *intra-note* — they
  // shouldn't auto-switch viewMode the way cross-note navigation
  // (backlinks / wikilinks) does. When this flag is true, NoteView's
  // scroll effects skip the mode switch.
  const [pendingPreserveMode, setPendingPreserveMode] = useState(false);
  // Phase 1 C: right rail collapse toggle. Persisted across reloads so
  // the user's preference sticks.
  const [railCollapsed, setRailCollapsed] = useState<boolean>(() => {
    if (typeof window === "undefined") return false;
    return window.localStorage.getItem(RAIL_COLLAPSE_KEY) === "1";
  });
  // Phase 1 C slice 2: left-rail tab — files (file tree) vs tags (tag browser).
  const [leftTab, setLeftTab] = useState<"files" | "tags">("files");
  // When a `#tag` chip in preview is clicked, AppShell hops to the Tags
  // tab and TagBrowser drills into that tag. We pass the requested tag
  // through `pendingTag` so TagBrowser (which just remounted) sees it.
  const [pendingTag, setPendingTag] = useState<string | null>(null);
  // Phase 1 C slice 3 — graph focus mode (Cmd+Shift+G).
  const [graphFocusOpen, setGraphFocusOpen] = useState(false);
  // Phase 1 D slice 1 — Settings dialog (currently only Appearance).
  const [settingsOpen, setSettingsOpen] = useState(false);
  // Phase 1 D slice 2 — global search focus mode (Cmd+Shift+F).
  const [searchFocusOpen, setSearchFocusOpen] = useState(false);
  // Phase 2 D Slice 2 — 新建文档 dialog. `seedFolder` is the folder
  // pre-selected when the dialog opens (current tree selection or the
  // folder right-clicked from the tree's context menu).
  const [newDocOpen, setNewDocOpen] = useState(false);
  const [newDocSeedFolder, setNewDocSeedFolder] = useState<string>("");
  const [windowWidth, setWindowWidth] = useState(() =>
    typeof window === "undefined" ? 1400 : window.innerWidth,
  );

  // Phase 1 D / D1 — prune tabs whose note no longer exists in the
  // tree (typical: user deleted the note, or the file was removed
  // out-of-band in Finder). FileTree's useQuery already feeds the
  // QK.tree cache; this useQuery just subscribes so the prune effect
  // re-runs on every tree refetch (delete / restore / new note).
  const treeQuery = useQuery<TreeFolder>({
    queryKey: QK.tree,
    queryFn: getTree,
  });
  useEffect(() => {
    if (!treeQuery.data) return;
    // Don't prune while a refetch is in flight — a freshly-created
    // note (NewDocDialog / Daily) lands in the tabs the same tick we
    // invalidate QK.tree, but the cached `treeQuery.data` is still
    // the pre-invalidation snapshot until the refetch completes. If
    // we prune here we'd erroneously close the just-created tab.
    if (treeQuery.isFetching) return;
    const valid = new Set<string>();
    const stack: TreeFolder[] = [treeQuery.data];
    while (stack.length) {
      const f = stack.pop();
      if (!f) continue;
      for (const n of f.notes) valid.add(n.id);
      for (const sub of f.folders) stack.push(sub);
    }
    const stale = tabsApi.tabs.filter((id) => !valid.has(id));
    for (const id of stale) tabsApi.closeTab(id);
  }, [treeQuery.data, treeQuery.isFetching, tabsApi]);

  // Phase 2 D Slice 2 — seed folder for the New-doc dialog. Default
  // is the folder of the currently-active note; if no note is open,
  // fall back to vault root. Right-click on a folder in the tree
  // overrides this via `setNewDocSeedFolder` before opening.
  const activeNoteFolder = useMemo(() => {
    if (!selectedNoteId || !treeQuery.data) return "";
    const stack: { folder: TreeFolder; path: string }[] = [
      { folder: treeQuery.data, path: "" },
    ];
    while (stack.length) {
      const node = stack.pop();
      if (!node) continue;
      for (const n of node.folder.notes) {
        if (n.id === selectedNoteId) return node.path;
      }
      for (const sub of node.folder.folders) {
        const subPath = node.path ? `${node.path}/${sub.name}` : sub.name;
        stack.push({ folder: sub, path: subPath });
      }
    }
    return "";
  }, [selectedNoteId, treeQuery.data]);

  const openNewDocDialog = useCallback(
    (seed?: string) => {
      setNewDocSeedFolder(seed ?? activeNoteFolder);
      setNewDocOpen(true);
    },
    [activeNoteFolder],
  );

  // Look up the currently-selected note's title from the tree cache so
  // the Backlinks empty-state can render `[[Title]]` correctly. Tree is
  // already cached for the FileTree, so this is free.
  const selectedNoteTitle = useMemo(() => {
    if (!selectedNoteId) return "";
    const tree = qc.getQueryData<TreeFolder>(QK.tree);
    if (!tree) return "";
    const stack: TreeFolder[] = [tree];
    while (stack.length) {
      const f = stack.pop();
      if (!f) continue;
      for (const n of f.notes) if (n.id === selectedNoteId) return n.title;
      for (const sub of f.folders) stack.push(sub);
    }
    return "";
  }, [selectedNoteId, qc]);

  const toggleRail = () => {
    setRailCollapsed((v) => {
      const next = !v;
      if (typeof window !== "undefined") {
        window.localStorage.setItem(RAIL_COLLAPSE_KEY, next ? "1" : "0");
      }
      return next;
    });
  };

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

  const railSizes = useMemo(() => {
    const defaultSize = Math.max(
      pxToPercent(MIN_RAIL_PX, windowWidth),
      Math.min(MAX_RAIL_PERCENT, pxToPercent(DEFAULT_RAIL_PX, windowWidth)),
    );
    const minSize = Math.min(
      MAX_RAIL_PERCENT,
      pxToPercent(MIN_RAIL_PX, windowWidth),
    );
    return { defaultSize, minSize };
  }, [windowWidth]);
  // Reserved for Phase 1 B — when a tree mutation is in flight we may want
  // to mark the editor read-only so the user doesn't type into a stale
  // note that's about to be moved out from under them.
  const [, setTreeBusy] = useState(false);

  // Phase 2 D Slice 1 — daily note open/create handler. Defined
  // inside the component (not inside the effect) so the header
  // button + keyboard shortcut can both call it; effect deps stay
  // honest. tabsApi.openNote is stable across renders.
  const openTodayDaily = async () => {
    try {
      const id = await openOrCreateTodayDailyNote(qc);
      tabsApi.openNote(id);
    } catch (err) {
      // Surface to console for now; toast UI is Phase 3 polish.
      console.error("daily-note open/create failed", err);
    }
  };

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
        setPendingPreserveMode(false);
        setPendingHash(detail.hash || null);
      })();
    };
    const openTag = (e: Event) => {
      const detail = (e as CustomEvent<{ tag: string }>).detail;
      if (!detail || !detail.tag) return;
      setLeftTab("tags");
      setPendingTag(detail.tag);
    };
    // Cmd+Shift+G → toggle graph focus mode.
    // Cmd+Shift+F → toggle global search focus mode.
    const onKey = (e: KeyboardEvent) => {
      if (
        (e.metaKey || e.ctrlKey) &&
        e.shiftKey &&
        (e.key === "g" || e.key === "G")
      ) {
        e.preventDefault();
        setGraphFocusOpen((v) => !v);
      }
      if (
        (e.metaKey || e.ctrlKey) &&
        e.shiftKey &&
        (e.key === "f" || e.key === "F")
      ) {
        e.preventDefault();
        setSearchFocusOpen((v) => !v);
      }
      // Phase 2 D Slice 1 — Cmd+Shift+D opens (or creates) today's
      // daily note in a new tab. Idempotent: pressing again on the
      // same day re-activates the existing tab.
      if (
        (e.metaKey || e.ctrlKey) &&
        e.shiftKey &&
        (e.key === "d" || e.key === "D")
      ) {
        e.preventDefault();
        void openTodayDaily();
      }
      // Phase 2 D Slice 2 — Cmd+N opens the New-doc dialog. Seed folder
      // = current active note's folder (or root if none).
      if (
        (e.metaKey || e.ctrlKey) &&
        !e.shiftKey &&
        !e.altKey &&
        (e.key === "n" || e.key === "N")
      ) {
        e.preventDefault();
        openNewDocDialog();
      }
    };
    // Phase 2 D Slice 2 — NewDocDialog footer link dispatches this
    // event when the user clicks "Templates → Settings / Templates".
    // For Slice 2a we still surface the existing TemplatesDialog as
    // the "manager" UI; Slice 2c will move it under Settings.
    const openTemplates = () => setTemplatesOpen(true);
    // FileTree's "+ Note" toolbar button (click) and right-click
    // "New note inside <folder>" both dispatch this event with the
    // seedFolder. Shift+click on the toolbar uses the legacy inline-
    // create path inside FileTree itself.
    const openNewDoc = (e: Event) => {
      const detail = (e as CustomEvent<{ seedFolder?: string }>).detail;
      openNewDocDialog(detail?.seedFolder ?? "");
    };
    // Phase 2 D Slice 2b — when user changes the folder field inside
    // the dialog, sync the seed so FileTree's ghost selection follows.
    // We use a window event (not a prop callback) to break the
    // render cycle that triggered React #185 — see NewDocDialog.tsx.
    const onFolderChange = (e: Event) => {
      const folder = (e as CustomEvent<string>).detail ?? "";
      setNewDocSeedFolder(folder);
    };
    window.addEventListener("knowlet:open-palette", openPalette);
    window.addEventListener("knowlet:open-trash", openTrash);
    window.addEventListener("knowlet:open-templates", openTemplates);
    window.addEventListener("knowlet:open-new-doc", openNewDoc);
    window.addEventListener("knowlet:new-doc-folder-change", onFolderChange);
    window.addEventListener("knowlet:open-wikilink", openWikilink);
    window.addEventListener("knowlet:open-tag", openTag);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("knowlet:open-palette", openPalette);
      window.removeEventListener("knowlet:open-trash", openTrash);
      window.removeEventListener("knowlet:open-templates", openTemplates);
      window.removeEventListener("knowlet:open-new-doc", openNewDoc);
      window.removeEventListener(
        "knowlet:new-doc-folder-change",
        onFolderChange,
      );
      window.removeEventListener("knowlet:open-wikilink", openWikilink);
      window.removeEventListener("knowlet:open-tag", openTag);
      window.removeEventListener("keydown", onKey);
    };
  }, [qc, selectedNoteId, openNewDocDialog]);

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
              aria-label={t("app.daily")}
              title={t("app.daily") + " (⌘⇧D)"}
              onClick={() => void openTodayDaily()}
              data-testid="header-daily-button"
            >
              <CalendarDays className="size-4" />
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
              aria-label={t("app.graph")}
              title={t("app.graph") + " (⌘⇧G)"}
              onClick={() => setGraphFocusOpen(true)}
              data-testid="header-graph-button"
            >
              <Network className="size-4" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              aria-label={t("app.trash")}
              onClick={() => setTrashOpen(true)}
            >
              <Trash2 className="size-4" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              aria-label={t("app.settings")}
              onClick={() => setSettingsOpen(true)}
              data-testid="header-settings-button"
            >
              <SettingsIcon className="size-4" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              aria-label={
                railCollapsed ? t("rail.expand") : t("rail.collapse")
              }
              onClick={toggleRail}
              data-testid="rail-toggle"
            >
              {railCollapsed ? (
                <PanelRightOpen className="size-4" />
              ) : (
                <PanelRight className="size-4" />
              )}
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
              <div className="flex h-full min-h-0 flex-col">
                <div
                  className="flex shrink-0 border-b"
                  style={{
                    borderColor: "var(--line)",
                    background: "var(--panel)",
                  }}
                  data-testid="left-tabs"
                >
                  <button
                    type="button"
                    onClick={() => setLeftTab("files")}
                    aria-pressed={leftTab === "files"}
                    data-testid="left-tab-files"
                    className="flex-1 px-3 py-1.5 text-xs transition-colors"
                    style={{
                      color:
                        leftTab === "files"
                          ? "var(--ink)"
                          : "var(--ink-mute)",
                      fontWeight: leftTab === "files" ? 500 : 400,
                      borderBottom:
                        leftTab === "files"
                          ? "2px solid var(--accent, #5b7a9c)"
                          : "2px solid transparent",
                    }}
                  >
                    {t("tree.tabFiles")}
                  </button>
                  <button
                    type="button"
                    onClick={() => setLeftTab("tags")}
                    aria-pressed={leftTab === "tags"}
                    data-testid="left-tab-tags"
                    className="flex-1 px-3 py-1.5 text-xs transition-colors"
                    style={{
                      color:
                        leftTab === "tags"
                          ? "var(--ink)"
                          : "var(--ink-mute)",
                      fontWeight: leftTab === "tags" ? 500 : 400,
                      borderBottom:
                        leftTab === "tags"
                          ? "2px solid var(--accent, #5b7a9c)"
                          : "2px solid transparent",
                    }}
                  >
                    {t("tree.tabTags")}
                  </button>
                </div>
                <div className="min-h-0 flex-1">
                  {leftTab === "files" ? (
                    <FileTree
                      selectedNoteId={selectedNoteId}
                      onSelectNote={(id) => {
                        setSelectedNoteId(id);
                        setPendingHash(null);
                        setPendingLine(null);
                        setPendingPreserveMode(false);
                      }}
                      onMutating={setTreeBusy}
                      ghostFolder={newDocOpen ? newDocSeedFolder : undefined}
                    />
                  ) : (
                    <TagBrowser
                      onSelectNote={(id) => {
                        setSelectedNoteId(id);
                        setPendingHash(null);
                        setPendingLine(null);
                        setPendingPreserveMode(false);
                      }}
                      pendingTag={pendingTag}
                      onPendingTagConsumed={() => setPendingTag(null)}
                    />
                  )}
                </div>
              </div>
            </ResizablePanel>
            <ResizableHandle />
            <ResizablePanel
              defaultSize={
                railCollapsed
                  ? 100 - sidebarSizes.defaultSize
                  : 100 - sidebarSizes.defaultSize - railSizes.defaultSize
              }
              minSize={30}
            >
              <div className="flex h-full min-h-0 flex-col">
                <TabStrip
                  tabs={tabsApi.tabs}
                  activeId={tabsApi.activeId}
                  onActivate={tabsApi.setActive}
                  onClose={tabsApi.closeTab}
                />
                <div className="min-h-0 flex-1">
                  <NoteView
                    noteId={selectedNoteId}
                    pendingHash={pendingHash}
                    onPendingHashConsumed={() => setPendingHash(null)}
                    pendingLine={pendingLine}
                    onPendingLineConsumed={() => setPendingLine(null)}
                    preserveViewMode={pendingPreserveMode}
                  />
                </div>
              </div>
            </ResizablePanel>
            {!railCollapsed && (
              <>
                <ResizableHandle />
                <ResizablePanel
                  defaultSize={railSizes.defaultSize}
                  minSize={railSizes.minSize}
                  maxSize={MAX_RAIL_PERCENT}
                >
                  <RightRail
                    noteId={selectedNoteId}
                    noteTitle={selectedNoteTitle}
                    onOpenSource={(sourceId, line) => {
                      if (sourceId !== selectedNoteId)
                        setSelectedNoteId(sourceId);
                      setPendingHash(null);
                      setPendingPreserveMode(false);
                      setPendingLine(line);
                    }}
                    onOpenTarget={(targetId) => {
                      if (targetId !== selectedNoteId)
                        setSelectedNoteId(targetId);
                      setPendingHash(null);
                      setPendingLine(null);
                      setPendingPreserveMode(false);
                    }}
                    onEnterGraphFocus={() => setGraphFocusOpen(true)}
                    onJumpToHeading={(slug, line) => {
                      // Outline click → scroll BOTH panes (preview
                      // anchor + CM line). preserveMode = true tells
                      // NoteView this is an *intra-note* jump, so it
                      // should NOT auto-switch from edit / preview to
                      // split (the user explicitly chose their mode).
                      setPendingPreserveMode(true);
                      setPendingHash(slug);
                      setPendingLine(line);
                    }}
                  />
                </ResizablePanel>
              </>
            )}
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
      <GraphFocusMode
        open={graphFocusOpen}
        noteId={selectedNoteId}
        onClose={() => setGraphFocusOpen(false)}
        onOpenNote={(id) => {
          setSelectedNoteId(id);
          setPendingHash(null);
          setPendingLine(null);
          setPendingPreserveMode(false);
        }}
      />
      <SettingsDialog
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
      />
      <SearchFocusMode
        open={searchFocusOpen}
        onClose={() => setSearchFocusOpen(false)}
        onOpenNote={(id) => {
          setSelectedNoteId(id);
          setPendingHash(null);
          setPendingLine(null);
          setPendingPreserveMode(false);
        }}
      />
      <NewDocDialog
        open={newDocOpen}
        onClose={() => setNewDocOpen(false)}
        seedFolder={newDocSeedFolder}
        onCreated={(note) => {
          setSelectedNoteId(note.id);
          setPendingHash(null);
          setPendingLine(null);
          setPendingPreserveMode(false);
        }}
      />
    </>
  );
}
