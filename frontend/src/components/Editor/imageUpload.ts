/**
 * Phase 1 B slice 4 — image paste / drop for the CodeMirror editor.
 *
 * Why a ViewPlugin with native capture-phase listeners (not the simpler
 * `EditorView.domEventHandlers`):
 *
 *   CM6's built-in `handlers.drop` reads `event.dataTransfer.files`
 *   with `FileReader.readAsText(...)` — it treats every dropped file
 *   as text and tries to insert the bytes as characters. With plugin
 *   handlers via `domEventHandlers`, we *should* preempt the built-in
 *   (the dispatch loop bails early on `event.defaultPrevented`), but
 *   in practice macOS Finder drags can land in the editor with
 *   `File.type === ""`, our strict MIME whitelist filters them out,
 *   our handler returns false, the built-in handler runs and tries to
 *   insert binary PNG bytes — the user sees the cursor position shift
 *   to the drop point but nothing inserted.
 *
 *   The fix is to (1) attach native `addEventListener` with
 *   `{ capture: true }` so we beat any other listener regardless of
 *   the host framework's event system, and (2) loosen the MIME filter
 *   to also accept `image/<ext>` filenames whose `type` came back
 *   blank. The backend still validates strictly (415 on non-image
 *   bytes), so a permissive frontend can't smuggle anything in.
 *
 * Flow:
 *   1. paste / drop event includes one or more image-ish files
 *   2. for each file: insert a transient placeholder at the cursor
 *      (`![uploading…](placeholder-N)`) so the user sees a landing spot
 *      immediately
 *   3. upload via POST /api/attachments
 *   4. on response: replace the placeholder with the real
 *      `![<filename>](<vault-relative-path>)`
 *   5. on error: replace the placeholder with `![upload-failed: <err>]()`
 */

import {
  EditorSelection,
  type Extension,
  StateEffect,
  StateField,
} from "@codemirror/state";
import {
  Decoration,
  type DecorationSet,
  EditorView,
  ViewPlugin,
  WidgetType,
} from "@codemirror/view";

import { uploadAttachment } from "@/api/client";

// ---------- drop-position indicator ----------
//
// CM6 only renders its built-in caret (`.cm-cursor`) when the editor
// is focused. During a drag from Finder, the user clicks Finder first,
// stealing focus — by the time the cursor enters the editor the
// caret has vanished, leaving no visual hint of where the image will
// land. We render our own indicator via a StateField → Decoration
// pipeline that paints regardless of focus state.

class DropIndicatorWidget extends WidgetType {
  toDOM() {
    const el = document.createElement("span");
    el.className = "kn-drop-indicator";
    return el;
  }
  // Same instance ⇒ no re-paint cost when only the position changed.
  eq() {
    return true;
  }
  ignoreEvent() {
    return true;
  }
}

const setDropPos = StateEffect.define<number | null>();
const dropPosField = StateField.define<number | null>({
  create: () => null,
  update(value, tr) {
    for (const e of tr.effects) if (e.is(setDropPos)) return e.value;
    return value;
  },
  provide: (f) =>
    EditorView.decorations.from(f, (value): DecorationSet => {
      if (value === null) return Decoration.none;
      return Decoration.set([
        Decoration.widget({
          widget: new DropIndicatorWidget(),
          side: 1,
        }).range(value),
      ]);
    }),
});

const ALLOWED_MIME = new Set([
  "image/png",
  "image/jpeg",
  "image/jpg",
  "image/gif",
  "image/webp",
]);
const ALLOWED_EXT = /\.(png|jpe?g|gif|webp)$/i;

let placeholderCounter = 0;

function deriveFilename(file: File | Blob): string {
  if (file instanceof File && file.name) return file.name;
  const ext = ((file.type.split("/")[1] || "png") as string).replace("jpeg", "jpg");
  return `pasted-${Date.now()}.${ext}`;
}

/** Looks like an image File we should try to upload — generous on mime
 *  type (some OS-level drags expose `type === ""`), strict on extension
 *  when mime is missing. Backend rejects truly non-image content. */
function looksLikeImage(file: File): boolean {
  const t = (file.type || "").toLowerCase();
  if (ALLOWED_MIME.has(t)) return true;
  if (t.startsWith("image/")) return true;
  if (t === "" && ALLOWED_EXT.test(file.name || "")) return true;
  return false;
}

function insertAtCursor(view: EditorView, text: string): { from: number; to: number } {
  const { from } = view.state.selection.main;
  view.dispatch({
    changes: { from, insert: text },
    selection: EditorSelection.cursor(from + text.length),
    scrollIntoView: true,
  });
  return { from, to: from + text.length };
}

function replaceMarker(view: EditorView, marker: string, replacement: string): boolean {
  const doc = view.state.doc.toString();
  const idx = doc.indexOf(marker);
  if (idx < 0) return false;
  view.dispatch({
    changes: { from: idx, to: idx + marker.length, insert: replacement },
  });
  return true;
}

async function handleFiles(view: EditorView, files: File[]): Promise<void> {
  for (const file of files) {
    const filename = deriveFilename(file);
    const id = ++placeholderCounter;
    const marker = `![uploading…](knowlet-placeholder-${id})`;
    insertAtCursor(view, marker);
    void (async () => {
      try {
        const r = await uploadAttachment(file, filename);
        replaceMarker(view, marker, `![${filename}](${r.path})`);
      } catch (err) {
        const detail =
          err && typeof err === "object" && "detail" in err
            ? String((err as { detail: unknown }).detail)
            : String(err);
        replaceMarker(view, marker, `![upload-failed: ${detail}]()`);
      }
    })();
  }
}

/**
 * Pull image File entries out of a clipboard / dataTransfer payload.
 * Walks both `items` (preferred — works for clipboard pastes that
 * never populate `files`) and `files` (Finder drags), de-duping in
 * case both report the same File object.
 */
function extractImages(
  items: DataTransferItemList | null,
  files: FileList | null,
): File[] {
  const seen = new Set<File>();
  const out: File[] = [];
  if (items) {
    for (const it of Array.from(items)) {
      if (it.kind !== "file") continue;
      const f = it.getAsFile();
      if (f && looksLikeImage(f) && !seen.has(f)) {
        seen.add(f);
        out.push(f);
      }
    }
  }
  if (files) {
    for (const f of Array.from(files)) {
      if (looksLikeImage(f) && !seen.has(f)) {
        seen.add(f);
        out.push(f);
      }
    }
  }
  return out;
}

/** Loose check used during dragover/dragenter when per-item mimes are
 *  hidden by the browser. `dt.types` always exposes "Files" for native
 *  file drags, even when the rest is masked. */
function isFileDrag(dt: DataTransfer | null): boolean {
  if (!dt) return false;
  if (dt.types && Array.from(dt.types).includes("Files")) return true;
  if (dt.items) {
    for (const it of Array.from(dt.items)) {
      if (it.kind === "file") return true;
    }
  }
  return false;
}

/**
 * The actual extension. We use a ViewPlugin so we can add native
 * capture-phase listeners on `view.contentDOM` and remove them on
 * destroy — guaranteeing we beat CM6's built-in drop handler (which
 * otherwise tries to read dropped binary files as text and inserts
 * garbage bytes into the editor).
 */
export function imageUploadExtension(): Extension {
  const plugin = ViewPlugin.define((view) => {
    const dom = view.contentDOM;

    function onPaste(event: ClipboardEvent) {
      const images = extractImages(event.clipboardData?.items ?? null, null);
      if (images.length === 0) return; // let CM handle text paste
      event.preventDefault();
      event.stopPropagation();
      void handleFiles(view, images);
    }

    function onDragenter(event: DragEvent) {
      if (isFileDrag(event.dataTransfer)) event.preventDefault();
    }

    let lastDragPos = -1;
    function clearIndicator() {
      lastDragPos = -1;
      if (view.state.field(dropPosField, false) !== null) {
        view.dispatch({ effects: setDropPos.of(null) });
      }
    }
    function onDragover(event: DragEvent) {
      // HTML5 spec: dragover MUST preventDefault for a drop to fire.
      // We claim every file drag here; final mime filtering happens at
      // drop time once File objects are exposed.
      if (!isFileDrag(event.dataTransfer)) return;
      event.preventDefault();
      if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
      // Show our own focus-independent drop indicator at the position
      // under the mouse. Skip dispatching when nothing changed —
      // dragover fires ~60Hz, the StateField update is cheap but
      // re-rendering the decoration set every frame is not.
      const pos = view.posAtCoords({ x: event.clientX, y: event.clientY });
      if (pos === null || pos === lastDragPos) return;
      lastDragPos = pos;
      view.dispatch({ effects: setDropPos.of(pos) });
    }
    function onDragleave(event: DragEvent) {
      // Only clear when leaving the editor for a node that's outside it
      // — dragging over inner nodes (line spans, decorations) fires
      // dragleave on the outer .cm-content, but we don't want that to
      // hide the indicator mid-drag.
      const related = event.relatedTarget;
      if (related instanceof Node && dom.contains(related)) return;
      clearIndicator();
    }

    function onDrop(event: DragEvent) {
      const dt = event.dataTransfer;
      if (!dt) return;
      const images = extractImages(dt.items ?? null, dt.files ?? null);
      if (images.length === 0) {
        clearIndicator();
        return; // text drag — let CM handle it
      }
      // Beat CM's own drop handler. preventDefault + stopPropagation
      // both — the latter prevents the bubble-phase CM listener from
      // running readAsText on our binary blob.
      event.preventDefault();
      event.stopPropagation();
      lastDragPos = -1;
      const pos = view.posAtCoords({ x: event.clientX, y: event.clientY });
      // Clear the indicator + position the real selection at the drop
      // point in one transaction so the placeholder lands there.
      view.dispatch({
        effects: setDropPos.of(null),
        ...(pos !== null ? { selection: EditorSelection.cursor(pos) } : {}),
      });
      void handleFiles(view, images);
    }

    // Capture phase + non-passive so preventDefault / stopPropagation work.
    const opts: AddEventListenerOptions = { capture: true };
    dom.addEventListener("paste", onPaste, opts);
    dom.addEventListener("dragenter", onDragenter, opts);
    dom.addEventListener("dragover", onDragover, opts);
    dom.addEventListener("dragleave", onDragleave, opts);
    dom.addEventListener("drop", onDrop, opts);

    return {
      destroy() {
        dom.removeEventListener("paste", onPaste, opts);
        dom.removeEventListener("dragenter", onDragenter, opts);
        dom.removeEventListener("dragover", onDragover, opts);
        dom.removeEventListener("dragleave", onDragleave, opts);
        dom.removeEventListener("drop", onDrop, opts);
      },
    };
  });
  // The state field has to be combined with the plugin so the field is
  // installed on every editor that uses our extension.
  return [dropPosField, plugin];
}
