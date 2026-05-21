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
    drafts = store.all_drafts()
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


@app.command("edit")
def drafts_edit(
    draft_id: Annotated[str, typer.Argument(help="Draft id (or 8-char prefix).")],
) -> None:
    """Open the draft file in $EDITOR (or $VISUAL).

    Edits the markdown file directly — frontmatter + body. After the
    editor exits the file is left as the user saved it; knowlet picks
    up the new title / body on the next list / show / approve. Use
    when capture's AI extraction needs refining before approve."""
    import os
    import subprocess

    from knowlet.core.drafts import DraftStore

    vault = resolve_vault_or_die()
    store = DraftStore(vault.drafts_dir)
    d = store.get(draft_id)
    if d is None or d.path is None:
        err_console.print(f"[red]draft not found:[/red] {draft_id}")
        raise typer.Exit(code=1)
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vi"
    subprocess.run([editor, str(d.path)], check=False)
    console.print(f"[dim]edited (saved as-is):[/dim] {d.path}")


@app.command("kind")
def drafts_kind(
    draft_id: Annotated[str, typer.Argument(help="Draft id (or 8-char prefix).")],
    kind: Annotated[
        str,
        typer.Argument(help="New kind: 'knowledge' or 'reference'."),
    ],
) -> None:
    """Change a draft's kind (knowledge / reference).

    Web UI mirror per ADR-0029 §4.5 — every backend capability the
    UI exposes should be reachable from CLI too."""
    from knowlet.core.drafts import DraftStore

    if kind not in ("knowledge", "reference"):
        err_console.print(
            f"[red]invalid kind:[/red] {kind!r} (must be 'knowledge' or 'reference')"
        )
        raise typer.Exit(code=1)
    vault = resolve_vault_or_die()
    store = DraftStore(vault.drafts_dir)
    d = store.get(draft_id)
    if d is None:
        err_console.print(f"[red]draft not found:[/red] {draft_id}")
        raise typer.Exit(code=1)
    d.kind = kind  # type: ignore[assignment]
    store.save(d)
    console.print(f"[green]kind set:[/green] {d.id[:8]}… → {kind}")


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
