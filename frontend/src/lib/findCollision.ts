/**
 * Tree-cache collision checks for note + folder name uniqueness.
 *
 * The backend doesn't enforce per-folder title uniqueness for notes
 * (ULID filenames mean two notes can coexist with the same title —
 * Bear's behaviour), but the file tree displays titles directly, so
 * a collision shows up as two visually identical rows. Same story
 * for folders, except `mkdir_folder` is idempotent so a duplicate
 * is silently a no-op rather than a confusing dupe row.
 *
 * We pre-flight against the cached tree before firing the mutation,
 * so the user gets a friendly alert (in `FileTree.commitPending` /
 * `FileTree.onRename` / `NoteView.submitTitle`) instead of either
 * a silent no-op or a backend 409. Each rename callsite passes an
 * `excludeId` so the entity being renamed doesn't collide with
 * itself.
 */

import type { TreeFolder } from "@/api/types";

/** Walk the tree to the folder identified by a slash-separated path.
 *  Empty string = root. Returns null if any segment is missing. */
function walkTo(root: TreeFolder, parentPath: string): TreeFolder | null {
  if (!parentPath) return root;
  let cursor: TreeFolder | undefined = root;
  for (const seg of parentPath.split("/")) {
    cursor = cursor.folders.find((f) => f.name === seg);
    if (!cursor) return null;
  }
  return cursor;
}

/**
 * True if a note with `title` (case-insensitive) already lives in
 * `parentPath`. Pass `excludeNoteId` to skip the note being renamed
 * (a note renaming to its own current title is a no-op, not a clash).
 */
export function noteTitleClashesIn(
  root: TreeFolder | undefined,
  parentPath: string,
  title: string,
  excludeNoteId?: string,
): boolean {
  if (!root) return false;
  const folder = walkTo(root, parentPath);
  if (!folder) return false;
  const lower = title.toLowerCase();
  return folder.notes.some(
    (n) => n.id !== excludeNoteId && n.title.toLowerCase() === lower,
  );
}

/**
 * True if a folder named `name` (case-insensitive) already exists
 * directly under `parentPath`. Pass `excludeFolderPath` to skip the
 * folder being renamed (full path, e.g. `projects/knowlet`).
 */
export function folderNameClashesIn(
  root: TreeFolder | undefined,
  parentPath: string,
  name: string,
  excludeFolderPath?: string,
): boolean {
  if (!root) return false;
  const folder = walkTo(root, parentPath);
  if (!folder) return false;
  const lower = name.toLowerCase();
  return folder.folders.some(
    (f) => f.path !== excludeFolderPath && f.name.toLowerCase() === lower,
  );
}
