/**
 * Wire types — mirror Pydantic models in `knowlet/web/server.py`.
 *
 * These are kept hand-written (not codegen) because the surface is small
 * (~10 endpoints used by Phase 1 A) and a build step / OpenAPI dump would
 * be more friction than the duplication. If the API surface grows past
 * 30 endpoints, revisit and pull in `openapi-typescript`.
 */

export interface NoteSummary {
  id: string;
  title: string;
  path: string;
  folder: string;
  tags: string[];
  created_at: string;
  updated_at: string;
  /** Phase 1 D / D3 Properties UI — alternate names for this note.
   *  Default `[]` for back-compat with summary builders that don't
   *  carry the column. */
  aliases?: string[];
  /** URL the note was captured from (e.g. quick-capture from a web
   *  page). Read-only display in Properties UI. */
  source?: string | null;
}

export interface NoteFull extends NoteSummary {
  body: string;
  /** Task #108 — surfaces the lenient-read flag so NoteView can
   *  render a warning chip + auto-repair affordance. Default
   *  "valid" matches the backend so old payloads (pre-task-#108
   *  servers) parse without breaking. */
  frontmatter_status?: "valid" | "auto_filled" | "corrupted";
  frontmatter_corruption?: string | null;
}

// ---------- Quick actions (Phase 2 D Slice 2c, ADR-0025) ----------

export interface CreateNoteParams {
  kind: "create_note";
  folder: string;
  title_template: string;
  content_template_id?: string | null;
}

/** Discriminated union — when more `kind` values ship, append. */
export type QuickActionParams = CreateNoteParams;

export interface QuickAction {
  schema_version: number;
  id: string;
  name: string;
  description?: string | null;
  shortcut?: string | null;
  params: QuickActionParams;
}

export interface QuickActionPayload {
  name: string;
  description?: string | null;
  shortcut?: string | null;
  params: QuickActionParams;
}

export interface TreeNote {
  id: string;
  title: string;
  updated_at: string;
  tags: string[];
}

export interface TreeFolder {
  name: string;
  path: string;
  folders: TreeFolder[];
  notes: TreeNote[];
}

export interface TrashEntry {
  name: string;
  title: string;
  note_id: string;
  trashed_at: string;
  /** Folder the note lived in before it was trashed. Empty string =
   *  root. null = legacy entry without metadata (will restore to root). */
  original_folder?: string | null;
}

export interface TrashListResponse {
  entries: TrashEntry[];
}

export interface FolderResponse {
  path: string;
}

export interface ApiError {
  status: number;
  detail: string;
}

// ---------- backlinks (M7.0.4 backend, Phase 1 C frontend) ----------

export interface BacklinkRow {
  source_id: string;
  source_title: string;
  /** Wikilink target as written (case + spacing may differ from canonical title). */
  target: string;
  /** 1-based line number in the source note. */
  line: number;
  /** Trimmed sentence preview, max 240 chars; contains the literal `[[…]]` syntax. */
  sentence: string;
}

// ---------- tags (Phase 1 C slice 2) ----------

export interface TagSummary {
  tag: string;
  count: number;
}

export interface TagWithNotes {
  tag: string;
  count: number;
  notes: NoteSummary[];
}

// ---------- graph (Phase 1 C slice 3) ----------

export interface GraphNodeRow {
  id: string;
  title: string;
  folder: string;
  in_degree: number;
  out_degree: number;
}

export interface GraphEdgeRow {
  source: string;
  target: string;
}

export interface GraphPayload {
  nodes: GraphNodeRow[];
  edges: GraphEdgeRow[];
}

// ---------- search (Phase 1 D slice 2) ----------

export interface SearchHitRow {
  note_id: string;
  title: string;
  folder: string;
  /** Plain-text snippet around the match; client highlights by query. */
  snippet: string;
  /** RRF score from server; informational, not displayed. */
  score: number;
}

export interface SearchPayload {
  query: string;
  hits: SearchHitRow[];
}
