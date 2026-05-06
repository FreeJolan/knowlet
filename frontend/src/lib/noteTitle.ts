/**
 * Canonical title-normalization for notes.
 *
 * The on-disk filename is always `<ULID>.md` — the title lives in
 * frontmatter, separate from the file extension. We keep the title
 * a *concept-layer* string (no extension), matching Bear / Notion /
 * Logseq conventions and our own existing rule for `_attachments/`
 * and `_templates/`: storage details belong to the system, not the
 * user.
 *
 * Strip a trailing `.md` (case-insensitive) from any user-supplied
 * title — at create time AND at rename time — so the tree never
 * shows `foo` and `foo.md` as two near-identical rows. The dogfood
 * report that motivated this: `111` and `111.md` looked identical
 * but were two different notes, because the strip was only applied
 * at create.
 *
 * Returns the trimmed + extension-stripped title. Empty string out
 * means the input was nothing usable (caller should treat as cancel).
 */
export function normalizeNoteTitle(raw: string): string {
  return raw.trim().replace(/\.md$/i, "");
}
