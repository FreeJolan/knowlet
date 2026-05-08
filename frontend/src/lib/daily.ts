/**
 * Phase 2 D / 2.D.1 — Daily notes.
 *
 * Bear / Obsidian / Reflect all expose a "today's note" affordance.
 * In knowlet a daily note is just a regular note titled
 * `YYYY-MM-DD` placed under a `daily/` folder. The keyboard shortcut
 * `Cmd+Shift+D` opens (or creates) today's note in a tab.
 *
 * Idempotency:
 *   - If a note titled today's local-date already exists in `daily/`,
 *     reuse it.
 *   - Otherwise, create the folder if missing and a fresh empty note.
 *
 * Why local date, not UTC: a user writing a journal at 23:30 in
 * UTC+8 expects "today" to be the local calendar day, not yesterday.
 * `Date#toISOString` gives UTC; we format from local components.
 *
 * Template integration is deferred. If the user keeps a template
 * named exactly "daily" under `_templates/`, we could auto-apply it
 * here (createBlankNote already accepts `templateId`); for v1 we
 * always create empty so the affordance ships without a template-
 * lookup detour.
 */

import { createBlankNote, createFolder, getTree } from "@/api/client";
import type { TreeFolder } from "@/api/types";
import type { QueryClient } from "@tanstack/react-query";

import { QK } from "./queryClient";

const DAILY_FOLDER = "daily";

/** Today's date in `YYYY-MM-DD` (local time, not UTC). */
export function todayLocal(): string {
  const d = new Date();
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

/** Walk the tree to find an existing note with `title` in `folder`. */
function findInFolder(
  root: TreeFolder | undefined,
  folderName: string,
  title: string,
): string | null {
  if (!root) return null;
  const stack: TreeFolder[] = [root];
  while (stack.length) {
    const f = stack.pop();
    if (!f) continue;
    if (f.name === folderName || f.path === folderName) {
      for (const n of f.notes) if (n.title === title) return n.id;
    }
    for (const sub of f.folders) stack.push(sub);
  }
  return null;
}

/** Whether the tree currently has a top-level folder named `daily/`. */
function hasDailyFolder(root: TreeFolder | undefined): boolean {
  if (!root) return false;
  return root.folders.some((f) => f.name === DAILY_FOLDER);
}

/**
 * Open today's daily note — find or create. Returns the note ID so
 * the caller can hand it to whatever opens notes (tabs, NoteView).
 *
 * Throws on backend error so the caller can surface a toast / log.
 */
export async function openOrCreateTodayDailyNote(
  qc: QueryClient,
): Promise<string> {
  const date = todayLocal();
  // Force a fresh tree fetch so we don't race with a daily note the
  // user just made in another tab. The query cost is one tree GET.
  const tree = await qc.fetchQuery<TreeFolder>({
    queryKey: QK.tree,
    queryFn: getTree,
  });

  // Reuse existing note if there is one for today.
  const existingId = findInFolder(tree, DAILY_FOLDER, date);
  if (existingId) return existingId;

  // Ensure the folder exists. createFolder is idempotent on the
  // backend (returns 409 on conflict); we tolerate that.
  if (!hasDailyFolder(tree)) {
    try {
      await createFolder(DAILY_FOLDER);
    } catch (err) {
      // 409 conflict means another tab raced ahead — fine.
      const status = (err as { status?: number }).status;
      if (status !== 409) throw err;
    }
  }

  const fresh = await createBlankNote({
    title: date,
    folder: DAILY_FOLDER,
  });

  // Bust caches so the file tree + tab strip can pick up the new note
  // without a manual refresh.
  await qc.invalidateQueries({ queryKey: QK.tree });

  return fresh.id;
}
