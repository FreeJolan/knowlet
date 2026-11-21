/**
 * Phase 1 B note view — uncontrolled CodeMirror editor + debounced auto-save.
 *
 * Data flow:
 *   - The mounted editor's document is the source of truth for the body.
 *     MarkdownEditor reads `initialValue` once per mount (`key={note.id}`)
 *     and never re-syncs from props, so the per-note query cache can
 *     change underneath it (save responses, tag / title responses,
 *     right-rail refetches) without touching what the user is typing.
 *   - `metaRef` is the client's source of truth for title / tags /
 *     aliases of the loaded note; header edits update it synchronously.
 *   - Every PUT for a note goes through `enqueueNoteWrite` (one at a time
 *     per note) and builds its payload when it is SENT, from `bodyRef` +
 *     `metaRef`. Whichever PUT lands last therefore carries the newest
 *     body and the newest metadata.
 *   - Server data for the already-loaded note is adopted only when it is
 *     genuinely new: no write of ours is pending, it differs from the last
 *     body the server acknowledged, and the editor has no unsaved edits.
 *     Then it is dispatched into the live editor (sync pull, AI apply,
 *     merge resolution, frontmatter repair). With unsaved edits the local
 *     text wins; the next autosave overwrites the file, and the backend
 *     backs up the replaced version before overwriting.
 *
 * Save triggers:
 *   - onChange  → bodyRef.current = next; mark dirty; scheduleSave (800 ms)
 *   - onBlur    → flushSave (cancel debounce, save now)
 *   - noteId change → flushSave for the previous note before remount
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import GithubSlugger from "github-slugger";
import { Columns2, Eye, Pen, Star } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  addFavorite,
  getNote,
  listFavorites,
  listTemplates,
  removeFavorite,
  setNoteKind,
  updateNote,
} from "@/api/client";
import type { TemplateSummary } from "@/api/client";
import type { NoteFull, NoteKind, TreeFolder } from "@/api/types";
import { KindChip } from "@/components/KindChip";
import { EditorView } from "@codemirror/view";

import { MarkdownEditor } from "@/components/Editor/MarkdownEditor";
import { MarkdownPreview } from "@/components/Editor/MarkdownPreview";
import { InlineEditInput } from "@/components/InlineEdit/InlineEditInput";
import { ConflictMergeView } from "@/components/Sync/ConflictMergeView";
import { SyncStatusBadge } from "@/components/Sync/SyncStatusBadge";
import {
  MERGE_OPEN_EVENT,
  takePendingMergeOpen,
} from "@/lib/pendingMergeOpen";

import { FrontmatterCorruptedNotice } from "./FrontmatterCorruptedNotice";
import { enqueueNoteWrite } from "./noteWriteQueue";
import { noteTitleClashesIn } from "@/lib/findCollision";
import { registerNoteTitleWriter } from "@/lib/noteWrites";
import { normalizeNoteTitle } from "@/lib/noteTitle";
import { QK } from "@/lib/queryClient";

import { AliasChipStrip } from "./AliasChipStrip";
import {
  PropertiesContent,
  PropertiesToggle,
  SourceKickerPill,
  usePropertiesCollapsed,
} from "./PropertiesPanel";
import { attachScrollSync } from "./scrollSync";
import { TagChipStrip } from "./TagChipStrip";

/**
 * Update one note inside a TreeFolder snapshot. Used for optimistic
 * title rename from the editor — mirrors the helper FileTree owns.
 */
function updateNoteTitleInTree(
  root: TreeFolder,
  noteId: string,
  title: string,
): TreeFolder {
  return {
    ...root,
    notes: root.notes.map((n) => (n.id === noteId ? { ...n, title } : n)),
    folders: root.folders.map((f) => updateNoteTitleInTree(f, noteId, title)),
  };
}

const AUTOSAVE_DEBOUNCE_MS = 800;
const VIEW_MODE_STORAGE_KEY = "knowlet:view-mode";

type SaveState = "idle" | "saving" | "saved" | "error";
type ViewMode = "edit" | "split" | "preview";

type NoteMeta = { title: string; tags: string[]; aliases: string[] };
const META_KEYS = ["title", "tags", "aliases"] as const;

function metaOf(n: NoteFull): NoteMeta {
  return { title: n.title, tags: n.tags, aliases: n.aliases ?? [] };
}

function sameValue(a: string | string[], b: string | string[]): boolean {
  if (Array.isArray(a) && Array.isArray(b)) {
    return a.length === b.length && a.every((x, i) => x === b[i]);
  }
  return a === b;
}

/** One queued PUT. `patch` / `bodySnapshot` are only consulted when the
 *  note is no longer the one loaded in the editor by the time the PUT
 *  is sent (e.g. the flush that runs while switching notes). */
type NoteWrite = {
  id: string;
  loadToken: number;
  patch: Partial<NoteMeta>;
  bodySnapshot?: string;
  /** Undo this write's optimistic state. Runs inside the queue, before
   *  the next queued write builds its payload. */
  rollback?: () => void;
};
type NoteWriteResult = { data: NoteFull; sentBody: string };

function loadInitialViewMode(): ViewMode {
  if (typeof window === "undefined") return "edit";
  const v = window.localStorage.getItem(VIEW_MODE_STORAGE_KEY);
  if (v === "edit" || v === "split" || v === "preview") return v;
  return "edit";
}

export function NoteView({
  noteId,
  pendingHash,
  onPendingHashConsumed,
  pendingLine,
  onPendingLineConsumed,
  preserveViewMode = false,
}: {
  noteId: string | null;
  pendingHash?: string | null;
  onPendingHashConsumed?: () => void;
  /** Phase 1 C slice 1: when set, scroll the editor to this 1-based
   *  line and place the cursor there. Used by Backlinks panel clicks. */
  pendingLine?: number | null;
  onPendingLineConsumed?: () => void;
  /** Phase 1 D slice 1: when true, the pendingHash / pendingLine
   *  effects MUST NOT auto-switch viewMode. Outline-driven jumps are
   *  intra-note and should respect the user's chosen mode (preview /
   *  edit / split); cross-note nav (backlinks / wikilinks) keeps the
   *  old auto-switch behavior because changing notes implies the
   *  destination is what matters. */
  preserveViewMode?: boolean;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();

  const note = useQuery({
    queryKey: noteId ? QK.note(noteId) : ["note", "_empty"],
    queryFn: () => {
      if (!noteId) throw new Error("noteId required");
      return getNote(noteId);
    },
    enabled: !!noteId,
  });

  // ---- Per-note save state, all kept in refs so the editor doesn't
  // re-mount on every keystroke. ----
  // The editor's current text. Updated by onChange.
  const bodyRef = useRef("");
  // The id this body belongs to. When noteId switches, we use this to know
  // which id to save to during the transition flush.
  const loadedIdRef = useRef<string | null>(null);
  // Bumped each time a note is (re)loaded into the editor. A queued write
  // reads the live refs only if it was queued during the same load.
  const loadTokenRef = useRef(0);
  // Title / tags / aliases the next PUT sends for the loaded note, and
  // the values the server is known to hold (the merge base used to tell
  // our own echoes from external changes).
  const metaRef = useRef<NoteMeta | null>(null);
  const serverMetaRef = useRef<NoteMeta | null>(null);
  // Last body the backend acknowledged for the loaded note. Used to skip
  // no-op saves and to tell our own echoes from external changes.
  const lastSavedRef = useRef("");
  const dirtyRef = useRef(false);
  const debounceRef = useRef<number | null>(null);
  // JSON of the last successful PUT payload per note: a queued write
  // whose payload is identical skips the request.
  const lastSentRef = useRef(new Map<string, string>());
  const [savingState, setSavingState] = useState<SaveState>("idle");
  const [viewMode, setViewMode] = useState<ViewMode>(loadInitialViewMode);
  // Title click-to-edit state. Notion / Bear / Typora all let you edit
  // the note title inline at the top of the doc; Obsidian doesn't but
  // the dogfood feedback was that it feels missing. The flow goes
  // through `updateNote(id, {title, body, tags})` so the file tree
  // sees the rename via tree-cache invalidation, same path the F2
  // shortcut already uses.
  const [editingTitle, setEditingTitle] = useState(false);
  // D3 Properties UI: shared collapse state between the inline crumb
  // toggle and the rows below TagChipStrip. localStorage-backed.
  // Per-note collapse state — pass the active note's id so each
  // note remembers its own preference instead of sharing one
  // global toggle across the whole vault.
  const propsCollapse = usePropertiesCollapsed(note.data?.id ?? null);
  // CM6 view + preview-scroll-container refs for split-mode sync.
  // viewRef is set once per note (key remount in MarkdownEditor) via
  // onViewMount. previewWrapperRef hooks the [data-testid] wrapper.
  const editorViewRef = useRef<EditorView | null>(null);
  const previewWrapperRef = useRef<HTMLDivElement | null>(null);
  // The preview pane shows the editor's body — mirror it into state when
  // we change modes / when the user clicks back into the editor pane after
  // editing in split. In split-mode it tracks the editor live.
  const [previewBody, setPreviewBody] = useState("");
  // S5: merge editor visibility. Lives here (rather than inside the
  // badge) so the dialog stays mounted across badge re-renders +
  // can be reopened without losing the user's hunk choices via
  // React Query's bundle cache.
  const [mergeOpen, setMergeOpen] = useState(false);
  // #107a — the conflicts inbox can land us in either state when
  // the user clicks a row:
  //   * already-open note: the listener is already attached; the
  //     custom event fires synchronously and we open the dialog.
  //   * not-yet-open note: AppShell's openNote(id) shifts the active
  //     tab; this NoteView's note.data eventually resolves to the
  //     new id. The event might have fired before the listener
  //     was attached, so we ALSO drain the pending queue every
  //     time the active note id changes (covers cold-mount).
  useEffect(() => {
    const id = note.data?.id;
    if (!id) return;
    if (takePendingMergeOpen(id)) {
      setMergeOpen(true);
    }
    const onOpenMerge = (e: Event) => {
      const detail = (e as CustomEvent<{ noteId: string }>).detail;
      if (detail?.noteId !== id) return;
      // ``takePendingMergeOpen`` consumes the queue entry so the
      // mount-time drain above doesn't double-fire if the user
      // clicks the same note twice in quick succession.
      if (takePendingMergeOpen(id)) {
        setMergeOpen(true);
      } else {
        // No queue entry — direct event delivery (note was already
        // open, AppShell only fired the event without queuing).
        setMergeOpen(true);
      }
    };
    window.addEventListener(MERGE_OPEN_EVENT, onOpenMerge);
    return () => window.removeEventListener(MERGE_OPEN_EVENT, onOpenMerge);
  }, [note.data?.id]);

  // The single PUT path for this view. Runs inside the per-note queue and
  // builds the payload at send time (see the module docstring).
  const runWrite = useCallback(
    (w: NoteWrite): Promise<NoteWriteResult> =>
      enqueueNoteWrite(w.id, async () => {
        try {
          // A GET started before this PUT may resolve after it with the
          // pre-PUT file; cancel it instead of letting it land.
          await qc.cancelQueries({ queryKey: QK.note(w.id) });
          const isLive = () =>
            loadedIdRef.current === w.id &&
            loadTokenRef.current === w.loadToken &&
            metaRef.current !== null;
          const live = isLive();
          const baseBefore = live ? serverMetaRef.current : null;
          const cached = qc.getQueryData<NoteFull>(QK.note(w.id));
          let payload: NoteMeta & { body: string };
          if (live) {
            payload = { ...metaRef.current!, body: bodyRef.current };
          } else {
            const title = w.patch.title ?? cached?.title;
            const tags = w.patch.tags ?? cached?.tags;
            const aliases =
              w.patch.aliases ?? cached?.aliases ?? (cached ? [] : undefined);
            const body = w.bodySnapshot ?? cached?.body;
            if (
              title === undefined ||
              tags === undefined ||
              aliases === undefined ||
              body === undefined
            ) {
              // Never send a guessed snapshot: an empty tags / aliases
              // list would clear them on disk.
              throw new Error(`no snapshot available to write note ${w.id}`);
            }
            payload = { title, tags, aliases, body };
          }
          const key = JSON.stringify(payload);
          if (cached && lastSentRef.current.get(w.id) === key) {
            // Nothing changed since our last successful write.
            return { data: cached, sentBody: payload.body };
          }
          const data = await updateNote(w.id, payload);
          lastSentRef.current.set(w.id, key);
          void qc.cancelQueries({ queryKey: QK.note(w.id) });
          const result = metaOf(data);
          if (live && isLive()) {
            lastSavedRef.current = payload.body;
            serverMetaRef.current = result;
            // Take the server's normalized value (inline #tags merged
            // into tags) for fields the user hasn't changed since send.
            const cur = metaRef.current!;
            metaRef.current = {
              title: sameValue(cur.title, payload.title) ? result.title : cur.title,
              tags: sameValue(cur.tags, payload.tags) ? result.tags : cur.tags,
              aliases: sameValue(cur.aliases, payload.aliases)
                ? result.aliases
                : cur.aliases,
            };
          }
          qc.setQueryData<NoteFull>(QK.note(w.id), (prev) => {
            if (!prev) return data;
            // PUT rewrites in place (ULID filenames) and its response
            // does not carry `folder`.
            const merged: NoteFull = { ...prev, ...data, folder: prev.folder };
            if (!baseBefore) return merged;
            // Keep cached metadata that changed after this payload was
            // built (a queued edit's optimistic value, or another
            // writer's) instead of flashing this response's older value.
            const prevMeta = metaOf(prev);
            if (
              !sameValue(prevMeta.title, payload.title) &&
              !sameValue(prevMeta.title, baseBefore.title)
            ) {
              merged.title = prevMeta.title;
            }
            if (
              !sameValue(prevMeta.tags, payload.tags) &&
              !sameValue(prevMeta.tags, baseBefore.tags)
            ) {
              merged.tags = prevMeta.tags;
            }
            if (
              !sameValue(prevMeta.aliases, payload.aliases) &&
              !sameValue(prevMeta.aliases, baseBefore.aliases)
            ) {
              merged.aliases = prevMeta.aliases;
            }
            return merged;
          });
          return { data, sentBody: payload.body };
        } catch (err) {
          w.rollback?.();
          throw err;
        }
      }),
    [qc],
  );

  // After any successful write: the body may now be saved even if this
  // write was a tag / title change (every PUT carries the latest body).
  const settleSaveState = useCallback((w: NoteWrite) => {
    if (loadedIdRef.current !== w.id || loadTokenRef.current !== w.loadToken) {
      return;
    }
    dirtyRef.current = bodyRef.current !== lastSavedRef.current;
    // Keystrokes that arrived after this PUT was sent have their own
    // save scheduled / queued; keep showing "saving" until it lands.
    if (dirtyRef.current) return;
    setSavingState((s) => (s === "saving" || s === "error" ? "saved" : s));
    window.setTimeout(() => {
      setSavingState((s) => (s === "saved" ? "idle" : s));
    }, 1200);
  }, []);

  const saveMutation = useMutation({
    mutationFn: (w: NoteWrite) => runWrite(w),
    // Auto-retry transient failures (network blip, slow backend) with
    // exponential backoff. After 3 attempts (~14s max wait) we give
    // up and surface the failure visibly via onError below — per the
    // "no silent failure" UX rule from sync-design discussion.
    retry: 3,
    retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 10000),
    onSuccess: (_res, w) => {
      // Body saves can include inline `#tag` syntax that the backend
      // merges into frontmatter. Invalidate tag caches so the Tag
      // browser reflects new tags without a manual reload.
      void qc.invalidateQueries({ queryKey: QK.tags });
      void qc.invalidateQueries({ queryKey: QK.tagsWithNotes });
      settleSaveState(w);
    },
    onError: (_err, w) => {
      // Reaching here means the backend rejected us OR all retries
      // exhausted. The user must know — saving silently dropping
      // edits is exactly the "沉默地陷入糟糕状态" failure mode the
      // sync-design memory rules out. (A later tag / title write may
      // already have carried the same body — then nothing is unsaved.)
      if (loadedIdRef.current !== w.id || loadTokenRef.current !== w.loadToken) {
        return;
      }
      if (bodyRef.current !== lastSavedRef.current) setSavingState("error");
      else settleSaveState(w);
    },
  });

  // Manual retry — clicked from the error badge. Re-fires the save with
  // the current editor body so the user doesn't lose anything just
  // because the auto-retries exhausted.
  const retryFailedSave = useCallback(() => {
    const id = loadedIdRef.current;
    const meta = metaRef.current;
    if (!id || !meta) return;
    dirtyRef.current = true;
    setSavingState("saving");
    saveMutation.mutate({
      id,
      loadToken: loadTokenRef.current,
      patch: { ...meta },
      bodySnapshot: bodyRef.current,
    });
  }, [saveMutation]);

  // Header metadata edits (title rename, tag chips, alias chips).
  const metaMutation = useMutation({
    mutationFn: (w: NoteWrite) => runWrite(w),
    onSuccess: (_res, w) => settleSaveState(w),
    onSettled: (_d, _e, w) => {
      if (w.patch.tags) {
        void qc.invalidateQueries({ queryKey: QK.tags });
        void qc.invalidateQueries({ queryKey: QK.tagsWithNotes });
      }
      if (w.patch.tags || w.patch.title !== undefined) {
        void qc.invalidateQueries({ queryKey: QK.tree });
      }
    },
  });
  const mutateMeta = metaMutation.mutateAsync;

  // Latest metadata for `id`: the live refs for the loaded note, the
  // cache for a note this view has already switched away from.
  const currentMeta = useCallback(
    (id: string): NoteMeta | null => {
      if (loadedIdRef.current === id && metaRef.current) return metaRef.current;
      const cached = qc.getQueryData<NoteFull>(QK.note(id));
      return cached ? metaOf(cached) : null;
    },
    [qc],
  );

  // Apply a metadata change optimistically (refs + per-note cache) and
  // queue the PUT. Rollback restores only the fields this change set,
  // and only while they still hold the values it set. Rejects when the
  // write fails (state is already rolled back by then).
  const changeMeta = useCallback(
    (
      id: string,
      patch: Partial<NoteMeta>,
      extraRollback?: () => void,
    ): Promise<NoteWriteResult> => {
      const keys = Object.keys(patch) as (keyof NoteMeta)[];
      const live = loadedIdRef.current === id && metaRef.current !== null;
      const prevMeta = live ? metaRef.current : null;
      if (live) metaRef.current = { ...metaRef.current!, ...patch };
      const prevNote = qc.getQueryData<NoteFull>(QK.note(id));
      if (prevNote) {
        qc.setQueryData<NoteFull>(QK.note(id), { ...prevNote, ...patch });
      }
      const restore = <T extends Partial<NoteMeta>>(cur: T, prev: T): T => {
        const next: Record<string, unknown> = { ...cur };
        for (const k of keys) {
          if (cur[k] === patch[k]) next[k] = prev[k];
        }
        return next as T;
      };
      return mutateMeta({
        id,
        loadToken: live ? loadTokenRef.current : -1,
        patch,
        rollback: () => {
          if (prevMeta && metaRef.current && loadedIdRef.current === id) {
            metaRef.current = restore(metaRef.current, prevMeta);
          }
          if (prevNote) {
            qc.setQueryData<NoteFull>(QK.note(id), (cur) =>
              cur ? restore(cur, prevNote) : cur,
            );
          }
          extraRollback?.();
        },
      });
    },
    [mutateMeta, qc],
  );

  const addTag = useCallback(
    (id: string, tag: string) => {
      const meta = currentMeta(id);
      if (!meta || meta.tags.includes(tag)) return;
      changeMeta(id, { tags: [...meta.tags, tag] }).catch(() => undefined);
    },
    [changeMeta, currentMeta],
  );
  const removeTag = useCallback(
    (id: string, tag: string) => {
      const meta = currentMeta(id);
      if (!meta) return;
      changeMeta(id, { tags: meta.tags.filter((x) => x !== tag) }).catch(
        () => undefined,
      );
    },
    [changeMeta, currentMeta],
  );
  const addAlias = useCallback(
    (id: string, alias: string) => {
      const meta = currentMeta(id);
      if (!meta) return;
      changeMeta(id, { aliases: [...meta.aliases, alias] }).catch(
        () => undefined,
      );
    },
    [changeMeta, currentMeta],
  );
  const removeAlias = useCallback(
    (id: string, alias: string) => {
      const meta = currentMeta(id);
      if (!meta) return;
      changeMeta(id, {
        aliases: meta.aliases.filter((a) => a !== alias),
      }).catch(() => undefined);
    },
    [changeMeta, currentMeta],
  );

  // A file-tree rename of the open note goes through this view's own
  // metadata path, so no later autosave can send the old title back.
  const loadedNoteId = note.data?.id ?? null;
  useEffect(() => {
    if (!loadedNoteId) return;
    return registerNoteTitleWriter(loadedNoteId, async (title) => {
      const res = await changeMeta(loadedNoteId, { title });
      return res.data;
    });
  }, [loadedNoteId, changeMeta]);

  // Phase 3 Stage 2 — knowledge / reference toggle (ADR-0029 §4.5).
  // Demote confirmation is handled inside KindChip itself (popover);
  // by the time this mutation fires, the user already confirmed.
  // Backend still enforces confirm=true for safety in case some other
  // caller (CLI / future MCP) tries to demote without it.
  const setKindMutation = useMutation({
    // Queued with the PUTs: the kind endpoint rewrites the same file.
    mutationFn: ({ id, kind }: { id: string; kind: NoteKind }) =>
      enqueueNoteWrite(id, () => setNoteKind(id, { kind, confirm: true })),
    onSuccess: (data, vars) => {
      qc.setQueryData<NoteFull>(QK.note(vars.id), (prev) =>
        prev ? { ...prev, kind: data.kind } : data,
      );
    },
  });

  // ⌘⇧K — toggle kind. Reference → knowledge promotes instantly (no
  // confirmation needed per ADR-0029 §4.5 asymmetric semantics).
  // Knowledge → reference is a downgrade; the keyboard path doesn't
  // bypass the chip's popover, so we focus the chip so the user can
  // confirm with Enter. This keeps the anti-drift guard from being
  // shortcut-bypassed.
  useEffect(() => {
    const onToggleKind = () => {
      const current = note.data;
      if (!current) return;
      const kind = current.kind ?? "knowledge";
      if (kind === "reference") {
        setKindMutation.mutate({ id: current.id, kind: "knowledge" });
        return;
      }
      // knowledge → reference: focus the chip so the popover opens
      // on click (the chip button toggles the popover when activated).
      const chipBtn = document.querySelector<HTMLButtonElement>(
        '[data-testid="kind-chip-knowledge-button"]',
      );
      chipBtn?.focus();
      chipBtn?.click();
    };
    window.addEventListener("knowlet:toggle-active-note-kind", onToggleKind);
    return () =>
      window.removeEventListener(
        "knowlet:toggle-active-note-kind",
        onToggleKind,
      );
  }, [note.data, setKindMutation]);

  const flushSave = useCallback(() => {
    if (debounceRef.current !== null) {
      window.clearTimeout(debounceRef.current);
      debounceRef.current = null;
    }
    if (!dirtyRef.current) return;
    const id = loadedIdRef.current;
    const meta = metaRef.current;
    const body = bodyRef.current;
    if (!id || !meta) return;
    if (body === lastSavedRef.current) {
      dirtyRef.current = false;
      return;
    }
    setSavingState("saving");
    saveMutation.mutate({
      id,
      loadToken: loadTokenRef.current,
      patch: { ...meta },
      bodySnapshot: body,
    });
  }, [saveMutation]);

  const scheduleSave = useCallback(() => {
    if (debounceRef.current !== null) {
      window.clearTimeout(debounceRef.current);
    }
    debounceRef.current = window.setTimeout(() => {
      debounceRef.current = null;
      flushSave();
    }, AUTOSAVE_DEBOUNCE_MS);
  }, [flushSave]);

  // Prime the refs when a note is loaded; afterwards, decide whether a
  // cache change for the same note is ours or genuinely external.
  useEffect(() => {
    const data = note.data;
    if (!data) return;
    if (loadedIdRef.current !== data.id) {
      loadTokenRef.current += 1;
      loadedIdRef.current = data.id;
      bodyRef.current = data.body;
      lastSavedRef.current = data.body;
      metaRef.current = metaOf(data);
      serverMetaRef.current = metaOf(data);
      setPreviewBody(data.body);
      dirtyRef.current = false;
      setSavingState("idle");
      return;
    }
    // Same note: three-way merge per field. local = refs, base = what the
    // server is known to hold, incoming = cache. Only a change the server
    // made (incoming != base) on a field the user hasn't touched
    // (local == base) is adopted; our own optimistic updates and save
    // responses never overwrite local state.
    const incoming = metaOf(data);
    const local = metaRef.current;
    const base = serverMetaRef.current;
    let serverChanged = data.body !== lastSavedRef.current;
    if (local && base) {
      const nextLocal: Record<string, unknown> = { ...local };
      const nextBase: Record<string, unknown> = { ...base };
      let adopted = false;
      for (const k of META_KEYS) {
        if (sameValue(incoming[k], base[k]) || sameValue(incoming[k], local[k])) {
          continue;
        }
        serverChanged = true;
        if (sameValue(local[k], base[k])) {
          nextLocal[k] = incoming[k];
          nextBase[k] = incoming[k];
          adopted = true;
        }
      }
      if (adopted) {
        metaRef.current = nextLocal as NoteMeta;
        serverMetaRef.current = nextBase as NoteMeta;
      }
    }
    // The file changed under us: a later write must not be skipped as
    // "identical to what we last sent".
    if (serverChanged) lastSentRef.current.delete(data.id);
    if (data.body === lastSavedRef.current) return;
    if (data.body === bodyRef.current) {
      lastSavedRef.current = data.body;
      dirtyRef.current = false;
      return;
    }
    // Unsaved local edits win over a concurrent external change.
    if (dirtyRef.current) return;
    lastSavedRef.current = data.body;
    bodyRef.current = data.body;
    const view = editorViewRef.current;
    if (view && view.state.doc.toString() !== data.body) {
      view.dispatch({
        changes: { from: 0, to: view.state.doc.length, insert: data.body },
      });
    }
    setPreviewBody(data.body);
  }, [note.data]);

  // Persist the user's view-mode choice across reloads.
  useEffect(() => {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(VIEW_MODE_STORAGE_KEY, viewMode);
    }
  }, [viewMode]);

  // Split-mode scroll sync: bind only when both panes are mounted +
  // visible. Re-runs on view-mode toggle and on note swap (the
  // editor view-ref changes via the `key={note.data.id}` remount).
  // The detail of which pane is "active" + how lines map to elements
  // lives in `scrollSync.ts`; this effect just owns the lifetime.
  useEffect(() => {
    if (viewMode !== "split") return;
    if (!noteId) return;
    let teardown: (() => void) | null = null;
    // The CM view sets editorViewRef inside onViewMount, which fires
    // *after* this effect's first run. Poll briefly until both refs
    // populate. requestAnimationFrame is enough — CM mounts within
    // a frame of the parent's commit.
    let cancelled = false;
    const tryAttach = () => {
      if (cancelled) return;
      const view = editorViewRef.current;
      const previewEl = previewWrapperRef.current;
      if (view && previewEl) {
        teardown = attachScrollSync({ view, previewEl });
        return;
      }
      requestAnimationFrame(tryAttach);
    };
    tryAttach();
    return () => {
      cancelled = true;
      teardown?.();
    };
  }, [viewMode, noteId]);

  // When entering preview/split mode, snapshot the latest editor body.
  // (In edit-only mode the preview isn't rendered, so we don't need to.)
  useEffect(() => {
    if (viewMode !== "edit") {
      setPreviewBody(bodyRef.current);
    }
  }, [viewMode]);

  // Wikilink hash navigation: when AppShell asks us to scroll to a
  // `#heading` after a wiki-link click, force preview mode (so there's
  // something to scroll to) and find the matching heading id from
  // rehype-slug. Critical: rehype-slug uses `github-slugger` to derive
  // ids (lowercase + hyphenated), so we MUST run the same slugger on
  // pendingHash before querying — otherwise `[[Note#Conclusion]]` looks
  // for `#Conclusion` and finds nothing (the actual id is `#conclusion`).
  useEffect(() => {
    if (!pendingHash || !note.data) return;
    // Switching from edit to split is the whole point of a wikilink-with-
    // anchor click — there's nothing to scroll to in edit mode. Skip
    // the switch when caller asked us to preserve mode (outline-driven
    // intra-note jumps).
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (!preserveViewMode && viewMode === "edit") setViewMode("split");
    setPreviewBody(bodyRef.current);
    const slugger = new GithubSlugger();
    const slug = slugger.slug(pendingHash);
    let cancelled = false;
    const t0 = Date.now();
    const tick = () => {
      if (cancelled) return;
      const root = document.querySelector('[data-testid="markdown-preview"]');
      // Try slugged form first (canonical), then literal as a fallback
      // for any future renderer that doesn't slug.
      const target =
        root?.querySelector(`#${CSS.escape(slug)}`) ??
        root?.querySelector(`#${CSS.escape(pendingHash)}`);
      if (target) {
        target.scrollIntoView({ behavior: "smooth", block: "start" });
        onPendingHashConsumed?.();
        return;
      }
      // Try for up to 1.5 s — KaTeX / Mermaid lazy-render can delay the
      // heading layout briefly.
      if (Date.now() - t0 < 1500) requestAnimationFrame(tick);
      else onPendingHashConsumed?.();
    };
    requestAnimationFrame(tick);
    return () => {
      cancelled = true;
    };
  }, [pendingHash, note.data, viewMode, onPendingHashConsumed, preserveViewMode]);

  // Phase 1 C slice 1 — Backlinks-driven line jump. When AppShell asks us
  // to scroll to line N (1-based), force a mode that shows the editor
  // (split or edit), then dispatch a CodeMirror selection + scrollIntoView
  // at the line's start offset. Retry up to 1.5s because the editor view
  // may not be mounted yet right after a note swap.
  useEffect(() => {
    if (!pendingLine || !note.data) return;
    // Cross-note nav (backlinks click) wants preview→split so the
    // user sees the line. Intra-note jumps (outline) keep the user's
    // chosen mode — see preserveViewMode prop docstring.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (!preserveViewMode && viewMode === "preview") setViewMode("split");
    let cancelled = false;
    const t0 = Date.now();
    const tick = () => {
      if (cancelled) return;
      const view = editorViewRef.current;
      if (view) {
        const doc = view.state.doc;
        const lineNo = Math.max(1, Math.min(pendingLine, doc.lines));
        const line = doc.line(lineNo);
        view.dispatch({
          selection: { anchor: line.from, head: line.from },
          effects: EditorView.scrollIntoView(line.from, { y: "center" }),
        });
        // Don't pull focus — user might still be hovering the rail. The
        // scroll happens; cursor moves; that's enough.
        onPendingLineConsumed?.();
        return;
      }
      if (Date.now() - t0 < 1500) requestAnimationFrame(tick);
      else onPendingLineConsumed?.();
    };
    requestAnimationFrame(tick);
    return () => {
      cancelled = true;
    };
  }, [pendingLine, note.data, viewMode, onPendingLineConsumed, preserveViewMode]);

  // Flush pending edits for the previous note BEFORE remount.
  useEffect(() => {
    return () => {
      flushSave();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [noteId]);

  const handleChange = useCallback(
    (next: string) => {
      bodyRef.current = next;
      dirtyRef.current = next !== lastSavedRef.current;
      if (dirtyRef.current) scheduleSave();
      // Live-mirror to preview only in split mode — keeps the right
      // pane in sync as the user types. In edit-only and preview-only
      // modes there's no live render, so skip the re-render cost.
      if (viewMode === "split") setPreviewBody(next);
    },
    [scheduleSave, viewMode],
  );

  // Lazy reader the wikilink autocomplete extension calls on each
  // keystroke — pulls the latest tree out of the QueryClient cache so
  // suggestions track folder / note creation without re-mounting CM.
  const getTreeForAutocomplete = useMemo(
    () => () => qc.getQueryData<TreeFolder>(QK.tree),
    [qc],
  );
  // Async cache-aware body fetcher for `[[Title#` heading completions.
  // Hits the cache first (no network if the target note was already
  // visited), then falls back to fetchQuery which de-dupes concurrent
  // requests for the same noteId. Returning null on error keeps the
  // popup quiet rather than blowing up the editor.
  const getNoteBodyForAutocomplete = useMemo(
    () => async (id: string) => {
      const cached = qc.getQueryData<NoteFull>(QK.note(id));
      if (cached) return cached.body;
      try {
        const fetched = await qc.fetchQuery({
          queryKey: QK.note(id),
          queryFn: () => getNote(id),
        });
        return fetched.body;
      } catch {
        return null;
      }
    },
    [qc],
  );

  // Slash-command (`/`) inline template insertion. The list comes from
  // the cached templates query (kept fresh by the rest of the app's
  // mutations); the body fetch hits the same per-note cache the
  // wikilink heading completion uses, then runs `{{title}}` /
  // `{{date}}` substitution against the *current* note's title.
  const getTemplatesForSlash = useMemo(
    () => () => qc.getQueryData<TemplateSummary[]>(QK.templates) ?? [],
    [qc],
  );
  const fetchTemplateBodyForSlash = useMemo(
    () => async (id: string) => {
      const cached = qc.getQueryData<NoteFull>(QK.note(id));
      if (cached) return cached.body;
      try {
        const fetched = await qc.fetchQuery({
          queryKey: QK.note(id),
          queryFn: () => getNote(id),
        });
        return fetched.body;
      } catch {
        return null;
      }
    },
    [qc],
  );
  const substituteForSlash = useMemo(
    () => (body: string) => {
      const title = note.data?.title ?? "";
      const today = new Date().toISOString().slice(0, 10);
      // Match the backend's regex shape so behaviour is consistent.
      return body.replace(
        /\{\{\s*([a-zA-Z_][\w-]*)\s*\}\}/g,
        (full, key: string) => {
          const k = key.toLowerCase();
          if (k === "title") return title;
          if (k === "date") return today;
          return full;
        },
      );
    },
    [note.data?.title],
  );
  // Keep the templates query primed so the slash menu has something
  // to show on the first `/` keystroke without a network round-trip.
  useQuery({ queryKey: QK.templates, queryFn: listTemplates });
  const templateSlashLabels = useMemo(
    () => ({ insert: t("templates.slashLabel"), empty: t("templates.slashEmpty") }),
    [t],
  );

  // Title click-to-edit handlers. The rename is queued behind any
  // in-flight save and, like every write, sends the editor's latest body.
  const submitTitle = useCallback(
    (raw: string) => {
      // Same normalization as create + tree-rename — trailing `.md` is
      // a storage detail, never part of the title.
      const next = normalizeNoteTitle(raw);
      if (!next || !note.data) {
        setEditingTitle(false);
        return;
      }
      if (next === note.data.title) {
        setEditingTitle(false);
        return;
      }
      // Pre-flight against the cached tree for a sibling collision —
      // matches the FileTree create + rename paths. Pass the current
      // note's id as `excludeId` so renaming to your own current
      // title isn't (incorrectly) treated as a clash.
      const tree = qc.getQueryData<TreeFolder>(QK.tree);
      const folder = note.data.folder ?? "";
      if (noteTitleClashesIn(tree, folder, next, note.data.id)) {
        // Dogfood feedback: keeping the input open after a blocked
        // rename strands the user — they have to manually click /
        // Esc to recover. Closing the editor (revert to the
        // current title implicitly) is the natural "operation
        // failed, undo" state. The alert tells them WHY; the
        // closed h1 tells them WHERE we are. They re-click the h1
        // if they want to retry.
        window.alert(t("menu.duplicateNote", { name: next }));
        setEditingTitle(false);
        return;
      }
      const id = note.data.id;
      const prevTitle = note.data.title;
      // Optimistic in the tree as well, so the file-tree row updates on
      // the same frame as the h1.
      const prevTree = qc.getQueryData<TreeFolder>(QK.tree);
      if (prevTree) {
        qc.setQueryData<TreeFolder>(
          QK.tree,
          updateNoteTitleInTree(prevTree, id, next),
        );
      }
      changeMeta(id, { title: next }, () => {
        qc.setQueryData<TreeFolder>(QK.tree, (cur) =>
          cur ? updateNoteTitleInTree(cur, id, prevTitle) : cur,
        );
      }).catch(() => undefined);
      setEditingTitle(false);
    },
    [changeMeta, note.data, qc, t],
  );
  const cancelTitle = useCallback(() => setEditingTitle(false), []);

  if (!noteId) {
    return (
      <div className="kn-paper flex h-full items-center justify-center text-sm text-muted-foreground">
        {t("note.selectPrompt")}
      </div>
    );
  }
  if (note.isLoading) {
    return <div className="p-6 text-sm text-muted-foreground">{t("tree.loading")}</div>;
  }
  if (note.isError && !note.data) {
    // ApiError is `{status, detail}`. ``String({...})`` gives the
    // notorious "[object Object]" — extract ``detail`` first, then
    // fall back to ``message`` for native Error, then a final
    // string coerce as belt-and-braces.
    const e = note.error as { detail?: string; message?: string } | null;
    const errStr =
      e?.detail ?? e?.message ?? (note.error ? String(note.error) : "unknown");
    return (
      <div className="p-6 text-sm text-destructive">
        {t("note.loadFailed", { error: errStr })}
      </div>
    );
  }
  if (!note.data) return null;

  return (
    <div className="kn-paper flex h-full flex-col">
      {note.data.frontmatter_status === "corrupted" && (
        <FrontmatterCorruptedNotice
          noteId={note.data.id}
          corruption={note.data.frontmatter_corruption}
        />
      )}
      <header className="shrink-0 px-10 pt-6 pb-3">
        <div className="flex items-baseline justify-between gap-4">
          {editingTitle ? (
            <div className="flex-1">
              <InlineEditInput
                initial={note.data.title}
                placeholder={t("note.titlePlaceholder")}
                onSubmit={submitTitle}
                onCancel={cancelTitle}
                dataTestId="title-edit-input"
                // Make the input read as a direct replacement for
                // the h1 it stands in for: same serif font, same
                // 28px size, same ink color, no border / bg / ring.
                // A subtle bottom underline marks the edit affordance
                // without the layout-shifting box of the default
                // tree-row styling.
                className="block w-full rounded-sm border-0 border-b bg-transparent p-0 font-serif font-semibold outline-none ring-0 focus:border-b focus:outline-none"
                style={{
                  color: "var(--ink)",
                  fontSize: 28,
                  lineHeight: 1.18,
                  letterSpacing: "-0.014em",
                  borderBottomColor: "var(--ring)",
                  borderBottomWidth: 1,
                }}
              />
            </div>
          ) : (
            <h1
              className="cursor-text rounded-sm font-serif font-semibold transition-colors hover:bg-accent/40"
              style={{
                color: "var(--ink)",
                fontSize: 28,
                lineHeight: 1.18,
                letterSpacing: "-0.014em",
                wordBreak: "break-word",
              }}
              role="button"
              tabIndex={0}
              data-testid="note-title"
              title={t("note.editTitleHint")}
              onClick={() => setEditingTitle(true)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === "F2") {
                  e.preventDefault();
                  // Consumed here: the file tree's window-level F2 must
                  // not also open a rename of its selected row.
                  e.stopPropagation();
                  setEditingTitle(true);
                }
              }}
            >
              {note.data.title}
            </h1>
          )}
          <div className="flex items-center gap-3">
            {/* Phase 3 Stage 2 — kind chip (knowledge / reference).
             * ADR-0029 §4.5 meta principle: type must be visible on
             * the same screen the user makes save decisions. Click
             * to toggle; demote (knowledge → reference) opens a
             * popover for confirmation. */}
            <KindChip
              kind={note.data.kind ?? "knowledge"}
              variant="chip"
              onConfirmedToggle={(next) =>
                setKindMutation.mutate({ id: note.data.id, kind: next })
              }
            />
            {/* Reserve a fixed slot so the toolbar / title baseline doesn't
             * jump when the badge text appears + disappears. The visible
             * text is wrapped in a span we toggle with `visibility`, which
             * preserves layout during the idle / saved transition. */}
            <span
              className="inline-flex min-w-16 items-center justify-end gap-2 font-mono text-[11px] uppercase tracking-wider"
              style={{
                color:
                  savingState === "error"
                    ? "var(--err, #c0392b)"
                    : "var(--ink-mute)",
              }}
              data-testid="autosave-state"
              data-state={savingState}
            >
              {savingState === "error" ? (
                <>
                  <span title={t("note.saveFailedHint")}>
                    {t("note.saveFailed")}
                  </span>
                  <button
                    type="button"
                    data-testid="autosave-retry"
                    onClick={retryFailedSave}
                    className="rounded border px-1.5 py-0.5 text-[10px] uppercase tracking-wider transition-colors hover:bg-accent/30"
                    style={{ borderColor: "currentColor" }}
                  >
                    {t("note.saveFailedRetry")}
                  </button>
                </>
              ) : (
                <span
                  style={{
                    visibility: savingState === "idle" ? "hidden" : "visible",
                  }}
                >
                  {savingState === "saving" && t("note.saving")}
                  {savingState === "saved" && t("note.saved")}
                  {savingState === "idle" && t("note.saved")}
                </span>
              )}
            </span>
            <StarToggle noteId={note.data.id} />
            <SyncStatusBadge
              noteId={note.data?.id ?? null}
              isSaving={savingState === "saving"}
              hasUnsavedEdits={dirtyRef.current}
              onConflictClick={() => setMergeOpen(true)}
            />
            <ConflictMergeView
              noteId={note.data?.id ?? null}
              noteTitle={note.data?.title ?? ""}
              open={mergeOpen}
              onOpenChange={setMergeOpen}
            />
            <ViewModeToggle value={viewMode} onChange={setViewMode} t={t} />
          </div>
        </div>
        {/* Row B — kicker: folder · ULID · UPDATED · source pill · ▸ Properties */}
        <div
          className="mt-1.5 flex flex-wrap items-center font-mono text-[11px] uppercase tracking-wider"
          style={{ color: "var(--ink-mute)" }}
        >
          <span>{note.data.folder || t("note.rootLabel")}</span>
          <KickerSep />
          <span>{note.data.id.slice(0, 8)}</span>
          <KickerSep />
          <span>
            {t("note.updatedPrefix")} {note.data.updated_at.slice(0, 10)}
          </span>
          {note.data.source ? (
            <>
              <KickerSep />
              <SourceKickerPill url={note.data.source} />
            </>
          ) : null}
          <span style={{ flex: 1 }} />
          <PropertiesToggle
            collapsed={propsCollapse.collapsed}
            onToggle={propsCollapse.toggle}
          />
        </div>
        {/* Row C — chips: tags │ aliases (only when ≥1 of either) */}
        {(note.data.tags.length > 0 || (note.data.aliases ?? []).length > 0) && (
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <TagChipStrip
              tags={note.data.tags}
              noteId={note.data.id}
              onAdd={(tag) => addTag(note.data.id, tag)}
              onRemove={(tag) => removeTag(note.data.id, tag)}
            />
            {note.data.tags.length > 0 && (note.data.aliases ?? []).length > 0 && (
              <span
                aria-hidden="true"
                style={{
                  display: "inline-block",
                  width: 1,
                  height: 14,
                  background: "var(--line)",
                  margin: "0 4px",
                }}
              />
            )}
            <AliasChipStrip
              aliases={note.data.aliases ?? []}
              noteId={note.data.id}
              onAdd={(alias) => addAlias(note.data.id, alias)}
              onRemove={(alias) => removeAlias(note.data.id, alias)}
            />
          </div>
        )}
        {/* Row D — Properties expanded: only created + full source URL */}
        <PropertiesContent
          collapsed={propsCollapse.collapsed}
          source={note.data.source ?? null}
          createdAt={note.data.created_at}
        />
        {/* Empty-state affordance: when both tags + aliases are empty,
         *  give the user discoverable add buttons. Per design these
         *  could be ghosts in the kicker; for v1 we render them as a
         *  separate compact row right after kicker so the chip-strip
         *  state machinery (input edit / IME) can be reused without
         *  splitting the components. */}
        {note.data.tags.length === 0 &&
          (note.data.aliases ?? []).length === 0 && (
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              <TagChipStrip
                tags={note.data.tags}
                noteId={note.data.id}
                onAdd={(tag) => addTag(note.data.id, tag)}
                onRemove={() => {
                  /* no-op — empty */
                }}
              />
              <span
                aria-hidden="true"
                style={{
                  display: "inline-block",
                  width: 1,
                  height: 14,
                  background: "var(--line)",
                  margin: "0 4px",
                }}
              />
              <AliasChipStrip
                aliases={note.data.aliases ?? []}
                noteId={note.data.id}
                onAdd={(alias) => addAlias(note.data.id, alias)}
                onRemove={() => {
                  /* no-op — empty */
                }}
              />
            </div>
          )}
      </header>
      {/* Both panes are ALWAYS mounted — we toggle visibility via the
        * `hidden` class instead of conditionally rendering. Two wins:
        *   - scroll position survives mode toggles (split → preview-
        *     only → split lands you back where you were);
        *   - the EditorView + ref stay alive across modes, so the
        *     scroll-sync effect can re-attach without polling for a
        *     freshly-mounted view.
        * `min-w-0` keeps a long line / wide diagram from pushing one
        * pane past 50% and crushing the other.
        */}
      <div className="flex min-h-0 flex-1 px-10 pb-8 gap-6">
        <div
          className={`min-h-0 min-w-0 flex-1 ${
            viewMode === "preview" ? "hidden" : ""
          }`}
          data-testid="markdown-editor"
          data-view-mode={viewMode}
        >
          <MarkdownEditor
            // key forces a fresh mount per note; MarkdownEditor reads
            // initialValue only on mount. A remount of the already-loaded
            // note reseeds from the live editor text, not the cache.
            key={note.data.id}
            initialValue={
              loadedIdRef.current === note.data.id
                ? bodyRef.current
                : note.data.body
            }
            onChange={handleChange}
            onBlur={flushSave}
            getTree={getTreeForAutocomplete}
            getNoteBody={getNoteBodyForAutocomplete}
            getTemplates={getTemplatesForSlash}
            fetchTemplateBody={fetchTemplateBodyForSlash}
            substituteTemplate={substituteForSlash}
            templateSlashLabels={templateSlashLabels}
            onViewMount={(view) => {
              editorViewRef.current = view;
            }}
          />
        </div>
        {viewMode === "split" && (
          <div
            className="min-h-0 w-px shrink-0 self-stretch"
            style={{ background: "var(--accent-soft)" }}
          />
        )}
        <div
          ref={previewWrapperRef}
          className={`min-h-0 min-w-0 flex-1 overflow-y-auto ${
            viewMode === "edit" ? "hidden" : ""
          }`}
          data-testid="markdown-preview"
        >
          <MarkdownPreview value={previewBody} />
        </div>
      </div>
    </div>
  );
}

type ToggleProps = {
  value: ViewMode;
  onChange: (next: ViewMode) => void;
  t: (key: string) => string;
};

/** Tiny `·` separator inside the kicker row. Same color register as
 *  the surrounding mono text but `--ink-faint` so the dots recede
 *  visually below the words they separate. */
function StarToggle({ noteId }: { noteId: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const favs = useQuery({
    queryKey: QK.favorites,
    queryFn: listFavorites,
    staleTime: 30_000,
  });
  const isStarred = (favs.data?.favorites ?? []).some((f) => f.id === noteId);
  const onSuccess = (res: { favorites: { id: string; title: string | null }[] }) =>
    qc.setQueryData(QK.favorites, res);
  const addMut = useMutation({ mutationFn: addFavorite, onSuccess });
  const removeMut = useMutation({ mutationFn: removeFavorite, onSuccess });
  const busy = addMut.isPending || removeMut.isPending;
  return (
    <button
      type="button"
      data-testid="note-star-toggle"
      data-starred={isStarred ? "true" : "false"}
      aria-label={isStarred ? t("favorites.unstar") : t("favorites.star")}
      title={isStarred ? t("favorites.starred") : t("favorites.star")}
      disabled={busy}
      onClick={() => {
        if (isStarred) removeMut.mutate(noteId);
        else addMut.mutate(noteId);
      }}
      className="flex size-7 items-center justify-center rounded-sm transition-colors hover:bg-accent/30"
      style={{
        color: isStarred ? "rgb(245 158 11)" : "var(--ink-mute)",
      }}
    >
      <Star
        className={`size-4 ${isStarred ? "fill-current" : ""}`}
      />
    </button>
  );
}

function KickerSep() {
  return (
    <span
      aria-hidden="true"
      style={{ color: "var(--ink-faint)", padding: "0 8px", userSelect: "none" }}
    >
      ·
    </span>
  );
}

function ViewModeToggle({ value, onChange, t }: ToggleProps) {
  // Segmented control. We don't pull in shadcn's ToggleGroup here because
  // (a) only used in this one place, (b) it would add Radix Toggle code
  // we don't otherwise need, (c) three buttons and a `data-active` is a
  // shorter implementation than configuring ToggleGroup primitives.
  const items: { mode: ViewMode; label: string; Icon: typeof Pen }[] = [
    { mode: "edit", label: t("note.viewEdit"), Icon: Pen },
    { mode: "split", label: t("note.viewSplit"), Icon: Columns2 },
    { mode: "preview", label: t("note.viewPreview"), Icon: Eye },
  ];
  return (
    <div
      className="flex items-center rounded-md border p-0.5"
      style={{ borderColor: "var(--accent-soft)", background: "var(--bg-1)" }}
      role="tablist"
      data-testid="view-mode-toggle"
    >
      {items.map(({ mode, label, Icon }) => {
        const active = value === mode;
        return (
          <button
            key={mode}
            type="button"
            role="tab"
            aria-selected={active}
            aria-label={label}
            title={label}
            data-mode={mode}
            data-active={active}
            onClick={() => onChange(mode)}
            className="flex size-7 items-center justify-center rounded-sm transition-colors"
            style={{
              background: active ? "var(--accent-tint-2)" : "transparent",
              color: active ? "var(--ink)" : "var(--ink-mute)",
            }}
          >
            <Icon className="size-3.5" />
          </button>
        );
      })}
    </div>
  );
}
