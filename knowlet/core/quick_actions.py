"""Phase 2 D Slice 2c — Quick Actions persistence (per ADR-0025).

A Quick Action is a saved, replayable "create document" preset:
position + title template + optional content template + optional
shortcut. ADR-0025 reserves space for additional `kind` values in
the future (apply_template, move_note, ingest_url, ...) but v1 only
ships ``kind="create_note"``.

Storage: ``<vault>/.knowlet/quick-actions.toml``. A single file
keyed by ``schema_version`` + an ``actions`` array. We read with
stdlib ``tomllib`` and write with a homegrown serializer (the
schema is small and we don't want a third-party dep).

Discriminated union by ``params.kind``: invalid kinds raise on load
so a user-edited file with a typo fails loud rather than silently
dropping the action.

Public API:
- ``QuickActionStore.load() -> list[QuickAction]``
- ``QuickActionStore.save(actions)``
- ``QuickActionStore.upsert(action) -> QuickAction``
- ``QuickActionStore.delete(action_id) -> bool``
- ``run_action(vault, index, action) -> ActionResult`` — applies the
  action; for v1 this means create-note in the right folder with the
  right template.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator
from ulid import ULID

from knowlet.config import VAULT_MARKER_DIR


SCHEMA_VERSION = 1
QUICK_ACTIONS_FILENAME = "quick-actions.toml"


class CreateNoteParams(BaseModel):
    """Parameters for ``kind="create_note"`` actions."""

    kind: Literal["create_note"] = "create_note"
    folder: str = ""
    title_template: str = ""
    content_template_id: str | None = None

    @field_validator("folder")
    @classmethod
    def _no_traversal(cls, v: str) -> str:
        # Match the safety rules in vault._resolve_subpath: no
        # absolute paths, no `..`, no leading dot directories.
        if not v:
            return v
        if v.startswith("/"):
            raise ValueError("folder must be a relative path")
        for part in v.split("/"):
            if part in ("", ".", ".."):
                raise ValueError(f"invalid folder segment: {part!r}")
            if part.startswith("."):
                raise ValueError(f"folder segments cannot start with '.': {part!r}")
        return v


# Discriminated union by `params.kind`. Add new kinds here as they
# ship; Pydantic + Field(discriminator=...) gives us a single error
# message ("input does not match any expected kind") for typos.
ActionParams = CreateNoteParams  # | OtherParams when more land


class QuickAction(BaseModel):
    """A single quick action — the schema persisted in TOML and
    surfaced to the frontend."""

    schema_version: int = SCHEMA_VERSION
    id: str
    name: str
    description: str | None = None
    shortcut: str | None = None
    params: ActionParams = Field(discriminator="kind")


def new_action_id() -> str:
    return str(ULID())


# ---------- store ----------


def quick_actions_path(vault_root: Path) -> Path:
    return vault_root / VAULT_MARKER_DIR / QUICK_ACTIONS_FILENAME


def _toml_value(v: Any) -> str:
    """Inline-value writer for the simple types we use here."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int) and not isinstance(v, bool):
        return str(v)
    if isinstance(v, str):
        # Conservative quoting: prefer the literal triple-quote / quote
        # form that round-trips; escape backslash + double-quote.
        escaped = v.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if v is None:
        return '""'
    raise TypeError(f"unserializable TOML value: {v!r} ({type(v).__name__})")


def _serialize(actions: list[QuickAction]) -> str:
    """Hand-rolled TOML writer for the schema. Format:

    .. code-block:: toml

        schema_version = 1

        [[actions]]
        id = "..."
        name = "..."
        # description / shortcut omitted when None

        [actions.params]
        kind = "create_note"
        folder = "..."
        title_template = "..."
        # content_template_id omitted when None
    """
    lines: list[str] = [f"schema_version = {SCHEMA_VERSION}", ""]
    for a in actions:
        lines.append("[[actions]]")
        lines.append(f"id = {_toml_value(a.id)}")
        lines.append(f"name = {_toml_value(a.name)}")
        if a.description is not None:
            lines.append(f"description = {_toml_value(a.description)}")
        if a.shortcut is not None:
            lines.append(f"shortcut = {_toml_value(a.shortcut)}")
        lines.append("")
        lines.append("[actions.params]")
        lines.append(f"kind = {_toml_value(a.params.kind)}")
        if isinstance(a.params, CreateNoteParams):
            lines.append(f"folder = {_toml_value(a.params.folder)}")
            lines.append(f"title_template = {_toml_value(a.params.title_template)}")
            if a.params.content_template_id is not None:
                lines.append(
                    f"content_template_id = {_toml_value(a.params.content_template_id)}"
                )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _atomic_write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(p)


@dataclass
class QuickActionStore:
    """Vault-scoped quick-action persistence."""

    vault_root: Path

    @property
    def path(self) -> Path:
        return quick_actions_path(self.vault_root)

    def load(self) -> list[QuickAction]:
        if not self.path.exists():
            return []
        with self.path.open("rb") as f:
            data = tomllib.load(f)
        # `actions` may be missing or empty.
        raw = data.get("actions") or []
        out: list[QuickAction] = []
        for entry in raw:
            # Move `params` table into a `params` field for Pydantic.
            params = entry.pop("params", None) or {}
            out.append(QuickAction.model_validate({**entry, "params": params}))
        return out

    def save(self, actions: list[QuickAction]) -> None:
        _atomic_write(self.path, _serialize(actions))

    def upsert(self, action: QuickAction) -> QuickAction:
        actions = self.load()
        idx = next((i for i, a in enumerate(actions) if a.id == action.id), -1)
        if idx >= 0:
            actions[idx] = action
        else:
            actions.append(action)
        self.save(actions)
        return action

    def delete(self, action_id: str) -> bool:
        actions = self.load()
        before = len(actions)
        actions = [a for a in actions if a.id != action_id]
        if len(actions) == before:
            return False
        self.save(actions)
        return True

    def get(self, action_id: str) -> QuickAction | None:
        for a in self.load():
            if a.id == action_id:
                return a
        return None


# ---------- placeholder rendering ----------


def render_title_placeholders(template: str, *, now: Any | None = None) -> str:
    """Server-side mirror of ``frontend/src/lib/placeholders.ts``.

    Supports ``{{date}} {{week}} {{month}} {{year}} {{time}} {{datetime}}``
    using LOCAL time (matching the frontend, which uses local-date
    semantics so a 23:30 entry in UTC+8 lands on the user's calendar
    day, not yesterday).
    """
    from datetime import datetime as _dt

    d = now if now is not None else _dt.now().astimezone()

    # ISO 8601 week (Mon-based, week containing Jan 4 is week 1).
    iso_year, iso_week, _ = d.isocalendar()

    yyyy = d.strftime("%Y")
    mm = d.strftime("%m")
    dd = d.strftime("%d")
    hh = d.strftime("%H")
    mi = d.strftime("%M")
    table = {
        "date": f"{yyyy}-{mm}-{dd}",
        "week": f"{iso_year}-W{iso_week:02d}",
        "month": f"{yyyy}-{mm}",
        "year": yyyy,
        "time": f"{hh}:{mi}",
        "datetime": f"{yyyy}-{mm}-{dd} {hh}:{mi}",
    }
    out = template
    for key, value in table.items():
        out = out.replace(f"{{{{{key}}}}}", value)
    return out
