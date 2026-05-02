"""`knowlet quiz` — scope-driven active recall (M7.4.0, ADR-0014).

CLI-only flow. The full UX (focus mode, scope picker, Cards reflux)
lands in M7.4.1+. This subcommand is the validation harness for the
generation + grading prompts: a developer / dogfooding user can run
`knowlet quiz <note-id>` and verify the quality of the generated
questions and the advisory grading before any UI exists.

Per ADR-0008, the CLI is the source of truth for the backend functions —
the web layer (M7.4.1) reuses `core/quiz.py` directly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt

from knowlet.cli._common import (
    console,
    err_console,
    load_config_or_default,
    make_index,
    resolve_vault_or_die,
)
from knowlet.core.llm import LLMClient

app = typer.Typer(
    help="Active-recall quizzes over your notes (ADR-0014).",
    no_args_is_help=True,
)


def _resolve_note_id(idx, note_id_or_prefix: str) -> tuple[str, str, str]:
    """Resolve an 8-char-prefix or full ULID to (id, title, body). Raises
    typer.Exit on miss. Body is read from disk via `Note.from_file` so
    frontmatter is stripped and we always quiz against the latest text."""
    from knowlet.core.note import Note

    meta = idx.get_note_meta(note_id_or_prefix)
    if meta is None:
        rows = idx.list_notes(limit=None)
        matches = [r for r in rows if r["id"].startswith(note_id_or_prefix)]
        if len(matches) == 0:
            err_console.print(f"[red]no note matches[/red] {note_id_or_prefix!r}")
            raise typer.Exit(code=2)
        if len(matches) > 1:
            err_console.print(
                f"[red]ambiguous prefix[/red] {note_id_or_prefix!r} matches "
                f"{len(matches)} notes; pass a longer prefix"
            )
            raise typer.Exit(code=2)
        meta = matches[0]
    path = Path(meta["path"])
    if not path.exists():
        err_console.print(f"[red]note file missing on disk:[/red] {path}")
        raise typer.Exit(code=2)
    note = Note.from_file(path)
    return note.id, note.title, note.body


@app.command("run")
def quiz_run(
    note_ids: Annotated[
        list[str],
        typer.Argument(help="One or more Note ids (or 8-char prefixes) to quiz over."),
    ],
    n: Annotated[
        int,
        typer.Option("-n", "--num", help="Number of questions (default 5)."),
    ] = 5,
) -> None:
    """Run an active-recall quiz over the given Notes.

    Generates `n` questions via the configured LLM, asks each interactively,
    grades each answer, prints a summary. M7.4.0 — no persistence; once
    you exit, the session is gone. M7.4.1 wires the on-disk quiz store.
    """
    from knowlet.core.note import new_id
    from knowlet.core.quiz import (
        QuizQuestion,
        QuizSession,
        aggregate_score,
        generate_quiz,
        grade_answer,
    )
    from datetime import datetime, UTC

    if n < 1:
        err_console.print("[red]--num must be ≥ 1[/red]")
        raise typer.Exit(code=2)

    vault = resolve_vault_or_die()
    cfg = load_config_or_default(vault)
    idx = make_index(vault, cfg)
    llm = LLMClient(cfg.llm)

    notes_for_llm: list[tuple[str, str, str]] = []
    note_titles: list[str] = []
    for nid in note_ids:
        rid, title, body = _resolve_note_id(idx, nid)
        notes_for_llm.append((rid, title, body))
        note_titles.append(title)
    if not notes_for_llm:
        err_console.print("[red]no notes resolved[/red]")
        raise typer.Exit(code=2)

    console.print(
        f"[dim]Generating {n} questions over[/dim] "
        + ", ".join(f"[bold]《{t}》[/bold]" for t in note_titles)
        + "[dim]…[/dim]"
    )
    try:
        questions = generate_quiz(llm, notes_for_llm, n=n)
    except Exception as exc:  # noqa: BLE001
        err_console.print(f"[red]generation failed:[/red] {exc}")
        raise typer.Exit(code=1) from None

    session = QuizSession(
        id=new_id(),
        started_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        model=cfg.llm.model,
        scope_type="notes",
        scope_note_ids=[r[0] for r in notes_for_llm],
        questions=questions,
    )

    for i, q in enumerate(questions, start=1):
        console.print()
        console.print(
            Panel(
                Markdown(q.question),
                title=f"[{i}/{len(questions)}] {q.type}",
                border_style="cyan",
            )
        )
        # Multiline-ish answer: a single line via Prompt is enough for
        # M7.4.0 dogfood. Real UI gets a textarea.
        answer = Prompt.ask("[bold]答[/bold] (Enter to skip)", default="")
        score, reason, missing = grade_answer(llm, q, answer)
        q.user_answer = answer
        q.ai_score = score
        q.ai_reason = reason
        q.ai_missing = missing
        color = "green" if score >= 4 else ("yellow" if score >= 3 else "red")
        console.print(f"[{color}]score: {score}/5[/{color}] · {reason}")
        if missing:
            console.print(
                "[dim]missing:[/dim] " + " · ".join(f"[dim]{m}[/dim]" for m in missing)
            )
        if score < 3:
            console.print(f"[dim]reference:[/dim] {q.reference_answer}")

    aggregate_score(session)
    console.print()
    console.print(
        Panel(
            f"[bold]session score: {session.session_score}/100[/bold]\n"
            f"correct: {session.n_correct}/{session.n_questions}  ·  "
            f"per-question avg: {session.session_score / 100 * 5:.1f}/5",
            title="Quiz summary",
            border_style="green",
        )
    )
