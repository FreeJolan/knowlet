/**
 * Phase 1 B markdown editor — CodeMirror 6 wrapped via @uiw/react-codemirror.
 *
 * Design choice: this component is *uncontrolled* in steady state. The
 * `initialValue` prop seeds the doc on mount, then the editor owns the
 * source of truth — `onChange` pushes the latest text up, but the parent
 * never reaches back in to set `value`. That avoids the classic React
 * controlled-CodeMirror race where every keystroke triggers a re-render,
 * which dispatches a sync transaction, which can clobber the user's
 * very-next keystroke if the transaction round-trips through React state.
 *
 * To switch to a different note, the parent remounts this component with
 * a new `key={noteId}` — that reseeds via `initialValue` cleanly.
 *
 * Cmd+B / Cmd+I / Cmd+K are wired with high precedence so the browser's
 * native contenteditable "bold" / "italic" / "open URL bar" handlers
 * don't preempt them.
 */

import { autocompletion } from "@codemirror/autocomplete";
import { markdown, markdownLanguage } from "@codemirror/lang-markdown";
import { languages } from "@codemirror/language-data";
import { EditorSelection, type Extension, Prec } from "@codemirror/state";
import { EditorView, keymap } from "@codemirror/view";
import CodeMirror from "@uiw/react-codemirror";
import { useMemo } from "react";

import type { TemplateSummary } from "@/api/client";
import type { TreeFolder } from "@/api/types";

import { imageUploadExtension } from "./imageUpload";
import { templateSlashSource } from "./templateSlash";
import {
  wikilinkReopenOnDelete,
  wikilinkSources,
} from "./wikilinkAutocomplete";

function wrapSelection(view: EditorView, marker: string): boolean {
  const { state } = view;
  const changes = state.changeByRange((range) => {
    const m = marker.length;
    if (range.empty) {
      return {
        changes: { from: range.from, insert: marker + marker },
        range: EditorSelection.cursor(range.from + m),
      };
    }
    return {
      changes: [
        { from: range.from, insert: marker },
        { from: range.to, insert: marker },
      ],
      range: EditorSelection.range(range.from + m, range.to + m),
    };
  });
  view.dispatch(changes, { scrollIntoView: true });
  view.focus();
  return true;
}

function insertLink(view: EditorView): boolean {
  const { state } = view;
  const changes = state.changeByRange((range) => {
    const selected = state.sliceDoc(range.from, range.to);
    const insert = `[${selected}]()`;
    const cursorAt = range.from + insert.length - 1;
    return {
      changes: { from: range.from, to: range.to, insert },
      range: EditorSelection.cursor(cursorAt),
    };
  });
  view.dispatch(changes, { scrollIntoView: true });
  view.focus();
  return true;
}

const markdownKeymap = Prec.high(
  keymap.of([
    { key: "Mod-b", preventDefault: true, run: (v) => wrapSelection(v, "**") },
    { key: "Mod-i", preventDefault: true, run: (v) => wrapSelection(v, "*") },
    { key: "Mod-k", preventDefault: true, run: insertLink },
  ]),
);

const paperTheme = EditorView.theme({
  "&": {
    height: "100%",
    fontSize: "16px",
    background: "transparent",
    color: "var(--ink)",
  },
  ".cm-scroller": {
    // Match the kn-md preview stack — see globals.css. Sans-serif keeps
    // CJK + Latin glyphs on the same baseline, with PingFang SC / Geist
    // both supporting a true 700 bold.
    fontFamily: "var(--kn-font-body)",
    lineHeight: "1.7",
    padding: "8px 0",
    overflow: "auto",
  },
  ".cm-content": {
    caretColor: "var(--ring)",
    padding: "0",
  },
  ".cm-cursor, .cm-dropCursor": {
    borderLeftColor: "var(--ring)",
    borderLeftWidth: "2px",
  },
  "&.cm-focused .cm-selectionBackground, ::selection": {
    background: "var(--accent-soft) !important",
  },
  ".cm-selectionBackground": {
    background: "var(--accent-tint) !important",
  },
  ".cm-activeLine": {
    background: "transparent",
  },
  ".cm-gutters": {
    display: "none",
  },
  "&.cm-focused": {
    outline: "none",
  },
});

type Props = {
  /**
   * Seeds the editor doc on mount. Updates to this prop AFTER mount are
   * IGNORED — the parent should remount via `key=` to reseed.
   */
  initialValue: string;
  onChange: (next: string) => void;
  onBlur?: () => void;
  readOnly?: boolean;
  /**
   * Returns the latest tree snapshot, or undefined if the cache is
   * empty. Used by the `[[` wiki-link autocomplete to suggest titles
   * without an extra round-trip per keystroke.
   */
  getTree?: () => TreeFolder | undefined;
  /**
   * Async (cache-aware) fetch of a target note's body. Used by the
   * `[[Title#partial` heading completion path. Returning null disables
   * heading completion for that target without breaking the popup.
   */
  getNoteBody?: (noteId: string) => Promise<string | null>;
  /**
   * Cached templates list for the `/` slash command. When present
   * (alongside `fetchTemplateBody` + `substituteTemplate` + the i18n
   * labels), typing `/` at line start opens an inline template picker
   * that inserts the template body at the cursor.
   */
  getTemplates?: () => TemplateSummary[];
  fetchTemplateBody?: (id: string) => Promise<string | null>;
  substituteTemplate?: (body: string) => string;
  templateSlashLabels?: { insert: string; empty: string };
  /**
   * Notified once when CodeMirror has mounted, with the live view.
   * Used by NoteView to attach split-mode scroll-sync listeners on
   * `view.scrollDOM` and to drive editor-side scroll programmatically.
   * Receives `null` on unmount so the parent can drop its ref.
   */
  onViewMount?: (view: EditorView | null) => void;
};

export function MarkdownEditor({
  initialValue,
  onChange,
  onBlur,
  readOnly,
  getTree,
  getNoteBody,
  getTemplates,
  fetchTemplateBody,
  substituteTemplate,
  templateSlashLabels,
  onViewMount,
}: Props) {
  const extensions = useMemo<Extension[]>(() => {
    // Collect all our domain completion sources into a single
    // `autocompletion()` extension. CM6 doesn't merge multiple
    // separate autocompletion configs cleanly — a single one keeps
    // the keymap + popup behaviour consistent across `[[` and `/`.
    const sources = [];
    if (getTree && getNoteBody) {
      sources.push(...wikilinkSources({ getTree, getNoteBody }));
    }
    if (
      getTemplates &&
      fetchTemplateBody &&
      substituteTemplate &&
      templateSlashLabels
    ) {
      sources.push(
        templateSlashSource({
          getTemplates,
          fetchTemplateBody,
          substitute: substituteTemplate,
          labels: templateSlashLabels,
        }),
      );
    }
    return [
      markdownKeymap,
      markdown({ base: markdownLanguage, codeLanguages: languages }),
      imageUploadExtension(),
      ...(sources.length > 0
        ? [
            autocompletion({
              override: sources,
              activateOnTyping: true,
              closeOnBlur: true,
              icons: false,
            }),
            wikilinkReopenOnDelete(),
          ]
        : []),
      paperTheme,
      EditorView.lineWrapping,
    ];
    // Closures are stable per QueryClient; we intentionally don't
    // rebuild the editor on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <CodeMirror
      // Pass initialValue via `value` only on first render. After mount,
      // react-codemirror's effect compares prop to current doc and skips
      // when equal — but to fully avoid pushback, the parent passes the
      // SAME initialValue forever for this mount; remount on note swap.
      value={initialValue}
      onChange={onChange}
      onBlur={onBlur}
      extensions={extensions}
      basicSetup={{
        lineNumbers: false,
        foldGutter: false,
        highlightActiveLine: false,
        highlightActiveLineGutter: false,
      }}
      readOnly={readOnly ?? false}
      theme="none"
      style={{ height: "100%" }}
      // @uiw/react-codemirror fires this once after the EditorView is
      // first constructed; null isn't passed on unmount (the wrapper
      // doesn't expose that) so we settle for "view set when mounted,
      // stale ref dropped by parent on next note's mount via key=".
      onCreateEditor={(view) => {
        onViewMount?.(view);
      }}
    />
  );
}
