/**
 * Diff review (Phase 3 Stage 4 P3 + P4).
 *
 * Renders the AI's proposed change to a note as a Cursor-style inline
 * diff via @codemirror/merge's unifiedMergeView: the editor holds the
 * proposed (new) body, the original (old) body is the baseline, and
 * each changed chunk gets accept (keep new) / reject (revert to old)
 * controls in the gutter. The user can also hand-edit before applying.
 *
 * P4 invariant: nothing is written until the user clicks 应用 — and
 * even then the write goes through the existing atomic note-save (PUT
 * /api/notes/{id}), which backs up the previous version per ADR-0018.
 * 放弃 / closing discards the proposal; the note is never silently
 * changed.
 */

import { markdown, markdownLanguage } from "@codemirror/lang-markdown";
import { languages } from "@codemirror/language-data";
import { unifiedMergeView } from "@codemirror/merge";
import { EditorState } from "@codemirror/state";
import { EditorView } from "@codemirror/view";
import { Check, X } from "lucide-react";
import { useEffect, useRef } from "react";

import { Button } from "@/components/ui/button";

const reviewTheme = EditorView.theme({
  "&": { height: "100%", fontSize: "15px", background: "transparent", color: "var(--ink)" },
  ".cm-scroller": { fontFamily: "var(--kn-font-body)", lineHeight: "1.7", overflow: "auto" },
  ".cm-content": { caretColor: "var(--ring)" },
  ".cm-deletedChunk .cm-chunkButtons": {
    top: "2px",
    display: "flex",
    gap: "4px",
  },
  ".cm-deletedChunk .cm-chunkButtons button": {
    width: "20px",
    height: "20px",
    padding: "0",
    lineHeight: "20px",
    fontSize: "13px",
    fontWeight: "700",
  },
});

function renderChunkControl(
  type: "accept" | "reject",
  action: (event: MouseEvent) => void,
): HTMLElement {
  const button = document.createElement("button");
  button.type = "button";
  button.name = type;
  button.setAttribute(
    "aria-label",
    type === "accept" ? "接受这一块改动" : "拒绝这一块改动",
  );
  button.title = type === "accept" ? "接受这一块改动" : "拒绝这一块改动";
  button.textContent = type === "accept" ? "✓" : "×";
  button.onmousedown = action;
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
  const viewRef = useRef<EditorView | null>(null);

  useEffect(() => {
    if (!hostRef.current) return;
    const view = new EditorView({
      parent: hostRef.current,
      state: EditorState.create({
        doc: newBody,
        extensions: [
          markdown({ base: markdownLanguage, codeLanguages: languages }),
          // original = the note as it stands; doc = AI's proposal. The
          // merge view shows the delta with per-chunk accept/reject.
          unifiedMergeView({ original: oldBody, mergeControls: renderChunkControl }),
          EditorView.lineWrapping,
          EditorView.editable.of(true),
          reviewTheme,
        ],
      }),
    });
    viewRef.current = view;
    return () => {
      view.destroy();
      viewRef.current = null;
    };
  }, [oldBody, newBody]);

  const apply = () => {
    const text = viewRef.current?.state.doc.toString() ?? newBody;
    onAccept(text);
  };

  return (
    <div data-testid="diff-review" className="flex h-full min-h-0 flex-col">
      <div
        className="flex shrink-0 items-center justify-between border-b px-3 py-2"
        style={{ borderColor: "var(--line)", background: "var(--panel)" }}
      >
        <div className="text-sm" style={{ color: "var(--ink)" }}>
          AI 建议的改动 · 逐块接受/拒绝，确认后应用
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
        ref={hostRef}
        data-testid="diff-editor"
        className="min-h-0 flex-1 overflow-auto px-3 py-2"
      />
    </div>
  );
}
