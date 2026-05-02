"""`knowlet notes` — Note delete / restore (M7.0.1).

`knowlet ls` (top-level) and the chat REPL `:ls` slash already cover
listing. This sub-app adds the destructive operations and their inverse,
both of which need an id and confirmation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Confirm

from knowlet.cli._common import (
    console,
    err_console,
    load_config_or_default,
    make_index,
    resolve_vault_or_die,
)

app = typer.Typer(help="Note operations (delete / restore).", no_args_is_help=True)


@app.command("delete")
def notes_delete(
    note_id: Annotated[str, typer.Argument(help="Note id (or 8-char prefix).")],
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip the confirmation prompt."),
    ] = False,
) -> None:
    """Soft-delete a Note (move to `notes/.trash/`). Recoverable with `notes restore`."""
    vault = resolve_vault_or_die()
    cfg = load_config_or_default(vault)
    idx = make_index(vault, cfg)
    try:
        meta = idx.get_note_meta(note_id)
        if meta is None:
            # Tolerate prefix lookup
            for row in idx.list_notes(limit=10000):
                if row["id"].startswith(note_id):
                    meta = idx.get_note_meta(row["id"])
                    break
        if meta is None:
            err_console.print(f"[red]note not found:[/red] {note_id}")
            raise typer.Exit(code=1)

        title = meta.get("title", "(untitled)")
        if not yes:
            console.print(
                Panel.fit(
                    f"[bold]{title}[/bold]\n\n"
                    f"[dim]id: {meta['id']}[/dim]\n"
                    f"[dim]path: {meta.get('path', '?')}[/dim]",
                    title="confirm delete",
                )
            )
            if not Confirm.ask("move to .trash?", default=False):
                console.print("[dim]cancelled[/dim]")
                return

        path = Path(meta["path"])
        if not path.is_absolute():
            path = vault.notes_dir / path.name
        trashed = vault.trash_note(path)
        idx.delete_note(meta["id"])
        console.print(f"[yellow]trashed[/yellow] → {trashed}")
    finally:
        idx.close()


@app.command("restore")
def notes_restore(
    name: Annotated[
        str,
        typer.Argument(
            help="Trashed file name (e.g. '01HX....md') or 8-char id prefix.",
        ),
    ],
) -> None:
    """Restore a Note from `notes/.trash/` back to `notes/`."""
    vault = resolve_vault_or_die()
    # Find matching trashed file
    candidates = [p for p in vault.iter_trashed_paths() if p.stem.startswith(name) or p.name == name]
    if not candidates:
        err_console.print(f"[red]no trashed note matches:[/red] {name}")
        raise typer.Exit(code=1)
    if len(candidates) > 1:
        err_console.print(
            f"[red]ambiguous prefix {name!r} matches {len(candidates)} files:[/red]"
        )
        for p in candidates:
            err_console.print(f"  · {p.name}")
        raise typer.Exit(code=2)

    try:
        target = vault.restore_note(candidates[0])
    except FileExistsError as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]restored[/green] → {target}")
    console.print(
        "[dim]hint: run `knowlet reindex` so the index picks the file back up.[/dim]"
    )


@app.command("trash")
def notes_trash() -> None:
    """List Notes currently in `.trash/` (recoverable)."""
    from rich.table import Table

    vault = resolve_vault_or_die()
    paths = sorted(vault.iter_trashed_paths(), key=lambda p: p.stat().st_mtime, reverse=True)
    if not paths:
        console.print("[dim].trash/ is empty.[/dim]")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("file", style="dim", no_wrap=True)
    table.add_column("size", justify="right")
    table.add_column("trashed at", style="dim")
    import datetime
    for p in paths:
        st = p.stat()
        table.add_row(
            p.name,
            f"{st.st_size}B",
            datetime.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
        )
    console.print(table)
