/**
 * Convert the backend TreeFolder shape into the flat-with-children form
 * react-arborist expects. We tag each node with `kind` so the row renderer
 * can branch on it.
 */

import type { TreeFolder } from "@/api/types";

export type TreeNodeData = {
  id: string; // unique in the tree — "folder:<path>" or "note:<noteId>"
  name: string; // display label
  kind: "folder" | "note";
  /** Folder: path under notes/ (empty = root). Note: empty. */
  folderPath: string;
  /** Note: backend note id. Folder: empty. */
  noteId: string;
  /** Note: ISO timestamp for sort. Folder: empty. */
  updatedAt: string;
  children?: TreeNodeData[];
};

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
