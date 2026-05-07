"""`knowlet tags` — Phase 1 C slice 2 CLI peer of `/api/tags`.

Per [ADR-0008](docs/decisions/0008-cli-parity-discipline.md) every UI
surface that consumes a backend has a CLI mirror so the CLI doubles as
QA harness. Tag browser is no exception.
"""

from __future__ import annotations

from typing import Annotated

import typer
from rich.table import Table

from knowlet.cli._common import (
    console,
    err_console,
    load_config_or_default,
    make_index,
    resolve_vault_or_die,
)

app = typer.Typer(help="Inspect tags across the vault.", no_args_is_help=True)


@app.command("list")
def tags_list() -> None:
    """List every tag in the vault with note counts (sorted by count desc)."""
    vault = resolve_vault_or_die()
    cfg = load_config_or_default(vault)
    idx = make_index(vault, cfg)
    try:
        rows = idx.aggregate_tags()
        if not rows:
            console.print("[dim]No tags yet. Add `tags:` to a note's frontmatter.[/dim]")
            return
        table = Table(show_header=True, header_style="bold")
        table.add_column("tag")
        table.add_column("count", justify="right")
        for tag, count in rows:
            table.add_row(tag, str(count))
        console.print(table)
    finally:
        idx.close()


@app.command("show")
def tags_show(
    tag: Annotated[str, typer.Argument(help="Tag name (case-sensitive).")],
) -> None:
    """List notes that carry the given tag."""
    vault = resolve_vault_or_die()
    cfg = load_config_or_default(vault)
    idx = make_index(vault, cfg)
    try:
        rows = idx.list_notes_by_tag(tag)
        if not rows:
            err_console.print(f"[yellow]no notes carry tag {tag!r}.[/yellow]")
            raise typer.Exit(code=1)
        table = Table(show_header=True, header_style="bold")
        table.add_column("id")
        table.add_column("title")
        table.add_column("tags")
        table.add_column("updated_at")
        for r in rows:
            table.add_row(
                r["id"][:8] + "…",
                r["title"],
                ", ".join(r["tags"]),
                r["updated_at"],
            )
        console.print(table)
        console.print(f"\n[dim]{len(rows)} note(s) with tag {tag!r}.[/dim]")
    finally:
        idx.close()
