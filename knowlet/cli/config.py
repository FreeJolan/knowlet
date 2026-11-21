"""`knowlet config` — configuration init / set / show."""

from __future__ import annotations

import json
from typing import Annotated, Any

import typer
from rich.panel import Panel
from rich.prompt import Prompt

from knowlet.cli._common import (
    console,
    err_console,
    load_config_or_default,
    resolve_vault_or_die,
)
from knowlet.config import KnowletConfig, config_path, save_config
from knowlet.core.i18n import set_language, t

app = typer.Typer(help="Configuration.", no_args_is_help=True)


def is_secret_field(field: str) -> bool:
    """Credential fields (`llm.api_key`, `web_search.brave_api_key`, …)."""
    return field == "api_key" or field.endswith("_api_key")


def mask_secret(value: str) -> str:
    """Keep the first 4 and last 2 characters so keys stay tell-apart-able;
    values too short for that to hide most of them are fully starred."""
    if not value:
        return ""
    if len(value) <= 10:
        return "*" * len(value)
    return value[:4] + "*" * (len(value) - 6) + value[-2:]


def redacted_config_dump(cfg: KnowletConfig, *, show_secrets: bool = False) -> dict[str, Any]:
    data = cfg.model_dump()
    if show_secrets:
        return data
    for section in data.values():
        if not isinstance(section, dict):
            continue
        for field, value in section.items():
            if is_secret_field(field) and isinstance(value, str):
                section[field] = mask_secret(value)
    return data


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
    masked_current = mask_secret(cfg.llm.api_key)
    api_key = Prompt.ask(
        t("config.api_key.prompt"),
        default=masked_current,
        password=True,
    )
    # Accepting the default returns the masked string — keep the real key.
    if api_key and api_key != masked_current:
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
        knowlet config set llm.model gpt-5.5
        knowlet config set llm.api_key sk-...
    """
    vault = resolve_vault_or_die()
    cfg = load_config_or_default(vault)
    parts = key.split(".")
    # Slice 5.A added sync; web_search has been here since M7. The
    # gate exists so a typo'd section doesn't auto-vivify a new one
    # via setattr — every legitimate section needs to be listed.
    allowed_sections = {
        "general",
        "llm",
        "embedding",
        "retrieval",
        "web_search",
        "sync",
    }
    if len(parts) != 2 or parts[0] not in allowed_sections:
        err_console.print(
            f"[red]invalid key {key!r}; expected <section>.<field> "
            f"where section is one of {sorted(allowed_sections)}[/red]"
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
        err_console.print(
            f"[red]value {value!r} not convertible to {field_type.__name__}: {exc}[/red]"
        )
        raise typer.Exit(code=2) from exc

    setattr(section, field, coerced)
    save_config(vault.root, cfg)
    if section_name == "general" and field == "language":
        set_language(str(coerced))
    shown = mask_secret(str(coerced)) if is_secret_field(field) else coerced
    console.print(f"[green]✓[/green] {key} = {shown}")


@app.command("show")
def config_show(
    show_secrets: Annotated[
        bool,
        typer.Option("--show-secrets", help="Print API keys in full instead of masked."),
    ] = False,
) -> None:
    """Print the current config (API keys masked unless --show-secrets)."""
    vault = resolve_vault_or_die()
    cfg = load_config_or_default(vault)
    safe = redacted_config_dump(cfg, show_secrets=show_secrets)
    console.print(json.dumps(safe, indent=2, ensure_ascii=False), markup=False, soft_wrap=True)
    console.print(f"[dim]{config_path(vault.root)}[/dim]")
