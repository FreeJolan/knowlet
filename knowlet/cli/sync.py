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


def _load_and_verify_creds(tok_path: Path) -> SyncCredentials | None:
    """Load credentials and verify the stored scopes match the
    build's required SCOPES. Returns None when no creds exist;
    raises ScopeUpgradeRequiredError when scopes are stale.

    Why this lives here vs in credentials.py: scope verification
    needs ``oauth.SCOPES`` which transitively imports the optional
    google libs. The sync CLI is the only entry point that needs
    both, so the import + raise + render-friendly-message dance
    happens here."""
    from knowlet.core.sync.credentials import load_credentials
    from knowlet.core.sync.oauth import verify_scope

    creds = load_credentials(tok_path)
    if creds is None:
        return None
    verify_scope(creds)
    return creds


# Forward reference resolved at runtime; we only need the type for
# the helper above, not for module-level use.
from knowlet.core.sync.credentials import SyncCredentials  # noqa: E402


def _scope_err() -> type[Exception]:
    """Lazy accessor for ScopeUpgradeRequiredError so the top-level
    `except _scope_err()` clauses don't trigger an oauth import at
    CLI module load time. (oauth pulls google client libs.)"""
    from knowlet.core.sync.oauth import ScopeUpgradeRequiredError

    return ScopeUpgradeRequiredError


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
    identity stored at connect time. Status renders the scope-stale
    warning inline (rather than raising) so users always get a
    coherent picture of where they are."""
    vault = resolve_vault_or_die()
    cfg = load_config_or_default(vault)
    cs_path, tok_path = _resolve_paths(vault.root, cfg.sync)
    from knowlet.core.sync.credentials import load_credentials
    from knowlet.core.sync.oauth import (
        ScopeUpgradeRequiredError,
        verify_scope,
    )

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
    # Slice 5.C.1 — scope upgrade check. If the stored token was
    # issued under an older scope set, surface the upgrade hint
    # inline. status keeps reporting; commands like push / pull
    # actually block until the user reconnects.
    try:
        verify_scope(creds)
    except ScopeUpgradeRequiredError as exc:
        console.print(
            f"  [yellow]Scope upgrade needed:[/yellow] missing "
            f"{', '.join(exc.missing)}.\n"
            "  Run [bold]knowlet sync disconnect[/bold] then "
            "[bold]knowlet sync connect[/bold] to re-authorize."
        )


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
    # #115 — empty client_secrets_path is fine; ``run_connect_flow``
    # falls back to the embedded OAuth client. Only warn (not error)
    # if a configured path is set but the file is missing.
    if cs_path is not None and not cs_path.exists():
        err_console.print(
            f"[yellow]sync.client_secrets_path = {cs_path} but that file "
            "doesn't exist — falling back to the embedded OAuth client.[/yellow]"
        )
        cs_path = None

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


@app.command("pull")
def sync_pull(
    reset_token: Annotated[
        bool,
        typer.Option(
            "--reset-token",
            help="Discard the cached startPageToken and re-bootstrap from now. "
            "Use after a long offline period if you only want to "
            "resume tracking from this moment forward, not replay history.",
        ),
    ] = False,
) -> None:
    """Phase 2 E Slice 5.B — read-only Drive Changes API pull.

    Reports what's changed in your Drive since the last pull. No
    local file is touched; this is the foundation that 5.C+ build
    the actual sync logic on top of.

    First run on a fresh vault calls ``changes.getStartPageToken``
    to bootstrap the cursor (so we don't replay the user's whole
    Drive history); subsequent runs pull only what's changed since.
    """
    vault = resolve_vault_or_die()
    cfg = load_config_or_default(vault)
    _, tok_path = _resolve_paths(vault.root, cfg.sync)

    try:
        creds = _load_and_verify_creds(tok_path)
    except _scope_err() as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=4) from exc
    if creds is None:
        err_console.print(
            "[red]Not connected.[/red] Run "
            "[bold]knowlet sync connect[/bold] first."
        )
        raise typer.Exit(code=2)

    try:
        from knowlet.core.sync import (
            SyncDependenciesMissingError,
            require_google_libs,
        )
        from knowlet.core.sync.changes import (
            get_initial_start_page_token,
            list_all_changes,
        )
        from knowlet.core.sync.drive_client import DriveClient
        from knowlet.core.sync.state import SyncStateStore

        require_google_libs()
        client = DriveClient(creds)
        state = SyncStateStore(vault.root)
        try:
            device_id = state.device_id()
            device_label = state.device_label()
            console.print(
                f"[dim]device_id={device_id}  label={device_label}[/dim]"
            )

            cached_token = state.start_page_token()
            if reset_token or cached_token is None:
                token = get_initial_start_page_token(client)
                state.set_start_page_token(token)
                if cached_token is None:
                    console.print(
                        f"[green]Bootstrapped[/green] startPageToken={token}. "
                        "First sync — no history replayed; future pulls will "
                        "report changes from now on."
                    )
                else:
                    console.print(
                        f"[yellow]Reset[/yellow] startPageToken={token}."
                    )
                return

            changes, new_token = list_all_changes(
                client, page_token=cached_token
            )
            state.set_start_page_token(new_token)
            console.print(
                f"[green]Pulled[/green] {len(changes)} change(s); "
                f"new token cached."
            )
            for c in changes[:20]:
                marker = (
                    "[red]REMOVED[/red]"
                    if c.removed
                    else "[yellow]TRASHED[/yellow]"
                    if c.trashed
                    else "[green]UPDATED[/green]"
                )
                name = (c.file or {}).get("name") or "(no metadata)"
                console.print(f"  {marker}  {c.file_id}  {name}")
            if len(changes) > 20:
                console.print(f"  [dim]… {len(changes) - 20} more[/dim]")
        finally:
            state.close()
    except SyncDependenciesMissingError as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=3) from exc


@app.command("push")
def sync_push(
    note_id: Annotated[
        str | None,
        typer.Argument(help="Note ULID to push. Omit to push every note."),
    ] = None,
) -> None:
    """Phase 2 E Slice 5.C — push local note(s) to Drive.

    First push of a Note creates a Drive file + records the
    drive_file_id. Subsequent pushes are conditional on the last-
    known head revision id; on a mismatch we surface the conflict
    + tell the user to run [bold]knowlet sync resolve[/bold].
    """
    vault = resolve_vault_or_die()
    cfg = load_config_or_default(vault)
    _, tok_path = _resolve_paths(vault.root, cfg.sync)
    from knowlet.core.note import Note

    try:
        creds = _load_and_verify_creds(tok_path)
    except _scope_err() as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=4) from exc
    if creds is None:
        err_console.print("[red]Not connected.[/red] Run knowlet sync connect first.")
        raise typer.Exit(code=2)

    try:
        from knowlet.core.sync import (
            SyncDependenciesMissingError,
            require_google_libs,
        )
        from knowlet.core.sync.drive_client import DriveClient
        from knowlet.core.sync.push import (
            ConflictReport,
            NoteFileMissingError,
            push_note,
        )
        from knowlet.core.sync.state import SyncStateStore

        require_google_libs()
        client = DriveClient(creds)
        service = client.service()
        state = SyncStateStore(vault.root)
        try:
            # Pick targets.
            if note_id:
                paths = list(vault.iter_note_paths())
                target = next((p for p in paths if p.stem == note_id), None)
                if target is None:
                    err_console.print(
                        f"[red]No note with id {note_id!r} found in {vault.notes_dir}.[/red]"
                    )
                    raise typer.Exit(code=2)
                targets = [Note.from_file(target)]
            else:
                targets = [Note.from_file(p) for p in vault.iter_note_paths()]

            pushed = 0
            conflicts: list[ConflictReport] = []
            for n in targets:
                try:
                    result = push_note(service=service, state=state, note=n)
                except NoteFileMissingError as exc:
                    err_console.print(f"[yellow]Skip {n.id}: {exc}[/yellow]")
                    continue
                if isinstance(result, ConflictReport):
                    conflicts.append(result)
                    console.print(
                        f"[yellow]Conflict[/yellow] {n.title} ({n.id}) — "
                        "remote moved since last sync."
                    )
                else:
                    verb = "Created" if result.created else "Updated"
                    console.print(
                        f"[green]{verb}[/green] {n.title} ({n.id}) → "
                        f"drive:{result.drive_file.id}"
                    )
                    pushed += 1

            console.print(
                f"\n[bold]{pushed} pushed, {len(conflicts)} conflict(s).[/bold]"
            )
            if conflicts:
                console.print(
                    "Run [bold]knowlet sync resolve <note-id>[/bold] for each "
                    "conflicted note. Use [bold]--strategy mine|remote|both[/bold]."
                )
        finally:
            state.close()
    except SyncDependenciesMissingError as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=3) from exc


@app.command("resolve")
def sync_resolve(
    note_id: Annotated[str, typer.Argument(help="Note ULID to resolve.")],
    strategy: Annotated[
        str,
        typer.Option(
            "--strategy",
            help='"mine" overwrites remote with local; "remote" overwrites '
            'local with remote; "both" keeps remote as a sibling conflict '
            "copy and pushes local on next sync.",
        ),
    ] = "",
) -> None:
    """Resolve a sync conflict surfaced by ``knowlet sync push``.

    Re-fetches both versions from Drive + local so the resolution
    is applied to the current state, not stale data captured at the
    earlier push attempt.
    """
    if strategy not in {"mine", "remote", "both"}:
        err_console.print(
            "[red]--strategy is required: one of mine | remote | both[/red]"
        )
        raise typer.Exit(code=2)
    vault = resolve_vault_or_die()
    cfg = load_config_or_default(vault)
    _, tok_path = _resolve_paths(vault.root, cfg.sync)
    from knowlet.core.note import Note

    try:
        creds = _load_and_verify_creds(tok_path)
    except _scope_err() as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=4) from exc
    if creds is None:
        err_console.print("[red]Not connected.[/red]")
        raise typer.Exit(code=2)

    try:
        from knowlet.core.sync import (
            SyncDependenciesMissingError,
            require_google_libs,
        )
        from knowlet.core.sync.drive_client import DriveClient
        from knowlet.core.sync.push import (
            ConflictReport,
            push_note,
            resolve_keep_both,
            resolve_use_mine,
            resolve_use_remote,
        )
        from knowlet.core.sync.state import SyncStateStore

        require_google_libs()
        client = DriveClient(creds)
        service = client.service()
        state = SyncStateStore(vault.root)
        try:
            paths = list(vault.iter_note_paths())
            target = next((p for p in paths if p.stem == note_id), None)
            if target is None:
                err_console.print(
                    f"[red]No note with id {note_id!r} found.[/red]"
                )
                raise typer.Exit(code=2)
            note = Note.from_file(target)
            # Re-trigger the push to capture a fresh conflict snapshot.
            result = push_note(service=service, state=state, note=note)
            if not isinstance(result, ConflictReport):
                console.print(
                    "[green]No conflict — push completed cleanly.[/green]"
                )
                return

            if strategy == "mine":
                done = resolve_use_mine(
                    service=service, state=state, conflict=result
                )
                console.print(
                    f"[green]Resolved (mine):[/green] overwrote remote with "
                    f"local; head revision now "
                    f"{done.drive_file.head_revision_id}."
                )
            elif strategy == "remote":
                resolve_use_remote(
                    state=state, conflict=result, local_path=target
                )
                console.print(
                    "[green]Resolved (remote):[/green] local file replaced "
                    "with remote bytes. .knowlet/backups/ has the prior "
                    "local version if you change your mind."
                )
            else:  # both
                label = state.device_label()
                copy_path = resolve_keep_both(
                    state=state,
                    conflict=result,
                    local_path=target,
                    device_label=label,
                )
                console.print(
                    f"[green]Resolved (both):[/green] remote saved as "
                    f"{copy_path.name}. Local kept; next push will retry."
                )
        finally:
            state.close()
    except SyncDependenciesMissingError as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=3) from exc


@app.command("disconnect")
def sync_disconnect() -> None:
    """Delete the local tokens + reset sync state. Does NOT revoke
    server-side access — the user must visit Google's account
    permissions page if they want to fully revoke. We print the
    link so it's one click away.

    The local device_id is preserved in sync_state.sqlite so a
    later reconnect from the same machine doesn't masquerade as
    a "new device" to the auto-detection path (ADR-0027 §4)."""
    vault = resolve_vault_or_die()
    cfg = load_config_or_default(vault)
    _, tok_path = _resolve_paths(vault.root, cfg.sync)
    from knowlet.core.sync.credentials import delete_credentials
    from knowlet.core.sync.state import SyncStateStore

    removed = delete_credentials(tok_path)
    state = SyncStateStore(vault.root)
    try:
        state.clear()
    finally:
        state.close()
    if removed:
        console.print(
            f"[green]Disconnected.[/green] Removed {tok_path} and "
            "cleared sync_state.sqlite (device_id preserved)."
        )
    else:
        console.print(
            "[yellow]No local tokens to remove[/yellow] — sync state "
            "still cleared."
        )
    console.print(
        "Server-side revoke (manual): "
        "https://myaccount.google.com/permissions"
    )
