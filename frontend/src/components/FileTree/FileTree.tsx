/**
 * Vault file tree (Phase 1 A, Slice 2.1 + 2.2 + 2.3).
 *
 * react-arborist gives us virtualization, drag-drop, multi-select and
 * inline rename for free; we own the row renderer + the wiring between
 * Tree events and the backend mutations.
 */

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { ChevronRight, ChevronDown, FileText, Folder, Plus } from "lucide-react";
import { useEffect, useRef, useState } from "react";
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
import { QK } from "@/lib/queryClient";

import { ContextMenu, type ContextMenuItem } from "./ContextMenu";
import { toArborist, type TreeNodeData } from "./treeData";

export interface FileTreeProps {
  selectedNoteId: string | null;
  onSelectNote: (id: string) => void;
  /** True while a tree mutation is in flight; parent can grey out the editor. */
  onMutating?: (busy: boolean) => void;
}

export function FileTree({ selectedNoteId, onSelectNote, onMutating }: FileTreeProps) {
  const qc = useQueryClient();
  const [containerRef, size] = useElementSize();
  const treeRef = useRef<TreeApi<TreeNodeData> | null>(null);
  const [menu, setMenu] = useState<{
    node: TreeNodeData;
    x: number;
    y: number;
  } | null>(null);

  const tree = useQuery({
    queryKey: QK.tree,
    queryFn: getTree,
  });

  // ----- mutations: every one invalidates the tree query so the next render reflects disk -----

  const refresh = () => qc.invalidateQueries({ queryKey: QK.tree });
  const startBusy = () => onMutating?.(true);
  const endBusy = () => onMutating?.(false);

  const renameNoteM = useMutation({
    mutationFn: async ({ id, title }: { id: string; title: string }) => {
      // Pull current note (we need body+tags for PUT).
      const cur = await getNote(id);
      return updateNote(id, { title, tags: cur.tags, body: cur.body });
    },
    onMutate: startBusy,
    onSettled: () => {
      endBusy();
      refresh();
    },
  });
  const renameFolderM = useMutation({
    mutationFn: ({ path, newName }: { path: string; newName: string }) =>
      renameFolder(path, newName),
    onMutate: startBusy,
    onSettled: () => {
      endBusy();
      refresh();
    },
  });
  const createFolderM = useMutation({
    mutationFn: ({ path }: { path: string }) => createFolder(path),
    onMutate: startBusy,
    onSettled: () => {
      endBusy();
      refresh();
    },
  });
  const moveNoteM = useMutation({
    mutationFn: ({ id, target }: { id: string; target: string }) => moveNote(id, target),
    onMutate: startBusy,
    onSettled: () => {
      endBusy();
      refresh();
    },
  });
  const moveFolderM = useMutation({
    mutationFn: ({ src, dstParent }: { src: string; dstParent: string }) =>
      moveFolder(src, dstParent),
    onMutate: startBusy,
    onSettled: () => {
      endBusy();
      refresh();
    },
  });
  const deleteNoteM = useMutation({
    mutationFn: (id: string) => deleteNote(id),
    onMutate: startBusy,
    onSettled: () => {
      endBusy();
      refresh();
    },
  });
  const deleteFolderM = useMutation({
    mutationFn: (path: string) => deleteFolder(path),
    onMutate: startBusy,
    onSettled: () => {
      endBusy();
      refresh();
    },
  });

  // ----- arborist event wiring -----

  const onRename = ({ id, name, node }: { id: string; name: string; node: NodeApi<TreeNodeData> }) => {
    const trimmed = name.trim();
    if (!trimmed) return;
    if (node.data.kind === "note") {
      renameNoteM.mutate({ id: node.data.noteId, title: trimmed });
    } else {
      renameFolderM.mutate({ path: node.data.folderPath, newName: trimmed });
    }
    void id; // unused; arborist passes it for our convenience
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
    // Target folder is the drop-parent's folderPath; null = root.
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

  // ----- right-click menu items -----

  const menuItems = (node: TreeNodeData): ContextMenuItem[] => {
    const items: ContextMenuItem[] = [];
    if (node.kind === "folder") {
      items.push({
        label: "New folder inside",
        onSelect: () => {
          const name = window.prompt("Folder name?");
          if (name?.trim())
            createFolderM.mutate({
              path: node.folderPath ? `${node.folderPath}/${name.trim()}` : name.trim(),
            });
        },
      });
      items.push({
        label: "Rename",
        onSelect: () => {
          const arboristNode = treeRef.current?.get(node.id);
          arboristNode?.edit();
        },
      });
      items.push({
        label: "Delete folder",
        destructive: true,
        onSelect: () => {
          if (
            window.confirm(
              `Delete "${node.name}"? All notes inside go to .trash/.`,
            )
          ) {
            deleteFolderM.mutate(node.folderPath);
          }
        },
      });
    } else {
      items.push({
        label: "Rename",
        onSelect: () => {
          const arboristNode = treeRef.current?.get(node.id);
          arboristNode?.edit();
        },
      });
      items.push({
        label: "Move to root",
        onSelect: () => moveNoteM.mutate({ id: node.noteId, target: "" }),
      });
      items.push({
        label: "Delete",
        destructive: true,
        onSelect: () => {
          if (window.confirm(`Move "${node.name}" to .trash/?`)) {
            deleteNoteM.mutate(node.noteId);
          }
        },
      });
    }
    return items;
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
        className="flex items-center justify-between border-b px-3 py-2"
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
        >
          <Plus className="size-4" />
        </Button>
      </div>
      <div ref={containerRef} className="flex-1 overflow-hidden">
        <Tree<TreeNodeData>
          ref={treeRef}
          data={data}
          openByDefault={false}
          width={size.width}
          height={size.height}
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
          disableEdit={(node: TreeNodeData) =>
            // Disable inline edit on the synthetic root only; everything else is renamable.
            node.id === "root"
          }
        >
          {(props: NodeRendererProps<TreeNodeData>) => (
            <Row
              {...props}
              onContextMenu={(e) => {
                e.preventDefault();
                setMenu({ node: props.node.data, x: e.clientX, y: e.clientY });
              }}
            />
          )}
        </Tree>
      </div>
      {menu && (
        <ContextMenu
          x={menu.x}
          y={menu.y}
          items={menuItems(menu.node)}
          onClose={() => setMenu(null)}
        />
      )}
    </div>
  );
}

// ----- row renderer -----

function Row({
  node,
  style,
  dragHandle,
  onContextMenu,
}: NodeRendererProps<TreeNodeData> & {
  onContextMenu: (e: React.MouseEvent) => void;
}) {
  const isFolder = node.data.kind === "folder";
  const isOpen = node.isOpen;
  return (
    <div
      ref={dragHandle}
      style={style}
      onContextMenu={onContextMenu}
      className={`group flex items-center gap-1 px-2 text-sm rounded-sm cursor-default select-none ${
        node.isSelected ? "bg-accent text-accent-foreground" : "hover:bg-secondary"
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
          className="flex-1 bg-transparent outline-none ring-1 ring-ring rounded-sm px-1"
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
}

// ----- size hook -----

function useElementSize(): [
  React.RefObject<HTMLDivElement | null>,
  { width: number; height: number },
] {
  const ref = useRef<HTMLDivElement | null>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  useEffect(() => {
    if (!ref.current) return;
    const obs = new ResizeObserver((entries) => {
      const e = entries[0];
      if (e) {
        const { width, height } = e.contentRect;
        setSize({ width, height });
      }
    });
    obs.observe(ref.current);
    return () => obs.disconnect();
  }, []);
  return [ref, size];
}
