"""`knowlet graph` — Phase 1 C slice 3 CLI peer of `/api/graph`.

The Web UI's force-directed graph view is fundamentally visual and
doesn't translate to a CLI tabular form, but the underlying *data*
should still be reachable from the CLI per [ADR-0008](../docs/decisions/0008-cli-parity-discipline.md).
`knowlet graph export` dumps the same `{nodes, edges}` JSON the Web UI
consumes, so external tooling (jq pipelines, third-party visualizers)
can chain on top.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from knowlet.cli._common import (
    console,
    load_config_or_default,
    make_index,
    resolve_vault_or_die,
)
from knowlet.core.graph import build_graph, read_body_via_note

app = typer.Typer(help="Inspect the user-authored bilink graph.", no_args_is_help=True)


@app.command("export")
def graph_export(
    output: Annotated[
        str,
        typer.Option(
            "--output",
            "-o",
            help="Write to a file path; default `-` = stdout.",
        ),
    ] = "-",
    pretty: Annotated[
        bool,
        typer.Option(
            "--pretty/--compact",
            help="Indent the JSON for human reading.",
        ),
    ] = True,
) -> None:
    """Dump the full bilink graph as `{nodes, edges}` JSON.

    Same shape as `GET /api/graph`. Dangling `[[Foo]]` references
    (target Note doesn't exist) are excluded — they're surfaced by
    the Linter (per [ADR-0023 §5](../docs/decisions/0023-llm-wiki-comparison-and-takeaways.md))."""
    vault = resolve_vault_or_die()
    cfg = load_config_or_default(vault)
    idx = make_index(vault, cfg)
    try:
        metas = idx.list_notes(limit=None)

        def _read_body(path_str: str) -> str:
            p = Path(path_str)
            if not p.is_absolute():
                p = vault.notes_dir / p.name
            return read_body_via_note(p)

        graph = build_graph(
            metas,
            folder_for=vault.folder_of,
            read_body=_read_body,
        )
        payload = {
            "nodes": [
                {
                    "id": n.id,
                    "title": n.title,
                    "folder": n.folder,
                    "in_degree": n.in_degree,
                    "out_degree": n.out_degree,
                }
                for n in graph.nodes
            ],
            "edges": [{"source": e.source, "target": e.target} for e in graph.edges],
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2 if pretty else None)
        if output == "-":
            console.print(text)
        else:
            Path(output).write_text(text, encoding="utf-8")
            console.print(
                f"[green]wrote[/green] {len(graph.nodes)} nodes / "
                f"{len(graph.edges)} edges → {output}"
            )
    finally:
        idx.close()
