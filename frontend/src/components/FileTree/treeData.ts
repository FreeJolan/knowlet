/**
 * Convert the backend TreeFolder shape into the flat-with-children form
 * react-arborist expects. We tag each node with `kind` so the row renderer
 * can branch on it.
 */

import type { TreeFolder } from "@/api/types";

export type TreeNodeKind = "folder" | "note" | "pending-folder" | "pending-note";

export type TreeNodeData = {
  id: string; // unique in the tree
  name: string; // display label
  kind: TreeNodeKind;
  /** Folder: path under notes/ (empty = root). Note / pending: empty. */
  folderPath: string;
  /** Note: backend note id. Folder / pending: empty. */
  noteId: string;
  /** Note: ISO timestamp for sort. Folder / pending: empty. */
  updatedAt: string;
  /** Pending only: where to drop the new entity. */
  pendingParent?: string;
  children?: TreeNodeData[];
};

export const PENDING_NOTE_ID = "__pending_note__";
export const PENDING_FOLDER_ID = "__pending_folder__";

/**
 * Inject a placeholder row for an in-progress create at the top of its
 * parent folder's children (or top of root if parent is empty).
 */
export function injectPending(
  data: TreeNodeData[],
  pending: { kind: "note" | "folder"; parentPath: string },
): TreeNodeData[] {
  const placeholder: TreeNodeData = {
    id: pending.kind === "note" ? PENDING_NOTE_ID : PENDING_FOLDER_ID,
    name: "",
    kind: pending.kind === "note" ? "pending-note" : "pending-folder",
    folderPath: "",
    noteId: "",
    updatedAt: "",
    pendingParent: pending.parentPath,
  };
  if (!pending.parentPath) {
    return [placeholder, ...data];
  }
  // Walk into the matching folder and prepend.
  const parts = pending.parentPath.split("/");
  function insert(nodes: TreeNodeData[], depth: number): TreeNodeData[] {
    return nodes.map((n) => {
      if (n.kind !== "folder") return n;
      if (n.name !== parts[depth]) return n;
      if (depth === parts.length - 1) {
        return { ...n, children: [placeholder, ...(n.children ?? [])] };
      }
      return { ...n, children: insert(n.children ?? [], depth + 1) };
    });
  }
  return insert(data, 0);
}

export function toArborist(root: TreeFolder): TreeNodeData[] {
  return [
    ...root.folders.map(folderToNode),
    ...root.notes.map((n) => ({
      id: `note:${n.id}`,
      name: n.title || "(无标题)",
      kind: "note" as const,
      folderPath: "",
      noteId: n.id,
      updatedAt: n.updated_at,
    })),
  ];
}

function folderToNode(folder: TreeFolder): TreeNodeData {
  return {
    id: `folder:${folder.path}`,
    name: folder.name,
    kind: "folder",
    folderPath: folder.path,
    noteId: "",
    updatedAt: "",
    children: [
      ...folder.folders.map(folderToNode),
      ...folder.notes.map((n) => ({
        id: `note:${n.id}`,
        name: n.title || "(无标题)",
        kind: "note" as const,
        folderPath: "",
        noteId: n.id,
        updatedAt: n.updated_at,
      })),
    ],
  };
}
