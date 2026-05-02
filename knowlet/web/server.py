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
from pathlib import Path
from typing import Any

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, status
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
    Draft,
    commit_draft,
    draft_from_conversation,
)
from knowlet.config import KnowletConfig, find_vault, load_config
from knowlet.core.card import Card, parse_due
from knowlet.core.events import ErrorEvent, event_to_dict
from knowlet.core.fsrs_wrap import initial_state, schedule_next
from knowlet.core.i18n import SUPPORTED_LANGUAGES, all_keys, set_language
from knowlet.core.index import IndexDimensionMismatchError
from knowlet.core.llm import LLMClient
from knowlet.core.mining.runner import reset_task_state, run_task
from knowlet.core.mining.scheduler import MiningScheduler
from knowlet.core.mining.task import MiningTask, Schedule, SourceSpec
from knowlet.core.user_profile import (
    UserProfile,
    read_profile,
    write_profile,
)
from knowlet.core.vault import Vault

STATIC_DIR = Path(__file__).resolve().parent / "static"


# ----------------------------------------------------------------- request/response models


class RenameSessionRequest(BaseModel):
    title: str


class ChatTurnRequest(BaseModel):
    text: str = Field(..., description="user message")


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


class NoteFull(NoteSummary):
    body: str


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
            except Exception as exc:  # noqa: BLE001
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


def _runtime_dep(app: FastAPI):
    """FastAPI dependency: hand back the ChatRuntime, initializing on demand."""

    def _dep() -> ChatRuntime:
        state: WebState = app.state.web_state
        return state.runtime_or_init()

    return _dep


# ----------------------------------------------------------------- factory


def create_app(vault: Vault, config: KnowletConfig) -> FastAPI:
    """Build a FastAPI app bound to a specific vault and config.

    Used both by `knowlet web` (production) and by tests (with a tmp_path
    vault, dummy embedding, stub LLM).
    """
    state = WebState(vault=vault, config=config)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Activate the configured UI language for any backend-rendered strings.
        set_language(config.general.language)
        # Bootstrap (which calls reindex_vault) runs on a background thread
        # so uvicorn accepts connections immediately. Endpoints that need
        # the runtime poll `bootstrap_status` and 503 while indexing. The
        # frontend reads this via `/api/health.ready` and shows a banner.
        # Without this, a vault with thousands of notes would block uvicorn
        # for minutes on first launch and look like the server crashed.
        state.start_bootstrap_async()
        yield
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
        from knowlet.cli._doctor import run_doctor_checks

        results = run_doctor_checks(
            runtime.vault, runtime.config,
            skip_llm=skip_llm, skip_embedding=skip_embedding,
        )
        return {
            "results": [
                {"status": r[0], "name": r[1], "detail": r[2]}
                for r in results
            ],
            "failures": sum(1 for r in results if r[0] == "fail"),
            "warnings": sum(1 for r in results if r[0] == "warn"),
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

    # ---------------- chat ----------------

    @app.post("/api/chat/turn", response_model=ChatTurnResponse)
    def chat_turn(
        req: ChatTurnRequest,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> ChatTurnResponse:
        traces: list[ToolTrace] = []

        def on_tool_call(tc, payload) -> None:
            traces.append(
                ToolTrace(
                    name=tc.name, arguments=tc.arguments, result=payload
                )
            )

        try:
            reply, _ = runtime.session.user_turn(req.text, on_tool_call=on_tool_call)
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

        def event_source():
            try:
                for event in runtime.session.user_turn_stream(req.text):
                    payload = json.dumps(event_to_dict(event), ensure_ascii=False)
                    yield f"data: {payload}\n\n"
            except Exception as exc:  # noqa: BLE001
                err = ErrorEvent(message=f"server error: {exc}")
                yield f"data: {json.dumps(event_to_dict(err))}\n\n"
            finally:
                # Persist the (possibly partial) turn so a refresh mid-stream
                # doesn't drop the exchange.
                try:
                    runtime.persist_active()
                except Exception:  # noqa: BLE001
                    pass

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

        def event_source():
            try:
                for event in ephemeral.user_turn_stream(req.text):
                    payload = json.dumps(event_to_dict(event), ensure_ascii=False)
                    yield f"data: {payload}\n\n"
            except Exception as exc:  # noqa: BLE001
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
        public = [
            m for m in runtime.session.history if m.get("role") in ("user", "assistant")
        ]
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
            "Use the same language the user wrote in.\n\n"
            + "\n\n".join(excerpt)
            + "\n\nTitle:"
        )
        try:
            resp = runtime.llm.chat(
                [{"role": "user", "content": prompt}],
                max_tokens=32,
                temperature=0,
            )
        except Exception as exc:  # noqa: BLE001
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
        draft = Draft(title=payload.title, tags=payload.tags, body=payload.body)
        note = commit_draft(draft, runtime.vault, runtime.index, runtime.config)
        return CommitDraftResponse(note_id=note.id, path=str(note.path))

    # ---------------- notes (read) ----------------

    @app.get("/api/notes", response_model=list[NoteSummary])
    def list_notes(
        limit: int = 20,
        recent: bool = False,
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> list[NoteSummary]:
        rows = runtime.index.list_notes(
            limit=limit, order="updated_at" if recent else "created_at"
        )
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

    @app.get("/api/notes/{note_id}", response_model=NoteFull)
    def get_note(
        note_id: str, runtime: ChatRuntime = Depends(runtime_dep)
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
        return NoteFull(
            id=note.id,
            title=note.title,
            path=str(path),
            tags=note.tags,
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
        note.tags = list(payload.tags)
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
            created_at=note.created_at,
            updated_at=note.updated_at,
            body=note.body,
        )

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

    def _draft_summary(d) -> DraftSummary:
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
        return [_draft_summary(d) for d in runtime.ctx.drafts.list()]

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

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

        @app.get("/")
        def index() -> FileResponse:
            return FileResponse(STATIC_DIR / "index.html")

    return app


def serve(host: str = "127.0.0.1", port: int = 8765) -> None:  # pragma: no cover
    """Start the web server. Auto-discovers the vault from CWD / KNOWLET_VAULT."""
    import uvicorn

    vault_root = find_vault()
    vault = Vault(vault_root)
    cfg = load_config(vault.root)
    if not cfg.llm.api_key:
        raise SystemExit(
            "LLM api_key is empty — run `knowlet config init` (or `config set llm.api_key …`)."
        )
    app = create_app(vault, cfg)
    uvicorn.run(app, host=host, port=port, log_level="info")
