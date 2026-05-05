/**
 * Vault file tree (Phase 1 A).
 *
 * react-arborist gives us virtualization, drag-drop, multi-select and
 * inline rename for free; we own the row renderer + the wiring between
 * Tree events and the backend mutations. Right-click is delegated to the
 * shadcn ContextMenu (Radix under the hood) — `asChild` merges the menu
 * trigger onto the row element so we don't add an extra DOM node inside
 * the virtualized row.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, FileText, Folder, Plus } from "lucide-react";
import { useRef } from "react";
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
  /** True while a tree mutation is in flight; parent can grey out the editor. */
  onMutating?: (busy: boolean) => void;
}

export function FileTree({ selectedNoteId, onSelectNote, onMutating }: FileTreeProps) {
  const qc = useQueryClient();
  const treeRef = useRef<TreeApi<TreeNodeData> | null>(null);

  const tree = useQuery({
    queryKey: QK.tree,
    queryFn: getTree,
  });

  // ----- mutations: every one invalidates the tree query so the next render reflects disk -----

  const refresh = () => qc.invalidateQueries({ queryKey: QK.tree });
  const startBusy = () => onMutating?.(true);
  const endBusy = () => onMutating?.(false);
  const settled = () => {
    endBusy();
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

  // ----- arborist event wiring -----

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
        `Delete ${nodes.length} item${nodes.length === 1 ? "" : "s"}? Notes go to trash; folders + their contents go to trash.`,
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

  // ----- new-folder at root button -----

  const onNewRootFolder = () => {
    const name = window.prompt("New folder name?");
    if (name?.trim()) createFolderM.mutate({ path: name.trim() });
  };

  if (tree.isLoading) {
    return <div className="p-4 text-sm text-muted-foreground">Loading…</div>;
  }
  if (tree.isError) {
    return (
      <div className="p-4 text-sm text-destructive">
        Failed to load tree.
        <Button variant="link" size="sm" onClick={() => tree.refetch()}>
          Retry
        </Button>
      </div>
    );
  }

  const data = tree.data ? toArborist(tree.data) : [];

  return (
    <div className="flex h-full flex-col">
      <div
        className="flex shrink-0 items-center justify-between border-b px-3 py-2"
        style={{ borderColor: "var(--line)" }}
      >
        <span className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
          Vault
        </span>
        <Button
          variant="ghost"
          size="icon"
          aria-label="New folder"
          onClick={onNewRootFolder}
          className="size-7"
        >
          <Plus className="size-4" />
        </Button>
      </div>
      <div className="min-h-0 flex-1 overflow-hidden">
        {data.length === 0 ? (
          <div className="px-3 py-6 text-sm text-muted-foreground">
            Empty vault. Use <kbd className="rounded bg-muted px-1">+</kbd> above
            to add a folder, or run <code className="font-mono">knowlet add</code>
            .
          </div>
        ) : (
          // Pass percentage strings so react-arborist sizes itself against
          // its parent — no ResizeObserver / ref dance needed. The parent
          // is `flex-1` inside a `flex-col` Panel, so it has finite px space.
          <Tree<TreeNodeData>
              ref={treeRef}
              data={data}
              openByDefault={true}
              width="100%"
              height={5000}
              rowHeight={28}
              indent={16}
              onRename={onRename}
              onMove={onMove}
              onDelete={onDelete}
              selection={selectedNoteId ? `note:${selectedNoteId}` : undefined}
              onActivate={(node) => {
                if (node.data.kind === "note") onSelectNote(node.data.noteId);
                else node.toggle();
              }}
            >
              {(props: NodeRendererProps<TreeNodeData>) => (
                <Row
                  {...props}
                  onCreateChildFolder={(parentPath) => {
                    const name = window.prompt("Folder name?");
                    if (name?.trim()) {
                      createFolderM.mutate({
                        path: parentPath ? `${parentPath}/${name.trim()}` : name.trim(),
                      });
                    }
                  }}
                  onMoveToRoot={(noteId) =>
                    moveNoteM.mutate({ id: noteId, target: "" })
                  }
                  onDeleteFolder={(folderPath, name) => {
                    if (
                      window.confirm(
                        `Delete "${name}"? All notes inside go to .trash/.`,
                      )
                    ) {
                      deleteFolderM.mutate(folderPath);
                    }
                  }}
                  onDeleteNote={(noteId, name) => {
                    if (window.confirm(`Move "${name}" to .trash/?`)) {
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
  onCreateChildFolder: (parentPath: string) => void;
  onMoveToRoot: (noteId: string) => void;
  onDeleteFolder: (folderPath: string, name: string) => void;
  onDeleteNote: (noteId: string, name: string) => void;
}

function Row({
  node,
  style,
  dragHandle,
  onCreateChildFolder,
  onMoveToRoot,
  onDeleteFolder,
  onDeleteNote,
}: RowProps) {
  const isFolder = node.data.kind === "folder";
  const isOpen = node.isOpen;

  const rowBody = (
    <div
      ref={dragHandle}
      style={style}
      className={`group flex h-full items-center gap-1 px-2 text-sm rounded-sm cursor-default select-none ${
        node.isSelected
          ? "bg-accent/20 text-accent-foreground"
          : "hover:bg-secondary/60"
      }`}
      onClick={() => {
        if (isFolder) node.toggle();
        else node.activate();
      }}
    >
      {isFolder ? (
        isOpen ? (
          <ChevronDown className="size-3 shrink-0 text-muted-foreground" />
        ) : (
          <ChevronRight className="size-3 shrink-0 text-muted-foreground" />
        )
      ) : (
        <span className="w-3" />
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
        />
      ) : (
        <span className="truncate">{node.data.name}</span>
      )}
    </div>
  );

  return (
    <ContextMenu>
      <ContextMenuTrigger asChild>{rowBody}</ContextMenuTrigger>
      <ContextMenuContent className="w-56">
        {isFolder && (
          <ContextMenuItem
            onSelect={() => onCreateChildFolder(node.data.folderPath)}
          >
            New folder inside
          </ContextMenuItem>
        )}
        <ContextMenuItem onSelect={() => node.edit()}>Rename</ContextMenuItem>
        {!isFolder && (
          <ContextMenuItem onSelect={() => onMoveToRoot(node.data.noteId)}>
            Move to root
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
          Delete
        </ContextMenuItem>
      </ContextMenuContent>
    </ContextMenu>
  );
}

