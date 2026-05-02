"""`knowlet vault` — vault layout and lifecycle commands."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.panel import Panel

from knowlet.cli._common import console
from knowlet.config import KnowletConfig, config_path, load_config, save_config
from knowlet.core.i18n import set_language, t
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
