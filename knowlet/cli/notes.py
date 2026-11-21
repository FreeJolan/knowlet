"""`knowlet notes` — Note file ops (delete / restore + Phase 1 A folder ops).

`knowlet ls` (top-level) and the chat REPL `:ls` slash already cover
listing. This sub-app adds the destructive + organizational operations
that the React UI mirrors over `/api/folders`, `/api/trash`, and
`/api/notes/{id}/move` (per ADR-0008 CLI/UI parity discipline).
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import typer
from rich.markup import escape
from rich.panel import Panel
from rich.prompt import Confirm

from knowlet.cli._common import (
    console,
    err_console,
    load_config_or_default,
    make_index,
    resolve_vault_or_die,
)
from knowlet.cli._sync_marks import mark_deleted, mark_dirty, mark_restored
from knowlet.core.backlinks import find_backlinks
from knowlet.core.index import Index
from knowlet.core.note import Note
from knowlet.core.vault import Vault

app = typer.Typer(help="Note operations (delete / restore).", no_args_is_help=True)


def _resolve_note_meta(idx: Index, note_id: str) -> dict[str, Any]:
    """Resolve a full note id or a unique id prefix to its index row.

    Exits on a miss, and on a prefix matching several notes: callers go
    on to trash / move whatever this returns, and list views only show
    8-char prefixes, which collide for notes created in the same second.
    """
    needle = note_id.strip()
    if not needle:
        err_console.print("[red]note id is empty[/red]")
        raise typer.Exit(code=1)
    meta = idx.get_note_meta(needle)
    if meta is not None:
        return meta
    matches = [row for row in idx.list_notes(limit=None) if row["id"].startswith(needle)]
    if not matches:
        err_console.print(f"[red]note not found:[/red] {escape(needle)}")
        raise typer.Exit(code=1)
    if len(matches) > 1:
        err_console.print(
            f"[red]ambiguous prefix {escape(repr(needle))} matches {len(matches)} notes; "
            "pass a longer id:[/red]"
        )
        for row in sorted(matches, key=lambda r: r["id"]):
            err_console.print(f"  · {row['id']}  {escape(row.get('title') or '')}")
        raise typer.Exit(code=2)
    resolved = idx.get_note_meta(matches[0]["id"])
    if resolved is None:
        err_console.print(f"[red]note not found:[/red] {escape(needle)}")
        raise typer.Exit(code=1)
    return resolved


def _index_ids_by_path_under(vault: Vault, idx: Index, folder: Path) -> dict[Path, str]:
    """Index rows whose stored path lies under ``folder``, keyed by the
    resolved path. The index is the authority on which id a file was
    indexed under — filename stems are not (hand-named notes, trash
    collision suffixes)."""
    root = folder.resolve()
    out: dict[Path, str] = {}
    for row in idx.list_notes(limit=None):
        try:
            path = vault.resolve_note_path_from_index(row["path"]).resolve()
        except ValueError:
            continue
        if path.is_relative_to(root):
            out[path] = row["id"]
    return out


def _persist_folder_hint(vault: Vault, path: Path) -> Note | None:
    """Rewrite the note's ``folder`` frontmatter to match where it now
    lives (what the web move endpoints do), so a flat Drive appData
    restore rebuilds the same tree. Rewrites in place: the filename of a
    hand-named note must not change. Corrupted frontmatter is left
    byte-for-byte untouched. Returns the note, or None if unreadable."""
    try:
        note = vault.read_note(path)
    except (OSError, ValueError):
        return None
    if note.frontmatter_status == "corrupted":
        return note
    folder = vault.folder_of(path) or None
    if note.folder != folder:
        note.folder = folder
        note.path = path
        vault.write_note(note)
    return note


def _resync_moved_folder(vault: Vault, idx: Index, old_root: Path, new_root: Path) -> list[str]:
    """After a folder move / rename, point every moved note's index row
    at its new path (by real note id) and refresh its folder hint.
    Returns the ids of the moved notes."""
    old_ids = _index_ids_by_path_under(vault, idx, old_root)
    resolved_old_root = old_root.resolve()
    moved: list[str] = []
    for md in sorted(new_root.rglob("*.md")):
        if not md.is_file() or any(p.startswith(".") for p in md.relative_to(new_root).parts):
            continue
        rel = md.relative_to(new_root)
        note = _persist_folder_hint(vault, md)
        if note is not None and note.frontmatter_status != "corrupted":
            note_id = note.id
        else:
            note_id = old_ids.get(resolved_old_root / rel, md.stem)
        idx.update_note_path(note_id, str(md))
        moved.append(note_id)
    return moved


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
        meta = _resolve_note_meta(idx, note_id)

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
        mark_deleted(vault.root, [meta["id"]])
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
    restored = Note.from_file(target)
    restored_id = restored.id if restored.frontmatter_status == "valid" else target.stem
    mark_restored(vault.root, [restored_id])
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
        meta = _resolve_note_meta(idx, note_id)
        path = vault.resolve_note_path_from_index(meta["path"])
        clean_folder = "" if target_folder in (".", "/") else target_folder
        try:
            new_path = vault.move_note(path, clean_folder)
        except (ValueError, FileExistsError) as exc:
            err_console.print(f"[red]{exc}[/red]")
            raise typer.Exit(code=2) from exc
        _persist_folder_hint(vault, new_path)
        idx.update_note_path(meta["id"], str(new_path))
        mark_dirty(vault.root, [meta["id"]])
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
        mark_dirty(vault.root, _resync_moved_folder(vault, idx, vault.notes_dir / src, new_path))
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
        mark_dirty(vault.root, _resync_moved_folder(vault, idx, vault.notes_dir / folder, new_path))
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
        meta = _resolve_note_meta(idx, note_id)

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
        # delete_folder validated `folder`; the index rows still carry the
        # pre-trash paths.
        stale_ids = set(_index_ids_by_path_under(vault, idx, vault.notes_dir / folder).values())
        for trashed_path in trashed:
            try:
                trashed_note = Note.from_file(trashed_path)
            except (OSError, ValueError):
                continue
            if trashed_note.frontmatter_status == "valid" and not trashed_note.id_assigned:
                stale_ids.add(trashed_note.id)
        for stale_id in sorted(stale_ids):
            idx.delete_note(stale_id)
        mark_deleted(vault.root, sorted(stale_ids))
        console.print(f"[yellow]trashed {len(trashed)} note(s) → .trash/[/yellow]")
    finally:
        idx.close()
