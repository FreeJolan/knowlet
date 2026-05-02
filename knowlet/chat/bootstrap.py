"""Chat session bootstrapping — the single entry point both CLI and UI call.

`bootstrap_chat(vault, cfg)` returns a fully-wired `ChatRuntime`: embedding
backend loaded, index opened, vault re-scanned, conversation log primed,
LLM client + tool registry + ChatSession ready. Any UI layer (REPL, web,
desktop) just calls this and starts driving turns.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from knowlet.chat.conversation_store import Conversation, ConversationStore
from knowlet.chat.log import prune_old
from knowlet.chat.prompts import build_chat_system_prompt
from knowlet.chat.session import ChatSession
from knowlet.config import KnowletConfig, save_config
from knowlet.core.card_store import CardStore
from knowlet.core.drafts import DraftStore
from knowlet.core.embedding import EmbeddingBackend, make_backend
from knowlet.core.index import Index, reindex_vault
from knowlet.core.llm import LLMClient
from knowlet.core.mining.task_store import TaskStore
from knowlet.core.tools._registry import Registry, ToolContext, default_registry
from knowlet.core.user_profile import UserProfile, read_profile
from knowlet.core.vault import Vault


class ChatNotReadyError(RuntimeError):
    """Raised when the vault/config is not in a state ready to start chat."""


@dataclass
class ChatRuntime:
    vault: Vault
    config: KnowletConfig
    backend: EmbeddingBackend
    index: Index
    llm: LLMClient
    registry: Registry
    ctx: ToolContext
    conversations: ConversationStore  # the multi-session repo (M6.4)
    session: ChatSession              # active in-memory session
    active_conversation: Conversation # currently-loaded persisted record
    user_profile: UserProfile | None = None

    def close(self) -> None:
        # Persist whatever's in flight before tearing down the index. The
        # /api/chat/turn endpoint already saves after every turn, but the
        # CLI REPL may exit mid-stream, so this catches that path.
        self.persist_active()
        self.index.close()

    def persist_active(self) -> None:
        """Sync the in-memory `ChatSession.history` back to the persisted
        `active_conversation` record. Only writes when there's content past
        the system prompt — empty sessions don't pollute the listing."""
        if not self.session.history or len(self.session.history) <= 1:
            return
        self.active_conversation.messages = list(self.session.history)
        self.conversations.save(self.active_conversation)

    def switch_to(self, conv: Conversation) -> None:
        """Make `conv` the active session: load its messages into ChatSession
        and remember it as the persistence target. The system prompt at index
        0 stays whatever was last saved (per-session), so a profile change
        only takes effect for *new* sessions."""
        # Persist the outgoing session before discarding it.
        self.persist_active()
        if not conv.messages:
            # Defensive: a brand-new conversation should at least carry the
            # current build of the system prompt.
            conv.messages = [self.session.history[0]] if self.session.history else []
        self.active_conversation = conv
        self.session.history = list(conv.messages)

    def new_session(self, system_prompt: str | None = None) -> Conversation:
        """Start a fresh persisted conversation and switch to it."""
        prompt = (
            system_prompt
            if system_prompt is not None
            else (self.session.history[0]["content"] if self.session.history else "")
        )
        conv = self.conversations.new(model=self.config.llm.model, system_prompt=prompt)
        self.switch_to(conv)
        return conv


@dataclass
class BootstrapReport:
    """Side-effect summary from `bootstrap_chat` — surfaced by the caller."""

    pruned_conversations: int = 0
    reindex_changed: int = 0
    reindex_deleted: int = 0
    reindex_unchanged: int = 0
    embedding_dim_synced: bool = False
    user_profile_loaded: bool = False


def bootstrap_chat(
    vault: Vault,
    cfg: KnowletConfig,
    *,
    rescan: bool = True,
    prune_days: int = 30,
) -> tuple[ChatRuntime, BootstrapReport]:
    """Set everything up and return a usable chat runtime.

    Raises:
        ChatNotReadyError: if api_key is empty.
        IndexDimensionMismatchError: if persisted index doesn't match the
            configured embedding dim. Caller decides UX (CLI prints + exits;
            UI shows a dialog with `reindex --rebuild` suggestion).
    """
    if not cfg.llm.api_key:
        raise ChatNotReadyError(
            "LLM api_key is empty — run `knowlet config init` (or `config set llm.api_key …`)."
        )

    report = BootstrapReport()

    backend = make_backend(cfg.embedding.backend, cfg.embedding.model, cfg.embedding.dim)
    if backend.dim != cfg.embedding.dim:
        cfg.embedding.dim = backend.dim
        save_config(vault.root, cfg)
        report.embedding_dim_synced = True

    if rescan:
        report.reindex_changed, report.reindex_deleted, report.reindex_unchanged = reindex_vault(
            vault.root,
            vault.db_path,
            backend,
            chunk_size=cfg.retrieval.chunk_size,
            chunk_overlap=cfg.retrieval.chunk_overlap,
            note_paths=list(vault.iter_note_paths()),
        )

    idx = Index(vault.db_path, backend)
    idx.connect()

    report.pruned_conversations = prune_old(vault.conversations_dir, days=prune_days)

    # M7.4.3: archive 90+ day quiz sessions on startup. Spares sessions
    # that produced Cards (the user learned something specific from them
    # — worth keeping live per ADR-0014 §5.2). Idempotent + cheap; the
    # store walks `.knowlet/quizzes/*.json` once, no LLM call.
    try:
        from knowlet.core.quiz_store import QuizStore

        QuizStore(vault.state_dir).archive_aged()
    except Exception:  # noqa: BLE001 — boundary; aging is non-critical
        pass

    profile = read_profile(vault.profile_path)
    if profile is not None:
        report.user_profile_loaded = True
    profile_body = profile.truncated_for_prompt() if profile is not None else None
    system_prompt = build_chat_system_prompt(profile_body)

    llm = LLMClient(cfg.llm)
    registry = default_registry()
    cards = CardStore(vault.cards_dir)
    tasks = TaskStore(vault.tasks_dir)
    drafts = DraftStore(vault.drafts_dir)
    ctx = ToolContext(
        vault=vault, index=idx, config=cfg,
        cards=cards, tasks=tasks, drafts=drafts,
    )
    session = ChatSession(
        llm=llm, registry=registry, ctx=ctx, system_prompt=system_prompt
    )
    conversations = ConversationStore(vault.conversations_dir)

    # Resume the most recent meaningful conversation (M6.4): a user closing
    # the browser and coming back tomorrow doesn't lose context. Falls back
    # to a fresh session if there's nothing on disk yet.
    resumed = conversations.most_recent()
    if resumed is not None:
        # Replay the persisted messages into the session. The first message
        # in the persisted log is the system prompt at the time of that
        # conversation's start; we trust it (per-session prompt history).
        session.history = list(resumed.messages)
        active = resumed
    else:
        active = conversations.new(model=cfg.llm.model, system_prompt=system_prompt)

    runtime = ChatRuntime(
        vault=vault,
        config=cfg,
        backend=backend,
        index=idx,
        llm=llm,
        registry=registry,
        ctx=ctx,
        conversations=conversations,
        session=session,
        active_conversation=active,
        user_profile=profile,
    )
    return runtime, report


def render_history(history: list[dict[str, Any]]) -> str:
    """Plain-text rendering of the user/assistant turns. Reusable from UI."""
    lines: list[str] = []
    for m in history:
        role = m.get("role")
        if role == "user":
            lines.append(f"USER: {m.get('content') or ''}")
        elif role == "assistant":
            content = m.get("content") or ""
            if content:
                lines.append(f"ASSISTANT: {content}")
    return "\n\n".join(lines).strip()
