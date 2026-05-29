/**
 * Diff review (Phase 3 Stage 4 P3 + P4).
 *
 * Renders the AI's proposed change to a note as a VS Code-style
 * side-by-side diff via @codemirror/merge's MergeView: the left pane is
 * the current note, and the right pane is the editable AI proposal.
 *
 * P4 invariant: nothing is written until the user clicks 应用 — and
 * even then the write goes through the existing atomic note-save (PUT
 * /api/notes/{id}), which backs up the previous version per ADR-0018.
 * 放弃 / closing discards the proposal; the note is never silently
 * changed.
 */

import { markdown, markdownLanguage } from "@codemirror/lang-markdown";
import { languages } from "@codemirror/language-data";
import { MergeView } from "@codemirror/merge";
import { EditorState } from "@codemirror/state";
import { EditorView } from "@codemirror/view";
import { Check, X } from "lucide-react";
import { useEffect, useRef } from "react";

import { Button } from "@/components/ui/button";

const reviewTheme = EditorView.theme({
  "&": {
    minHeight: "100%",
    fontSize: "15px",
    background: "transparent",
    color: "var(--ink)",
  },
  ".cm-scroller": {
    fontFamily: "var(--kn-font-body)",
    lineHeight: "1.7",
    overflow: "visible",
  },
  ".cm-content": {
    caretColor: "var(--ring)",
    padding: "10px 12px 16px",
  },
  ".cm-gutters": {
    background: "transparent",
    borderRight: "1px solid var(--line-soft)",
    color: "var(--ink-mute)",
  },
  ".cm-activeLine, .cm-activeLineGutter": {
    background: "transparent",
  },
  "&.cm-focused": {
    outline: "none",
  },
});

function renderRevertControl(): HTMLElement {
  const button = document.createElement("button");
  button.type = "button";
  button.setAttribute("aria-label", "用左侧原文还原右侧这一块");
  button.title = "用左侧原文还原右侧这一块";
  button.textContent = "→";
  return button;
}

export function DiffReview({
  oldBody,
  newBody,
  saving = false,
  onAccept,
  onReject,
}: {
  oldBody: string;
  newBody: string;
  saving?: boolean;
  onAccept: (finalBody: string) => void;
  onReject: () => void;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const mergeRef = useRef<MergeView | null>(null);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    host.textContent = "";

    const commonExtensions = [
      markdown({ base: markdownLanguage, codeLanguages: languages }),
      EditorView.lineWrapping,
      reviewTheme,
    ];

    const view = new MergeView({
      parent: host,
      a: {
        doc: oldBody,
        extensions: [
          ...commonExtensions,
          EditorState.readOnly.of(true),
          EditorView.editable.of(false),
        ],
      },
      b: {
        doc: newBody,
        extensions: [...commonExtensions, EditorView.editable.of(true)],
      },
      orientation: "a-b",
      revertControls: "a-to-b",
      renderRevertControl,
      collapseUnchanged: { margin: 4, minSize: 8 },
      diffConfig: { scanLimit: 1000 },
    });
    view.dom.classList.add("kn-diff-merge");
    mergeRef.current = view;
    return () => {
      view.destroy();
      mergeRef.current = null;
    };
  }, [oldBody, newBody]);

  const apply = () => {
    const text = mergeRef.current?.b.state.doc.toString() ?? newBody;
    onAccept(text);
  };

  return (
    <div data-testid="diff-review" className="flex h-full min-h-0 flex-col">
      <div
        className="flex shrink-0 items-center justify-between border-b px-3 py-2"
        style={{ borderColor: "var(--line)", background: "var(--panel)" }}
      >
        <div className="text-sm" style={{ color: "var(--ink)" }}>
          AI 建议的改动 · 双栏审阅，确认后应用
        </div>
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="ghost"
            data-testid="diff-reject"
            onClick={onReject}
            disabled={saving}
          >
            <X className="mr-1 size-3" />
            放弃
          </Button>
          <Button
            size="sm"
            data-testid="diff-apply"
            onClick={apply}
            disabled={saving}
          >
            <Check className="mr-1 size-3" />
            {saving ? "应用中…" : "应用"}
          </Button>
        </div>
      </div>
      <div
        className="grid shrink-0 grid-cols-2 border-b text-xs font-medium"
        style={{
          borderColor: "var(--line)",
          background: "var(--card-paper)",
          color: "var(--ink-mute)",
        }}
      >
        <div
          data-testid="diff-label-original"
          className="border-r px-3 py-2"
          style={{ borderColor: "var(--line)" }}
        >
          当前正文
        </div>
        <div data-testid="diff-label-proposal" className="px-3 py-2">
          AI 提案
        </div>
      </div>
      <div
        ref={hostRef}
        data-testid="diff-editor"
        className="min-h-0 flex-1 overflow-hidden"
      />
    </div>
  );
}
