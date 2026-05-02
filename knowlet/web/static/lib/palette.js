// Pure logic for the Cmd+K palette: classifying a raw query string into
// the right execution mode + computing the result list.
//
// Extracted from app.js so the state machine can be unit-tested without a
// browser / Alpine. The Alpine layer in app.js owns the *state* (notes,
// chatHistory, palette flags) and the rendering; this module is functional.

/**
 * Classify a palette query into one of four modes.
 *
 * Inputs the user typed (after `palette.query.trim()`):
 *   - leading `>`  → ask AI one-shot. payload.text is the rest after `>`.
 *   - leading `+`  → create a new note. payload.text is the title.
 *   - empty / bare → fuzzy match against notes + commands.
 *   - empty input  → "browse" mode (show top notes + commands as-is).
 *
 * Returns: { mode: 'ask'|'newnote'|'fuzzy'|'browse', text: string }
 *   - 'ask' / 'newnote' carry the (possibly-empty) trailing text
 *   - 'fuzzy'  carries the lowercased query
 *   - 'browse' carries an empty string
 */
export function classifyQuery(raw) {
  const q = (raw ?? "").trim();
  if (!q) return { mode: "browse", text: "" };
  if (q.startsWith(">")) return { mode: "ask", text: q.slice(1).trim() };
  if (q.startsWith("+")) return { mode: "newnote", text: q.slice(1).trim() };
  return { mode: "fuzzy", text: q.toLowerCase() };
}

/**
 * Filter a list of notes by case-insensitive title substring.
 * Stable order: preserves the input list's relative ordering (which
 * the caller has typically sorted by `updated_at` already).
 */
export function filterNotes(notes, lowerQuery, limit = 8) {
  if (!Array.isArray(notes)) return [];
  if (!lowerQuery) return notes.slice(0, limit);
  const out = [];
  for (const n of notes) {
    if (out.length >= limit) break;
    if (n && typeof n.title === "string" &&
        n.title.toLowerCase().includes(lowerQuery)) {
      out.push(n);
    }
  }
  return out;
}

/**
 * Filter palette commands by their visible label.
 * Each command must have at least { id, label }; everything else passes
 * through unchanged. `lowerQuery` empty means return all.
 */
export function filterCommands(commands, lowerQuery) {
  if (!Array.isArray(commands)) return [];
  if (!lowerQuery) return commands.slice();
  return commands.filter(
    (c) => c && typeof c.label === "string" &&
           c.label.toLowerCase().includes(lowerQuery)
  );
}
