"""`knowlet notes` — Note file ops (delete / restore + Phase 1 A folder ops).

`knowlet ls` (top-level) and the chat REPL `:ls` slash already cover
listing. This sub-app adds the destructive + organizational operations
that the React UI mirrors over `/api/folders`, `/api/trash`, and
`/api/notes/{id}/move` (per ADR-0008 CLI/UI parity discipline).
"""

from __future__ import annotations

from typing import Annotated

import typer
from rich.panel import Panel
from rich.prompt import Confirm

from knowlet.cli._common import (
    console,
    err_console,
    load_config_or_default,
    make_index,
    resolve_vault_or_die,
)
from knowlet.core.backlinks import find_backlinks

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

        path = vault.resolve_note_path_from_index(meta["path"])
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
    candidates = [
        p for p in vault.iter_trashed_paths() if p.stem.startswith(name) or p.name == name
    ]
    if not candidates:
        err_console.print(f"[red]no trashed note matches:[/red] {name}")
        raise typer.Exit(code=1)
    if len(candidates) > 1:
        err_console.print(f"[red]ambiguous prefix {name!r} matches {len(candidates)} files:[/red]")
        for p in candidates:
            err_console.print(f"  · {p.name}")
        raise typer.Exit(code=2)

    try:
        target = vault.restore_note(candidates[0])
    except FileExistsError as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]restored[/green] → {target}")
    console.print("[dim]hint: run `knowlet reindex` so the index picks the file back up.[/dim]")


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


@app.command("purge")
def notes_purge(
    name: Annotated[
        str,
        typer.Argument(help="Trashed file name (full basename, e.g. '01HX....md')."),
    ],
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip the confirmation prompt."),
    ] = False,
) -> None:
    """Permanently delete one entry from `.trash/` (irreversible)."""
    vault = resolve_vault_or_die()
    target = vault.trash_dir / name
    if not target.exists():
        err_console.print(f"[red]not in .trash/:[/red] {name}")
        raise typer.Exit(code=1)
    if not yes:
        console.print(f"[bold red]permanent delete:[/bold red] {target}")
        if not Confirm.ask("really purge?", default=False):
            console.print("[dim]cancelled[/dim]")
            return
    vault.purge_trashed(name)
    console.print(f"[red]purged[/red] {name}")


@app.command("mkdir")
def notes_mkdir(
    folder: Annotated[
        str,
        typer.Argument(help="Forward-slash path under notes/, e.g. 'projects/knowlet'."),
    ],
) -> None:
    """Create a folder under `notes/` (idempotent)."""
    vault = resolve_vault_or_die()
    try:
        target = vault.mkdir_folder(folder)
    except ValueError as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2) from exc
    console.print(f"[green]created[/green] → {target}")


@app.command("mv")
def notes_mv(
    note_id: Annotated[str, typer.Argument(help="Note id (or 8-char prefix).")],
    target_folder: Annotated[
        str,
        typer.Argument(help="Target folder under notes/ (empty / '.' = root)."),
    ] = "",
) -> None:
    """Move a single Note to a target folder. Filename (ULID) preserved."""
    vault = resolve_vault_or_die()
    cfg = load_config_or_default(vault)
    idx = make_index(vault, cfg)
    try:
        meta = idx.get_note_meta(note_id)
        if meta is None:
            for row in idx.list_notes(limit=10000):
                if row["id"].startswith(note_id):
                    meta = idx.get_note_meta(row["id"])
                    break
        if meta is None:
            err_console.print(f"[red]note not found:[/red] {note_id}")
            raise typer.Exit(code=1)
        path = vault.resolve_note_path_from_index(meta["path"])
        clean_folder = "" if target_folder in (".", "/") else target_folder
        try:
            new_path = vault.move_note(path, clean_folder)
        except (ValueError, FileExistsError) as exc:
            err_console.print(f"[red]{exc}[/red]")
            raise typer.Exit(code=2) from exc
        idx.update_note_path(meta["id"], str(new_path))
        console.print(f"[green]moved[/green] → {new_path}")
    finally:
        idx.close()


@app.command("mvfolder")
def notes_mvfolder(
    src: Annotated[str, typer.Argument(help="Source folder under notes/.")],
    dst_parent: Annotated[
        str,
        typer.Argument(help="Destination parent folder ('.' = root)."),
    ] = "",
) -> None:
    """Move a folder under a different parent. Index paths re-sync."""
    vault = resolve_vault_or_die()
    cfg = load_config_or_default(vault)
    idx = make_index(vault, cfg)
    try:
        clean_parent = "" if dst_parent in (".", "/") else dst_parent
        try:
            new_path = vault.move_folder(src, clean_parent)
        except (ValueError, FileNotFoundError, FileExistsError) as exc:
            err_console.print(f"[red]{exc}[/red]")
            raise typer.Exit(code=2) from exc
        for md in new_path.rglob("*.md"):
            if md.is_file() and not any(p.startswith(".") for p in md.relative_to(new_path).parts):
                idx.update_note_path(md.stem, str(md))
        console.print(f"[green]moved[/green] → {new_path}")
    finally:
        idx.close()


@app.command("rnfolder")
def notes_rnfolder(
    folder: Annotated[str, typer.Argument(help="Existing folder path under notes/.")],
    new_name: Annotated[str, typer.Argument(help="New basename (no slashes).")],
) -> None:
    """Rename a folder in place. Index paths re-sync."""
    vault = resolve_vault_or_die()
    cfg = load_config_or_default(vault)
    idx = make_index(vault, cfg)
    try:
        try:
            new_path = vault.rename_folder(folder, new_name)
        except (ValueError, FileNotFoundError, FileExistsError) as exc:
            err_console.print(f"[red]{exc}[/red]")
            raise typer.Exit(code=2) from exc
        for md in new_path.rglob("*.md"):
            if md.is_file() and not any(p.startswith(".") for p in md.relative_to(new_path).parts):
                idx.update_note_path(md.stem, str(md))
        console.print(f"[green]renamed[/green] → {new_path}")
    finally:
        idx.close()


@app.command("backlinks")
def notes_backlinks(
    note_id: Annotated[str, typer.Argument(help="Note id (or 8-char prefix).")],
) -> None:
    """List notes that reference this one via `[[Title]]`.

    Phase 1 C slice 1 — CLI peer of `GET /api/notes/{id}/backlinks` per
    [ADR-0008](docs/decisions/0008-cli-parity-discipline.md). Output:
    grouped by source title, with line + sentence preview."""
    vault = resolve_vault_or_die()
    cfg = load_config_or_default(vault)
    idx = make_index(vault, cfg)
    try:
        meta = idx.get_note_meta(note_id)
        if meta is None:
            for row in idx.list_notes(limit=10000):
                if row["id"].startswith(note_id):
                    meta = idx.get_note_meta(row["id"])
                    break
        if meta is None:
            err_console.print(f"[red]note not found:[/red] {note_id}")
            raise typer.Exit(code=1)

        title = (meta.get("title") or "").strip()
        if not title:
            console.print("[dim](note has no title; cannot resolve backlinks)[/dim]")
            return

        results = find_backlinks(
            title,
            vault.iter_note_paths(),
            exclude_id=meta["id"],
        )
        if not results:
            console.print(f"[dim]no other note links to {title!r} via [[Title]] yet.[/dim]")
            return

        # Group by source for the same shape as the right rail.
        current_source: str | None = None
        for b in results:
            if b.source_title != current_source:
                console.print(f"\n[bold cyan]{b.source_title}[/bold cyan]")
                current_source = b.source_title
            console.print(
                f"  [dim]L{b.line}[/dim]  {b.sentence}",
            )
        console.print(
            f"\n[dim]{len(results)} mention(s) across "
            f"{len({b.source_id for b in results})} note(s).[/dim]"
        )
    finally:
        idx.close()


@app.command("rmfolder")
def notes_rmfolder(
    folder: Annotated[str, typer.Argument(help="Folder under notes/ to delete.")],
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip confirmation prompt."),
    ] = False,
) -> None:
    """Delete a folder. All notes inside are soft-deleted to `.trash/`."""
    vault = resolve_vault_or_die()
    cfg = load_config_or_default(vault)
    idx = make_index(vault, cfg)
    try:
        if not yes:
            console.print(f"[bold yellow]about to trash every note under:[/bold yellow] {folder}")
            if not Confirm.ask("continue?", default=False):
                console.print("[dim]cancelled[/dim]")
                return
        try:
            trashed = vault.delete_folder(folder)
        except (ValueError, FileNotFoundError) as exc:
            err_console.print(f"[red]{exc}[/red]")
            raise typer.Exit(code=2) from exc
        for trashed_path in trashed:
            idx.delete_note(trashed_path.stem)
        console.print(f"[yellow]trashed {len(trashed)} note(s) → .trash/[/yellow]")
    finally:
        idx.close()
