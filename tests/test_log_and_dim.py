import json
import os
import time
from pathlib import Path

import pytest

from knowlet.chat.log import ConversationLog, prune_old
from knowlet.core.embedding import DummyBackend
from knowlet.core.index import Index, IndexDimensionMismatchError
from knowlet.core.note import Note, new_id
from knowlet.core.tools._registry import ToolContext, default_registry
from knowlet.core.vault import Vault


def test_conversation_log_write_skips_empty(tmp_path: Path):
    log = ConversationLog(dir=tmp_path / "convos", model="m")
    assert log.write([]) is None
    assert log.write([{"role": "system", "content": "x"}]) is None
    assert not (tmp_path / "convos").exists()


def test_conversation_log_writes_history(tmp_path: Path):
    log = ConversationLog(dir=tmp_path / "convos", model="m")
    history = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    path = log.write(history)
    assert path is not None and path.exists()
    payload = json.loads(path.read_text("utf-8"))
    assert payload["model"] == "m"
    assert payload["messages"] == history
    # 0600 permissions
    mode = path.stat().st_mode & 0o777
    assert mode == 0o600


def test_prune_old_deletes_only_aged(tmp_path: Path):
    d = tmp_path / "convos"
    d.mkdir()
    fresh = d / "fresh.json"
    fresh.write_text("{}", encoding="utf-8")
    aged = d / "aged.json"
    aged.write_text("{}", encoding="utf-8")
    long_ago = time.time() - 60 * 86400
    os.utime(aged, (long_ago, long_ago))
    assert prune_old(d, days=30) == 1
    assert fresh.exists()
    assert not aged.exists()


def test_dim_mismatch_raises(tmp_path: Path):
    vault = Vault(tmp_path)
    vault.init_layout()
    backend_a = DummyBackend(dim=128)
    idx = Index(vault.db_path, backend_a)
    idx.connect()
    idx.close()

    backend_b = DummyBackend(dim=256)
    idx2 = Index(vault.db_path, backend_b)
    with pytest.raises(IndexDimensionMismatchError):
        idx2.connect()


def test_list_recent_notes_tool(tmp_path: Path):
    from knowlet.config import KnowletConfig

    vault = Vault(tmp_path)
    vault.init_layout()
    backend = DummyBackend(dim=64)
    idx = Index(vault.db_path, backend)
    idx.connect()

    n1 = Note(id=new_id(), title="First note", body="body one")
    n2 = Note(id=new_id(), title="Second note", body="body two")
    vault.write_note(n1)
    vault.write_note(n2)
    idx.upsert_note(n1, chunk_size=200, chunk_overlap=40)
    idx.upsert_note(n2, chunk_size=200, chunk_overlap=40)

    cfg = KnowletConfig()
    from knowlet.core.cards import CardStore
    ctx = ToolContext(vault=vault, index=idx, config=cfg, cards=CardStore(vault.cards_dir))
    reg = default_registry()
    res = reg.dispatch("list_recent_notes", {"limit": 5}, ctx)
    assert res["count"] == 2
    titles = {r["title"] for r in res["results"]}
    assert titles == {"First note", "Second note"}
    idx.close()
