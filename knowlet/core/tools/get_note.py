"""get_note — read the full body of a Note by id."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from knowlet.core.tools._registry import ToolContext, ToolDef


def _handler(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    note_id = (args.get("note_id") or "").strip()
    if not note_id:
        return {
            "error": "note_id is empty",
            "suggestion": "pass a note_id from a previous search_notes result",
        }
    meta = ctx.index.get_note_meta(note_id)
    if meta is None:
        return {
            "error": f"note not found: {note_id}",
            "suggestion": "call search_notes first to find a valid note_id",
        }
    path = Path(meta["path"])
    if not path.is_absolute():
        path = ctx.vault.notes_dir / path.name
    try:
        note = ctx.vault.read_note(path)
    except FileNotFoundError:
        return {
            "error": f"note file missing on disk: {path}",
            "suggestion": "run `knowlet reindex` to sync the index",
        }
    return {
        "note": {
            "id": note.id,
            "title": note.title,
            "tags": note.tags,
            "body": note.body,
            "created_at": note.created_at,
            "updated_at": note.updated_at,
        }
    }


TOOL = ToolDef(
    name="get_note",
    description=(
        "Fetch the full body of a Note by id. Use this when a search snippet is "
        "not enough and you need the complete content to answer the user."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "note_id": {
                "type": "string",
                "description": "ULID of the Note (from search_notes results)",
            }
        },
        "required": ["note_id"],
        "additionalProperties": False,
    },
    handler=_handler,
)
