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
from knowlet.core.events import ErrorEvent, event_to_dict
from knowlet.core.index import IndexDimensionMismatchError
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
        # state is set on the app below; nothing to do at startup.
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
        }

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
