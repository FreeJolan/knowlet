/**
 * Thin fetch wrappers around the FastAPI backend.
 *
 * All requests target `/api/*` — Vite dev-proxies that to localhost:8000;
 * production builds get the same prefix from FastAPI's StaticFiles mount.
 */

import type {
  ApiError,
  BacklinkRow,
  FolderResponse,
  GraphPayload,
  NoteFull,
  NoteSummary,
  QuickAction,
  QuickActionPayload,
  SearchPayload,
  TagSummary,
  TagWithNotes,
  TrashListResponse,
  TreeFolder,
} from "./types";

async function request<T>(
  method: string,
  url: string,
  body?: unknown,
): Promise<T> {
  const init: RequestInit = {
    method,
    headers: { "Content-Type": "application/json" },
  };
  if (body !== undefined) init.body = JSON.stringify(body);
  const r = await fetch(url, init);
  if (!r.ok) {
    let detail = r.statusText;
    try {
      const data = (await r.json()) as { detail?: string };
      if (data.detail) detail = data.detail;
    } catch {
      // body wasn't JSON; keep statusText
    }
    const err: ApiError = { status: r.status, detail };
    throw err;
  }
  if (r.status === 204) return undefined as T;
  return (await r.json()) as T;
}

// ---------- tree / folders ----------

export const getTree = (): Promise<TreeFolder> => request("GET", "/api/tree");

export const createFolder = (path: string): Promise<FolderResponse> =>
  request("POST", "/api/folders", { path });

export const renameFolder = (
  path: string,
  newName: string,
): Promise<FolderResponse> =>
  request("PATCH", "/api/folders", { path, new_name: newName });

export const moveFolder = (
  src: string,
  dstParent: string,
): Promise<FolderResponse> =>
  request("POST", "/api/folders/move", { src, dst_parent: dstParent });

export const deleteFolder = (path: string): Promise<{ trashed_count: number }> =>
  request("DELETE", "/api/folders", { path });

// ---------- notes ----------

export const getNote = (id: string): Promise<NoteFull> =>
  request("GET", `/api/notes/${encodeURIComponent(id)}`);

export const moveNote = (id: string, targetFolder: string): Promise<NoteFull> =>
  request("POST", `/api/notes/${encodeURIComponent(id)}/move`, {
    target_folder: targetFolder,
  });

export const deleteNote = (id: string): Promise<{ trashed_to: string }> =>
  request("DELETE", `/api/notes/${encodeURIComponent(id)}`);

export const updateNote = (
  id: string,
  payload: { title: string; tags: string[]; body: string; aliases?: string[] },
): Promise<NoteFull> =>
  request("PUT", `/api/notes/${encodeURIComponent(id)}`, payload);

// Create a note via the existing POST /api/notes (sediment commit shape).
// Phase 1 B will add a dedicated /api/notes/new for empty notes; for now
// the UI uses this with empty body and Phase 1 A mkdir-then-edit.
export const createNote = (
  payload: { title: string; tags: string[]; body: string },
): Promise<{ note_id: string; path: string }> =>
  request("POST", "/api/notes", payload);

// Phase 1 A: create an empty note with title + folder placement. Distinct
// from createNote (sediment-commit shape, flat).
export const createBlankNote = (payload: {
  title: string;
  folder?: string;
  tags?: string[];
  templateId?: string;
}): Promise<NoteFull> =>
  request("POST", "/api/notes/new", {
    title: payload.title,
    folder: payload.folder ?? "",
    tags: payload.tags ?? [],
    template_id: payload.templateId ?? null,
  });

// ---------- backlinks (Phase 1 C slice 1) ----------

export const getBacklinks = (noteId: string): Promise<BacklinkRow[]> =>
  request("GET", `/api/notes/${encodeURIComponent(noteId)}/backlinks`);

// ---------- tags (Phase 1 C slice 2) ----------

export const listTags = (): Promise<TagSummary[]> =>
  request("GET", "/api/tags");

export const listNotesByTag = (tag: string): Promise<NoteSummary[]> =>
  request("GET", `/api/tags/${encodeURIComponent(tag)}/notes`);

export const listTagsWithNotes = (): Promise<TagWithNotes[]> =>
  request("GET", "/api/tags/all-with-notes");

// ---------- graph (Phase 1 C slice 3) ----------

export const getGraph = (): Promise<GraphPayload> =>
  request("GET", "/api/graph");

// ---------- quick actions (Phase 2 D slice 2c, ADR-0025) ----------

export const listQuickActions = (): Promise<QuickAction[]> =>
  request("GET", "/api/quick-actions");

export const createQuickAction = (
  payload: QuickActionPayload,
): Promise<QuickAction> => request("POST", "/api/quick-actions", payload);

export const updateQuickAction = (
  id: string,
  payload: QuickActionPayload,
): Promise<QuickAction> =>
  request("PUT", `/api/quick-actions/${encodeURIComponent(id)}`, payload);

export const deleteQuickAction = (id: string): Promise<{ ok: boolean }> =>
  request("DELETE", `/api/quick-actions/${encodeURIComponent(id)}`);

export const runQuickAction = (id: string): Promise<NoteFull> =>
  request("POST", `/api/quick-actions/${encodeURIComponent(id)}/run`);

// ---------- sync notifications (Phase 2 E Slice 5.D, ADR-0027) ----------

export interface SyncNotification {
  note_id: string;
  drive_file_id: string;
  detected_at: string;
  new_revision: string | null;
  drive_file_name: string | null;
  /** Human-friendly title pulled from local note frontmatter. The
   *  Drive filename is a ULID (per ADR-0006 on-disk convention),
   *  so callers should prefer this for display. */
  note_title?: string | null;
  removed: boolean;
}

export interface SyncNotificationsResponse {
  running: boolean;
  notifications: SyncNotification[];
  health?: {
    running?: boolean;
    interval_s?: number;
    last_success_at?: string | null;
    last_error?: string | null;
    pending_count?: number;
  };
}

export const listSyncNotifications = (): Promise<SyncNotificationsResponse> =>
  request("GET", "/api/sync/notifications");

export interface SnoozeResult {
  snoozed: boolean;
  until: string;
}

// 5.D.3.A: dismiss is now a 24h snooze, not a permanent clear.
// Conflicts re-surface after the snooze window. To permanently
// silence a conflict use `acceptCurrentAsSynced` instead.
export const dismissSyncNotification = (
  noteId: string,
  hours = 24,
): Promise<SnoozeResult> =>
  request(
    "POST",
    `/api/sync/notifications/${encodeURIComponent(noteId)}/dismiss?hours=${hours}`,
  );

export interface AcceptCurrentResult {
  ok: boolean;
  new_revision: string;
}

export const acceptCurrentAsSynced = (
  noteId: string,
): Promise<AcceptCurrentResult> =>
  request(
    "POST",
    `/api/sync/conflicts/${encodeURIComponent(noteId)}/accept-current`,
  );

export type BulkResolveStrategy =
  | "mine"
  | "remote"
  | "both"
  | "accept-current"
  | "snooze";

export interface BulkResolveResult {
  ok: boolean;
  succeeded: number;
  failed: number;
  results: Array<{ note_id: string; ok: boolean; detail?: string }>;
}

export const bulkResolveSyncConflicts = (
  noteIds: string[],
  strategy: BulkResolveStrategy,
  snoozeHours = 24,
): Promise<BulkResolveResult> =>
  request("POST", `/api/sync/conflicts/bulk-resolve`, {
    note_ids: noteIds,
    strategy,
    snooze_hours: snoozeHours,
  });

export interface SyncConflictPayload {
  conflict: boolean;
  note_id: string;
  drive_file_id: string;
  drive_file_name: string;
  expected_revision: string | null;
  current_revision: string | null;
  local_text: string;
  remote_text: string;
}

export const getSyncConflict = (noteId: string): Promise<SyncConflictPayload> =>
  request("GET", `/api/sync/conflicts/${encodeURIComponent(noteId)}`);

export type ConflictStrategy = "mine" | "remote" | "both";

export interface ConflictResolveResult {
  ok: boolean;
  action: ConflictStrategy;
  new_revision?: string;
  conflict_copy_path?: string;
}

export const resolveSyncConflict = (
  noteId: string,
  strategy: ConflictStrategy,
): Promise<ConflictResolveResult> =>
  request(
    "POST",
    `/api/sync/conflicts/${encodeURIComponent(noteId)}/resolve`,
    { strategy },
  );

// ---------- search (Phase 1 D slice 2) ----------

export const searchVault = (
  q: string,
  topK: number = 30,
): Promise<SearchPayload> => {
  const params = new URLSearchParams({ q, top_k: String(topK) });
  return request("GET", `/api/search?${params.toString()}`);
};

// ---------- templates (Phase 1 B slice 8) ----------

export type TemplateSummary = { id: string; title: string };

export const listTemplates = (): Promise<TemplateSummary[]> =>
  request("GET", "/api/templates");

// ---------- trash ----------

export const listTrash = (): Promise<TrashListResponse> =>
  request("GET", "/api/trash");

export const restoreTrashed = (name: string): Promise<NoteFull> =>
  request("POST", `/api/trash/${encodeURIComponent(name)}/restore`);

export const restoreAllTrashed = (): Promise<{
  restored_count: number;
  skipped: string[];
}> => request("POST", "/api/trash/restore-all");

export const purgeTrashed = (name: string): Promise<{ name: string }> =>
  request("DELETE", `/api/trash/${encodeURIComponent(name)}`);

export const emptyTrash = (): Promise<{ purged_count: number }> =>
  request("DELETE", "/api/trash");

// ---------- attachments (Phase 1 B slice 4) ----------

/**
 * Upload an image to the vault's `_attachments/` folder. Returns the
 * vault-relative path (e.g. `_attachments/01HXxxxx.png`) that the editor
 * inserts into the note as `![](path)`. Backend serves the file at
 * `/files/<path>` for the preview pane.
 */
export async function uploadAttachment(
  file: File | Blob,
  filename: string,
): Promise<{ path: string; bytes: number }> {
  const form = new FormData();
  form.append("file", file, filename);
  const r = await fetch("/api/attachments", { method: "POST", body: form });
  if (!r.ok) {
    let detail = r.statusText;
    try {
      const j = (await r.json()) as { detail?: string };
      if (j.detail) detail = j.detail;
    } catch {
      // not json
    }
    throw { status: r.status, detail };
  }
  return (await r.json()) as { path: string; bytes: number };
}
