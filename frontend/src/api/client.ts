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

// Task #108 — auto-repair the warning-chip's "尝试自动修复" button.
// Backend backs up the corrupted file to .knowlet/backups/ before
// rewriting it (ADR-0018), so this is reversible.
export const repairFrontmatter = (id: string): Promise<NoteFull> =>
  request(
    "POST",
    `/api/notes/${encodeURIComponent(id)}/repair-frontmatter`,
  );

// ---------- preflight + conflicts inbox (#107a) ----------

export interface PreflightConflict {
  note_id: string;
  note_title: string | null;
  drive_file_id: string | null;
  last_synced_at: string | null;
  last_known_revision: string | null;
  current_drive_revision: string | null;
  remote_modified_at: string | null;
  remote_modified_by: string | null;
}

export interface PreflightOffline {
  note_id: string;
  note_title: string | null;
  detail: string | null;
}

export interface PreflightReport {
  ran_at: number | null;
  scanned: number;
  conflicts: PreflightConflict[];
  offline: PreflightOffline[];
  auto_pulled_ids: string[];
  synced_count: number;
  dirty_count: number;
  unauthenticated: boolean;
}

export const runPreflight = (): Promise<PreflightReport> =>
  request("POST", "/api/sync/preflight");

export const getConflicts = (): Promise<PreflightReport> =>
  request("GET", "/api/sync/conflicts");

// ---------- sync mode (#107b) ----------

export type SyncMode = "auto" | "strict" | "lax";

export interface SyncModeResponse {
  mode: SyncMode;
  /** What the UI should react to. Differs from ``mode`` when Auto
   *  auto-promotes to Strict via cross-device heartbeat detection
   *  (#111). Settings UI shows ``device_count`` so the user knows
   *  why. */
  effective_mode: SyncMode;
  /** Number of distinct knowlet installations seen on this vault's
   *  Drive appData within the heartbeat TTL (30 days). 0 when no
   *  preflight has run yet OR no Drive auth. */
  device_count: number;
}

export const getSyncMode = (): Promise<SyncModeResponse> =>
  request("GET", "/api/sync/mode");

export const setSyncMode = (mode: SyncMode): Promise<SyncModeResponse> =>
  request("PUT", "/api/sync/mode", { mode });

// ---------- first-push (#113) ----------

export interface UnpushedStatus {
  count: number;
  authenticated: boolean;
}

export const getUnpushedStatus = (): Promise<UnpushedStatus> =>
  request("GET", "/api/sync/unpushed-status");

export const pushAllUnpushed = (): Promise<{ queued: number }> =>
  request("POST", "/api/sync/push-all-unpushed");

// ---------- Drive auth (#116) ----------

export interface SyncAuthStatus {
  connected: boolean;
  user_email: string | null;
  user_display_name: string | null;
  connecting: boolean;
  last_error: string | null;
}

export const getAuthStatus = (): Promise<SyncAuthStatus> =>
  request("GET", "/api/sync/auth-status");

export const startConnect = (): Promise<{ started: boolean; reason?: string }> =>
  request("POST", "/api/sync/connect");

export const disconnect = (): Promise<{ removed_token_file: boolean }> =>
  request("POST", "/api/sync/disconnect");

export const cancelConnect = (): Promise<{ cancelled: boolean }> =>
  request("POST", "/api/sync/cancel-connect");

// ---------- push failures (#122) ----------

export interface PushError {
  note_id: string;
  note_title: string | null;
  count: number;
  last_error: string | null;
  last_attempt_at: string | null;
}

export const getPushErrors = (): Promise<{ errors: PushError[] }> =>
  request("GET", "/api/sync/push-errors");

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

export interface ProposedEdit {
  note_id: string;
  old_body: string;
  new_body: string;
  changed: boolean;
  reason: string;
}

// Phase 3 Stage 4 P3 — ask the AI for a minimal revision of a note.
// Returns old + new body for the diff UI; never writes. The user
// accepts the diff (P4), then the existing `updateNote` PUT does the
// atomic write + backup (ADR-0018).
export const proposeNoteEdit = (
  noteId: string,
  instruction: string,
): Promise<ProposedEdit> =>
  request(
    "POST",
    `/api/chat/note/${encodeURIComponent(noteId)}/propose-edit`,
    { instruction },
  );

export interface CheckNoteFinding {
  severity: "high" | "medium" | "low";
  paragraph: number | null;
  quote: string;
  finding: string;
  why: string;
  suggestion: string;
  fix_instruction: string;
  confidence: number;
}

export interface CheckNoteReport {
  note_id: string;
  summary: string;
  findings: CheckNoteFinding[];
}

export const checkNote = (
  noteId: string,
  payload: { standard_answer?: string; instruction?: string },
): Promise<CheckNoteReport> =>
  request("POST", `/api/chat/note/${encodeURIComponent(noteId)}/check`, {
    standard_answer: payload.standard_answer ?? "",
    instruction: payload.instruction ?? "",
  });

export const proposeDraftInternalize = (
  draftId: string,
  instruction: string,
): Promise<ProposedEdit> =>
  request(
    "POST",
    `/api/chat/draft/${encodeURIComponent(draftId)}/propose-internalize`,
    { instruction },
  );

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

// ---------- sync (Slice S1, ADR-0027 redesign) ----------

export type NoteSyncState =
  | "unauthenticated"
  | "offline"
  | "synced"
  | "dirty"
  | "conflict";

export interface NoteSyncStatus {
  state: NoteSyncState;
  last_synced_at: string | null;
  drive_file_id: string | null;
  last_known_revision: string | null;
  current_drive_revision: string | null;
  detail: string | null;
}

export const getNoteSyncStatus = (
  noteId: string,
): Promise<NoteSyncStatus> =>
  request("GET", `/api/sync/note-status/${encodeURIComponent(noteId)}`);

// ---------- merge editor (Slice S5) ----------

export interface ConflictBundle {
  note_id: string;
  drive_file_id: string;
  local_text: string;
  remote_text: string;
  current_drive_revision: string | null;
  last_known_revision: string | null;
  /** ISO-UTC mtime of the local file. */
  local_modified_at: string | null;
  /** Drive's modifiedTime (ISO). */
  remote_modified_at: string | null;
  /** Drive's lastModifyingUser displayName / email. */
  remote_modified_by: string | null;
}

export const getConflictBundle = (noteId: string): Promise<ConflictBundle> =>
  request("GET", `/api/sync/conflict-bundle/${encodeURIComponent(noteId)}`);

export interface ResolveMergeResponse {
  drive_file_id: string;
  new_revision: string | null;
}

export const resolveMerge = (
  noteId: string,
  mergedText: string,
): Promise<ResolveMergeResponse> =>
  request("POST", `/api/sync/resolve-merge/${encodeURIComponent(noteId)}`, {
    merged_text: mergedText,
  });

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

// ---------- favorites (Phase 2 D B1) ----------

export interface FavoriteSummary {
  id: string;
  title: string | null;
}

export const listFavorites = (): Promise<{ favorites: FavoriteSummary[] }> =>
  request("GET", "/api/favorites");

export const addFavorite = (
  noteId: string,
): Promise<{ favorites: FavoriteSummary[] }> =>
  request("POST", `/api/favorites/${encodeURIComponent(noteId)}`);

export const removeFavorite = (
  noteId: string,
): Promise<{ favorites: FavoriteSummary[] }> =>
  request("DELETE", `/api/favorites/${encodeURIComponent(noteId)}`);

// ---------- vault portability (Phase 2 E) ----------

export interface ImportReportPayload {
  mode: "restore" | "merge";
  target_path: string;
  notes_created: number;
  notes_skipped: number;
  notes_renamed: number;
  attachments_copied: number;
  dry_run: boolean;
  items: { source: string; action: string; final: string | null }[];
  manifest: {
    knowlet_version: string;
    exported_at: string;
    note_count: number;
    attachment_count: number;
  } | null;
}

/** URL only — caller opens this in a new tab or triggers an
 *  ``<a download>`` so the browser streams the zip. We don't use
 *  fetch + Blob because that needlessly buffers a large file in JS
 *  memory before re-emitting it as a download. */
export const exportVaultUrl = (): string => "/api/vault/export";

async function postFile<T>(path: string, file: File): Promise<T> {
  const form = new FormData();
  form.append("file", file);
  const r = await fetch(path, { method: "POST", body: form });
  if (!r.ok) {
    const detail = await r.text().catch(() => "");
    throw new Error(`${r.status} ${r.statusText}${detail ? ` — ${detail}` : ""}`);
  }
  return (await r.json()) as T;
}

export const previewImport = (file: File): Promise<ImportReportPayload> =>
  postFile("/api/vault/import-preview", file);

export const commitImport = (file: File): Promise<ImportReportPayload> =>
  postFile("/api/vault/import", file);

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

// ---------- LLM config (Phase 3 P3.0) ----------

export interface LLMConfigSummary {
  base_url: string;
  model: string;
  has_api_key: boolean;
  max_tokens: number;
}

export interface LLMConfigUpdate {
  base_url?: string;
  model?: string;
  /** Empty string = keep existing key; omit = unchanged; non-empty = overwrite. */
  api_key?: string;
  max_tokens?: number;
}

export interface LLMTestResult {
  ok: boolean;
  latency_ms: number;
  preview?: string;
  model?: string;
  error?: string;
  capabilities?: CapabilityProfile;
}

export interface CapabilityCheck {
  name: string;
  ok: boolean;
  detail: string;
  latency_ms: number;
  error?: string | null;
}

export interface CapabilityProfile {
  model: string;
  checks: CapabilityCheck[];
  supported: Record<string, boolean>;
}

export const getLLMConfig = (): Promise<LLMConfigSummary> =>
  request("GET", "/api/llm/config");

export const updateLLMConfig = (
  payload: LLMConfigUpdate,
): Promise<LLMConfigSummary> => request("PUT", "/api/llm/config", payload);

export interface LLMTestRequest {
  base_url?: string;
  api_key?: string;
  model?: string;
}

/** Test LLM connectivity. Pass draft credentials (what the user is
 *  currently typing in Settings) so the test verifies the current
 *  form values — not the still-saved old ones. Omit / empty fields
 *  fall back to the saved config. */
export const testLLM = (draft?: LLMTestRequest): Promise<LLMTestResult> =>
  request("POST", "/api/llm/test", draft ?? {});

export interface ProviderModelList {
  models: { id: string }[];
  error?: string;
}

export interface ProviderModelsRequest {
  base_url?: string;
  api_key?: string;
}

/** Live model list from the user's configured LLM provider's
 *  ``/v1/models`` endpoint. NOT a knowlet recommendation — passthrough.
 *
 *  Pass draft credentials (from the Settings form before user
 *  clicks Save) to preview models without committing. Omit / empty
 *  falls back to saved config. Empty + error message when provider
 *  doesn't support it or auth fails. */
export const getProviderModels = (
  draft?: ProviderModelsRequest,
): Promise<ProviderModelList> =>
  request("POST", "/api/llm/provider-models", draft ?? {});

// ---------- audit log (Phase 3 Stage 1 Step 1.6) ----------

export interface AICallEvent {
  id: string;
  ts: string;
  kind: string;
  entity_type: string;
  entity_id: string;
  actor: string;
  payload: {
    role?: string;
    model?: string;
    prompt_chars?: number;
    response_chars?: number;
    latency_ms?: number;
    tool_calls?: number;
    stream?: boolean;
    input_preview?: string;
    output_preview?: string;
    error?: string;
  };
}

export interface AICallEventsResponse {
  events: AICallEvent[];
  total: number;
}

/** Fetch recent ``ai.call`` audit events for the Settings → Advanced
 *  power-user trace viewer. Backed by the generic ``/api/events``
 *  endpoint filtered to ``kind=ai.call``. */
export const listAICallEvents = (
  limit = 50,
): Promise<AICallEventsResponse> =>
  request("GET", `/api/events?kind=ai.call&limit=${limit}`);

// ---------- Note kind (Phase 3 Stage 2 — ADR-0029 §4.5) ----------

/** Set a note's kind. ADR-0029 §4.5 asymmetric semantics:
 *  - reference → knowledge: instant, no ``confirm`` needed
 *  - knowledge → reference: requires ``confirm: true``; otherwise
 *    the backend returns 409 with detail.code = "demote_requires_confirm".
 *  - Same-kind POST is a 200 no-op, useful for refresh.
 */
export const setNoteKind = (
  noteId: string,
  payload: { kind: "knowledge" | "reference"; confirm?: boolean },
): Promise<NoteFull> =>
  request("POST", `/api/notes/${noteId}/kind`, payload);

// ---------- Capture flow (Phase 3 Stage 3 — ADR-0009 amendment) ----

export interface CapturePayload {
  title: string;
  body: string;
  source?: string | null;
  hostname?: string | null;
  /** True iff the page extracted but the summarize LLM call raised.
   *  Frontend should render "摘要失败" / "summary failed" hint. */
  summary_failed?: boolean;
  /** When summary_failed=true, the underlying LLM error message.
   *  Surfacing root cause lets user diagnose (e.g. "auth expired"
   *  / "rate limited") instead of guessing. */
  summary_error?: string | null;
}

export interface CaptureDecisionResponse {
  decision: "knowledge" | "reference" | "defer";
  note_id?: string | null;
  note_path?: string | null;
  draft_id?: string | null;
  draft_path?: string | null;
}

/** POST a URL → backend fetches + summarizes → returns a capsule. */
export const captureFromUrl = (url: string): Promise<CapturePayload> =>
  request("POST", "/api/capture/url", { url });

/** POST a multipart file → returns a capsule. Markdown / text only;
 *  PDF returns 415 (deferred per Stage 3 scope). */
export const captureFromFile = async (
  file: File,
): Promise<CapturePayload> => {
  const fd = new FormData();
  fd.append("file", file);
  const r = await fetch("/api/capture/file", { method: "POST", body: fd });
  if (!r.ok) {
    let detail = r.statusText;
    try {
      const data = (await r.json()) as { detail?: string };
      if (data.detail) detail = data.detail;
    } catch {
      /* not JSON */
    }
    const err: ApiError = { status: r.status, detail };
    throw err;
  }
  return (await r.json()) as CapturePayload;
};

/** User's three-way decision on a capsule. Knowledge / reference
 *  write a Note directly; defer writes a Draft. */
export const captureDecide = (payload: {
  capsule: CapturePayload;
  decision: "knowledge" | "reference" | "defer";
  defer_kind?: "knowledge" | "reference";
}): Promise<CaptureDecisionResponse> =>
  request("POST", "/api/capture/decide", payload);

// ---------- Drafts list (Phase 3 Stage 3) ----------------

export interface DraftSummary {
  id: string;
  title: string;
  body?: string;
  source?: string | null;
  tags: string[];
  kind: "knowledge" | "reference";
  task_id?: string | null;
  folder?: string | null;
  created_at: string;
  updated_at: string;
  /** computed by backend: days elapsed since created_at */
  age_days?: number;
  is_stale?: boolean;
  is_warn_age?: boolean;
  pending_diff_base?: string | null;
  pending_diff_body?: string | null;
}

export const listDrafts = (): Promise<DraftSummary[]> =>
  request("GET", "/api/drafts");

export const getDraft = (id: string): Promise<DraftSummary> =>
  request("GET", `/api/drafts/${encodeURIComponent(id)}`);

export type DigestPeriod = "today" | "week" | "all";

export const listDigestDrafts = (
  period: DigestPeriod = "today",
): Promise<DraftSummary[]> =>
  request("GET", `/api/digest/drafts?period=${encodeURIComponent(period)}`);

export interface DigestSourceSummary {
  id: string;
  name: string;
  kind: "rss" | "prompt";
  enabled: boolean;
  url?: string | null;
  prompt?: string | null;
  created_at: string;
  updated_at: string;
  last_pull_at?: string | null;
  last_success_at?: string | null;
  last_error?: string | null;
  pull_status?: "idle" | "ok" | "error" | "paused";
}

export interface DigestSourcePayload {
  name: string;
  kind: "rss" | "prompt";
  enabled?: boolean;
  url?: string | null;
  prompt?: string | null;
}

export const listDigestSources = (): Promise<DigestSourceSummary[]> =>
  request("GET", "/api/digest/sources");

export const createDigestSource = (
  payload: DigestSourcePayload,
): Promise<DigestSourceSummary> => request("POST", "/api/digest/sources", payload);

export const updateDigestSource = (
  id: string,
  payload: DigestSourcePayload,
): Promise<DigestSourceSummary> =>
  request("PUT", `/api/digest/sources/${encodeURIComponent(id)}`, payload);

export const deleteDigestSource = (id: string): Promise<{ ok: boolean }> =>
  request("DELETE", `/api/digest/sources/${encodeURIComponent(id)}`);

export interface RawInfoSummary {
  id: string;
  source_id: string;
  source_name: string;
  source_kind: "rss" | "prompt";
  title: string;
  url: string;
  published_at?: string | null;
  fetched_at: string;
  summary: string;
  key_points: string[];
  why_it_matters: string;
  suggested_tags: string[];
  confidence: "high" | "medium" | "low";
  content_excerpt: string;
  status:
    | "unprocessed"
    | "viewed"
    | "discussed"
    | "drafted"
    | "discarded"
    | "included";
  note_draft_id?: string | null;
  note_id?: string | null;
}

export interface DigestPullReport {
  started_at: string;
  finished_at: string;
  source_ids: string[];
  fetched: number;
  new_items: number;
  created: number;
  skipped: number;
  paused: boolean;
  errors: string[];
}

export interface DigestStatus {
  status: "idle" | "running" | "ok" | "error" | "paused";
  pending_count: number;
  last_report?: Record<string, unknown> | null;
  last_error?: string | null;
  sources: DigestSourceSummary[];
}

export const listRawInfoItems = (): Promise<RawInfoSummary[]> =>
  request("GET", "/api/digest/items");

export interface RawInfoDraftResult {
  raw_info: RawInfoSummary;
  draft: DraftSummary;
  rationale: string;
}

export const createRawInfoDraft = (
  id: string,
  payload: { history?: Array<{ role: string; content: string }> },
): Promise<RawInfoDraftResult> =>
  request("POST", `/api/digest/items/${encodeURIComponent(id)}/draft`, payload);

export interface DraftDiffProposal {
  kind: "draft_edit_proposal";
  draft_id: string;
  title: string;
  old_body: string;
  new_body: string;
  changed: boolean;
  reason?: string;
  summary?: string;
  draft: DraftSummary;
}

export const proposeDraftDiff = (
  id: string,
  payload: { instruction?: string },
): Promise<DraftDiffProposal> =>
  request("POST", `/api/drafts/${encodeURIComponent(id)}/diff`, {
    instruction: payload.instruction ?? "",
  });

export const acceptDraftDiff = (
  id: string,
  payload: { final_body?: string },
): Promise<{ draft: DraftSummary; accepted: boolean }> =>
  request("POST", `/api/drafts/${encodeURIComponent(id)}/diff/accept`, {
    final_body: payload.final_body ?? null,
  });

export const rejectDraftDiff = (
  id: string,
): Promise<{ draft: DraftSummary; rejected: boolean }> =>
  request("POST", `/api/drafts/${encodeURIComponent(id)}/diff/reject`);

export const commitNoteDraft = (
  id: string,
  payload?: { folder?: string },
): Promise<{
  note_id: string;
  path: string;
  title: string;
  raw_info_id?: string | null;
}> => request("POST", `/api/drafts/${encodeURIComponent(id)}/commit`, payload);

export const getDigestStatus = (): Promise<DigestStatus> =>
  request("GET", "/api/digest/status");

export const pullDigestSources = (): Promise<DigestPullReport> =>
  request("POST", "/api/digest/pull");

export const pullDigestSource = (id: string): Promise<DigestPullReport> =>
  request("POST", `/api/digest/sources/${encodeURIComponent(id)}/pull`);

export const approveDraft = (id: string): Promise<{ note_id: string }> =>
  request("POST", `/api/drafts/${id}/approve`);

export const rejectDraft = (id: string): Promise<{ archived: boolean }> =>
  request("POST", `/api/drafts/${id}/reject`);

/** PUT /api/drafts/{id} — pre-approve edit. Per ADR-0029 §4 原则 1,
 *  the user is the last-byte channel: AI's first pass isn't always
 *  the final text. All fields optional. */
export const updateDraft = (
  id: string,
  payload: {
    title?: string;
    body?: string;
    tags?: string[];
    kind?: "knowledge" | "reference";
    folder?: string;
  },
): Promise<DraftSummary> =>
  request("PUT", `/api/drafts/${id}`, payload);

// ---------- Mining task status (Phase 3 Stage 3 §3.8) -------------

export interface MiningTaskSummary {
  id: string;
  name: string;
  enabled: boolean;
  schedule: Record<string, string>;
  sources: Array<Record<string, string>>;
  updated_at: string;
  status: "running" | "paused-by-user" | "paused-by-backlog";
  max_pending_drafts: number | null;
  pending_drafts: number;
}

export const listMiningTasks = (): Promise<MiningTaskSummary[]> =>
  request("GET", "/api/mining/tasks");
