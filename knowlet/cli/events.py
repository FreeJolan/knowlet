"""`knowlet events` — Phase 2 E Slice 4.B CLI peer of `/api/events`.

Per [ADR-0008](docs/decisions/0008-cli-parity-discipline.md) every UI
surface has a CLI mirror. The web UI doesn't surface events yet (that's
its own future slice), but the CLI ships first so power users can poke
at the audit log right now and dogfood the producer hooks.

Sub-commands:
- ``knowlet events tail [-n N]`` — last N events (default 20).
- ``knowlet events list [--kind ...]`` — filtered list, oldest-first.
- ``knowlet events log [--limit N]`` — regenerate ``vault/.knowlet/log.md``.
"""

from __future__ import annotations

from typing import Annotated

import typer
from rich.table import Table

from knowlet.cli._common import (
    console,
    resolve_vault_or_die,
)
from knowlet.core.audit_log import AuditEvent, AuditEventStore

app = typer.Typer(help="Inspect the vault audit log.", no_args_is_help=True)


def _print_events(events: list[AuditEvent]) -> None:
    if not events:
        console.print("[dim]No events.[/dim]")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("ts")
    table.add_column("kind")
    table.add_column("entity")
    table.add_column("payload", overflow="fold")
    for ev in events:
        # Compact one-line payload — full JSON lives in the SQLite
        # row, this is just for at-a-glance reading.
        bits: list[str] = []
        for k, v in ev.payload.items():
            bits.append(f"{k}={v!r}")
        table.add_row(
            ev.ts,
            ev.kind,
            f"{ev.entity_type}/{ev.entity_id}",
            ", ".join(bits) or "—",
        )
    console.print(table)


@app.command("tail")
def events_tail(
    n: Annotated[
        int,
        typer.Option("-n", "--n", help="Number of recent events to show."),
    ] = 20,
) -> None:
    """Show the last N events, oldest-first within the slice so the
    output reads like a live log scrolling down."""
    vault = resolve_vault_or_die()
    store = AuditEventStore(vault.root)
    try:
        _print_events(store.tail(n))
    finally:
        store.close()


@app.command("list")
def events_list(
    kind: Annotated[
        list[str] | None,
        typer.Option(
            "--kind",
            help="Filter by kind (repeatable). e.g. --kind note.created.",
        ),
    ] = None,
    entity_id: Annotated[
        str | None,
        typer.Option(
            "--entity-id",
            help="Filter by entity id (typically a Note ULID).",
        ),
    ] = None,
    limit: Annotated[
        int | None,
        typer.Option("--limit", help="Cap the result set."),
    ] = None,
) -> None:
    """List events with optional filters. Output is oldest-first;
    pipe through ``tac`` for newest-first."""
    vault = resolve_vault_or_die()
    store = AuditEventStore(vault.root)
    try:
        events = store.query(
            kinds=kind or None,
            entity_id=entity_id,
            limit=limit,
        )
        _print_events(events)
    finally:
        store.close()


@app.command("log")
def events_log(
    limit: Annotated[
        int,
        typer.Option(
            "--limit", help="Most recent N events to render into log.md."
        ),
    ] = 200,
) -> None:
    """Regenerate ``vault/.knowlet/log.md`` from the SQLite log.
    The file is rewritten wholesale — never appended in place — so
    callers can run this any number of times without piling up."""
    vault = resolve_vault_or_die()
    store = AuditEventStore(vault.root)
    try:
        out = store.render_log_md(limit=limit)
        console.print(f"[green]wrote[/green] {out} ({store.count()} events total)")
    finally:
        store.close()


@app.command("count")
def events_count() -> None:
    """Print the total number of events in the audit log."""
    vault = resolve_vault_or_die()
    store = AuditEventStore(vault.root)
    try:
        n = store.count()
        console.print(f"{n}")
    finally:
        store.close()
