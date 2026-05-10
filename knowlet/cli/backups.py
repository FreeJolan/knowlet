"""`knowlet backups` — Phase 2 E Slice 4.E CLI peer of the backup store.

Per ADR-0008 (CLI parity discipline) every backend feature has a
matching CLI surface. The backup store has no UI — backups are an
operational safety net, not a user-facing feature — but power users
and scripts need a way to inspect / restore.

Sub-commands:
- ``knowlet backups list [--entity ...] [--id ...]`` — newest-first
  per (entity, id).
- ``knowlet backups restore <backup-path> --to <dest>`` — copy a
  backup back to a target path. Refuses to overwrite a live file
  (move it aside first).
- ``knowlet backups prune [--keep N]`` — manually re-apply the LRU
  cap. Normally invoked automatically on each backup; this is for
  scripts that want to compress N=5 down to N=1, etc.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.table import Table

from knowlet.cli._common import (
    console,
    err_console,
    resolve_vault_or_die,
)
from knowlet.core.backups import DEFAULT_KEEP, BackupStore

app = typer.Typer(help="Inspect / restore per-file vault backups.", no_args_is_help=True)


@app.command("list")
def backups_list(
    entity: Annotated[
        str | None,
        typer.Option("--entity", help='Filter by entity type (e.g. "note").'),
    ] = None,
    entity_id: Annotated[
        str | None,
        typer.Option(
            "--id", help="Filter by entity id (typically a Note ULID)."
        ),
    ] = None,
) -> None:
    """List backup files. Newest-first within each (entity, id)."""
    vault = resolve_vault_or_die()
    store = BackupStore(vault.root)
    rows = store.list_backups(entity_type=entity, entity_id=entity_id)
    if not rows:
        console.print("[dim]No backups.[/dim]")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("ts")
    table.add_column("entity")
    table.add_column("path", overflow="fold")
    for r in rows:
        table.add_row(
            r.timestamp,
            f"{r.entity_type}/{r.entity_id}",
            str(r.path),
        )
    console.print(table)


@app.command("restore")
def backups_restore(
    backup: Annotated[Path, typer.Argument(help="Backup file path.")],
    dest: Annotated[
        Path, typer.Option("--to", help="Where to restore the backup.")
    ],
) -> None:
    """Copy a backup back into the live vault. Refuses if ``--to``
    already exists — move the live file aside first so a wrong
    restore can itself be reverted via the next backup cycle."""
    vault = resolve_vault_or_die()
    store = BackupStore(vault.root)
    try:
        out = store.restore(backup, dest)
        console.print(f"[green]restored[/green] {backup.name} → {out}")
    except FileExistsError as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    except FileNotFoundError as exc:
        err_console.print(f"[red]backup not found:[/red] {backup}")
        raise typer.Exit(code=2) from exc


@app.command("prune")
def backups_prune(
    keep: Annotated[
        int,
        typer.Option(
            "--keep", help="Per-id retention cap.", min=1, max=50
        ),
    ] = DEFAULT_KEEP,
) -> None:
    """Trim every (entity, id) stream down to the most recent `keep`
    entries. Normally each backup_before_overwrite call does this
    automatically; use this command to compact retroactively (e.g.
    after lowering the desired keep count)."""
    vault = resolve_vault_or_die()
    store = BackupStore(vault.root)
    rows = store.list_backups()
    # Group by (entity_type, entity_id); drop tail beyond `keep`.
    groups: dict[tuple[str, str], list[Path]] = {}
    for r in rows:
        groups.setdefault((r.entity_type, r.entity_id), []).append(r.path)
    deleted = 0
    for paths in groups.values():
        # rows is already newest-first per group.
        for old in paths[keep:]:
            try:
                old.unlink()
                deleted += 1
            except OSError:
                err_console.print(f"[yellow]could not delete[/yellow] {old}")
    console.print(f"[green]pruned[/green] {deleted} files (kept {keep} per id)")
