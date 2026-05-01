"""Chat session bootstrapping — the single entry point both CLI and UI call.

`bootstrap_chat(vault, cfg)` returns a fully-wired `ChatRuntime`: embedding
backend loaded, index opened, vault re-scanned, conversation log primed,
LLM client + tool registry + ChatSession ready. Any UI layer (REPL, web,
desktop) just calls this and starts driving turns.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from knowlet.chat.log import ConversationLog, prune_old
from knowlet.chat.prompts import build_chat_system_prompt
from knowlet.chat.session import ChatSession
from knowlet.config import KnowletConfig, save_config
from knowlet.core.cards import CardStore
from knowlet.core.embedding import EmbeddingBackend, make_backend
from knowlet.core.index import Index, reindex_vault
from knowlet.core.llm import LLMClient
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
    convo: ConversationLog
    session: ChatSession
    user_profile: UserProfile | None = None

    def close(self) -> None:
        self.index.close()


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

    profile = read_profile(vault.profile_path)
    if profile is not None:
        report.user_profile_loaded = True
    profile_body = profile.truncated_for_prompt() if profile is not None else None
    system_prompt = build_chat_system_prompt(profile_body)

    llm = LLMClient(cfg.llm)
    registry = default_registry()
    cards = CardStore(vault.cards_dir)
    ctx = ToolContext(vault=vault, index=idx, config=cfg, cards=cards)
    session = ChatSession(
        llm=llm, registry=registry, ctx=ctx, system_prompt=system_prompt
    )
    convo = ConversationLog(dir=vault.conversations_dir, model=cfg.llm.model)

    runtime = ChatRuntime(
        vault=vault,
        config=cfg,
        backend=backend,
        index=idx,
        llm=llm,
        registry=registry,
        ctx=ctx,
        convo=convo,
        session=session,
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
