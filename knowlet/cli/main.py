"""knowlet CLI — typer entrypoint."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from knowlet import __version__
from knowlet.config import (
    KnowletConfig,
    VaultNotFoundError,
    config_path,
    find_vault,
    load_config,
    save_config,
)
from knowlet.core.embedding import make_backend
from knowlet.core.i18n import set_language, t
from knowlet.core.index import Index, reindex_vault
from knowlet.core.llm import LLMClient
from knowlet.core.tools._registry import ToolContext, default_registry
from knowlet.core.vault import Vault

app = typer.Typer(
    name="knowlet",
    help="A personal knowledge base that organizes itself.",
    no_args_is_help=False,
    add_completion=False,
)
vault_app = typer.Typer(help="Vault layout and lifecycle.", no_args_is_help=True)
config_app = typer.Typer(help="Configuration.", no_args_is_help=True)
user_app = typer.Typer(
    help="User profile (`<vault>/users/me.md`).",
    no_args_is_help=True,
)
cards_app = typer.Typer(
    help="Spaced-repetition Cards (scenario C).",
    no_args_is_help=True,
)
mining_app = typer.Typer(
    help="Knowledge-mining tasks (scenario B).",
    no_args_is_help=True,
)
drafts_app = typer.Typer(
    help="AI-extracted drafts pending review.",
    no_args_is_help=True,
)
app.add_typer(vault_app, name="vault")
app.add_typer(config_app, name="config")
app.add_typer(user_app, name="user")
app.add_typer(cards_app, name="cards")
app.add_typer(mining_app, name="mining")
app.add_typer(drafts_app, name="drafts")

console = Console()
err_console = Console(stderr=True)


# ------------------------------------------------------------------ utilities


def _resolve_vault_or_die() -> Vault:
    try:
        root = find_vault()
    except VaultNotFoundError as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2) from exc
    return Vault(root)


def _load_config_or_default(vault: Vault) -> KnowletConfig:
    cfg = load_config(vault.root)
    # Activate the configured UI language for everything downstream.
    set_language(cfg.general.language)
    return cfg


def _make_index(vault: Vault, cfg: KnowletConfig) -> Index:
    backend = make_backend(
        cfg.embedding.backend, cfg.embedding.model, cfg.embedding.dim
    )
    idx = Index(vault.db_path, backend)
    idx.connect()
    # Sync dim into config if backend reports something different.
    real_dim = backend.dim
    if real_dim != cfg.embedding.dim:
        cfg.embedding.dim = real_dim
        save_config(vault.root, cfg)
    return idx


def _mask(value: str, keep: int = 4) -> str:
    if not value:
        return ""
    if len(value) <= keep:
        return "*" * len(value)
    return value[:keep] + "*" * (len(value) - keep)


# ------------------------------------------------------------------ root


@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
    version: Annotated[
        bool, typer.Option("--version", help="Show version and exit.", is_eager=True)
    ] = False,
) -> None:
    if version:
        console.print(f"knowlet {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        # Bare `knowlet` → drop into chat. Subcommands stay available via
        # `knowlet --help` / `knowlet <name>` for scripting and one-off ops.
        _run_chat(save_after=False)
        raise typer.Exit()


# ------------------------------------------------------------------ vault


@vault_app.command("init")
def vault_init(
    path: Annotated[
        Optional[Path],
        typer.Argument(help="Vault directory. Defaults to current directory."),
    ] = None,
) -> None:
    """Create the on-disk layout for a knowlet vault."""
    target = (path or Path.cwd()).resolve()
    target.mkdir(parents=True, exist_ok=True)
    vault = Vault(target)
    vault.init_layout()
    cfg_path = config_path(vault.root)
    if not cfg_path.exists():
        save_config(vault.root, KnowletConfig())
    # Apply the (just-saved or pre-existing) language for the success banner.
    cfg = load_config(vault.root)
    set_language(cfg.general.language)
    console.print(
        Panel.fit(
            t("vault.init.banner", root=str(vault.root)),
            title=t("vault.init.title"),
        )
    )


# ------------------------------------------------------------------ config


@config_app.command("init")
def config_init() -> None:
    """Interactive wizard: configure the LLM endpoint and embedding model."""
    vault = _resolve_vault_or_die()
    cfg = _load_config_or_default(vault)

    # Language first — every subsequent prompt rendering will follow it.
    console.print(f"[bold]{t('config.lang.title')}[/bold]")
    cfg.general.language = Prompt.ask(
        t("config.lang.prompt"),
        default=cfg.general.language,
        choices=["en", "zh"],
    )
    set_language(cfg.general.language)

    console.print(
        Panel.fit(
            t("config.llm.intro"),
            title=t("config.llm.title"),
        )
    )
    cfg.llm.base_url = Prompt.ask(t("config.base_url.prompt"), default=cfg.llm.base_url)
    cfg.llm.model = Prompt.ask(t("config.model.prompt"), default=cfg.llm.model)
    api_key = Prompt.ask(
        t("config.api_key.prompt"),
        default=(_mask(cfg.llm.api_key) if cfg.llm.api_key else ""),
        password=True,
    )
    if api_key and not api_key.startswith("****"):
        cfg.llm.api_key = api_key

    console.print()
    console.print(f"[bold]{t('config.embed.title')}[/bold]")
    cfg.embedding.backend = Prompt.ask(
        t("config.embed.backend.prompt"),
        default=cfg.embedding.backend,
        choices=["sentence_transformers", "dummy"],
    )
    cfg.embedding.model = Prompt.ask(t("config.embed.model.prompt"), default=cfg.embedding.model)

    save_config(vault.root, cfg)
    console.print(
        Panel.fit(
            t("config.saved", path=str(config_path(vault.root))) + "\n\n" + t("config.next"),
            title=t("vault.init.title"),
        )
    )


@config_app.command("set")
def config_set(
    key: Annotated[
        str,
        typer.Argument(
            help="Dotted path: llm.base_url, llm.api_key, llm.model, llm.temperature, "
            "embedding.backend, embedding.model, retrieval.chunk_size, etc.",
        ),
    ],
    value: Annotated[str, typer.Argument(help="Value to set (string; coerced by type).")],
) -> None:
    """Non-interactive single-field update of the config.

    Designed for scripts/agents and for users who don't want the wizard:
        knowlet config set llm.base_url http://127.0.0.1:8317/v1
        knowlet config set llm.model claude-opus-4-7
        knowlet config set llm.api_key sk-...
    """
    vault = _resolve_vault_or_die()
    cfg = _load_config_or_default(vault)
    parts = key.split(".")
    if len(parts) != 2 or parts[0] not in {"general", "llm", "embedding", "retrieval"}:
        err_console.print(
            f"[red]invalid key {key!r}; expected <section>.<field> "
            f"where section is general | llm | embedding | retrieval[/red]"
        )
        raise typer.Exit(code=2)
    section_name, field = parts
    section = getattr(cfg, section_name)
    if not hasattr(section, field):
        err_console.print(f"[red]unknown field: {section_name}.{field}[/red]")
        raise typer.Exit(code=2)

    # Coerce value to the field's declared type.
    field_type = type(getattr(section, field))
    try:
        coerced: object
        if field_type is bool:
            coerced = value.lower() in {"1", "true", "yes", "y", "on"}
        elif field_type is int:
            coerced = int(value)
        elif field_type is float:
            coerced = float(value)
        else:
            coerced = value
    except ValueError as exc:
        err_console.print(f"[red]value {value!r} not convertible to {field_type.__name__}: {exc}[/red]")
        raise typer.Exit(code=2) from exc

    setattr(section, field, coerced)
    save_config(vault.root, cfg)
    # If language changed, re-apply immediately so the success line uses it.
    if section_name == "general" and field == "language":
        set_language(str(coerced))
    shown = _mask(str(coerced)) if field == "api_key" else coerced
    console.print(f"[green]✓[/green] {key} = {shown}")


@config_app.command("show")
def config_show() -> None:
    """Print the current config (with API key masked)."""
    vault = _resolve_vault_or_die()
    cfg = _load_config_or_default(vault)
    safe = cfg.model_dump()
    safe["llm"]["api_key"] = _mask(cfg.llm.api_key)
    console.print(json.dumps(safe, indent=2, ensure_ascii=False))
    console.print(f"[dim]{config_path(vault.root)}[/dim]")


# ------------------------------------------------------------------ cards


@cards_app.command("new")
def cards_new(
    front: Annotated[str, typer.Option("--front", "-f", help="Card front (cue).")],
    back: Annotated[str, typer.Option("--back", "-b", help="Card back (answer).")],
    tags: Annotated[
        Optional[str],
        typer.Option("--tags", "-t", help="Comma-separated tags."),
    ] = None,
    card_type: Annotated[
        str,
        typer.Option("--type", help="basic | cloze (default basic)."),
    ] = "basic",
) -> None:
    """Create a new spaced-repetition Card. The new card is due immediately."""
    from knowlet.core.card import Card
    from knowlet.core.cards import CardStore
    from knowlet.core.fsrs_wrap import initial_state

    vault = _resolve_vault_or_die()
    store = CardStore(vault.cards_dir)
    parsed_tags = (
        [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    )
    card = Card(
        type=card_type,
        front=front,
        back=back,
        tags=parsed_tags,
        fsrs_state=initial_state(),
    )
    path = store.save(card)
    console.print(f"[green]created[/green] → {path}")


@cards_app.command("due")
def cards_due(
    limit: Annotated[int, typer.Option("--limit", "-n", help="Max rows.")] = 20,
) -> None:
    """List Cards that are due now."""
    from knowlet.core.card import parse_due
    from knowlet.core.cards import CardStore

    vault = _resolve_vault_or_die()
    store = CardStore(vault.cards_dir)
    due = store.list_due(limit=limit)
    if not due:
        console.print("[dim]nothing due — create cards or come back later[/dim]")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("id", style="dim", no_wrap=True)
    table.add_column("front")
    table.add_column("tags", style="cyan")
    table.add_column("due", style="dim")
    for c in due:
        table.add_row(
            c.id[:8] + "…",
            c.front[:60] + ("…" if len(c.front) > 60 else ""),
            ", ".join(c.tags),
            parse_due(c).strftime("%Y-%m-%d %H:%M"),
        )
    console.print(table)


@cards_app.command("review")
def cards_review(
    limit: Annotated[
        int,
        typer.Option("--limit", "-n", help="Max cards in this session."),
    ] = 20,
) -> None:
    """Walk through due Cards interactively, recording ratings."""
    _run_cards_review(limit=limit)


def _run_cards_review(limit: int = 20) -> None:
    from knowlet.core.card import parse_due
    from knowlet.core.cards import CardStore
    from knowlet.core.fsrs_wrap import schedule_next

    vault = _resolve_vault_or_die()
    store = CardStore(vault.cards_dir)
    due = store.list_due(limit=limit)
    if not due:
        console.print("[dim]nothing due — create cards or come back later[/dim]")
        return

    console.print(
        Panel.fit(
            f"reviewing {len(due)} card(s)\n"
            "rate yourself: 1=again  2=hard  3=good  4=easy   q=quit",
            title="cards review",
        )
    )
    for i, card in enumerate(due, 1):
        console.print(f"\n[bold cyan]{i}/{len(due)}[/bold cyan]")
        console.print(Panel(Markdown(card.front), title="front"))
        try:
            Prompt.ask("press [enter] to reveal", default="", show_default=False)
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]exiting review[/dim]")
            return
        console.print(Panel(Markdown(card.back), title="back"))
        try:
            rating = Prompt.ask(
                "your recall",
                choices=["1", "2", "3", "4", "q"],
                default="3",
            )
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]exiting review[/dim]")
            return
        if rating == "q":
            console.print("[dim]exiting review[/dim]")
            return
        schedule_next(card, int(rating))
        store.save(card)
        console.print(
            f"[dim]next due: {parse_due(card).strftime('%Y-%m-%d %H:%M')}[/dim]"
        )
    console.print("\n[green]done[/green]")


@cards_app.command("show")
def cards_show(
    card_id: Annotated[str, typer.Argument(help="Card ULID (full or 8-char prefix).")],
) -> None:
    """Print a single Card's content."""
    from knowlet.core.cards import CardStore

    vault = _resolve_vault_or_die()
    store = CardStore(vault.cards_dir)
    card = store.get(card_id)
    if card is None:
        # try prefix match for convenience
        for c in store.list_cards():
            if c.id.startswith(card_id):
                card = c
                break
    if card is None:
        err_console.print(f"[red]card not found:[/red] {card_id}")
        raise typer.Exit(code=1)
    console.print(Panel(Markdown(card.front), title="front"))
    console.print(Panel(Markdown(card.back), title="back"))
    console.print(
        f"[dim]tags: {', '.join(card.tags) or '—'}  ·  "
        f"due: {card.fsrs_state.get('due') or '—'}[/dim]"
    )


# ------------------------------------------------------------------ mining


@mining_app.command("list")
def mining_list() -> None:
    """List configured mining tasks."""
    from knowlet.core.mining.tasks import TaskStore

    vault = _resolve_vault_or_die()
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


@mining_app.command("add")
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
) -> None:
    """Create a new mining task."""
    from knowlet.core.mining.task import MiningTask, Schedule, SourceSpec
    from knowlet.core.mining.tasks import TaskStore

    if not (rss or url):
        err_console.print("[red]at least one --rss or --url is required[/red]")
        raise typer.Exit(code=2)
    if every and cron:
        err_console.print("[red]use --every OR --cron, not both[/red]")
        raise typer.Exit(code=2)

    vault = _resolve_vault_or_die()
    cfg = _load_config_or_default(vault)
    store = TaskStore(vault.tasks_dir)

    sources: list[SourceSpec] = []
    if rss:
        sources.extend(SourceSpec(type="rss", url=u.strip()) for u in rss.split(",") if u.strip())
    if url:
        sources.extend(SourceSpec(type="url", url=u.strip()) for u in url.split(",") if u.strip())

    # output_language resolution: explicit > "none" sentinel disables > cfg.general.language
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
    )
    problems = task.validate()
    if problems:
        err_console.print(f"[red]invalid task:[/red] {'; '.join(problems)}")
        raise typer.Exit(code=2)
    path = store.save(task)
    console.print(f"[green]created[/green] → {path}")


@mining_app.command("edit")
def mining_edit(
    task_id: Annotated[str, typer.Argument(help="Task id (or 8-char prefix).")],
) -> None:
    """Open the task's Markdown file in $EDITOR for direct editing."""
    import os
    import subprocess

    from knowlet.core.mining.tasks import TaskStore

    vault = _resolve_vault_or_die()
    store = TaskStore(vault.tasks_dir)
    task = store.get(task_id)
    if task is None or task.path is None:
        err_console.print(f"[red]task not found:[/red] {task_id}")
        raise typer.Exit(code=1)
    editor = os.environ.get("EDITOR") or "vi"
    subprocess.run([editor, str(task.path)], check=True)
    console.print(f"[green]edited[/green] → {task.path}")


@mining_app.command("remove")
def mining_remove(
    task_id: Annotated[str, typer.Argument(help="Task id (or 8-char prefix).")],
) -> None:
    """Remove a mining task. The drafts it produced stay in <vault>/drafts/."""
    from knowlet.core.mining.tasks import TaskStore

    vault = _resolve_vault_or_die()
    store = TaskStore(vault.tasks_dir)
    if not store.delete(task_id):
        err_console.print(f"[red]task not found:[/red] {task_id}")
        raise typer.Exit(code=1)
    console.print(f"[green]removed[/green] {task_id}")


@mining_app.command("run")
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


@mining_app.command("reset")
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
    """Clear the seen-set so the next run re-extracts everything. Useful when
    you've changed `output_language` / `prompt` and want fresh drafts."""
    from knowlet.core.drafts import DraftStore
    from knowlet.core.mining.runner import reset_task_state
    from knowlet.core.mining.tasks import TaskStore

    vault = _resolve_vault_or_die()
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


@mining_app.command("run-all")
def mining_run_all() -> None:
    """Run every enabled mining task now."""
    from knowlet.core.llm import LLMClient
    from knowlet.core.mining.runner import run_task
    from knowlet.core.mining.tasks import TaskStore

    vault = _resolve_vault_or_die()
    cfg = _load_config_or_default(vault)
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
    from knowlet.core.mining.tasks import TaskStore

    vault = _resolve_vault_or_die()
    cfg = _load_config_or_default(vault)
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
    if report.errors:
        line += f"  errors={len(report.errors)}"
    console.print(line)
    for err in report.errors[:5]:
        console.print(f"  [red]· {err}[/red]")
    if len(report.errors) > 5:
        console.print(f"  [dim]…{len(report.errors) - 5} more errors[/dim]")


# ------------------------------------------------------------------ drafts


@drafts_app.command("list")
def drafts_list() -> None:
    """List drafts pending review."""
    from knowlet.core.drafts import DraftStore

    vault = _resolve_vault_or_die()
    store = DraftStore(vault.drafts_dir)
    drafts = store.list()
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


@drafts_app.command("show")
def drafts_show(
    draft_id: Annotated[str, typer.Argument(help="Draft id (or 8-char prefix).")],
) -> None:
    """Print a draft's full body."""
    from knowlet.core.drafts import DraftStore

    vault = _resolve_vault_or_die()
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


@drafts_app.command("approve")
def drafts_approve(
    draft_id: Annotated[str, typer.Argument(help="Draft id (or 8-char prefix).")],
) -> None:
    """Promote a draft to a Note and remove it from drafts/."""
    _draft_approve_or_reject(draft_id, approve=True)


@drafts_app.command("reject")
def drafts_reject(
    draft_id: Annotated[str, typer.Argument(help="Draft id (or 8-char prefix).")],
) -> None:
    """Delete a draft."""
    _draft_approve_or_reject(draft_id, approve=False)


def _draft_approve_or_reject(draft_id: str, *, approve: bool) -> None:
    from knowlet.core.drafts import DraftStore
    from knowlet.core.embedding import make_backend
    from knowlet.core.index import Index

    vault = _resolve_vault_or_die()
    cfg = _load_config_or_default(vault)
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


# ------------------------------------------------------------------ web


@app.command("web")
def web(
    host: Annotated[
        str,
        typer.Option("--host", help="Bind address. Default 127.0.0.1 (localhost only)."),
    ] = "127.0.0.1",
    port: Annotated[
        int,
        typer.Option("--port", help="Port. Default 8765."),
    ] = 8765,
) -> None:
    """Start the local web UI (http://127.0.0.1:8765 by default).

    Single-user, localhost-only. No auth. Reuses the same backend modules as
    the CLI — every UI action has a CLI mirror by design (see ADR-0008).
    """
    from knowlet.web.server import create_app

    vault = _resolve_vault_or_die()
    cfg = _load_config_or_default(vault)
    if not cfg.llm.api_key:
        err_console.print(
            "[red]LLM api_key is empty. Run `knowlet config init` first.[/red]"
        )
        raise typer.Exit(code=2)

    try:
        import uvicorn
    except ImportError as exc:  # noqa: F841
        err_console.print(
            "[red]uvicorn is not installed. Reinstall knowlet to pull web deps.[/red]"
        )
        raise typer.Exit(code=2)

    # Long-running process — make sure scheduler / mining / LLM errors land
    # somewhere the user can find them, even if they close the terminal.
    from knowlet._logging import configure_logging
    configure_logging(vault.root)

    fastapi_app = create_app(vault, cfg)
    console.print(
        Panel.fit(
            f"knowlet web · http://{host}:{port}\n"
            f"vault={vault.root.name}  model={cfg.llm.model}\n"
            "Ctrl-C to stop.",
            title=f"knowlet {__version__}",
        )
    )
    uvicorn.run(fastapi_app, host=host, port=port, log_level="warning")


# ------------------------------------------------------------------ user profile


@user_app.command("show")
def user_show() -> None:
    """Print the user profile (or note that none exists yet)."""
    from knowlet.core.user_profile import read_profile

    vault = _resolve_vault_or_die()
    profile = read_profile(vault.profile_path)
    if profile is None:
        console.print(
            "[dim]no profile yet — `knowlet user edit` to create one.[/dim]"
        )
        return
    console.print(Panel(Markdown(profile.body), title=str(vault.profile_path)))
    console.print(f"[dim]updated_at: {profile.updated_at}[/dim]")


@user_app.command("edit")
def user_edit() -> None:
    """Open the user profile in $EDITOR (creates a default template if missing)."""
    from knowlet.core.user_profile import edit_profile_in_editor

    vault = _resolve_vault_or_die()
    try:
        profile = edit_profile_in_editor(vault.profile_path)
    except FileNotFoundError as exc:
        err_console.print(
            f"[red]editor not found:[/red] {exc} — set $EDITOR to a working editor."
        )
        raise typer.Exit(code=2) from exc
    except Exception as exc:  # noqa: BLE001
        err_console.print(f"[red]editor failed:[/red] {exc}")
        raise typer.Exit(code=2) from exc
    console.print(f"[green]profile saved[/green] → {profile.path}")


# ------------------------------------------------------------------ ls / reindex


@app.command("ls")
def ls(
    recent: Annotated[
        bool,
        typer.Option("--recent", help="Sort by updated_at (default is created_at)."),
    ] = False,
    limit: Annotated[int, typer.Option("--limit", "-n", help="Max rows.")] = 20,
) -> None:
    """List Notes in the current vault."""
    vault = _resolve_vault_or_die()
    cfg = _load_config_or_default(vault)
    idx = _make_index(vault, cfg)
    try:
        rows = idx.list_notes(limit=limit, order="updated_at" if recent else "created_at")
    finally:
        idx.close()
    if not rows:
        console.print("[dim]no notes yet — start a chat and use :save[/dim]")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("id", style="dim", no_wrap=True)
    table.add_column("title")
    table.add_column("tags", style="cyan")
    table.add_column("updated_at" if recent else "created_at", style="dim")
    for r in rows:
        table.add_row(
            r["id"][:8] + "…",
            r["title"],
            ", ".join(r["tags"]),
            r["updated_at"] if recent else r["created_at"],
        )
    console.print(table)


@app.command("reindex")
def reindex(
    rebuild: Annotated[
        bool,
        typer.Option(
            "--rebuild",
            help="Drop the index DB and rebuild from disk. Use after switching embedding models.",
        ),
    ] = False,
) -> None:
    """Rebuild the index from on-disk Notes."""
    vault = _resolve_vault_or_die()
    cfg = _load_config_or_default(vault)
    if rebuild and vault.db_path.exists():
        vault.db_path.unlink()
        console.print(f"[dim]dropped {vault.db_path}[/dim]")
    backend = make_backend(cfg.embedding.backend, cfg.embedding.model, cfg.embedding.dim)
    if backend.dim != cfg.embedding.dim:
        cfg.embedding.dim = backend.dim
        save_config(vault.root, cfg)
    changed, deleted, unchanged = reindex_vault(
        vault.root,
        vault.db_path,
        backend,
        chunk_size=cfg.retrieval.chunk_size,
        chunk_overlap=cfg.retrieval.chunk_overlap,
        note_paths=list(vault.iter_note_paths()),
    )
    console.print(
        f"reindex done: {changed} updated, {deleted} removed, {unchanged} unchanged"
    )


# ------------------------------------------------------------------ doctor


@app.command("doctor")
def doctor(
    skip_llm: Annotated[
        bool,
        typer.Option("--skip-llm", help="Don't call the LLM endpoint."),
    ] = False,
    skip_embedding: Annotated[
        bool,
        typer.Option("--skip-embedding", help="Don't load the embedding backend."),
    ] = False,
) -> None:
    """Smoke-test the configured vault + LLM endpoint + embedding stack.

    Useful when wiring up an OpenAI-compatible wrapper around Claude Code /
    Codex / Ollama / etc. — confirms that knowlet can speak to the proxy and
    that tool-calling works.
    """
    try:
        vault_root = find_vault()
    except VaultNotFoundError as exc:
        _print_doctor([("fail", "vault", str(exc))])
        raise typer.Exit(code=1) from exc
    vault = Vault(vault_root)
    cfg = _load_config_or_default(vault)
    results = _run_doctor_checks(vault, cfg, skip_llm=skip_llm, skip_embedding=skip_embedding)
    _print_doctor(results)
    if any(r[0] == "fail" for r in results):
        raise typer.Exit(code=1)


def _run_doctor_checks(
    vault: Vault,
    cfg: KnowletConfig,
    *,
    skip_llm: bool = False,
    skip_embedding: bool = False,
) -> list[tuple[str, str, str]]:
    """Pure check logic — produces a list of (status, name, detail) tuples.

    Reusable from both the `doctor` CLI command and the `:doctor` REPL slash.
    """
    from knowlet.core.index import IndexDimensionMismatchError

    results: list[tuple[str, str, str]] = []

    def ok(name: str, detail: str = "") -> None:
        results.append(("ok", name, detail))

    def fail(name: str, detail: str) -> None:
        results.append(("fail", name, detail))

    def warn(name: str, detail: str) -> None:
        results.append(("warn", name, detail))

    ok("vault", str(vault.root))
    ok("config file", str(config_path(vault.root)))
    if cfg.llm.api_key:
        ok("llm.api_key", "set")
    else:
        warn("llm.api_key", "empty — `knowlet config init` to set")
    ok("llm.base_url", cfg.llm.base_url)
    ok("llm.model", cfg.llm.model)
    ok("embedding.backend", f"{cfg.embedding.backend} ({cfg.embedding.model})")

    backend = None
    if skip_embedding:
        warn("embedding load", "skipped")
    else:
        try:
            backend = make_backend(cfg.embedding.backend, cfg.embedding.model, cfg.embedding.dim)
            v = backend.embed_query("test")
            ok("embedding load", f"dim={backend.dim}, sample shape={v.shape}")
            if backend.dim != cfg.embedding.dim:
                cfg.embedding.dim = backend.dim
                save_config(vault.root, cfg)
                warn("embedding dim", f"updated cfg.embedding.dim → {backend.dim}")
        except Exception as exc:  # noqa: BLE001
            fail("embedding load", f"{type(exc).__name__}: {exc}")

    if backend is not None:
        try:
            idx = Index(vault.db_path, backend)
            idx.connect()
            n = len(idx.list_notes(limit=10000))
            idx.close()
            ok("index", f"{n} note(s) indexed")
        except IndexDimensionMismatchError as exc:
            fail("index dim", str(exc))
        except Exception as exc:  # noqa: BLE001
            fail("index", f"{type(exc).__name__}: {exc}")
    else:
        warn("index", "skipped (no embedding backend)")

    if skip_llm:
        warn("llm ping", "skipped")
    elif not cfg.llm.api_key:
        warn("llm ping", "skipped (no api_key)")
    else:
        llm = LLMClient(cfg.llm)
        try:
            resp = llm.chat(
                [{"role": "user", "content": "Reply with exactly: pong"}],
                max_tokens=8,
                temperature=0,
            )
            content = (resp.content or "").strip()
            if "pong" in content.lower():
                ok("llm ping", f"got {content!r}")
            else:
                warn("llm ping", f"unexpected reply {content!r}")
        except Exception as exc:  # noqa: BLE001
            fail("llm ping", f"{type(exc).__name__}: {exc} — check base_url / api_key / network")

        try:
            registry = default_registry()
            resp = llm.chat(
                [
                    {
                        "role": "user",
                        "content": (
                            "Call the search_notes tool with query='ping' and limit=1. "
                            "Do not answer in prose."
                        ),
                    }
                ],
                tools=registry.openai_schema(),
                max_tokens=128,
                temperature=0,
            )
            if resp.tool_calls:
                names = ", ".join(tc.name for tc in resp.tool_calls)
                ok("llm tool-calling", f"{len(resp.tool_calls)} call(s): {names}")
            else:
                fail(
                    "llm tool-calling",
                    "no tool_calls in response — backend may not support OpenAI tool-calling",
                )
        except Exception as exc:  # noqa: BLE001
            fail("llm tool-calling", f"{type(exc).__name__}: {exc}")

    return results


def _print_doctor(results: list[tuple[str, str, str]]) -> None:
    icons = {"ok": "[green]✓[/green]", "fail": "[red]✗[/red]", "warn": "[yellow]⚠[/yellow]"}
    table = Table(show_header=True, header_style="bold", box=None)
    table.add_column("", width=2)
    table.add_column("check", style="bold")
    table.add_column("detail", overflow="fold")
    for status, name, detail in results:
        table.add_row(icons[status], name, detail)
    console.print(table)
    failures = sum(1 for r in results if r[0] == "fail")
    warnings = sum(1 for r in results if r[0] == "warn")
    if failures:
        console.print(f"\n[red]doctor: {failures} failure(s), {warnings} warning(s)[/red]")
    elif warnings:
        console.print(f"\n[yellow]doctor: {warnings} warning(s)[/yellow]")
    else:
        console.print("\n[green]doctor: all checks passed[/green]")


# ------------------------------------------------------------------ chat


@app.command("chat")
def chat(
    save_after: Annotated[
        bool,
        typer.Option(
            "--save-after",
            help="After exit, prompt to sediment the conversation into a Note.",
        ),
    ] = False,
) -> None:
    """Start an interactive chat REPL backed by the vault."""
    _run_chat(save_after=save_after)


def _run_chat(*, save_after: bool) -> None:
    """Inner chat entry — also called by the bare-`knowlet` root callback."""
    from knowlet.chat.bootstrap import ChatNotReadyError, bootstrap_chat
    from knowlet.core.index import IndexDimensionMismatchError

    vault, cfg = _ensure_ready_or_wizard()

    try:
        runtime, report = bootstrap_chat(vault, cfg)
    except ChatNotReadyError as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2) from exc
    except IndexDimensionMismatchError as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2) from exc

    if report.pruned_conversations:
        console.print(
            f"[dim]pruned {report.pruned_conversations} old conversation log(s)[/dim]"
        )

    console.print(
        Panel.fit(
            t(
                "chat.banner.body",
                vault=runtime.vault.root.name,
                model=runtime.config.llm.model,
            ),
            title=t("chat.banner.title", version=__version__),
        )
    )

    try:
        while True:
            try:
                user_text = Prompt.ask(t("chat.prompt")).strip()
            except (EOFError, KeyboardInterrupt):
                console.print()
                break

            if not user_text:
                continue

            if user_text.startswith(":") or user_text == "?":
                handled, should_quit = _handle_slash(user_text, runtime)
                if should_quit:
                    break
                if handled:
                    continue

            try:
                _stream_turn_to_console(runtime, user_text)
            except Exception as exc:  # noqa: BLE001
                err_console.print(f"[red]LLM error:[/red] {exc}")
                continue
    finally:
        if save_after:
            _do_sediment(runtime, quiet_skip=True)
        try:
            convo_path = runtime.convo.write(runtime.session.history)
            if convo_path is not None:
                console.print(f"[dim]conversation saved → {convo_path}[/dim]")
        except Exception as exc:  # noqa: BLE001
            err_console.print(f"[yellow]could not save conversation log: {exc}[/yellow]")
        runtime.close()


# ------------------------------------------------------------------ slash commands


def _handle_slash(text: str, runtime) -> tuple[bool, bool]:
    """Dispatch a slash command. Returns (handled, should_quit)."""
    parts = text[1:].split() if text.startswith(":") else [text.lstrip("?")]
    if not parts or not parts[0]:
        _print_help()
        return True, False
    name = parts[0].lower()
    args = parts[1:]

    if name in ("quit", "exit", "q"):
        return True, True
    if name in ("help", "h", ""):
        _print_help()
        return True, False
    if name == "clear":
        runtime.session.history = runtime.session.history[:1]
        console.print(f"[dim]{t('chat.history.cleared')}[/dim]")
        return True, False
    if name == "save":
        _do_sediment(runtime)
        return True, False
    if name == "ls":
        recent = "--recent" in args or "-r" in args
        rows = runtime.index.list_notes(
            limit=20, order="updated_at" if recent else "created_at"
        )
        _render_notes_table(rows, recent=recent)
        return True, False
    if name == "reindex":
        from knowlet.core.index import reindex_vault as _reindex

        changed, deleted, unchanged = _reindex(
            runtime.vault.root,
            runtime.vault.db_path,
            runtime.backend,
            chunk_size=runtime.config.retrieval.chunk_size,
            chunk_overlap=runtime.config.retrieval.chunk_overlap,
            note_paths=list(runtime.vault.iter_note_paths()),
        )
        # The reindex closes the connection; reopen for the live session.
        runtime.index = Index(runtime.vault.db_path, runtime.backend)
        runtime.index.connect()
        runtime.ctx.index = runtime.index
        console.print(
            f"[dim]reindex: {changed} updated, {deleted} removed, {unchanged} unchanged[/dim]"
        )
        return True, False
    if name == "doctor":
        results = _run_doctor_checks(
            runtime.vault, runtime.config, skip_llm=False, skip_embedding=False
        )
        _print_doctor(results)
        return True, False
    if name == "config":
        sub = args[0] if args else "show"
        if sub == "show":
            safe = runtime.config.model_dump()
            safe["llm"]["api_key"] = _mask(runtime.config.llm.api_key)
            console.print(json.dumps(safe, indent=2, ensure_ascii=False))
        else:
            console.print(
                "[yellow]inside the chat REPL, only `:config show` is supported.\n"
                "for edits, exit and run `knowlet config set <key> <value>`.[/yellow]"
            )
        return True, False
    if name == "tools":
        names = sorted(runtime.registry.tools)
        console.print(f"[dim]available tools: {', '.join(names)}[/dim]")
        return True, False
    if name == "mining":
        sub = args[0] if args else "list"
        if sub == "list":
            tasks = runtime.ctx.tasks.list()
            if not tasks:
                console.print("[dim]no mining tasks; `knowlet mining add` to create one[/dim]")
            else:
                table = Table(show_header=True, header_style="bold")
                table.add_column("id", style="dim", no_wrap=True)
                table.add_column("name")
                table.add_column("schedule")
                table.add_column("on?")
                for task in tasks:
                    sched = (
                        (task.schedule.every and f"every {task.schedule.every}")
                        or (task.schedule.cron and f"cron {task.schedule.cron}")
                        or "—"
                    )
                    table.add_row(
                        task.id[:8] + "…",
                        task.name,
                        sched,
                        "yes" if task.enabled else "no",
                    )
                console.print(table)
        elif sub == "run":
            if len(args) < 2:
                console.print("[yellow]usage: :mining run <task_id>[/yellow]")
            else:
                from knowlet.core.mining.runner import run_task as _run

                task = runtime.ctx.tasks.get(args[1])
                if task is None:
                    console.print(f"[red]task not found:[/red] {args[1]}")
                else:
                    report = _run(
                        task,
                        runtime.vault,
                        runtime.llm,
                        drafts=runtime.ctx.drafts,
                        default_output_language=runtime.config.general.language,
                    )
                    _render_run_report(report)
        elif sub == "run-all":
            from knowlet.core.mining.runner import run_task as _run

            tasks = [task for task in runtime.ctx.tasks.list() if task.enabled]
            if not tasks:
                console.print("[dim]no enabled tasks[/dim]")
            for task in tasks:
                console.print(f"[bold]{task.name}[/bold] ({task.id[:8]}…)")
                report = _run(
                    task,
                    runtime.vault,
                    runtime.llm,
                    drafts=runtime.ctx.drafts,
                    default_output_language=runtime.config.general.language,
                )
                _render_run_report(report)
        else:
            console.print(
                f"[yellow]unknown :mining subcommand: {sub}  "
                f"(use list | run <id> | run-all)[/yellow]"
            )
        return True, False
    if name == "drafts":
        sub = args[0] if args else "list"
        if sub == "list":
            drafts = runtime.ctx.drafts.list()
            if not drafts:
                console.print("[dim]inbox empty[/dim]")
            else:
                table = Table(show_header=True, header_style="bold")
                table.add_column("id", style="dim", no_wrap=True)
                table.add_column("title")
                table.add_column("source", style="cyan", overflow="fold")
                table.add_column("when", style="dim")
                for d in drafts:
                    table.add_row(d.id[:8] + "…", d.title, (d.source or "")[:60], d.created_at)
                console.print(table)
        elif sub in ("show", "approve", "reject"):
            if len(args) < 2:
                console.print(f"[yellow]usage: :drafts {sub} <draft_id>[/yellow]")
                return True, False
            d = runtime.ctx.drafts.get(args[1])
            if d is None:
                console.print(f"[red]draft not found:[/red] {args[1]}")
                return True, False
            if sub == "show":
                console.print(Panel(Markdown(d.body), title=d.title))
            elif sub == "reject":
                runtime.ctx.drafts.delete(d.id)
                console.print(f"[green]rejected[/green] {d.id[:8]}…")
            elif sub == "approve":
                note = d.to_note()
                path = runtime.vault.write_note(note)
                note.path = path
                runtime.index.upsert_note(
                    note,
                    chunk_size=runtime.config.retrieval.chunk_size,
                    chunk_overlap=runtime.config.retrieval.chunk_overlap,
                )
                runtime.ctx.drafts.delete(d.id)
                console.print(f"[green]approved[/green] → {path}")
        else:
            console.print(
                f"[yellow]unknown :drafts subcommand: {sub}  "
                f"(use list | show <id> | approve <id> | reject <id>)[/yellow]"
            )
        return True, False
    if name == "cards":
        sub = args[0] if args else "due"
        if sub == "due":
            from knowlet.core.card import parse_due

            due = runtime.ctx.cards.list_due(limit=20)
            if not due:
                console.print("[dim]nothing due — `:cards new` to create[/dim]")
            else:
                table = Table(show_header=True, header_style="bold")
                table.add_column("id", style="dim", no_wrap=True)
                table.add_column("front")
                table.add_column("tags", style="cyan")
                table.add_column("due", style="dim")
                for c in due:
                    table.add_row(
                        c.id[:8] + "…",
                        c.front[:60] + ("…" if len(c.front) > 60 else ""),
                        ", ".join(c.tags),
                        parse_due(c).strftime("%Y-%m-%d %H:%M"),
                    )
                console.print(table)
        elif sub == "review":
            _run_cards_review(limit=20)
        elif sub == "new":
            console.print(
                "[yellow]inside chat, ask me to create the card "
                "(e.g. \"add a card: front=… back=…\") or run "
                "`knowlet cards new` from a separate shell.[/yellow]"
            )
        else:
            console.print(
                f"[yellow]unknown :cards subcommand: {sub}  (use due | review | new)[/yellow]"
            )
        return True, False
    if name == "user":
        from knowlet.core.user_profile import edit_profile_in_editor, read_profile

        sub = args[0] if args else "show"
        if sub == "show":
            profile = read_profile(runtime.vault.profile_path)
            if profile is None:
                console.print(
                    "[dim]no profile yet — `:user edit` to create one.[/dim]"
                )
            else:
                console.print(
                    Panel(Markdown(profile.body), title=str(runtime.vault.profile_path))
                )
                console.print(f"[dim]updated_at: {profile.updated_at}[/dim]")
        elif sub == "edit":
            try:
                profile = edit_profile_in_editor(runtime.vault.profile_path)
            except Exception as exc:  # noqa: BLE001
                err_console.print(f"[red]editor failed:[/red] {exc}")
                return True, False
            # Reload into the runtime so subsequent turns see the new profile.
            runtime.user_profile = profile
            from knowlet.chat.prompts import build_chat_system_prompt

            new_system = build_chat_system_prompt(profile.truncated_for_prompt())
            if runtime.session.history and runtime.session.history[0]["role"] == "system":
                runtime.session.history[0]["content"] = new_system
            console.print(f"[green]profile saved[/green] → {profile.path}")
        else:
            console.print(
                f"[yellow]unknown :user subcommand: {sub}  (use show | edit)[/yellow]"
            )
        return True, False

    console.print(f"[yellow]unknown slash command: :{name}  (try :help)[/yellow]")
    return True, False


def _stream_turn_to_console(runtime, user_text: str) -> None:
    """Run a streaming user turn, rendering chunks + tool traces incrementally.

    Per ADR-0008, this consumes `runtime.session.user_turn_stream` — the same
    event generator the web SSE endpoint reads. No business logic here, only
    rendering.
    """
    from knowlet.core.events import (
        ErrorEvent,
        ReplyChunkEvent,
        ToolCallEvent,
        ToolResultEvent,
        TurnDoneEvent,
    )

    started_assistant = False
    final_text = ""

    def maybe_open_assistant() -> None:
        nonlocal started_assistant
        if not started_assistant:
            console.print("[bold]knowlet:[/bold] ", end="")
            started_assistant = True

    for ev in runtime.session.user_turn_stream(user_text):
        if isinstance(ev, ReplyChunkEvent):
            maybe_open_assistant()
            console.print(ev.text, end="", soft_wrap=True, markup=False)
            final_text += ev.text
        elif isinstance(ev, ToolCallEvent):
            if started_assistant:
                console.print()
                started_assistant = False
            args_preview = json.dumps(ev.arguments, ensure_ascii=False)[:120]
            console.print(f"[dim]· {ev.name}({args_preview})[/dim]")
        elif isinstance(ev, ToolResultEvent):
            if isinstance(ev.payload, dict) and "error" in ev.payload:
                console.print(
                    f"[dim]  → {ev.name} error: {ev.payload['error']}[/dim]"
                )
            else:
                count = (
                    ev.payload.get("count") if isinstance(ev.payload, dict) else None
                )
                tail = f" ({count} hits)" if count is not None else ""
                console.print(f"[dim]  → {ev.name}{tail}[/dim]")
        elif isinstance(ev, TurnDoneEvent):
            if started_assistant:
                console.print()
                started_assistant = False
            final_text = ev.final_text or final_text
        elif isinstance(ev, ErrorEvent):
            if started_assistant:
                console.print()
                started_assistant = False
            err_console.print(f"[red]error: {ev.message}[/red]")


def _print_help() -> None:
    console.print(
        Panel.fit(t("slash.help.body"), title=t("slash.help.title"))
    )


def _render_notes_table(rows: list[dict], recent: bool) -> None:
    if not rows:
        console.print("[dim]no notes yet[/dim]")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("id", style="dim", no_wrap=True)
    table.add_column("title")
    table.add_column("tags", style="cyan")
    table.add_column("updated_at" if recent else "created_at", style="dim")
    for r in rows:
        table.add_row(
            r["id"][:8] + "…",
            r["title"],
            ", ".join(r["tags"]),
            r["updated_at"] if recent else r["created_at"],
        )
    console.print(table)


def _do_sediment(runtime, quiet_skip: bool = False) -> None:
    from knowlet.chat.sediment import (
        commit_draft,
        draft_from_conversation,
        open_in_editor,
    )

    if len(runtime.session.history) <= 1:
        if not quiet_skip:
            console.print("[dim]nothing to sediment yet[/dim]")
        return
    console.print("[dim]drafting Note from conversation…[/dim]")
    try:
        draft = draft_from_conversation(runtime.llm, runtime.session.history)
    except Exception as exc:  # noqa: BLE001
        err_console.print(f"[red]draft failed:[/red] {exc}")
        return

    while True:
        preview = (
            f"# {draft.title}\n\n"
            f"_tags: {', '.join(draft.tags) or '—'}_\n\n"
            f"{draft.body}"
        )
        console.print(Panel(Markdown(preview), title="draft"))
        choice = Prompt.ask(
            "save? [y]es / [n]o / [e]dit",
            choices=["y", "n", "e"],
            default="y",
        )
        if choice == "n":
            console.print("[dim]discarded[/dim]")
            return
        if choice == "e":
            try:
                draft = open_in_editor(draft)
            except Exception as exc:  # noqa: BLE001
                err_console.print(f"[red]editor failed:[/red] {exc}")
                return
            continue
        note = commit_draft(draft, runtime.vault, runtime.index, runtime.config)
        console.print(f"[green]saved[/green] → {note.path}")
        return


# ------------------------------------------------------------------ setup wizard


def _ensure_ready_or_wizard() -> tuple[Vault, KnowletConfig]:
    """Find the vault and verify config; if anything is missing, walk through
    setup interactively. Returns (vault, cfg) ready for `bootstrap_chat`."""
    import os

    try:
        vault_root = find_vault()
    except VaultNotFoundError:
        cwd = Path.cwd().resolve()
        console.print(
            Panel.fit(
                t("vault.notfound", cwd=str(cwd)),
                title=t("vault.welcome.title"),
            )
        )
        proceed = Prompt.ask(
            t("vault.init.prompt"), choices=["y", "n"], default="y"
        )
        if proceed != "y":
            raise typer.Exit(code=0)
        target = Path(
            Prompt.ask(t("vault.dir.prompt"), default=str(cwd))
        ).expanduser().resolve()
        target.mkdir(parents=True, exist_ok=True)
        vault = Vault(target)
        vault.init_layout()
        save_config(vault.root, KnowletConfig())
        os.environ["KNOWLET_VAULT"] = str(vault.root)
        vault_root = vault.root
        console.print(f"[green]{t('vault.created', root=str(vault.root))}[/green]\n")

    vault = Vault(vault_root)
    cfg = _load_config_or_default(vault)
    if not cfg.llm.api_key:
        console.print(
            Panel.fit(
                t("config.llm_setup.intro"),
                title=t("config.llm_setup.title"),
            )
        )
        cfg.llm.base_url = Prompt.ask(t("config.base_url.prompt"), default=cfg.llm.base_url)
        cfg.llm.model = Prompt.ask(t("config.model.prompt"), default=cfg.llm.model)
        api_key = Prompt.ask(t("config.api_key.prompt"), password=True)
        if api_key:
            cfg.llm.api_key = api_key
        save_config(vault.root, cfg)
        console.print(
            f"[green]{t('config.saved', path=str(config_path(vault.root)))}[/green]\n"
        )
    return vault, cfg


if __name__ == "__main__":  # pragma: no cover
    sys.exit(app())
