"""Shared CLI helpers used by every sub-app.

Anything that more than one CLI module needs lives here: vault discovery,
config loading, the index factory, console singletons, etc. Sub-apps
import from here; this module imports nothing from `knowlet.cli.*` to
avoid cycles.
"""

from __future__ import annotations

import typer
from rich.console import Console

from knowlet.config import (
    KnowletConfig,
    VaultNotFoundError,
    find_vault,
    load_config,
    save_config,
)
from knowlet.core.embedding import make_backend
from knowlet.core.i18n import set_language
from knowlet.core.index import Index
from knowlet.core.vault import Vault

console = Console()
err_console = Console(stderr=True)


def resolve_vault_or_die() -> Vault:
    try:
        root = find_vault()
    except VaultNotFoundError as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2) from exc
    return Vault(root)


def load_config_or_default(vault: Vault) -> KnowletConfig:
    cfg = load_config(vault.root)
    # Activate the configured UI language for everything downstream.
    set_language(cfg.general.language)
    return cfg


def make_index(vault: Vault, cfg: KnowletConfig) -> Index:
    backend = make_backend(
        cfg.embedding.backend, cfg.embedding.model, cfg.embedding.dim
    )
    idx = Index(vault.db_path, backend)
    idx.connect()
    # Sync dim into config if backend reports something different.
    real_dim = backend.dim
    if real_dim != cfg.embedding.dim:
        cfg.embedding.dim = real_dim
        save_config(vault.root, cfg)
    return idx


def mask(value: str, keep: int = 4) -> str:
    if not value:
        return ""
    if len(value) <= keep:
        return "*" * len(value)
    return value[:keep] + "*" * (len(value) - keep)


def render_notes_table(rows: list[dict], recent: bool) -> None:
    """Render a Notes listing. Used by `knowlet ls` and the chat REPL `:ls`."""
    from rich.table import Table

    if not rows:
        console.print("[dim]no notes yet[/dim]")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("id", style="dim", no_wrap=True)
    table.add_column("title")
    table.add_column("tags", style="cyan")
    table.add_column("updated_at" if recent else "created_at", style="dim")
    for r in rows:
        table.add_row(
            r["id"][:8] + "…",
            r["title"],
            ", ".join(r["tags"]),
            r["updated_at"] if recent else r["created_at"],
        )
    console.print(table)
