/**
 * Phase 1 B slice 9 — anchor-based scroll sync between the CodeMirror
 * editor and the markdown preview. Activated only in split mode; the
 * caller (NoteView) wires us up when both panes are visible.
 *
 * Algorithm (mirrors VS Code's `markdown-language-features` approach,
 * MIT-licensed reference):
 *
 *   - The preview's HTML is stamped with `data-source-line="N"` on
 *     every block-level element by `rehypeSourceLine`. N is 1-based,
 *     matching CodeMirror's own line numbering.
 *
 *   - "Active" pane = the one the user last interacted with (wheel /
 *     mousedown / touchstart). Only its scroll events drive sync.
 *     The other pane is passive — its scroll is set programmatically,
 *     and its scroll events are ignored (avoids feedback loops cleaner
 *     than a mutex flag).
 *
 *   - Editor → preview: on scroll, take the line at the top of the
 *     CodeMirror viewport. Find the nearest `data-source-line ≤ N`
 *     element in the preview, scroll it to the preview's top.
 *
 *   - Preview → editor: on scroll, find the topmost element in the
 *     viewport that has `data-source-line`. Read its line, dispatch
 *     a CM scrollIntoView for the line's `from` position.
 */

import type { EditorView } from "@codemirror/view";

export type ScrollSyncTarget = {
  /** The CodeMirror EditorView (provides `scrollDOM` + `state`). */
  view: EditorView;
  /** The preview pane's outer scroll container (the element with
   *  `overflow-y: auto`; usually the `[data-testid="markdown-preview"]`
   *  wrapper or the `.kn-md` inside it — whichever owns the scroll). */
  previewEl: HTMLElement;
};

/**
 * Wire up bidirectional scroll sync. Returns a teardown function that
 * removes every listener added. Call when split mode mounts; call the
 * teardown when split mode unmounts (or the host re-mounts for a
 * different note).
 */
export function attachScrollSync({ view, previewEl }: ScrollSyncTarget): () => void {
  // Track which pane the user last interacted with. Defaults to the
  // editor — the more common starting point — so the very first
  // wheel event before any pointerdown still drives a sync.
  type Pane = "editor" | "preview";
  let activePane: Pane = "editor";
  // True while we're driving a programmatic scroll on the OTHER
  // pane — that pane's scroll listener checks this and bails so we
  // don't bounce back into a feedback loop.
  let drivingProgrammaticScroll = false;

  const editorScroller = view.scrollDOM;

  function setActive(p: Pane) {
    activePane = p;
  }

  // --- Pane → pane mappings -----------------------------------------

  /** CM line at the top of the editor viewport (1-based). */
  function editorTopLine(): number {
    const top = editorScroller.scrollTop;
    const block = view.elementAtHeight(top);
    return view.state.doc.lineAt(block.from).number;
  }

  /** Find the preview element to align with `line`. Picks the latest
   *  element whose `data-source-line` is ≤ line; falls back to the
   *  first element if none qualifies (line precedes everything). */
  function previewElementForLine(line: number): HTMLElement | null {
    const candidates = previewEl.querySelectorAll<HTMLElement>(
      "[data-source-line]",
    );
    if (candidates.length === 0) return null;
    let best: HTMLElement | null = null;
    for (const el of candidates) {
      const ln = Number(el.dataset.sourceLine);
      if (Number.isNaN(ln)) continue;
      if (ln <= line) best = el;
      else break; // children are in DOM (≈ source) order
    }
    return best ?? candidates[0]!;
  }

  /** Find which preview element is at the top of its viewport, return
   *  its source line. */
  function previewTopLine(): number | null {
    const candidates = previewEl.querySelectorAll<HTMLElement>(
      "[data-source-line]",
    );
    if (candidates.length === 0) return null;
    const containerTop = previewEl.getBoundingClientRect().top;
    let best: HTMLElement | null = null;
    for (const el of candidates) {
      // Use bounding rect rather than offsetTop — the latter is
      // sensitive to nested positioned ancestors.
      const r = el.getBoundingClientRect();
      if (r.top - containerTop > 0) break;
      best = el;
    }
    if (!best) best = candidates[0]!;
    const ln = Number(best.dataset.sourceLine);
    return Number.isNaN(ln) ? null : ln;
  }

  // --- Sync drivers --------------------------------------------------

  function syncPreviewToEditor() {
    const line = editorTopLine();
    const target = previewElementForLine(line);
    if (!target) return;
    drivingProgrammaticScroll = true;
    const containerTop = previewEl.getBoundingClientRect().top;
    const targetTop = target.getBoundingClientRect().top;
    previewEl.scrollTop += targetTop - containerTop;
    // Drop the flag after the layout settles. RAF-then-RAF gives
    // browsers two paint cycles to absorb the scrollTop write.
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        drivingProgrammaticScroll = false;
      });
    });
  }

  function syncEditorToPreview() {
    const line = previewTopLine();
    if (line === null) return;
    const doc = view.state.doc;
    if (line < 1 || line > doc.lines) return;
    const linePos = doc.line(line).from;
    drivingProgrammaticScroll = true;
    // Place the matching source line at the TOP of the editor
    // viewport — same alignment as the editor → preview direction.
    const block = view.lineBlockAt(linePos);
    editorScroller.scrollTop = block.top;
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        drivingProgrammaticScroll = false;
      });
    });
  }

  // --- DOM listeners ------------------------------------------------

  function onEditorPointer() {
    setActive("editor");
  }
  function onPreviewPointer() {
    setActive("preview");
  }
  function onEditorScroll() {
    if (drivingProgrammaticScroll) return;
    if (activePane !== "editor") return;
    syncPreviewToEditor();
  }
  function onPreviewScroll() {
    if (drivingProgrammaticScroll) return;
    if (activePane !== "preview") return;
    syncEditorToPreview();
  }

  editorScroller.addEventListener("scroll", onEditorScroll, { passive: true });
  editorScroller.addEventListener("wheel", onEditorPointer, { passive: true });
  editorScroller.addEventListener("mousedown", onEditorPointer);
  editorScroller.addEventListener("touchstart", onEditorPointer, {
    passive: true,
  });

  previewEl.addEventListener("scroll", onPreviewScroll, { passive: true });
  previewEl.addEventListener("wheel", onPreviewPointer, { passive: true });
  previewEl.addEventListener("mousedown", onPreviewPointer);
  previewEl.addEventListener("touchstart", onPreviewPointer, {
    passive: true,
  });

  return () => {
    editorScroller.removeEventListener("scroll", onEditorScroll);
    editorScroller.removeEventListener("wheel", onEditorPointer);
    editorScroller.removeEventListener("mousedown", onEditorPointer);
    editorScroller.removeEventListener("touchstart", onEditorPointer);

    previewEl.removeEventListener("scroll", onPreviewScroll);
    previewEl.removeEventListener("wheel", onPreviewPointer);
    previewEl.removeEventListener("mousedown", onPreviewPointer);
    previewEl.removeEventListener("touchstart", onPreviewPointer);
  };
}
