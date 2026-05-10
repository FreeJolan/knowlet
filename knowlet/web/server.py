"""FastAPI app for the knowlet web UI.

Per ADR-0008 (CLI parity discipline), every endpoint here is a thin shell over
backend functions in `knowlet/core/*` and `knowlet/chat/*`. Tests target both
the backend functions directly *and* this HTTP API; the UI itself only needs
smoke testing for rendering and event plumbing.

Single-user, single-vault, localhost-only. Auth is intentionally absent — the
server binds to 127.0.0.1 by default and trusts the caller. Multi-user would
need a real auth design that is out of scope for the MVP.
"""

from __future__ import annotations

import json
import threading
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Annotated, Any

from fastapi import Body, Depends, FastAPI, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from knowlet import __version__
from knowlet.chat.bootstrap import (
    ChatNotReadyError,
    ChatRuntime,
    bootstrap_chat,
)
from knowlet.chat.sediment import (
    Draft as SedimentDraft,
)
from knowlet.chat.sediment import (
    commit_draft,
    draft_from_conversation,
)
from knowlet.config import KnowletConfig, find_vault, load_config
from knowlet.core.backlinks import find_backlinks
from knowlet.core.card import Card, parse_due
from knowlet.core.drafts import Draft
from knowlet.core.events import ErrorEvent, event_to_dict
from knowlet.core.fsrs_wrap import initial_state, schedule_next
from knowlet.core.graph import build_graph, read_body_via_note
from knowlet.core.i18n import SUPPORTED_LANGUAGES, all_keys, set_language
from knowlet.core.index import Index, IndexDimensionMismatchError
from knowlet.core.inline_tags import merge_with_inline_tags
from knowlet.core.llm import ToolCall
from knowlet.core.mining.runner import reset_task_state, run_task
from knowlet.core.mining.scheduler import MiningScheduler
from knowlet.core.mining.task import MiningTask, Schedule, SourceSpec
from knowlet.core.note import Note
from knowlet.core.quick_actions import (
    CreateNoteParams,
    QuickAction,
    QuickActionStore,
    new_action_id,
    render_title_placeholders,
)
from knowlet.core.quiz import (
    DEFAULT_N_QUESTIONS,
    QuizSession,
    aggregate_score,
    generate_quiz,
    grade_answer,
)
from knowlet.core.quiz_store import QuizStore
from knowlet.core.quote_refs import (
    MAX_REFERENCES,
    QuoteRef,
    format_references_block,
)
from knowlet.core.structure_signals import (
    DEFAULT_AGING_UNTOUCHED_DAYS,
    DEFAULT_NEAR_DUP_COSINE,
    DEFAULT_ORPHAN_UNTOUCHED_DAYS,
    compute_signals,
)
from knowlet.core.url_capture import (
    ExtractionError,
    FetchError,
    capture_url,
)
from knowlet.core.user_profile import (
    UserProfile,
    read_profile,
    write_profile,
)
from knowlet.core.vault import Vault

# Phase 1 A onwards: the React build under `frontend/dist/` is the served
# UI. Path is resolved relative to the repo root (server.py → web/ → knowlet/
# → repo). `knowlet web` mounts it if present; in dev we usually run
# `bun/npm run dev` separately on :5173 instead and let Vite proxy /api/*.
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


# ----------------------------------------------------------------- request/response models


class RenameSessionRequest(BaseModel):
    title: str


# S0 (2026-05-10): sync resolve / bulk-resolve request models lived
# here. All sync UI endpoints torn out; redesign restarts at S1. New
# models will land alongside the new endpoints when each slice ships.


class QuoteRefPayload(BaseModel):
    """M7.1 / M7.2: one capsule. `source = "note"` (M7.1 default) →
    the backend fetches the Note body via note_id and runs the enclosing-
    section algorithm. `source = "url"` (M7.2) → quote_text is already
    the LLM-produced summary; source_url surfaces the page reference."""

    note_id: str
    note_title: str
    quote_text: str
    paragraph_anchor: str = ""
    source: str = "note"  # "note" | "url"
    source_url: str = ""


class ChatTurnRequest(BaseModel):
    text: str = Field(..., description="user message")
    references: list[QuoteRefPayload] = Field(
        default_factory=list,
        description="M7.1 selection capsules — soft cap 5; over-cap is silently truncated.",
    )


class ToolTrace(BaseModel):
    name: str
    arguments: dict[str, Any]
    result: dict[str, Any]


class ChatTurnResponse(BaseModel):
    reply: str
    tool_calls: list[ToolTrace]


class DraftPayload(BaseModel):
    title: str
    tags: list[str]
    body: str
    # Phase 1 D / D3 Properties UI: alternate names for this note.
    # Tri-state semantics:
    #   - `None` (or absent) → leave existing aliases untouched. This
    #     keeps pre-D3 API clients from accidentally wiping the field
    #     just by issuing a normal title/body update.
    #   - `[]` → explicit "clear all aliases".
    #   - `[..]` → replace with the given list.
    # The knowlet web UI always sends an explicit list (current value
    # echoed back, or the new chip-strip value), so user-driven
    # changes are unambiguous.
    aliases: list[str] | None = None


class CommitDraftRequest(DraftPayload):
    pass


class CommitDraftResponse(BaseModel):
    note_id: str
    path: str


class NoteSummary(BaseModel):
    id: str
    title: str
    path: str
    folder: str = ""  # M7.0.2: relative dir under notes/, empty = top-level
    tags: list[str]
    created_at: str
    updated_at: str
    # Phase 1 D / D3 Properties UI fields. Default-empty / null keeps
    # NoteSummary back-compat with index-row builders that don't carry
    # these columns yet — NoteFull constructors fill them explicitly.
    aliases: list[str] = []
    source: str | None = None


class NoteFull(NoteSummary):
    body: str


class BacklinkRow(BaseModel):
    """M7.0.4: one inbound `[[Title]]` reference for the right-rail panel."""

    source_id: str
    source_title: str
    target: str  # the wikilink target as written
    line: int
    sentence: str


class TagSummary(BaseModel):
    """Phase 1 C slice 2 — one tag with its note count for the tag browser."""

    tag: str
    count: int


class TagWithNotes(BaseModel):
    """Phase 1 C slice 2 polish D — one tag + the notes carrying it. Used
    by the file-tree-style Tag browser to render notes as children of
    tag nodes without N+1 round-trips."""

    tag: str
    count: int
    notes: list[NoteSummary]


class GraphNodeRow(BaseModel):
    """Phase 1 C slice 3 — one node in the user-authored bilink graph."""

    id: str
    title: str
    folder: str = ""
    in_degree: int = 0
    out_degree: int = 0


class GraphEdgeRow(BaseModel):
    """Phase 1 C slice 3 — one resolved `[[Title]]` edge in the graph."""

    source: str
    target: str


class GraphPayload(BaseModel):
    """Full graph snapshot. One pull, full vault. <5k notes per ADR-0021."""

    nodes: list[GraphNodeRow]
    edges: list[GraphEdgeRow]


class SearchHitRow(BaseModel):
    """Phase 1 D slice 2 — one result row in the global search panel."""

    note_id: str
    title: str
    folder: str = ""
    snippet: str
    score: float


class SearchPayload(BaseModel):
    """Search response wrapper. `query` echoed back for cache key /
    stale-result detection on the client side."""

    query: str
    hits: list[SearchHitRow]


# ---------------- Phase 1 A wire schemas (file ops) ----------------


class TreeNote(BaseModel):
    """A note leaf in the file-tree. We surface the minimum the sidebar
    needs to render + click-through; full body comes via /api/notes/{id}."""

    id: str
    title: str
    updated_at: str
    tags: list[str] = Field(default_factory=list)


class TreeFolder(BaseModel):
    """A folder node in the tree. `path` is forward-slash relative to
    notes_dir (empty string = root). `folders` and `notes` are siblings —
    UI sorts however it likes (we sort folders-first, alpha)."""

    name: str
    path: str
    folders: list[TreeFolder] = Field(default_factory=list)
    notes: list[TreeNote] = Field(default_factory=list)


class FolderCreateRequest(BaseModel):
    path: str = Field(..., description="forward-slash relative path under notes/")


class FolderRenameRequest(BaseModel):
    path: str
    new_name: str


class FolderMoveRequest(BaseModel):
    src: str
    dst_parent: str = ""


class FolderDeleteRequest(BaseModel):
    path: str


class FolderResponse(BaseModel):
    """Common-shape reply for mkdir / rename / move."""

    path: str  # final relative path under notes/


class NoteMoveRequest(BaseModel):
    target_folder: str = ""


class NewNoteRequest(BaseModel):
    """Phase 1 A: create an empty note with a title and optional folder.
    Distinct from POST /api/notes which is the sediment-commit shape;
    this one supports folder placement and accepts an empty body.

    Phase 1 B slice 8: optional `template_id` pre-fills the body from
    a template note in `notes/templates/` with `{{title}}` / `{{date}}`
    substituted.
    """

    title: str
    folder: str = ""
    tags: list[str] = Field(default_factory=list)
    template_id: str | None = None


class TemplateSummary(BaseModel):
    """Minimal shape the template-picker UI consumes."""

    id: str
    title: str


class QuickActionPayload(BaseModel):
    """Shape accepted by POST / PUT /api/quick-actions{,/<id>}.

    The server assigns `id` if missing on create and ignores any
    client-supplied id on update (path id wins). `params` is a
    nested object whose `kind` discriminator selects the variant.
    """

    name: str
    description: str | None = None
    shortcut: str | None = None
    # CreateNoteParams is a Pydantic model; allow it as a plain dict
    # at the boundary so the discriminator works through JSON.
    params: dict[str, Any]


class TrashEntry(BaseModel):
    name: str  # basename inside notes/.trash/
    title: str  # frontmatter title if parseable, else stem
    note_id: str  # ULID parsed from filename, "" if unparseable
    trashed_at: str  # mtime as ISO
    # Folder the note lived in before it was trashed. "" = root, None
    # = legacy trash entry without metadata (will restore to root).
    original_folder: str | None = None


class TrashListResponse(BaseModel):
    entries: list[TrashEntry]


class RestoreAllResponse(BaseModel):
    """Outcome of `POST /api/trash/restore-all`. Per-entry success isn't
    independent — a name collision on one entry shouldn't abort the
    rest — so we report counts + the names that we couldn't restore."""

    restored_count: int
    skipped: list[str]


class UrlCaptureRequest(BaseModel):
    url: str


class UrlCaptureResponse(BaseModel):
    """M7.2: result of fetching + summarizing a URL. summary may be empty
    if the LLM call failed but the page extracted — frontend surfaces a
    "(摘要失败)" capsule in that case so the user can still attach + ask."""

    url: str
    title: str
    hostname: str
    summary: str
    summary_failed: bool = False  # True iff fetch ok but summarize raised


class SimilarNoteRow(BaseModel):
    """M7.2: ADR-0013 §3 Layer A — top-K similar Notes for the sediment
    modal. No `score` field on the wire to discourage UIs from showing
    confidence numbers (the contract says no auto-actions, no implied
    judgment). Just title + path + a short preview."""

    id: str
    title: str
    path: str
    preview: str


# ---------------- M7.4 quiz wire schemas (ADR-0014) ----------------


class QuizStartRequest(BaseModel):
    """M7.4.3: scope can now be `notes` (the default — explicit ids) or
    `tag` (resolve all Notes with the tag to ids server-side). The
    cluster scope is wire-compatible (`scope_type="cluster" + cluster_id`)
    but blocked at the route layer until ADR-0013 Layer B (M8) lands."""

    note_ids: list[str] = []
    n: int = DEFAULT_N_QUESTIONS
    scope_type: str = "notes"  # "notes" | "tag" | "cluster"
    tag: str = ""
    cluster_id: str = ""


class NearDupPairPayload(BaseModel):
    a_id: str
    a_title: str
    b_id: str
    b_title: str
    cosine: float


class NoteClusterPayload(BaseModel):
    note_ids: list[str]
    note_titles: list[str]


class OrphanNotePayload(BaseModel):
    id: str
    title: str
    days_untouched: int


class AgingCandidatePayload(BaseModel):
    id: str
    title: str
    days_untouched: int


class StructureSignalsPayload(BaseModel):
    """M8.1 / ADR-0013 Layer B — read-only structure signals over the
    vault. Pure information per ADR-0013 §1: no scores rendered as
    judgment, no auto-action verbs in the wire shape. The M8.2
    knowledge-map sidebar will consume this; no UI yet."""

    near_duplicates: list[NearDupPairPayload]
    clusters: list[NoteClusterPayload]
    orphan_notes: list[OrphanNotePayload]
    aging_candidates: list[AgingCandidatePayload]


class QuizSummaryRow(BaseModel):
    """Light row for the past-quizzes list. Avoids shipping every
    question down the wire when all the user wants is "did I quiz on
    RAG last week?"."""

    id: str
    started_at: str
    finished_at: str
    scope_type: str
    scope_note_ids: list[str]
    scope_tag: str
    n_questions: int
    n_correct: int
    n_disagreement: int
    cards_created: int
    session_score: int


class QuizQuestionPayload(BaseModel):
    type: str
    question: str
    reference_answer: str
    source_note_ids: list[str] = []
    user_answer: str = ""
    ai_score: int | None = None
    ai_reason: str = ""
    ai_missing: list[str] = []
    user_disagrees: bool = False
    user_disagree_reason: str = ""
    card_id_after_reflux: str | None = None


class QuizSessionPayload(BaseModel):
    id: str
    started_at: str
    finished_at: str = ""
    model: str = ""
    scope_type: str = "notes"
    scope_note_ids: list[str] = []
    scope_tag: str = ""
    questions: list[QuizQuestionPayload] = []
    n_questions: int = 0
    n_correct: int = 0
    n_disagreement: int = 0
    cards_created: int = 0
    session_score: int = 0


class QuizAnswerRequest(BaseModel):
    question_index: int
    user_answer: str


class QuizDisagreeRequest(BaseModel):
    question_index: int
    disagree: bool = True
    reason: str = ""


class QuizRefluxRequest(BaseModel):
    """Convert one quiz question into a Card (M7.4.2 Cards reflux)."""

    question_index: int
    front: str = ""  # default = question text
    back: str = ""  # default = reference_answer (or user's edited version)
    tags: list[str] = []  # default = source-note tags ∪ {quiz}  # noqa: RUF003


class ProfilePayload(BaseModel):
    body: str
    name: str | None = None


class CardCreate(BaseModel):
    front: str
    back: str
    tags: list[str] = Field(default_factory=list)
    type: str = "basic"
    source_note_id: str | None = None


class CardReview(BaseModel):
    rating: int = Field(..., ge=1, le=4)


class CardSummary(BaseModel):
    id: str
    type: str
    front: str
    back: str
    tags: list[str]
    due: str
    state: int | None = None


class CardFull(CardSummary):
    source_note_id: str | None = None
    created_at: str
    updated_at: str
    fsrs_state: dict[str, Any]


class TaskCreate(BaseModel):
    name: str
    sources: list[dict[str, str]] = Field(default_factory=list)
    schedule: dict[str, str] = Field(default_factory=dict)
    prompt: str = ""
    enabled: bool = True
    body: str = ""
    output_language: str | None = None


class TaskSummary(BaseModel):
    id: str
    name: str
    enabled: bool
    schedule: dict[str, str]
    sources: list[dict[str, str]]
    updated_at: str


class TaskFull(TaskSummary):
    prompt: str
    body: str
    created_at: str
    output_language: str | None = None


class DraftSummary(BaseModel):
    id: str
    title: str
    tags: list[str]
    source: str | None = None
    task_id: str | None = None
    created_at: str
    updated_at: str


class DraftFull(DraftSummary):
    body: str


# ----------------------------------------------------------------- runtime singleton


class WebState:
    """Holds the shared ChatRuntime for the running server.

    Kept as a tiny app-state holder (not a global) so tests can construct one
    independently of an actual `uvicorn run`.

    Bootstrap is async by default (production path): the FastAPI lifespan
    kicks off `start_bootstrap_async` which runs reindex on a daemon thread,
    so uvicorn accepts connections immediately. Endpoints that need the
    runtime poll `bootstrap_status`. Tests don't enter lifespan as a context
    manager, so they keep using `runtime_or_init` which falls back to a
    synchronous bootstrap on first call.
    """

    def __init__(self, vault: Vault, config: KnowletConfig):
        self.vault = vault
        self.config = config
        self.runtime: ChatRuntime | None = None
        self.scheduler: MiningScheduler | None = None
        # Bootstrap state (production async path):
        #   "idle"   — never attempted (no api_key, or tests pre-init)
        #   "running"— lifespan started a thread; not done
        #   "ready"  — runtime + scheduler ready
        #   "error"  — bootstrap raised; bootstrap_error holds the exception
        self.bootstrap_status: str = "idle"
        self.bootstrap_error: Exception | None = None
        self._bootstrap_thread: threading.Thread | None = None

    def start_bootstrap_async(self) -> None:
        """Kick off bootstrap on a daemon thread. Called from lifespan.

        Idempotent: if a thread is already running or runtime is ready,
        does nothing.
        """
        if self.bootstrap_status in ("running", "ready"):
            return
        if not self.config.llm.api_key:
            # Per ADR-0012, AI is optional; an unconfigured vault is a legal
            # state. Static + Notes endpoints work; chat endpoints will 503.
            self.bootstrap_status = "idle"
            return

        self.bootstrap_status = "running"
        self.bootstrap_error = None

        def _run() -> None:
            try:
                runtime, _report = bootstrap_chat(self.vault, self.config)
                self.runtime = runtime
                scheduler = MiningScheduler(
                    self.vault,
                    runtime.llm,
                    default_output_language=self.config.general.language,
                )
                scheduler.start()
                self.scheduler = scheduler
                self.bootstrap_status = "ready"
            except Exception as exc:
                self.bootstrap_error = exc
                self.bootstrap_status = "error"

        self._bootstrap_thread = threading.Thread(
            target=_run, name="knowlet-bootstrap", daemon=True
        )
        self._bootstrap_thread.start()

    def runtime_or_init(self) -> ChatRuntime:
        """Return the ready runtime, or raise an HTTPException with the
        right status for the current bootstrap phase.

        - `ready` → return runtime
        - `running` → 503, "still indexing"
        - `error` → 500, with the original exception's message
        - `idle` → fall back to a synchronous bootstrap (test path / first
          call before lifespan got a chance to spawn the thread)
        """
        if self.bootstrap_status == "ready" and self.runtime is not None:
            return self.runtime
        if self.bootstrap_status == "running":
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="knowlet is still indexing the vault — try again shortly",
            )
        if self.bootstrap_status == "error" and self.bootstrap_error is not None:
            exc = self.bootstrap_error
            if isinstance(exc, ChatNotReadyError):
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=str(exc),
                )
            if isinstance(exc, IndexDimensionMismatchError):
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=str(exc),
                )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"bootstrap failed: {exc}",
            )

        # bootstrap_status == "idle" — fall back to synchronous bootstrap.
        # This is the test path (TestClient without `with`) and the
        # api-key-empty path.
        try:
            runtime, _report = bootstrap_chat(self.vault, self.config)
        except ChatNotReadyError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(exc),
            ) from exc
        except IndexDimensionMismatchError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(exc),
            ) from exc
        self.runtime = runtime
        self.bootstrap_status = "ready"
        return self.runtime

    def close(self) -> None:
        if self.scheduler is not None:
            self.scheduler.shutdown()
            self.scheduler = None
        if self.runtime is not None:
            self.runtime.close()
            self.runtime = None
        # Don't join the bootstrap thread on shutdown — it's a daemon, and
        # waiting for an in-flight reindex would hang the server.


def _runtime_dep(app: FastAPI) -> Callable[[], ChatRuntime]:
    """FastAPI dependency: hand back the ChatRuntime, initializing on demand."""

    def _dep() -> ChatRuntime:
        state: WebState = app.state.web_state
        return state.runtime_or_init()

    return _dep


# ----------------------------------------------------------------- file-tree helpers


def _iso(epoch: float) -> str:
    from datetime import UTC, datetime

    return datetime.fromtimestamp(epoch, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _rel_folder(vault: Vault, folder_path: Path) -> str:
    """Forward-slash path of `folder_path` relative to `notes/`. Empty
    string for the root."""
    try:
        rel = folder_path.relative_to(vault.notes_dir)
    except ValueError:
        return ""
    if not rel.parts:
        return ""
    return "/".join(rel.parts)


def _build_tree(vault: Vault, index: Index) -> TreeFolder:
    """Walk the index for note metadata, fold into a TreeFolder hierarchy.

    We use the index (not iter_note_paths) because it already has the
    title + tags; the tree is a hot path on every UI mount and a thousand-
    note vault would otherwise re-parse a thousand frontmatter blocks.
    """
    root = TreeFolder(name="", path="")
    # Pre-create folder nodes so empty folders show up.
    for folder_path in vault.iter_folders():
        rel = _rel_folder(vault, folder_path)
        _ensure_folder(root, rel)

    # Place every indexed note under its folder.
    for row in index.list_notes(limit=10_000, order="updated_at"):
        path_str = row.get("path") or ""
        if not path_str:
            continue
        path = Path(path_str)
        rel_path: Path
        try:
            rel_path = path.relative_to(vault.notes_dir)
        except ValueError:
            # Path stored relative — re-anchor under notes_dir.
            rel_path = Path(path.name)
        folder_rel = "/".join(rel_path.parts[:-1]) if len(rel_path.parts) > 1 else ""
        node = _ensure_folder(root, folder_rel)
        node.notes.append(
            TreeNote(
                id=row["id"],
                title=row.get("title") or "(无标题)",
                updated_at=row.get("updated_at") or "",
                tags=json.loads(row["tags"]) if isinstance(row.get("tags"), str) else [],
            )
        )
    _sort_tree(root)
    return root


def _ensure_folder(root: TreeFolder, rel: str) -> TreeFolder:
    """Walk into `root`, creating TreeFolder children as needed for each
    segment of `rel`. Returns the leaf folder node."""
    if not rel:
        return root
    cur = root
    accum: list[str] = []
    for part in rel.split("/"):
        accum.append(part)
        existing = next((f for f in cur.folders if f.name == part), None)
        if existing is None:
            existing = TreeFolder(name=part, path="/".join(accum))
            cur.folders.append(existing)
        cur = existing
    return cur


def _sort_tree(node: TreeFolder) -> None:
    node.folders.sort(key=lambda f: f.name.lower())
    node.notes.sort(key=lambda n: n.title.lower())
    for child in node.folders:
        _sort_tree(child)


def _resync_paths_under(runtime: ChatRuntime, folder_path: Path) -> None:
    """After a folder rename/move, every note inside has a new on-disk
    path. Walk the new location and update the index `path` column for
    each by ULID (parsed from the filename — `<id>.md`)."""
    if not folder_path.is_dir():
        return
    for md in folder_path.rglob("*.md"):
        if md.is_file() and not any(p.startswith(".") for p in md.relative_to(folder_path).parts):
            note_id = md.stem
            runtime.index.update_note_path(note_id, str(md))


# ----------------------------------------------------------------- factory


def create_app(vault: Vault, config: KnowletConfig) -> FastAPI:
    """Build a FastAPI app bound to a specific vault and config.

    Used both by `knowlet web` (production) and by tests (with a tmp_path
    vault, dummy embedding, stub LLM).
    """
    state = WebState(vault=vault, config=config)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Activate the configured UI language for any backend-rendered strings.
        set_language(config.general.language)
        # Bootstrap (which calls reindex_vault) runs on a background thread
        # so uvicorn accepts connections immediately. Endpoints that need
        # the runtime poll `bootstrap_status` and 503 while indexing. The
        # frontend reads this via `/api/health.ready` and shows a banner.
        # Without this, a vault with thousands of notes would block uvicorn
        # for minutes on first launch and look like the server crashed.
        state.start_bootstrap_async()
        # S0 (2026-05-10): the SyncPoller used to start here so its
        # in-memory pending list could feed /api/sync/notifications.
        # All sync UI endpoints have been torn out; the poller has
        # no consumer right now. S2 will re-add it (state-reconciliation
        # path) when the per-note status indicator needs the data.
        try:
            yield
        finally:
            state.close()

    app = FastAPI(title="knowlet", version=__version__, lifespan=lifespan)
    app.state.web_state = state
    runtime_dep = _runtime_dep(app)

    # ---------------- health ----------------

    # ---------------- system (M6.5) ----------------

    @app.post("/api/system/reindex")
    def system_reindex(
        rebuild: bool = False,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> dict[str, Any]:
        """Rebuild the index from on-disk Notes. Mirrors `knowlet reindex`
        (ADR-0008). The Cmd+K palette `重建索引` command calls this."""
        from knowlet.core.embedding import make_backend
        from knowlet.core.index import Index, reindex_vault

        v = runtime.vault
        cfg = runtime.config
        if rebuild and v.db_path.exists():
            v.db_path.unlink()
        backend = make_backend(cfg.embedding.backend, cfg.embedding.model, cfg.embedding.dim)
        if backend.dim != cfg.embedding.dim:
            cfg.embedding.dim = backend.dim
            from knowlet.config import save_config as _save_cfg

            _save_cfg(v.root, cfg)
        changed, deleted, unchanged = reindex_vault(
            v.root,
            v.db_path,
            backend,
            chunk_size=cfg.retrieval.chunk_size,
            chunk_overlap=cfg.retrieval.chunk_overlap,
            note_paths=list(v.iter_note_paths()),
        )
        # The reindex closes/reopens the DB; reload the runtime's index too.
        runtime.index = Index(v.db_path, backend)
        runtime.index.connect()
        runtime.ctx.index = runtime.index
        return {"changed": changed, "deleted": deleted, "unchanged": unchanged}

    @app.post("/api/system/doctor")
    def system_doctor(
        skip_llm: bool = False,
        skip_embedding: bool = False,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> dict[str, Any]:
        """Run the same health checks as `knowlet doctor`. Returns the raw
        (status, name, detail) tuples; the palette renders them as a toast
        summary or links into a richer view."""
        from knowlet.core.doctor import run_doctor_checks

        results = run_doctor_checks(
            runtime.vault,
            runtime.config,
            skip_llm=skip_llm,
            skip_embedding=skip_embedding,
        )
        return {
            "results": [{"status": r[0], "name": r[1], "detail": r[2]} for r in results],
            "failures": sum(1 for r in results if r[0] == "fail"),
            "warnings": sum(1 for r in results if r[0] == "warn"),
        }

    # ----------------------------------------------------- audit log
    # Phase 2 E Slice 4.B — read-only window into the vault audit log
    # (ADR-0023 §3 + ADR-0018). Producer hooks live in Vault; the API
    # stays narrow on purpose — no append endpoint, no UPDATE / DELETE.
    # The contract is "the log is what the vault did", not "what the
    # client says the vault did".
    @app.get("/api/events")
    def list_events(
        kind: list[str] | None = Query(default=None),
        entity_id: str | None = Query(default=None),
        limit: int = Query(default=200, ge=1, le=2000),
    ) -> dict[str, Any]:
        from knowlet.core.audit_log import AuditEventStore

        store = AuditEventStore(vault.root)
        try:
            events = store.query(
                kinds=kind or None,
                entity_id=entity_id,
                limit=limit,
            )
            return {
                "events": [
                    {
                        "id": e.id,
                        "ts": e.ts,
                        "kind": e.kind,
                        "entity_type": e.entity_type,
                        "entity_id": e.entity_id,
                        "actor": e.actor,
                        "payload": e.payload,
                    }
                    for e in events
                ],
                "total": store.count(),
            }
        finally:
            store.close()

    # ---------------- per-note sync status (Slice S1) ----------------
    # Single seam the UI binds the per-note SyncStatusBadge to.
    # Returns one of {unauthenticated, offline, synced, dirty,
    # conflict} plus tooltip metadata. ~150ms per request when
    # connected (one Drive files.get round trip); the frontend
    # polls every 10s for the active note.
    @app.get("/api/sync/note-status/{note_id}")
    def get_note_sync_status(note_id: str) -> dict[str, Any]:
        from knowlet.core.sync.state import SyncStateStore
        from knowlet.core.sync.status import compute_note_sync_status

        store = SyncStateStore(vault.root)
        try:
            status = compute_note_sync_status(
                vault_root=vault.root,
                note_id=note_id,
                state_store=store,
            )
        finally:
            store.close()
        return {
            "state": status.state,
            "last_synced_at": status.last_synced_at,
            "drive_file_id": status.drive_file_id,
            "last_known_revision": status.last_known_revision,
            "current_drive_revision": status.current_drive_revision,
            "detail": status.detail,
        }

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        bs = state.bootstrap_status
        body: dict[str, Any] = {
            "status": "ok",
            "version": __version__,
            "vault": str(vault.root),
            "model": config.llm.model,
            "language": config.general.language,
            "supported_languages": list(SUPPORTED_LANGUAGES),
            # Async-bootstrap signal. The frontend reads `ready` to show a
            # "still indexing" banner during the first reindex on a large
            # vault. `bootstrap_status` exposes finer detail for diagnostics.
            "ready": bs == "ready",
            "bootstrap_status": bs,
        }
        if bs == "error" and state.bootstrap_error is not None:
            body["bootstrap_error"] = str(state.bootstrap_error)
        return body

    @app.get("/api/i18n/{lang}")
    def i18n_catalog(lang: str) -> dict[str, str]:
        return all_keys(lang)

    # ---------------- structure signals (M8.1 / ADR-0013 Layer B) ----------

    @app.get("/api/structure/signals", response_model=StructureSignalsPayload)
    def structure_signals(
        near_dup_cosine: float = DEFAULT_NEAR_DUP_COSINE,
        orphan_days: int = DEFAULT_ORPHAN_UNTOUCHED_DAYS,
        aging_days: int = DEFAULT_AGING_UNTOUCHED_DAYS,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> StructureSignalsPayload:
        """Compute the four structure signals over the current vault.
        Read-only; no UI yet (M8.2 knowledge-map sidebar will consume).

        Per ADR-0013 §1 contract: pure information, no auto-action
        verbs. The wire payload deliberately ships titles + ids only —
        the UI decides how (or whether) to surface buttons."""
        # Bound thresholds defensively: cosine ∈ [0.5, 0.999], days ≥ 1.
        cos = max(0.5, min(0.999, float(near_dup_cosine)))
        od = max(1, int(orphan_days))
        ad = max(1, int(aging_days))
        result = compute_signals(
            runtime.index,
            runtime.vault.iter_note_paths(),
            near_dup_cosine=cos,
            orphan_days=od,
            aging_days=ad,
        )
        return StructureSignalsPayload(
            near_duplicates=[
                NearDupPairPayload(
                    a_id=p.a_id,
                    a_title=p.a_title,
                    b_id=p.b_id,
                    b_title=p.b_title,
                    cosine=round(p.cosine, 4),
                )
                for p in result.near_duplicates
            ],
            clusters=[
                NoteClusterPayload(
                    note_ids=c.note_ids,
                    note_titles=c.note_titles,
                )
                for c in result.clusters
            ],
            orphan_notes=[
                OrphanNotePayload(id=o.id, title=o.title, days_untouched=o.days_untouched)
                for o in result.orphan_notes
            ],
            aging_candidates=[
                AgingCandidatePayload(id=a.id, title=a.title, days_untouched=a.days_untouched)
                for a in result.aging_candidates
            ],
        )

    # ---------------- chat ----------------

    def _expand_references(
        runtime: ChatRuntime,
        refs: list[QuoteRefPayload],
    ) -> list[tuple[QuoteRef, str]]:
        """Resolve each capsule into (QuoteRef, body) pairs for the prompt
        formatter. Two branches per ADR-0016 §2:

        - source="note" (M7.1): vault lookup of note_id → fresh body. Notes
          the user has since deleted are dropped silently.
        - source="url" (M7.2): no vault lookup; quote_text already holds
          the LLM-produced summary. body passes as "" (formatter ignores
          it for url source).

        Hard-truncates at MAX_REFERENCES per ADR-0015 §2."""
        out: list[tuple[QuoteRef, str]] = []
        for r in refs[:MAX_REFERENCES]:
            if r.source == "url":
                out.append(
                    (
                        QuoteRef(
                            note_id=r.note_id,
                            note_title=r.note_title,
                            quote_text=r.quote_text,
                            paragraph_anchor="",
                            source="url",
                            source_url=r.source_url,
                        ),
                        "",  # body unused for url source
                    )
                )
                continue
            # source="note" path
            meta = runtime.index.get_note_meta(r.note_id)
            if meta is None:
                continue
            path = Path(meta["path"])
            if not path.is_absolute():
                path = runtime.vault.notes_dir / path.name
            try:
                note = runtime.vault.read_note(path)
            except Exception:  # noqa: S112 — skip unreadable notes; quote panel is best-effort
                continue
            out.append(
                (
                    QuoteRef(
                        note_id=r.note_id,
                        note_title=r.note_title or note.title,
                        quote_text=r.quote_text,
                        paragraph_anchor=r.paragraph_anchor,
                        source="note",
                    ),
                    note.body,
                )
            )
        return out

    def _compose_user_text(req: ChatTurnRequest, runtime: ChatRuntime) -> str:
        """If the request carries capsules, prefix the user text with
        formatted quote+section blocks. Otherwise return text unchanged.
        Centralized so /turn and /stream stay in lockstep."""
        if not req.references:
            return req.text
        pairs = _expand_references(runtime, req.references)
        prefix = format_references_block(pairs)
        return prefix + req.text if prefix else req.text

    @app.post("/api/chat/turn", response_model=ChatTurnResponse)
    def chat_turn(
        req: ChatTurnRequest,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> ChatTurnResponse:
        traces: list[ToolTrace] = []

        def on_tool_call(tc: ToolCall, payload: dict[str, Any]) -> None:
            traces.append(ToolTrace(name=tc.name, arguments=tc.arguments, result=payload))

        try:
            user_text = _compose_user_text(req, runtime)
            reply, _ = runtime.session.user_turn(user_text, on_tool_call=on_tool_call)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"LLM error: {exc}",
            ) from exc
        # M6.4: persist the active conversation after every turn so a
        # browser refresh / server restart doesn't lose the exchange.
        runtime.persist_active()
        return ChatTurnResponse(reply=reply, tool_calls=traces)

    @app.post("/api/chat/stream")
    def chat_stream(
        req: ChatTurnRequest,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> StreamingResponse:
        """SSE stream of structured chat events for one user turn.

        Per ADR-0008, this is the primary chat path. The frontend reads it via
        `fetch` + ReadableStream + manual SSE parsing. The non-streaming
        `/api/chat/turn` is kept as a fallback for non-browser callers.
        """

        user_text = _compose_user_text(req, runtime)

        def event_source() -> Iterator[str]:
            try:
                for event in runtime.session.user_turn_stream(user_text):
                    payload = json.dumps(event_to_dict(event), ensure_ascii=False)
                    yield f"data: {payload}\n\n"
            except Exception as exc:
                err = ErrorEvent(message=f"server error: {exc}")
                yield f"data: {json.dumps(event_to_dict(err))}\n\n"
            finally:
                # Persist the (possibly partial) turn so a refresh mid-stream
                # doesn't drop the exchange.
                with suppress(Exception):
                    runtime.persist_active()

        return StreamingResponse(
            event_source(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",  # disable proxy buffering if any
            },
        )

    @app.post("/api/chat/clear")
    def chat_clear(runtime: ChatRuntime = Depends(runtime_dep)) -> dict[str, Any]:
        """`Clear chat` from the UI now means *start a new session* (M6.4).

        The previous session stays on disk and is reachable from the
        sidebar. This is more honest semantics than truncating history in
        place: nothing is destroyed, and the user gets a fresh slate.
        """
        new_conv = runtime.new_session()
        return {"ok": True, "active_id": new_conv.id}

    @app.post("/api/chat/ask-once")
    def chat_ask_once(
        req: ChatTurnRequest,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> StreamingResponse:
        """One-shot chat turn that does NOT touch the persistent session.

        Cmd+K palette uses this to power the `>` prefix (ADR-0011 §4): the
        answer pops up inline and is discarded. Reuses the same llm/registry/
        ctx as the persistent session, but with a fresh `ChatSession` so its
        history is born and dies in this request.
        """
        from knowlet.chat.session import ChatSession

        ephemeral = ChatSession(
            llm=runtime.session.llm,
            registry=runtime.session.registry,
            ctx=runtime.session.ctx,
            system_prompt=runtime.session.history[0].get("content")
            if runtime.session.history
            else None,
        )

        def event_source() -> Iterator[str]:
            try:
                for event in ephemeral.user_turn_stream(req.text):
                    payload = json.dumps(event_to_dict(event), ensure_ascii=False)
                    yield f"data: {payload}\n\n"
            except Exception as exc:
                err = ErrorEvent(message=f"server error: {exc}")
                yield f"data: {json.dumps(event_to_dict(err))}\n\n"

        return StreamingResponse(
            event_source(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @app.get("/api/chat/history")
    def chat_history(
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> dict[str, Any]:
        # Skip the system message in the response — the UI doesn't need it.
        public = [m for m in runtime.session.history if m.get("role") in ("user", "assistant")]
        return {
            "history": public,
            "active_id": runtime.active_conversation.id,
            "active_title": runtime.active_conversation.title,
        }

    # ---------------- multi-session (M6.4) ----------------

    @app.get("/api/chat/sessions")
    def chat_sessions_list(
        limit: int = 50,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> dict[str, Any]:
        """List persisted conversations, most recent first."""
        rows = runtime.conversations.list(limit=limit, only_meaningful=True)
        return {
            "active_id": runtime.active_conversation.id,
            "sessions": [
                {
                    "id": r.id,
                    "title": r.title,
                    "model": r.model,
                    "started_at": r.started_at,
                    "updated_at": r.updated_at,
                    "message_count": r.message_count,
                }
                for r in rows
            ],
        }

    @app.post("/api/chat/sessions")
    def chat_sessions_new(
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> dict[str, Any]:
        """Start a fresh session and switch the runtime to it."""
        new_conv = runtime.new_session()
        return {"id": new_conv.id, "title": new_conv.title}

    @app.post("/api/chat/sessions/{conv_id}/activate")
    def chat_sessions_activate(
        conv_id: str,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> dict[str, Any]:
        """Switch the runtime's active session. Persists the outgoing one."""
        target = runtime.conversations.get(conv_id)
        if target is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"conversation not found: {conv_id}",
            )
        runtime.switch_to(target)
        return {"id": target.id, "title": target.title}

    @app.put("/api/chat/sessions/{conv_id}")
    def chat_sessions_rename(
        conv_id: str,
        req: RenameSessionRequest,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> dict[str, Any]:
        conv = runtime.conversations.rename(conv_id, req.title)
        if conv is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"conversation not found: {conv_id}",
            )
        # If we just renamed the active session, refresh the in-memory copy.
        if runtime.active_conversation.id == conv_id:
            runtime.active_conversation = conv
        return {"id": conv.id, "title": conv.title}

    @app.post("/api/chat/sessions/{conv_id}/auto-title")
    def chat_sessions_auto_title(
        conv_id: str,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> dict[str, Any]:
        """Generate a short title for a conversation via LLM summary.

        Per ADR-0011 §"Open questions" #2: titles are auto-summarized
        after the first user message. The frontend fires this
        fire-and-forget right after sendChat completes for an untitled
        session — no UI blocking, just a refresh of the session list a
        moment later picks up the new title.

        Idempotent-ish: if the conversation already has a title, returns
        the existing one without re-calling the LLM. Empty / new-session
        edge case returns 400.
        """
        conv = runtime.conversations.get(conv_id)
        if conv is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"conversation not found: {conv_id}",
            )
        if conv.title:
            return {"id": conv.id, "title": conv.title, "generated": False}

        # Pull the first real user/assistant exchange. The system prompt
        # at index 0 isn't useful for a title.
        excerpt: list[str] = []
        for m in conv.messages:
            role = m.get("role")
            content = (m.get("content") or "").strip()
            if not content:
                continue
            if role == "user":
                excerpt.append(f"USER: {content[:400]}")
            elif role == "assistant":
                excerpt.append(f"ASSISTANT: {content[:400]}")
            if len(excerpt) >= 2:
                break
        if not excerpt:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="conversation has no exchanges to summarize",
            )

        prompt = (
            "Give a 3-to-5-word title for this short conversation excerpt. "
            "Output the title only — no quotes, no preamble, no period. "
            "Use the same language the user wrote in.\n\n" + "\n\n".join(excerpt) + "\n\nTitle:"
        )
        try:
            resp = runtime.llm.chat(
                [{"role": "user", "content": prompt}],
                max_tokens=32,
                temperature=0,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"auto-title LLM error: {exc}",
            ) from exc

        title = (resp.content or "").strip().strip('"').strip("'").strip()
        # Clip aggressively. LLMs sometimes ignore the word-cap; we don't
        # want a paragraph-long title polluting the sidebar.
        if len(title) > 60:
            title = title[:57].rstrip() + "…"
        if not title:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="auto-title returned empty content",
            )

        runtime.conversations.rename(conv.id, title)
        if runtime.active_conversation.id == conv.id:
            runtime.active_conversation.title = title
        return {"id": conv.id, "title": title, "generated": True}

    @app.delete("/api/chat/sessions/{conv_id}")
    def chat_sessions_delete(
        conv_id: str,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> dict[str, Any]:
        # Refuse to delete the active session — the UI should switch first.
        if runtime.active_conversation.id == conv_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="cannot delete the active session — switch first",
            )
        ok = runtime.conversations.delete(conv_id)
        if not ok:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"conversation not found: {conv_id}",
            )
        return {"ok": True}

    # ---------------- sediment / save ----------------

    @app.post("/api/chat/draft", response_model=DraftPayload)
    def chat_draft(runtime: ChatRuntime = Depends(runtime_dep)) -> DraftPayload:
        if len(runtime.session.history) <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="nothing to sediment yet",
            )
        try:
            draft = draft_from_conversation(runtime.llm, runtime.session.history)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"draft failed: {exc}",
            ) from exc
        return DraftPayload(title=draft.title, tags=draft.tags, body=draft.body)

    @app.post("/api/notes", response_model=CommitDraftResponse)
    def commit_note(
        payload: CommitDraftRequest,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> CommitDraftResponse:
        draft = SedimentDraft(title=payload.title, tags=payload.tags, body=payload.body)
        note = commit_draft(draft, runtime.vault, runtime.index, runtime.config)
        return CommitDraftResponse(note_id=note.id, path=str(note.path))

    # ---------------- notes (read) ----------------

    @app.get("/api/notes", response_model=list[NoteSummary])
    def list_notes(
        limit: int = 20,
        recent: bool = False,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> list[NoteSummary]:
        rows = runtime.index.list_notes(limit=limit, order="updated_at" if recent else "created_at")
        # M7.0.2: derive folder (relative to notes_dir) for each row so
        # the sidebar can build a tree without extra round-trips.
        out: list[NoteSummary] = []
        for r in rows:
            folder = ""
            p = r.get("path")
            if p:
                try:
                    folder = runtime.vault.folder_of(Path(p))
                except (TypeError, ValueError):
                    folder = ""
            out.append(NoteSummary(**r, folder=folder))
        return out

    # ---------------- tags (Phase 1 C slice 2) ----------------

    @app.get("/api/tags", response_model=list[TagSummary])
    def list_all_tags(
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> list[TagSummary]:
        """All tags in the vault with note counts, sorted by count desc.

        Phase 1 C slice 2 — backend for the left-rail Tag browser. Tags
        are user-typed labels stored in Note frontmatter `tags:` and
        indexed as a JSON column. ADR-0013 §3 Layer B: NO auto-grouping
        / NO taxonomy enforcement — we just surface what the user wrote.
        """
        return [
            TagSummary(tag=t, count=c) for t, c in runtime.index.aggregate_tags()
        ]

    @app.get("/api/tags/{tag}/notes", response_model=list[NoteSummary])
    def list_notes_with_tag(
        tag: str,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> list[NoteSummary]:
        """Return all notes that include `tag` in their frontmatter tags.

        Linear scan via `index.list_notes_by_tag`; fine up to ~5k notes
        per ADR-0021. Case-sensitive match (tags are user identity, not
        approximate)."""
        rows = runtime.index.list_notes_by_tag(tag)
        out: list[NoteSummary] = []
        for r in rows:
            folder = ""
            p = r.get("path")
            if p:
                try:
                    folder = runtime.vault.folder_of(Path(p))
                except (TypeError, ValueError):
                    folder = ""
            out.append(NoteSummary(**r, folder=folder))
        return out

    @app.get("/api/tags/all-with-notes", response_model=list[TagWithNotes])
    def list_tags_with_notes(
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> list[TagWithNotes]:
        """Phase 1 C slice 2 polish D — every tag + its notes in one round-
        trip. The file-tree Tag browser needs this to render notes as
        children of tag nodes without firing an N+1 wave per tag.

        Implementation: single scan of `list_notes` (no embedding work),
        group by tag in Python. Cheap at ADR-0021 vault sizes (<5k)."""
        notes_by_tag: dict[str, list[NoteSummary]] = {}
        counts: dict[str, int] = {}
        for r in runtime.index.list_notes(limit=None):
            folder = ""
            p = r.get("path")
            if p:
                try:
                    folder = runtime.vault.folder_of(Path(p))
                except (TypeError, ValueError):
                    folder = ""
            note_summary = NoteSummary(**r, folder=folder)
            for t in r.get("tags") or []:
                if not isinstance(t, str) or not t.strip():
                    continue
                key = t.strip()
                notes_by_tag.setdefault(key, []).append(note_summary)
                counts[key] = counts.get(key, 0) + 1
        # Match /api/tags ordering: count desc, then tag asc.
        ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].lower()))
        return [
            TagWithNotes(
                tag=tag,
                count=count,
                notes=notes_by_tag.get(tag, []),
            )
            for tag, count in ordered
        ]

    @app.get("/api/graph", response_model=GraphPayload)
    def get_graph(runtime: ChatRuntime = Depends(runtime_dep)) -> GraphPayload:
        """Phase 1 C slice 3 — user-authored bilink graph snapshot.

        Per [ADR-0023 §1](docs/decisions/0023-llm-wiki-comparison-and-takeaways.md)
        this view shows ground-truth user-validated structure (the
        `[[Title]]` references the user wrote themselves), distinct
        from M8.2 knowledge-map sidebar which surfaces LLM-inferred
        signals. Dangling links are excluded — the Linter (ADR-0023
        §5) handles those separately.

        Cheap at <5k notes (one pass + per-note read for wikilink
        extraction; same approach as `/api/notes/{id}/backlinks`).
        """
        metas = runtime.index.list_notes(limit=None)

        def _read_body(path_str: str) -> str:
            p = Path(path_str)
            if not p.is_absolute():
                p = runtime.vault.notes_dir / p.name
            return read_body_via_note(p)

        graph = build_graph(
            metas,
            folder_for=runtime.vault.folder_of,
            read_body=_read_body,
        )
        return GraphPayload(
            nodes=[
                GraphNodeRow(
                    id=n.id,
                    title=n.title,
                    folder=n.folder,
                    in_degree=n.in_degree,
                    out_degree=n.out_degree,
                )
                for n in graph.nodes
            ],
            edges=[
                GraphEdgeRow(source=e.source, target=e.target) for e in graph.edges
            ],
        )

    @app.get("/api/search", response_model=SearchPayload)
    def search_vault(
        q: str = "",
        top_k: int = 30,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> SearchPayload:
        """Phase 1 D slice 2 — global full-text + vector search.

        Reuses `index.search()` (RRF hybrid: BM25 over chunks_fts +
        cosine over chunks_vec, fused with k=60). Returns up to
        `top_k` hits (clamped [1, 50]). Caller is the focus-mode
        Search panel; chunk_position from the underlying SearchHit
        is intentionally NOT exposed because chunk → line conversion
        is non-trivial and the v1 panel only needs note-level open.

        For empty / whitespace-only `q`, returns `{query, hits: []}`.
        Folder is derived from the on-disk path, same shape as the
        rest of the API."""
        q_stripped = (q or "").strip()
        k = max(1, min(50, int(top_k)))
        if not q_stripped:
            return SearchPayload(query=q, hits=[])
        hits = runtime.index.search(query=q_stripped[:4000], top_k=k)
        out: list[SearchHitRow] = []
        for h in hits:
            folder = ""
            if h.path:
                try:
                    folder = runtime.vault.folder_of(Path(h.path))
                except (TypeError, ValueError):
                    folder = ""
            # Templates live under `_templates/` as a vault convention
            # (per ADR / Phase 1 B slice 8) — they're storage for the
            # Templates dialog, not user knowledge. Hide from the global
            # search so they don't dilute results when the query happens
            # to overlap a template's placeholder text.
            if folder.startswith("_templates"):
                continue
            out.append(
                SearchHitRow(
                    note_id=h.note_id,
                    title=(h.title or "(untitled)").strip(),
                    folder=folder,
                    snippet=(h.snippet or "").strip(),
                    score=float(h.score),
                )
            )
        return SearchPayload(query=q, hits=out)

    @app.get("/api/notes/similar", response_model=list[SimilarNoteRow])
    def list_similar_notes(
        q: str = "",
        top_k: int = 3,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> list[SimilarNoteRow]:
        """M7.2 / ADR-0013 §3 Layer A — top-K Notes whose content overlaps
        the query string (typically the user's draft body in the sediment
        modal). Pure information; the contract is "AI gives info, human
        decides" — no merge buttons, no scores, no auto-actions.

        Reuses `index.search()` (RRF hybrid: FTS + vec). top_k clamped
        to [1, 10] so a careless caller can't exhaust the index. Route
        deliberately registered *before* `/api/notes/{note_id}` so the
        literal path doesn't get captured as a note id."""
        q = (q or "").strip()
        if not q:
            return []
        k = max(1, min(10, int(top_k)))
        hits = runtime.index.search(query=q[:4000], top_k=k)
        return [
            SimilarNoteRow(
                id=h.note_id,
                title=h.title or "(无标题)",
                path=h.path or "",
                preview=(h.snippet or "").strip()[:160],
            )
            for h in hits
        ]

    @app.get("/api/notes/{note_id}", response_model=NoteFull)
    def get_note(note_id: str, runtime: ChatRuntime = Depends(runtime_dep)) -> NoteFull:
        meta = runtime.index.get_note_meta(note_id)
        if meta is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"note not found: {note_id}",
            )
        path = Path(meta["path"])
        if not path.is_absolute():
            path = runtime.vault.notes_dir / path.name
        try:
            note = runtime.vault.read_note(path)
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail=f"note file missing on disk: {path}",
            ) from exc
        return NoteFull(
            id=note.id,
            title=note.title,
            path=str(path),
            tags=note.tags,
            aliases=list(note.aliases),
            source=note.source,
            created_at=note.created_at,
            updated_at=note.updated_at,
            body=note.body,
        )

    @app.delete("/api/notes/{note_id}")
    def delete_note(
        note_id: str,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> dict[str, Any]:
        """Soft-delete a Note (M7.0.1).

        Moves the file to `<vault>/notes/.trash/` (recoverable via the
        `knowlet notes restore` CLI or by hand in Finder) and removes the
        index entry so search / chat tools stop surfacing it. Per ADR-0013
        §1, this counts as a structural change — only triggered by an
        explicit user click, never by AI.
        """
        meta = runtime.index.get_note_meta(note_id)
        if meta is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"note not found: {note_id}",
            )
        path = Path(meta["path"])
        if not path.is_absolute():
            path = runtime.vault.notes_dir / path.name
        try:
            trashed = runtime.vault.trash_note(path)
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail=f"note file missing on disk: {path}",
            ) from exc
        runtime.index.delete_note(note_id)
        return {
            "ok": True,
            "id": note_id,
            "trashed_to": str(trashed),
        }

    @app.put("/api/notes/{note_id}", response_model=NoteFull)
    def update_note(
        note_id: str,
        payload: DraftPayload,  # reuses {title, tags, body} shape
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> NoteFull:
        meta = runtime.index.get_note_meta(note_id)
        if meta is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"note not found: {note_id}",
            )
        path = Path(meta["path"])
        if not path.is_absolute():
            path = runtime.vault.notes_dir / path.name
        try:
            note = runtime.vault.read_note(path)
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail=f"note file missing on disk: {path}",
            ) from exc
        # ULID-only filenames: the on-disk path doesn't change when the
        # title changes, so this is a pure in-place rewrite — no rename,
        # no unlink, no sync-conflict (B3 / 2026-05-02 critique #5).
        note.title = payload.title.strip() or note.title
        note.body = payload.body
        # Phase 1 C polish — merge inline `#tag` from body into frontmatter
        # additively. User-typed body tags become first-class without
        # extra UI gymnastics. ADR-0013 §1 still holds: this is user-
        # initiated (the user wrote `#tag` themselves), not LLM-inferred.
        note.tags = merge_with_inline_tags(list(payload.tags), payload.body)
        # D3 Properties UI: aliases is None == "leave alone"; an empty
        # list clears; a list replaces. Tri-state lets pre-D3 clients
        # do title/body PUTs without wiping aliases someone added in
        # the UI or via Finder.
        if payload.aliases is not None:
            note.aliases = [a.strip() for a in payload.aliases if a and a.strip()]
        new_path = runtime.vault.write_note(note)
        runtime.index.upsert_note(
            note,
            chunk_size=runtime.config.retrieval.chunk_size,
            chunk_overlap=runtime.config.retrieval.chunk_overlap,
        )
        return NoteFull(
            id=note.id,
            title=note.title,
            path=str(new_path),
            tags=note.tags,
            aliases=list(note.aliases),
            source=note.source,
            created_at=note.created_at,
            updated_at=note.updated_at,
            body=note.body,
        )

    @app.get("/api/notes/{note_id}/backlinks", response_model=list[BacklinkRow])
    def list_backlinks(
        note_id: str,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> list[BacklinkRow]:
        """M7.0.4: Notes that reference this one via `[[Title]]`.

        On-demand scan over `iter_note_paths` — small vaults (<5k notes)
        finish in well under 100ms; if that ever becomes a problem we'll
        add a wikilink table to the index. For now, no precompute
        means no stale-index bug, which is the right tradeoff.
        """
        meta = runtime.index.get_note_meta(note_id)
        if meta is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"note not found: {note_id}",
            )
        target_title = (meta.get("title") or "").strip()
        if not target_title:
            return []
        results = find_backlinks(
            target_title,
            runtime.vault.iter_note_paths(),
            exclude_id=note_id,
        )
        return [
            BacklinkRow(
                source_id=b.source_id,
                source_title=b.source_title,
                target=b.target,
                line=b.line,
                sentence=b.sentence,
            )
            for b in results
        ]

    # ---------------- file tree + folder + trash (Phase 1 A) ----------------

    @app.get("/api/tree", response_model=TreeFolder)
    def get_tree(runtime: ChatRuntime = Depends(runtime_dep)) -> TreeFolder:
        """Return the entire `notes/` hierarchy (folders + notes) for the
        sidebar. Walks the index for note metadata so we don't re-parse
        every Markdown file on each tree refresh.

        Notes that exist on disk but aren't indexed (rare — usually a
        partial-write or freshly-pasted file) get surfaced under the root
        with `(unindexed)` in the title so the user sees them; reindex
        picks them up.
        """
        return _build_tree(runtime.vault, runtime.index)

    @app.post("/api/folders", response_model=FolderResponse)
    def create_folder(
        req: FolderCreateRequest,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> FolderResponse:
        try:
            target = runtime.vault.mkdir_folder(req.path)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        return FolderResponse(path=_rel_folder(runtime.vault, target))

    @app.patch("/api/folders", response_model=FolderResponse)
    def rename_folder_endpoint(
        req: FolderRenameRequest,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> FolderResponse:
        """Rename a folder in place. Cascades into the index: every note
        under the old path gets its `path` column updated to the new
        location (no re-chunking — bodies are unchanged)."""
        try:
            new_path = runtime.vault.rename_folder(req.path, req.new_name)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except FileExistsError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        _resync_paths_under(runtime, new_path)
        return FolderResponse(path=_rel_folder(runtime.vault, new_path))

    @app.post("/api/folders/move", response_model=FolderResponse)
    def move_folder_endpoint(
        req: FolderMoveRequest,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> FolderResponse:
        try:
            new_path = runtime.vault.move_folder(req.src, req.dst_parent)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except FileExistsError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        _resync_paths_under(runtime, new_path)
        return FolderResponse(path=_rel_folder(runtime.vault, new_path))

    @app.delete("/api/folders")
    def delete_folder_endpoint(
        req: FolderDeleteRequest,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> dict[str, Any]:
        """Delete a folder. Every note under it gets soft-deleted to
        `notes/.trash/` (recoverable) and removed from the index by id; the
        empty subtree is then `rmtree`d."""
        try:
            trashed = runtime.vault.delete_folder(req.path)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        for trashed_path in trashed:
            note_id = trashed_path.stem
            runtime.index.delete_note(note_id)
        return {"ok": True, "trashed_count": len(trashed)}

    @app.get("/api/templates", response_model=list[TemplateSummary])
    def list_templates(
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> list[TemplateSummary]:
        """List notes that live under `notes/templates/`. Surfaces the
        title only — full body is read at apply-time. Empty list when
        the folder doesn't exist or has no .md files."""
        out: list[TemplateSummary] = []
        for p in runtime.vault.iter_templates():
            try:
                tpl = runtime.vault.read_note(p)
            except FileNotFoundError:
                continue
            out.append(TemplateSummary(id=tpl.id, title=tpl.title))
        return out

    @app.post("/api/notes/new", response_model=NoteFull)
    def create_blank_note(
        req: NewNoteRequest,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> NoteFull:
        """Create a new note in the given folder. The folder must
        already exist (UI mkdirs first if needed). When `template_id`
        is supplied, the new note's body is pre-filled from the
        template (which must live under `notes/templates/`), with
        `{{title}}` / `{{date}}` substituted."""
        from knowlet.core.note import Note as _Note
        from knowlet.core.note import new_id

        title = req.title.strip()
        if not title:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="title is empty")
        body = ""
        if req.template_id:
            tpl_path: Path | None = None
            for p in runtime.vault.iter_templates():
                try:
                    tpl = runtime.vault.read_note(p)
                except FileNotFoundError:
                    continue
                if tpl.id == req.template_id:
                    tpl_path = p
                    body = runtime.vault.apply_template_placeholders(tpl.body, title=title)
                    break
            if tpl_path is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"template not found: {req.template_id}",
                )
        # Phase 1 C polish — pick up `#tag` from a template body too.
        merged_tags = merge_with_inline_tags(list(req.tags), body)
        note = _Note(id=new_id(), title=title, body=body, tags=merged_tags)
        try:
            path = runtime.vault.write_note(note, folder=req.folder or None)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        runtime.index.upsert_note(
            note,
            chunk_size=runtime.config.retrieval.chunk_size,
            chunk_overlap=runtime.config.retrieval.chunk_overlap,
        )
        return NoteFull(
            id=note.id,
            title=note.title,
            path=str(path),
            folder=runtime.vault.folder_of(path),
            tags=note.tags,
            aliases=list(note.aliases),
            source=note.source,
            created_at=note.created_at,
            updated_at=note.updated_at,
            body=note.body,
        )

    # ---------- Quick actions (Phase 2 D Slice 2c, ADR-0025) ----------

    def _quick_action_store(runtime: ChatRuntime) -> QuickActionStore:
        return QuickActionStore(vault_root=runtime.vault.root)

    def _coerce_payload(payload: QuickActionPayload, *, action_id: str) -> QuickAction:
        """Validate the JSON payload through the discriminated-union
        Pydantic model. Raises 400 on invalid `kind` / missing fields."""
        kind = payload.params.get("kind")
        if kind == "create_note":
            params: CreateNoteParams = CreateNoteParams.model_validate(payload.params)
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"unsupported action kind: {kind!r}",
            )
        return QuickAction(
            id=action_id,
            name=payload.name,
            description=payload.description,
            shortcut=payload.shortcut,
            params=params,
        )

    @app.get("/api/quick-actions", response_model=list[QuickAction])
    def list_quick_actions(
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> list[QuickAction]:
        # First call seeds the default `today-note` action; subsequent
        # calls just load whatever the user has now (including [] if
        # they deleted everything). See QuickActionStore.load_with_defaults.
        return _quick_action_store(runtime).load_with_defaults()

    @app.post("/api/quick-actions", response_model=QuickAction)
    def create_quick_action(
        payload: QuickActionPayload,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> QuickAction:
        action = _coerce_payload(payload, action_id=new_action_id())
        return _quick_action_store(runtime).upsert(action)

    @app.put("/api/quick-actions/{action_id}", response_model=QuickAction)
    def update_quick_action(
        action_id: str,
        payload: QuickActionPayload,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> QuickAction:
        store = _quick_action_store(runtime)
        if store.get(action_id) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"quick action not found: {action_id}",
            )
        action = _coerce_payload(payload, action_id=action_id)
        return store.upsert(action)

    @app.delete("/api/quick-actions/{action_id}")
    def delete_quick_action(
        action_id: str,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> dict[str, Any]:
        ok = _quick_action_store(runtime).delete(action_id)
        if not ok:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"quick action not found: {action_id}",
            )
        return {"ok": True, "id": action_id}

    @app.post("/api/quick-actions/{action_id}/run", response_model=NoteFull)
    def run_quick_action(
        action_id: str,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> NoteFull:
        """Execute the action. v1 only handles `kind=create_note`:
        renders the title placeholders, mkdirs the target folder if
        missing, and creates the note (idempotent: same folder + same
        rendered title returns the existing note instead of duplicating).
        """
        from knowlet.core.note import Note as _Note
        from knowlet.core.note import new_id

        action = _quick_action_store(runtime).get(action_id)
        if action is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"quick action not found: {action_id}",
            )
        if not isinstance(action.params, CreateNoteParams):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"action kind {action.params.kind!r} is not runnable in v1",
            )
        params = action.params
        title = render_title_placeholders(params.title_template).strip()
        if not title:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="rendered title is empty",
            )
        # Idempotency: if a note with this title already exists in the
        # target folder, return it. Mirrors daily-note semantics so a
        # user re-running "今日笔记" doesn't pile up duplicates.
        target_folder = params.folder.strip("/")
        notes_dir = runtime.vault.notes_dir
        scan_dir = (notes_dir / target_folder) if target_folder else notes_dir
        if scan_dir.is_dir():
            for p in sorted(scan_dir.glob("*.md")):
                try:
                    existing = runtime.vault.read_note(p)
                except FileNotFoundError:
                    continue
                if existing.title == title:
                    return NoteFull(
                        id=existing.id,
                        title=existing.title,
                        path=str(p),
                        folder=runtime.vault.folder_of(p),
                        tags=existing.tags,
                        aliases=list(existing.aliases),
                        source=existing.source,
                        created_at=existing.created_at,
                        updated_at=existing.updated_at,
                        body=existing.body,
                    )
        # Mkdir if needed.
        if target_folder:
            try:
                runtime.vault.mkdir_folder(target_folder)
            except FileExistsError:
                pass
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=str(exc),
                ) from exc
        body = ""
        if params.content_template_id:
            tpl_path: Path | None = None
            for p in runtime.vault.iter_templates():
                try:
                    tpl = runtime.vault.read_note(p)
                except FileNotFoundError:
                    continue
                if tpl.id == params.content_template_id:
                    tpl_path = p
                    body = runtime.vault.apply_template_placeholders(
                        tpl.body, title=title
                    )
                    break
            if tpl_path is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"template not found: {params.content_template_id}",
                )
        merged_tags = merge_with_inline_tags([], body)
        note = _Note(id=new_id(), title=title, body=body, tags=merged_tags)
        path = runtime.vault.write_note(note, folder=target_folder or None)
        runtime.index.upsert_note(
            note,
            chunk_size=runtime.config.retrieval.chunk_size,
            chunk_overlap=runtime.config.retrieval.chunk_overlap,
        )
        return NoteFull(
            id=note.id,
            title=note.title,
            path=str(path),
            folder=runtime.vault.folder_of(path),
            tags=note.tags,
            aliases=list(note.aliases),
            source=note.source,
            created_at=note.created_at,
            updated_at=note.updated_at,
            body=note.body,
        )

    @app.post("/api/notes/{note_id}/move", response_model=NoteFull)
    def move_note_endpoint(
        note_id: str,
        req: NoteMoveRequest,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> NoteFull:
        """Move a single note to a target folder. The note id (and ULID
        filename) stay the same; the path column updates."""
        meta = runtime.index.get_note_meta(note_id)
        if meta is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"note not found: {note_id}",
            )
        path = Path(meta["path"])
        if not path.is_absolute():
            path = runtime.vault.notes_dir / path.name
        try:
            new_path = runtime.vault.move_note(path, req.target_folder)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_410_GONE, detail=str(exc)) from exc
        except FileExistsError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        runtime.index.update_note_path(note_id, str(new_path))
        note = runtime.vault.read_note(new_path)
        return NoteFull(
            id=note.id,
            title=note.title,
            path=str(new_path),
            folder=runtime.vault.folder_of(new_path),
            tags=note.tags,
            aliases=list(note.aliases),
            source=note.source,
            created_at=note.created_at,
            updated_at=note.updated_at,
            body=note.body,
        )

    @app.get("/api/trash", response_model=TrashListResponse)
    def list_trash(runtime: ChatRuntime = Depends(runtime_dep)) -> TrashListResponse:
        """List soft-deleted notes in `notes/.trash/`. We parse the
        frontmatter title best-effort; if a file is corrupt, we still
        surface it so the user can purge it. The `original_folder`
        field comes from the `trashed_from` frontmatter key written
        at trash time — used by the UI to hint where the note will
        land on restore."""
        entries: list[TrashEntry] = []
        for path in runtime.vault.iter_trashed_paths():
            original_folder: str | None = None
            try:
                note = Note.from_file(path)
                title = note.title
                note_id = note.id
                original_folder = note.trashed_from
            except Exception:
                title = path.stem
                note_id = path.stem
            entries.append(
                TrashEntry(
                    name=path.name,
                    title=title,
                    note_id=note_id,
                    trashed_at=_iso(path.stat().st_mtime),
                    original_folder=original_folder,
                )
            )
        # Newest-first matches "what did I just delete" intuition.
        entries.sort(key=lambda e: e.trashed_at, reverse=True)
        return TrashListResponse(entries=entries)

    @app.post("/api/trash/{name}/restore", response_model=NoteFull)
    def restore_trashed(
        name: str,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> NoteFull:
        if "/" in name or name.startswith(".") or not name.endswith(".md"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"invalid trash entry: {name!r}",
            )
        trashed_path = runtime.vault.trash_dir / name
        if not trashed_path.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"trash entry not found: {name}",
            )
        try:
            restored_path = runtime.vault.restore_note(trashed_path)
        except FileExistsError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        note = runtime.vault.read_note(restored_path)
        runtime.index.upsert_note(
            note,
            chunk_size=runtime.config.retrieval.chunk_size,
            chunk_overlap=runtime.config.retrieval.chunk_overlap,
        )
        return NoteFull(
            id=note.id,
            title=note.title,
            path=str(restored_path),
            folder=runtime.vault.folder_of(restored_path),
            tags=note.tags,
            aliases=list(note.aliases),
            source=note.source,
            created_at=note.created_at,
            updated_at=note.updated_at,
            body=note.body,
        )

    @app.post("/api/trash/restore-all", response_model=RestoreAllResponse)
    def restore_all_trashed(
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> RestoreAllResponse:
        """Restore every entry from `notes/.trash/` to its original
        folder (recreating ancestors as needed). A per-entry collision
        is not fatal — that one is skipped and the rest continue."""
        restored = 0
        skipped: list[str] = []
        for trashed_path in list(runtime.vault.iter_trashed_paths()):
            try:
                restored_path = runtime.vault.restore_note(trashed_path)
                note = runtime.vault.read_note(restored_path)
                runtime.index.upsert_note(
                    note,
                    chunk_size=runtime.config.retrieval.chunk_size,
                    chunk_overlap=runtime.config.retrieval.chunk_overlap,
                )
                restored += 1
            except FileExistsError:
                skipped.append(trashed_path.name)
            except FileNotFoundError:
                skipped.append(trashed_path.name)
        return RestoreAllResponse(restored_count=restored, skipped=skipped)

    @app.delete("/api/trash/{name}")
    def purge_trashed(
        name: str,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> dict[str, Any]:
        """Permanently delete one entry from trash. Index entry is already
        gone (`delete_note` runs at trash-time), so this is a pure file op."""
        try:
            runtime.vault.purge_trashed(name)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        return {"ok": True, "name": name}

    @app.delete("/api/trash")
    def empty_trash(runtime: ChatRuntime = Depends(runtime_dep)) -> dict[str, Any]:
        """Permanent-delete every entry in trash. No body needed."""
        purged = 0
        for path in list(runtime.vault.iter_trashed_paths()):
            try:
                runtime.vault.purge_trashed(path.name)
                purged += 1
            except (ValueError, FileNotFoundError):
                continue
        return {"ok": True, "purged_count": purged}

    # ---------------- attachments (M7.0.3) ----------------

    @app.post("/api/attachments")
    async def upload_attachment(
        file: UploadFile = File(...),
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> dict[str, Any]:
        """Save a pasted image into `notes/_attachments/<ULID>.<ext>` and
        return the markdown-relative path. Frontend pastes that path into
        the editor as `![](_attachments/...)` so the note stays portable
        across Obsidian / iCloud / plain Finder.

        Hard-coded to bitmap images for now — no PDFs, no SVG (XSS risk in
        the preview pane), no random binaries. The web UI is the only
        caller; CLI users embed images by hand in markdown."""
        ext_map = {
            "image/png": "png",
            "image/jpeg": "jpg",
            "image/jpg": "jpg",
            "image/gif": "gif",
            "image/webp": "webp",
        }
        ext = ext_map.get((file.content_type or "").lower())
        if ext is None:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=f"unsupported image type: {file.content_type!r}",
            )
        # 20 MB ceiling — bigger pastes are usually accidents (scanned PDFs
        # rasterized into the clipboard). Streaming would be nicer but the
        # body is already in memory by the time we reach here.
        data = await file.read()
        if len(data) > 20 * 1024 * 1024:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="attachment exceeds 20 MB limit",
            )
        path = runtime.vault.write_attachment(data, ext)
        return {
            "path": runtime.vault.attachment_relpath(path),
            "bytes": len(data),
        }

    @app.get("/files/_attachments/{name}")
    def get_attachment(
        name: str,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> FileResponse:
        """Serve an attachment by basename. Path-traversal hardened: no
        slashes / backslashes / leading dots / non-allowlisted extensions.
        Single segment only."""
        if "/" in name or "\\" in name or name.startswith("."):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid attachment name",
            )
        suffix = Path(name).suffix.lower().lstrip(".")
        if suffix not in {"png", "jpg", "jpeg", "gif", "webp"}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"disallowed extension: {suffix!r}",
            )
        target = runtime.vault.attachments_dir / name
        if not target.exists() or not target.is_file():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"attachment not found: {name}",
            )
        return FileResponse(target)

    # ---------------- url capture (M7.2 / ADR-0016) ----------------

    @app.post("/api/url/capture", response_model=UrlCaptureResponse)
    def capture_url_endpoint(
        req: UrlCaptureRequest,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> UrlCaptureResponse:
        """Fetch a URL via trafilatura, summarize via the configured LLM,
        return a payload the frontend wraps in a `source="url"` capsule.

        Failure modes:
        - 400: empty / non-http URL
        - 502: page fetch failed (DNS / 4xx / 5xx / timeout)
        - 422: page fetched but no readable content (JS-heavy / paywall)
        - 200 + summary_failed=true: page extracted, but the summarize
          LLM call raised. Frontend surfaces a "(摘要失败)" capsule so
          the user can still attach the URL and ask manually.
        """
        url = (req.url or "").strip()
        if not url or not (url.startswith("http://") or url.startswith("https://")):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid url (must start with http:// or https://)",
            )
        try:
            cap = capture_url(url, runtime.llm)
            return UrlCaptureResponse(
                url=cap.url,
                title=cap.title,
                hostname=cap.hostname,
                summary=cap.summary,
                summary_failed=False,
            )
        except FetchError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=str(exc),
            ) from exc
        except ExtractionError as exc:
            # 422 by literal — starlette renamed the constant to
            # _CONTENT and deprecated _ENTITY; either name is a
            # version-coupling hazard, the integer isn't.
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            # Page fetched + extracted, but the LLM step blew up. Per
            # ADR-0016 §3 we still return a capsule so the user can
            # attach the URL and ask manually.
            from knowlet.core.url_capture import _hostname, fetch_and_extract

            try:
                title, _ = fetch_and_extract(url)
            except Exception:
                title = url
            return UrlCaptureResponse(
                url=url,
                title=title,
                hostname=_hostname(url),
                summary=f"(摘要失败:{exc})",
                summary_failed=True,
            )

    # ---------------- quiz (M7.4 / ADR-0014) ----------------

    def _quiz_store_for(runtime: ChatRuntime) -> QuizStore:
        """Lazy QuizStore — vault might not have a `quizzes/` dir until the
        first session is saved. ADR-0006: `<vault>/.knowlet/quizzes/` is the
        third LLM-generated persistent surface alongside notes/ and drafts/."""
        return QuizStore(runtime.vault.state_dir)

    def _session_to_payload(session: QuizSession) -> QuizSessionPayload:
        return QuizSessionPayload(
            id=session.id,
            started_at=session.started_at,
            finished_at=session.finished_at,
            model=session.model,
            scope_type=session.scope_type,
            scope_note_ids=session.scope_note_ids,
            scope_tag=session.scope_tag,
            questions=[
                QuizQuestionPayload(
                    type=q.type,
                    question=q.question,
                    reference_answer=q.reference_answer,
                    source_note_ids=q.source_note_ids,
                    user_answer=q.user_answer,
                    ai_score=q.ai_score,
                    ai_reason=q.ai_reason,
                    ai_missing=q.ai_missing,
                    user_disagrees=q.user_disagrees,
                    user_disagree_reason=q.user_disagree_reason,
                    card_id_after_reflux=q.card_id_after_reflux,
                )
                for q in session.questions
            ],
            n_questions=session.n_questions,
            n_correct=session.n_correct,
            n_disagreement=session.n_disagreement,
            cards_created=session.cards_created,
            session_score=session.session_score,
        )

    @app.get("/api/quiz", response_model=list[QuizSummaryRow])
    def quiz_list(
        limit: int = 50,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> list[QuizSummaryRow]:
        """M7.4.3: past quizzes list for the focus mode's history tab.
        Returns light rows (no question text) — opens via /api/quiz/{id}."""
        store = _quiz_store_for(runtime)
        sessions = store.list_recent(limit=max(1, min(200, int(limit))))
        return [
            QuizSummaryRow(
                id=s.id,
                started_at=s.started_at,
                finished_at=s.finished_at,
                scope_type=s.scope_type,
                scope_note_ids=s.scope_note_ids,
                scope_tag=s.scope_tag,
                n_questions=s.n_questions,
                n_correct=s.n_correct,
                n_disagreement=s.n_disagreement,
                cards_created=s.cards_created,
                session_score=s.session_score,
            )
            for s in sessions
        ]

    @app.post("/api/quiz/start", response_model=QuizSessionPayload)
    def quiz_start(
        req: QuizStartRequest,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> QuizSessionPayload:
        """Generate `n` questions over the chosen Notes and persist a fresh
        QuizSession. M7.4.3 adds tag scope (resolves to note ids server-side);
        cluster scope is reserved for M8 Layer B and blocked here."""
        from datetime import UTC, datetime

        from knowlet.core.note import Note, new_id

        scope_type = (req.scope_type or "notes").lower()
        if scope_type == "cluster":
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail="cluster scope requires ADR-0013 Layer B (M8); not yet available",
            )
        n = max(1, min(20, int(req.n)))  # bound LLM call size

        # Resolve scope → list of note ids.
        if scope_type == "tag":
            tag = (req.tag or "").strip()
            if not tag:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="scope_type='tag' requires a non-empty `tag` field",
                )
            # In-memory tag filter — list_notes returns all rows with the
            # tags JSON column already parsed. Linear scan is fine for the
            # vault sizes the index supports today.
            scope_ids: list[str] = []
            for row in runtime.index.list_notes(limit=None):
                tags = row.get("tags") or []
                if tag in tags:
                    scope_ids.append(row["id"])
            if not scope_ids:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"no notes found with tag {tag!r}",
                )
        elif scope_type == "notes":
            scope_ids = list(req.note_ids)
            if not scope_ids:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="note_ids must be non-empty when scope_type='notes'",
                )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"unknown scope_type: {scope_type!r}",
            )

        notes_for_llm: list[tuple[str, str, str]] = []
        for nid in scope_ids:
            meta = runtime.index.get_note_meta(nid)
            if meta is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"note not found: {nid}",
                )
            path = Path(meta["path"])
            if not path.is_absolute():
                path = runtime.vault.notes_dir / path.name
            if not path.exists():
                raise HTTPException(
                    status_code=status.HTTP_410_GONE,
                    detail=f"note file missing on disk: {path}",
                )
            note = Note.from_file(path)
            notes_for_llm.append((note.id, note.title, note.body))

        try:
            questions = generate_quiz(runtime.llm, notes_for_llm, n=n)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"generation failed: {exc}",
            ) from exc

        session = QuizSession(
            id=new_id(),
            started_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            model=runtime.config.llm.model,
            scope_type=scope_type,
            scope_note_ids=[r[0] for r in notes_for_llm],
            scope_tag=req.tag if scope_type == "tag" else "",
            questions=questions,
        )
        _quiz_store_for(runtime).save(session)
        return _session_to_payload(session)

    @app.get("/api/quiz/{quiz_id}", response_model=QuizSessionPayload)
    def quiz_get(
        quiz_id: str,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> QuizSessionPayload:
        session = _quiz_store_for(runtime).load(quiz_id)
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"quiz not found: {quiz_id}",
            )
        return _session_to_payload(session)

    @app.post("/api/quiz/{quiz_id}/answer", response_model=QuizSessionPayload)
    def quiz_answer(
        quiz_id: str,
        req: QuizAnswerRequest,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> QuizSessionPayload:
        store = _quiz_store_for(runtime)
        session = store.load(quiz_id)
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"quiz not found: {quiz_id}",
            )
        if not 0 <= req.question_index < len(session.questions):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="question_index out of range",
            )
        q = session.questions[req.question_index]
        score, reason, missing = grade_answer(runtime.llm, q, req.user_answer)
        q.user_answer = req.user_answer
        q.ai_score = score
        q.ai_reason = reason
        q.ai_missing = missing
        store.save(session)
        return _session_to_payload(session)

    @app.post("/api/quiz/{quiz_id}/disagree", response_model=QuizSessionPayload)
    def quiz_disagree(
        quiz_id: str,
        req: QuizDisagreeRequest,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> QuizSessionPayload:
        """M7.4.2 disagreement loop. Records the user's mark + optional
        rationale; n_disagreement is reflected in the next aggregate."""
        store = _quiz_store_for(runtime)
        session = store.load(quiz_id)
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"quiz not found: {quiz_id}",
            )
        if not 0 <= req.question_index < len(session.questions):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="question_index out of range",
            )
        q = session.questions[req.question_index]
        q.user_disagrees = req.disagree
        q.user_disagree_reason = req.reason if req.disagree else ""
        store.save(session)
        return _session_to_payload(session)

    @app.post("/api/quiz/{quiz_id}/complete", response_model=QuizSessionPayload)
    def quiz_complete(
        quiz_id: str,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> QuizSessionPayload:
        from datetime import UTC, datetime

        store = _quiz_store_for(runtime)
        session = store.load(quiz_id)
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"quiz not found: {quiz_id}",
            )
        if not session.finished_at:
            session.finished_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        aggregate_score(session)
        store.save(session)
        return _session_to_payload(session)

    @app.post("/api/quiz/{quiz_id}/reflux", response_model=QuizSessionPayload)
    def quiz_reflux(
        quiz_id: str,
        req: QuizRefluxRequest,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> QuizSessionPayload:
        """M7.4.2 Cards reflux. Convert one quiz question into a Card.
        Defaults: front = question, back = (user's edited) reference,
        tags = source-note tags ∪ {quiz}. Idempotent: if the question
        already has a card_id_after_reflux, return without re-creating."""  # noqa: RUF002
        from knowlet.core.note import new_id

        store = _quiz_store_for(runtime)
        session = store.load(quiz_id)
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"quiz not found: {quiz_id}",
            )
        if not 0 <= req.question_index < len(session.questions):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="question_index out of range",
            )
        q = session.questions[req.question_index]
        if q.card_id_after_reflux:
            return _session_to_payload(session)

        front = (req.front or q.question).strip()
        back = (req.back or q.reference_answer).strip()
        # Default tags = union of source-Note tags + "quiz".
        if req.tags:
            tags = list(req.tags)
        else:
            tag_set: set[str] = {"quiz"}
            for sid in q.source_note_ids:
                meta = runtime.index.get_note_meta(sid)
                if meta:
                    tag_set.update(meta.get("tags") or [])
            tags = sorted(tag_set)

        card = Card(
            id=new_id(),
            type="qa",
            front=front,
            back=back,
            tags=tags,
            fsrs_state=initial_state(),
            source_note_id=q.source_note_ids[0] if q.source_note_ids else None,
        )
        runtime.ctx.cards.save(card)
        q.card_id_after_reflux = card.id
        # Update aggregate so cards_created reflects the new mark.
        aggregate_score(session)
        store.save(session)
        return _session_to_payload(session)

    # ---------------- cards ----------------

    def _summary(card: Card) -> CardSummary:
        return CardSummary(
            id=card.id,
            type=card.type,
            front=card.front,
            back=card.back,
            tags=card.tags,
            due=parse_due(card).isoformat(),
            state=card.fsrs_state.get("state"),
        )

    @app.get("/api/cards/due", response_model=list[CardSummary])
    def list_due(
        limit: int = 20,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> list[CardSummary]:
        return [_summary(c) for c in runtime.ctx.cards.list_due(limit=limit)]

    @app.post("/api/cards", response_model=CardSummary)
    def create_card(
        payload: CardCreate,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> CardSummary:
        if not payload.front.strip() or not payload.back.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="front and back are both required",
            )
        card = Card(
            type=payload.type,
            front=payload.front,
            back=payload.back,
            tags=payload.tags,
            source_note_id=payload.source_note_id,
            fsrs_state=initial_state(),
        )
        runtime.ctx.cards.save(card)
        return _summary(card)

    @app.get("/api/cards/{card_id}", response_model=CardFull)
    def get_card(
        card_id: str,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> CardFull:
        card = runtime.ctx.cards.get(card_id)
        if card is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"card not found: {card_id}",
            )
        return CardFull(
            id=card.id,
            type=card.type,
            front=card.front,
            back=card.back,
            tags=card.tags,
            source_note_id=card.source_note_id,
            created_at=card.created_at,
            updated_at=card.updated_at,
            due=parse_due(card).isoformat(),
            state=card.fsrs_state.get("state"),
            fsrs_state=card.fsrs_state,
        )

    @app.post("/api/cards/{card_id}/review", response_model=CardSummary)
    def review_card_endpoint(
        card_id: str,
        payload: CardReview,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> CardSummary:
        card = runtime.ctx.cards.get(card_id)
        if card is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"card not found: {card_id}",
            )
        schedule_next(card, payload.rating)
        runtime.ctx.cards.save(card)
        return _summary(card)

    # ---------------- mining tasks ----------------

    def _task_summary(t: MiningTask) -> TaskSummary:
        return TaskSummary(
            id=t.id,
            name=t.name,
            enabled=t.enabled,
            schedule=t.schedule.to_payload(),
            sources=[s.to_payload() for s in t.sources],
            updated_at=t.updated_at,
        )

    def _reload_scheduler() -> None:
        if state.scheduler is not None:
            state.scheduler.reload()

    @app.get("/api/mining/tasks", response_model=list[TaskSummary])
    def list_mining(runtime: ChatRuntime = Depends(runtime_dep)) -> list[TaskSummary]:
        return [_task_summary(t) for t in runtime.ctx.tasks.list()]

    @app.post("/api/mining/tasks", response_model=TaskFull)
    def create_mining(
        payload: TaskCreate,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> TaskFull:
        task = MiningTask(
            name=payload.name,
            enabled=payload.enabled,
            schedule=Schedule(**{k: v for k, v in payload.schedule.items() if v}),
            sources=[SourceSpec.parse(s) for s in payload.sources],
            prompt=payload.prompt,
            output_language=payload.output_language,
            body=payload.body,
        )
        problems = task.validate()
        if problems:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="; ".join(problems),
            )
        runtime.ctx.tasks.save(task)
        _reload_scheduler()
        return TaskFull(
            **_task_summary(task).model_dump(),
            prompt=task.prompt,
            body=task.body,
            created_at=task.created_at,
            output_language=task.output_language,
        )

    @app.get("/api/mining/tasks/{task_id}", response_model=TaskFull)
    def get_mining(
        task_id: str,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> TaskFull:
        t = runtime.ctx.tasks.get(task_id)
        if t is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"task not found: {task_id}",
            )
        return TaskFull(
            **_task_summary(t).model_dump(),
            prompt=t.prompt,
            body=t.body,
            created_at=t.created_at,
            output_language=t.output_language,
        )

    @app.put("/api/mining/tasks/{task_id}", response_model=TaskFull)
    def update_mining(
        task_id: str,
        payload: TaskCreate,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> TaskFull:
        existing = runtime.ctx.tasks.get(task_id)
        if existing is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"task not found: {task_id}",
            )
        existing.name = payload.name
        existing.enabled = payload.enabled
        existing.schedule = Schedule(**{k: v for k, v in payload.schedule.items() if v})
        existing.sources = [SourceSpec.parse(s) for s in payload.sources]
        existing.prompt = payload.prompt
        existing.output_language = payload.output_language
        existing.body = payload.body
        problems = existing.validate()
        if problems:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="; ".join(problems),
            )
        runtime.ctx.tasks.save(existing)
        _reload_scheduler()
        return TaskFull(
            **_task_summary(existing).model_dump(),
            prompt=existing.prompt,
            body=existing.body,
            created_at=existing.created_at,
            output_language=existing.output_language,
        )

    @app.delete("/api/mining/tasks/{task_id}")
    def delete_mining(
        task_id: str,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> dict[str, Any]:
        if not runtime.ctx.tasks.delete(task_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"task not found: {task_id}",
            )
        _reload_scheduler()
        return {"ok": True}

    @app.post("/api/mining/tasks/{task_id}/run")
    def run_mining_now(
        task_id: str,
        max_items: int | None = None,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> dict[str, Any]:
        t = runtime.ctx.tasks.get(task_id)
        if t is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"task not found: {task_id}",
            )
        report = run_task(
            t,
            runtime.vault,
            runtime.llm,
            drafts=runtime.ctx.drafts,
            default_output_language=runtime.config.general.language,
            max_items=max_items,
        )
        return report.to_dict()

    @app.post("/api/mining/run-all")
    def run_all_mining(
        max_items: int | None = None,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for t in runtime.ctx.tasks.list():
            if not t.enabled:
                continue
            report = run_task(
                t,
                runtime.vault,
                runtime.llm,
                drafts=runtime.ctx.drafts,
                default_output_language=runtime.config.general.language,
                max_items=max_items,
            )
            out.append(report.to_dict())
        return out

    @app.post("/api/mining/tasks/{task_id}/reset")
    def reset_mining_task(
        task_id: str,
        delete_drafts: bool = False,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> dict[str, Any]:
        """Clear the seen-set so the next run re-extracts everything.
        Optionally also delete drafts produced by this task.
        Useful for re-running with a different output_language / prompt."""
        t = runtime.ctx.tasks.get(task_id)
        if t is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"task not found: {task_id}",
            )
        return reset_task_state(
            runtime.vault, t.id, drafts=runtime.ctx.drafts, delete_drafts=delete_drafts
        )

    # ---------------- drafts ----------------

    def _draft_summary(d: Draft) -> DraftSummary:
        return DraftSummary(
            id=d.id,
            title=d.title,
            tags=d.tags,
            source=d.source,
            task_id=d.task_id,
            created_at=d.created_at,
            updated_at=d.updated_at,
        )

    @app.get("/api/drafts", response_model=list[DraftSummary])
    def list_drafts_endpoint(
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> list[DraftSummary]:
        return [_draft_summary(d) for d in runtime.ctx.drafts.all_drafts()]

    @app.get("/api/drafts/{draft_id}", response_model=DraftFull)
    def get_draft_endpoint(
        draft_id: str,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> DraftFull:
        d = runtime.ctx.drafts.get(draft_id)
        if d is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"draft not found: {draft_id}",
            )
        return DraftFull(**_draft_summary(d).model_dump(), body=d.body)

    @app.post("/api/drafts/{draft_id}/approve")
    def approve_draft_endpoint(
        draft_id: str,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> dict[str, Any]:
        d = runtime.ctx.drafts.get(draft_id)
        if d is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"draft not found: {draft_id}",
            )
        note = d.to_note()
        path = runtime.vault.write_note(note)
        note.path = path
        runtime.index.upsert_note(
            note,
            chunk_size=runtime.config.retrieval.chunk_size,
            chunk_overlap=runtime.config.retrieval.chunk_overlap,
        )
        runtime.ctx.drafts.delete(d.id)
        return {"note_id": note.id, "path": str(path)}

    @app.post("/api/drafts/{draft_id}/reject")
    def reject_draft_endpoint(
        draft_id: str,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> dict[str, Any]:
        if not runtime.ctx.drafts.delete(draft_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"draft not found: {draft_id}",
            )
        return {"ok": True}

    # ---------------- profile ----------------

    @app.get("/api/profile")
    def get_profile() -> dict[str, Any]:
        profile = read_profile(vault.profile_path)
        if profile is None:
            return {"exists": False}
        return {
            "exists": True,
            "name": profile.name,
            "body": profile.body,
            "updated_at": profile.updated_at,
            "created_at": profile.created_at,
        }

    @app.put("/api/profile", response_model=ProfilePayload)
    def put_profile(
        payload: ProfilePayload,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> ProfilePayload:
        existing = read_profile(vault.profile_path)
        profile = UserProfile(
            body=payload.body,
            name=payload.name,
            created_at=existing.created_at if existing else UserProfile(body="").created_at,
        )
        write_profile(vault.profile_path, profile)
        # Refresh runtime so the next chat turn sees the new profile.
        runtime.user_profile = profile
        from knowlet.chat.prompts import build_chat_system_prompt

        new_system = build_chat_system_prompt(profile.truncated_for_prompt())
        if runtime.session.history and runtime.session.history[0]["role"] == "system":
            runtime.session.history[0]["content"] = new_system
        return ProfilePayload(body=profile.body, name=profile.name)

    # ---------------- static UI ----------------

    if FRONTEND_DIST.exists():
        # Vite emits hashed bundles under `dist/assets/`. Mount that as a real
        # static dir; everything else falls through to the SPA index so deep
        # links + browser-refresh on a route work without a per-route handler.
        assets_dir = FRONTEND_DIST / "assets"
        if assets_dir.exists():
            app.mount(
                "/assets",
                StaticFiles(directory=assets_dir),
                name="assets",
            )

        @app.get("/")
        def index() -> FileResponse:
            return FileResponse(FRONTEND_DIST / "index.html")

        # SPA fallback. Anything that isn't /api/* / /assets/* / /files/*
        # gets index.html and lets React Router (Phase 1 B+) handle it.
        @app.get("/{full_path:path}")
        def spa_fallback(full_path: str) -> FileResponse:
            if (
                full_path.startswith("api/")
                or full_path.startswith("assets/")
                or full_path.startswith("files/")
            ):
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
            # Phase 1 B may serve favicon/manifest from `dist/` root.
            candidate = FRONTEND_DIST / full_path
            if candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(FRONTEND_DIST / "index.html")

    return app


def serve(host: str = "127.0.0.1", port: int = 8765) -> None:  # pragma: no cover
    """Start the web server. Auto-discovers the vault from CWD / KNOWLET_VAULT."""
    import uvicorn

    vault_root = find_vault()
    # Phase 2 E — wire audit log (4.B) + backup store (4.E) so the
    # live web server records events AND keeps prior bytes around
    # before each Note overwrite.
    from knowlet.core.audit_log import AuditEventStore
    from knowlet.core.backups import BackupStore

    vault = Vault(
        vault_root,
        audit_log=AuditEventStore(vault_root),
        backups=BackupStore(vault_root),
    )
    cfg = load_config(vault.root)
    if not cfg.llm.api_key:
        raise SystemExit(
            "LLM api_key is empty — run `knowlet config init` (or `config set llm.api_key …`)."
        )
    app = create_app(vault, cfg)
    uvicorn.run(app, host=host, port=port, log_level="info")
