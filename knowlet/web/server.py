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

STATIC_DIR = Path(__file__).parent / "static"


# ----------------------------------------------------------------- request/response models


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
    """

    def __init__(self, vault: Vault, config: KnowletConfig):
        self.vault = vault
        self.config = config
        self.runtime: ChatRuntime | None = None
        self.scheduler: MiningScheduler | None = None

    def runtime_or_init(self) -> ChatRuntime:
        if self.runtime is None:
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
        return self.runtime

    def close(self) -> None:
        if self.scheduler is not None:
            self.scheduler.shutdown()
            self.scheduler = None
        if self.runtime is not None:
            self.runtime.close()
            self.runtime = None


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
        # Eager-initialize the runtime so the scheduler can share its LLMClient.
        # If api_key is empty (test fixtures, fresh installs), skip — endpoints
        # will surface ChatNotReadyError on first call.
        if config.llm.api_key:
            try:
                runtime = state.runtime_or_init()
                state.scheduler = MiningScheduler(
                    vault,
                    runtime.llm,
                    default_output_language=config.general.language,
                )
                state.scheduler.start()
            except HTTPException:
                # bootstrap failed (e.g., dim mismatch) — endpoints will surface it
                pass
        yield
        state.close()

    app = FastAPI(title="knowlet", version=__version__, lifespan=lifespan)
    app.state.web_state = state
    runtime_dep = _runtime_dep(app)

    # ---------------- health ----------------

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "version": __version__,
            "vault": str(vault.root),
            "model": config.llm.model,
            "language": config.general.language,
            "supported_languages": list(SUPPORTED_LANGUAGES),
        }

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
        # Keep system prompt; drop the rest.
        runtime.session.history = runtime.session.history[:1]
        return {"ok": True}

    @app.get("/api/chat/history")
    def chat_history(
        runtime: ChatRuntime = Depends(runtime_dep),
    ) -> dict[str, Any]:
        # Skip the system message in the response — the UI doesn't need it.
        public = [
            m for m in runtime.session.history if m.get("role") in ("user", "assistant")
        ]
        return {"history": public}

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
        return [NoteSummary(**r) for r in rows]

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
