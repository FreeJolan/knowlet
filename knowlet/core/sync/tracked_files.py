"""Helpers for syncing non-note vault data files.

Notes and attachments have custom sync code. Everything else that is still
durable vault data is described here as a small allow-list: profile,
cards, drafts, mining tasks, digest settings/items, quick actions,
favorites, quizzes, and the vault wiki schema.

The inverse rule is just as important: local device state, credentials,
indexes, caches, backups, and raw config files do not appear in this
inventory, so they cannot accidentally leak through Drive appData.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, unquote

from knowlet.config import VAULT_MARKER_DIR
from knowlet.core.vault import (
    CARDS_DIR,
    DIGEST_DIR,
    DIGEST_ITEMS_DIR,
    DIGEST_SOURCES_DIR,
    DRAFTS_DIR,
    PROFILE_FILENAME,
    TASKS_DIR,
    USERS_DIR,
)

DIGEST_SOURCE_ENTITY_TYPE = "digest_source"
RAW_INFO_ENTITY_TYPE = "raw_info"
USER_PROFILE_ENTITY_TYPE = "user_profile"
CARD_ENTITY_TYPE = "card"
DRAFT_ENTITY_TYPE = "draft"
MINING_TASK_ENTITY_TYPE = "mining_task"
WIKI_SCHEMA_ENTITY_TYPE = "wiki_schema"
QUICK_ACTIONS_ENTITY_TYPE = "quick_actions"
FAVORITES_ENTITY_TYPE = "favorites"
QUIZ_SESSION_ENTITY_TYPE = "quiz_session"
CONFIG_SNAPSHOT_ENTITY_TYPE = "config_snapshot"

SYNCABLE_VAULT_FILE_ENTITY_TYPES = {
    DIGEST_SOURCE_ENTITY_TYPE,
    RAW_INFO_ENTITY_TYPE,
    USER_PROFILE_ENTITY_TYPE,
    CARD_ENTITY_TYPE,
    DRAFT_ENTITY_TYPE,
    MINING_TASK_ENTITY_TYPE,
    WIKI_SCHEMA_ENTITY_TYPE,
    QUICK_ACTIONS_ENTITY_TYPE,
    FAVORITES_ENTITY_TYPE,
    QUIZ_SESSION_ENTITY_TYPE,
    CONFIG_SNAPSHOT_ENTITY_TYPE,
}

SYNCABLE_VAULT_FILE_PREFIXES = {
    DIGEST_SOURCE_ENTITY_TYPE: "digest-source__",
    RAW_INFO_ENTITY_TYPE: "raw-info__",
    USER_PROFILE_ENTITY_TYPE: "user-profile__",
    CARD_ENTITY_TYPE: "card__",
    DRAFT_ENTITY_TYPE: "draft__",
    MINING_TASK_ENTITY_TYPE: "mining-task__",
    WIKI_SCHEMA_ENTITY_TYPE: "wiki-schema__",
    QUICK_ACTIONS_ENTITY_TYPE: "quick-actions__",
    FAVORITES_ENTITY_TYPE: "favorites__",
    QUIZ_SESSION_ENTITY_TYPE: "quiz-session__",
    CONFIG_SNAPSHOT_ENTITY_TYPE: "config-snapshot__",
}


@dataclass(frozen=True)
class SyncableVaultFile:
    entity_type: str
    entity_id: str
    path: Path
    mime_type: str


@dataclass(frozen=True)
class _FileSpec:
    entity_type: str
    root_parts: tuple[str, ...]
    suffixes: tuple[str, ...]
    mime_type: str
    recursive: bool = False
    allow_dotdirs: bool = False
    single_filename: str | None = None

    def root(self, vault_root: Path) -> Path:
        return vault_root.joinpath(*self.root_parts)

    def iter_paths(self, vault_root: Path) -> list[Path]:
        root = self.root(vault_root)
        if self.single_filename is not None:
            candidate = root / self.single_filename
            return [candidate] if candidate.is_file() else []
        if not root.exists():
            return []
        iterator = root.rglob("*") if self.recursive else root.iterdir()
        return [path for path in iterator if self.matches_path(vault_root, path)]

    def matches_path(self, vault_root: Path, path: Path) -> bool:
        root = self.root(vault_root)
        try:
            rel = path.resolve().relative_to(root.resolve())
        except ValueError:
            return False
        if self.single_filename is not None:
            return rel.as_posix() == self.single_filename
        if not self.recursive and len(rel.parts) != 1:
            return False
        if not self.allow_dotdirs and any(part.startswith(".") for part in rel.parts[:-1]):
            return False
        if not self.suffixes:
            return True
        return path.suffix.lower() in self.suffixes

    def entity_id_for_path(self, vault_root: Path, path: Path) -> str:
        root = self.root(vault_root)
        rel = path.resolve().relative_to(root.resolve())
        return _encode_relative_path(rel)

    def path_for_entity_id(self, vault_root: Path, entity_id: str) -> Path | None:
        if self.single_filename is not None and entity_id != self.single_filename:
            return None
        rel = Path(_decode_relative_path(entity_id))
        if rel.is_absolute() or any(part in {"", ".", ".."} for part in rel.parts):
            return None
        if not self.allow_dotdirs and any(part.startswith(".") for part in rel.parts[:-1]):
            return None
        if self.single_filename is None and not self.recursive and len(rel.parts) != 1:
            return None
        if self.single_filename is not None and rel.as_posix() != self.single_filename:
            return None
        if self.suffixes and rel.suffix.lower() not in self.suffixes:
            return None
        target = self.root(vault_root) / rel
        try:
            target.resolve().relative_to(self.root(vault_root).resolve())
        except ValueError:
            return None
        return target


_SPECS: tuple[_FileSpec, ...] = (
    _FileSpec(
        USER_PROFILE_ENTITY_TYPE,
        (USERS_DIR,),
        (".md",),
        "text/markdown",
        single_filename=PROFILE_FILENAME,
    ),
    _FileSpec(CARD_ENTITY_TYPE, (CARDS_DIR,), (".json",), "application/json"),
    _FileSpec(
        DRAFT_ENTITY_TYPE,
        (DRAFTS_DIR,),
        (".md",),
        "text/markdown",
        recursive=True,
        allow_dotdirs=True,
    ),
    _FileSpec(MINING_TASK_ENTITY_TYPE, (TASKS_DIR,), (".md",), "text/markdown"),
    _FileSpec(
        DIGEST_SOURCE_ENTITY_TYPE,
        (VAULT_MARKER_DIR, DIGEST_DIR, DIGEST_SOURCES_DIR),
        (".json",),
        "application/json",
    ),
    _FileSpec(
        RAW_INFO_ENTITY_TYPE,
        (VAULT_MARKER_DIR, DIGEST_DIR, DIGEST_ITEMS_DIR),
        (".json",),
        "application/json",
    ),
    _FileSpec(
        WIKI_SCHEMA_ENTITY_TYPE,
        (VAULT_MARKER_DIR,),
        (".md",),
        "text/markdown",
        single_filename="wiki_schema.md",
    ),
    _FileSpec(
        QUICK_ACTIONS_ENTITY_TYPE,
        (VAULT_MARKER_DIR,),
        (".toml",),
        "application/toml",
        single_filename="quick-actions.toml",
    ),
    _FileSpec(
        FAVORITES_ENTITY_TYPE,
        (VAULT_MARKER_DIR,),
        (".json",),
        "application/json",
        single_filename="favorites.json",
    ),
    _FileSpec(
        QUIZ_SESSION_ENTITY_TYPE,
        (VAULT_MARKER_DIR, "quizzes"),
        (".json",),
        "application/json",
        recursive=True,
        allow_dotdirs=True,
    ),
    _FileSpec(
        CONFIG_SNAPSHOT_ENTITY_TYPE,
        (VAULT_MARKER_DIR, "sync"),
        (".toml",),
        "application/toml",
        single_filename="config-public.toml",
    ),
)

_SPECS_BY_ENTITY_TYPE = {spec.entity_type: spec for spec in _SPECS}


def _encode_relative_path(rel: Path) -> str:
    rel_posix = rel.as_posix()
    if "/" not in rel_posix:
        return rel_posix
    return quote(rel_posix, safe="")


def _decode_relative_path(entity_id: str) -> str:
    return unquote(entity_id)


def iter_syncable_vault_files(vault_root: Path) -> list[SyncableVaultFile]:
    """Return every currently existing non-note vault data file we sync."""
    out: list[SyncableVaultFile] = []
    for spec in _SPECS:
        for path in spec.iter_paths(vault_root):
            out.append(
                SyncableVaultFile(
                    entity_type=spec.entity_type,
                    entity_id=spec.entity_id_for_path(vault_root, path),
                    path=path,
                    mime_type=spec.mime_type,
                )
            )
    out.sort(key=lambda item: (item.entity_type, item.entity_id))
    return out


def syncable_vault_file_for_path(vault_root: Path, path: Path) -> SyncableVaultFile | None:
    """Return the sync inventory row for ``path`` even if the path was
    already deleted. Delete hooks need this after they know the old path.
    """
    for spec in _SPECS:
        if not spec.matches_path(vault_root, path):
            continue
        return SyncableVaultFile(
            entity_type=spec.entity_type,
            entity_id=spec.entity_id_for_path(vault_root, path),
            path=path,
            mime_type=spec.mime_type,
        )
    return None


def resolve_syncable_vault_file_path(
    vault_root: Path,
    entity_type: str,
    entity_id: str,
) -> Path | None:
    spec = _SPECS_BY_ENTITY_TYPE.get(entity_type)
    if spec is None:
        return None
    return spec.path_for_entity_id(vault_root, entity_id)


def mime_type_for_entity_type(entity_type: str) -> str:
    spec = _SPECS_BY_ENTITY_TYPE.get(entity_type)
    if spec is None:
        raise ValueError(f"unsupported synced file entity_type: {entity_type!r}")
    return spec.mime_type


def digest_sources_root(vault_root: Path) -> Path:
    return vault_root / VAULT_MARKER_DIR / DIGEST_DIR / DIGEST_SOURCES_DIR


def digest_items_root(vault_root: Path) -> Path:
    return vault_root / VAULT_MARKER_DIR / DIGEST_DIR / DIGEST_ITEMS_DIR


def infer_vault_root_from_digest_dir(root: Path) -> Path | None:
    """Return vault root for ``.knowlet/digest/{sources,items}`` paths."""
    if (
        root.name in {DIGEST_SOURCES_DIR, DIGEST_ITEMS_DIR}
        and root.parent.name == DIGEST_DIR
        and root.parent.parent.name == VAULT_MARKER_DIR
    ):
        return root.parent.parent.parent
    return None


def queue_synced_json_if_authenticated(
    *,
    vault_root: Path,
    entity_type: str,
    entity_id: str,
) -> None:
    """Backward-compatible alias for digest JSON callers."""
    queue_syncable_file_if_authenticated(
        vault_root=vault_root,
        entity_type=entity_type,
        entity_id=entity_id,
    )


def queue_syncable_file_if_authenticated(
    *,
    vault_root: Path,
    entity_type: str,
    entity_id: str,
) -> None:
    """Mark a syncable vault file dirty when Drive credentials exist.

    If the user has not connected Drive yet, do nothing. The drainer's
    first creds-positive untracked sweep will queue existing files later.
    """
    from knowlet.core.sync.credentials import credentials_path, load_credentials
    from knowlet.core.sync.state import FileState, SyncStateStore

    if entity_type not in SYNCABLE_VAULT_FILE_ENTITY_TYPES:
        raise ValueError(f"unsupported synced file entity_type: {entity_type!r}")
    if load_credentials(credentials_path(vault_root)) is None:
        return

    store = SyncStateStore(vault_root)
    try:
        rec = store.get_file_state(entity_type, entity_id)
        if rec is None:
            store.upsert_file_state(
                FileState(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    drive_file_id=None,
                    last_known_etag=None,
                    last_synced_at=None,
                    dirty=True,
                )
            )
            return
        if rec.dirty:
            return
        store.upsert_file_state(
            FileState(
                entity_type=rec.entity_type,
                entity_id=rec.entity_id,
                drive_file_id=rec.drive_file_id,
                last_known_etag=rec.last_known_etag,
                last_synced_at=rec.last_synced_at,
                dirty=True,
                dismissed_until=rec.dismissed_until,
                delete_intent=rec.delete_intent,
            )
        )
    finally:
        store.close()


def queue_synced_json_delete_if_authenticated(
    *,
    vault_root: Path,
    entity_type: str,
    entity_id: str,
) -> None:
    """Backward-compatible alias for digest JSON callers."""
    queue_syncable_file_delete_if_authenticated(
        vault_root=vault_root,
        entity_type=entity_type,
        entity_id=entity_id,
    )


def queue_syncable_file_delete_if_authenticated(
    *,
    vault_root: Path,
    entity_type: str,
    entity_id: str,
) -> None:
    """Queue Drive deletion for a syncable vault file removed locally."""
    from knowlet.core.sync.credentials import credentials_path, load_credentials
    from knowlet.core.sync.state import FileState, SyncStateStore

    if entity_type not in SYNCABLE_VAULT_FILE_ENTITY_TYPES:
        raise ValueError(f"unsupported synced file entity_type: {entity_type!r}")
    if load_credentials(credentials_path(vault_root)) is None:
        return

    store = SyncStateStore(vault_root)
    try:
        rec = store.get_file_state(entity_type, entity_id)
        if rec is None:
            return
        if rec.drive_file_id is None:
            store.remove_file_state(entity_type, entity_id)
            return
        store.upsert_file_state(
            FileState(
                entity_type=rec.entity_type,
                entity_id=rec.entity_id,
                drive_file_id=rec.drive_file_id,
                last_known_etag=rec.last_known_etag,
                last_synced_at=rec.last_synced_at,
                dirty=False,
                dismissed_until=rec.dismissed_until,
                delete_intent="hard",
            )
        )
    finally:
        store.close()


def queue_syncable_vault_file_if_authenticated(*, vault_root: Path, path: Path) -> None:
    item = syncable_vault_file_for_path(vault_root, path)
    if item is None:
        return
    queue_syncable_file_if_authenticated(
        vault_root=vault_root,
        entity_type=item.entity_type,
        entity_id=item.entity_id,
    )


def queue_syncable_vault_file_delete_if_authenticated(*, vault_root: Path, path: Path) -> None:
    item = syncable_vault_file_for_path(vault_root, path)
    if item is None:
        return
    queue_syncable_file_delete_if_authenticated(
        vault_root=vault_root,
        entity_type=item.entity_type,
        entity_id=item.entity_id,
    )
