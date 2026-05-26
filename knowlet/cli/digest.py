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
from knowlet.core.digest import build_digest_task, is_digest_task, list_digest_tasks
from knowlet.core.mining.task import Schedule, SourceSpec
from knowlet.core.mining.task_store import TaskStore

app = typer.Typer(help="Information digest sources and intake runs.", no_args_is_help=True)


def _parse_sources(rss: str | None, url: str | None) -> list[SourceSpec]:
    sources: list[SourceSpec] = []
    if rss:
        sources.extend(SourceSpec(type="rss", url=u.strip()) for u in rss.split(",") if u.strip())
    if url:
        sources.extend(SourceSpec(type="url", url=u.strip()) for u in url.split(",") if u.strip())
    return sources


def _schedule(every: str | None, cron: str | None) -> Schedule:
    if every and cron:
        err_console.print("[red]use --every OR --cron, not both[/red]")
        raise typer.Exit(code=2)
    return Schedule(every=every, cron=cron)


@app.command("list")
def digest_list() -> None:
    """List configured digest sources."""
    vault = resolve_vault_or_die()
    store = TaskStore(vault.tasks_dir)
    tasks = list_digest_tasks(store)
    if not tasks:
        console.print("[dim]no digest sources yet — `knowlet digest add` to create one[/dim]")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("id", style="dim", no_wrap=True)
    table.add_column("name")
    table.add_column("schedule")
    table.add_column("sources")
    table.add_column("on?", style="dim")
    for task in tasks:
        sched = (
            (task.schedule.every and f"every {task.schedule.every}")
            or (task.schedule.cron and f"cron {task.schedule.cron}")
            or "—"
        )
        srcs = ", ".join(
            source.url[:40] + ("…" if len(source.url) > 40 else "")
            for source in task.sources
        )
        table.add_row(
            task.id[:8] + "…",
            task.name,
            sched,
            srcs,
            "yes" if task.enabled else "no",
        )
    console.print(table)


@app.command("add")
def digest_add(
    name: Annotated[str, typer.Option("--name", help="Human-readable source name.")],
    rss: Annotated[
        str | None,
        typer.Option("--rss", help="RSS / Atom feed URL (repeatable via comma)."),
    ] = None,
    url: Annotated[
        str | None,
        typer.Option("--url", help="Plain URL fetch (repeatable via comma)."),
    ] = None,
    every: Annotated[
        str | None,
        typer.Option("--every", help="Interval like '1h' / '6h' / '1d'."),
    ] = "1d",
    cron: Annotated[
        str | None,
        typer.Option("--cron", help="5-field cron expression (e.g. '0 9 * * *')."),
    ] = None,
    output_language: Annotated[
        str | None,
        typer.Option(
            "--output-language",
            help="'en' | 'zh' | 'none' (skip translation). Default: cfg.general.language.",
        ),
    ] = None,
    enabled: Annotated[
        bool,
        typer.Option("--enabled/--disabled", help="Whether the scheduler should run it."),
    ] = True,
) -> None:
    """Create a digest source backed by a scheduled MiningTask."""
    sources = _parse_sources(rss, url)
    if not sources:
        err_console.print("[red]at least one --rss or --url is required[/red]")
        raise typer.Exit(code=2)

    vault = resolve_vault_or_die()
    cfg = load_config_or_default(vault)
    if output_language is None:
        resolved_lang = cfg.general.language
    elif output_language.lower() in ("none", "off", "source"):
        resolved_lang = None
    else:
        resolved_lang = output_language

    task = build_digest_task(
        name=name,
        sources=sources,
        schedule=_schedule(every, cron),
        output_language=resolved_lang,
        enabled=enabled,
    )
    problems = task.validate()
    if problems:
        err_console.print(f"[red]invalid digest source:[/red] {'; '.join(problems)}")
        raise typer.Exit(code=2)
    path = TaskStore(vault.tasks_dir).save(task)
    console.print(f"[green]created digest source[/green] → {path}")


@app.command("remove")
def digest_remove(
    source_id: Annotated[str, typer.Argument(help="Digest source id (or 8-char prefix).")],
) -> None:
    """Remove a digest source. Drafts it produced stay in drafts/."""
    vault = resolve_vault_or_die()
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
