"""`knowlet vault` — vault layout and lifecycle commands."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.panel import Panel

from knowlet.cli._common import console, err_console, resolve_vault_or_die
from knowlet.config import KnowletConfig, config_path, load_config, save_config
from knowlet.core.i18n import set_language, t
from knowlet.core.note import Note
from knowlet.core.vault import Vault

app = typer.Typer(help="Vault layout and lifecycle.", no_args_is_help=True)


@app.command("init")
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
    cfg = load_config(vault.root)
    set_language(cfg.general.language)
    console.print(
        Panel.fit(
            t("vault.init.banner", root=str(vault.root)),
            title=t("vault.init.title"),
        )
    )


@app.command("migrate-filenames")
def vault_migrate_filenames(
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Print what would be renamed; don't touch the disk."),
    ] = False,
) -> None:
    """Rename existing notes from `<id>-<slug>.md` to `<id>.md` (ULID-only).

    Run this once after upgrading to the version that drops the slug
    suffix from filenames. Idempotent: notes already at `<id>.md` are
    skipped. Files that don't have a parseable ULID prefix are listed
    but left alone — those are usually hand-named files in the vault
    that aren't knowlet-managed Notes.
    """
    vault = resolve_vault_or_die()
    if not vault.notes_dir.exists():
        console.print("[dim]no notes/ directory; nothing to migrate.[/dim]")
        return

    renamed: list[tuple[Path, Path]] = []
    skipped_already_canonical: list[Path] = []
    skipped_no_id: list[Path] = []
    collisions: list[Path] = []

    for path in sorted(vault.notes_dir.glob("*.md")):
        if not path.is_file():
            continue
        try:
            note = Note.from_file(path)
        except Exception as exc:  # noqa: BLE001
            err_console.print(f"[yellow]skip[/yellow] {path.name}: {exc}")
            skipped_no_id.append(path)
            continue
        target = vault.notes_dir / f"{note.id}.md"
        if path == target:
            skipped_already_canonical.append(path)
            continue
        if target.exists():
            err_console.print(
                f"[red]collision[/red] {path.name} → {target.name} already exists, leaving in place"
            )
            collisions.append(path)
            continue
        renamed.append((path, target))

    if not renamed and not collisions:
        console.print(
            f"[green]✓[/green] all {len(skipped_already_canonical)} note(s) already at <id>.md"
        )
        return

    for src, dst in renamed:
        if dry_run:
            console.print(f"[dim]would rename[/dim] {src.name} → {dst.name}")
        else:
            src.rename(dst)
            console.print(f"[green]renamed[/green] {src.name} → {dst.name}")

    if dry_run:
        console.print(
            f"\n[dim]dry-run summary: {len(renamed)} would rename, "
            f"{len(skipped_already_canonical)} already canonical, "
            f"{len(skipped_no_id)} unparseable, {len(collisions)} collisions[/dim]"
        )
    else:
        console.print(
            f"\n[green]✓[/green] {len(renamed)} renamed, "
            f"{len(skipped_already_canonical)} already canonical, "
            f"{len(skipped_no_id)} unparseable, {len(collisions)} collisions"
        )
        if renamed:
            console.print(
                "[dim]hint: run `knowlet reindex` so the index points at the new paths.[/dim]"
            )
