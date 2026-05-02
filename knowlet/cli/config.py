"""`knowlet config` — configuration init / set / show."""

from __future__ import annotations

import json
from typing import Annotated

import typer
from rich.panel import Panel
from rich.prompt import Prompt

from knowlet.cli._common import (
    console,
    err_console,
    load_config_or_default,
    mask,
    resolve_vault_or_die,
)
from knowlet.config import config_path, save_config
from knowlet.core.i18n import set_language, t

app = typer.Typer(help="Configuration.", no_args_is_help=True)


@app.command("init")
def config_init() -> None:
    """Interactive wizard: configure the LLM endpoint and embedding model."""
    vault = resolve_vault_or_die()
    cfg = load_config_or_default(vault)

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
        default=(mask(cfg.llm.api_key) if cfg.llm.api_key else ""),
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


@app.command("set")
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
    vault = resolve_vault_or_die()
    cfg = load_config_or_default(vault)
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
    if section_name == "general" and field == "language":
        set_language(str(coerced))
    shown = mask(str(coerced)) if field == "api_key" else coerced
    console.print(f"[green]✓[/green] {key} = {shown}")


@app.command("show")
def config_show() -> None:
    """Print the current config (with API key masked)."""
    vault = resolve_vault_or_die()
    cfg = load_config_or_default(vault)
    safe = cfg.model_dump()
    safe["llm"]["api_key"] = mask(cfg.llm.api_key)
    console.print(json.dumps(safe, indent=2, ensure_ascii=False))
    console.print(f"[dim]{config_path(vault.root)}[/dim]")
