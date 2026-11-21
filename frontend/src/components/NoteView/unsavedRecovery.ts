/**
 * Unsaved editor text set aside when a save was refused because the note
 * changed on disk (sync auto-pull, another process, another tab) and the
 * editor reloaded the newer version.
 *
 * Kept until the user copies / restores / dismisses it, and mirrored to
 * localStorage so it survives switching notes or reloading the page.
 * Storage failures fall back to memory for this page's lifetime.
 */

export type UnsavedRecovery = { body: string; savedAt: string };

export const UNSAVED_RECOVERY_EVENT = "knowlet:unsaved-recovery";

const memory = new Map<string, UnsavedRecovery>();
const storageKey = (noteId: string) => `knowlet:unsaved-recovery:${noteId}`;

export function saveUnsavedRecovery(noteId: string, body: string): void {
  const entry: UnsavedRecovery = { body, savedAt: new Date().toISOString() };
  memory.set(noteId, entry);
  try {
    window.localStorage.setItem(storageKey(noteId), JSON.stringify(entry));
  } catch {
    // quota / disabled storage — the in-memory copy still holds it
  }
  window.dispatchEvent(
    new CustomEvent(UNSAVED_RECOVERY_EVENT, { detail: { noteId } }),
  );
}

export function loadUnsavedRecovery(noteId: string): UnsavedRecovery | null {
  const inMemory = memory.get(noteId);
  if (inMemory) return inMemory;
  try {
    const raw = window.localStorage.getItem(storageKey(noteId));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<UnsavedRecovery>;
    if (typeof parsed.body !== "string") return null;
    return { body: parsed.body, savedAt: String(parsed.savedAt ?? "") };
  } catch {
    return null;
  }
}

export function clearUnsavedRecovery(noteId: string): void {
  memory.delete(noteId);
  try {
    window.localStorage.removeItem(storageKey(noteId));
  } catch {
    // ignore
  }
}
