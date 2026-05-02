"""Interactive chat REPL — invoked by `knowlet chat` and bare `knowlet`.

This is the largest single piece of CLI logic; it lives in its own module so
`main.py` can stay short. Slash-command dispatch, streaming-event rendering,
and the sediment workflow all live here.
"""

from __future__ import annotations

import json
from typing import Any

import typer
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from knowlet import __version__
from knowlet.cli._common import console, err_console, mask, render_notes_table
from knowlet.cli._doctor import print_doctor, run_doctor_checks
from knowlet.cli.cards import run_cards_review
from knowlet.cli.mining import _render_run_report
from knowlet.core.i18n import t
from knowlet.core.index import Index


def run_chat(*, save_after: bool, ensure_ready) -> None:
    """Inner chat entry. `ensure_ready` is the bootstrap closure from main —
    we accept it as a callable to avoid an import cycle with the setup wizard.
    """
    from knowlet.chat.bootstrap import ChatNotReadyError, bootstrap_chat
    from knowlet.core.index import IndexDimensionMismatchError

    vault, cfg = ensure_ready()

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


def _handle_slash(text: str, runtime: Any) -> tuple[bool, bool]:
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
        render_notes_table(rows, recent=recent)
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
        runtime.index = Index(runtime.vault.db_path, runtime.backend)
        runtime.index.connect()
        runtime.ctx.index = runtime.index
        console.print(
            f"[dim]reindex: {changed} updated, {deleted} removed, {unchanged} unchanged[/dim]"
        )
        return True, False
    if name == "doctor":
        results = run_doctor_checks(
            runtime.vault, runtime.config, skip_llm=False, skip_embedding=False
        )
        print_doctor(results)
        return True, False
    if name == "config":
        sub = args[0] if args else "show"
        if sub == "show":
            safe = runtime.config.model_dump()
            safe["llm"]["api_key"] = mask(runtime.config.llm.api_key)
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
            run_cards_review(limit=20)
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


def _stream_turn_to_console(runtime: Any, user_text: str) -> None:
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


def _do_sediment(runtime: Any, quiet_skip: bool = False) -> None:
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
