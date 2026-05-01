"""run_task — orchestrates a single mining-task execution.

Steps:
  1. Fetch all source items (RSS + URLs).
  2. Drop items already seen by this task (per-task seen-set in `<vault>/.knowlet/mining/<task_id>.json`).
  3. For each new item, call `extractor.extract_one` to produce a Draft.
  4. Save successful drafts under `<vault>/drafts/`.
  5. Persist the seen-set so the next run skips them.
  6. Return a `RunReport` for telemetry / UI display.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

from knowlet.core.drafts import DraftStore
from knowlet.core.llm import LLMClient
from knowlet.core.mining.extractor import ExtractionResult, extract_one
from knowlet.core.mining.sources import SourceItem, fetch_source
from knowlet.core.mining.task import MiningTask
from knowlet.core.vault import Vault


@dataclass
class RunReport:
    task_id: str
    started_at: str
    finished_at: str
    fetched: int = 0
    new_items: int = 0
    drafts_created: int = 0
    skipped_empty: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "fetched": self.fetched,
            "new_items": self.new_items,
            "drafts_created": self.drafts_created,
            "skipped_empty": self.skipped_empty,
            "errors": list(self.errors),
        }


# ----------------------------------------------------- seen-set persistence


def _seen_set_path(vault: Vault, task_id: str) -> Path:
    return vault.state_dir / "mining" / f"{task_id}.json"


def _load_seen(vault: Vault, task_id: str) -> set[str]:
    p = _seen_set_path(vault, task_id)
    if not p.exists():
        return set()
    try:
        data = json.loads(p.read_text("utf-8"))
        return set(data.get("seen", []))
    except (OSError, json.JSONDecodeError):
        return set()


def _save_seen(vault: Vault, task_id: str, seen: Iterable[str]) -> None:
    p = _seen_set_path(vault, task_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {"seen": sorted(set(seen))}
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


# ----------------------------------------------------- runner


def run_task(
    task: MiningTask,
    vault: Vault,
    llm: LLMClient,
    drafts: DraftStore | None = None,
) -> RunReport:
    """Execute one mining task. Pure-function-ish — all side effects go
    through `vault` (drafts dir + .knowlet/mining/seen state)."""
    if drafts is None:
        drafts = DraftStore(vault.root / "drafts")

    started = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    report = RunReport(task_id=task.id, started_at=started, finished_at=started)

    if not task.enabled:
        report.errors.append("task is disabled")
        report.finished_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        return report

    items: list[SourceItem] = []
    for spec in task.sources:
        try:
            fetched = fetch_source(spec)
        except Exception as exc:  # noqa: BLE001 — boundary
            report.errors.append(f"fetch {spec.type}:{spec.url}: {type(exc).__name__}: {exc}")
            continue
        items.extend(fetched)
    report.fetched = len(items)

    seen = _load_seen(vault, task.id)
    new_items = [it for it in items if it.item_id not in seen]
    report.new_items = len(new_items)

    new_seen_ids: list[str] = []
    for item in new_items:
        result = extract_one(task, item, llm)
        if result.error:
            if result.error == "empty source content" or "LLM declined" in result.error:
                report.skipped_empty += 1
            else:
                report.errors.append(f"item {item.item_id!r}: {result.error}")
            new_seen_ids.append(item.item_id)  # mark even failed ones to avoid loops
            continue
        if result.draft is not None:
            drafts.save(result.draft)
            report.drafts_created += 1
            new_seen_ids.append(item.item_id)

    if new_seen_ids:
        _save_seen(vault, task.id, list(seen) + new_seen_ids)

    report.finished_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return report
