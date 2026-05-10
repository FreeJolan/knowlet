"""`knowlet sync` — Phase 2 E Slice 5.A connect surface (ADR-0027).

Slice 5.A is **CLI-only** + **connect-verification only**. Sub-commands:

- ``knowlet sync connect``    — run the OAuth flow, persist tokens.
- ``knowlet sync status``     — print whether we're connected + identity.
- ``knowlet sync disconnect`` — wipe local tokens (does NOT revoke
                                 server-side; user must visit Google
                                 account permissions for that, with
                                 a printed link).

Saving notes still goes through the local-only path. ADR-0027 §8
sequences the actual sync write/read flows into Slices 5.B-5.G.

Imports are lazy / wrapped so the CLI loads cleanly even when the
optional ``[sync]`` extra isn't installed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from knowlet.cli._common import (
    console,
    err_console,
    load_config_or_default,
    resolve_vault_or_die,
)

app = typer.Typer(help="Connect knowlet to Google Drive (opt-in sync).", no_args_is_help=True)


def _resolve_paths(
    vault_root: Path, sync_cfg: object
) -> tuple[Path | None, Path]:
    """Return (client_secrets_path | None, token_path) resolved
    against the vault root + config. ``client_secrets_path`` is None
    when the user hasn't configured one (don't conflate with "."
    which would silently match the cwd).
    """
    from knowlet.core.sync.credentials import credentials_path

    cs = getattr(sync_cfg, "client_secrets_path", "") or ""
    cs_path: Path | None
    if cs:
        cs_path = Path(cs).expanduser()
        if not cs_path.is_absolute():
            cs_path = vault_root / cs_path
    else:
        cs_path = None
    tok_path = credentials_path(
        vault_root, getattr(sync_cfg, "token_path", "") or None
    )
    return cs_path, tok_path


@app.command("status")
def sync_status() -> None:
    """Show connection state. No network call; reads the cached
    identity stored at connect time."""
    vault = resolve_vault_or_die()
    cfg = load_config_or_default(vault)
    cs_path, tok_path = _resolve_paths(vault.root, cfg.sync)
    from knowlet.core.sync.credentials import load_credentials

    creds = load_credentials(tok_path)
    if creds is None:
        if cs_path is None:
            console.print(
                "[yellow]Not connected.[/yellow] "
                "Set [bold]sync.client_secrets_path[/bold] in your config "
                "first — see docs/sync-setup.md for the OAuth client setup."
            )
        elif not cs_path.exists():
            console.print(
                "[yellow]Not connected.[/yellow] "
                f"sync.client_secrets_path = {cs_path}, but that file "
                "doesn't exist."
            )
        else:
            console.print(
                "[yellow]Not connected.[/yellow] "
                "Run [bold]knowlet sync connect[/bold] to authorize."
            )
        return
    name = creds.user_display_name or "(unknown)"
    console.print(
        f"[green]Connected[/green] · {creds.user_email} ({name})"
    )
    console.print(f"  tokens at: {tok_path}")


@app.command("connect")
def sync_connect(
    port: Annotated[
        int,
        typer.Option(
            "--port",
            help="Loopback port for the OAuth callback. 0 = OS picks free port.",
            min=0,
            max=65535,
        ),
    ] = 0,
) -> None:
    """Start the OAuth flow. Opens your default browser, waits for
    consent, then persists the refresh + access tokens locally."""
    vault = resolve_vault_or_die()
    cfg = load_config_or_default(vault)
    cs_path, tok_path = _resolve_paths(vault.root, cfg.sync)
    if cs_path is None:
        err_console.print(
            "[red]sync.client_secrets_path is empty in your config.[/red]\n"
            "1) Create a Desktop OAuth client in Google Cloud Console.\n"
            "2) Download client_secret.json.\n"
            "3) knowlet config set sync.client_secrets_path /path/to/client_secret.json"
        )
        raise typer.Exit(code=2)

    try:
        from knowlet.core.sync import (
            SyncDependenciesMissingError,
            require_google_libs,
        )
        from knowlet.core.sync.oauth import (
            ClientSecretsMissingError,
            OAuthFlowError,
            run_connect_flow,
        )

        require_google_libs()
        result = run_connect_flow(
            client_secrets_path=cs_path,
            save_to=tok_path,
            port=port,
        )
        console.print(
            f"[green]Connected as[/green] {result.user_email}"
            + (f" ({result.user_display_name})" if result.user_display_name else "")
        )
        console.print(f"Tokens saved to: {result.saved_to}")
    except SyncDependenciesMissingError as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=3) from exc
    except ClientSecretsMissingError as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2) from exc
    except OAuthFlowError as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc


@app.command("disconnect")
def sync_disconnect() -> None:
    """Delete the local tokens. Does NOT revoke server-side access —
    the user must visit Google's account permissions page if they
    want to fully revoke. We print the link so it's one click away."""
    vault = resolve_vault_or_die()
    cfg = load_config_or_default(vault)
    _, tok_path = _resolve_paths(vault.root, cfg.sync)
    from knowlet.core.sync.credentials import delete_credentials

    removed = delete_credentials(tok_path)
    if removed:
        console.print(f"[green]Disconnected.[/green] Removed {tok_path}.")
    else:
        console.print(
            "[yellow]Not connected — nothing to remove.[/yellow]"
        )
    console.print(
        "Server-side revoke (manual): "
        "https://myaccount.google.com/permissions"
    )
