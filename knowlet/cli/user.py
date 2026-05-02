"""`knowlet user` — user profile show / edit."""

from __future__ import annotations

import typer
from rich.markdown import Markdown
from rich.panel import Panel

from knowlet.cli._common import console, err_console, resolve_vault_or_die

app = typer.Typer(
    help="User profile (`<vault>/users/me.md`).",
    no_args_is_help=True,
)


@app.command("show")
def user_show() -> None:
    """Print the user profile (or note that none exists yet)."""
    from knowlet.core.user_profile import read_profile

    vault = resolve_vault_or_die()
    profile = read_profile(vault.profile_path)
    if profile is None:
        console.print(
            "[dim]no profile yet — `knowlet user edit` to create one.[/dim]"
        )
        return
    console.print(Panel(Markdown(profile.body), title=str(vault.profile_path)))
    console.print(f"[dim]updated_at: {profile.updated_at}[/dim]")


@app.command("edit")
def user_edit() -> None:
    """Open the user profile in $EDITOR (creates a default template if missing)."""
    from knowlet.core.user_profile import edit_profile_in_editor

    vault = resolve_vault_or_die()
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
