from __future__ import annotations

from pathlib import Path

from knowlet.config import (
    KnowletConfig,
    apply_synced_config_snapshot,
    config_path,
    load_config,
    save_config,
    synced_config_snapshot_path,
)
from knowlet.core.card import Card
from knowlet.core.card_store import CardStore
from knowlet.core.drafts import Draft, DraftStore
from knowlet.core.favorites import FavoritesStore
from knowlet.core.mining.task import MiningTask
from knowlet.core.mining.task_store import TaskStore
from knowlet.core.quick_actions import CreateNoteParams, QuickAction, QuickActionStore
from knowlet.core.quiz import QuizSession
from knowlet.core.quiz_store import QuizStore
from knowlet.core.sync.credentials import SyncCredentials, credentials_path, save_credentials
from knowlet.core.sync.files import DriveFileBrief
from knowlet.core.sync.oauth import SCOPES
from knowlet.core.sync.push import appdata_entity_from_drive_name, drive_appdata_name
from knowlet.core.sync.restore import restore_vault_from_drive
from knowlet.core.sync.state import FileState, SyncStateStore
from knowlet.core.sync.tracked_files import (
    CARD_ENTITY_TYPE,
    CONFIG_SNAPSHOT_ENTITY_TYPE,
    DRAFT_ENTITY_TYPE,
    FAVORITES_ENTITY_TYPE,
    MINING_TASK_ENTITY_TYPE,
    QUICK_ACTIONS_ENTITY_TYPE,
    QUIZ_SESSION_ENTITY_TYPE,
    USER_PROFILE_ENTITY_TYPE,
    WIKI_SCHEMA_ENTITY_TYPE,
    iter_syncable_vault_files,
    resolve_syncable_vault_file_path,
    syncable_vault_file_for_path,
)
from knowlet.core.user_profile import UserProfile, write_profile
from knowlet.core.vault import Vault
from knowlet.core.vault_identity import write_vault_id


def _touch(path: Path, text: str = "x\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


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


def test_iter_syncable_vault_files_includes_user_data_and_excludes_local_state(
    tmp_path: Path,
) -> None:
    vault = Vault(tmp_path)
    vault.init_layout()
    _touch(vault.profile_path, "# Me\n")
    _touch(vault.cards_dir / "01CARD.json", '{"front":"q"}\n')
    _touch(vault.drafts_dir / "01DRAFT.md", "---\nid: 01DRAFT\n---\n")
    _touch(vault.drafts_dir / ".archive" / "2026-06" / "01OLD.md", "old\n")
    _touch(vault.tasks_dir / "01TASK.md", "---\nid: 01TASK\n---\n")
    _touch(vault.state_dir / "quick-actions.toml", "schema_version = 1\n")
    _touch(vault.state_dir / "favorites.json", '{"ids":[]}\n')
    _touch(vault.state_dir / "quizzes" / "01QUIZ.json", '{"id":"01QUIZ"}\n')
    _touch(vault.state_dir / "digest" / "sources" / "01SRC.json", "{}\n")
    _touch(vault.state_dir / "config.toml", 'api_key = "secret"\n')
    _touch(vault.state_dir / "sync_credentials.json", '{"token":"secret"}\n')
    _touch(vault.state_dir / "index.sqlite", "cache")

    files = list(iter_syncable_vault_files(vault.root))
    by_rel = {
        item.path.relative_to(vault.root).as_posix(): (item.entity_type, item.entity_id)
        for item in files
    }

    assert by_rel["users/me.md"][0] == USER_PROFILE_ENTITY_TYPE
    assert by_rel["cards/01CARD.json"][0] == CARD_ENTITY_TYPE
    assert by_rel["drafts/01DRAFT.md"][0] == DRAFT_ENTITY_TYPE
    assert by_rel["drafts/.archive/2026-06/01OLD.md"][0] == DRAFT_ENTITY_TYPE
    assert "/" not in by_rel["drafts/.archive/2026-06/01OLD.md"][1]
    assert by_rel["tasks/01TASK.md"][0] == MINING_TASK_ENTITY_TYPE
    assert by_rel[".knowlet/wiki_schema.md"][0] == WIKI_SCHEMA_ENTITY_TYPE
    assert by_rel[".knowlet/quick-actions.toml"][0] == QUICK_ACTIONS_ENTITY_TYPE
    assert by_rel[".knowlet/favorites.json"][0] == FAVORITES_ENTITY_TYPE
    assert by_rel[".knowlet/quizzes/01QUIZ.json"][0] == QUIZ_SESSION_ENTITY_TYPE
    assert ".knowlet/config.toml" not in by_rel
    assert ".knowlet/sync_credentials.json" not in by_rel
    assert ".knowlet/index.sqlite" not in by_rel


def test_syncable_vault_file_round_trips_encoded_nested_paths(tmp_path: Path) -> None:
    vault = Vault(tmp_path)
    vault.init_layout()
    archived = _touch(vault.drafts_dir / ".archive" / "2026-06" / "01OLD.md", "old\n")

    item = syncable_vault_file_for_path(vault.root, archived)

    assert item is not None
    assert item.entity_type == DRAFT_ENTITY_TYPE
    assert item.entity_id == ".archive%2F2026-06%2F01OLD.md"
    drive_name = drive_appdata_name(item.entity_type, item.entity_id, vault_root=vault.root)
    parsed = appdata_entity_from_drive_name(drive_name, vault_root=vault.root)
    assert parsed == (DRAFT_ENTITY_TYPE, item.entity_id)
    assert (
        resolve_syncable_vault_file_path(vault.root, item.entity_type, item.entity_id) == archived
    )


def test_restore_vault_from_drive_materializes_generic_vault_files(
    monkeypatch,
    tmp_path: Path,
) -> None:
    vault = Vault(tmp_path / "Restored")
    vault.init_layout()
    write_vault_id(vault.root, "01REMOTEVAULTID000000000000")
    draft_entity_id = ".archive%2F2026-06%2F01OLD.md"
    drive_files = {
        "DRIVE-PROFILE": DriveFileBrief(
            name=drive_appdata_name(
                USER_PROFILE_ENTITY_TYPE,
                "me.md",
                vault_root=vault.root,
            ),
            head_revision_id="rev-profile",
        ),
        "DRIVE-TASK": DriveFileBrief(
            name=drive_appdata_name(
                MINING_TASK_ENTITY_TYPE,
                "01TASK.md",
                vault_root=vault.root,
            ),
            head_revision_id="rev-task",
        ),
        "DRIVE-QA": DriveFileBrief(
            name=drive_appdata_name(
                QUICK_ACTIONS_ENTITY_TYPE,
                "quick-actions.toml",
                vault_root=vault.root,
            ),
            head_revision_id="rev-qa",
        ),
        "DRIVE-DRAFT": DriveFileBrief(
            name=drive_appdata_name(
                DRAFT_ENTITY_TYPE,
                draft_entity_id,
                vault_root=vault.root,
            ),
            head_revision_id="rev-draft",
        ),
    }
    bodies = {
        "DRIVE-PROFILE": b"# Me\n",
        "DRIVE-TASK": b"---\nid: 01TASK\n---\n",
        "DRIVE-QA": b"schema_version = 1\n",
        "DRIVE-DRAFT": b"old\n",
    }

    monkeypatch.setattr(
        "knowlet.core.sync.restore.list_appdata_revisions",
        lambda _service: drive_files,
    )
    monkeypatch.setattr(
        "knowlet.core.sync.restore.download_file",
        lambda _service, file_id: bodies[file_id],
    )

    report = restore_vault_from_drive(object(), vault_root=vault.root)

    assert report.materialized_count == 4
    assert (vault.users_dir / "me.md").read_text(encoding="utf-8") == "# Me\n"
    assert (vault.tasks_dir / "01TASK.md").read_text(encoding="utf-8").startswith("---")
    assert (vault.state_dir / "quick-actions.toml").read_text(encoding="utf-8") == (
        "schema_version = 1\n"
    )
    assert (vault.drafts_dir / ".archive" / "2026-06" / "01OLD.md").read_text(
        encoding="utf-8"
    ) == "old\n"
    state = SyncStateStore(vault.root)
    try:
        assert state.get_file_state(USER_PROFILE_ENTITY_TYPE, "me.md") is not None
        assert state.get_file_state(MINING_TASK_ENTITY_TYPE, "01TASK.md") is not None
        assert state.get_file_state(QUICK_ACTIONS_ENTITY_TYPE, "quick-actions.toml") is not None
        assert state.get_file_state(DRAFT_ENTITY_TYPE, draft_entity_id) is not None
    finally:
        state.close()


def test_syncable_store_writes_queue_dirty_when_drive_connected(tmp_path: Path) -> None:
    vault = Vault(tmp_path)
    vault.init_layout()
    _seed_creds(vault)

    card = Card(front="q", back="a")
    card_path = CardStore(vault.cards_dir).save(card)
    draft = Draft(title="Draft", body="draft")
    draft_path = DraftStore(vault.drafts_dir).save(draft)
    task = MiningTask(name="Task", prompt="collect")
    task_path = TaskStore(vault.tasks_dir).save(task)
    QuickActionStore(vault.root).save(
        [
            QuickAction(
                id="qa-1",
                name="Daily",
                params=CreateNoteParams(folder="", title_template="{{date}}"),
            )
        ]
    )
    FavoritesStore(vault.root).add("note-1")
    write_profile(vault.profile_path, UserProfile(body="Alice"))
    quiz_path = QuizStore(vault.state_dir).save(
        QuizSession(id="quiz-1", started_at="2026-06-04T00:00:00Z", questions=[])
    )

    state = SyncStateStore(vault.root)
    try:
        queued = {
            (row.entity_type, row.entity_id): row for row in state.list_all_files() if row.dirty
        }
    finally:
        state.close()

    assert (CARD_ENTITY_TYPE, card_path.name) in queued
    assert (DRAFT_ENTITY_TYPE, draft_path.name) in queued
    assert (MINING_TASK_ENTITY_TYPE, task_path.name) in queued
    assert (QUICK_ACTIONS_ENTITY_TYPE, "quick-actions.toml") in queued
    assert (FAVORITES_ENTITY_TYPE, "favorites.json") in queued
    assert (USER_PROFILE_ENTITY_TYPE, "me.md") in queued
    assert (QUIZ_SESSION_ENTITY_TYPE, quiz_path.name) in queued


def test_save_config_writes_scrubbed_sync_snapshot_and_queues(tmp_path: Path) -> None:
    vault = Vault(tmp_path)
    vault.init_layout()
    _seed_creds(vault)
    cfg = KnowletConfig()
    cfg.general.language = "zh"
    cfg.llm.base_url = "https://llm.example.test/v1"
    cfg.llm.api_key = "llm-secret"
    cfg.llm.model = "gpt-5.5"
    cfg.web_search.provider = "brave"
    cfg.web_search.brave_api_key = "brave-secret"
    cfg.sync.client_secrets_path = "/Users/alice/client-secret.json"

    save_config(vault.root, cfg)

    snapshot = synced_config_snapshot_path(vault.root)
    text = snapshot.read_text(encoding="utf-8")
    assert "gpt-5.5" in text
    assert "https://llm.example.test/v1" in text
    assert "llm-secret" not in text
    assert "brave-secret" not in text
    assert "client-secret.json" not in text
    state = SyncStateStore(vault.root)
    try:
        row = state.get_file_state(CONFIG_SNAPSHOT_ENTITY_TYPE, "config-public.toml")
    finally:
        state.close()
    assert row is not None
    assert row.dirty is True


def test_apply_synced_config_snapshot_preserves_local_secrets(tmp_path: Path) -> None:
    vault = Vault(tmp_path)
    vault.init_layout()
    local = KnowletConfig()
    local.llm.api_key = "local-llm-secret"
    local.web_search.brave_api_key = "local-brave-secret"
    local.sync.client_secrets_path = "/local/client.json"
    save_config(vault.root, local, sync_snapshot=False)
    snapshot = synced_config_snapshot_path(vault.root)
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_text(
        "\n".join(
            [
                "[general]",
                'language = "zh"',
                "",
                "[llm]",
                'base_url = "https://remote.example.test/v1"',
                'model = "remote-model"',
                "max_tokens = 4096",
                "",
                "[web_search]",
                'provider = "brave"',
                "max_per_turn = 5",
                "",
            ]
        ),
        encoding="utf-8",
    )

    merged = apply_synced_config_snapshot(vault.root)

    assert merged is not None
    loaded = load_config(vault.root)
    assert loaded.general.language == "zh"
    assert loaded.llm.model == "remote-model"
    assert loaded.llm.base_url == "https://remote.example.test/v1"
    assert loaded.llm.api_key == "local-llm-secret"
    assert loaded.web_search.provider == "brave"
    assert loaded.web_search.brave_api_key == "local-brave-secret"
    assert loaded.sync.client_secrets_path == "/local/client.json"


def test_restore_config_snapshot_applies_local_config(
    monkeypatch,
    tmp_path: Path,
) -> None:
    vault = Vault(tmp_path / "Restored")
    vault.init_layout()
    write_vault_id(vault.root, "01REMOTEVAULTID000000000000")
    drive_files = {
        "DRIVE-CONFIG": DriveFileBrief(
            name=drive_appdata_name(
                CONFIG_SNAPSHOT_ENTITY_TYPE,
                "config-public.toml",
                vault_root=vault.root,
            ),
            head_revision_id="rev-config",
        )
    }

    monkeypatch.setattr(
        "knowlet.core.sync.restore.list_appdata_revisions",
        lambda _service: drive_files,
    )
    monkeypatch.setattr(
        "knowlet.core.sync.restore.download_file",
        lambda _service, _file_id: (
            b'[llm]\nbase_url = "https://remote.example.test/v1"\nmodel = "remote-model"\n'
        ),
    )

    restore_vault_from_drive(object(), vault_root=vault.root)

    assert config_path(vault.root).exists()
    loaded = load_config(vault.root)
    assert loaded.llm.base_url == "https://remote.example.test/v1"
    assert loaded.llm.model == "remote-model"
    assert loaded.llm.api_key == ""


def test_syncable_store_deletes_queue_drive_delete_when_tracked(tmp_path: Path) -> None:
    vault = Vault(tmp_path)
    vault.init_layout()
    _seed_creds(vault)
    card = Card(front="q", back="a")
    card_path = CardStore(vault.cards_dir).save(card)
    draft = Draft(title="Draft", body="draft")
    draft_path = DraftStore(vault.drafts_dir).save(draft)

    state = SyncStateStore(vault.root)
    try:
        state.upsert_file_state(
            FileState(
                entity_type=CARD_ENTITY_TYPE,
                entity_id=card_path.name,
                drive_file_id="DRIVE-CARD",
                last_known_etag="rev-card",
                last_synced_at="2026-06-04T00:00:00Z",
                dirty=False,
            )
        )
        state.upsert_file_state(
            FileState(
                entity_type=DRAFT_ENTITY_TYPE,
                entity_id=draft_path.name,
                drive_file_id="DRIVE-DRAFT",
                last_known_etag="rev-draft",
                last_synced_at="2026-06-04T00:00:00Z",
                dirty=False,
            )
        )
    finally:
        state.close()

    assert CardStore(vault.cards_dir).delete(card.id) is True
    assert DraftStore(vault.drafts_dir).delete(draft.id) is True

    state = SyncStateStore(vault.root)
    try:
        card_row = state.get_file_state(CARD_ENTITY_TYPE, card_path.name)
        draft_row = state.get_file_state(DRAFT_ENTITY_TYPE, draft_path.name)
    finally:
        state.close()
    assert card_row is not None
    assert card_row.delete_intent == "hard"
    assert draft_row is not None
    assert draft_row.delete_intent == "hard"
