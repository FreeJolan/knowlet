"""Sync tracking for Stage C digest files."""

from __future__ import annotations

from pathlib import Path

from knowlet.core.digest_items import RawInfo, RawInfoStore
from knowlet.core.digest_sources import DigestSource, DigestSourceStore
from knowlet.core.sync.credentials import SyncCredentials, credentials_path, save_credentials
from knowlet.core.sync.oauth import SCOPES
from knowlet.core.sync.push import DIGEST_SOURCE_ENTITY_TYPE, RAW_INFO_ENTITY_TYPE
from knowlet.core.sync.state import FileState, SyncStateStore
from knowlet.core.vault import Vault


def _vault(tmp_path: Path) -> Vault:
    vault = Vault(tmp_path)
    vault.init_layout()
    return vault


def _seed_creds(vault: Vault) -> None:
    save_credentials(
        credentials_path(vault.root),
        SyncCredentials(
            user_email="alice@example.com",
            token={
                "scopes": list(SCOPES),
                "token": "x",
                "refresh_token": "y",
                "client_id": "c",
                "client_secret": "s",
                "token_uri": "https://oauth2.googleapis.com/token",
            },
        ),
    )


def test_digest_source_save_queues_sync_when_drive_is_connected(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    _seed_creds(vault)
    source = DigestSource(name="AI feed", kind="rss", url="https://example.com/feed.xml")

    path = DigestSourceStore(vault.digest_sources_dir).save(source)

    store = SyncStateStore(vault.root)
    try:
        rec = store.get_file_state(DIGEST_SOURCE_ENTITY_TYPE, path.name)
    finally:
        store.close()
    assert rec is not None
    assert rec.drive_file_id is None
    assert rec.dirty is True


def test_raw_info_save_queues_sync_when_drive_is_connected(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    _seed_creds(vault)
    item = RawInfo(
        source_id="source-1",
        source_name="AI feed",
        source_kind="rss",
        item_key="rss:item-1",
        title="Raw item",
        url="https://example.com/item",
        summary="Needs review.",
    )

    path = RawInfoStore(vault.digest_items_dir).save(item)

    store = SyncStateStore(vault.root)
    try:
        rec = store.get_file_state(RAW_INFO_ENTITY_TYPE, path.name)
    finally:
        store.close()
    assert rec is not None
    assert rec.drive_file_id is None
    assert rec.dirty is True


def test_digest_source_delete_queues_drive_delete_when_tracked(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    _seed_creds(vault)
    store = DigestSourceStore(vault.digest_sources_dir)
    source = DigestSource(name="AI feed", kind="rss", url="https://example.com/feed.xml")
    path = store.save(source)

    state = SyncStateStore(vault.root)
    try:
        state.upsert_file_state(
            FileState(
                entity_type=DIGEST_SOURCE_ENTITY_TYPE,
                entity_id=path.name,
                drive_file_id="DRIVE-SOURCE",
                last_known_etag="rev-1",
                last_synced_at="2026-05-31T00:00:00Z",
                dirty=False,
            )
        )
    finally:
        state.close()

    assert store.delete(source.id) is True

    state = SyncStateStore(vault.root)
    try:
        rec = state.get_file_state(DIGEST_SOURCE_ENTITY_TYPE, path.name)
    finally:
        state.close()
    assert rec is not None
    assert rec.drive_file_id == "DRIVE-SOURCE"
    assert rec.dirty is False
    assert rec.delete_intent == "hard"
