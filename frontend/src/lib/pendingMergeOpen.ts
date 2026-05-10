/**
 * #107a — pending "open merge dialog for note X" requests.
 *
 * Two paths cover the two states an inbox click can land in:
 *
 * 1. Note is NOT already open. The chip calls openNote(id) which
 *    activates a new tab. The NoteView for the new note mounts and
 *    its useQuery resolves a few hundred ms later. By the time the
 *    event would fire, the listener isn't registered yet — the
 *    event is lost. So we ALSO push the id onto a queue here, and
 *    NoteView's mount-time effect drains the queue.
 *
 * 2. Note IS already open. The custom event fires while the
 *    listener is attached and matches.
 *
 * Both paths consume from the same queue so a single click never
 * results in a double-open.
 */

const pending = new Set<string>();

export function queueMergeOpen(noteId: string): void {
  pending.add(noteId);
}

/** True iff the queue had this note id; consuming it. */
export function takePendingMergeOpen(noteId: string): boolean {
  if (!pending.has(noteId)) return false;
  pending.delete(noteId);
  return true;
}

export const MERGE_OPEN_EVENT = "knowlet:open-merge-dialog";
