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


# ---------------------------------------------------- vault snapshot (data safety)


SNAPSHOT_DIR_NAME = "snapshots"
# What to copy. Skipped: the `snapshots/` dir itself (avoids recursion) and
# the rebuildable indexes — `reindex` recreates them. Everything else is
# fair game (config, conversations, quizzes, backups) because data the
# user has acted on belongs in a safety copy even if it's "auxiliary."
#
# SQLite WAL mode produces `<db>-shm` and `<db>-wal` sidecars holding
# in-flight transactions; we match by stem prefix so those never sneak
# in (an inconsistent snapshot of mid-transaction data is worse than
# rebuilding from scratch on next start).
_SNAPSHOT_SKIP_NAMES = {SNAPSHOT_DIR_NAME}
_SNAPSHOT_SKIP_STEMS = {"index.sqlite", "vectors.sqlite"}
# Public alias preserved for the regression test that pins this set.
_SNAPSHOT_SKIP = _SNAPSHOT_SKIP_NAMES | _SNAPSHOT_SKIP_STEMS


def _should_skip(name: str) -> bool:
    """Match snapshot dir by exact name + indexes by stem prefix."""
    if name in _SNAPSHOT_SKIP_NAMES:
        return True
    return any(name == s or name.startswith(s + "-") for s in _SNAPSHOT_SKIP_STEMS)


def _iter_snapshot_targets(vault_root: Path):
    """Yield top-level (src, rel_dst) pairs for a vault snapshot. Skips
    the snapshot dir + rebuildable indexes."""
    for entry in vault_root.iterdir():
        if entry.name == ".knowlet":
            yield entry, entry.relative_to(vault_root)
            continue
        if entry.is_dir() or entry.is_file():
            yield entry, entry.relative_to(vault_root)


def _copy_skip_filter(src: str, names: list[str]) -> list[str]:
    """`shutil.copytree` ignore-callable. Skips snapshot dir + indexes
    (including SQLite WAL `-shm` / `-wal` sidecars)."""
    return [n for n in names if _should_skip(n)]


@app.command("snapshot")
def vault_snapshot(
    label: Annotated[
        Optional[str],
        typer.Option(
            "--label",
            help="Optional label appended to the snapshot directory name "
            "(e.g. `pre-m8-upgrade`). Plain ts-only if omitted.",
        ),
    ] = None,
    to: Annotated[
        Optional[Path],
        typer.Option(
            "--to",
            help="Custom destination directory. Default = "
            "`<vault>/.knowlet/snapshots/<ts>[-<label>]/`.",
        ),
    ] = None,
) -> None:
    """Make a full safety copy of the vault before risky operations.

    What's included: notes/, cards/, drafts/, tasks/, users/, plus
    .knowlet/{config.toml, conversations/, quizzes/, backups/}.

    What's excluded: existing snapshots (no recursion), rebuildable
    indexes (`index.sqlite`, `vectors.sqlite` — `knowlet reindex`
    rebuilds them in seconds).

    Recommended: run **before** `git pull && uv sync` to upgrade
    knowlet, so you can restore if a migration goes wrong. Snapshots
    accumulate; clean old ones with `knowlet vault list-snapshots`.
    """
    import shutil
    from datetime import UTC, datetime

    vault = resolve_vault_or_die()
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
    name = f"{ts}-{label}" if label else ts
    target = (to or (vault.state_dir / SNAPSHOT_DIR_NAME / name)).resolve()
    if target.exists():
        err_console.print(f"[red]snapshot path already exists:[/red] {target}")
        raise typer.Exit(code=2)

    target.mkdir(parents=True, exist_ok=True)
    bytes_copied = 0
    files_copied = 0
    for src, rel in _iter_snapshot_targets(vault.root):
        dst = target / rel
        if src.is_file():
            if _should_skip(src.name):
                continue
            shutil.copy2(src, dst)
            bytes_copied += dst.stat().st_size
            files_copied += 1
        elif src.is_dir():
            shutil.copytree(src, dst, ignore=_copy_skip_filter, dirs_exist_ok=True)
            for p in dst.rglob("*"):
                if p.is_file():
                    bytes_copied += p.stat().st_size
                    files_copied += 1

    mb = bytes_copied / (1024 * 1024)
    console.print(
        f"[green]snapshot ok[/green] · {files_copied} files / {mb:.1f} MB"
    )
    console.print(f"[dim]→ {target}[/dim]")
    console.print(
        "[dim]hint: keep until you've confirmed the upgrade works; "
        "delete with `rm -rf <path>` when done.[/dim]"
    )


@app.command("list-snapshots")
def vault_list_snapshots() -> None:
    """List all snapshots in `<vault>/.knowlet/snapshots/`. Read-only."""
    vault = resolve_vault_or_die()
    snap_dir = vault.state_dir / SNAPSHOT_DIR_NAME
    if not snap_dir.exists():
        console.print("[dim]no snapshots yet.[/dim]")
        return
    snaps = sorted(
        (p for p in snap_dir.iterdir() if p.is_dir()),
        key=lambda p: p.name,
        reverse=True,
    )
    if not snaps:
        console.print("[dim]no snapshots yet.[/dim]")
        return
    total = 0
    for s in snaps:
        size = sum(p.stat().st_size for p in s.rglob("*") if p.is_file())
        total += size
        console.print(f"  · {s.name}  [dim]{size / 1024 / 1024:.1f} MB[/dim]")
    console.print(f"[dim]total: {total / 1024 / 1024:.1f} MB across {len(snaps)} snapshots[/dim]")


@app.command("restore-snapshot")
def vault_restore_snapshot(
    snapshot_name: Annotated[
        str,
        typer.Argument(
            help="Snapshot directory name (or unique prefix). See `knowlet vault list-snapshots`."
        ),
    ],
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip the confirmation prompt."),
    ] = False,
) -> None:
    """Restore a snapshot OVER the current vault.

    DESTRUCTIVE: this overwrites notes/, cards/, drafts/, tasks/, users/
    + .knowlet/{config.toml, conversations/, quizzes/, backups/} with
    the snapshot's contents. The current state is FIRST snapshotted as
    `<ts>-pre-restore` so you can undo this restore.

    The rebuildable indexes (`index.sqlite`, `vectors.sqlite`) are
    cleared so the next `knowlet` command rebuilds them from scratch
    against the restored notes — avoids stale-index drift.
    """
    import shutil
    from datetime import UTC, datetime
    from rich.prompt import Confirm

    vault = resolve_vault_or_die()
    snap_dir = vault.state_dir / SNAPSHOT_DIR_NAME
    if not snap_dir.exists():
        err_console.print("[red]no snapshots in this vault[/red]")
        raise typer.Exit(code=2)
    candidates = [p for p in snap_dir.iterdir() if p.is_dir() and p.name.startswith(snapshot_name)]
    if len(candidates) == 0:
        err_console.print(f"[red]no snapshot matches[/red] {snapshot_name!r}")
        raise typer.Exit(code=2)
    if len(candidates) > 1:
        err_console.print(
            f"[red]ambiguous prefix[/red] {snapshot_name!r} matches "
            f"{len(candidates)} snapshots; pass a longer prefix"
        )
        for c in candidates:
            err_console.print(f"  · {c.name}")
        raise typer.Exit(code=2)
    src_root = candidates[0]

    if not yes:
        ok = Confirm.ask(
            f"Restore [bold]{src_root.name}[/bold] OVER current vault? "
            f"(current state will be saved as `<ts>-pre-restore`)",
            default=False,
        )
        if not ok:
            console.print("[dim]aborted.[/dim]")
            return

    # 1. Snapshot current state first.
    pre_ts = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
    pre_path = snap_dir / f"{pre_ts}-pre-restore"
    pre_path.mkdir(parents=True, exist_ok=True)
    for src, rel in _iter_snapshot_targets(vault.root):
        dst = pre_path / rel
        if src.is_file():
            if not _should_skip(src.name):
                shutil.copy2(src, dst)
        elif src.is_dir():
            shutil.copytree(src, dst, ignore=_copy_skip_filter, dirs_exist_ok=True)
    console.print(f"[dim]· current state snapshotted to {pre_path.name}[/dim]")

    # 2. Wipe live entity dirs (the ones we restore over).
    for d in (vault.notes_dir, vault.cards_dir, vault.drafts_dir,
              vault.tasks_dir, vault.users_dir, vault.conversations_dir,
              vault.backups_dir):
        if d.exists():
            shutil.rmtree(d)

    # 3. Drop rebuildable indexes so they get rebuilt fresh.
    for idx_name in ("index.sqlite", "vectors.sqlite"):
        p = vault.state_dir / idx_name
        if p.exists():
            p.unlink()

    # 4. Copy snapshot contents back.
    for entry in src_root.iterdir():
        dst = vault.root / entry.name
        if entry.is_file():
            shutil.copy2(entry, dst)
        elif entry.is_dir():
            shutil.copytree(entry, dst, dirs_exist_ok=True)

    console.print(f"[green]restored from {src_root.name}[/green]")
    console.print("[dim]· run `knowlet reindex` to rebuild the search index[/dim]")
