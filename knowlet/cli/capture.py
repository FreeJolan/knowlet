"""`knowlet capture` — CLI mirror of the web UI's CaptureBox flow.

Per CLAUDE.md §3 (single source of truth / thin shells per interface)
+ §E.4 (cross-interface check): every backend capability the web
exposes should also be reachable from the CLI. The web side ships
``POST /api/capture/url`` / ``/file`` / ``/decide``; this is the CLI
mirror.

Usage:
    knowlet capture url <URL>      [--kind knowledge|reference|defer]
    knowlet capture file <PATH>    [--kind knowledge|reference|defer]

Without ``--kind``, prints the AI-extracted capsule and prompts for
a three-way decision (k / r / d / s for skip). With ``--kind``, runs
non-interactively — ``knowlet capture url X --kind reference`` is
the scriptable form.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

import typer
from rich.markdown import Markdown
from rich.panel import Panel

from knowlet.cli._common import (
    console,
    err_console,
    load_config_or_default,
    resolve_vault_or_die,
)

app = typer.Typer(
    help="Capture external material (URL / file) into the vault.",
    no_args_is_help=True,
)

Decision = Literal["knowledge", "reference", "defer"]


def _decide_interactively(default: str | None = None) -> Decision:
    """Prompt for one of k / r / d. Empty → default (if any) or repeat."""
    prompt = "[k]nowledge / [r]eference / [d]efer / [s]kip"
    while True:
        ans = typer.prompt(prompt, default=default or "k").strip().lower()
        if ans in ("k", "knowledge"):
            return "knowledge"
        if ans in ("r", "reference"):
            return "reference"
        if ans in ("d", "defer"):
            return "defer"
        if ans in ("s", "skip", ""):
            console.print("[dim]skipped — nothing written[/dim]")
            raise typer.Exit(code=0)
        console.print(f"[red]invalid:[/red] {ans!r}")


def _commit_capsule(
    *, title: str, body: str, source: str | None, decision: Decision
) -> None:
    """Wire-equivalent of POST /api/capture/decide."""
    from knowlet.core.drafts import Draft, DraftStore
    from knowlet.core.embedding import make_backend
    from knowlet.core.index import Index
    from knowlet.core.note import Note, new_id

    vault = resolve_vault_or_die()
    cfg = load_config_or_default(vault)

    if decision == "defer":
        store = DraftStore(vault.drafts_dir)
        d = Draft(
            id=new_id(),
            title=title,
            body=body,
            source=source,
            kind="reference",  # capture-time default (ADR-0029 §4.5)
        )
        store.save(d)
        console.print(f"[green]deferred to drafts/[/green]: {d.id[:8]}…")
        return

    note = Note(id=new_id(), title=title, body=body, source=source, kind=decision)
    path = vault.write_note(note)
    note.path = path
    backend = make_backend(
        cfg.embedding.backend, cfg.embedding.model, cfg.embedding.dim
    )
    idx = Index(vault.db_path, backend)
    idx.connect()
    try:
        idx.upsert_note(
            note,
            chunk_size=cfg.retrieval.chunk_size,
            chunk_overlap=cfg.retrieval.chunk_overlap,
        )
    finally:
        idx.close()
    console.print(f"[green]saved as {decision}[/green] → {path}")


@app.command("url")
def capture_url_cmd(
    url: Annotated[str, typer.Argument(help="URL to fetch + summarize.")],
    kind: Annotated[
        str | None,
        typer.Option(
            "--kind",
            "-k",
            help="Skip prompt; commit as knowledge / reference / defer.",
        ),
    ] = None,
) -> None:
    """Fetch + summarize a URL via the configured LLM, then triage.

    Mirrors POST /api/capture/url + /api/capture/decide. The summary
    is the AI-extracted capsule; decision (k/r/d) is the user's."""
    from knowlet.core.llm import LLMClient
    from knowlet.core.url_capture import (
        ExtractionError,
        FetchError,
        capture_url,
    )

    vault = resolve_vault_or_die()
    cfg = load_config_or_default(vault)
    if not cfg.llm.api_key:
        err_console.print(
            "[red]LLM not configured.[/red] Run `knowlet config init` or set api_key."
        )
        raise typer.Exit(code=1)
    llm = LLMClient(cfg.llm)
    try:
        cap = capture_url(url, llm)
    except FetchError as exc:
        err_console.print(f"[red]fetch failed:[/red] {exc}")
        raise typer.Exit(code=2) from exc
    except ExtractionError as exc:
        err_console.print(f"[red]extraction failed:[/red] {exc}")
        raise typer.Exit(code=3) from exc

    console.print(
        Panel(
            Markdown(cap.summary or "(no summary)"),
            title=f"{cap.title}  [dim]· {cap.hostname}[/dim]",
        )
    )

    if kind is None:
        decision = _decide_interactively()
    elif kind in ("knowledge", "reference", "defer"):
        decision = kind  # type: ignore[assignment]
    else:
        err_console.print(
            f"[red]invalid --kind:[/red] {kind!r} (knowledge / reference / defer)"
        )
        raise typer.Exit(code=1)
    _commit_capsule(
        title=cap.title or url,
        body=cap.summary,
        source=cap.url,
        decision=decision,
    )


@app.command("file")
def capture_file_cmd(
    path: Annotated[
        Path, typer.Argument(help="Markdown / text file to capture.")
    ],
    kind: Annotated[
        str | None,
        typer.Option(
            "--kind",
            "-k",
            help="Skip prompt; commit as knowledge / reference / defer.",
        ),
    ] = None,
) -> None:
    """Capture a local .md / .txt file as a note (or draft).

    Mirrors POST /api/capture/file + /api/capture/decide. PDF is
    deferred per Stage 3 scope (2026-05-21)."""
    if not path.exists():
        err_console.print(f"[red]file not found:[/red] {path}")
        raise typer.Exit(code=1)
    suffix = path.suffix.lower().lstrip(".")
    if suffix not in ("md", "markdown", "txt", "text"):
        err_console.print(
            f"[red]unsupported file type:[/red] .{suffix}  "
            f"(only .md / .txt supported — PDF on roadmap)"
        )
        raise typer.Exit(code=1)
    text = path.read_text(encoding="utf-8", errors="replace")
    title = path.stem
    # Prefer first H1/H2 if present (matches web /api/capture/file).
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# ") or stripped.startswith("## "):
            title = stripped.lstrip("#").strip() or title
            break

    console.print(Panel(Markdown(text[:1500] or "(empty)"), title=title))

    if kind is None:
        decision = _decide_interactively()
    elif kind in ("knowledge", "reference", "defer"):
        decision = kind  # type: ignore[assignment]
    else:
        err_console.print(
            f"[red]invalid --kind:[/red] {kind!r} (knowledge / reference / defer)"
        )
        raise typer.Exit(code=1)
    _commit_capsule(
        title=title, body=text, source=str(path.name), decision=decision
    )
