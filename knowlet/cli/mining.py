"""`knowlet mining` — knowledge-mining task commands."""

from __future__ import annotations

from typing import Annotated, Optional

import typer
from rich.table import Table

from knowlet.cli._common import (
    console,
    err_console,
    load_config_or_default,
    resolve_vault_or_die,
)

app = typer.Typer(help="Knowledge-mining tasks (scenario B).", no_args_is_help=True)


@app.command("list")
def mining_list() -> None:
    """List configured mining tasks."""
    from knowlet.core.mining.task_store import TaskStore

    vault = resolve_vault_or_die()
    store = TaskStore(vault.tasks_dir)
    tasks = store.list()
    if not tasks:
        console.print("[dim]no mining tasks yet — `knowlet mining add` to create one[/dim]")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("id", style="dim", no_wrap=True)
    table.add_column("name")
    table.add_column("schedule")
    table.add_column("sources")
    table.add_column("on?", style="dim")
    for t in tasks:
        sched = (
            t.schedule.every and f"every {t.schedule.every}"
        ) or (t.schedule.cron and f"cron {t.schedule.cron}") or "—"
        srcs = ", ".join(s.url[:40] + ("…" if len(s.url) > 40 else "") for s in t.sources)
        table.add_row(t.id[:8] + "…", t.name, sched, srcs, "yes" if t.enabled else "no")
    console.print(table)


@app.command("add")
def mining_add(
    name: Annotated[str, typer.Option("--name", help="Human-readable task name.")],
    rss: Annotated[
        Optional[str],
        typer.Option("--rss", help="RSS / Atom feed URL (repeatable via comma)."),
    ] = None,
    url: Annotated[
        Optional[str],
        typer.Option("--url", help="Plain URL fetch (repeatable via comma)."),
    ] = None,
    every: Annotated[
        Optional[str],
        typer.Option(
            "--every",
            help="Interval: '30m' / '1h' / '6h' / '1d'. Use --cron for cron expressions.",
        ),
    ] = None,
    cron: Annotated[
        Optional[str],
        typer.Option("--cron", help="5-field cron expression (e.g. '0 9 * * *')."),
    ] = None,
    prompt: Annotated[
        Optional[str],
        typer.Option(
            "--prompt", help="Extraction guidance for the LLM."
        ),
    ] = None,
    output_language: Annotated[
        Optional[str],
        typer.Option(
            "--output-language",
            help="'en' | 'zh' | 'none' (skip translation). "
            "Default: inherit from cfg.general.language.",
        ),
    ] = None,
    max_items_per_run: Annotated[
        int,
        typer.Option(
            "--max-items-per-run",
            help="Hard ceiling on new items processed per run. Protects against an "
            "offline daemon waking up and chewing through a multi-day backlog in "
            "one LLM avalanche. Default 50; pass 0 to disable.",
        ),
    ] = 50,
    max_keep: Annotated[
        int,
        typer.Option(
            "--max-keep",
            help="Soft cap on the live drafts queue for this task. When new items "
            "push the count over the threshold, the oldest drafts are moved to "
            "drafts/.archive/ (recoverable). Default 30; pass 0 to disable.",
        ),
    ] = 30,
    critical_take: Annotated[
        bool,
        typer.Option(
            "--critical-take/--no-critical-take",
            help="M7.3.1: ask the LLM to add a `## Critical take` section with a "
            "content-grounded opinion on each draft (vs the default neutral "
            "summary). Off by default — adds tokens and not every feed warrants "
            "an opinion.",
        ),
    ] = False,
) -> None:
    """Create a new mining task."""
    from knowlet.core.mining.task import MiningTask, Schedule, SourceSpec
    from knowlet.core.mining.task_store import TaskStore

    if not (rss or url):
        err_console.print("[red]at least one --rss or --url is required[/red]")
        raise typer.Exit(code=2)
    if every and cron:
        err_console.print("[red]use --every OR --cron, not both[/red]")
        raise typer.Exit(code=2)

    vault = resolve_vault_or_die()
    cfg = load_config_or_default(vault)
    store = TaskStore(vault.tasks_dir)

    sources: list[SourceSpec] = []
    if rss:
        sources.extend(SourceSpec(type="rss", url=u.strip()) for u in rss.split(",") if u.strip())
    if url:
        sources.extend(SourceSpec(type="url", url=u.strip()) for u in url.split(",") if u.strip())

    if output_language is None:
        resolved_lang = cfg.general.language
    elif output_language.lower() in ("none", "off", "source"):
        resolved_lang = None
    else:
        resolved_lang = output_language

    task = MiningTask(
        name=name,
        sources=sources,
        schedule=Schedule(every=every, cron=cron),
        prompt=prompt or "Summarize each item; surface anything new or surprising.",
        output_language=resolved_lang,
        max_items_per_run=None if max_items_per_run <= 0 else max_items_per_run,
        max_keep=None if max_keep <= 0 else max_keep,
        include_critical_take=critical_take,
    )
    problems = task.validate()
    if problems:
        err_console.print(f"[red]invalid task:[/red] {'; '.join(problems)}")
        raise typer.Exit(code=2)
    path = store.save(task)
    console.print(f"[green]created[/green] → {path}")


@app.command("edit")
def mining_edit(
    task_id: Annotated[str, typer.Argument(help="Task id (or 8-char prefix).")],
) -> None:
    """Open the task's Markdown file in $EDITOR for direct editing."""
    import os
    import subprocess

    from knowlet.core.mining.task_store import TaskStore

    vault = resolve_vault_or_die()
    store = TaskStore(vault.tasks_dir)
    task = store.get(task_id)
    if task is None or task.path is None:
        err_console.print(f"[red]task not found:[/red] {task_id}")
        raise typer.Exit(code=1)
    editor = os.environ.get("EDITOR") or "vi"
    subprocess.run([editor, str(task.path)], check=True)
    console.print(f"[green]edited[/green] → {task.path}")


@app.command("remove")
def mining_remove(
    task_id: Annotated[str, typer.Argument(help="Task id (or 8-char prefix).")],
) -> None:
    """Remove a mining task. The drafts it produced stay in <vault>/drafts/."""
    from knowlet.core.mining.task_store import TaskStore

    vault = resolve_vault_or_die()
    store = TaskStore(vault.tasks_dir)
    if not store.delete(task_id):
        err_console.print(f"[red]task not found:[/red] {task_id}")
        raise typer.Exit(code=1)
    console.print(f"[green]removed[/green] {task_id}")


@app.command("run")
def mining_run(
    task_id: Annotated[str, typer.Argument(help="Task id (or 8-char prefix).")],
    limit: Annotated[
        Optional[int],
        typer.Option(
            "--limit", "-n",
            help="Cap the number of new items processed this run (useful for quick verification).",
        ),
    ] = None,
) -> None:
    """Run a single mining task now."""
    _run_one_task(task_id, limit=limit)


@app.command("reset")
def mining_reset(
    task_id: Annotated[str, typer.Argument(help="Task id (or 8-char prefix).")],
    delete_drafts: Annotated[
        bool,
        typer.Option(
            "--delete-drafts",
            help="Also delete every draft this task previously produced. Without this flag, "
            "only the seen-set is cleared and existing drafts stay.",
        ),
    ] = False,
) -> None:
    """Clear the seen-set so the next run re-extracts everything."""
    from knowlet.core.drafts import DraftStore
    from knowlet.core.mining.runner import reset_task_state
    from knowlet.core.mining.task_store import TaskStore

    vault = resolve_vault_or_die()
    store = TaskStore(vault.tasks_dir)
    task = store.get(task_id)
    if task is None:
        err_console.print(f"[red]task not found:[/red] {task_id}")
        raise typer.Exit(code=1)
    drafts = DraftStore(vault.drafts_dir)
    out = reset_task_state(vault, task.id, drafts=drafts, delete_drafts=delete_drafts)
    console.print(
        f"[green]reset[/green] {task.name} ({task.id[:8]}…)  "
        f"seen_cleared={out['seen_cleared']}  drafts_deleted={out['drafts_deleted']}"
    )


@app.command("run-all")
def mining_run_all() -> None:
    """Run every enabled mining task now."""
    from knowlet.core.llm import LLMClient
    from knowlet.core.mining.runner import run_task
    from knowlet.core.mining.task_store import TaskStore

    vault = resolve_vault_or_die()
    cfg = load_config_or_default(vault)
    if not cfg.llm.api_key:
        err_console.print("[red]LLM api_key is empty. Run `knowlet config init` first.[/red]")
        raise typer.Exit(code=2)
    store = TaskStore(vault.tasks_dir)
    tasks = [t for t in store.list() if t.enabled]
    if not tasks:
        console.print("[dim]no enabled tasks[/dim]")
        return
    llm = LLMClient(cfg.llm)
    for t in tasks:
        console.print(f"[bold]running[/bold] {t.name} ({t.id[:8]}…)")
        report = run_task(
            t, vault, llm, default_output_language=cfg.general.language
        )
        _render_run_report(report)


def _run_one_task(task_id: str, limit: int | None = None) -> None:
    from knowlet.core.llm import LLMClient
    from knowlet.core.mining.runner import run_task
    from knowlet.core.mining.task_store import TaskStore

    vault = resolve_vault_or_die()
    cfg = load_config_or_default(vault)
    if not cfg.llm.api_key:
        err_console.print("[red]LLM api_key is empty. Run `knowlet config init` first.[/red]")
        raise typer.Exit(code=2)
    store = TaskStore(vault.tasks_dir)
    task = store.get(task_id)
    if task is None:
        err_console.print(f"[red]task not found:[/red] {task_id}")
        raise typer.Exit(code=1)
    llm = LLMClient(cfg.llm)
    console.print(f"[bold]running[/bold] {task.name} ({task.id[:8]}…)")
    report = run_task(
        task, vault, llm,
        default_output_language=cfg.general.language,
        max_items=limit,
    )
    _render_run_report(report)


def _render_run_report(report) -> None:
    line = (
        f"  fetched={report.fetched}  new={report.new_items}  "
        f"drafts={report.drafts_created}  skipped_empty={report.skipped_empty}"
    )
    if getattr(report, "drafts_archived", 0):
        line += f"  archived={report.drafts_archived}"
    if report.errors:
        line += f"  errors={len(report.errors)}"
    console.print(line)
    for err in report.errors[:5]:
        console.print(f"  [red]· {err}[/red]")
    if len(report.errors) > 5:
        console.print(f"  [dim]…{len(report.errors) - 5} more errors[/dim]")
