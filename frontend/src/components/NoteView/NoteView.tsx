/**
 * Phase 1 B note view — uncontrolled CodeMirror editor + debounced auto-save.
 *
 * The editor is uncontrolled: we seed it with `initialValue` once per
 * note (forced via `key={note.id}`) and then read changes into a ref
 * inside `onChange`. We do NOT keep the body in React state — that would
 * re-render on every keystroke and race react-codemirror's value-sync
 * back into the editor.
 *
 * Save flow:
 *   - onChange  → bodyRef.current = next; mark dirty; scheduleSave (800 ms)
 *   - onBlur    → flushSave (cancel debounce, save now)
 *   - noteId change → flushSave for the previous note before remount
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import GithubSlugger from "github-slugger";
import { Columns2, Eye, Pen } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { getNote, listTemplates, updateNote } from "@/api/client";
import type { TemplateSummary } from "@/api/client";
import type { NoteFull, TreeFolder } from "@/api/types";
import { EditorView } from "@codemirror/view";

import { MarkdownEditor } from "@/components/Editor/MarkdownEditor";
import { MarkdownPreview } from "@/components/Editor/MarkdownPreview";
import { InlineEditInput } from "@/components/InlineEdit/InlineEditInput";
import { ConflictMergeView } from "@/components/Sync/ConflictMergeView";
import { SyncStatusBadge } from "@/components/Sync/SyncStatusBadge";
import { noteTitleClashesIn } from "@/lib/findCollision";
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
  // The note metadata (title/tags) we send back unchanged in the PUT.
  // Kept as a ref so flushSave doesn't depend on a re-rendering value.
  const noteMetaRef = useRef<NoteFull | null>(null);
  // Last value that successfully reached the backend. Used to skip no-op
  // saves and to short-circuit dirty checks.
  const lastSavedRef = useRef("");
  const dirtyRef = useRef(false);
  const debounceRef = useRef<number | null>(null);
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
  const propsCollapse = usePropertiesCollapsed();
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

  const saveMutation = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: NoteFull }) =>
      updateNote(id, {
        title: payload.title,
        tags: payload.tags,
        body: payload.body,
        // D3: PUT defaults aliases to [] when missing (which CLEARS
        // them server-side). Pass current aliases through so a body /
        // title / tag save never wipes them.
        aliases: payload.aliases ?? [],
      }),
    // Auto-retry transient failures (network blip, slow backend) with
    // exponential backoff. After 3 attempts (~14s max wait) we give
    // up and surface the failure visibly via onError below — per the
    // "no silent failure" UX rule from sync-design discussion.
    retry: 3,
    retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 10000),
    onSuccess: (data, vars) => {
      qc.setQueryData(QK.note(vars.id), data);
      // Body saves can include inline `#tag` syntax that the backend
      // merges into frontmatter. Invalidate tag caches so the Tag
      // browser reflects new tags without a manual reload.
      void qc.invalidateQueries({ queryKey: QK.tags });
      void qc.invalidateQueries({ queryKey: QK.tagsWithNotes });
      // Only update the badge / dirty flag for the CURRENTLY-loaded note.
      // A late-arriving response from the previous note (after a switch)
      // shouldn't flip the new note's UI back to "saved".
      if (loadedIdRef.current === vars.id) {
        lastSavedRef.current = data.body;
        dirtyRef.current = false;
        setSavingState("saved");
        window.setTimeout(() => {
          if (loadedIdRef.current === vars.id) setSavingState("idle");
        }, 1200);
      }
    },
    onError: (_err, vars) => {
      // Reaching here means the backend rejected us OR all retries
      // exhausted. The user must know — saving silently dropping
      // edits is exactly the "沉默地陷入糟糕状态" failure mode the
      // sync-design memory rules out.
      if (loadedIdRef.current === vars.id) {
        setSavingState("error");
      }
    },
  });

  // Manual retry — clicked from the error badge. Re-fires the same
  // save with the current editor body so the user doesn't lose
  // anything just because the auto-retries exhausted.
  const retryFailedSave = useCallback(() => {
    const id = loadedIdRef.current;
    const meta = note.data;
    if (!id || !meta) return;
    setSavingState("saving");
    saveMutation.mutate({
      id,
      payload: { ...meta, body: bodyRef.current },
    });
  }, [note.data, saveMutation]);

  // Title rename — fired when the user finishes editing the inline
  // title input. Optimistic against both the per-note query AND the
  // tree query, so the right-pane h1 + the file tree row both update
  // on the same frame the user pressed Enter (no flash of old name).
  const renameTitleMutation = useMutation({
    mutationFn: ({
      id,
      title,
      payload,
    }: {
      id: string;
      title: string;
      payload: NoteFull;
    }) =>
      updateNote(id, {
        title,
        tags: payload.tags,
        body: payload.body,
        aliases: payload.aliases ?? [],
      }),
    onMutate: ({ id, title }) => {
      const prevTree = qc.getQueryData<TreeFolder>(QK.tree);
      const prevNote = qc.getQueryData<NoteFull>(QK.note(id));
      if (prevTree) {
        qc.setQueryData<TreeFolder>(
          QK.tree,
          updateNoteTitleInTree(prevTree, id, title),
        );
      }
      if (prevNote) {
        qc.setQueryData<NoteFull>(QK.note(id), { ...prevNote, title });
      }
      return { prevTree, prevNote };
    },
    onError: (_err, vars, ctx) => {
      if (ctx?.prevTree) qc.setQueryData(QK.tree, ctx.prevTree);
      if (ctx?.prevNote) qc.setQueryData(QK.note(vars.id), ctx.prevNote);
    },
    onSuccess: (data, vars) => {
      qc.setQueryData(QK.note(vars.id), data);
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: QK.tree });
    },
  });

  // Phase 1 C polish — tag-only update (chip strip add/remove). Mirrors
  // the rename pattern: optimistic update on the cached note + tree, with
  // QK.tags invalidation on success so the left-rail Tag browser refreshes.
  const updateTagsMutation = useMutation({
    mutationFn: ({
      id,
      tags,
      payload,
    }: {
      id: string;
      tags: string[];
      payload: NoteFull;
    }) =>
      updateNote(id, {
        title: payload.title,
        tags,
        body: payload.body,
        aliases: payload.aliases ?? [],
      }),
    onMutate: ({ id, tags }) => {
      const prevNote = qc.getQueryData<NoteFull>(QK.note(id));
      if (prevNote) {
        qc.setQueryData<NoteFull>(QK.note(id), { ...prevNote, tags });
      }
      return { prevNote };
    },
    onError: (_err, vars, ctx) => {
      if (ctx?.prevNote) qc.setQueryData(QK.note(vars.id), ctx.prevNote);
    },
    onSuccess: (data, vars) => {
      qc.setQueryData(QK.note(vars.id), data);
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: QK.tags });
      void qc.invalidateQueries({ queryKey: QK.tagsWithNotes });
      void qc.invalidateQueries({ queryKey: QK.tree });
    },
  });

  // Phase 1 D / D3 — aliases mutation. Same shape as tag updates but
  // doesn't touch QK.tags / QK.tagsWithNotes (aliases are per-note
  // metadata, not a vault-wide taxonomy).
  const updateAliasesMutation = useMutation({
    mutationFn: ({
      id,
      aliases,
      payload,
    }: {
      id: string;
      aliases: string[];
      payload: NoteFull;
    }) =>
      updateNote(id, {
        title: payload.title,
        tags: payload.tags,
        body: payload.body,
        aliases,
      }),
    onMutate: ({ id, aliases }) => {
      const prevNote = qc.getQueryData<NoteFull>(QK.note(id));
      if (prevNote) {
        qc.setQueryData<NoteFull>(QK.note(id), { ...prevNote, aliases });
      }
      return { prevNote };
    },
    onError: (_err, vars, ctx) => {
      if (ctx?.prevNote) qc.setQueryData(QK.note(vars.id), ctx.prevNote);
    },
    onSuccess: (data, vars) => {
      qc.setQueryData(QK.note(vars.id), data);
    },
  });

  const flushSave = useCallback(() => {
    if (debounceRef.current !== null) {
      window.clearTimeout(debounceRef.current);
      debounceRef.current = null;
    }
    if (!dirtyRef.current) return;
    const id = loadedIdRef.current;
    const meta = noteMetaRef.current;
    const body = bodyRef.current;
    if (!id || !meta) return;
    if (body === lastSavedRef.current) {
      dirtyRef.current = false;
      return;
    }
    if (loadedIdRef.current === id) setSavingState("saving");
    saveMutation.mutate({ id, payload: { ...meta, body } });
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

  // When server data lands for a new note, prime the refs. This runs once
  // per note (the equality check guards against re-runs from refetch).
  useEffect(() => {
    if (!note.data) return;
    if (loadedIdRef.current === note.data.id) {
      // Same note — keep the user's in-progress edits intact, but
      // refresh the metadata snapshot in case title/tags were updated
      // by a tree-side rename mutation.
      noteMetaRef.current = note.data;
      return;
    }
    bodyRef.current = note.data.body;
    lastSavedRef.current = note.data.body;
    loadedIdRef.current = note.data.id;
    noteMetaRef.current = note.data;
    setPreviewBody(note.data.body);
    dirtyRef.current = false;
    setSavingState("idle");
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
    setPreviewBody(note.data.body);
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
      if (next !== lastSavedRef.current) {
        dirtyRef.current = true;
        scheduleSave();
      }
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

  // Title click-to-edit handlers. We:
  //   - flush any pending body save first (so its payload reflects the
  //     pre-rename body before the title-rename payload overwrites it)
  //   - send the rename via PUT /api/notes/{id} with the latest body
  //     to avoid a race where two in-flight PUTs trample each other
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
      flushSave();
      renameTitleMutation.mutate({
        id: note.data.id,
        title: next,
        payload: { ...note.data, body: bodyRef.current },
      });
      setEditingTitle(false);
    },
    [flushSave, note.data, qc, renameTitleMutation, t],
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
  if (note.isError) {
    return (
      <div className="p-6 text-sm text-destructive">
        {t("note.loadFailed", { error: String(note.error) })}
      </div>
    );
  }
  if (!note.data) return null;

  return (
    <div className="kn-paper flex h-full flex-col">
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
                  setEditingTitle(true);
                }
              }}
            >
              {note.data.title}
            </h1>
          )}
          <div className="flex items-center gap-3">
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
              onAdd={(tag) => {
                const next = [...note.data!.tags, tag];
                updateTagsMutation.mutate({
                  id: note.data!.id,
                  tags: next,
                  payload: note.data!,
                });
              }}
              onRemove={(tag) => {
                const next = note.data!.tags.filter((t) => t !== tag);
                updateTagsMutation.mutate({
                  id: note.data!.id,
                  tags: next,
                  payload: note.data!,
                });
              }}
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
              onAdd={(alias) => {
                const next = [...(note.data!.aliases ?? []), alias];
                updateAliasesMutation.mutate({
                  id: note.data!.id,
                  aliases: next,
                  payload: note.data!,
                });
              }}
              onRemove={(alias) => {
                const next = (note.data!.aliases ?? []).filter(
                  (a) => a !== alias,
                );
                updateAliasesMutation.mutate({
                  id: note.data!.id,
                  aliases: next,
                  payload: note.data!,
                });
              }}
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
                onAdd={(tag) =>
                  updateTagsMutation.mutate({
                    id: note.data!.id,
                    tags: [tag],
                    payload: note.data!,
                  })
                }
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
                onAdd={(alias) =>
                  updateAliasesMutation.mutate({
                    id: note.data!.id,
                    aliases: [alias],
                    payload: note.data!,
                  })
                }
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
            // key forces a fresh mount per note — the editor is uncontrolled
            // after that, so we never push value back in mid-edit.
            key={note.data.id}
            initialValue={note.data.body}
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
