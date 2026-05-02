"""knowlet CLI — typer entrypoint.

This module is intentionally thin: app + sub-app registration, top-level
commands (`web` / `doctor` / `reindex` / `ls` / `chat`), the `_root`
callback, and the first-launch setup wizard. Each sub-app lives in its
own module under `knowlet.cli.*`; the chat REPL implementation lives in
`knowlet.cli.chat_repl`.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.panel import Panel
from rich.prompt import Prompt

from knowlet import __version__
from knowlet.cli import cards as cards_cli
from knowlet.cli import config as config_cli
from knowlet.cli import drafts as drafts_cli
from knowlet.cli import mining as mining_cli
from knowlet.cli import notes as notes_cli
from knowlet.cli import quiz as quiz_cli
from knowlet.cli import user as user_cli
from knowlet.cli import vault as vault_cli
from knowlet.cli._common import (
    console,
    err_console,
    load_config_or_default,
    make_index,
    render_notes_table,
    resolve_vault_or_die,
)
from knowlet.cli._doctor import print_doctor, run_doctor_checks
from knowlet.cli.chat_repl import run_chat
from knowlet.config import (
    KnowletConfig,
    VaultNotFoundError,
    config_path,
    find_vault,
    save_config,
)
from knowlet.core.embedding import make_backend
from knowlet.core.i18n import t
from knowlet.core.index import reindex_vault
from knowlet.core.vault import Vault

app = typer.Typer(
    name="knowlet",
    help="A personal knowledge base that organizes itself.",
    no_args_is_help=False,
    add_completion=False,
)
app.add_typer(vault_cli.app, name="vault")
app.add_typer(config_cli.app, name="config")
app.add_typer(user_cli.app, name="user")
app.add_typer(cards_cli.app, name="cards")
app.add_typer(mining_cli.app, name="mining")
app.add_typer(drafts_cli.app, name="drafts")
app.add_typer(notes_cli.app, name="notes")
app.add_typer(quiz_cli.app, name="quiz")


# ------------------------------------------------------------------ root


@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
    version: Annotated[
        bool, typer.Option("--version", help="Show version and exit.", is_eager=True)
    ] = False,
) -> None:
    if version:
        console.print(f"knowlet {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        # Bare `knowlet` → drop into chat. Subcommands stay available via
        # `knowlet --help` / `knowlet <name>` for scripting and one-off ops.
        run_chat(save_after=False, ensure_ready=_ensure_ready_or_wizard)
        raise typer.Exit()


# ------------------------------------------------------------------ web


@app.command("web")
def web(
    host: Annotated[
        str,
        typer.Option("--host", help="Bind address. Default 127.0.0.1 (localhost only)."),
    ] = "127.0.0.1",
    port: Annotated[
        int,
        typer.Option("--port", help="Port. Default 8765."),
    ] = 8765,
) -> None:
    """Start the local web UI (http://127.0.0.1:8765 by default).

    Single-user, localhost-only. No auth. Reuses the same backend modules as
    the CLI — every UI action has a CLI mirror by design (see ADR-0008).
    """
    from knowlet.web.server import create_app

    vault = resolve_vault_or_die()
    cfg = load_config_or_default(vault)
    if not cfg.llm.api_key:
        err_console.print(
            "[red]LLM api_key is empty. Run `knowlet config init` first.[/red]"
        )
        raise typer.Exit(code=2)

    try:
        import uvicorn
    except ImportError as exc:  # noqa: F841
        err_console.print(
            "[red]uvicorn is not installed. Reinstall knowlet to pull web deps.[/red]"
        )
        raise typer.Exit(code=2)

    # Long-running process — make sure scheduler / mining / LLM errors land
    # somewhere the user can find them, even if they close the terminal.
    from knowlet._logging import configure_logging
    configure_logging(vault.root)

    fastapi_app = create_app(vault, cfg)

    console.print(
        Panel.fit(
            f"knowlet web · http://{host}:{port}\n"
            f"vault={vault.root.name}  model={cfg.llm.model}\n"
            f"Ctrl-C to stop.",
            title=f"knowlet {__version__}",
        )
    )
    uvicorn.run(fastapi_app, host=host, port=port, log_level="info")


# ------------------------------------------------------------------ ls / reindex


@app.command("ls")
def ls(
    recent: Annotated[
        bool,
        typer.Option("--recent", help="Sort by updated_at (default is created_at)."),
    ] = False,
    limit: Annotated[int, typer.Option("--limit", "-n", help="Max rows.")] = 20,
) -> None:
    """List Notes in the current vault."""
    vault = resolve_vault_or_die()
    cfg = load_config_or_default(vault)
    idx = make_index(vault, cfg)
    try:
        rows = idx.list_notes(limit=limit, order="updated_at" if recent else "created_at")
    finally:
        idx.close()
    if not rows:
        console.print("[dim]no notes yet — start a chat and use :save[/dim]")
        return
    render_notes_table(rows, recent=recent)


@app.command("reindex")
def reindex(
    rebuild: Annotated[
        bool,
        typer.Option(
            "--rebuild",
            help="Drop the index DB and rebuild from disk. Use after switching embedding models.",
        ),
    ] = False,
) -> None:
    """Rebuild the index from on-disk Notes."""
    vault = resolve_vault_or_die()
    cfg = load_config_or_default(vault)
    if rebuild and vault.db_path.exists():
        vault.db_path.unlink()
        console.print(f"[dim]dropped {vault.db_path}[/dim]")
    backend = make_backend(cfg.embedding.backend, cfg.embedding.model, cfg.embedding.dim)
    if backend.dim != cfg.embedding.dim:
        cfg.embedding.dim = backend.dim
        save_config(vault.root, cfg)
    changed, deleted, unchanged = reindex_vault(
        vault.root,
        vault.db_path,
        backend,
        chunk_size=cfg.retrieval.chunk_size,
        chunk_overlap=cfg.retrieval.chunk_overlap,
        note_paths=list(vault.iter_note_paths()),
    )
    console.print(
        f"reindex done: {changed} updated, {deleted} removed, {unchanged} unchanged"
    )


# ------------------------------------------------------------------ doctor


@app.command("doctor")
def doctor(
    skip_llm: Annotated[
        bool,
        typer.Option("--skip-llm", help="Don't call the LLM endpoint."),
    ] = False,
    skip_embedding: Annotated[
        bool,
        typer.Option("--skip-embedding", help="Don't load the embedding backend."),
    ] = False,
) -> None:
    """Smoke-test the configured vault + LLM endpoint + embedding stack.

    Useful when wiring up an OpenAI-compatible wrapper around Claude Code /
    Codex / Ollama / etc. — confirms that knowlet can speak to the proxy and
    that tool-calling works.
    """
    try:
        vault_root = find_vault()
    except VaultNotFoundError as exc:
        print_doctor([("fail", "vault", str(exc))])
        raise typer.Exit(code=1) from exc
    vault = Vault(vault_root)
    cfg = load_config_or_default(vault)
    results = run_doctor_checks(vault, cfg, skip_llm=skip_llm, skip_embedding=skip_embedding)
    print_doctor(results)
    if any(r[0] == "fail" for r in results):
        raise typer.Exit(code=1)


# ------------------------------------------------------------------ chat


@app.command("chat")
def chat(
    save_after: Annotated[
        bool,
        typer.Option(
            "--save-after",
            help="After exit, prompt to sediment the conversation into a Note.",
        ),
    ] = False,
) -> None:
    """Start an interactive chat REPL backed by the vault."""
    run_chat(save_after=save_after, ensure_ready=_ensure_ready_or_wizard)


# ------------------------------------------------------------------ setup wizard


def _ensure_ready_or_wizard() -> tuple[Vault, KnowletConfig]:
    """Find the vault and verify config; if anything is missing, walk through
    setup interactively. Returns (vault, cfg) ready for `bootstrap_chat`."""
    import os

    try:
        vault_root = find_vault()
    except VaultNotFoundError:
        cwd = Path.cwd().resolve()
        console.print(
            Panel.fit(
                t("vault.notfound", cwd=str(cwd)),
                title=t("vault.welcome.title"),
            )
        )
        proceed = Prompt.ask(
            t("vault.init.prompt"), choices=["y", "n"], default="y"
        )
        if proceed != "y":
            raise typer.Exit(code=0)
        target = Path(
            Prompt.ask(t("vault.dir.prompt"), default=str(cwd))
        ).expanduser().resolve()
        target.mkdir(parents=True, exist_ok=True)
        vault = Vault(target)
        vault.init_layout()
        save_config(vault.root, KnowletConfig())
        os.environ["KNOWLET_VAULT"] = str(vault.root)
        vault_root = vault.root
        console.print(f"[green]{t('vault.created', root=str(vault.root))}[/green]\n")

    vault = Vault(vault_root)
    cfg = load_config_or_default(vault)
    if not cfg.llm.api_key:
        console.print(
            Panel.fit(
                t("config.llm_setup.intro"),
                title=t("config.llm_setup.title"),
            )
        )
        cfg.llm.base_url = Prompt.ask(t("config.base_url.prompt"), default=cfg.llm.base_url)
        cfg.llm.model = Prompt.ask(t("config.model.prompt"), default=cfg.llm.model)
        api_key = Prompt.ask(t("config.api_key.prompt"), password=True)
        if api_key:
            cfg.llm.api_key = api_key
        save_config(vault.root, cfg)
        console.print(
            f"[green]{t('config.saved', path=str(config_path(vault.root)))}[/green]\n"
        )
    return vault, cfg


if __name__ == "__main__":  # pragma: no cover
    sys.exit(app())
