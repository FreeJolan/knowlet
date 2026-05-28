/**
 * Vault file tree (Phase 1 A).
 *
 * react-arborist gives us virtualization, drag-drop, multi-select and
 * inline rename for free; we own the row renderer + the wiring between
 * Tree events and the backend mutations. Right-click is delegated to the
 * shadcn ContextMenu (Radix under the hood).
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronDown,
  ChevronRight,
  FilePlus,
  FileText,
  Folder,
  FolderPlus,
  Star,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Tree,
  type NodeApi,
  type NodeRendererProps,
  type RowRendererProps,
  type TreeApi,
} from "react-arborist";

import {
  addFavorite,
  createBlankNote,
  createFolder,
  deleteFolder,
  deleteNote,
  getNote,
  getTree,
  listFavorites,
  moveFolder,
  moveNote,
  removeFavorite,
  renameFolder,
  updateNote,
} from "@/api/client";
import { Button } from "@/components/ui/button";
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuTrigger,
} from "@/components/ui/context-menu";
import { InlineEditInput } from "@/components/InlineEdit/InlineEditInput";
import {
  folderNameClashesIn,
  noteTitleClashesIn,
} from "@/lib/findCollision";
import { normalizeNoteTitle } from "@/lib/noteTitle";
import { QK } from "@/lib/queryClient";

import type { NoteFull, TreeFolder } from "@/api/types";

import {
  injectPending,
  PENDING_FOLDER_ID,
  PENDING_NOTE_ID,
  toArborist,
  type TreeNodeData,
} from "./treeData";

/**
 * Recursively update a TreeFolder snapshot. Used for optimistic rename:
 * the user's Enter triggers a PUT, but arborist's submit() synchronously
 * exits edit mode and the row would render with the *old* cached title
 * until the backend's response invalidates the tree (~50–200 ms gap).
 * Mutating the cache here makes the new title visible on the same frame
 * the user pressed Enter.
 */
function applyToTree(
  root: TreeFolder,
  fn: (root: TreeFolder) => TreeFolder,
): TreeFolder {
  return fn(root);
}

function updateNoteInTree(
  root: TreeFolder,
  noteId: string,
  patch: { title?: string },
): TreeFolder {
  return {
    ...root,
    notes: root.notes.map((n) =>
      n.id === noteId ? { ...n, ...(patch.title !== undefined && { title: patch.title }) } : n,
    ),
    folders: root.folders.map((f) => updateNoteInTree(f, noteId, patch)),
  };
}

function renameFolderInTree(root: TreeFolder, path: string, newName: string): TreeFolder {
  if (!path) return root;
  const parts = path.split("/");
  function walk(node: TreeFolder, depth: number): TreeFolder {
    return {
      ...node,
      folders: node.folders.map((f) => {
        if (f.name !== parts[depth]) return f;
        if (depth === parts.length - 1) {
          // Compute the new path with the renamed segment.
          const newSegs = [...parts.slice(0, depth), newName];
          return { ...f, name: newName, path: newSegs.join("/") };
        }
        return walk(f, depth + 1);
      }),
    };
  }
  return walk(root, 0);
}

type PendingCreate = {
  kind: "note" | "folder";
  parentPath: string;
  name?: string;
  submitting?: boolean;
  /** When set, the eventual createBlankNote call uses this template. */
  templateId?: string | null;
};

export interface FileTreeProps {
  selectedNoteId: string | null;
  onSelectNote: (id: string) => void;
  onMutating?: (busy: boolean) => void;
  /** Phase 2 D Slice 2b — when the New-doc dialog is open, this is
   *  the folder path the dialog currently targets. The tree
   *  highlights that folder + the path from root to it ("ghost
   *  selection"). Empty / undefined = no highlight. */
  ghostFolder?: string;
  /** Phase 2 D Slice 2c.2 — pin the tree to a sub-folder under
   *  `notes/`. When set, FileTree behaves as if THAT folder is the
   *  root: shows its descendants only, top-level mkdir/create stays
   *  inside it, the HIDDEN_TOP_LEVEL_FOLDERS filter is bypassed
   *  (since the user explicitly opted into that subtree). Used for
   *  the Templates left-rail tab where rootFolderPath="_templates". */
  rootFolderPath?: string;
}

export function FileTree({
  selectedNoteId,
  onSelectNote,
  onMutating,
  ghostFolder,
  rootFolderPath,
}: FileTreeProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const treeRef = useRef<TreeApi<TreeNodeData> | null>(null);
  // Controlled open state. Arborist's uncontrolled mode wasn't reflecting
  // node.toggle() in the DOM in our setup (likely a re-render race with
  // TanStack Query invalidations); owning the map ourselves is cheap and
  // makes toggle deterministic.
  const [openMap, setOpenMap] = useState<Record<string, boolean>>({});
  const isNodeOpen = useCallback(
    (id: string) => (openMap[id] === undefined ? true : openMap[id]),
    [openMap],
  );

  // Inline-create state. When set, the tree gets a phantom row in edit
  // mode under the named parent. Submit POSTs the real entity and clears
  // this; Esc / outside-click clears without creating. VS Code-style.
  const [pendingCreate, setPendingCreate] = useState<PendingCreate | null>(null);

  // Most recently clicked tree row, used as the F2 rename target. We
  // track this ourselves rather than read arborist's focusedNode because
  // the latter only populates when the tree-container DOM has focus,
  // which it doesn't reliably after our CustomRow strips tabIndex (a
  // necessary fix for input-focus stealing — see CustomRow comments).
  const [lastClickedId, setLastClickedId] = useState<string | null>(null);

  const tree = useQuery({ queryKey: QK.tree, queryFn: getTree });

  // Phase 2 D B1 — favorites for context-menu star/unstar.
  const favs = useQuery({
    queryKey: QK.favorites,
    queryFn: listFavorites,
    staleTime: 30_000,
  });
  const starredIds = useMemo(
    () => new Set((favs.data?.favorites ?? []).map((f) => f.id)),
    [favs.data],
  );
  const addFavM = useMutation({
    mutationFn: addFavorite,
    onSuccess: (res) => qc.setQueryData(QK.favorites, res),
  });
  const removeFavM = useMutation({
    mutationFn: removeFavorite,
    onSuccess: (res) => qc.setQueryData(QK.favorites, res),
  });
  const toggleStar = useCallback(
    (noteId: string, currentlyStarred: boolean) => {
      if (currentlyStarred) removeFavM.mutate(noteId);
      else addFavM.mutate(noteId);
    },
    [addFavM, removeFavM],
  );

  // F2 = rename the focused row. Matches VS Code / Finder. We listen at
  // the window level so the user doesn't have to first click into the
  // tree column. No-op if focus is in any text-input field (so F2 in
  // Cmd+P palette / a future editor doesn't collide).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "F2") return;
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable)) {
        return;
      }
      const treeApi = treeRef.current;
      if (!treeApi || !lastClickedId) return;
      const node = treeApi.get(lastClickedId);
      if (!node) return;
      e.preventDefault();
      node.edit();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [lastClickedId]);

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: QK.tree });
    // Tree-shape mutations may have moved a note in or out of
    // notes/_templates/, so refresh the picker source too.
    void qc.invalidateQueries({ queryKey: QK.templates });
    // Deletes also feed the trash. Without invalidating, the user
    // has to close + reopen the dialog (or hard-refresh) to see
    // the just-deleted note land there.
    void qc.invalidateQueries({ queryKey: QK.trash });
    // Phase 2 D B1 — a delete may orphan a favorite row. The
    // backend prunes dangling ids on next list call; this just
    // forces the UI to re-fetch so the row disappears without
    // waiting out the staleTime window.
    void qc.invalidateQueries({ queryKey: QK.favorites });
  };
  const startBusy = () => onMutating?.(true);
  const settled = () => {
    onMutating?.(false);
    refresh();
  };

  const renameNoteM = useMutation({
    mutationFn: async ({ id, title }: { id: string; title: string }) => {
      const cur = await getNote(id);
      return updateNote(id, {
        title,
        tags: cur.tags,
        body: cur.body,
        // Phase 1 D / D3: aliases is tri-state on the backend
        // (None=preserve / []=clear / [..]=replace). Echo current so
        // a tree-driven rename never wipes an aliases list the user
        // edited via NoteView.
        aliases: cur.aliases ?? [],
      });
    },
    // Optimistic update: write the new title into BOTH the tree query
    // cache AND the per-note cache (QK.note(id)) BEFORE the PUT
    // round-trips. Two reasons:
    //   - arborist's submit() flips the row out of edit mode on Enter;
    //     without the tree patch, the <span> re-renders the OLD cached
    //     title for ~100 ms (user reads it as a flash).
    //   - NoteView reads `useQuery(QK.note(id))`. If we don't patch
    //     this cache, the open note's <h1> shows the OLD title until
    //     the next refetch (2026-05-09 dogfood: "目录树改文件名时
    //     内容区标题没实时刷新"). settled() invalidates both, but
    //     until that fires the per-note cache returns stale data.
    onMutate: ({ id, title }) => {
      onMutating?.(true);
      const previousTree = qc.getQueryData<TreeFolder>(QK.tree);
      if (previousTree) {
        qc.setQueryData<TreeFolder>(
          QK.tree,
          applyToTree(previousTree, (root) =>
            updateNoteInTree(root, id, { title }),
          ),
        );
      }
      const previousNote = qc.getQueryData<NoteFull>(QK.note(id));
      if (previousNote) {
        qc.setQueryData<NoteFull>(QK.note(id), { ...previousNote, title });
      }
      return { previousTree, previousNote, id };
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.previousTree) qc.setQueryData(QK.tree, ctx.previousTree);
      if (ctx?.previousNote && ctx?.id) {
        qc.setQueryData(QK.note(ctx.id), ctx.previousNote);
      }
    },
    onSuccess: (data, vars) => {
      // PUT response is the canonical post-rename note; trust it over
      // the optimistic patch (handles backend-side title normalization
      // like trailing-`.md` strip).
      qc.setQueryData(QK.note(vars.id), data);
    },
    onSettled: settled,
  });
  const renameFolderM = useMutation({
    mutationFn: ({ path, newName }: { path: string; newName: string }) =>
      renameFolder(path, newName),
    onMutate: ({ path, newName }) => {
      onMutating?.(true);
      const previous = qc.getQueryData<TreeFolder>(QK.tree);
      if (previous) {
        qc.setQueryData<TreeFolder>(
          QK.tree,
          applyToTree(previous, (root) => renameFolderInTree(root, path, newName)),
        );
      }
      return { previous };
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.previous) qc.setQueryData(QK.tree, ctx.previous);
    },
    onSettled: settled,
  });
  const createFolderM = useMutation({
    mutationFn: ({ path }: { path: string }) => createFolder(path),
    onMutate: startBusy,
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: QK.tree });
      setPendingCreate(null);
    },
    onError: () => setPendingCreate(null),
    onSettled: () => onMutating?.(false),
  });
  const createNoteM = useMutation({
    mutationFn: ({
      title,
      folder,
      templateId,
    }: {
      title: string;
      folder: string;
      templateId?: string | null;
    }) =>
      createBlankNote({
        title,
        folder,
        templateId: templateId ?? undefined,
      }),
    onMutate: startBusy,
    onSuccess: async (note) => {
      // Force-open every ancestor folder so the new row is visible.
      if (note.folder) {
        setOpenMap((m) => {
          const next = { ...m };
          const parts = note.folder.split("/");
          for (let i = 1; i <= parts.length; i++) {
            next[`folder:${parts.slice(0, i).join("/")}`] = true;
          }
          return next;
        });
      }
      // Wait for the tree refetch to land before clearing the pending
      // placeholder + selecting. Otherwise the user sees the inline-edit
      // row vanish, then a brief empty gap, then the real note appear —
      // it reads as "my note disappeared".
      await qc.invalidateQueries({ queryKey: QK.tree });
      setPendingCreate(null);
      onSelectNote(note.id);
    },
    onError: () => {
      // Mutation failed — drop the placeholder so the user can retry.
      setPendingCreate(null);
    },
    onSettled: () => {
      onMutating?.(false);
      // No invalidate here — onSuccess already did. Avoids a second
      // refetch round-trip.
    },
  });
  const moveNoteM = useMutation({
    mutationFn: ({ id, target }: { id: string; target: string }) => moveNote(id, target),
    onMutate: startBusy,
    onSettled: settled,
  });
  const moveFolderM = useMutation({
    mutationFn: ({ src, dstParent }: { src: string; dstParent: string }) =>
      moveFolder(src, dstParent),
    onMutate: startBusy,
    onSettled: settled,
  });
  const deleteNoteM = useMutation({
    mutationFn: (id: string) => deleteNote(id),
    onMutate: startBusy,
    onSettled: settled,
  });
  const deleteFolderM = useMutation({
    mutationFn: (path: string) => deleteFolder(path),
    onMutate: startBusy,
    onSettled: settled,
  });

  const onRename = ({ name, node }: { id: string; name: string; node: NodeApi<TreeNodeData> }) => {
    const root = qc.getQueryData<TreeFolder>(QK.tree);
    if (node.data.kind === "note") {
      // Strip a trailing `.md` so renaming "foo" to "foo.md" doesn't
      // leak a storage detail into the title — see lib/noteTitle.ts.
      const cleaned = normalizeNoteTitle(name);
      if (!cleaned) {
        // arborist already exited edit mode; nothing else to do.
        return;
      }
      const currentFolder = findNoteFolder(root, node.data.noteId);
      if (
        currentFolder !== null &&
        noteTitleClashesIn(root, currentFolder, cleaned, node.data.noteId)
      ) {
        // Same UX as the title-edit + create paths: alert the user,
        // exit edit mode, leave the row showing its old name. They
        // can F2 again to retry. arborist's onRename fires AFTER
        // submit() — so editingId is already cleared by the time we
        // get here. No reset needed.
        window.alert(t("menu.duplicateNote", { name: cleaned }));
        return;
      }
      renameNoteM.mutate({ id: node.data.noteId, title: cleaned });
    } else {
      const trimmed = name.trim();
      if (!trimmed) return;
      const fullPath = node.data.folderPath;
      const lastSlash = fullPath.lastIndexOf("/");
      const parentPath = lastSlash === -1 ? "" : fullPath.slice(0, lastSlash);
      if (folderNameClashesIn(root, parentPath, trimmed, fullPath)) {
        window.alert(t("menu.duplicateFolder", { name: trimmed }));
        return;
      }
      renameFolderM.mutate({ path: fullPath, newName: trimmed });
    }
  };

  /**
   * Find the path-of-folder a note currently lives in. Returns "" for
   * root-level notes, null if the note isn't in the cached tree.
   */
  function findNoteFolder(
    root: TreeFolder | undefined,
    noteId: string,
  ): string | null {
    if (!root) return null;
    function walk(folder: TreeFolder, path: string): string | null {
      if (folder.notes.some((n) => n.id === noteId)) return path;
      for (const sub of folder.folders) {
        const found = walk(sub, sub.path);
        if (found !== null) return found;
      }
      return null;
    }
    return walk(root, "");
  }

  const onMove = ({
    dragIds,
    parentNode,
  }: {
    dragIds: string[];
    parentNode: NodeApi<TreeNodeData> | null;
    parentId: string | null;
    index: number;
  }) => {
    const targetFolderPath = parentNode?.data.folderPath ?? "";
    if (parentNode && parentNode.data.kind !== "folder") return;
    for (const dragId of dragIds) {
      const node = treeRef.current?.get(dragId);
      if (!node) continue;
      if (node.data.kind === "note") {
        moveNoteM.mutate({ id: node.data.noteId, target: targetFolderPath });
      } else {
        moveFolderM.mutate({
          src: node.data.folderPath,
          dstParent: targetFolderPath,
        });
      }
    }
  };

  const onDelete = ({ nodes }: { nodes: NodeApi<TreeNodeData>[] }) => {
    if (
      !window.confirm(
        t("menu.bulkDeleteConfirm", { count: nodes.length }),
      )
    ) {
      return;
    }
    for (const node of nodes) {
      if (node.data.kind === "note") {
        deleteNoteM.mutate(node.data.noteId);
      } else {
        deleteFolderM.mutate(node.data.folderPath);
      }
    }
  };

  // VS Code-style inline create: stage a pending row in the tree instead
  // of popping a browser prompt. Submit (Enter) hits the backend; Esc or
  // outside-click cancels.
  const startCreate = (kind: "note" | "folder", parentPath: string) => {
    // Defensive: arborist's edit state can survive between renames (e.g.
    // a Rename right-click that the user Esc'd in a way that didn't
    // fully clear `editingId`). If we open a pending row while another
    // row is still in edit mode, the tree shows two inputs and the
    // user's Enter / pinyin lands in the wrong one. Force-reset here.
    treeRef.current?.reset();
    if (parentPath) {
      // Auto-open the folder so the placeholder is visible.
      setOpenMap((m) => ({ ...m, [`folder:${parentPath}`]: true }));
    }
    setPendingCreate({ kind, parentPath });
  };
  // When pinned to a sub-folder root (Templates tab), "+" buttons
  // create inside that pinned root rather than the vault root.
  const onNewRootFolder = () => startCreate("folder", rootFolderPath ?? "");
  const onNewRootNote = () => startCreate("note", rootFolderPath ?? "");
  const cancelPending = () => setPendingCreate(null);

  const [duplicateError, setDuplicateError] = useState<string | null>(null);

  const commitPending = (rawName: string) => {
    if (!pendingCreate) return;
    // For notes: strip trailing `.md` (storage convention, not title).
    // For folders: just trim — folder names CAN end in `.md` if the
    // user really wants. Same helper is reused in onRename.
    const trimmed =
      pendingCreate.kind === "note"
        ? normalizeNoteTitle(rawName)
        : rawName.trim();
    if (!trimmed) {
      cancelPending();
      return;
    }
    const root = qc.getQueryData<TreeFolder>(QK.tree);
    const clash =
      pendingCreate.kind === "note"
        ? noteTitleClashesIn(root, pendingCreate.parentPath, trimmed)
        : folderNameClashesIn(root, pendingCreate.parentPath, trimmed);
    if (clash) {
      // Same UX as title-edit + tree-rename: alert the user, then
      // exit the inline-create state so the placeholder vanishes.
      // Re-clicking "+ note" / "+ folder" re-opens fresh. Keeping
      // the input open after a blocked submit was confusing —
      // dogfood feedback was the user couldn't tell whether to
      // retry, hit Esc, or click away.
      const key =
        pendingCreate.kind === "note"
          ? "menu.duplicateNote"
          : "menu.duplicateFolder";
      setDuplicateError(t(key, { name: trimmed }));
      window.alert(t(key, { name: trimmed }));
      cancelPending();
      return;
    }
    setDuplicateError(null);
    if (pendingCreate.kind === "note") {
      setPendingCreate({
        ...pendingCreate,
        name: trimmed,
        submitting: true,
      });
      createNoteM.mutate({
        title: trimmed,
        folder: pendingCreate.parentPath,
        templateId: pendingCreate.templateId ?? null,
      });
    } else {
      setPendingCreate({
        ...pendingCreate,
        name: trimmed,
        submitting: true,
      });
      const path = pendingCreate.parentPath
        ? `${pendingCreate.parentPath}/${trimmed}`
        : trimmed;
      createFolderM.mutate({ path });
    }
    // Note: do NOT clear pendingCreate here. The placeholder stays in
    // the tree until the mutation lands so the user doesn't see a gap.
    // createNoteM / createFolderM clear it in onSuccess.
  };
  // Surface duplicateError as a guard against TypeScript dead-code
  // pruning; consumed for accessibility and (future) toast wiring.
  void duplicateError;

  // The legacy TemplatesDialog dispatched `knowlet:start-create-from-
  // template` events that this hook listened for. Slice 2c.2-A'
  // removed the dialog (templates manage moved to Templates left-rail
  // tab + use template via NewDocDialog dropdown), so this bridge is
  // no longer wired. Keeping the comment as a marker in case the
  // event needs to be re-introduced for some other surface.

  // Memoize the conversion so arborist's internal open/closed state isn't
  // reset every render. Without this, every click rebuilds the array and
  // arborist re-applies `openByDefault`, undoing the toggle. Must be called
  // before any conditional return so the hook order is stable across renders.
  const data = useMemo(() => {
    if (!tree.data) return [];
    // Phase 2 D Slice 2c.2 — when pinned to a sub-folder root
    // (`rootFolderPath`), find that folder in the tree and treat its
    // children as the visible top-level rows. The HIDDEN_TOP_LEVEL_
    // FOLDERS filter inside toArborist only fires at vault-root
    // level, so subfolders bypass it naturally.
    let rootFolder: TreeFolder | null = tree.data;
    if (rootFolderPath) {
      const parts = rootFolderPath.split("/");
      let cursor: TreeFolder | undefined = tree.data;
      for (const p of parts) {
        cursor = cursor?.folders.find((f) => f.name === p);
        if (!cursor) break;
      }
      rootFolder = cursor ?? null;
    }
    const base = rootFolder ? toArborist(rootFolder) : [];
    if (!pendingCreate) return base;
    // injectPending walks `base` by folder NAME starting from depth 0.
    // When the visible tree is pinned (rootFolderPath set), the
    // pending row's `parentPath` is the FULL path under notes/ but
    // base doesn't contain the rootFolder itself as a row — so we
    // strip the rootFolderPath prefix before injecting.
    let injectionPath = pendingCreate.parentPath;
    if (rootFolderPath) {
      if (injectionPath === rootFolderPath) {
        injectionPath = "";
      } else if (injectionPath.startsWith(rootFolderPath + "/")) {
        injectionPath = injectionPath.slice(rootFolderPath.length + 1);
      }
    }
    return injectPending(base, {
      kind: pendingCreate.kind,
      parentPath: injectionPath,
      name: pendingCreate.name,
      submitting: pendingCreate.submitting,
    });
  }, [tree.data, pendingCreate, rootFolderPath]);

  // Phase 2 D Slice 2b — auto-expand path on ghost-folder change is
  // temporarily disabled while we investigate a React #185 cascade
  // it triggers in combination with arborist's row re-renders.
  // Without auto-expand, ghost highlight only appears if the user
  // has the target folder already expanded. Slice 2c will revisit.

  // Phase 2 D Slice 2b — compute "hot depths" per visible row when
  // the New-doc dialog is open with a target folder. Hot depths form
  // a continuous vertical line from root → target by lighting up each
  // ancestor's column in every row that lives between the ancestor
  // and the target (inclusive of target). See ADR-0025 + Claude
  // Design 2026-05-09 v2.
  const ghost = useMemo(() => {
    const empty = {
      hotMap: new Map<string, Set<number>>(),
      targetId: null as string | null,
    };
    if (ghostFolder === undefined || ghostFolder === "") return empty;
    const targetId = `folder:${ghostFolder}`;
    // Flatten visible nodes in DFS order respecting openMap.
    type Flat = { id: string; level: number };
    const flat: Flat[] = [];
    const visit = (nodes: TreeNodeData[], level: number) => {
      for (const n of nodes) {
        flat.push({ id: n.id, level });
        const open = openMap[n.id] === undefined ? true : openMap[n.id];
        if (open && n.children?.length) visit(n.children, level + 1);
      }
    };
    visit(data, 0);
    const tIdx = flat.findIndex((n) => n.id === targetId);
    if (tIdx < 0) return { ...empty, targetId };
    const target = flat[tIdx];
    if (!target) return { ...empty, targetId };
    const hotMap = new Map<string, Set<number>>();
    for (let d = target.level - 1; d >= 0; d--) {
      // Find ancestor at depth d (walk back from target).
      let aIdx = -1;
      for (let i = tIdx - 1; i >= 0; i--) {
        const row = flat[i];
        if (row && row.level === d) {
          aIdx = i;
          break;
        }
      }
      if (aIdx < 0) continue;
      // Mark rows (aIdx, tIdx] as hot at depth d.
      for (let i = aIdx + 1; i <= tIdx; i++) {
        const row = flat[i];
        if (!row) continue;
        if (!hotMap.has(row.id)) hotMap.set(row.id, new Set());
        hotMap.get(row.id)!.add(d);
      }
    }
    return { hotMap, targetId };
  }, [data, openMap, ghostFolder]);
  const visibleRowCount = useMemo(
    () => countVisibleRows(data, openMap),
    [data, openMap],
  );

  if (tree.isLoading) {
    return <div className="p-4 text-sm text-muted-foreground">{t("tree.loading")}</div>;
  }
  if (tree.isError) {
    return (
      <div className="p-4 text-sm text-destructive">
        {t("tree.loadFailed")}
        <Button variant="link" size="sm" onClick={() => tree.refetch()}>
          {t("tree.retry")}
        </Button>
      </div>
    );
  }

  return (
    // ``min-w-0`` — see AppShell row note. Without it this flex child
    // would refuse to shrink below its inner min-content width, and
    // ResizablePanel would silently overflow into the editor panel.
    <div className="flex min-h-0 min-w-0 flex-1 flex-col">
      {/* Header — VS Code-style bold uppercase title; left padding
          lines up with the row's chevron column (px-2 row + 8px row
          inner gap). One ``+`` button opens a popover with "新建
          笔记 / 新建文件夹". Single fixed-width button = the layout
          is bulletproof at any rail width; no JS measurement, no
          responsive branching. */}
      <div
        className="flex shrink-0 items-center justify-between gap-2 border-b py-1.5 pr-1 pl-3"
        style={{ borderColor: "var(--line)" }}
      >
        <span
          data-testid="file-tree-heading"
          className="min-w-0 truncate text-[11px] font-semibold uppercase tracking-wide text-foreground/80"
        >
          {rootFolderPath === "_templates"
            ? t("tree.tabTemplates")
            : t("tree.vault")}
        </span>
        {/* Two icons clustered on the right; heading on the left.
            Both buttons are ``shrink-0`` (fixed 24 px); heading is
            ``min-w-0 truncate`` so it ellipsizes first when the
            panel narrows. The min-w-0 chain fix at AppShell + FileTree
            outer level means the panel can now shrink past
            min-content, so the buttons can no longer be pushed
            outside the panel even at extreme widths. */}
        <div className="flex shrink-0 items-center gap-0.5">
          <button
            type="button"
            aria-label={t("tree.newNote")}
            title={t("tree.newNoteHint")}
            onClick={(e) => {
              if (e.shiftKey) onNewRootNote();
              else
                window.dispatchEvent(
                  new CustomEvent("knowlet:open-new-doc", {
                    detail: { seedFolder: "" },
                  }),
                );
            }}
            className="flex size-6 shrink-0 items-center justify-center rounded-sm text-muted-foreground transition-colors hover:bg-accent/40 hover:text-foreground"
          >
            <FilePlus className="size-3.5" />
          </button>
          <button
            type="button"
            aria-label={t("tree.newFolder")}
            title={t("tree.newFolder")}
            onClick={onNewRootFolder}
            className="flex size-6 shrink-0 items-center justify-center rounded-sm text-muted-foreground transition-colors hover:bg-accent/40 hover:text-foreground"
          >
            <FolderPlus className="size-3.5" />
          </button>
        </div>
      </div>
      {/* Scrollable viewport. ``min-h-0 flex-1`` lets it claim the
          flex-remaining height inside the rail; ``overflow-y-auto``
          puts the scrollbar HERE, on the wrapper. react-arborist's
          internal virtualizer is fed the natural content height
          (``contentHeight`` below) so it renders every node and the
          wrapper does the actual scrolling — no measurement needed.
          For typical knowlet vaults (<<1000 notes) the lost
          virtualization-in-viewport optimization is negligible. */}
      <div
        // ``scrollbar-gutter: stable`` reserves a permanent slot for
        // the scrollbar so the wrapper's content width stays constant
        // whether or not the scrollbar is currently rendered. Without
        // this, expanding the Favorites tray could shrink the tree
        // vertically → trigger overflow → make the scrollbar appear →
        // steal ~15 px of width → cause the header's railWidth
        // measurement to drop under the breakpoint and collapse the
        // ``+ Folder`` button. Inline style instead of a Tailwind
        // arbitrary class so we don't gamble on JIT compilation
        // quirks for an arbitrary CSS property the user is relying on.
        data-fade-bottom={data.length > 12 ? "true" : undefined}
        className="min-h-0 flex-1 overflow-y-auto"
        style={{ scrollbarGutter: "stable" }}
      >
        {data.length === 0 ? (
          <div className="px-3 py-6 text-sm text-muted-foreground">
            {t("tree.empty")}
          </div>
        ) : (
          <Tree<TreeNodeData>
            ref={treeRef}
            data={data}
            openByDefault={true}
            width="100%"
            // Content-height tells react-arborist's react-window to
            // render every visible row. Count recursively rather than
            // using top-level data.length; otherwise nested rows exist
            // in the DOM but are clipped by the virtualizer viewport.
            height={visibleRowCount * 26 + 8}
            rowHeight={26}
            indent={14}
            paddingTop={4}
            onRename={onRename}
            onMove={onMove}
            onDelete={onDelete}
            selection={selectedNoteId ? `note:${selectedNoteId}` : undefined}
            onActivate={(node) => {
              const raw = node.id;
              if (raw.startsWith("note:"))
                onSelectNote(raw.slice("note:".length));
            }}
            onToggle={(id) => {
              setOpenMap((m) => ({ ...m, [id]: !isNodeOpen(id) }));
            }}
            renderRow={CustomRow}
          >
            {(props: NodeRendererProps<TreeNodeData>) => (
              <Row
                {...props}
                openMap={openMap}
                setOpenMap={setOpenMap}
                onClickRow={setLastClickedId}
                ghostHotDepths={ghost.hotMap.get(props.node.id) ?? EMPTY_SET}
                isGhostTarget={ghost.targetId === props.node.id}
                onCreateChildFolder={(parentPath) =>
                  startCreate("folder", parentPath)
                }
                onCommitPending={commitPending}
                onCancelPending={cancelPending}
                onDeleteFolder={(folderPath, name) => {
                  if (window.confirm(t("menu.deleteFolderConfirm", { name }))) {
                    deleteFolderM.mutate(folderPath);
                  }
                }}
                onDeleteNote={(noteId, name) => {
                  if (window.confirm(t("menu.deleteNoteConfirm", { name }))) {
                    deleteNoteM.mutate(noteId);
                  }
                }}
                starredIds={starredIds}
                onToggleStar={toggleStar}
              />
            )}
          </Tree>
        )}
      </div>
    </div>
  );
}

// ----- custom Row wrapper -----

/**
 * Replaces arborist's DefaultRow. The default puts `tabIndex=-1` on the
 * row + binds an `innerRef` that arborist's RowContainer then calls
 * `.focus()` on whenever `node.isFocused` flips. That steals focus
 * from any input we mount inside the row (rename / new-note inline edit).
 *
 * Fix: keep `innerRef` (drop hooks need it for hover detection!) but
 * strip `tabIndex` from the attrs so `.focus()` on the resulting div
 * is a no-op, leaving the input's focus alone.
 */
function CustomRow<T>({ node, attrs, innerRef, children }: RowRendererProps<T>) {
  const { tabIndex: _ignored, ...rest } = attrs;
  return (
    <div
      {...rest}
      ref={innerRef}
      onFocus={(e) => e.stopPropagation()}
      onClick={node.handleClick}
    >
      {children}
    </div>
  );
}

// ----- row renderer -----

interface RowProps extends NodeRendererProps<TreeNodeData> {
  openMap: Record<string, boolean>;
  setOpenMap: React.Dispatch<React.SetStateAction<Record<string, boolean>>>;
  onClickRow: (id: string) => void;
  onCreateChildFolder: (parentPath: string) => void;
  onCommitPending: (name: string) => void;
  onCancelPending: () => void;
  onDeleteFolder: (folderPath: string, name: string) => void;
  onDeleteNote: (noteId: string, name: string) => void;
  /** Phase 2 D Slice 2b — depths whose indent guide should render
   *  with the highlighted accent color (path from root to dialog
   *  target folder). Empty set when dialog is closed. */
  ghostHotDepths: Set<number>;
  /** True when this row is the dialog's currently-selected target
   *  folder. Adds a left-edge accent border + accent-tint bg. */
  isGhostTarget: boolean;
  /** Phase 2 D B1 — set of starred note ids. Lets the row decide
   *  whether to render "Star" or "Unstar" without per-row queries. */
  starredIds: Set<string>;
  /** Phase 2 D B1 — toggle a note's starred state. */
  onToggleStar: (noteId: string, currentlyStarred: boolean) => void;
}

/** Phase 2 D Slice 2b — passive indent guide + dialog-driven ghost
 *  selection. `--line-soft` 1px guides per depth (always visible).
 *  When the New-doc dialog is open, the path from root → target gets
 *  `accent` 2px guides + the target row gets a ghost selection bg. */
const INDENT = 14;
const ROW_LEFT_PAD = 8;
const HOT_GUIDE = "rgba(91,122,156,.55)";
const EMPTY_SET: Set<number> = new Set();

function countVisibleRows(
  nodes: TreeNodeData[],
  openMap: Record<string, boolean>,
): number {
  let total = 0;
  for (const node of nodes) {
    total += 1;
    const isOpen = openMap[node.id] === undefined ? true : openMap[node.id];
    if (isOpen && node.children?.length) {
      total += countVisibleRows(node.children, openMap);
    }
  }
  return total;
}

function Row({
  node,
  style,
  dragHandle,
  openMap,
  setOpenMap,
  onClickRow,
  onCreateChildFolder,
  onCommitPending,
  onCancelPending,
  onDeleteFolder,
  onDeleteNote,
  ghostHotDepths,
  isGhostTarget,
  starredIds,
  onToggleStar,
}: RowProps) {
  const { t } = useTranslation();
  const isPending =
    node.id === PENDING_NOTE_ID || node.id === PENDING_FOLDER_ID;
  const isFolder =
    node.data.kind === "folder" || node.data.kind === "pending-folder";
  const noteId = !isFolder ? node.data.noteId : null;
  const isStarred = noteId !== null && starredIds.has(noteId);
  // Read from our controlled openMap; default = open (matches openByDefault).
  const isOpen = openMap[node.id] === undefined ? true : openMap[node.id];

  // Click anywhere on the row toggles a folder / opens a note (VS Code +
  // Obsidian convention). Arborist doesn't call onActivate on a single
  // row click — its onActivate fires on double-click / Enter. So we wire
  // the click ourselves on the inner pill (the outermost div is the
  // dragHandle which arborist itself binds events on, so we go one level
  // deeper to avoid stepping on it).
  const handleClick = () => {
    if (isPending) return;
    if (node.isEditing) return;
    onClickRow(node.id);
    if (isFolder) {
      // Drive both arborist's internal toggle (so it knows to render
      // children) and our controlled openMap (so the chevron icon flips).
      // We also call node.toggle() to keep arborist's visibleNodes list
      // in sync, then mirror the result into our state.
      node.toggle();
      setOpenMap((m) => ({ ...m, [node.id]: !isOpen }));
    } else node.activate();
  };

  // Phase 2 D Slice 2b — indent guides + ghost selection chrome.
  // Build N spans (one per ancestor depth). Highlighted depths use a
  // 2 px accent-tint stroke; passive depths use a 1 px line-soft.
  // The spans are absolutely-positioned within `rowBody` so they
  // span the row's full height and tile vertically with adjacent rows
  // to form continuous lines.
  const indentGuides = (
    <>
      {Array.from({ length: node.level }).map((_, depth) => {
        const hot = ghostHotDepths.has(depth);
        return (
          <span
            key={`g-${depth}`}
            aria-hidden="true"
            style={{
              position: "absolute",
              left: ROW_LEFT_PAD + depth * INDENT + 7 - (hot ? 0.5 : 0),
              top: 0,
              bottom: 0,
              width: hot ? 2 : 1,
              background: hot ? HOT_GUIDE : "var(--line-soft)",
              pointerEvents: "none",
              transition: "background 0.14s, width 0.14s",
            }}
          />
        );
      })}
    </>
  );

  const rowBody = (
    <div
      ref={dragHandle}
      style={{ ...style, position: "relative" }}
      data-ghost-target={isGhostTarget ? "1" : undefined}
      // pr-3 = 12 px right gutter so the inline-edit input's border /
      // ring doesn't kiss the panel's right edge (visually merging with
      // the resize handle when renaming).
      className="group flex h-full items-center pr-3 pl-1 select-none cursor-default"
    >
      {indentGuides}
      {/* Ghost-target left bar — sits at the row's far left, full height. */}
      {isGhostTarget && (
        <span
          aria-hidden="true"
          style={{
            position: "absolute",
            left: 0,
            top: 0,
            bottom: 0,
            width: 2,
            background: "var(--accent)",
            pointerEvents: "none",
          }}
        />
      )}
      <div
        onClick={handleClick}
        className={`flex h-[calc(100%-2px)] w-full items-center gap-2 rounded-md px-2 text-sm ${
          node.isEditing || isPending
            ? "" // Editing rows: input ring is the focus indicator; no row bg.
            : isGhostTarget
              ? "" // Ghost selection bg is set inline below.
              : node.isSelected
                ? "bg-secondary text-foreground"
                : "hover:bg-muted/60"
        }`}
        style={
          isGhostTarget && !node.isEditing && !isPending
            ? { background: "var(--accent-tint)" }
            : undefined
        }
      >
        {/* Chevron is purely visual — the row's onClick handles toggle.
            Empty folders get the spacer (no chevron) — Obsidian convention,
            keeps the column visually quieter. */}
        {isFolder && (node.children?.length ?? 0) > 0 ? (
          <span className="flex size-4 shrink-0 items-center justify-center text-muted-foreground">
            {isOpen ? (
              <ChevronDown className="size-3.5" />
            ) : (
              <ChevronRight className="size-3.5" />
            )}
          </span>
        ) : (
          <span className="size-4 shrink-0" />
        )}
        {isFolder ? (
          <Folder className="size-4 shrink-0 text-muted-foreground" />
        ) : noteId !== null ? (
          // Phase 2 D B1 — the note icon doubles as a star toggle.
          // ``FileText`` → click to star, swaps to filled ``Star``;
          // filled star → click to unstar, swaps back. Symmetric on
          // both states (dogfood 2026-05-12: users expected the
          // icon to be the toggle on the un-starred side too).
          // We stopPropagation so the click doesn't fire the row's
          // open-note handler.
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onToggleStar(noteId, isStarred);
            }}
            data-testid={
              isStarred
                ? `tree-star-${noteId}`
                : `tree-unstar-${noteId}`
            }
            aria-label={
              isStarred ? t("favorites.unstar") : t("favorites.star")
            }
            title={
              isStarred ? t("favorites.unstar") : t("favorites.star")
            }
            className="shrink-0 rounded-sm transition-colors hover:text-amber-500"
          >
            {isStarred ? (
              <Star className="size-4 fill-current text-amber-500" />
            ) : (
              <FileText className="size-4 text-muted-foreground" />
            )}
          </button>
        ) : (
          // Pending row (no noteId yet) — no toggle, just placeholder.
          <FileText className="size-4 shrink-0 text-muted-foreground" />
        )}
        {isPending && node.data.submitting ? (
          <span className="flex-1 truncate rounded-sm border border-transparent px-1 text-muted-foreground">
            {node.data.name || t("tree.untitled")}
          </span>
        ) : node.isEditing || isPending ? (
          <InlineEditInput
            initial={node.data.name}
            placeholder={
              isPending
                ? node.data.kind === "pending-note"
                  ? t("tree.newNote")
                  : t("tree.newFolder")
                : ""
            }
            onSubmit={(v) => {
              if (isPending) {
                onCommitPending(v);
                return;
              }
              const trimmed = v.trim();
              if (trimmed) node.submit(trimmed);
              else node.reset();
            }}
            onCancel={() => {
              if (isPending) onCancelPending();
              else node.reset();
            }}
          />
        ) : (
          // Match the input's `border + px-1` box so the text doesn't
          // visually jump 5 px when the row toggles into edit mode.
          // Border is transparent, padding is preserved.
          <span className="flex-1 truncate rounded-sm border border-transparent px-1">
            {node.data.name || t("tree.untitled")}
          </span>
        )}
      </div>
    </div>
  );

  return (
    <ContextMenu>
      <ContextMenuTrigger asChild>{rowBody}</ContextMenuTrigger>
      <ContextMenuContent
        className="w-52"
        // Radix's default close behavior auto-returns focus to the trigger
        // (the row's outer div). When the user picks "Rename", the menu
        // closes ~80 ms later and steals focus from the inline-edit input
        // we just mounted. We preventDefault, then re-focus the input
        // after Radix's full cleanup pass (aria-hidden / inert removal
        // on portal siblings). The setTimeout(0) lets Radix flush before
        // we touch focus — without it Chrome warns about focus being
        // inside an aria-hidden subtree.
        onCloseAutoFocus={(e) => {
          e.preventDefault();
          setTimeout(() => {
            const input = document.querySelector<HTMLInputElement>(
              'input[data-rename-input="true"]',
            );
            input?.focus();
            input?.select();
          }, 0);
        }}
      >
        {isFolder && (
          <>
            <ContextMenuItem
              onSelect={() => {
                // Defer the dispatch by one microtask so Radix's
                // menu-close + focus-restore sequence completes
                // before the dialog mounts. Synchronous dispatch
                // races with Radix's portal cleanup and the dialog
                // ends up not visible in the resulting render.
                const folderPath = node.data.folderPath;
                setTimeout(() => {
                  window.dispatchEvent(
                    new CustomEvent("knowlet:open-new-doc", {
                      detail: { seedFolder: folderPath },
                    }),
                  );
                }, 0);
              }}
            >
              {t("menu.newNoteInside")}
            </ContextMenuItem>
            <ContextMenuItem
              onSelect={() => onCreateChildFolder(node.data.folderPath)}
            >
              {t("menu.newFolderInside")}
            </ContextMenuItem>
            <ContextMenuSeparator />
          </>
        )}
        <ContextMenuItem onSelect={() => node.edit()}>
          {t("menu.rename")}
        </ContextMenuItem>
        {!isFolder && noteId !== null && (
          <ContextMenuItem
            onSelect={() => onToggleStar(noteId, isStarred)}
            data-testid={`menu-toggle-star-${noteId}`}
          >
            {isStarred ? t("favorites.unstar") : t("favorites.star")}
          </ContextMenuItem>
        )}
        <ContextMenuSeparator />
        <ContextMenuItem
          variant="destructive"
          onSelect={() =>
            isFolder
              ? onDeleteFolder(node.data.folderPath, node.data.name)
              : onDeleteNote(node.data.noteId, node.data.name)
          }
        >
          {t("menu.delete")}
        </ContextMenuItem>
      </ContextMenuContent>
    </ContextMenu>
  );
}
