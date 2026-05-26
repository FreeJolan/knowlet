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
from typing import Any, Literal

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
# models land alongside the new endpoints when each slice ships.


class ResolveMergeRequest(BaseModel):
    """S5 — body for ``POST /api/sync/resolve-merge/<note_id>``.
    Frontend sends the user's hand-merged text; backend writes it
    locally + force-pushes to Drive. Defined module-level so FastAPI
    treats it as a body model rather than a query-string class
    (closure-defined BaseModels regress to that, learned in 5.D)."""

    merged_text: str


class DevSeedConflictRequest(BaseModel):
    """Dev-only — body for ``POST /api/sync/dev-seed-conflict/<id>``.
    Optional ``remote_text`` lets the caller dictate the synthetic
    "other side"; absent / None falls back to ``_synth_remote`` which
    derives a divergent version from the local content. Module-level
    for the same FastAPI body-vs-query reason as ResolveMergeRequest."""

    remote_text: str | None = None


class LLMConfigUpdate(BaseModel):
    """Payload for PUT /api/llm/config (Phase 3 P3.0).

    All fields optional; only present ones are written. ``api_key``
    is special: empty string = "leave existing key intact" (so the
    UI never has to round-trip the secret); anything else = overwrite.

    The ``provider`` field used to be here but knowlet's actual LLM
    call only needs base_url + api_key + model; provider was a
    vestigial label, removed 2026-05-16 per user feedback.
    """

    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    max_tokens: int | None = None


class DraftUpdate(BaseModel):
    """Payload for PUT /api/drafts/{id} (Phase 3 Stage 3).

    All fields optional — only present ones are written. Lets the
    Drafts focus-mode editor fix typos / improve title / clean up
    AI-extracted body before the user approves. Per ADR-0029 §4
    原则 1: the user is the last-byte channel; pre-approve edits
    are the central case, not an edge case."""

    title: str | None = None
    body: str | None = None
    kind: Literal["knowledge", "reference"] | None = None


class NoteKindUpdate(BaseModel):
    """Payload for POST /api/notes/{id}/kind (Phase 3 Stage 2).

    Asymmetric upgrade per ADR-0029 §4.5: 资料 → 知识 (upgrade) is
    instant; 知识 → 资料 (downgrade) requires ``confirm=true`` — the
    UI surfaces a popover before sending. Module-level so FastAPI
    can resolve the body type.
    """

    kind: Literal["knowledge", "reference"]
    confirm: bool = False


# --------- Capture flow (Phase 3 Stage 3 — ADR-0009 amendment A2.1)


class CapturePayload(BaseModel):
    """A capsule of AI-processed material, ready for user decision.

    Stateless: the /capture/url + /capture/file endpoints return the
    full capsule; the frontend holds it and re-sends to /capture/decide.
    No server-side TTL store needed."""

    title: str
    body: str
    source: str | None = None
    hostname: str | None = None
    # True iff the page extracted but the summarize LLM step raised.
    # Frontend can render "(摘要失败 — 仅原始内容)" so the user is
    # informed and can still proceed.
    summary_failed: bool = False
    # When summary_failed=true, this is the underlying LLM error
    # message (truncated). Surfacing it in product lets the user
    # diagnose root cause (e.g. "Codex auth expired" / "rate
    # limited" / "model not found") instead of guessing.
    summary_error: str | None = None


class CaptureDecision(BaseModel):
    """User's three-way decision on a capsule (per ADR-0009 A2.2).

    - ``decision="knowledge"`` → write a Note with kind=knowledge to
      `notes/` (skips drafts queue per ADR-0009 A2.1: queue is the
      explicit-defer exception, not the default).
    - ``decision="reference"`` → write a Note with kind=reference to
      `notes/`.
    - ``decision="defer"`` → write a Draft to `drafts/` with the
      best-guess ``defer_kind`` (caller may pass; defaults to
      "reference" since most defers are URL/file captures).
    """

    capsule: CapturePayload
    decision: Literal["knowledge", "reference", "defer"]
    # Only used when decision == "defer"; sets the draft's kind so
    # the user can later see what they were thinking when they parked
    # it. Default reference (the majority case for capture).
    defer_kind: Literal["knowledge", "reference"] = "reference"


class CaptureDecisionResponse(BaseModel):
    decision: Literal["knowledge", "reference", "defer"]
    # Populated when decision is knowledge / reference — the new Note.
    note_id: str | None = None
    note_path: str | None = None
    # Populated when decision is defer — the new Draft.
    draft_id: str | None = None
    draft_path: str | None = None


class LLMProviderModelsRequest(BaseModel):
    """Optional draft credentials for POST /api/llm/provider-models.

    Used so the Settings UI can preview models **before saving** —
    fixes the chicken-and-egg where the user can't pick a model
    until they save creds, but can't save creds confidently until
    they see what models exist. Both fields fall back to the saved
    config if omitted / blank.
    """

    base_url: str | None = None
    api_key: str | None = None


class LLMTestRequest(BaseModel):
    """Optional draft credentials for POST /api/llm/test.

    Same motivation as :class:`LLMProviderModelsRequest`: the user
    types new values in the Settings form and naturally expects
    Test to verify **what they just typed**, not the still-saved
    old creds. Fields fall back to the saved config when omitted /
    blank."""

    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None


class SyncModeRequest(BaseModel):
    """#107b — body for ``PUT /api/sync/mode``. Validation is a
    closed three-way enum; backend re-validates so a malformed
    request can't poison sync_state."""

    mode: str


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


class NoteChatMessage(BaseModel):
    """One prior turn forwarded for conversation memory (A6)."""

    role: Literal["user", "assistant"]
    content: str


class NoteChatRequest(BaseModel):
    """Body for POST /api/chat/note/{note_id}/stream (Phase 3 Stage 4 P1).

    Note-anchored discussion. ``text`` is the user's message; the note's
    content is grounded server-side from ``note_id``. The AI infers its
    tone from the note's nature — there is no user-selected stance.
    ``history`` carries prior clean turns so the model has conversation
    memory (A6); the grounding rides in the current turn, not history."""

    text: str = Field(..., description="user message")
    history: list[NoteChatMessage] = Field(default_factory=list)


class NoteEditProposeRequest(BaseModel):
    """Body for POST /api/chat/note/{note_id}/propose-edit (Stage 4 P3).

    ``instruction`` is what the user wants changed (often distilled from
    the discussion). The AI proposes a minimal revision; the endpoint
    returns it as a diff and never writes — the user accepts in P4."""

    instruction: str = Field(..., description="what to change")


class NoteCheckRequest(BaseModel):
    """Body for POST /api/chat/note/{note_id}/check (Stage D).

    ``standard_answer`` is optional but preferred: it is the answer/key
    the note should be checked against. The endpoint returns a report
    only and never writes to the note.
    """

    standard_answer: str = ""
    instruction: str = ""


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
    # Phase 3 Stage 2 — ADR-0029 §4.5 知识 / 资料. Default "knowledge"
    # for legacy index rows that don't carry the column yet.
    kind: Literal["knowledge", "reference"] = "knowledge"


class NoteFull(NoteSummary):
    body: str
    # Task #108 — surfaces the lenient-read flag to the UI so the
    # NoteView can render a warning chip + auto-repair affordance.
    # Default "valid" keeps the field optional in JSON for clients
    # that haven't been updated yet.
    frontmatter_status: Literal["valid", "auto_filled", "corrupted"] = "valid"
    frontmatter_corruption: str | None = None


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
    # Phase 3 Stage 3 §3.3 — auto-pause visibility per ADR-0009 A2.3.
    # ``status`` = "running" | "paused-by-user" | "paused-by-backlog".
    # ``pending_drafts`` = live draft count for this task (so UI can
    # show "5 / 5 pending" next to the paused-by-backlog badge).
    status: Literal["running", "paused-by-user", "paused-by-backlog"] = "running"
    max_pending_drafts: int | None = 5
    pending_drafts: int = 0


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
    # Phase 3 Stage 3 — ADR-0029 §4.5 kind on drafts.
    kind: Literal["knowledge", "reference"] = "knowledge"
    # Phase 3 Stage 3 — age helpers computed server-side so the UI
    # doesn't re-derive timezone math (per ADR-0029 §4 原则 7
    # anti-drift visibility).
    age_days: int = 0
    is_stale: bool = False
    is_warn_age: bool = False
    # Phase 3 Stage 3 dogfood fix (2026-05-22) — include body in
    # summary so the focus-mode row can expand inline without a
    # follow-up GET /api/drafts/{id}. knowlet's soft-limit is 20
    # drafts so the payload stays small in practice.
    body: str = ""


class DraftFull(DraftSummary):
    """Same shape as DraftSummary now that body lives there. Kept
    as a distinct type for API back-compat."""


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
        # #107a — last preflight scan result. None means "never run".
        # The endpoint POSTs to refresh; the GET reads this without
        # re-scanning. React Query stale-times handle the cadence.
        self.preflight_report: Any | None = None
        self.preflight_ran_at: float | None = None
        # S4 — background drainer that pushes locally-dirty notes to
        # Drive. Instantiated by ``create_app`` after the helper
        # closures are defined; started by ``lifespan``.
        self.push_drainer: Any | None = None
        # #116 — in-flight OAuth state. ``state`` is one of:
        #   "idle"       — no flow has run this session
        #   "running"    — browser is open, waiting for user consent
        #   "connected"  — last flow completed; tokens on disk
        #   "error"      — last flow failed; ``oauth_last_error`` is set
        # The actual creds live on disk (.knowlet/sync_credentials.json);
        # this struct is just the in-memory snapshot of the most
        # recent attempt so the UI can show a spinner.
        self.oauth_flow_state: str = "idle"
        self.oauth_last_error: str | None = None
        self._oauth_thread: threading.Thread | None = None
        # #116 fix — monotonic counter so a cancelled OAuth thread
        # (which we can't actually kill — google_auth_oauthlib's
        # ``run_local_server`` doesn't expose a stop hook) can't
        # later overwrite the state of a newer attempt. Each
        # ``POST /api/sync/connect`` increments this; thread checks
        # before writing.
        self.oauth_session: int = 0

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

        # S4 (#112) — start the background push drainer if it was
        # configured by create_app. Idempotent. The drainer no-ops
        # while creds are absent and while the runtime hasn't
        # finished bootstrap, so start order is forgiving.
        if state.push_drainer is not None:
            state.push_drainer.start()
        try:
            yield
        finally:
            if state.push_drainer is not None:
                state.push_drainer.stop()
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

    # ---------------- per-note sync status (Slice S1 + S2) ----------------
    # Single seam the UI binds the per-note SyncStatusBadge to.
    # Returns one of {unauthenticated, offline, synced, dirty,
    # conflict} plus tooltip metadata. ~150ms per request when
    # connected (one Drive files.get round trip); the frontend
    # polls every 10s for the active note.
    #
    # S2 — silent auto-pull when safe. compute returns a sixth
    # internal state ``stale`` (revs differ + local clean). The
    # endpoint catches it, downloads remote, recomputes, and returns
    # ``synced`` — the UI never sees ``stale``. Real conflicts
    # (local dirty + remote moved) still surface as ``conflict``.
    @app.get("/api/sync/note-status/{note_id}")
    def get_note_sync_status(note_id: str) -> dict[str, Any]:
        from knowlet.core.sync.state import SyncStateStore
        from knowlet.core.sync.status import compute_note_sync_status

        store = SyncStateStore(vault.root)
        try:
            local_path = _resolve_note_local_path(note_id)
            status = compute_note_sync_status(
                vault_root=vault.root,
                note_id=note_id,
                state_store=store,
                local_path=local_path,
            )
            if status.state == "stale" and local_path is not None:
                # Safe to auto-pull: revs differ + local clean. Do
                # it inline so the frontend never has to. Worst case
                # (Drive errors mid-pull), the recompute below
                # returns the now-offline state and we degrade to
                # the badge showing offline.
                _auto_pull_stale(store, note_id, local_path)
                status = compute_note_sync_status(
                    vault_root=vault.root,
                    note_id=note_id,
                    state_store=store,
                    local_path=local_path,
                )
        finally:
            store.close()
        # Wire contract: only the five UI-visible states leave this
        # endpoint. ``stale`` is internal — if it survives the
        # auto-pull attempt above (couldn't resolve local_path, or
        # pull silently no-op'd), surface it as ``conflict`` so the
        # user at least sees a "something needs attention" signal
        # rather than a phantom state the frontend can't render.
        wire_state = status.state if status.state != "stale" else "conflict"
        return {
            "state": wire_state,
            "last_synced_at": status.last_synced_at,
            "drive_file_id": status.drive_file_id,
            "last_known_revision": status.last_known_revision,
            "current_drive_revision": status.current_drive_revision,
            "detail": status.detail,
        }

    # ---------------- explicit pull (Slice S2 primitive) -----------------
    # Surfaces ``pull_note_to_local`` as a callable — needed for
    # S3's open-time orchestrator (pull-many) and for any UI
    # affordance that wants a manual "fetch now" button. The
    # status endpoint already auto-pulls during routine polling;
    # this is the explicit handle.
    @app.post("/api/sync/note-pull/{note_id}")
    def pull_note_endpoint(note_id: str) -> dict[str, Any]:
        from knowlet.core.sync.credentials import (
            credentials_path,
            load_credentials,
        )
        from knowlet.core.sync.drive_client import DriveClient
        from knowlet.core.sync.pull import (
            PullStateMissingError,
            pull_note_to_local,
        )
        from knowlet.core.sync.state import SyncStateStore

        creds = load_credentials(credentials_path(vault.root))
        if creds is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="not authenticated to Drive",
            )
        local_path = _resolve_note_local_path(note_id)
        if local_path is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"note not found: {note_id}",
            )
        store = SyncStateStore(vault.root)
        try:
            try:
                result = pull_note_to_local(
                    service=DriveClient(creds).service(),
                    state=store,
                    note_id=note_id,
                    local_path=local_path,
                )
            except PullStateMissingError as exc:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=str(exc),
                ) from exc
        finally:
            store.close()
        return {
            "drive_file_id": result.drive_file_id,
            "new_revision": result.new_revision,
            "bytes": len(result.new_bytes),
        }

    def _resolve_note_local_path(note_id: str) -> Path | None:
        """Look up a note's on-disk path via the index. Returns
        ``None`` if the note isn't tracked or the resolved path
        doesn't exist — callers treat this as "no local file to
        compare against"."""
        try:
            runtime = state.runtime
        except Exception:
            return None
        if runtime is None:
            return None
        meta = runtime.index.get_note_meta(note_id)
        if meta is None:
            return None
        path = Path(meta["path"])
        if not path.is_absolute():
            path = runtime.vault.notes_dir / path.name
        return path if path.exists() else None

    def _auto_pull_stale(
        store: Any,  # SyncStateStore — kept loose to avoid a top-level import
        note_id: str,
        local_path: Path,
    ) -> None:
        """Best-effort auto-pull invoked from the status endpoint
        when state==stale. Failures are swallowed: the recompute
        afterwards will surface them as offline / conflict /
        unchanged-stale, whichever the new state actually is."""
        from knowlet.core.sync.credentials import (
            credentials_path,
            load_credentials,
        )
        from knowlet.core.sync.drive_client import DriveClient
        from knowlet.core.sync.pull import pull_note_to_local

        creds = load_credentials(credentials_path(vault.root))
        if creds is None:
            return
        try:
            pull_note_to_local(
                service=DriveClient(creds).service(),
                state=store,
                note_id=note_id,
                local_path=local_path,
            )
        except Exception:
            import logging as _logging

            _logging.getLogger(__name__).warning(
                "auto-pull failed for note %s",
                note_id,
                exc_info=True,
            )

    # ---------------- merge editor (Slice S5) -----------------------
    # The conflict-bundle endpoint hands the frontend everything it
    # needs to render the side-by-side merge UI: local text, remote
    # text, and the revisions involved. resolve-merge accepts the
    # user's hand-merged result, force-pushes it, and writes locally.
    # Drive's version history (30 days) keeps both pre-merge versions
    # recoverable if the merge needs unwinding.

    @app.get("/api/sync/conflict-bundle/{note_id}")
    def get_conflict_bundle(note_id: str) -> dict[str, Any]:
        from knowlet.core.sync.credentials import (
            credentials_path,
            load_credentials,
        )
        from knowlet.core.sync.drive_client import DriveClient
        from knowlet.core.sync.files import (
            DriveFile,
            download_file,
            get_file_metadata,
        )
        from knowlet.core.sync.state import SyncStateStore
        from knowlet.core.sync.status import DEV_FAKE_DRIVE_FILE_ID

        local_path = _resolve_note_local_path(note_id)
        if local_path is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"note not found: {note_id}",
            )
        store = SyncStateStore(vault.root)
        try:
            record = store.get_file_state("note", note_id)
        finally:
            store.close()
        if record is None or not record.drive_file_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"no Drive id tracked for note {note_id}",
            )

        # S5.5: bundle returns BODY only — frontmatter is decided
        # by rules in resolve_merge_endpoint, not by the user. Both
        # branches parse via Note.from_text so the diff stays free
        # of mechanical churn (updated_at / schema_version / tag
        # reformatting), eliminating the false-conflict noise the
        # user flagged in dogfood.

        # Dev seed-conflict short-circuit: read the fake remote text
        # from disk, fabricate metadata, skip Drive entirely.
        if record.drive_file_id == DEV_FAKE_DRIVE_FILE_ID:
            fake_path = _dev_conflict_path(note_id)
            if not fake_path.exists():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="dev conflict seed missing on disk",
                )
            try:
                local_raw = local_path.read_text(encoding="utf-8")
            except OSError as exc:
                raise HTTPException(
                    status_code=status.HTTP_410_GONE,
                    detail=f"local file read failed: {exc!r}",
                ) from exc
            remote_raw = fake_path.read_text(encoding="utf-8")
            mine_note = Note.from_text(local_raw, path=local_path)
            theirs_note = Note.from_text(remote_raw)
            local_modified_at: str | None
            try:
                local_modified_at = _iso(local_path.stat().st_mtime)
            except OSError:
                local_modified_at = None
            return {
                "note_id": note_id,
                "drive_file_id": record.drive_file_id,
                "local_text": mine_note.body,
                "remote_text": theirs_note.body,
                "current_drive_revision": "dev-rev-new",
                "last_known_revision": record.last_known_etag,
                "local_modified_at": local_modified_at,
                "remote_modified_at": _iso(fake_path.stat().st_mtime),
                "remote_modified_by": "dev seed (synthetic)",
            }

        creds = load_credentials(credentials_path(vault.root))
        if creds is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="not authenticated to Drive",
            )

        service = DriveClient(creds).service()
        try:
            remote_meta: DriveFile = get_file_metadata(
                service, record.drive_file_id
            )
            remote_bytes = download_file(service, record.drive_file_id)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Drive fetch failed: {exc!r}",
            ) from exc

        try:
            local_raw = local_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail=f"local file read failed: {exc!r}",
            ) from exc
        try:
            remote_raw = remote_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=f"remote bytes are not utf-8: {exc!r}",
            ) from exc

        mine_note = Note.from_text(local_raw, path=local_path)
        theirs_note = Note.from_text(remote_raw)

        # Human-readable timestamps + author for the merge editor's
        # column headers (S5 v2). The frontend turns these into
        # "you · 14:32 on this MacBook" vs "drive · 17:08 by alice"
        # — opaque revision ids alone leave users guessing which
        # side is which.
        try:
            local_modified_at = _iso(local_path.stat().st_mtime)
        except OSError:
            local_modified_at = None

        return {
            "note_id": note_id,
            "drive_file_id": record.drive_file_id,
            "local_text": mine_note.body,
            "remote_text": theirs_note.body,
            "current_drive_revision": remote_meta.head_revision_id,
            "last_known_revision": record.last_known_etag,
            "local_modified_at": local_modified_at,
            "remote_modified_at": remote_meta.modified_time,
            "remote_modified_by": remote_meta.last_modifying_user_display_name,
        }

    @app.post("/api/sync/resolve-merge/{note_id}")
    def resolve_merge_endpoint(
        note_id: str, body: ResolveMergeRequest
    ) -> dict[str, Any]:
        from knowlet.core.sync.credentials import (
            credentials_path,
            load_credentials,
        )
        from knowlet.core.sync.drive_client import DriveClient
        from knowlet.core.sync.files import download_file
        from knowlet.core.sync.frontmatter_merge import merge_notes
        from knowlet.core.sync.push import resolve_with_merge
        from knowlet.core.sync.state import SyncStateStore
        from knowlet.core.sync.status import DEV_FAKE_DRIVE_FILE_ID

        local_path = _resolve_note_local_path(note_id)
        if local_path is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"note not found: {note_id}",
            )
        store = SyncStateStore(vault.root)
        try:
            record = store.get_file_state("note", note_id)
            if record is None or not record.drive_file_id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"no Drive id tracked for note {note_id}",
                )

            # S5.5: the user's merged_text is BODY only. Re-parse mine
            # + theirs at save time so the rule-based frontmatter
            # merge sees the freshest sides (theirs may have moved
            # between bundle-time and save-time). The composed file
            # hits disk + Drive with a clean serialized frontmatter
            # via Note.to_markdown.
            try:
                local_raw = local_path.read_text(encoding="utf-8")
            except OSError as exc:
                raise HTTPException(
                    status_code=status.HTTP_410_GONE,
                    detail=f"local file read failed: {exc!r}",
                ) from exc
            mine_note = Note.from_text(local_raw, path=local_path)

            # Dev seed-conflict path: write the merged result locally,
            # delete the synthetic remote bytes + the sync_state row.
            # The note returns to a clean local-only state (badge will
            # show "dirty" if something else later syncs it).
            if record.drive_file_id == DEV_FAKE_DRIVE_FILE_ID:
                fake_path = _dev_conflict_path(note_id)
                if not fake_path.exists():
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="dev conflict seed missing on disk",
                    )
                theirs_note = Note.from_text(
                    fake_path.read_text(encoding="utf-8")
                )
                merged_note = merge_notes(
                    mine=mine_note,
                    theirs=theirs_note,
                    merged_body=body.merged_text,
                )
                # Force the URL id back on (mirrors the repair path) —
                # corrupted-frontmatter sides synthesize fresh ULIDs;
                # the canonical handle is whatever the user clicked.
                merged_note.id = note_id
                merged_bytes = merged_note.to_markdown().encode("utf-8")
                tmp = local_path.with_suffix(local_path.suffix + ".tmp")
                tmp.write_bytes(merged_bytes)
                tmp.replace(local_path)
                _dev_conflict_clear(store, note_id)
                _drop_from_preflight(note_id)
                return {
                    "drive_file_id": DEV_FAKE_DRIVE_FILE_ID,
                    "new_revision": "dev-resolved",
                }

            creds = load_credentials(credentials_path(vault.root))
            if creds is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="not authenticated to Drive",
                )
            service = DriveClient(creds).service()
            try:
                remote_bytes = download_file(service, record.drive_file_id)
            except Exception as exc:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Drive fetch failed: {exc!r}",
                ) from exc
            try:
                remote_raw = remote_bytes.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise HTTPException(
                    status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                    detail=f"remote bytes are not utf-8: {exc!r}",
                ) from exc
            theirs_note = Note.from_text(remote_raw)
            merged_note = merge_notes(
                mine=mine_note,
                theirs=theirs_note,
                merged_body=body.merged_text,
            )
            merged_note.id = note_id
            merged_bytes = merged_note.to_markdown().encode("utf-8")
            try:
                result = resolve_with_merge(
                    service=service,
                    state=store,
                    note_id=note_id,
                    drive_file_id=record.drive_file_id,
                    local_path=local_path,
                    merged_bytes=merged_bytes,
                )
            except Exception as exc:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"merge push failed: {exc!r}",
                ) from exc
        finally:
            store.close()
        _drop_from_preflight(note_id)
        return {
            "drive_file_id": result.drive_file.id,
            "new_revision": result.drive_file.head_revision_id,
        }

    # ---------------- dev seed-conflict (real-vault dogfood) -------
    # Lets a developer manufacture a conflict against their own
    # vault content without setting up Drive auth. Writes a fake
    # "remote" text to .knowlet/dev_conflicts/<id>.md and stamps
    # sync_state with the DEV_FAKE_DRIVE_FILE_ID sentinel; the
    # status / bundle / resolve endpoints read that sentinel and
    # serve the fake data instead of calling Drive.
    #
    # NOT a production feature; it's wired unconditionally for now
    # because the operations are idempotent + reversible (DELETE
    # endpoint cleans everything up). Gate behind an env var if it
    # ever leaves the developer-tools box.

    @app.post("/api/sync/dev-seed-conflict/{note_id}")
    def dev_seed_conflict(
        note_id: str,
        body: DevSeedConflictRequest | None = Body(default=None),
    ) -> dict[str, Any]:
        from knowlet.core.sync.state import FileState, SyncStateStore
        from knowlet.core.sync.status import DEV_FAKE_DRIVE_FILE_ID

        local_path = _resolve_note_local_path(note_id)
        if local_path is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"note not found: {note_id}",
            )
        try:
            local_text = local_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail=f"local file unreadable: {exc!r}",
            ) from exc
        remote_text = (body.remote_text if body else None) or _synth_remote(
            local_text
        )

        fake_path = _dev_conflict_path(note_id)
        fake_path.parent.mkdir(parents=True, exist_ok=True)
        fake_path.write_text(remote_text, encoding="utf-8")

        # Backdate the local file's mtime so the dirty-detector reads
        # "no local edits since last sync" — this is the canonical
        # conflict shape (revs differ + local clean would be 'stale'
        # and auto-pull, but DEV_FAKE short-circuits before reaching
        # that branch). For Carol-style conflicts (local dirty +
        # remote moved) the user can edit the note after seeding.
        store = SyncStateStore(vault.root)
        try:
            store.upsert_file_state(
                FileState(
                    entity_type="note",
                    entity_id=note_id,
                    drive_file_id=DEV_FAKE_DRIVE_FILE_ID,
                    last_known_etag="dev-rev-old",
                    last_synced_at="2020-01-01T00:00:00Z",
                    dirty=False,
                )
            )
        finally:
            store.close()
        _invalidate_preflight_cache()
        return {
            "note_id": note_id,
            "remote_text_lines": len(remote_text.split("\n")),
            "remote_path": str(fake_path),
        }

    # ---------------- dev real-Drive simulators ---------------------
    # Single-device dogfood helpers. drive.appdata scope hides files
    # from Drive web UI, so the natural "edit on the other side" loop
    # is impossible without a second machine — these endpoints make
    # it possible. Both use the user's real Drive credentials; they
    # don't fake anything at the knowlet layer.

    @app.post("/api/sync/dev-simulate-remote-edit/{note_id}")
    def dev_simulate_remote_edit(note_id: str) -> dict[str, Any]:
        """Carol-persona conflict in a single endpoint.

        Bumps the Drive copy with a "remote-side" marker AND appends
        a "local-side" marker to the local file + flips sync_state
        dirty. Without the local-side change, S2's auto-pull would
        silently merge the remote edit into the clean local file
        (its job!) and the user never sees a conflict — the dev
        simulator has to fake BOTH sides moving concurrently to
        exercise the merge editor.

        The ``last_known_etag`` stays pointed at the pre-simulate
        revision, so the next drainer tick's push hits 412 → real
        ConflictReport → chip lights up + merge dialog opens.
        """
        import os

        from knowlet.core.note import now_iso
        from knowlet.core.sync.credentials import (
            credentials_path,
            load_credentials,
        )
        from knowlet.core.sync.drive_client import DriveClient
        from knowlet.core.sync.files import download_file, force_overwrite
        from knowlet.core.sync.state import FileState, SyncStateStore

        creds = load_credentials(credentials_path(vault.root))
        if creds is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="not authenticated to Drive",
            )
        store = SyncStateStore(vault.root)
        try:
            rec = store.get_file_state("note", note_id)
        finally:
            store.close()
        if rec is None or not rec.drive_file_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="note has never been pushed to Drive",
            )
        local_path = _resolve_note_local_path(note_id)
        if local_path is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="local file not found",
            )
        service = DriveClient(creds).service()
        current = download_file(service, rec.drive_file_id).decode(
            "utf-8", errors="replace"
        )
        ts = now_iso()

        # Side 1 — remote-side edit
        remote_injected = (
            current.rstrip()
            + "\n\n[remote-side edit simulated at "
            + ts
            + " — pretend a coworker added this paragraph from another device]\n"
        )
        df = force_overwrite(
            service,
            file_id=rec.drive_file_id,
            content=remote_injected.encode("utf-8"),
        )

        # Side 2 — local-side edit. Read the on-disk file (which
        # might be the same as ``current`` if local hadn't been
        # touched, OR might have user edits we want to preserve).
        # Append a distinguishable marker so the merge editor's
        # left pane shows something the right pane doesn't.
        try:
            local_text = local_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail=f"local file read failed: {exc!r}",
            ) from exc
        local_injected = (
            local_text.rstrip()
            + "\n\n[local-side edit simulated at "
            + ts
            + " — pretend you wrote this paragraph on the local device]\n"
        )
        # Atomic write to mirror what Vault.write_note does.
        tmp = local_path.with_suffix(local_path.suffix + ".tmp")
        tmp.write_text(local_injected, encoding="utf-8")
        tmp.replace(local_path)
        # Bump mtime so ``_is_local_dirty`` reads True — kills any
        # chance of S2 misclassifying this as ``stale``.
        os.utime(local_path, None)

        # Mark dirty so the drainer tries to push; KEEP
        # ``last_known_etag`` at its pre-simulate value so that push
        # hits 412 against the bumped Drive revision.
        store = SyncStateStore(vault.root)
        try:
            store.upsert_file_state(
                FileState(
                    entity_type="note",
                    entity_id=note_id,
                    drive_file_id=rec.drive_file_id,
                    last_known_etag=rec.last_known_etag,  # stale on purpose
                    last_synced_at=rec.last_synced_at,
                    dirty=True,
                )
            )
        finally:
            store.close()

        _invalidate_preflight_cache()
        return {
            "drive_file_id": df.id,
            "remote_new_revision": df.head_revision_id,
            "local_bytes": len(local_injected),
            "hint": (
                "next drainer tick (≤5s) or POST /api/sync/drain-now → "
                "412 → chip should light up amber"
            ),
        }

    @app.post("/api/sync/dev-cleanup-orphan-sync-rows")
    def dev_cleanup_orphan_sync_rows() -> dict[str, Any]:
        """Walk sync_state, delete rows whose entity_id isn't in the
        index. Also delete the corresponding Drive files (they're
        unreachable from knowlet's note browser anyway). Used to
        recover from the corrupted-frontmatter id-regeneration bug
        that fanned out phantom rows pre-fix."""
        from knowlet.core.sync.credentials import (
            credentials_path,
            load_credentials,
        )
        from knowlet.core.sync.drive_client import DriveClient
        from knowlet.core.sync.state import SyncStateStore

        creds = load_credentials(credentials_path(vault.root))
        runtime = state.runtime
        if runtime is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="runtime not ready",
            )
        index_ids = {n["id"] for n in runtime.index.list_notes()}
        store = SyncStateStore(vault.root)
        deleted_rows = 0
        deleted_drive = 0
        drive_errors: list[str] = []
        try:
            service: Any = None
            for fs in store.list_all_files():
                if fs.entity_type != "note":
                    continue
                if fs.entity_id in index_ids:
                    continue
                # Orphan. Drop the Drive file if we have one + creds.
                if fs.drive_file_id and creds is not None:
                    if service is None:
                        service = DriveClient(creds).service()
                    try:
                        service.files().delete(
                            fileId=fs.drive_file_id
                        ).execute()
                        deleted_drive += 1
                    except Exception as exc:
                        drive_errors.append(
                            f"{fs.entity_id}: {exc!r}"
                        )
                # Drop the sync_state row. SyncStateStore doesn't
                # expose a row delete, so we use raw SQL on the
                # underlying connection.
                conn = store._connect()
                conn.execute(
                    "DELETE FROM file_state "
                    "WHERE entity_type=? AND entity_id=?",
                    (fs.entity_type, fs.entity_id),
                )
                conn.commit()
                deleted_rows += 1
        finally:
            store.close()
        _invalidate_preflight_cache()
        return {
            "deleted_rows": deleted_rows,
            "deleted_drive_files": deleted_drive,
            "drive_errors": drive_errors[:5],
        }

    @app.post("/api/sync/dev-fake-other-device-heartbeat")
    def dev_fake_other_device_heartbeat() -> dict[str, Any]:
        """Plant a fake heartbeat for a synthetic second device in
        Drive appData. Next preflight reads it + the local device's
        own heartbeat → ``alive_devices`` count = 2 → Auto mode
        auto-promotes to Strict."""
        from knowlet.core.sync.credentials import (
            credentials_path,
            load_credentials,
        )
        from knowlet.core.sync.drive_client import DriveClient
        from knowlet.core.sync.heartbeat import write_my_heartbeat

        creds = load_credentials(credentials_path(vault.root))
        if creds is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="not authenticated to Drive",
            )
        service = DriveClient(creds).service()
        # Use a stable fake id so re-runs overwrite instead of
        # accumulating. The "fake" prefix makes it obviously not
        # a real device when inspecting Drive appData manually.
        fake_id = "01FAKEOTHERDEVICEDOGFOOD00"
        write_my_heartbeat(
            service,
            device_id=fake_id,
            device_label="fake-other-device (dogfood)",
        )
        _invalidate_preflight_cache()
        return {"fake_device_id": fake_id, "ok": True}

    @app.delete("/api/sync/dev-seed-conflict/{note_id}")
    def dev_seed_conflict_clear(note_id: str) -> dict[str, Any]:
        from knowlet.core.sync.state import SyncStateStore

        store = SyncStateStore(vault.root)
        try:
            _dev_conflict_clear(store, note_id)
        finally:
            store.close()
        _drop_from_preflight(note_id)
        return {"note_id": note_id, "cleared": True}

    def _dev_conflict_path(note_id: str) -> Path:
        return vault.root / ".knowlet" / "dev_conflicts" / f"{note_id}.md"

    def _dev_conflict_clear(store: Any, note_id: str) -> None:
        from knowlet.core.sync.state import FileState
        from knowlet.core.sync.status import DEV_FAKE_DRIVE_FILE_ID

        # Nuke the fake remote file.
        fake = _dev_conflict_path(note_id)
        try:
            fake.unlink()
        except FileNotFoundError:
            pass
        # Clear the sync_state row by overwriting with a no-op
        # (clearing drive_file_id sends the note back to "dirty"
        # on the next status poll, which is the right state for a
        # never-pushed note). We can't easily DELETE through the
        # store's upsert-only API; null out the fields instead.
        existing = store.get_file_state("note", note_id)
        if existing and existing.drive_file_id == DEV_FAKE_DRIVE_FILE_ID:
            store.upsert_file_state(
                FileState(
                    entity_type="note",
                    entity_id=note_id,
                    drive_file_id=None,
                    last_known_etag=None,
                    last_synced_at=None,
                    dirty=False,
                )
            )

    def _synth_remote(local_text: str) -> str:
        """Build a plausible synthetic remote text from the local
        text — inserts a fake remotely-added line at ~1/3 mark and,
        if the body is long enough, modifies a later line. The goal
        is a diff that has BOTH "added on the remote side" hunks
        and "modified on both sides" hunks so the merge editor's
        full surface gets exercised."""
        lines = local_text.split("\n") if local_text else [""]
        insert_at = max(1, len(lines) // 3)
        lines.insert(
            insert_at,
            "[remotely-added line — pretend a coworker added this on another device]",
        )
        if len(lines) > 7:
            target = min(len(lines) - 1, insert_at + 4)
            lines[target] = "[modified remotely] " + lines[target]
        return "\n".join(lines)

    # ---------------- preflight scan + conflicts inbox (#107a) -----
    # POST /api/sync/preflight runs the scan synchronously: per-note
    # status compute, auto-pull stale, return real-conflict + offline
    # lists. GET /api/sync/conflicts reads the cached result so the
    # always-mounted chip can poll cheaply without re-scanning.
    #
    # The cache lives on WebState. Resolve-merge / repair / push all
    # invalidate it on success so the chip count drops immediately
    # after the user resolves a conflict.

    @app.post("/api/sync/preflight")
    def preflight_endpoint() -> dict[str, Any]:
        import time as _time

        from knowlet.core.sync.credentials import (
            credentials_path,
            load_credentials,
        )
        from knowlet.core.sync.drive_client import DriveClient
        from knowlet.core.sync.preflight import preflight_scan
        from knowlet.core.sync.state import SyncStateStore

        runtime = state.runtime
        note_meta: Any
        note_path: Any
        if runtime is None:
            note_meta = lambda _id: None  # noqa: E731
            note_path = lambda _id: None  # noqa: E731
        else:
            note_meta = runtime.index.get_note_meta
            note_path = _resolve_note_local_path

        def service_factory() -> Any | None:
            creds = load_credentials(credentials_path(vault.root))
            if creds is None:
                return None
            return DriveClient(creds).service()

        store = SyncStateStore(vault.root)
        try:
            report = preflight_scan(
                vault_root=vault.root,
                state_store=store,
                note_meta_lookup=note_meta,
                note_path_lookup=note_path,
                auto_pull_service_factory=service_factory,
                materialize_drive_file=_materialize_drive_file,
                trash_local_for_drive_deleted=_trash_local_for_drive_deleted,
            )
        finally:
            store.close()
        state.preflight_report = report
        state.preflight_ran_at = _time.time()
        return _serialize_preflight(report, state.preflight_ran_at)

    @app.get("/api/sync/conflicts")
    def conflicts_endpoint() -> dict[str, Any]:
        report = state.preflight_report
        if report is None:
            # No scan has run yet — return an "empty + needs scan"
            # shape so the chip stays hidden until the first POST
            # /preflight comes back.
            return {
                "ran_at": None,
                "scanned": 0,
                "conflicts": [],
                "offline": [],
                "auto_pulled_ids": [],
                "synced_count": 0,
                "dirty_count": 0,
                "unauthenticated": False,
                "alive_devices": [],
                "cloned_from_drive_ids": [],
                "trashed_for_drive_delete_ids": [],
            }
        return _serialize_preflight(report, state.preflight_ran_at)

    def _serialize_preflight(report: Any, ran_at: float | None) -> dict[str, Any]:
        return {
            "ran_at": ran_at,
            "scanned": report.scanned,
            "conflicts": [
                {
                    "note_id": c.note_id,
                    "note_title": c.note_title,
                    "drive_file_id": c.drive_file_id,
                    "last_synced_at": c.last_synced_at,
                    "last_known_revision": c.last_known_revision,
                    "current_drive_revision": c.current_drive_revision,
                    "remote_modified_at": c.remote_modified_at,
                    "remote_modified_by": c.remote_modified_by,
                }
                for c in report.conflicts
            ],
            "offline": [
                {
                    "note_id": o.note_id,
                    "note_title": o.note_title,
                    "detail": o.detail,
                }
                for o in report.offline
            ],
            "auto_pulled_ids": list(report.auto_pulled_ids),
            "synced_count": report.synced_count,
            "dirty_count": report.dirty_count,
            "unauthenticated": report.unauthenticated,
            "alive_devices": list(report.alive_devices),
            "cloned_from_drive_ids": list(report.cloned_from_drive_ids),
            "trashed_for_drive_delete_ids": list(
                report.trashed_for_drive_delete_ids
            ),
        }

    def _invalidate_preflight_cache() -> None:
        """Nuke the cached preflight report — used after seeds /
        rescan-needed events. Don't use this after a single-note
        resolve; the empty-cache → empty-conflicts → modal-unmounts
        race in Strict mode flashes the modal away mid-resolve.
        Use ``_drop_from_preflight`` for surgical removals."""
        state.preflight_report = None
        state.preflight_ran_at = None

    def _mark_note_delete_intent(note_id: str, kind: str) -> None:
        """#118 — flag a note's sync_state row for Drive-side deletion
        by the drainer. ``kind`` must be ``"soft"`` (Drive trash,
        30-day grace) or ``"hard"`` (permanent). No-op if there's
        no Drive backing (never-pushed note → no Drive file to
        clean up).

        Doesn't go through ``upsert_file_state`` so we preserve the
        existing drive_file_id / etag the drainer needs at delete
        time."""
        from knowlet.core.sync.state import FileState, SyncStateStore
        from knowlet.core.sync.status import DEV_FAKE_DRIVE_FILE_ID

        if kind not in ("soft", "hard"):
            raise ValueError(f"delete intent must be soft|hard, got {kind!r}")
        store = SyncStateStore(vault.root)
        try:
            rec = store.get_file_state("note", note_id)
            if rec is None or not rec.drive_file_id:
                # Never pushed → nothing for the drainer to clean.
                # Drop the row entirely if it exists (orphan).
                if rec is not None:
                    store.remove_file_state("note", note_id)
                return
            if rec.drive_file_id == DEV_FAKE_DRIVE_FILE_ID:
                # Dev seed — pretend nothing to delete on Drive.
                store.remove_file_state("note", note_id)
                return
            store.upsert_file_state(
                FileState(
                    entity_type=rec.entity_type,
                    entity_id=rec.entity_id,
                    drive_file_id=rec.drive_file_id,
                    last_known_etag=rec.last_known_etag,
                    last_synced_at=rec.last_synced_at,
                    dirty=False,  # not a push — Drive delete instead
                    dismissed_until=rec.dismissed_until,
                    delete_intent=kind,
                )
            )
        finally:
            store.close()
        _invalidate_preflight_cache()

    def _unmark_note_delete_intent(note_id: str) -> None:
        """#118 — user restored a trashed note before the drainer
        propagated the trash to Drive. Clear the delete_intent
        flag; we'll keep the local file + Drive copy in sync via
        normal push."""
        from knowlet.core.sync.state import FileState, SyncStateStore

        store = SyncStateStore(vault.root)
        try:
            rec = store.get_file_state("note", note_id)
            if rec is None or rec.delete_intent is None:
                return
            store.upsert_file_state(
                FileState(
                    entity_type=rec.entity_type,
                    entity_id=rec.entity_id,
                    drive_file_id=rec.drive_file_id,
                    last_known_etag=rec.last_known_etag,
                    last_synced_at=rec.last_synced_at,
                    dirty=True,  # restore = something changed locally
                    dismissed_until=rec.dismissed_until,
                    delete_intent=None,
                )
            )
        finally:
            store.close()

    def _mark_note_dirty_for_push(note_id: str) -> None:
        """S4 + #117 — call after Vault.write_note. Marks the note's
        sync_state row dirty=True so the background drainer picks
        it up on the next tick.

        Three cases:
          - Existing row with drive_file_id → flip dirty=True
            (update path; drainer's update_file_conditional runs).
          - No row yet AND Drive auth present → CREATE row with
            drive_file_id=None, dirty=True (first-push path; drainer's
            upload_new_file runs). Fixes the "new notes never
            auto-push" bug.
          - No row + no Drive auth → no-op (sync not configured;
            saving notes locally is the local-only path).
          - Dev-seeded (DEV_FAKE_CONFLICT) → skip (no real Drive
            backing).

        Cheap (one SQLite UPDATE or INSERT); safe to call from
        every save."""
        from knowlet.core.sync.credentials import (
            credentials_path,
            load_credentials,
        )
        from knowlet.core.sync.state import FileState, SyncStateStore
        from knowlet.core.sync.status import DEV_FAKE_DRIVE_FILE_ID

        store = SyncStateStore(vault.root)
        try:
            rec = store.get_file_state("note", note_id)
            if rec is not None and rec.drive_file_id == DEV_FAKE_DRIVE_FILE_ID:
                return
            if rec is None:
                # #117 — new note. Only auto-track if Drive auth
                # exists (otherwise we'd pile up dirty rows that
                # never get a chance to push).
                creds = load_credentials(credentials_path(vault.root))
                if creds is None:
                    return
                store.upsert_file_state(
                    FileState(
                        entity_type="note",
                        entity_id=note_id,
                        drive_file_id=None,
                        last_known_etag=None,
                        last_synced_at=None,
                        dirty=True,
                    )
                )
                return
            if rec.dirty:
                return  # already queued
            store.upsert_file_state(
                FileState(
                    entity_type=rec.entity_type,
                    entity_id=rec.entity_id,
                    drive_file_id=rec.drive_file_id,
                    last_known_etag=rec.last_known_etag,
                    last_synced_at=rec.last_synced_at,
                    dirty=True,
                    dismissed_until=rec.dismissed_until,
                )
            )
        finally:
            store.close()

    def _mark_attachment_dirty_for_push(filename: str) -> None:
        """#121 — call after a fresh attachment lands on disk so the
        drainer picks it up on the next tick. Only registers when
        Drive auth is present (otherwise the row would pile up with
        no consumer). Attachments are immutable so the only state we
        ever write is the first-push row."""
        from knowlet.core.sync.credentials import (
            credentials_path,
            load_credentials,
        )
        from knowlet.core.sync.push import ATTACHMENT_ENTITY_TYPE
        from knowlet.core.sync.state import FileState, SyncStateStore

        creds = load_credentials(credentials_path(vault.root))
        if creds is None:
            return
        store = SyncStateStore(vault.root)
        try:
            existing = store.get_file_state(
                ATTACHMENT_ENTITY_TYPE, filename
            )
            if existing is not None:
                return  # already tracked; nothing to do
            store.upsert_file_state(
                FileState(
                    entity_type=ATTACHMENT_ENTITY_TYPE,
                    entity_id=filename,
                    drive_file_id=None,
                    last_known_etag=None,
                    last_synced_at=None,
                    dirty=True,
                )
            )
        finally:
            store.close()

    def _add_conflict_to_preflight(
        note_id: str, drive_file_id: str | None
    ) -> None:
        """S4 — drainer-discovered conflict callback. When a save-
        time push gets 412, the drainer calls this so the chip /
        Strict modal lights up within seconds of the push attempt
        rather than waiting up to 60s for the next manual preflight.

        If the cache is empty (no prior scan), seed a minimal
        report so the chip has SOMETHING to show. Otherwise, append
        to the existing conflicts list (idempotent — checks if the
        note is already in the list)."""
        from knowlet.core.sync.preflight import (
            PreflightConflict,
            PreflightReport,
        )

        rep = state.preflight_report
        new_conflict = PreflightConflict(
            note_id=note_id,
            note_title=_title_for_note(note_id),
            drive_file_id=drive_file_id,
            last_synced_at=None,
            last_known_revision=None,
            current_drive_revision=None,
            remote_modified_at=None,
            remote_modified_by=None,
        )
        if rep is None:
            state.preflight_report = PreflightReport(
                conflicts=[new_conflict],
                offline=[],
                auto_pulled_ids=[],
                synced_count=0,
                dirty_count=0,
                scanned=0,
                unauthenticated=False,
                alive_devices=[],
            )
            return
        if any(c.note_id == note_id for c in rep.conflicts):
            return
        state.preflight_report = PreflightReport(
            conflicts=[*rep.conflicts, new_conflict],
            offline=rep.offline,
            auto_pulled_ids=rep.auto_pulled_ids,
            synced_count=rep.synced_count,
            dirty_count=rep.dirty_count,
            scanned=rep.scanned,
            unauthenticated=rep.unauthenticated,
            alive_devices=rep.alive_devices,
        )

    def _title_for_note(note_id: str) -> str | None:
        runtime = state.runtime
        if runtime is None:
            return None
        meta = runtime.index.get_note_meta(note_id)
        if meta is None:
            return None
        title = meta.get("title")
        return str(title) if title else None

    def _drop_from_preflight(note_id: str) -> None:
        """Surgical removal of one note's conflict / offline rows
        from the cached preflight report. Used after resolve-merge,
        repair, dev-seed-clear so the chip / Strict modal sees the
        new count immediately without bouncing through an empty
        cache. Safe no-op if the cache is already missing or the
        note isn't in it.

        ``synced_count`` is bumped when the dropped row was a
        conflict (the resolve produced a synced note); offline
        drops don't bump it because the offline state was
        transient (no real status change happened)."""
        from knowlet.core.sync.preflight import PreflightReport

        rep = state.preflight_report
        if rep is None:
            return
        was_conflict = any(c.note_id == note_id for c in rep.conflicts)
        was_offline = any(o.note_id == note_id for o in rep.offline)
        if not was_conflict and not was_offline:
            return
        new_conflicts = [c for c in rep.conflicts if c.note_id != note_id]
        new_offline = [o for o in rep.offline if o.note_id != note_id]
        state.preflight_report = PreflightReport(
            conflicts=new_conflicts,
            offline=new_offline,
            auto_pulled_ids=list(rep.auto_pulled_ids),
            synced_count=rep.synced_count + (1 if was_conflict else 0),
            dirty_count=rep.dirty_count,
            scanned=rep.scanned,
            unauthenticated=rep.unauthenticated,
            alive_devices=rep.alive_devices,
        )

    # ---------------- Drive auth (connect / disconnect / status, #116)

    @app.get("/api/sync/auth-status")
    def auth_status() -> dict[str, Any]:
        """One snapshot of "is Drive connected, and if so as whom".
        The chip / Settings panel polls this so the user never has
        to drop to terminal to know the state."""
        from knowlet.core.sync.credentials import (
            credentials_path,
            load_credentials,
        )

        creds = load_credentials(credentials_path(vault.root))
        if creds is None:
            return {
                "connected": False,
                "user_email": None,
                "user_display_name": None,
                "connecting": state.oauth_flow_state == "running",
                "last_error": state.oauth_last_error,
            }
        return {
            "connected": True,
            "user_email": creds.user_email,
            "user_display_name": creds.user_display_name,
            "connecting": False,
            "last_error": None,
        }

    @app.post("/api/sync/connect")
    def connect_endpoint() -> dict[str, Any]:
        """Kick off the OAuth flow on a daemon thread. Returns
        immediately with state="running"; the UI polls
        ``/api/sync/auth-status`` until ``connecting=false``. The
        OAuth library opens the user's browser to Google's consent
        page; the local loopback HTTP server in the thread blocks
        until the callback arrives.

        Per #115 the embedded OAuth client is used unless
        ``sync.client_secrets_path`` is set + points at a real
        file (advanced-user escape hatch). No client config is
        required for the common case."""

        if state.oauth_flow_state == "running":
            return {"started": False, "reason": "already running"}

        cs_path, tok_path = _resolve_paths_for_oauth()

        # Capture the session counter at the moment we kick the
        # thread off. The thread only writes state back if it's
        # still the current attempt — protects against a stuck
        # zombie thread (e.g. user closed the browser tab; this
        # thread is now blocked on the loopback server forever)
        # overwriting a newer attempt's result when it eventually
        # times out.
        my_session = state.oauth_session + 1
        state.oauth_session = my_session

        def _runner() -> None:
            from knowlet.core.sync.oauth import (
                OAuthFlowError,
                run_connect_flow,
            )

            try:
                run_connect_flow(
                    client_secrets_path=cs_path,
                    save_to=tok_path,
                    port=0,
                )
                if state.oauth_session == my_session:
                    # The drainer's untracked-sweep handles the
                    # "I had notes before connecting" backlog on its
                    # next tick (≤5s). No work needed here beyond
                    # flipping state to connected.
                    state.oauth_flow_state = "connected"
                    state.oauth_last_error = None
            except OAuthFlowError as exc:
                if state.oauth_session == my_session:
                    state.oauth_flow_state = "error"
                    state.oauth_last_error = str(exc)
            except Exception as exc:
                if state.oauth_session == my_session:
                    state.oauth_flow_state = "error"
                    state.oauth_last_error = repr(exc)

        state.oauth_flow_state = "running"
        state.oauth_last_error = None
        thread = threading.Thread(
            target=_runner, daemon=True, name="knowlet-oauth-flow"
        )
        thread.start()
        state._oauth_thread = thread
        return {"started": True}

    @app.post("/api/sync/disconnect")
    def disconnect_endpoint() -> dict[str, Any]:
        """Clear the local tokens + reset sync_state. Per ADR-0027
        the local device_id is preserved so reconnecting from the
        same machine doesn't look like a new device."""
        from knowlet.core.sync.credentials import (
            delete_credentials,
        )
        from knowlet.core.sync.state import SyncStateStore

        _, tok_path = _resolve_paths_for_oauth()
        removed = delete_credentials(tok_path)
        store = SyncStateStore(vault.root)
        try:
            store.clear()
        finally:
            store.close()
        state.oauth_flow_state = "idle"
        state.oauth_last_error = None
        _invalidate_preflight_cache()
        return {"removed_token_file": removed}

    @app.post("/api/sync/cancel-connect")
    def cancel_connect_endpoint() -> dict[str, Any]:
        """User aborted the in-progress OAuth flow (typically by
        closing the browser tab). We can't actually kill the
        background thread — ``google_auth_oauthlib``'s
        ``run_local_server`` has no stop hook — so we bump the
        session counter and reset state. The stuck thread's eventual
        writes are guarded by a session check, so they become
        harmless no-ops if/when it ever unblocks (or after the
        300-second timeout we set in ``run_connect_flow``).
        """
        if state.oauth_flow_state != "running":
            return {"cancelled": False}
        state.oauth_session += 1
        state.oauth_flow_state = "idle"
        state.oauth_last_error = None
        return {"cancelled": True}

    def _resolve_paths_for_oauth() -> tuple[Path | None, Path]:
        """Same resolution as the CLI uses (knowlet/cli/sync.py
        ``_resolve_paths``). Kept local to the endpoint so the
        sync module doesn't need to depend on the CLI module."""
        from knowlet.core.sync.credentials import credentials_path

        cs = (
            getattr(config.sync, "client_secrets_path", "") or ""
        )
        cs_path: Path | None
        if cs:
            cs_path = Path(cs).expanduser()
            if not cs_path.is_absolute():
                cs_path = vault.root / cs_path
            if not cs_path.exists():
                cs_path = None
        else:
            cs_path = None
        tok_path = credentials_path(
            vault.root,
            getattr(config.sync, "token_path", "") or None,
        )
        return cs_path, tok_path

    # ---------------- sync mode (#107b) ---------------------------
    # User-selected behavior: auto / strict / lax. Strict mode shows
    # the conflicts list as a blocking modal in the UI; lax disables
    # the blocking; auto matches lax today and will auto-promote to
    # strict once cross-device heartbeats land (#107c). The
    # ``effective_mode`` field is the value the UI should react to —
    # for now equal to ``mode``; the auto-promotion path will diverge
    # the two when implemented.

    @app.get("/api/sync/mode")
    def get_sync_mode() -> dict[str, Any]:
        from knowlet.core.sync.state import SyncStateStore

        store = SyncStateStore(vault.root)
        try:
            mode = store.sync_mode()
        finally:
            store.close()
        # #111 — Auto mode auto-promotes to Strict when ≥2 alive
        # devices are seen in the cached preflight's heartbeat
        # scan. The promotion is transparent: the frontend reads
        # ``effective_mode`` and reacts to that. The Settings panel
        # shows ``device_count`` so the user knows why Auto behaves
        # like Strict.
        rep = state.preflight_report
        device_count = (
            len(rep.alive_devices) if rep is not None else 0
        )
        if mode == "auto":
            effective = "strict" if device_count >= 2 else "lax"
        else:
            effective = mode
        return {
            "mode": mode,
            "effective_mode": effective,
            "device_count": device_count,
        }

    @app.put("/api/sync/mode")
    def put_sync_mode(body: SyncModeRequest) -> dict[str, Any]:
        from knowlet.core.sync.state import SyncStateStore

        store = SyncStateStore(vault.root)
        try:
            try:
                store.set_sync_mode(body.mode)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=str(exc),
                ) from exc
            new_mode = store.sync_mode()
        finally:
            store.close()
        rep = state.preflight_report
        device_count = (
            len(rep.alive_devices) if rep is not None else 0
        )
        if new_mode == "auto":
            effective = "strict" if device_count >= 2 else "lax"
        else:
            effective = new_mode
        return {
            "mode": new_mode,
            "effective_mode": effective,
            "device_count": device_count,
        }

    # ---------------- first-push helpers (#113) ---------------------
    # Notes created before Drive auth was set up have no sync_state
    # row, so the drainer ignores them. The Settings UI exposes a
    # "Push all unpushed" button that calls these endpoints to bring
    # those notes into the sync_state, after which the drainer
    # handles them on its next tick (push_note's first-push path).

    @app.get("/api/sync/unpushed-status")
    def unpushed_status() -> dict[str, Any]:
        from knowlet.core.sync.credentials import (
            credentials_path,
            load_credentials,
        )
        from knowlet.core.sync.state import SyncStateStore

        creds = load_credentials(credentials_path(vault.root))
        if creds is None:
            return {"count": 0, "authenticated": False}
        runtime = state.runtime
        if runtime is None:
            return {"count": 0, "authenticated": True}
        store = SyncStateStore(vault.root)
        try:
            synced_ids = {
                fs.entity_id
                for fs in store.list_all_files()
                if fs.entity_type == "note" and fs.drive_file_id
            }
        finally:
            store.close()
        all_notes = runtime.index.list_notes()
        count = sum(1 for n in all_notes if n["id"] not in synced_ids)
        return {"count": count, "authenticated": True}

    @app.post("/api/sync/push-all-unpushed")
    def push_all_unpushed() -> dict[str, Any]:
        from knowlet.core.sync.credentials import (
            credentials_path,
            load_credentials,
        )
        from knowlet.core.sync.state import FileState, SyncStateStore

        creds = load_credentials(credentials_path(vault.root))
        if creds is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="not authenticated to Drive",
            )
        runtime = state.runtime
        if runtime is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="runtime not ready",
            )
        store = SyncStateStore(vault.root)
        queued = 0
        try:
            synced_ids = {
                fs.entity_id
                for fs in store.list_all_files()
                if fs.entity_type == "note" and fs.drive_file_id
            }
            for n in runtime.index.list_notes():
                if n["id"] in synced_ids:
                    continue
                # Queue for first-push: drive_file_id=None tells
                # push_note to take the upload_new_file path.
                store.upsert_file_state(
                    FileState(
                        entity_type="note",
                        entity_id=n["id"],
                        drive_file_id=None,
                        last_known_etag=None,
                        last_synced_at=None,
                        dirty=True,
                    )
                )
                queued += 1
        finally:
            store.close()
        # Don't tick_once() here — that would block this HTTP request
        # while the drainer uploads possibly hundreds of notes
        # sequentially. The daemon thread picks them up on its
        # normal 5s cadence; user sees the chip's "Drive activity"
        # over the next minute or two.
        return {"queued": queued}

    # ---------------- background push drainer (S4 / #112) -----------
    # Wires the helper closures defined above (note lookup, conflict
    # surfacer, synced clearer) into a daemon-thread drainer that
    # the lifespan starts after bootstrap kicks off. The drainer
    # itself is no-op while creds are absent or the runtime hasn't
    # finished indexing — so it's safe to instantiate even on a
    # fresh single-device vault.

    def _drainer_note_lookup(note_id: str) -> Any:
        runtime = state.runtime
        if runtime is None:
            return None
        path = _resolve_note_local_path(note_id)
        if path is None:
            return None
        try:
            note = runtime.vault.read_note(path)
        except Exception:
            return None
        # #120 — stamp the current vault folder so it round-trips
        # via Drive frontmatter. Empty string from ``folder_of``
        # maps to None (root).
        folder = runtime.vault.folder_of(path)
        note.folder = folder or None
        return note

    def _drainer_on_conflict(note_id: str, _report: Any) -> None:
        _add_conflict_to_preflight(note_id, _report.drive_file_id)

    def _materialize_drive_file(
        drive_file_id: str, brief: Any
    ) -> str | None:
        """#119 — pull a Drive file we've never seen, place it in
        the local vault, write the sync_state row + index. Returns
        the note id (or attachment filename, #121) on success, None
        if anything broke (caller logs)."""
        from knowlet.core.note import Note, now_iso
        from knowlet.core.sync.credentials import (
            credentials_path,
            load_credentials,
        )
        from knowlet.core.sync.drive_client import DriveClient
        from knowlet.core.sync.files import download_file
        from knowlet.core.sync.push import ATTACHMENT_ENTITY_TYPE
        from knowlet.core.sync.state import FileState, SyncStateStore

        runtime = state.runtime
        if runtime is None:
            return None
        creds = load_credentials(credentials_path(vault.root))
        if creds is None:
            return None
        service = DriveClient(creds).service()
        body = download_file(service, drive_file_id)
        # #121 — non-markdown files are attachments. Recognized by
        # filename extension since the appData folder is flat and
        # filenames are authoritative (notes are always ``<id>.md``;
        # attachments are ``<ulid>.<png|jpg|...>``).
        if brief.name and not brief.name.endswith(".md"):
            att_dir = runtime.vault.attachments_dir
            att_dir.mkdir(parents=True, exist_ok=True)
            target = att_dir / brief.name
            tmp = target.with_suffix(target.suffix + ".tmp")
            tmp.write_bytes(body)
            tmp.replace(target)
            store = SyncStateStore(vault.root)
            try:
                store.upsert_file_state(
                    FileState(
                        entity_type=ATTACHMENT_ENTITY_TYPE,
                        entity_id=brief.name,
                        drive_file_id=drive_file_id,
                        last_known_etag=brief.head_revision_id,
                        last_synced_at=now_iso(),
                        dirty=False,
                    )
                )
            finally:
                store.close()
            return brief.name
        try:
            raw = body.decode("utf-8")
        except UnicodeDecodeError:
            return None
        note = Note.from_text(raw)
        # If the Drive file's frontmatter was empty / corrupted, the
        # synthesized note.id won't be stable; for first-clone
        # purposes prefer the file's own name (Drive stores it as
        # ``<id>.md``).
        if (
            note.frontmatter_status != "valid"
            and brief.name
            and brief.name.endswith(".md")
        ):
            stem = brief.name[:-3]
            if stem:
                note.id = stem
        # Place into the vault honoring the ``folder`` frontmatter
        # field (#120). None → root.
        folder = note.folder
        try:
            written = runtime.vault.write_note(note, folder=folder)
        except ValueError:
            # Folder escaped vault root or similar — fall back to root.
            note.folder = None
            written = runtime.vault.write_note(note)
        # Update sync_state so future preflights treat this as
        # tracked. last_known_etag from the brief (cheap; we just
        # fetched the file so we know its head).
        store = SyncStateStore(vault.root)
        try:
            store.upsert_file_state(
                FileState(
                    entity_type="note",
                    entity_id=note.id,
                    drive_file_id=drive_file_id,
                    last_known_etag=brief.head_revision_id,
                    last_synced_at=now_iso(),
                    dirty=False,
                )
            )
        finally:
            store.close()
        runtime.index.upsert_note(
            note,
            chunk_size=runtime.config.retrieval.chunk_size,
            chunk_overlap=runtime.config.retrieval.chunk_overlap,
        )
        # Note: written is the path on disk; not needed to return.
        del written
        return note.id

    def _trash_local_for_drive_deleted(note_id: str) -> None:
        """#119 — Drive removed this note (another device deleted +
        synced before us). Move our local copy to trash + drop the
        sync_state row + index entry. We do NOT also mark
        delete_intent — Drive's already done that side."""
        from knowlet.core.sync.state import SyncStateStore

        runtime = state.runtime
        if runtime is None:
            return
        meta = runtime.index.get_note_meta(note_id)
        if meta is None:
            return
        path = Path(meta["path"])
        if not path.is_absolute():
            path = runtime.vault.notes_dir / path.name
        try:
            runtime.vault.trash_note(path)
        except (FileNotFoundError, ValueError):
            pass
        try:
            runtime.index.delete_note(note_id)
        except Exception:
            pass
        store = SyncStateStore(vault.root)
        try:
            store.remove_file_state("note", note_id)
        finally:
            store.close()

    @app.get("/api/sync/push-errors")
    def push_errors_endpoint() -> dict[str, Any]:
        """#122 — list notes whose recent push attempts have failed.
        The chip surfaces a red badge when this is non-empty so
        the user knows sync is silently broken (drainer would
        otherwise just keep retrying forever)."""
        if state.push_drainer is None:
            return {"errors": []}
        runtime = state.runtime
        errors = []
        for nid, info in state.push_drainer.failures.items():
            title = None
            if runtime is not None:
                meta = runtime.index.get_note_meta(nid)
                if meta is not None:
                    title = meta.get("title")
            errors.append(
                {
                    "note_id": nid,
                    "note_title": title,
                    "count": info.get("count", 0),
                    "last_error": info.get("last_error"),
                    "last_attempt_at": info.get("last_attempt_at"),
                }
            )
        return {"errors": errors}

    @app.post("/api/sync/drain-now")
    def drain_now_endpoint() -> dict[str, Any]:
        """Manual trigger — useful for tests + dogfood when you'd
        rather not wait the 5-second poll interval. Runs one tick
        synchronously and returns. The daemon thread keeps running
        in the background; this is just a "kick it now" handle."""
        if state.push_drainer is None:
            return {"ran": False, "reason": "drainer not configured"}
        state.push_drainer.tick_once()
        return {"ran": True}

    # Defined AFTER all the helper closures above so the drainer's
    # callbacks can close over them. Stored on state so lifespan can
    # start/stop it without threading the instance through the
    # whole closure scope.
    from knowlet.core.sync.drainer import PushDrainer

    def _drainer_untracked_sweep() -> list[tuple[str, str]]:
        """Tell the drainer about notes AND attachments that exist on
        disk but have no sync_state row yet (the "I added these
        before connecting Drive" backlog). Drainer fires this once
        after creds first become available and queues them for first
        push. Returns [] when the runtime isn't ready — the drainer
        will retry on the next reconnect cycle."""
        from knowlet.core.sync.push import ATTACHMENT_ENTITY_TYPE
        from knowlet.core.sync.state import SyncStateStore

        runtime = state.runtime
        if runtime is None:
            return []
        store = SyncStateStore(vault.root)
        try:
            tracked = {
                (fs.entity_type, fs.entity_id)
                for fs in store.list_all_files()
            }
        finally:
            store.close()
        out: list[tuple[str, str]] = [
            ("note", n["id"])
            for n in runtime.index.list_notes()
            if ("note", n["id"]) not in tracked
        ]
        # #121 — attachments living in ``notes/_attachments/``.
        # Filename is the entity_id (ULID + ext). We don't recurse;
        # the directory is flat by design.
        att_dir = runtime.vault.attachments_dir
        if att_dir.exists():
            for entry in att_dir.iterdir():
                if not entry.is_file():
                    continue
                if entry.name.startswith("."):
                    # Skip OS metadata (.DS_Store, etc).
                    continue
                key = (ATTACHMENT_ENTITY_TYPE, entry.name)
                if key in tracked:
                    continue
                out.append(key)
        return out

    def _drainer_attachment_lookup(filename: str) -> Path | None:
        """Resolve an attachment id (filename) to its on-disk path.
        Returns None if the file is gone (drainer drops the row)."""
        runtime = state.runtime
        if runtime is None:
            return None
        candidate = runtime.vault.attachments_dir / filename
        if not candidate.exists():
            return None
        return candidate

    state.push_drainer = PushDrainer(
        vault_root=vault.root,
        note_lookup=_drainer_note_lookup,
        attachment_lookup=_drainer_attachment_lookup,
        on_conflict=_drainer_on_conflict,
        on_synced=_drop_from_preflight,
        untracked_sweep=_drainer_untracked_sweep,
        poll_interval=5.0,
    )

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

    @app.post("/api/chat/note/{note_id}/stream")
    def chat_note_stream(
        note_id: str,
        req: NoteChatRequest,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> StreamingResponse:
        """SSE stream for a note-anchored discussion (Phase 3 Stage 4 P1).

        Cursor-style "chat about this note": the note's content is
        grounded into the system prompt so the user never re-explains
        context. Ephemeral per request like ask-once (per-note
        persistence lands in P6). Reuses ``user_turn_stream`` so the
        ChatEvent stream stays the single source of truth (ADR-0008).
        """
        from knowlet.chat.note_chat import (
            build_grounded_turn,
            build_note_chat_session,
        )

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

        session = build_note_chat_session(
            llm=runtime.session.llm,
            registry=runtime.session.registry,
            ctx=runtime.session.ctx,
        )
        # A6: seed prior clean turns so the model has conversation memory.
        for m in req.history:
            session.history.append({"role": m.role, "content": m.content})
        # Grounding + tone guidance ride in the CURRENT user turn (not
        # system) so they survive proxies that drop system messages
        # (dogfood 2026-05-25). The AI infers tone from the note's nature.
        grounded = build_grounded_turn(note, req.text)

        def event_source() -> Iterator[str]:
            try:
                for event in session.user_turn_stream(grounded):
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

    @app.post("/api/chat/note/{note_id}/propose-edit")
    def chat_note_propose_edit(
        note_id: str,
        req: NoteEditProposeRequest,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> dict[str, Any]:
        """Ask the AI for a minimal revision of a note (Stage 4 P3).

        Returns old + new body for the diff UI; does NOT write — the
        user accepts the diff in P4 (ADR-0029 原则 1, the user is the
        last byte). A malformed AI reply yields ``changed=false``,
        never a corrupted note.
        """
        from knowlet.chat.note_chat import propose_note_edit

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
        try:
            result = propose_note_edit(
                llm=runtime.session.llm,
                note=note,
                instruction=req.instruction,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"LLM error: {exc}",
            ) from exc
        return {
            "note_id": note_id,
            "old_body": result.old_body,
            "new_body": result.new_body,
            "changed": result.changed,
            "reason": result.reason,
        }

    @app.post("/api/chat/note/{note_id}/check")
    def chat_note_check(
        note_id: str,
        req: NoteCheckRequest,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> dict[str, Any]:
        """Stage D: check one note against a standard answer / key.

        This is deliberately report-only: no status flag, no body edit,
        no background scan. D2 uses each finding's ``fix_instruction`` to
        enter the existing propose-edit + diff-accept flow.
        """
        from knowlet.chat.note_check import check_note

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
        try:
            report = check_note(
                llm=runtime.session.llm,
                note=note,
                standard_answer=req.standard_answer,
                instruction=req.instruction,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"LLM error: {exc}",
            ) from exc
        return {
            "note_id": note_id,
            "summary": report.summary,
            "findings": [
                {
                    "severity": finding.severity,
                    "paragraph": finding.paragraph,
                    "quote": finding.quote,
                    "finding": finding.finding,
                    "why": finding.why,
                    "suggestion": finding.suggestion,
                    "fix_instruction": finding.fix_instruction,
                    "confidence": finding.confidence,
                }
                for finding in report.findings
            ],
        }

    @app.post("/api/chat/draft/{draft_id}/stream")
    def chat_draft_stream(
        draft_id: str,
        req: NoteChatRequest,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> StreamingResponse:
        """SSE stream for a draft-anchored digest discussion (Stage C3).

        A digest item is still a Draft while the user is deciding. We
        project it to Note shape only in memory, then reuse the same
        grounded note-chat generator so "chat about this" works before
        any write/promotion happens.
        """
        from knowlet.chat.note_chat import (
            build_grounded_turn,
            build_note_chat_session,
        )

        draft = runtime.ctx.drafts.get(draft_id)
        if draft is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"draft not found: {draft_id}",
            )
        note = draft.to_note()
        session = build_note_chat_session(
            llm=runtime.session.llm,
            registry=runtime.session.registry,
            ctx=runtime.session.ctx,
        )
        for m in req.history:
            session.history.append({"role": m.role, "content": m.content})
        grounded = build_grounded_turn(note, req.text)

        def event_source() -> Iterator[str]:
            try:
                for event in session.user_turn_stream(grounded):
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

    @app.post("/api/chat/draft/{draft_id}/propose-internalize")
    def chat_draft_propose_internalize(
        draft_id: str,
        req: NoteEditProposeRequest,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> dict[str, Any]:
        """Ask AI to draft a knowledge-note body from a digest Draft.

        Proposal only: this endpoint does not mutate the draft and does
        not create a Note. The UI accepts the diff, then explicitly
        updates/approves the draft as knowledge.
        """
        from knowlet.chat.note_chat import propose_draft_internalization

        draft = runtime.ctx.drafts.get(draft_id)
        if draft is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"draft not found: {draft_id}",
            )
        note = draft.to_note()
        try:
            result = propose_draft_internalization(
                llm=runtime.session.llm,
                note=note,
                instruction=req.instruction,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"LLM error: {exc}",
            ) from exc
        return {
            "note_id": draft_id,
            "old_body": result.old_body,
            "new_body": result.new_body,
            "changed": result.changed,
            "reason": result.reason,
        }

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
        # The URL id is the canonical handle (it's whatever the
        # index stamped this path with). For corrupted notes, the
        # in-memory ``note.id`` is freshly synthesized on each
        # ``Note.from_file`` call (the file's id field is
        # unreadable), so always trust the URL id over the file's.
        return NoteFull(
            id=note_id,
            title=note.title,
            path=str(path),
            tags=note.tags,
            aliases=list(note.aliases),
            source=note.source,
            created_at=note.created_at,
            updated_at=note.updated_at,
            body=note.body,
            kind=note.kind,
            frontmatter_status=note.frontmatter_status,
            frontmatter_corruption=note.frontmatter_corruption,
        )

    # ---------------- frontmatter repair (Task #108) ---------------
    # The user clicks "auto-repair" on the warning chip. We re-read
    # the file (which is still corrupted), keep the synthesized id /
    # title / timestamps Note.from_file derived, and write_note —
    # which atomically replaces the file via tmp+rename and backs up
    # the original via .knowlet/backups/ (ADR-0018). The repair is
    # therefore reversible: the user can fish the original out of
    # backups if the auto-repair guessed wrong.
    @app.post("/api/notes/{note_id}/repair-frontmatter", response_model=NoteFull)
    def repair_frontmatter(
        note_id: str,
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
        # Re-read directly — bypass Vault.read_note's auto-fill
        # path because that would silently materialize before we
        # see the corruption; we want the corrupted handle so we
        # can persist its synthesized fields explicitly.
        n = Note.from_file(path)
        if n.frontmatter_status != "corrupted":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"nothing to repair — note's frontmatter status is "
                    f"'{n.frontmatter_status}'"
                ),
            )
        # Drop the corruption marker; write_note will emit a clean
        # frontmatter on top of the salvaged body. Force the index's
        # canonical id back onto the in-memory Note — Note.from_file
        # synthesizes a fresh ULID for corrupted notes (the file's
        # id field is unreadable) so without this override the
        # repaired file would be written with a different id than
        # the one the user clicked through.
        n.id = note_id
        n.frontmatter_status = "valid"
        n.frontmatter_corruption = None
        runtime.vault.write_note(n)
        _mark_note_dirty_for_push(note_id)
        # Re-read from disk to confirm the canonical version + invalidate
        # any prior coupling. After repair the index row is stale —
        # refresh it so search / backlinks see the new title.
        canonical = runtime.vault.read_note(path)
        runtime.index.upsert_note(
            canonical,
            chunk_size=runtime.config.retrieval.chunk_size,
            chunk_overlap=runtime.config.retrieval.chunk_overlap,
        )
        return NoteFull(
            id=note_id,
            title=canonical.title,
            path=str(path),
            tags=canonical.tags,
            aliases=list(canonical.aliases),
            source=canonical.source,
            created_at=canonical.created_at,
            updated_at=canonical.updated_at,
            body=canonical.body,
            frontmatter_status=canonical.frontmatter_status,
            frontmatter_corruption=canonical.frontmatter_corruption,
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
        # #118 — propagate the trash to Drive on the next drainer
        # tick. soft = Drive's own 30-day trash (recoverable from
        # Drive web UI even if we lose track locally).
        _mark_note_delete_intent(note_id, "soft")
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
        # S4 — queue this note for the background push drainer.
        # No-op for never-pushed / dev-seeded notes; cheap otherwise.
        _mark_note_dirty_for_push(note.id)
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
        _mark_note_dirty_for_push(note.id)
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
            kind=note.kind,
        )

    # ---------- Note kind (Phase 3 Stage 2 — ADR-0029 §4.5) ----------

    @app.post("/api/notes/{note_id}/kind", response_model=NoteFull)
    def set_note_kind(
        note_id: str,
        payload: NoteKindUpdate,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> NoteFull:
        from knowlet.core.note import now_iso as _now_iso

        meta = runtime.index.get_note_meta(note_id)
        if meta is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"note not found: {note_id}",
            )
        path = Path(meta["path"])
        if not path.is_absolute():
            path = runtime.vault.notes_dir / path.name
        note = runtime.vault.read_note(path)
        # ADR-0029 §4.5: knowledge → reference is a downgrade. Reject
        # unless the caller explicitly opted in via confirm=true so
        # accidental clicks can't quietly demote.
        is_downgrade = note.kind == "knowledge" and payload.kind == "reference"
        if is_downgrade and not payload.confirm:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "demote_requires_confirm",
                    "message": (
                        "Demoting knowledge → reference requires "
                        "confirm=true (anti-drift guard, ADR-0029 §4.5)."
                    ),
                },
            )
        if note.kind != payload.kind:
            note.kind = payload.kind
            note.updated_at = _now_iso()
            folder = runtime.vault.folder_of(path) or None
            runtime.vault.write_note(note, folder=folder)
            _mark_note_dirty_for_push(note.id)
            runtime.index.upsert_note(
                note,
                chunk_size=runtime.config.retrieval.chunk_size,
                chunk_overlap=runtime.config.retrieval.chunk_overlap,
            )
        return NoteFull(
            id=note_id,
            title=note.title,
            path=str(path),
            folder=runtime.vault.folder_of(path),
            tags=list(note.tags),
            aliases=list(note.aliases),
            source=note.source,
            created_at=note.created_at,
            updated_at=note.updated_at,
            body=note.body,
            kind=note.kind,
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
        _mark_note_dirty_for_push(note.id)
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
        # #118 — if the note was soft-deleted but the drainer hasn't
        # propagated yet, cancel the deletion. Otherwise re-push so
        # Drive matches the now-live local file.
        _unmark_note_delete_intent(note.id)
        _mark_note_dirty_for_push(note.id)
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
                _unmark_note_delete_intent(note.id)
                _mark_note_dirty_for_push(note.id)
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
        # #118 — grab the note id from the trashed file's frontmatter
        # BEFORE we delete the file, so we can upgrade the sync_state
        # row from soft → hard delete (Drive-delete instead of
        # Drive-trash on the next drainer tick).
        purged_note_id = _note_id_in_trash(runtime, name)
        try:
            runtime.vault.purge_trashed(name)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        if purged_note_id:
            _mark_note_delete_intent(purged_note_id, "hard")
        return {"ok": True, "name": name}

    @app.delete("/api/trash")
    def empty_trash(runtime: ChatRuntime = Depends(runtime_dep)) -> dict[str, Any]:
        """Permanent-delete every entry in trash. No body needed."""
        purged = 0
        for path in list(runtime.vault.iter_trashed_paths()):
            purged_note_id = _note_id_in_trash(runtime, path.name)
            try:
                runtime.vault.purge_trashed(path.name)
                purged += 1
                if purged_note_id:
                    _mark_note_delete_intent(purged_note_id, "hard")
            except (ValueError, FileNotFoundError):
                continue
        return {"ok": True, "purged_count": purged}

    def _note_id_in_trash(runtime: ChatRuntime, name: str) -> str | None:
        """Read the trashed file's frontmatter to recover the note id
        (so the sync delete tombstone has the right key). Returns
        None if the file can't be read — caller carries on without
        Drive-side cleanup; the orphan row gets caught by the
        cleanup endpoint."""
        try:
            trash_path = runtime.vault.trash_dir / name
            if not trash_path.exists():
                return None
            note = Note.from_file(trash_path)
            return note.id
        except Exception:
            return None

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
        # #121 — register the new attachment in sync_state as dirty
        # so the drainer pushes it on its next tick. Same pattern as
        # _mark_note_dirty_for_push: no-op if Drive isn't connected
        # (drainer will see this row when creds appear).
        _mark_attachment_dirty_for_push(path.name)
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

    # ---------------- Stage 3 capture flow (ADR-0009 amendment A2) ----

    @app.post("/api/capture/url", response_model=CapturePayload)
    def capture_flow_url(
        req: UrlCaptureRequest,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> CapturePayload:
        """Stage 3 capture: fetch + summarize URL, return a capsule the
        frontend will pair with /capture/decide to commit.

        Differs from the older /api/url/capture (M7.2) which returned
        URL-attachment shape for chat. This returns a generic
        CapturePayload usable for the modal three-button flow."""
        from knowlet.core.url_capture import (
            ExtractionError,
            FetchError,
            _hostname,
            capture_url,
            fetch_and_extract,
        )

        url = (req.url or "").strip()
        if not url or not (
            url.startswith("http://") or url.startswith("https://")
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid url (must start with http:// or https://)",
            )
        try:
            cap = capture_url(url, runtime.llm)
            return CapturePayload(
                title=cap.title or url,
                body=cap.summary,
                source=cap.url,
                hostname=cap.hostname,
                summary_failed=False,
            )
        except FetchError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
            ) from exc
        except ExtractionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            # Page fetched, but summarize blew up. Return a capsule
            # with raw extracted text so the user can still triage.
            try:
                title, body = fetch_and_extract(url)
            except Exception:  # noqa: BLE001
                title, body = url, ""
            return CapturePayload(
                title=title or url,
                body=body or f"(摘要失败: {exc})",
                source=url,
                hostname=_hostname(url),
                summary_failed=True,
                summary_error=repr(exc)[:300],
            )

    @app.post("/api/capture/file", response_model=CapturePayload)
    async def capture_flow_file(
        file: UploadFile,
        _runtime: ChatRuntime = Depends(runtime_dep),
    ) -> CapturePayload:
        """Stage 3 capture: drag-dropped text / markdown file → capsule.

        Stage 3 ships with text + markdown support only; PDF parsing is
        deferred (per Stage 3 scope decision 2026-05-21). Unsupported
        types return 415."""
        name = file.filename or "file"
        suffix = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if suffix not in ("md", "markdown", "txt", "text"):
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=(
                    "Only .md / .txt files are supported in Stage 3. "
                    "PDF support is on the roadmap."
                ),
            )
        raw = await file.read()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("utf-8", errors="replace")
        # Markdown files often start with frontmatter or a leading
        # heading. Use the first H1/H2 line as title if present,
        # otherwise fall back to the filename stem.
        title = Path(name).stem
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("# ") or stripped.startswith("## "):
                title = stripped.lstrip("#").strip() or title
                break
        return CapturePayload(
            title=title,
            body=text,
            source=name,
            hostname=None,
            summary_failed=False,
        )

    @app.post("/api/capture/decide", response_model=CaptureDecisionResponse)
    def capture_flow_decide(
        req: CaptureDecision,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> CaptureDecisionResponse:
        """User's three-way decision on a capsule.

        Per ADR-0009 amendment A2.1, the Drafts queue is the explicit-
        defer exception, NOT the default destination. Knowledge and
        Reference both write straight to notes/. Only "defer" lands in
        drafts/."""
        from knowlet.core.drafts import Draft, DraftStore
        from knowlet.core.note import Note, new_id

        cap = req.capsule
        title = (cap.title or "untitled").strip() or "untitled"
        body = cap.body or ""

        if req.decision == "defer":
            store = DraftStore(runtime.vault.drafts_dir)
            d = Draft(
                id=new_id(),
                title=title,
                body=body,
                source=cap.source,
                kind=req.defer_kind,
            )
            path = store.save(d)
            return CaptureDecisionResponse(
                decision="defer",
                draft_id=d.id,
                draft_path=str(path),
            )

        # decision is knowledge | reference — write straight to notes/
        note = Note(
            id=new_id(),
            title=title,
            body=body,
            source=cap.source,
            kind=req.decision,
        )
        try:
            path = runtime.vault.write_note(note)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from exc
        _mark_note_dirty_for_push(note.id)
        runtime.index.upsert_note(
            note,
            chunk_size=runtime.config.retrieval.chunk_size,
            chunk_overlap=runtime.config.retrieval.chunk_overlap,
        )
        return CaptureDecisionResponse(
            decision=req.decision,
            note_id=note.id,
            note_path=str(path),
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
        # Phase 3 Stage 3 — count this task's live drafts so the UI
        # can show "N / max_pending_drafts" next to a paused-by-
        # backlog badge.
        try:
            pending = len(
                runtime_or_init_safe()
                .ctx.drafts.list_for_task(t.id)
            )
        except Exception:  # noqa: BLE001
            pending = 0
        return TaskSummary(
            id=t.id,
            name=t.name,
            enabled=t.enabled,
            schedule=t.schedule.to_payload(),
            sources=[s.to_payload() for s in t.sources],
            updated_at=t.updated_at,
            status=t.status,  # type: ignore[arg-type]
            max_pending_drafts=t.max_pending_drafts,
            pending_drafts=pending,
        )

    def runtime_or_init_safe() -> ChatRuntime:
        """``runtime_or_init`` may raise during early bootstrap. _task_summary
        is also called from contexts where that's OK; this wrapper isolates
        a possible NoneType error."""
        return app.state.web_state.runtime_or_init()

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
            kind=d.kind,
            age_days=d.age_days,
            is_stale=d.is_stale,
            is_warn_age=d.is_warn_age,
            body=d.body,
        )

    @app.get("/api/drafts", response_model=list[DraftSummary])
    def list_drafts_endpoint(
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> list[DraftSummary]:
        # Phase 3 Stage 3 — enforce 90-day age-archive on every list
        # so stale drafts don't accumulate. Cheap; only mutates state
        # when something actually crossed the threshold.
        runtime.ctx.drafts.enforce_age_archive()
        return [
            _draft_summary(d) for d in runtime.ctx.drafts.all_drafts()
        ]

    @app.get("/api/digest/drafts", response_model=list[DraftSummary])
    def list_digest_drafts_endpoint(
        period: Literal["today", "week", "all"] = "today",
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> list[DraftSummary]:
        """Drafts produced by Stage C digest sources only.

        C2 is a read-only digest inbox: today / this week cards. The
        source-of-truth remains DraftStore + MiningTask; this endpoint
        only filters the existing draft queue by tasks marked as digest
        sources, so regular mining drafts never leak into the digest UI.
        """
        from knowlet.core.digest import is_digest_task

        runtime.ctx.drafts.enforce_age_archive()
        digest_task_ids = {
            task.id for task in runtime.ctx.tasks.list() if is_digest_task(task)
        }

        def in_period(draft: Draft) -> bool:
            if period == "all":
                return True
            if period == "today":
                return draft.age_days == 0
            return draft.age_days < 7

        return [
            _draft_summary(d)
            for d in runtime.ctx.drafts.all_drafts()
            if d.task_id in digest_task_ids and in_period(d)
        ]

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
        return DraftFull(**_draft_summary(d).model_dump())

    @app.put("/api/drafts/{draft_id}", response_model=DraftFull)
    def update_draft_endpoint(
        draft_id: str,
        payload: DraftUpdate,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> DraftFull:
        """Edit a draft in place — title / body / kind. Per ADR-0029
        §4 原则 1, pre-approve refinement is a central path: AI's
        first pass isn't always the user's final text."""
        d = runtime.ctx.drafts.get(draft_id)
        if d is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"draft not found: {draft_id}",
            )
        if payload.title is not None:
            d.title = payload.title.strip() or d.title
        if payload.body is not None:
            d.body = payload.body
        if payload.kind is not None:
            d.kind = payload.kind
        runtime.ctx.drafts.save(d)
        return DraftFull(**_draft_summary(d).model_dump())

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
        _mark_note_dirty_for_push(note.id)
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

    # ---------------- favorites (Phase 2 D B1) ----------------

    def _list_favorites_enriched(
        runtime: ChatRuntime,
    ) -> list[dict[str, Any]]:
        """Return favorites with title metadata. Prunes ids that no
        longer point at a real note (silent self-cleanup)."""
        from knowlet.core.favorites import FavoritesStore

        store = FavoritesStore(vault_root=vault.root)
        existing = {n["id"] for n in runtime.index.list_notes()}
        valid_ids = store.list(existing_ids=existing)
        out: list[dict[str, Any]] = []
        for nid in valid_ids:
            meta = runtime.index.get_note_meta(nid)
            title = meta.get("title") if meta else None
            out.append({"id": nid, "title": title})
        return out

    @app.get("/api/favorites")
    def list_favorites(
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> dict[str, Any]:
        return {"favorites": _list_favorites_enriched(runtime)}

    @app.post("/api/favorites/{note_id}")
    def add_favorite(
        note_id: str,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> dict[str, Any]:
        from knowlet.core.favorites import FavoritesStore

        if runtime.index.get_note_meta(note_id) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"note {note_id} not found",
            )
        FavoritesStore(vault_root=vault.root).add(note_id)
        return {"favorites": _list_favorites_enriched(runtime)}

    @app.delete("/api/favorites/{note_id}")
    def remove_favorite(
        note_id: str,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> dict[str, Any]:
        from knowlet.core.favorites import FavoritesStore

        FavoritesStore(vault_root=vault.root).remove(note_id)
        return {"favorites": _list_favorites_enriched(runtime)}

    # ---------------- vault portability (Phase 2 E) ----------------

    @app.get("/api/vault/export")
    def vault_export_endpoint() -> FileResponse:
        """Generate a portable `.zip` of the vault and stream it back
        to the browser. Mirrors ``knowlet vault export`` (ADR-0018)."""
        import tempfile
        from datetime import datetime as _dt

        from knowlet.core.portability import build_export_archive

        stamp = _dt.now().strftime("%Y-%m-%d")
        filename = f"knowlet-vault-{stamp}.zip"
        # Stage the archive in a tempfile so we don't pollute the
        # vault directory with one-off export artifacts. FileResponse
        # streams it back to the client; we leave cleanup to OS temp
        # rotation (small enough to be fine — non-issue per dogfood
        # scale).
        tmp = Path(tempfile.mkstemp(suffix=".zip", prefix="kn-export-")[1])
        try:
            build_export_archive(vault_root=vault.root, output_path=tmp)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise
        return FileResponse(
            path=tmp,
            media_type="application/zip",
            filename=filename,
        )

    def _unpack_for_merge(tmp_path: Path) -> Path:
        """Unzip the uploaded archive to a temp dir and return the
        directory we'll walk. Lifecycle is the caller's
        responsibility — return value points at a path the caller
        must ``shutil_rmtree_safe`` after merging."""
        import tempfile
        import zipfile

        walk_root = Path(tempfile.mkdtemp(prefix="kn-import-merge-"))
        with zipfile.ZipFile(tmp_path, "r") as zf:
            zf.extractall(walk_root)
        return walk_root

    @app.post("/api/vault/import-preview")
    async def vault_import_preview(
        file: UploadFile = File(...),
    ) -> dict[str, Any]:
        """Dry-run an import: surface counts + per-note actions so
        the user sees the plan before committing.

        UI-level import is ALWAYS merge into the current vault
        (per dogfood 2026-05-12: users expect upload → notes show
        up here, not "a sibling vault was created somewhere"). For
        sibling-vault restore use ``knowlet vault import --mode
        restore`` on the CLI.
        """
        import tempfile

        from knowlet.core.portability import merge_directory

        tmp_path = Path(
            tempfile.mkstemp(suffix=".zip", prefix="kn-import-")[1]
        )
        tmp_path.write_bytes(await file.read())
        walk_root = _unpack_for_merge(tmp_path)
        try:
            existing_titles = _existing_note_titles(vault.root)
            existing_ids = _existing_note_ids(vault.root)
            # A knowlet-format export wraps notes in a top-level
            # ``notes/`` folder; merge from that subfolder if it
            # exists so we don't try to import .knowlet/* etc.
            walk_target = (
                walk_root / "notes" if (walk_root / "notes").is_dir() else walk_root
            )
            report = merge_directory(
                source_dir=walk_target,
                vault_root=vault.root,
                existing_titles=existing_titles,
                existing_ids=existing_ids,
                dry_run=True,
            )
            return _import_report_to_json(report)
        finally:
            shutil_rmtree_safe(walk_root)
            tmp_path.unlink(missing_ok=True)

    @app.post("/api/vault/import")
    async def vault_import_endpoint(
        file: UploadFile = File(...),
    ) -> dict[str, Any]:
        """Commit a merge import. Always lands new notes under
        ``imported/YYYY-MM-DD/`` of the current vault. ID collisions
        skip (the live note wins); title collisions get an
        ``(imported)`` suffix."""
        import tempfile

        from knowlet.core.portability import merge_directory

        tmp_path = Path(
            tempfile.mkstemp(suffix=".zip", prefix="kn-import-")[1]
        )
        tmp_path.write_bytes(await file.read())
        walk_root = _unpack_for_merge(tmp_path)
        try:
            existing_titles = _existing_note_titles(vault.root)
            existing_ids = _existing_note_ids(vault.root)
            walk_target = (
                walk_root / "notes" if (walk_root / "notes").is_dir() else walk_root
            )
            report = merge_directory(
                source_dir=walk_target,
                vault_root=vault.root,
                existing_titles=existing_titles,
                existing_ids=existing_ids,
                dry_run=False,
            )
        finally:
            shutil_rmtree_safe(walk_root)
            tmp_path.unlink(missing_ok=True)

        # Re-index so the new notes show up in tree / search.
        runtime = state.runtime
        if runtime is not None:
            from knowlet.core.embedding import make_backend
            from knowlet.core.index import Index, reindex_vault

            cfg = runtime.config
            backend = make_backend(
                cfg.embedding.backend,
                cfg.embedding.model,
                cfg.embedding.dim,
            )
            reindex_vault(
                runtime.vault.root,
                runtime.vault.db_path,
                backend,
                chunk_size=cfg.retrieval.chunk_size,
                chunk_overlap=cfg.retrieval.chunk_overlap,
                note_paths=list(runtime.vault.iter_note_paths()),
            )
            runtime.index = Index(runtime.vault.db_path, backend)
        return _import_report_to_json(report)

    def _existing_note_titles(vault_root: Path) -> list[str]:
        out: list[str] = []
        notes_dir = vault_root / "notes"
        if not notes_dir.exists():
            return out
        from knowlet.core.note import Note as _Note

        for p in notes_dir.rglob("*.md"):
            try:
                note = _Note.from_file(p)
            except Exception:  # noqa: BLE001
                continue
            if note.title:
                out.append(note.title)
        return out

    def _existing_note_ids(vault_root: Path) -> list[str]:
        """All note ids currently in the vault. Used to skip
        ID-collisions during import (so re-importing one's own
        backup doesn't create duplicates)."""
        out: list[str] = []
        notes_dir = vault_root / "notes"
        if not notes_dir.exists():
            return out
        from knowlet.core.note import Note as _Note

        for p in notes_dir.rglob("*.md"):
            try:
                note = _Note.from_file(p)
            except Exception:  # noqa: BLE001
                continue
            if note.id:
                out.append(note.id)
        return out

    def shutil_rmtree_safe(p: Path) -> None:
        import shutil as _shutil

        try:
            _shutil.rmtree(p)
        except FileNotFoundError:
            pass

    def _import_report_to_json(report: Any) -> dict[str, Any]:
        return {
            "mode": report.mode,
            "target_path": str(report.target_path),
            "notes_created": report.notes_created,
            "notes_skipped": report.notes_skipped,
            "notes_renamed": report.notes_renamed,
            "attachments_copied": report.attachments_copied,
            "dry_run": report.dry_run,
            "items": [
                {"source": s, "action": a, "final": f}
                for (s, a, f) in (report.items or [])
            ],
            "manifest": (
                {
                    "knowlet_version": report.manifest.knowlet_version,
                    "exported_at": report.manifest.exported_at,
                    "note_count": report.manifest.note_count,
                    "attachment_count": report.manifest.attachment_count,
                }
                if report.manifest is not None
                else None
            ),
        }

    # ---------------- LLM config (Phase 3 P3.0) ----------------

    @app.get("/api/llm/config")
    def llm_config_get() -> dict[str, Any]:
        """Return the current LLM config (provider / base_url / model
        / has_api_key / max_tokens). **Never** returns the api_key
        itself — only ``has_api_key`` bool.

        Per ADR-0028 §1 amendment 2026-05-16: knowlet does not
        evaluate, classify, or comment on the configured model. The
        UI just shows what the user has set."""
        # Always read fresh from disk (config might've been edited
        # externally; we don't trust the in-process copy).
        fresh = load_config(vault.root)
        return {
            "base_url": fresh.llm.base_url,
            "model": fresh.llm.model,
            "has_api_key": bool(fresh.llm.api_key),
            "max_tokens": fresh.llm.max_tokens,
        }

    @app.put("/api/llm/config")
    def llm_config_put(
        payload: LLMConfigUpdate = Body(...),
    ) -> dict[str, Any]:
        """Update LLM config. Empty-string ``api_key`` means
        "keep existing" so the UI can save other fields without
        re-entering the secret."""
        from knowlet.config import save_config as _save_cfg

        fresh = load_config(vault.root)
        if payload.base_url is not None:
            fresh.llm.base_url = payload.base_url
        if payload.model is not None:
            fresh.llm.model = payload.model
        if payload.max_tokens is not None:
            fresh.llm.max_tokens = payload.max_tokens
        # api_key handling: None = field absent (don't touch); ""
        # = keep existing; anything else = overwrite.
        if payload.api_key is not None and payload.api_key != "":
            fresh.llm.api_key = payload.api_key
        _save_cfg(vault.root, fresh)
        # Mutate the in-process config so subsequent endpoints see
        # the new values without restart.
        config.llm.base_url = fresh.llm.base_url
        config.llm.model = fresh.llm.model
        config.llm.api_key = fresh.llm.api_key
        config.llm.max_tokens = fresh.llm.max_tokens
        return llm_config_get()

    @app.post("/api/llm/provider-models")
    def llm_provider_models(
        payload: LLMProviderModelsRequest | None = Body(default=None),
    ) -> dict[str, Any]:
        """Fetch the configured provider's actual ``/v1/models`` list.

        This is **not** a knowlet recommendation — it's whatever the
        user's own LLM provider exposes. knowlet just passes through.

        Whether ``/v1/models`` requires the API key is **provider-
        defined**: OpenAI-compatible proxies typically yes;
        local servers (LM Studio, vllm defaults) sometimes no.
        We pass whatever the caller provides (draft values from the
        Settings UI before save, or saved config as fallback) and
        let the provider decide. Errors return clean fallback so
        the UI degrades to a plain text input.

        POST (not GET) so draft credentials don't leak into URLs /
        access logs."""
        from openai import OpenAI

        draft_url = (payload.base_url if payload else None) or ""
        draft_key = (payload.api_key if payload else None) or ""
        effective_url = draft_url.strip() or config.llm.base_url
        # Empty string from caller = "use saved key". Caller can pass
        # whitespace-only or anything truthy to override; we don't
        # second-guess the draft.
        effective_key = (
            draft_key if draft_key else (config.llm.api_key or "knowlet-no-key")
        )

        if not effective_url:
            return {"models": [], "error": "base_url not configured"}
        try:
            client = OpenAI(base_url=effective_url, api_key=effective_key)
            response = client.models.list()
            models = [{"id": m.id} for m in response.data]
            return {"models": models}
        except Exception as exc:  # noqa: BLE001
            return {"models": [], "error": repr(exc)[:300]}

    @app.post("/api/llm/test")
    def llm_test(
        payload: LLMTestRequest | None = Body(default=None),
    ) -> dict[str, Any]:
        """Run a minimal completion against the configured LLM to
        verify connectivity + auth. Returns latency + a short echo
        of the response so the UI can show "OK reply: <preview>".

        Accepts optional draft credentials so the Settings UI can
        test what the user is **currently typing** without forcing
        a Save first — the natural expectation from Cursor / Postman
        / any modern API config UI."""
        import time as _time

        from knowlet.config import LLMConfig
        from knowlet.core.llm import LLMClient

        # Build an effective config: draft overrides saved per-field,
        # blank/None means "use saved".
        draft_url = (payload.base_url if payload else None) or ""
        draft_key = (payload.api_key if payload else None) or ""
        draft_model = (payload.model if payload else None) or ""
        effective = LLMConfig(
            base_url=draft_url.strip() or config.llm.base_url,
            api_key=draft_key or config.llm.api_key,
            model=draft_model.strip() or config.llm.model,
            max_tokens=config.llm.max_tokens,
        )
        client = LLMClient(effective)
        prompt = (
            "Reply with the single word 'ok' (no punctuation, no "
            "quotes). This is a connectivity check."
        )
        started = _time.monotonic()
        try:
            response = client.chat(
                messages=[{"role": "user", "content": prompt}],
                tools=None,
            )
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "error": repr(exc)[:500],
                "latency_ms": int((_time.monotonic() - started) * 1000),
            }
        latency_ms = int((_time.monotonic() - started) * 1000)
        # LLMClient returns AssistantMessage; preview the text content.
        preview = (
            (response.content or "")[:120]
            if hasattr(response, "content")
            else str(response)[:120]
        )
        return {
            "ok": True,
            "latency_ms": latency_ms,
            "preview": preview,
            "model": effective.model,
        }

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
