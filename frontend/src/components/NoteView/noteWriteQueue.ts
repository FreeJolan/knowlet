/**
 * Per-note serialized write queue for NoteView.
 *
 * `PUT /api/notes/{id}` is a full-snapshot write (title + tags + body +
 * aliases) with no version check, and the backend handles requests
 * concurrently. Two overlapping PUTs for the same note can land in
 * either order, and whichever lands last silently reverts the other's
 * fields. NoteView runs every write for a note through
 * `enqueueNoteWrite`, so they execute strictly one after another in call
 * order, and each job builds its payload when it starts — the last write
 * therefore always carries the newest state.
 */

const tails = new Map<string, Promise<void>>();

export function enqueueNoteWrite<T>(
  noteId: string,
  job: () => Promise<T>,
): Promise<T> {
  const prev = tails.get(noteId) ?? Promise.resolve();
  const run = prev.then(job);
  const tail = run.then(
    () => undefined,
    () => undefined,
  );
  tails.set(noteId, tail);
  void tail.then(() => {
    if (tails.get(noteId) === tail) tails.delete(noteId);
  });
  return run;
}
