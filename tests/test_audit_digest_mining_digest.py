"""Regression tests for the digest pull / RawInfo / review layer (2026-11 audit)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from knowlet.config import KnowletConfig, save_config
from knowlet.core import digest_items as digest_items_mod
from knowlet.core import digest_pull as digest_pull_mod
from knowlet.core.digest_items import RawInfo, RawInfoStore
from knowlet.core.digest_pull import pull_digest_sources
from knowlet.core.digest_review import (
    DigestReviewError,
    discard_pending_raw_infos,
    discard_raw_info,
)
from knowlet.core.digest_sources import DigestSource, DigestSourceStore
from knowlet.core.drafts import DraftStore
from knowlet.core.llm import AssistantMessage, ResponsesMessage
from knowlet.core.mining.sources import SourceItem
from knowlet.core.vault import Vault


def _ready_vault(tmp_path: Path) -> Vault:
    vault = Vault(tmp_path)
    vault.init_layout()
    cfg = KnowletConfig()
    cfg.embedding.backend = "dummy"
    cfg.embedding.dim = 32
    cfg.llm.api_key = "stub"
    save_config(vault.root, cfg)
    return vault


def _rss_source(vault: Vault, name: str = "Feed") -> DigestSource:
    source = DigestSource(name=name, kind="rss", url="https://feeds.example/rss.xml")
    DigestSourceStore(vault.digest_sources_dir).save(source)
    return source


def _feed(n: int) -> list[SourceItem]:
    return [
        SourceItem(
            source_url="https://feeds.example/rss.xml",
            item_id=f"entry-{i}",
            title=f"Entry {i}",
            url=f"https://feeds.example/{i}",
            published=None,
            content=f"body {i}",
        )
        for i in range(n)
    ]


def _normalized(title: str) -> str:
    return json.dumps(
        {
            "title": title,
            "summary": f"summary of {title}",
            "key_points": [],
            "why_it_matters": "",
            "suggested_tags": [],
            "confidence": "medium",
        }
    )


class _ChatLLM:
    """``chat`` returns the scripted raw strings in order, then valid JSON."""

    def __init__(self, replies: list[str] | None = None):
        self.replies = list(replies or [])
        self.calls = 0

    def chat(self, messages, tools=None, max_tokens=None, temperature=None):
        self.calls += 1
        content = self.replies.pop(0) if self.replies else _normalized(f"item {self.calls}")
        return AssistantMessage(content=content, tool_calls=[])


def _source_on_disk(vault: Vault, source_id: str) -> DigestSource:
    source = DigestSourceStore(vault.digest_sources_dir).get(source_id)
    assert source is not None
    return source


# ------------------------------------------------------- per-item failures


def test_one_unparseable_normalizer_reply_does_not_abort_the_source(tmp_path, monkeypatch):
    vault = _ready_vault(tmp_path)
    source = _rss_source(vault)
    monkeypatch.setattr(digest_pull_mod, "fetch_source", lambda spec: _feed(3))
    llm = _ChatLLM(
        [_normalized("first"), "Sure! Here is the JSON you asked for.", _normalized("third")]
    )

    report = pull_digest_sources(vault=vault, llm=llm, source_ids=[source.id])  # type: ignore[arg-type]
    assert report.created == 2
    assert any("Entry 1" in e for e in report.errors)
    assert _source_on_disk(vault, source.id).pull_status == "ok"

    again = _ChatLLM()
    second = pull_digest_sources(vault=vault, llm=again, source_ids=[source.id])  # type: ignore[arg-type]
    assert again.calls == 0
    assert second.new_items == 0


def test_skipped_rss_item_is_marked_seen(tmp_path, monkeypatch):
    vault = _ready_vault(tmp_path)
    source = _rss_source(vault)
    monkeypatch.setattr(digest_pull_mod, "fetch_source", lambda spec: _feed(1))
    thin = json.dumps({"title": "", "summary": ""})
    first = pull_digest_sources(vault=vault, llm=_ChatLLM([thin]), source_ids=[source.id])  # type: ignore[arg-type]
    assert first.skipped == 1

    again = _ChatLLM()
    pull_digest_sources(vault=vault, llm=again, source_ids=[source.id])  # type: ignore[arg-type]
    assert again.calls == 0


def test_provider_failure_keeps_seen_marks_of_finished_items(tmp_path, monkeypatch):
    vault = _ready_vault(tmp_path)
    source = _rss_source(vault)
    monkeypatch.setattr(digest_pull_mod, "fetch_source", lambda spec: _feed(3))
    thin = json.dumps({"title": "", "summary": ""})

    class DownAfterTwo(_ChatLLM):
        def chat(self, messages, tools=None, max_tokens=None, temperature=None):
            if self.calls >= 2:
                self.calls += 1
                raise ConnectionError("provider down")
            return super().chat(messages, tools, max_tokens, temperature)

    report = pull_digest_sources(
        vault=vault,
        llm=DownAfterTwo([_normalized("first"), thin]),  # type: ignore[arg-type]
        source_ids=[source.id],
    )
    assert _source_on_disk(vault, source.id).pull_status == "error"
    assert report.created == 1

    again = _ChatLLM()
    pull_digest_sources(vault=vault, llm=again, source_ids=[source.id])  # type: ignore[arg-type]
    assert again.calls == 1  # only the item the outage interrupted


# ------------------------------------------------------- prompt source


def test_prompt_source_without_web_search_fails_instead_of_inventing_items(tmp_path):
    vault = _ready_vault(tmp_path)
    source = DigestSource(name="Daily AI news", kind="prompt", prompt="latest AI news")
    DigestSourceStore(vault.digest_sources_dir).save(source)
    hallucinated = json.dumps(
        {"items": [{"title": "Made up", "url": "https://nowhere.example/x", "summary": "s"}]}
    )

    class NoSearchLLM:
        def __init__(self) -> None:
            self.tool_args: list[Any] = []

        def responses(
            self, input_text, *, tools=None, max_output_tokens=None, role=None, temperature=None
        ):
            self.tool_args.append(tools)
            if tools:
                raise RuntimeError("tool type web_search is not supported")
            return ResponsesMessage(content=hallucinated, raw={"output": [{"type": "message"}]})

    llm = NoSearchLLM()
    report = pull_digest_sources(vault=vault, llm=llm, source_ids=[source.id])  # type: ignore[arg-type]
    assert None not in llm.tool_args
    assert RawInfoStore(vault.digest_items_dir).list() == []
    on_disk = _source_on_disk(vault, source.id)
    assert on_disk.pull_status == "error"
    assert "web search" in (on_disk.last_error or "").lower()
    assert report.errors


# ------------------------------------------------------- source file writes


def test_pull_keeps_source_edits_made_while_it_was_running(tmp_path, monkeypatch):
    vault = _ready_vault(tmp_path)
    source = _rss_source(vault, name="Old name")
    store = DigestSourceStore(vault.digest_sources_dir)

    def fetch_while_user_edits(spec):
        edited = store.get(source.id)
        edited.name = "Renamed by user"
        edited.enabled = False
        store.save(edited)
        return _feed(1)

    monkeypatch.setattr(digest_pull_mod, "fetch_source", fetch_while_user_edits)
    pull_digest_sources(vault=vault, llm=_ChatLLM(), source_ids=[source.id])  # type: ignore[arg-type]

    on_disk = _source_on_disk(vault, source.id)
    assert on_disk.name == "Renamed by user"
    assert on_disk.enabled is False
    assert on_disk.pull_status == "ok"
    assert on_disk.last_success_at
    assert len(list(store.iter_paths())) == 1


def test_pull_does_not_resurrect_a_source_deleted_while_running(tmp_path, monkeypatch):
    vault = _ready_vault(tmp_path)
    source = _rss_source(vault)
    store = DigestSourceStore(vault.digest_sources_dir)

    def fetch_then_delete(spec):
        store.delete(source.id)
        return _feed(1)

    monkeypatch.setattr(digest_pull_mod, "fetch_source", fetch_then_delete)
    pull_digest_sources(vault=vault, llm=_ChatLLM(), source_ids=[source.id])  # type: ignore[arg-type]
    assert list(store.iter_paths()) == []


# ------------------------------------------------------- cross-process mutex


def test_pull_is_refused_while_another_process_holds_the_pull_lock(tmp_path, monkeypatch):
    vault = _ready_vault(tmp_path)
    source = _rss_source(vault)
    monkeypatch.setattr(digest_pull_mod, "fetch_source", lambda spec: _feed(2))
    lock_path = digest_pull_mod.pull_lock_path(vault)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    holder = subprocess.Popen(
        [
            sys.executable,
            "-I",
            "-c",
            "import fcntl, sys\n"
            "f = open(sys.argv[1], 'a')\n"
            "fcntl.flock(f, fcntl.LOCK_EX)\n"
            "print('locked', flush=True)\n"
            "sys.stdin.read()\n",
            str(lock_path),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout is not None and holder.stdout.readline().strip() == "locked"
        llm = _ChatLLM()
        report = pull_digest_sources(vault=vault, llm=llm, source_ids=[source.id])  # type: ignore[arg-type]
        assert llm.calls == 0
        assert report.created == 0
        assert any("already running" in e for e in report.errors)
        assert _source_on_disk(vault, source.id).pull_status == "idle"
    finally:
        assert holder.stdin is not None
        holder.stdin.close()
        holder.wait(timeout=10)

    llm = _ChatLLM()
    report = pull_digest_sources(vault=vault, llm=llm, source_ids=[source.id])  # type: ignore[arg-type]
    assert report.created == 2


# ------------------------------------------------------- RawInfo store scaling


def _seed_raw_infos(store: RawInfoStore, n: int, *, status: str = "discarded") -> list[RawInfo]:
    out = []
    for i in range(n):
        info = RawInfo(
            source_id="src",
            source_name="src",
            source_kind="rss",
            item_key=f"rss:src:{i}",
            title=f"old {i}",
            url=f"https://old.example/{i}",
            summary="s",
            status=status,  # type: ignore[arg-type]
        )
        store.save(info)
        out.append(info)
    return out


def test_pull_parses_the_raw_info_store_a_bounded_number_of_times(tmp_path, monkeypatch):
    vault = _ready_vault(tmp_path)
    source = _rss_source(vault)
    history = 40
    _seed_raw_infos(RawInfoStore(vault.digest_items_dir), history)
    monkeypatch.setattr(digest_pull_mod, "fetch_source", lambda spec: _feed(10))
    parses = 0
    real_from_file = RawInfo.from_file.__func__  # type: ignore[attr-defined]

    def counting_from_file(cls, path):
        nonlocal parses
        parses += 1
        return real_from_file(cls, path)

    monkeypatch.setattr(digest_items_mod.RawInfo, "from_file", classmethod(counting_from_file))
    report = pull_digest_sources(vault=vault, llm=_ChatLLM(), source_ids=[source.id])  # type: ignore[arg-type]
    assert report.created == 10
    assert parses <= 2 * (history + 10)


def test_bulk_discard_scans_the_store_once(tmp_path, monkeypatch):
    vault = _ready_vault(tmp_path)
    items = RawInfoStore(vault.digest_items_dir)
    _seed_raw_infos(items, 20, status="unprocessed")
    scans = 0
    real_iter = RawInfoStore.iter_paths

    def counting_iter(self):
        nonlocal scans
        scans += 1
        return real_iter(self)

    monkeypatch.setattr(RawInfoStore, "iter_paths", counting_iter)
    result = discard_pending_raw_infos(items=items, drafts=DraftStore(vault.drafts_dir))
    assert result.discarded_count == 20
    assert scans <= 2
    monkeypatch.undo()
    assert items.pending_count() == 0
    assert len(list(items.iter_paths())) == 20


# ------------------------------------------------------- id prefix lookup


def test_raw_info_get_rejects_ambiguous_prefix_and_discard_touches_nothing(tmp_path):
    vault = _ready_vault(tmp_path)
    items = RawInfoStore(vault.digest_items_dir)
    a = RawInfo(
        source_id="s",
        source_name="s",
        source_kind="rss",
        item_key="k1",
        title="A",
        url="https://a",
        summary="s",
        id="01AAA",
    )
    b = RawInfo(
        source_id="s",
        source_name="s",
        source_kind="rss",
        item_key="k2",
        title="B",
        url="https://b",
        summary="s",
        id="01AAB",
    )
    c = RawInfo(
        source_id="s",
        source_name="s",
        source_kind="rss",
        item_key="k3",
        title="C",
        url="https://c",
        summary="s",
        id="01AAAZ",
    )
    for info in (a, b, c):
        items.save(info)

    with pytest.raises(LookupError):
        items.get("01A")
    assert items.get("01AAA").title == "A"
    assert items.get("") is None

    with pytest.raises(DigestReviewError, match="ambiguous"):
        discard_raw_info(items=items, drafts=DraftStore(vault.drafts_dir), info_id="01AA")
    assert items.pending_count() == 3


def test_digest_source_get_and_delete_reject_ambiguous_prefix(tmp_path):
    vault = _ready_vault(tmp_path)
    store = DigestSourceStore(vault.digest_sources_dir)
    for source_id in ("01SRCA", "01SRCB"):
        store.save(
            DigestSource(id=source_id, name=source_id, kind="rss", url="https://f.example/x")
        )
    with pytest.raises(LookupError):
        store.get("01SRC")
    with pytest.raises(LookupError):
        store.delete("01")
    assert store.delete("") is False
    assert len(list(store.iter_paths())) == 2
    assert store.get("01SRCA").name == "01SRCA"


# ------------------------------------------------------- discard is recoverable


def _raw_info_with_draft(
    vault: Vault, items: RawInfoStore, drafts: DraftStore, n: int
) -> list[tuple[RawInfo, Path]]:
    from knowlet.core.drafts import Draft

    out = []
    for i in range(n):
        draft = Draft(title=f"draft {i}", body=f"user-edited body {i}")
        drafts.save(draft)
        info = RawInfo(
            source_id="s",
            source_name="s",
            source_kind="rss",
            item_key=f"k{i}",
            title=f"info {i}",
            url=f"https://i.example/{i}",
            summary="s",
            status="drafted",
            note_draft_id=draft.id,
        )
        items.save(info)
        assert draft.path is not None
        out.append((info, draft.path))
    return out


def _archived_bodies(drafts: DraftStore) -> list[str]:
    return sorted(p.read_text("utf-8") for p in drafts.archive_dir.rglob("*.md"))


def test_discard_raw_info_archives_the_linked_draft_instead_of_deleting(tmp_path):
    vault = _ready_vault(tmp_path)
    items = RawInfoStore(vault.digest_items_dir)
    drafts = DraftStore(vault.drafts_dir)
    [(info, draft_path)] = _raw_info_with_draft(vault, items, drafts, 1)

    result = discard_raw_info(items=items, drafts=drafts, info_id=info.id)
    assert result.draft_deleted is True
    assert result.item.status == "discarded"
    assert not draft_path.exists()
    assert drafts.all_drafts() == []
    archived = _archived_bodies(drafts)
    assert len(archived) == 1 and "user-edited body 0" in archived[0]


def test_bulk_discard_archives_every_linked_draft(tmp_path):
    vault = _ready_vault(tmp_path)
    items = RawInfoStore(vault.digest_items_dir)
    drafts = DraftStore(vault.drafts_dir)
    pairs = _raw_info_with_draft(vault, items, drafts, 3)

    result = discard_pending_raw_infos(items=items, drafts=drafts)
    assert result.discarded_count == 3
    assert len(result.deleted_draft_ids) == 3
    assert all(not path.exists() for _, path in pairs)
    assert len(_archived_bodies(drafts)) == 3
