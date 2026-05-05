"""CLI rendering for `knowlet doctor` and the chat REPL `:doctor` slash.

The pure check logic lives in `knowlet.core.doctor` (ADR-0020 §Layer 5);
this module owns the rich-table rendering and re-exports the runner so
existing callers keep working.
"""

from __future__ import annotations

from rich.table import Table

from knowlet.cli._common import console
from knowlet.core.doctor import run_doctor_checks

__all__ = ["print_doctor", "run_doctor_checks"]


def print_doctor(results: list[tuple[str, str, str]]) -> None:
    icons = {"ok": "[green]✓[/green]", "fail": "[red]✗[/red]", "warn": "[yellow]⚠[/yellow]"}
    table = Table(show_header=True, header_style="bold", box=None)
    table.add_column("", width=2)
    table.add_column("check", style="bold")
    table.add_column("detail", overflow="fold")
    for status, name, detail in results:
        table.add_row(icons[status], name, detail)
    console.print(table)
    failures = sum(1 for r in results if r[0] == "fail")
    warnings = sum(1 for r in results if r[0] == "warn")
    if failures:
        console.print(f"\n[red]doctor: {failures} failure(s), {warnings} warning(s)[/red]")
    elif warnings:
        console.print(f"\n[yellow]doctor: {warnings} warning(s)[/yellow]")
    else:
        console.print("\n[green]doctor: all checks passed[/green]")
