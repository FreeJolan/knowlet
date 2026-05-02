"""`knowlet drafts` — review AI-extracted drafts before they become Notes."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from knowlet.cli._common import (
    console,
    err_console,
    load_config_or_default,
    resolve_vault_or_die,
)

app = typer.Typer(help="AI-extracted drafts pending review.", no_args_is_help=True)


@app.command("list")
def drafts_list() -> None:
    """List drafts pending review."""
    from knowlet.core.drafts import DraftStore

    vault = resolve_vault_or_die()
    store = DraftStore(vault.drafts_dir)
    drafts = store.list()
    if not drafts:
        console.print("[dim]no drafts pending — your inbox is empty[/dim]")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("id", style="dim", no_wrap=True)
    table.add_column("title")
    table.add_column("source", style="cyan", overflow="fold")
    table.add_column("when", style="dim")
    for d in drafts:
        table.add_row(d.id[:8] + "…", d.title, (d.source or "")[:60], d.created_at)
    console.print(table)


@app.command("show")
def drafts_show(
    draft_id: Annotated[str, typer.Argument(help="Draft id (or 8-char prefix).")],
) -> None:
    """Print a draft's full body."""
    from knowlet.core.drafts import DraftStore

    vault = resolve_vault_or_die()
    store = DraftStore(vault.drafts_dir)
    d = store.get(draft_id)
    if d is None:
        err_console.print(f"[red]draft not found:[/red] {draft_id}")
        raise typer.Exit(code=1)
    console.print(Panel(Markdown(d.body), title=d.title))
    console.print(
        f"[dim]source: {d.source or '—'}  ·  task: {d.task_id or '—'}  ·  "
        f"tags: {', '.join(d.tags) or '—'}[/dim]"
    )


@app.command("approve")
def drafts_approve(
    draft_id: Annotated[str, typer.Argument(help="Draft id (or 8-char prefix).")],
) -> None:
    """Promote a draft to a Note and remove it from drafts/."""
    _draft_approve_or_reject(draft_id, approve=True)


@app.command("reject")
def drafts_reject(
    draft_id: Annotated[str, typer.Argument(help="Draft id (or 8-char prefix).")],
) -> None:
    """Delete a draft."""
    _draft_approve_or_reject(draft_id, approve=False)


def _draft_approve_or_reject(draft_id: str, *, approve: bool) -> None:
    from knowlet.core.drafts import DraftStore
    from knowlet.core.embedding import make_backend
    from knowlet.core.index import Index

    vault = resolve_vault_or_die()
    cfg = load_config_or_default(vault)
    store = DraftStore(vault.drafts_dir)
    draft = store.get(draft_id)
    if draft is None:
        err_console.print(f"[red]draft not found:[/red] {draft_id}")
        raise typer.Exit(code=1)
    if not approve:
        store.delete(draft.id)
        console.print(f"[green]rejected[/green] {draft.id[:8]}…")
        return
    backend = make_backend(cfg.embedding.backend, cfg.embedding.model, cfg.embedding.dim)
    idx = Index(vault.db_path, backend)
    idx.connect()
    try:
        note = draft.to_note()
        path = vault.write_note(note)
        note.path = path
        idx.upsert_note(
            note,
            chunk_size=cfg.retrieval.chunk_size,
            chunk_overlap=cfg.retrieval.chunk_overlap,
        )
    finally:
        idx.close()
    store.delete(draft.id)
    console.print(f"[green]approved[/green] → {path}")
