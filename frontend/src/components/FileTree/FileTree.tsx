/**
 * Vault file tree (Phase 1 A).
 *
 * react-arborist gives us virtualization, drag-drop, multi-select and
 * inline rename for free; we own the row renderer + the wiring between
 * Tree events and the backend mutations. Right-click is delegated to the
 * shadcn ContextMenu (Radix under the hood).
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, FileText, Folder, Plus } from "lucide-react";
import { useCallback, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Tree,
  type NodeApi,
  type NodeRendererProps,
  type TreeApi,
} from "react-arborist";

import {
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
import { QK } from "@/lib/queryClient";

import { toArborist, type TreeNodeData } from "./treeData";

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
    onMutate: startBusy,
    onSettled: settled,
  });
  const renameFolderM = useMutation({
    mutationFn: ({ path, newName }: { path: string; newName: string }) =>
      renameFolder(path, newName),
    onMutate: startBusy,
    onSettled: settled,
  });
  const createFolderM = useMutation({
    mutationFn: ({ path }: { path: string }) => createFolder(path),
    onMutate: startBusy,
    onSettled: settled,
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

  const onNewRootFolder = () => {
    const name = window.prompt(t("menu.rootFolderPrompt"));
    if (name?.trim()) createFolderM.mutate({ path: name.trim() });
  };

  // Memoize the conversion so arborist's internal open/closed state isn't
  // reset every render. Without this, every click rebuilds the array and
  // arborist re-applies `openByDefault`, undoing the toggle. Must be called
  // before any conditional return so the hook order is stable across renders.
  const data = useMemo(
    () => (tree.data ? toArborist(tree.data) : []),
    [tree.data],
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
        <Button
          variant="ghost"
          size="icon"
          aria-label={t("tree.newFolder")}
          onClick={onNewRootFolder}
          className="size-6"
        >
          <Plus className="size-3.5" />
        </Button>
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
          >
            {(props: NodeRendererProps<TreeNodeData>) => (
              <Row
                {...props}
                openMap={openMap}
                setOpenMap={setOpenMap}
                onCreateChildFolder={(parentPath) => {
                  const name = window.prompt(t("menu.newFolderPrompt"));
                  if (name?.trim()) {
                    createFolderM.mutate({
                      path: parentPath ? `${parentPath}/${name.trim()}` : name.trim(),
                    });
                  }
                }}
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

// ----- row renderer -----

interface RowProps extends NodeRendererProps<TreeNodeData> {
  openMap: Record<string, boolean>;
  setOpenMap: React.Dispatch<React.SetStateAction<Record<string, boolean>>>;
  onCreateChildFolder: (parentPath: string) => void;
  onDeleteFolder: (folderPath: string, name: string) => void;
  onDeleteNote: (noteId: string, name: string) => void;
}

function Row({
  node,
  style,
  dragHandle,
  openMap,
  setOpenMap,
  onCreateChildFolder,
  onDeleteFolder,
  onDeleteNote,
}: RowProps) {
  const { t } = useTranslation();
  const isFolder = node.data.kind === "folder";
  // Read from our controlled openMap; default = open (matches openByDefault).
  const isOpen = openMap[node.id] === undefined ? true : openMap[node.id];

  // Click anywhere on the row toggles a folder / opens a note (VS Code +
  // Obsidian convention). Arborist doesn't call onActivate on a single
  // row click — its onActivate fires on double-click / Enter. So we wire
  // the click ourselves on the inner pill (the outermost div is the
  // dragHandle which arborist itself binds events on, so we go one level
  // deeper to avoid stepping on it).
  const handleClick = () => {
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
          node.isSelected
            ? "bg-accent/40 text-accent-foreground"
            : "hover:bg-secondary/60"
        }`}
      >
        {/* Chevron is purely visual — the row's onPointerUp handles toggle.
            Notes get an empty spacer for alignment. */}
        {isFolder ? (
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
        {node.isEditing ? (
          <input
            className="flex-1 bg-transparent px-1 outline-none ring-1 ring-ring rounded-sm"
            defaultValue={node.data.name}
            autoFocus
            onFocus={(e) => e.currentTarget.select()}
            onBlur={() => node.reset()}
            onKeyDown={(e) => {
              if (e.key === "Enter") node.submit(e.currentTarget.value);
              if (e.key === "Escape") node.reset();
            }}
            onPointerDown={(e) => e.stopPropagation()}
          />
        ) : (
          <span className="truncate">{node.data.name || t("tree.untitled")}</span>
        )}
      </div>
    </div>
  );

  return (
    <ContextMenu>
      <ContextMenuTrigger asChild>{rowBody}</ContextMenuTrigger>
      <ContextMenuContent className="w-52">
        {isFolder && (
          <ContextMenuItem
            onSelect={() => onCreateChildFolder(node.data.folderPath)}
          >
            {t("menu.newFolderInside")}
          </ContextMenuItem>
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
