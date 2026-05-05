/**
 * Vault file tree (Phase 1 A).
 *
 * react-arborist gives us virtualization, drag-drop, multi-select and
 * inline rename for free; we own the row renderer + the wiring between
 * Tree events and the backend mutations. Right-click is delegated to the
 * shadcn ContextMenu (Radix under the hood).
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, FilePlus, FileText, Folder, FolderPlus } from "lucide-react";
import { useCallback, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Tree,
  type NodeApi,
  type NodeRendererProps,
  type RowRendererProps,
  type TreeApi,
} from "react-arborist";

import {
  createBlankNote,
  createFolder,
  deleteFolder,
  deleteNote,
  getNote,
  getTree,
  moveFolder,
  moveNote,
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
import { QK } from "@/lib/queryClient";

import type { TreeFolder } from "@/api/types";

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

type PendingCreate = { kind: "note" | "folder"; parentPath: string };

export interface FileTreeProps {
  selectedNoteId: string | null;
  onSelectNote: (id: string) => void;
  onMutating?: (busy: boolean) => void;
}

export function FileTree({ selectedNoteId, onSelectNote, onMutating }: FileTreeProps) {
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

  const tree = useQuery({ queryKey: QK.tree, queryFn: getTree });

  const refresh = () => qc.invalidateQueries({ queryKey: QK.tree });
  const startBusy = () => onMutating?.(true);
  const settled = () => {
    onMutating?.(false);
    refresh();
  };

  const renameNoteM = useMutation({
    mutationFn: async ({ id, title }: { id: string; title: string }) => {
      const cur = await getNote(id);
      return updateNote(id, { title, tags: cur.tags, body: cur.body });
    },
    // Optimistic update: write the new title into the tree query cache
    // BEFORE the PUT round-trips. Otherwise arborist's submit() flips
    // the row out of edit mode immediately, the row re-renders the
    // <span> with the OLD cached title, the user sees "alpha" for
    // ~100 ms, then the refetch replaces with "newname". User reads
    // it as a flash of the old name.
    onMutate: ({ id, title }) => {
      onMutating?.(true);
      const previous = qc.getQueryData<TreeFolder>(QK.tree);
      if (previous) {
        qc.setQueryData<TreeFolder>(
          QK.tree,
          applyToTree(previous, (root) => updateNoteInTree(root, id, { title })),
        );
      }
      return { previous };
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.previous) qc.setQueryData(QK.tree, ctx.previous);
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
    mutationFn: ({ title, folder }: { title: string; folder: string }) =>
      createBlankNote({ title, folder }),
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
    const trimmed = name.trim();
    if (!trimmed) return;
    if (node.data.kind === "note") {
      renameNoteM.mutate({ id: node.data.noteId, title: trimmed });
    } else {
      renameFolderM.mutate({ path: node.data.folderPath, newName: trimmed });
    }
  };

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
  const onNewRootFolder = () => startCreate("folder", "");
  const onNewRootNote = () => startCreate("note", "");
  const cancelPending = () => setPendingCreate(null);
  const commitPending = (rawName: string) => {
    if (!pendingCreate) return;
    const trimmed = rawName.trim().replace(/\.md$/i, "");
    if (!trimmed) {
      cancelPending();
      return;
    }
    if (pendingCreate.kind === "note") {
      createNoteM.mutate({ title: trimmed, folder: pendingCreate.parentPath });
    } else {
      const path = pendingCreate.parentPath
        ? `${pendingCreate.parentPath}/${trimmed}`
        : trimmed;
      createFolderM.mutate({ path });
    }
    // Note: do NOT clear pendingCreate here. The placeholder stays in
    // the tree until the mutation lands so the user doesn't see a gap.
    // createNoteM / createFolderM clear it in onSuccess.
  };

  // Memoize the conversion so arborist's internal open/closed state isn't
  // reset every render. Without this, every click rebuilds the array and
  // arborist re-applies `openByDefault`, undoing the toggle. Must be called
  // before any conditional return so the hook order is stable across renders.
  const data = useMemo(() => {
    const base = tree.data ? toArborist(tree.data) : [];
    return pendingCreate ? injectPending(base, pendingCreate) : base;
  }, [tree.data, pendingCreate]);

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
    <div className="flex h-full flex-col">
      {/* Header — VS Code-style bold uppercase title; left padding lines up
          with the row's chevron column (px-2 row + 8px row inner gap). */}
      <div
        className="flex shrink-0 items-center justify-between border-b py-1.5 pr-1 pl-3"
        style={{ borderColor: "var(--line)" }}
      >
        <span className="text-[11px] font-semibold uppercase tracking-wide text-foreground/80">
          {t("tree.vault")}
        </span>
        <div className="flex items-center gap-0.5">
          <Button
            variant="ghost"
            size="icon"
            aria-label={t("tree.newNote")}
            onClick={onNewRootNote}
            className="size-6"
          >
            <FilePlus className="size-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            aria-label={t("tree.newFolder")}
            onClick={onNewRootFolder}
            className="size-6"
          >
            <FolderPlus className="size-3.5" />
          </Button>
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-hidden">
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
            height={5000}
            rowHeight={26}
            indent={14}
            paddingTop={4}
            onRename={onRename}
            onMove={onMove}
            onDelete={onDelete}
            selection={selectedNoteId ? `note:${selectedNoteId}` : undefined}
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
                onCreateChildNote={(parentPath) => startCreate("note", parentPath)}
                onCreateChildFolder={(parentPath) => startCreate("folder", parentPath)}
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
  onCreateChildNote: (parentPath: string) => void;
  onCreateChildFolder: (parentPath: string) => void;
  onCommitPending: (name: string) => void;
  onCancelPending: () => void;
  onDeleteFolder: (folderPath: string, name: string) => void;
  onDeleteNote: (noteId: string, name: string) => void;
}

function Row({
  node,
  style,
  dragHandle,
  openMap,
  setOpenMap,
  onCreateChildNote,
  onCreateChildFolder,
  onCommitPending,
  onCancelPending,
  onDeleteFolder,
  onDeleteNote,
}: RowProps) {
  const { t } = useTranslation();
  const isPending =
    node.id === PENDING_NOTE_ID || node.id === PENDING_FOLDER_ID;
  const isFolder =
    node.data.kind === "folder" || node.data.kind === "pending-folder";
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
    if (isFolder) {
      // Drive both arborist's internal toggle (so it knows to render
      // children) and our controlled openMap (so the chevron icon flips).
      // We also call node.toggle() to keep arborist's visibleNodes list
      // in sync, then mirror the result into our state.
      node.toggle();
      setOpenMap((m) => ({ ...m, [node.id]: !isOpen }));
    } else node.activate();
  };

  const rowBody = (
    <div
      ref={dragHandle}
      style={style}
      className="group flex h-full items-center px-1 select-none cursor-default"
      onDoubleClick={(e) => {
        e.stopPropagation();
        node.edit();
      }}
    >
      <div
        onClick={handleClick}
        className={`flex h-[calc(100%-2px)] w-full items-center gap-2 rounded-md px-2 text-sm ${
          node.isEditing || isPending
            ? "" // Editing rows: input ring is the focus indicator; no row bg.
            : node.isSelected
              ? "bg-secondary text-foreground"
              : "hover:bg-muted/60"
        }`}
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
        ) : (
          <FileText className="size-4 shrink-0 text-muted-foreground" />
        )}
        {node.isEditing || isPending ? (
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
              onSelect={() => onCreateChildNote(node.data.folderPath)}
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
