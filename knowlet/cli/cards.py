"""`knowlet cards` — spaced-repetition card commands."""

from __future__ import annotations

from typing import Annotated, Optional

import typer
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from knowlet.cli._common import console, err_console, resolve_vault_or_die

app = typer.Typer(help="Spaced-repetition Cards (scenario C).", no_args_is_help=True)


@app.command("new")
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
    from knowlet.core.card_store import CardStore
    from knowlet.core.fsrs_wrap import initial_state

    vault = resolve_vault_or_die()
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


@app.command("due")
def cards_due(
    limit: Annotated[int, typer.Option("--limit", "-n", help="Max rows.")] = 20,
) -> None:
    """List Cards that are due now."""
    from knowlet.core.card import parse_due
    from knowlet.core.card_store import CardStore

    vault = resolve_vault_or_die()
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


@app.command("review")
def cards_review(
    limit: Annotated[
        int,
        typer.Option("--limit", "-n", help="Max cards in this session."),
    ] = 20,
) -> None:
    """Walk through due Cards interactively, recording ratings."""
    run_cards_review(limit=limit)


def run_cards_review(limit: int = 20) -> None:
    """Reusable from the chat REPL `:cards` slash too."""
    from knowlet.core.card import parse_due
    from knowlet.core.card_store import CardStore
    from knowlet.core.fsrs_wrap import schedule_next

    vault = resolve_vault_or_die()
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


@app.command("show")
def cards_show(
    card_id: Annotated[str, typer.Argument(help="Card ULID (full or 8-char prefix).")],
) -> None:
    """Print a single Card's content."""
    from knowlet.core.card_store import CardStore

    vault = resolve_vault_or_die()
    store = CardStore(vault.cards_dir)
    card = store.get(card_id)
    if card is None:
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
