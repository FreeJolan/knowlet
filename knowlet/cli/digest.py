"""`knowlet digest` — information-intake source commands."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.table import Table

from knowlet.cli._common import (
    console,
    err_console,
    load_config_or_default,
    resolve_vault_or_die,
)
from knowlet.cli.mining import _render_run_report
from knowlet.core.digest import is_digest_task, list_digest_tasks
from knowlet.core.digest_sources import DigestSource, DigestSourceStore
from knowlet.core.mining.task_store import TaskStore

app = typer.Typer(help="Information digest sources and intake runs.", no_args_is_help=True)


def _source_store() -> DigestSourceStore:
    vault = resolve_vault_or_die()
    return DigestSourceStore(vault.digest_sources_dir)


@app.command("list")
def digest_list() -> None:
    """List configured digest sources."""
    sources = _source_store().list()
    if not sources:
        console.print("[dim]no digest sources yet — `knowlet digest add` to create one[/dim]")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("id", style="dim", no_wrap=True)
    table.add_column("name")
    table.add_column("kind")
    table.add_column("source")
    table.add_column("on?", style="dim")
    table.add_column("last error")
    for source in sources:
        value = source.url if source.kind == "rss" else source.prompt
        value = (value or "").replace("\n", " ")
        preview = value[:48] + ("…" if len(value) > 48 else "")
        table.add_row(
            source.id[:8] + "…",
            source.name,
            source.kind,
            preview,
            "yes" if source.enabled else "no",
            source.last_error or "—",
        )
    console.print(table)


@app.command("add")
def digest_add(
    name: Annotated[str, typer.Option("--name", help="Human-readable source name.")],
    rss: Annotated[
        str | None,
        typer.Option("--rss", help="RSS / Atom feed URL."),
    ] = None,
    prompt: Annotated[
        str | None,
        typer.Option("--prompt", help="Prompt Source instruction."),
    ] = None,
    enabled: Annotated[
        bool,
        typer.Option("--enabled/--disabled", help="Whether the scheduler should run it."),
    ] = True,
) -> None:
    """Create an RSS Source or Prompt Source for the Stage C v2 inbox."""
    if bool(rss) == bool(prompt):
        err_console.print("[red]use exactly one of --rss or --prompt[/red]")
        raise typer.Exit(code=2)

    vault = resolve_vault_or_die()
    if rss:
        source = DigestSource(name=name, kind="rss", url=rss.strip(), enabled=enabled)
    else:
        source = DigestSource(
            name=name,
            kind="prompt",
            prompt=(prompt or "").strip(),
            enabled=enabled,
        )

    problems = source.validate()
    if problems:
        err_console.print(f"[red]invalid digest source:[/red] {'; '.join(problems)}")
        raise typer.Exit(code=2)
    path = DigestSourceStore(vault.digest_sources_dir).save(source)
    console.print(f"[green]created digest source[/green] → {path}")


def _set_enabled(source_id: str, enabled: bool) -> None:
    store = _source_store()
    source = store.get(source_id)
    if source is None:
        err_console.print(f"[red]digest source not found:[/red] {source_id}")
        raise typer.Exit(code=1)
    source.enabled = enabled
    store.save(source)
    console.print(
        f"[green]{'enabled' if enabled else 'disabled'}[/green] {source.id[:8]}…"
    )


@app.command("enable")
def digest_enable(
    source_id: Annotated[str, typer.Argument(help="Digest source id.")],
) -> None:
    """Enable a digest source."""
    _set_enabled(source_id, True)


@app.command("disable")
def digest_disable(
    source_id: Annotated[str, typer.Argument(help="Digest source id.")],
) -> None:
    """Disable a digest source."""
    _set_enabled(source_id, False)


@app.command("remove")
def digest_remove(
    source_id: Annotated[str, typer.Argument(help="Digest source id.")],
) -> None:
    """Remove a digest source."""
    vault = resolve_vault_or_die()
    source_store = DigestSourceStore(vault.digest_sources_dir)
    if source_store.delete(source_id):
        console.print(f"[green]removed[/green] {source_id}")
        return

    # Back-compat for Stage C v1 digest tasks created before source v2.
    store = TaskStore(vault.tasks_dir)
    task = store.get(source_id)
    if task is None or not is_digest_task(task):
        err_console.print(f"[red]digest source not found:[/red] {source_id}")
        raise typer.Exit(code=1)
    store.delete(task.id)
    console.print(f"[green]removed[/green] {source_id}")


@app.command("run")
def digest_run(
    source_id: Annotated[
        str | None,
        typer.Argument(help="Optional digest source id. Omit to run all enabled sources."),
    ] = None,
    limit: Annotated[
        int | None,
        typer.Option(
            "--limit",
            "-n",
            help="Cap the number of new items processed this run.",
        ),
    ] = None,
) -> None:
    """Run one digest source, or every enabled digest source, now."""
    from knowlet.core.llm import LLMClient
    from knowlet.core.mining.runner import run_task

    vault = resolve_vault_or_die()
    cfg = load_config_or_default(vault)
    if not cfg.llm.api_key:
        err_console.print("[red]LLM api_key is empty. Run `knowlet config init` first.[/red]")
        raise typer.Exit(code=2)
    store = TaskStore(vault.tasks_dir)
    if source_id:
        task = store.get(source_id)
        tasks = [task] if task is not None and is_digest_task(task) else []
    else:
        tasks = [task for task in list_digest_tasks(store) if task.enabled]
    if not tasks:
        console.print("[dim]no matching digest sources[/dim]")
        return
    llm = LLMClient(cfg.llm)
    for task in tasks:
        console.print(f"[bold]running[/bold] {task.name} ({task.id[:8]}…)")
        report = run_task(
            task,
            vault,
            llm,
            default_output_language=cfg.general.language,
            max_items=limit,
        )
        _render_run_report(report)
