/**
 * Client-side coordination for whole-note writes.
 *
 * `PUT /api/notes/{id}` replaces title + tags + body in one shot and the
 * backend has no revision check, so two writers that each read-modify-
 * write the same note (the editor's autosave, the tree's rename, the AI
 * diff "apply") can silently undo each other. Three pieces narrow that:
 *
 *  - `runExclusive(key, fn)` — per-key FIFO mutex. `api/client.ts` runs
 *    every note PUT (and every GET-then-PUT) through it, so a
 *    read-modify-write can never interleave with another PUT of the same
 *    note issued from this page.
 *  - `waitForPendingNoteMutations(qc, id)` — waits until no TanStack
 *    mutation targeting the note is pending. A pending mutation includes
 *    one sitting in its retry back-off, which holds no lock but will PUT
 *    again.
 *  - `registerNoteTitleWriter` — lets the view that owns a note's
 *    metadata take title changes made elsewhere (tree rename).
 */

import type {
  MutationCache,
  MutationKey,
  QueryClient,
} from "@tanstack/react-query";

import type { NoteFull } from "@/api/types";

const tails = new Map<string, Promise<void>>();

/** Run `fn` after every earlier `runExclusive` call for the same key has
 *  settled (success or failure). Calls for different keys don't wait on
 *  each other. `fn` must not call `runExclusive` with the same key, or it
 *  will wait on itself. */
export function runExclusive<T>(key: string, fn: () => Promise<T>): Promise<T> {
  const prev = tails.get(key) ?? Promise.resolve();
  const run = prev.then(fn);
  const tail = run.then(
    () => undefined,
    () => undefined,
  );
  tails.set(key, tail);
  void tail.then(() => {
    if (tails.get(key) === tail) tails.delete(key);
  });
  return run;
}

/**
 * Title writers for notes whose metadata is owned by a mounted view.
 *
 * A view that keeps its own copy of a note's title (and builds every PUT
 * from that copy) registers a writer for the note it has loaded. Other
 * surfaces that rename the note (the file tree) call that writer instead
 * of issuing their own PUT, so the owner's copy changes before its next
 * save is built and that save can't write the old title back.
 * The writer resolves with the server's note after the title is saved and
 * rejects if the write fails (the owner rolls back its own state).
 */
export type NoteTitleWriter = (title: string) => Promise<NoteFull>;

const titleWriters = new Map<string, NoteTitleWriter>();

/** Returns an unregister function; only removes the entry if it is still
 *  the one registered here. */
export function registerNoteTitleWriter(
  noteId: string,
  writer: NoteTitleWriter,
): () => void {
  titleWriters.set(noteId, writer);
  return () => {
    if (titleWriters.get(noteId) === writer) titleWriters.delete(noteId);
  };
}

export function getNoteTitleWriter(noteId: string): NoteTitleWriter | undefined {
  return titleWriters.get(noteId);
}

/** Upper bound for `waitForPendingNoteMutations`. Must exceed the longest
 *  autosave retry window (NoteView: 3 retries, back-off capped at 10 s,
 *  ~14 s worst case) so a rename never lands inside it. */
export const PENDING_NOTE_WRITE_TIMEOUT_MS = 20_000;

type AnyMutation = ReturnType<MutationCache["getAll"]>[number];

function targetsNote(m: AnyMutation, noteId: string): boolean {
  const vars = m.state.variables;
  return (
    typeof vars === "object" &&
    vars !== null &&
    (vars as { id?: unknown }).id === noteId
  );
}

function hasKey(m: AnyMutation, key: MutationKey | undefined): boolean {
  if (!key) return false;
  const own = m.options.mutationKey;
  return (
    own !== undefined &&
    own.length === key.length &&
    own.every((part, i) => part === key[i])
  );
}

/**
 * Resolve once no pending mutation in `qc` targets `noteId` — "targets"
 * meaning its variables are an object with `id === noteId`, the shape
 * every note-writing mutation in the app uses. Mutations whose
 * `mutationKey` equals `ignoreKey` are skipped (pass the caller's own key
 * so it doesn't wait on itself). Resolves anyway after `timeoutMs`; the
 * caller still serializes its actual write via `runExclusive`.
 */
export function waitForPendingNoteMutations(
  qc: QueryClient,
  noteId: string,
  {
    ignoreKey,
    timeoutMs = PENDING_NOTE_WRITE_TIMEOUT_MS,
  }: { ignoreKey?: MutationKey; timeoutMs?: number } = {},
): Promise<void> {
  const cache = qc.getMutationCache();
  const busy = () =>
    cache
      .getAll()
      .some(
        (m) =>
          m.state.status === "pending" &&
          !hasKey(m, ignoreKey) &&
          targetsNote(m, noteId),
      );
  if (!busy()) return Promise.resolve();
  return new Promise((resolve) => {
    let finished = false;
    const finish = () => {
      if (finished) return;
      finished = true;
      window.clearTimeout(timer);
      unsubscribe();
      resolve();
    };
    const unsubscribe = cache.subscribe(() => {
      if (!busy()) finish();
    });
    const timer = window.setTimeout(finish, timeoutMs);
  });
}
