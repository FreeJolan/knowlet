"""Regression tests for the 2026-11 audit findings in the `knowlet` CLI."""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import signal
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from typer.testing import CliRunner

from knowlet.cli.main import DESKTOP_PARENT_PID_ENV, app
from knowlet.config import KnowletConfig, load_config, save_config
from knowlet.core.digest_items import RawInfo, RawInfoStore
from knowlet.core.drafts import Draft, DraftStore
from knowlet.core.embedding import DummyBackend
from knowlet.core.index import Index
from knowlet.core.note import Note, new_id
from knowlet.core.vault import Vault

runner = CliRunner()

DIM = 32


def _ready_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Vault, KnowletConfig]:
    vault = Vault(tmp_path)
    vault.init_layout()
    cfg = KnowletConfig()
    cfg.embedding.backend = "dummy"
    cfg.embedding.dim = DIM
    cfg.llm.api_key = "stub"
    save_config(vault.root, cfg)
    monkeypatch.setenv("KNOWLET_VAULT", str(vault.root))
    return vault, cfg


def _open_index(vault: Vault) -> Index:
    idx = Index(vault.db_path, DummyBackend(dim=DIM))
    idx.connect()
    return idx


def _write_and_index(vault: Vault, note: Note, *, folder: str | None = None) -> Path:
    cfg = KnowletConfig()
    path = vault.write_note(note, folder=folder)
    idx = _open_index(vault)
    try:
        idx.upsert_note(
            note,
            chunk_size=cfg.retrieval.chunk_size,
            chunk_overlap=cfg.retrieval.chunk_overlap,
        )
    finally:
        idx.close()
    return path


def _index_meta(vault: Vault, note_id: str) -> dict[str, Any] | None:
    idx = _open_index(vault)
    try:
        return idx.get_note_meta(note_id)
    finally:
        idx.close()


# --------------------------------------------------------------- main.py:199


class _StopWatchdog(Exception):
    pass


def test_desktop_watchdog_requests_graceful_shutdown_before_hard_exit(monkeypatch):
    """Parent gone → SIGTERM (uvicorn graceful path, lifespan cleanup
    runs) first; os._exit only as the backstop after the grace period."""
    import knowlet.cli.main as main_mod

    calls: list[str] = []

    class _SyncThread:
        def __init__(self, *, target, name, daemon):
            self._target = target

        def start(self) -> None:
            with contextlib.suppress(_StopWatchdog):
                self._target()

    def _fake_exit(code: int) -> None:
        calls.append(f"exit:{code}")
        raise _StopWatchdog

    monkeypatch.setenv(DESKTOP_PARENT_PID_ENV, "999999")
    monkeypatch.setattr(main_mod.threading, "Thread", _SyncThread)
    monkeypatch.setattr(main_mod, "_process_exists", lambda _pid: False)
    monkeypatch.setattr(main_mod.time, "sleep", lambda _s: calls.append("sleep"))
    monkeypatch.setattr(signal, "raise_signal", lambda sig: calls.append(f"signal:{sig}"))
    monkeypatch.setattr(os, "_exit", _fake_exit)

    main_mod._start_desktop_parent_watchdog_from_env(interval_seconds=0)

    sigterm = f"signal:{signal.SIGTERM}"
    assert sigterm in calls, calls
    exit_index = next(i for i, c in enumerate(calls) if c.startswith("exit:"))
    assert calls.index(sigterm) < exit_index
    # A grace sleep separates the polite request from the hard exit.
    assert "sleep" in calls[calls.index(sigterm) : exit_index]


def test_web_bounds_graceful_shutdown_so_lifespan_cleanup_runs(tmp_path, monkeypatch):
    import knowlet.cli.main as main_mod

    _ready_vault(tmp_path, monkeypatch)
    captured: dict[str, Any] = {}

    def fake_run(app_obj, **kwargs):
        captured.update(kwargs)

    monkeypatch.delenv(DESKTOP_PARENT_PID_ENV, raising=False)
    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(run=fake_run))

    result = runner.invoke(app, ["web", "--port", "0"])

    assert result.exit_code == 0, result.output
    timeout = captured.get("timeout_graceful_shutdown")
    assert isinstance(timeout, int | float) and timeout > 0
    assert timeout < main_mod.DESKTOP_SHUTDOWN_GRACE_SECONDS


# --------------------------------------------------------------- main.py:253


def _make_dim_mismatch(vault: Vault) -> None:
    _write_and_index(vault, Note(id=new_id(), title="t", body="b"))
    cfg = load_config(vault.root)
    cfg.embedding.dim = DIM * 2
    save_config(vault.root, cfg)


@pytest.mark.parametrize("argv", [["reindex"], ["ls"], ["notes", "delete", "01X", "-y"]])
def test_embedding_dim_change_reports_rebuild_hint_not_traceback(tmp_path, monkeypatch, argv):
    vault, _cfg = _ready_vault(tmp_path, monkeypatch)
    _make_dim_mismatch(vault)

    result = runner.invoke(app, argv)

    assert result.exit_code == 2, (result.exit_code, result.output, result.exception)
    assert isinstance(result.exception, SystemExit), repr(result.exception)
    assert "reindex --rebuild" in result.output


def test_reindex_rebuild_still_recovers_from_dim_change(tmp_path, monkeypatch):
    vault, _cfg = _ready_vault(tmp_path, monkeypatch)
    _make_dim_mismatch(vault)

    result = runner.invoke(app, ["reindex", "--rebuild"])

    assert result.exit_code == 0, result.output
    assert "reindex done: 1 updated" in result.output


# --------------------------------------------------------------- notes.py:45

_PREFIX = "01JDK3F2"


def _twin_prefix_notes(vault: Vault) -> tuple[Note, Note]:
    a = Note(id=_PREFIX + "A" * 18, title="Alpha", body="a")
    b = Note(id=_PREFIX + "B" * 18, title="Beta", body="b")
    _write_and_index(vault, a)
    _write_and_index(vault, b)
    return a, b


def test_notes_delete_ambiguous_prefix_refuses_and_lists_candidates(tmp_path, monkeypatch):
    vault, _cfg = _ready_vault(tmp_path, monkeypatch)
    a, b = _twin_prefix_notes(vault)

    result = runner.invoke(app, ["notes", "delete", _PREFIX, "-y"])

    assert result.exit_code == 2, result.output
    assert "ambiguous" in result.output
    assert a.id in result.output and b.id in result.output
    assert (vault.notes_dir / a.filename).exists()
    assert (vault.notes_dir / b.filename).exists()
    assert not vault.trash_dir.exists() or not any(vault.trash_dir.glob("*.md"))


def test_notes_mv_ambiguous_prefix_refuses(tmp_path, monkeypatch):
    vault, _cfg = _ready_vault(tmp_path, monkeypatch)
    a, b = _twin_prefix_notes(vault)

    result = runner.invoke(app, ["notes", "mv", _PREFIX, "archive"])

    assert result.exit_code == 2, result.output
    assert (vault.notes_dir / a.filename).exists()
    assert (vault.notes_dir / b.filename).exists()


def test_notes_delete_unique_prefix_and_exact_id_still_work(tmp_path, monkeypatch):
    vault, _cfg = _ready_vault(tmp_path, monkeypatch)
    a, b = _twin_prefix_notes(vault)

    result = runner.invoke(app, ["notes", "delete", _PREFIX + "A", "-y"])
    assert result.exit_code == 0, result.output
    assert not (vault.notes_dir / a.filename).exists()

    result = runner.invoke(app, ["notes", "delete", b.id, "-y"])
    assert result.exit_code == 0, result.output
    assert not (vault.notes_dir / b.filename).exists()


def test_notes_delete_empty_prefix_does_not_match_everything(tmp_path, monkeypatch):
    vault, _cfg = _ready_vault(tmp_path, monkeypatch)
    only = Note(id=new_id(), title="Only", body="x")
    _write_and_index(vault, only)

    result = runner.invoke(app, ["notes", "delete", "", "-y"])

    assert result.exit_code != 0
    assert (vault.notes_dir / only.filename).exists()


# --------------------------------------------------------------- notes.py:340


def _hand_named_note(vault: Vault, folder: str, filename: str, title: str) -> Note:
    note = Note(id=new_id(), title=title, body="hand written")
    target_dir = vault.notes_dir / folder
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / filename
    path.write_text(note.to_markdown(), encoding="utf-8")
    note.path = path
    idx = _open_index(vault)
    try:
        cfg = KnowletConfig()
        idx.upsert_note(
            note, chunk_size=cfg.retrieval.chunk_size, chunk_overlap=cfg.retrieval.chunk_overlap
        )
    finally:
        idx.close()
    return note


def test_rmfolder_removes_index_rows_for_non_ulid_filenames(tmp_path, monkeypatch):
    vault, _cfg = _ready_vault(tmp_path, monkeypatch)
    readme = _hand_named_note(vault, "proj", "README.md", "Project readme")
    managed = Note(id=new_id(), title="Managed", body="m")
    _write_and_index(vault, managed, folder="proj")

    result = runner.invoke(app, ["notes", "rmfolder", "proj", "-y"])

    assert result.exit_code == 0, result.output
    assert _index_meta(vault, readme.id) is None
    assert _index_meta(vault, managed.id) is None


def test_rmfolder_removes_index_row_when_trash_renames_on_collision(tmp_path, monkeypatch):
    vault, _cfg = _ready_vault(tmp_path, monkeypatch)
    note = Note(id=new_id(), title="Collides", body="c")
    _write_and_index(vault, note, folder="proj")
    vault.trash_dir.mkdir(parents=True, exist_ok=True)
    (vault.trash_dir / note.filename).write_text("older trashed copy", encoding="utf-8")

    result = runner.invoke(app, ["notes", "rmfolder", "proj", "-y"])

    assert result.exit_code == 0, result.output
    assert _index_meta(vault, note.id) is None


@pytest.mark.parametrize(
    ("argv", "new_folder"),
    [
        (["notes", "mvfolder", "proj", "archive"], "archive/proj"),
        (["notes", "rnfolder", "proj", "renamed"], "renamed"),
    ],
)
def test_folder_move_resyncs_index_by_real_note_id(tmp_path, monkeypatch, argv, new_folder):
    vault, _cfg = _ready_vault(tmp_path, monkeypatch)
    vault.mkdir_folder("archive")
    readme = _hand_named_note(vault, "proj", "README.md", "Project readme")

    result = runner.invoke(app, argv)

    assert result.exit_code == 0, result.output
    expected = vault.notes_dir / new_folder / "README.md"
    assert expected.exists()
    meta = _index_meta(vault, readme.id)
    assert meta is not None
    assert vault.resolve_note_path_from_index(meta["path"]) == expected.resolve()
    # Same folder-hint persistence the web endpoint does, so Drive's flat
    # appData restore puts the note back in the same tree.
    assert vault.read_note(expected).folder == new_folder


def test_notes_mv_persists_folder_hint(tmp_path, monkeypatch):
    vault, _cfg = _ready_vault(tmp_path, monkeypatch)
    note = Note(id=new_id(), title="Mover", body="m")
    _write_and_index(vault, note)

    result = runner.invoke(app, ["notes", "mv", note.id, "projects/x"])

    assert result.exit_code == 0, result.output
    moved = vault.notes_dir / "projects" / "x" / note.filename
    assert moved.exists()
    assert vault.read_note(moved).folder == "projects/x"


# --------------------------------------------------------------- chat_repl.py:263


def _repl_runtime(vault: Vault, cfg: KnowletConfig) -> Any:
    idx = _open_index(vault)
    drafts = DraftStore(vault.drafts_dir)
    return SimpleNamespace(
        vault=vault,
        index=idx,
        config=cfg,
        ctx=SimpleNamespace(drafts=drafts, index=idx),
    )


def test_repl_drafts_approve_refuses_pending_diff(tmp_path, monkeypatch):
    from knowlet.cli.chat_repl import _handle_slash

    vault, cfg = _ready_vault(tmp_path, monkeypatch)
    draft = Draft(
        title="Pending",
        body="old body",
        pending_diff_base="old body",
        pending_diff_body="new body",
    )
    store = DraftStore(vault.drafts_dir)
    store.save(draft)
    runtime = _repl_runtime(vault, cfg)
    try:
        handled, quit_ = _handle_slash(f":drafts approve {draft.id}", runtime)
    finally:
        runtime.index.close()

    assert (handled, quit_) == (True, False)
    assert store.get(draft.id) is not None, "draft with an unresolved diff must survive"
    assert list(vault.iter_note_paths()) == []


def test_repl_drafts_approve_uses_commit_flow(tmp_path, monkeypatch):
    from knowlet.cli.chat_repl import _handle_slash

    vault, cfg = _ready_vault(tmp_path, monkeypatch)
    store = DraftStore(vault.drafts_dir)
    draft = Draft(title="Foldered", body="body text", folder="projects/x")
    store.save(draft)
    items = RawInfoStore(vault.digest_items_dir)
    item = RawInfo(
        source_id="s",
        source_name="S",
        source_kind="rss",
        item_key="rss:1",
        title="Item",
        url="https://example.com/1",
        summary="s",
        note_draft_id=draft.id,
    )
    items.save(item)
    runtime = _repl_runtime(vault, cfg)
    try:
        _handle_slash(f":drafts approve {draft.id}", runtime)
        note_rows = runtime.index.list_notes(limit=None)
    finally:
        runtime.index.close()

    paths = list(vault.iter_note_paths())
    assert len(paths) == 1
    assert vault.folder_of(paths[0]) == "projects/x"
    assert store.get(draft.id) is None
    assert len(note_rows) == 1
    loaded = items.get(item.id)
    assert loaded is not None and loaded.status == "included"


def test_repl_drafts_reject_archives_instead_of_unlinking(tmp_path, monkeypatch):
    from knowlet.cli.chat_repl import _handle_slash

    vault, cfg = _ready_vault(tmp_path, monkeypatch)
    store = DraftStore(vault.drafts_dir)
    draft = Draft(title="Reject me", body="keep my bytes")
    store.save(draft)
    runtime = _repl_runtime(vault, cfg)
    try:
        _handle_slash(f":drafts reject {draft.id}", runtime)
    finally:
        runtime.index.close()

    assert store.get(draft.id) is None
    archived = list(store.archive_dir.glob(f"{draft.id}*.md"))
    assert len(archived) == 1
    assert "keep my bytes" in archived[0].read_text(encoding="utf-8")


def test_repl_drafts_ambiguous_prefix_does_not_crash_repl(tmp_path, monkeypatch):
    from knowlet.cli.chat_repl import _handle_slash

    vault, cfg = _ready_vault(tmp_path, monkeypatch)
    store = DraftStore(vault.drafts_dir)
    store.save(Draft(id=_PREFIX + "A" * 18, title="One", body="1"))
    store.save(Draft(id=_PREFIX + "B" * 18, title="Two", body="2"))
    runtime = _repl_runtime(vault, cfg)
    try:
        handled, quit_ = _handle_slash(f":drafts reject {_PREFIX}", runtime)
    finally:
        runtime.index.close()

    assert (handled, quit_) == (True, False)
    assert len(store.all_drafts()) == 2


# --------------------------------------------------------------- config.py:148

_BRAVE = "brv-0123456789abcdefXY"
_TAVILY = "tvly-ZYXWVUTSRQPONMLKJI"
_LLM = "sk-llm-secret-value-QQ"


def _vault_with_secrets(tmp_path, monkeypatch) -> Vault:
    vault, cfg = _ready_vault(tmp_path, monkeypatch)
    cfg.llm.api_key = _LLM
    cfg.web_search.brave_api_key = _BRAVE
    cfg.web_search.tavily_api_key = _TAVILY
    save_config(vault.root, cfg)
    return vault


def test_config_show_masks_every_api_key_by_default(tmp_path, monkeypatch):
    _vault_with_secrets(tmp_path, monkeypatch)

    result = runner.invoke(app, ["config", "show"])

    assert result.exit_code == 0, result.output
    for secret in (_LLM, _BRAVE, _TAVILY):
        assert secret not in result.output
        # first 4 + last 2 stay visible so the user can tell keys apart
        assert secret[:4] in result.output
    assert "XY" in result.output


def test_config_show_reveals_secrets_only_on_request(tmp_path, monkeypatch):
    _vault_with_secrets(tmp_path, monkeypatch)

    result = runner.invoke(app, ["config", "show", "--show-secrets"])

    assert result.exit_code == 0, result.output
    for secret in (_LLM, _BRAVE, _TAVILY):
        assert secret in result.output


def test_config_set_echo_masks_web_search_keys(tmp_path, monkeypatch):
    vault, _cfg = _ready_vault(tmp_path, monkeypatch)

    result = runner.invoke(app, ["config", "set", "web_search.brave_api_key", _BRAVE])

    assert result.exit_code == 0, result.output
    assert _BRAVE not in result.output
    assert load_config(vault.root).web_search.brave_api_key == _BRAVE


def test_repl_config_show_masks_web_search_keys(tmp_path, monkeypatch, capsys):
    from knowlet.cli import chat_repl

    vault = _vault_with_secrets(tmp_path, monkeypatch)
    runtime = SimpleNamespace(config=load_config(vault.root))
    printed: list[str] = []
    monkeypatch.setattr(chat_repl.console, "print", lambda *a, **k: printed.append(str(a[0])))

    chat_repl._handle_slash(":config show", runtime)

    out = "\n".join(printed)
    for secret in (_LLM, _BRAVE, _TAVILY):
        assert secret not in out


def test_config_init_enter_keeps_existing_key(tmp_path, monkeypatch):
    """Accepting the masked default must not overwrite the real key with
    the masked string."""
    vault, cfg = _ready_vault(tmp_path, monkeypatch)
    cfg.llm.api_key = _LLM
    save_config(vault.root, cfg)

    # language, base_url, model, api_key, embedding backend, embedding model
    result = runner.invoke(app, ["config", "init"], input="\n" * 6)

    assert result.exit_code == 0, result.output
    assert load_config(vault.root).llm.api_key == _LLM


# --------------------------------------------------------------- digest.py:273


def _pending_raw_info_with_draft(vault: Vault) -> tuple[RawInfo, Draft]:
    drafts = DraftStore(vault.drafts_dir)
    draft = Draft(title="Linked", body="linked draft body")
    drafts.save(draft)
    item = RawInfo(
        source_id="s",
        source_name="S",
        source_kind="rss",
        item_key="rss:clear-1",
        title="Pending item",
        url="https://example.com/clear",
        summary="s",
        note_draft_id=draft.id,
    )
    RawInfoStore(vault.digest_items_dir).save(item)
    return item, draft


def test_digest_clear_requires_confirmation(tmp_path, monkeypatch):
    vault, _cfg = _ready_vault(tmp_path, monkeypatch)
    item, draft = _pending_raw_info_with_draft(vault)

    result = runner.invoke(app, ["digest", "clear"], input="n\n")

    loaded = RawInfoStore(vault.digest_items_dir).get(item.id)
    assert loaded is not None and loaded.status != "discarded", result.output
    assert DraftStore(vault.drafts_dir).get(draft.id) is not None


def test_digest_clear_yes_flag_skips_prompt(tmp_path, monkeypatch):
    vault, _cfg = _ready_vault(tmp_path, monkeypatch)
    item, _draft = _pending_raw_info_with_draft(vault)

    result = runner.invoke(app, ["digest", "clear", "--yes"])

    assert result.exit_code == 0, result.output
    loaded = RawInfoStore(vault.digest_items_dir).get(item.id)
    assert loaded is not None and loaded.status == "discarded"


def test_mining_reset_delete_drafts_requires_confirmation(tmp_path, monkeypatch):
    from knowlet.core.mining.task import MiningTask, Schedule, SourceSpec
    from knowlet.core.mining.task_store import TaskStore

    vault, _cfg = _ready_vault(tmp_path, monkeypatch)
    task = MiningTask(
        name="feed",
        sources=[SourceSpec(type="rss", url="https://example.com/feed.xml")],
        schedule=Schedule(every="1h"),
        prompt="p",
    )
    TaskStore(vault.tasks_dir).save(task)
    drafts = DraftStore(vault.drafts_dir)
    draft = Draft(title="Mined", body="mined body", task_id=task.id)
    drafts.save(draft)

    declined = runner.invoke(app, ["mining", "reset", task.id, "--delete-drafts"], input="n\n")
    assert drafts.get(draft.id) is not None, declined.output

    accepted = runner.invoke(app, ["mining", "reset", task.id, "--delete-drafts", "--yes"])
    assert accepted.exit_code == 0, accepted.output
    assert drafts.get(draft.id) is None


# --------------------------------------------------------------- cli/drafts.py reject


def test_drafts_reject_archives_instead_of_unlinking(tmp_path, monkeypatch):
    vault, _cfg = _ready_vault(tmp_path, monkeypatch)
    store = DraftStore(vault.drafts_dir)
    draft = Draft(title="Reject via CLI", body="recoverable bytes")
    store.save(draft)

    result = runner.invoke(app, ["drafts", "reject", draft.id])

    assert result.exit_code == 0, result.output
    assert store.get(draft.id) is None
    archived = list(store.archive_dir.glob(f"{draft.id}*.md"))
    assert len(archived) == 1
    assert "recoverable bytes" in archived[0].read_text(encoding="utf-8")


def test_drafts_reject_ambiguous_prefix_reports_candidates(tmp_path, monkeypatch):
    vault, _cfg = _ready_vault(tmp_path, monkeypatch)
    store = DraftStore(vault.drafts_dir)
    one = Draft(id=_PREFIX + "A" * 18, title="One", body="1")
    two = Draft(id=_PREFIX + "B" * 18, title="Two", body="2")
    store.save(one)
    store.save(two)

    result = runner.invoke(app, ["drafts", "reject", _PREFIX])

    assert result.exit_code == 2, (result.output, result.exception)
    assert isinstance(result.exception, SystemExit), repr(result.exception)
    assert "ambiguous" in result.output
    assert one.id in result.output and two.id in result.output
    assert len(store.all_drafts()) == 2


def test_drafts_show_ambiguous_prefix_is_a_clean_error(tmp_path, monkeypatch):
    vault, _cfg = _ready_vault(tmp_path, monkeypatch)
    store = DraftStore(vault.drafts_dir)
    store.save(Draft(id=_PREFIX + "A" * 18, title="One", body="1"))
    store.save(Draft(id=_PREFIX + "B" * 18, title="Two", body="2"))

    result = runner.invoke(app, ["drafts", "show", _PREFIX])

    assert result.exit_code == 2, (result.output, result.exception)
    assert isinstance(result.exception, SystemExit), repr(result.exception)
    assert "ambiguous" in result.output


# --------------------------------------------------------------- vault.py:138


def _wal_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA wal_autocheckpoint = 0")
    conn.execute("CREATE TABLE IF NOT EXISTS t (v TEXT)")
    conn.commit()
    return conn


def _rows(path: Path) -> list[str]:
    conn = sqlite3.connect(path)
    try:
        return [r[0] for r in conn.execute("SELECT v FROM t ORDER BY rowid")]
    finally:
        conn.close()


def test_snapshot_copies_live_wal_database_consistently(tmp_path, monkeypatch):
    vault, _cfg = _ready_vault(tmp_path, monkeypatch)
    db = vault.state_dir / "sync_state.sqlite"
    live = _wal_db(db)
    try:
        live.execute("INSERT INTO t VALUES ('in-wal-only')")
        live.commit()
        assert Path(f"{db}-wal").exists()

        result = runner.invoke(app, ["vault", "snapshot", "--label", "live"])
    finally:
        live.close()

    assert result.exit_code == 0, result.output
    snap = next((vault.state_dir / "snapshots").iterdir())
    snap_db = snap / ".knowlet" / "sync_state.sqlite"
    assert not Path(f"{snap_db}-wal").exists()
    assert not Path(f"{snap_db}-shm").exists()
    assert _rows(snap_db) == ["in-wal-only"]


def test_restore_snapshot_drops_stale_wal_sidecars(tmp_path, monkeypatch):
    vault, _cfg = _ready_vault(tmp_path, monkeypatch)
    db = vault.state_dir / "sync_state.sqlite"
    conn = _wal_db(db)
    conn.execute("INSERT INTO t VALUES ('A')")
    conn.commit()
    conn.close()

    assert runner.invoke(app, ["vault", "snapshot", "--label", "s1"]).exit_code == 0

    # Live state moves on: row B sits in a WAL sidecar next to the DB.
    conn = _wal_db(db)
    conn.execute("INSERT INTO t VALUES ('B')")
    conn.commit()
    saved = {s: Path(f"{db}{s}").read_bytes() for s in ("-wal", "-shm")}
    conn.close()
    for s, data in saved.items():
        Path(f"{db}{s}").write_bytes(data)
    stale_index_wal = Path(f"{vault.db_path}-wal")
    stale_index_wal.write_bytes(b"stale")

    snap_name = next(p.name for p in (vault.state_dir / "snapshots").iterdir() if "s1" in p.name)
    result = runner.invoke(app, ["vault", "restore-snapshot", snap_name, "--yes"])

    assert result.exit_code == 0, result.output
    assert _rows(db) == ["A"], "restored DB must not replay the live WAL"
    assert not stale_index_wal.exists()


# --------------------------------------------------------------- graph.py:85 / :61


def test_graph_export_stdout_is_valid_json_for_pipes(tmp_path, monkeypatch):
    vault, _cfg = _ready_vault(tmp_path, monkeypatch)
    long_title = "A very long title that will definitely exceed eighty columns " * 2
    target = Note(id=new_id(), title=long_title.strip(), body="t")
    source = Note(
        id=new_id(),
        title="Review [/review] and [[wikilink]] in title",
        body=f"see [[{target.title}]]",
    )
    _write_and_index(vault, target)
    _write_and_index(vault, source)

    for flag in ("--compact", "--pretty"):
        result = runner.invoke(app, ["graph", "export", flag])
        assert result.exit_code == 0, (result.output, result.exception)
        payload = json.loads(result.stdout)
        titles = {n["title"] for n in payload["nodes"]}
        assert source.title in titles
        assert target.title.strip() in titles
        assert {"source": source.id, "target": target.id} in payload["edges"]


def test_graph_export_resolves_relative_index_paths_with_subfolders(tmp_path, monkeypatch):
    vault, _cfg = _ready_vault(tmp_path, monkeypatch)
    target = Note(id=new_id(), title="Target", body="t")
    source = Note(id=new_id(), title="Source", body="links [[Target]]")
    _write_and_index(vault, target)
    _write_and_index(vault, source, folder="archive")
    # Root-level decoy with the same filename but different links.
    decoy = vault.notes_dir / source.filename
    shutil.copy2(vault.notes_dir / "archive" / source.filename, decoy)
    decoy.write_text(
        Note(id=source.id, title="Source", body="no links here").to_markdown(), encoding="utf-8"
    )
    idx = _open_index(vault)
    try:
        idx.update_note_path(source.id, f"archive/{source.filename}")
    finally:
        idx.close()

    result = runner.invoke(app, ["graph", "export", "--compact"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert {"source": source.id, "target": target.id} in payload["edges"]
    folders = {n["id"]: n["folder"] for n in payload["nodes"]}
    assert folders[source.id] == "archive"


# --------------------------------------------------------------- mining.py / digest.py ambiguous ids


def _twin_tasks(vault: Vault) -> list[Any]:
    from knowlet.core.mining.task import MiningTask, Schedule, SourceSpec
    from knowlet.core.mining.task_store import TaskStore

    store = TaskStore(vault.tasks_dir)
    tasks = []
    for suffix, name in (("A", "first feed"), ("B", "second feed")):
        task = MiningTask(
            id=_PREFIX + suffix * 18,
            name=name,
            sources=[SourceSpec(type="rss", url=f"https://example.com/{suffix}.xml")],
            schedule=Schedule(every="1h"),
            prompt="p",
        )
        store.save(task)
        tasks.append(task)
    return tasks


@pytest.mark.parametrize(
    "argv",
    [
        ["mining", "remove", _PREFIX],
        ["mining", "reset", _PREFIX, "--delete-drafts", "--yes"],
        ["mining", "run", _PREFIX],
        ["mining", "edit", _PREFIX],
    ],
)
def test_mining_ambiguous_task_prefix_lists_candidates(tmp_path, monkeypatch, argv):
    from knowlet.core.mining.task_store import TaskStore

    vault, _cfg = _ready_vault(tmp_path, monkeypatch)
    tasks = _twin_tasks(vault)

    result = runner.invoke(app, argv)

    assert result.exit_code == 2, (result.output, result.exception)
    assert isinstance(result.exception, SystemExit), repr(result.exception)
    lines = result.output.splitlines()
    for task in tasks:
        assert any(line.strip() == f"· {task.id}" for line in lines), result.output
    assert len(TaskStore(vault.tasks_dir).list()) == 2


@pytest.mark.parametrize(
    "argv",
    [
        ["digest", "disable", _PREFIX],
        ["digest", "enable", _PREFIX],
        ["digest", "remove", _PREFIX],
        ["digest", "run", _PREFIX],
    ],
)
def test_digest_ambiguous_source_prefix_lists_candidates(tmp_path, monkeypatch, argv):
    from knowlet.core.digest_sources import DigestSource, DigestSourceStore

    vault, _cfg = _ready_vault(tmp_path, monkeypatch)
    store = DigestSourceStore(vault.digest_sources_dir)
    sources = []
    for suffix in ("A", "B"):
        source = DigestSource(
            id=_PREFIX + suffix * 18,
            name=f"feed {suffix}",
            kind="rss",
            url=f"https://example.com/{suffix}.xml",
        )
        store.save(source)
        sources.append(source)

    result = runner.invoke(app, argv)

    assert result.exit_code == 2, (result.output, result.exception)
    assert isinstance(result.exception, SystemExit), repr(result.exception)
    lines = result.output.splitlines()
    for source in sources:
        assert any(line.strip() == f"· {source.id}" for line in lines), result.output
    remaining = store.list()
    assert len(remaining) == 2
    assert all(s.enabled for s in remaining)


def test_digest_discard_reports_archived_draft(tmp_path, monkeypatch):
    vault, _cfg = _ready_vault(tmp_path, monkeypatch)
    item, draft = _pending_raw_info_with_draft(vault)

    result = runner.invoke(app, ["digest", "discard", item.id])

    assert result.exit_code == 0, result.output
    assert "archived draft" in result.output
    assert "deleted draft" not in result.output
    assert list(DraftStore(vault.drafts_dir).archive_dir.glob(f"{draft.id}*.md"))


def test_digest_clear_reports_archived_drafts(tmp_path, monkeypatch):
    vault, _cfg = _ready_vault(tmp_path, monkeypatch)
    _item, draft = _pending_raw_info_with_draft(vault)

    result = runner.invoke(app, ["digest", "clear", "--yes"])

    assert result.exit_code == 0, result.output
    assert "archived linked drafts" in result.output
    assert "deleted linked drafts" not in result.output
    assert list(DraftStore(vault.drafts_dir).archive_dir.glob(f"{draft.id}*.md"))


def test_snapshot_still_copies_a_damaged_database(tmp_path, monkeypatch):
    vault, _cfg = _ready_vault(tmp_path, monkeypatch)
    broken = vault.state_dir / "sync_state.sqlite"
    payload = b"SQLite format 3\x00" + b"\xff" * 4096
    broken.write_bytes(payload)

    result = runner.invoke(app, ["vault", "snapshot", "--label", "broken"])

    assert result.exit_code == 0, (result.output, result.exception)
    snap = next((vault.state_dir / "snapshots").iterdir())
    assert "online backup failed" in result.output
    assert (snap / ".knowlet" / "sync_state.sqlite").read_bytes() == payload
    assert not list((snap / ".knowlet").glob("*.partial*"))
