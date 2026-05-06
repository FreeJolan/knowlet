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
}

export interface NoteFull extends NoteSummary {
  body: string;
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
