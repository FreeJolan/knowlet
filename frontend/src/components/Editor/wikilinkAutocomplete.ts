/**
 * Phase 1 B slice 7 — `[[` autocomplete for wiki-links.
 *
 * Two trigger zones:
 *   1. `[[<partial-title>`  → vault note titles (sync, from cached tree)
 *   2. `[[<title>#<partial>` → headings of the target note
 *      (async — fetch cached body via `getNoteBody`, parse `#` lines)
 *
 * Selecting a title-completion inserts `Title]]`. Selecting a heading
 * inserts the literal heading text + `]]`; the click-time scroller
 * re-slugs the heading via the same `github-slugger` rehype-slug uses,
 * so `[[Note#Some Heading]]` jumps to `#some-heading`.
 *
 * The popup also re-opens on backspace inside an existing wikilink
 * (default CM6 `activateOnTyping` only fires on character INSERT, which
 * surprised dogfood when editing an existing `[[Title]]`).
 */

import {
  type CompletionContext,
  type CompletionResult,
  type CompletionSource,
  startCompletion,
} from "@codemirror/autocomplete";
import type { Extension } from "@codemirror/state";
import { EditorView } from "@codemirror/view";

import type { TreeFolder, TreeNote } from "@/api/types";

/** Walk the cached tree, collecting every note's title + id. */
function flattenTitles(root: TreeFolder | undefined): TreeNote[] {
  if (!root) return [];
  const out: TreeNote[] = [];
  const stack: TreeFolder[] = [root];
  while (stack.length) {
    const f = stack.pop();
    if (!f) continue;
    out.push(...f.notes);
    for (const sub of f.folders) stack.push(sub);
  }
  return out;
}

/** Find a cached note in the tree by title (case-insensitive). */
function findNoteByTitle(
  root: TreeFolder | undefined,
  target: string,
): TreeNote | null {
  if (!root) return null;
  const lower = target.toLowerCase();
  for (const n of flattenTitles(root)) {
    if (n.title.toLowerCase() === lower) return n;
  }
  return null;
}

/** Parse a markdown body for ATX headings (`# Heading` … `###### x`).
 *  Returns level + raw text + 1-based line number, in document order.
 *  We skip headings inside fenced code blocks because ```\n# inside ```
 *  looks like a heading otherwise.
 *
 *  Exported so the Outline panel (Phase 1 D slice 1) can reuse the
 *  same parser. The slugged anchor (rehype-slug) is the consumer's
 *  job; this just gives raw level + text + line. */
export interface ParsedHeading {
  level: number;
  text: string;
  /** 1-based line number in `body`. Used by the Outline panel to
   *  scroll the CodeMirror editor (in split mode) alongside the
   *  preview's anchor jump, so both panes stay in sync. */
  line: number;
}

export function parseHeadings(body: string): ParsedHeading[] {
  const out: ParsedHeading[] = [];
  let inFence = false;
  const lines = body.split("\n");
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i] ?? "";
    if (/^\s*```/.test(line)) {
      inFence = !inFence;
      continue;
    }
    if (inFence) continue;
    const m = /^(#{1,6})\s+(.+?)\s*#*\s*$/.exec(line);
    if (m) {
      out.push({ level: m[1]!.length, text: m[2]!.trim(), line: i + 1 });
    }
  }
  return out;
}

/** Match `[[…` where `…` is the partial title (no `#` yet). */
const TITLE_TRIGGER = /\[\[([^\]\n#|]*)$/;
/** Match `[[Title#partial` — captures title + heading partial. */
const HEADING_TRIGGER = /\[\[([^\]\n#|]+)#([^\]\n]*)$/;

export type WikilinkAutocompleteOptions = {
  getTree: () => TreeFolder | undefined;
  /** Async fetch + cache of the target note's body. Returns null if
   *  the note isn't known. Implementation usually wraps QueryClient. */
  getNoteBody: (noteId: string) => Promise<string | null>;
};

/**
 * The two completion sources (title + heading) used by `[[…`
 * autocomplete. Exported as a list so the host editor can merge them
 * with other domain-specific sources (e.g. the `/` template slash)
 * into a single `autocompletion()` extension — multiple separate
 * `autocompletion()` calls compete for the same popup and lead to
 * inconsistent keymap behaviour.
 */
export function wikilinkSources(
  opts: WikilinkAutocompleteOptions,
): CompletionSource[] {
  const { getTree, getNoteBody } = opts;

  function titleSource(context: CompletionContext): CompletionResult | null {
    const line = context.state.doc.lineAt(context.pos);
    const before = context.state.sliceDoc(line.from, context.pos);
    const m = TITLE_TRIGGER.exec(before);
    if (!m) return null;
    const partial = m[1] ?? "";
    if (partial.includes("|")) return null;
    const all = flattenTitles(getTree());
    if (all.length === 0) return null;
    return {
      from: context.pos - partial.length,
      to: context.pos,
      options: all.map((n) => ({
        label: n.title,
        type: "text",
        apply: (view, _completion, from, to) => {
          // Reuse closeBrackets-injected `]]` if present, else add our own.
          const after = view.state.sliceDoc(to, to + 2);
          const closing = after === "]]" ? "" : "]]";
          const insert = `${n.title}${closing}`;
          const cursorPast = from + n.title.length + 2;
          view.dispatch({
            changes: { from, to, insert },
            selection: { anchor: cursorPast },
          });
        },
      })),
      validFor: /^[^\]\n#|]*$/,
    };
  }

  async function headingSource(
    context: CompletionContext,
  ): Promise<CompletionResult | null> {
    const line = context.state.doc.lineAt(context.pos);
    const before = context.state.sliceDoc(line.from, context.pos);
    const m = HEADING_TRIGGER.exec(before);
    if (!m) return null;
    const titleRaw = m[1]!;
    const partial = m[2] ?? "";
    const note = findNoteByTitle(getTree(), titleRaw.trim());
    if (!note) return null;
    const body = await getNoteBody(note.id);
    if (body == null) return null;
    const headings = parseHeadings(body);
    if (headings.length === 0) return null;
    return {
      from: context.pos - partial.length,
      to: context.pos,
      options: headings.map((h) => ({
        label: h.text,
        // Indent the popup label by heading depth so visual hierarchy
        // is obvious: `# top`, `## sub`, etc. CM6 strips this when
        // accepting the completion.
        detail: "#".repeat(h.level),
        type: "text",
        apply: (view, _completion, from, to) => {
          const after = view.state.sliceDoc(to, to + 2);
          const closing = after === "]]" ? "" : "]]";
          const insert = `${h.text}${closing}`;
          const cursorPast = from + h.text.length + 2;
          view.dispatch({
            changes: { from, to, insert },
            selection: { anchor: cursorPast },
          });
        },
      })),
      validFor: /^[^\]\n]*$/,
    };
  }

  return [titleSource, headingSource];
}

/**
 * Re-trigger autocomplete on backspace inside a wikilink trigger zone.
 * CM6's default `activateOnTyping` fires only on character INSERT, so
 * editing an existing `[[Title]]` by deleting characters surprised
 * the user — no popup until they typed something new.
 *
 * Returned as a standalone Extension so the host editor includes it
 * once alongside the merged `autocompletion()`.
 */
export function wikilinkReopenOnDelete(): Extension {
  return EditorView.updateListener.of((update) => {
    if (!update.docChanged) return;
    const isDelete = update.transactions.some(
      (tr) =>
        tr.isUserEvent("delete.backward") ||
        tr.isUserEvent("delete.forward") ||
        tr.isUserEvent("delete.selection"),
    );
    if (!isDelete) return;
    const view = update.view;
    const { state } = view;
    const pos = state.selection.main.head;
    const line = state.doc.lineAt(pos);
    const before = state.sliceDoc(line.from, pos);
    if (TITLE_TRIGGER.test(before) || HEADING_TRIGGER.test(before)) {
      queueMicrotask(() => startCompletion(view));
    }
  });
}
