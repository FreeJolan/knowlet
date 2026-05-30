"""Pull Stage C v2 digest sources into RawInfo items."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from knowlet.core.digest_items import RawInfo, RawInfoStore
from knowlet.core.digest_sources import DigestSource, DigestSourceStore
from knowlet.core.llm import LLMClient, response_has_output_type
from knowlet.core.mining.sources import SourceItem, fetch_source
from knowlet.core.mining.task import SourceSpec
from knowlet.core.note import now_iso
from knowlet.core.vault import Vault

PENDING_LIMIT = 200
MAX_CONTENT_CHARS = 6000
AUTO_PULL_STATE_FILE = "auto_pull.json"


@dataclass
class DigestPullReport:
    started_at: str
    finished_at: str
    source_ids: list[str] = field(default_factory=list)
    fetched: int = 0
    new_items: int = 0
    created: int = 0
    skipped: int = 0
    paused: bool = False
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "source_ids": list(self.source_ids),
            "fetched": self.fetched,
            "new_items": self.new_items,
            "created": self.created,
            "skipped": self.skipped,
            "paused": self.paused,
            "errors": list(self.errors),
        }


def pull_digest_sources(
    *,
    vault: Vault,
    llm: LLMClient,
    source_ids: list[str] | None = None,
    max_pending: int = PENDING_LIMIT,
    max_items: int | None = None,
) -> DigestPullReport:
    """Pull enabled RSS / Prompt sources and save new RawInfo items.

    This runner is intentionally separate from the older mining runner:
    Stage C v2 produces read-only RawInfo, not Drafts.
    """
    started = now_iso()
    report = DigestPullReport(started_at=started, finished_at=started)
    sources = _select_sources(DigestSourceStore(vault.digest_sources_dir), source_ids)
    report.source_ids = [source.id for source in sources]
    store = RawInfoStore(vault.digest_items_dir)
    source_store = DigestSourceStore(vault.digest_sources_dir)

    pending = store.pending_count()
    if pending >= max_pending:
        report.paused = True
        msg = (
            f"pending raw info reached {pending} (limit {max_pending}); "
            "process or discard items before pulling again"
        )
        for source in sources:
            _mark_source(source, source_store, status="paused", error=msg)
        report.errors.append(msg)
        report.finished_at = now_iso()
        return report

    for source in sources:
        if not source.enabled:
            continue
        try:
            _pull_one_source(
                source,
                vault,
                llm,
                store,
                report,
                max_items=max_items,
            )
        except Exception as exc:
            report.errors.append(f"{source.name}: {type(exc).__name__}: {exc}")
            _mark_source(
                source,
                source_store,
                status="error",
                error=f"{type(exc).__name__}: {exc}",
            )
            continue
        _mark_source(source, source_store, status="ok", error=None)

    report.finished_at = now_iso()
    return report


def maybe_auto_pull_digest_sources(
    *,
    vault: Vault,
    llm: LLMClient,
    today: str | None = None,
    max_pending: int = PENDING_LIMIT,
) -> DigestPullReport | None:
    """Run the daily digest pull once per local date.

    The web app calls this when it comes online and can call it again while
    staying open across midnight. The seen-set still dedupes fetched entries;
    this guard only prevents repeated LLM/fetch work during the same day.
    """
    source_store = DigestSourceStore(vault.digest_sources_dir)
    enabled_sources = [source for source in source_store.list() if source.enabled]
    if not enabled_sources:
        return None
    day = today or datetime.now().date().isoformat()
    state_path = _auto_pull_state_path(vault)
    state = _read_auto_pull_state(state_path)
    raw_last_by_source = state.get("last_by_source")
    last_by_source = (
        {str(source_id): str(last_day) for source_id, last_day in raw_last_by_source.items()}
        if isinstance(raw_last_by_source, dict)
        else {}
    )
    due_sources = [
        source
        for source in enabled_sources
        if last_by_source.get(source.id) != day and not _source_succeeded_on_day(source, day)
    ]
    if not due_sources:
        return None
    report = pull_digest_sources(
        vault=vault,
        llm=llm,
        source_ids=[source.id for source in due_sources],
        max_pending=max_pending,
    )
    if not report.paused:
        refreshed_store = DigestSourceStore(vault.digest_sources_dir)
        for source in due_sources:
            refreshed = refreshed_store.get(source.id)
            if refreshed is not None and refreshed.pull_status == "ok":
                last_by_source[source.id] = day
        _write_auto_pull_state(state_path, last_by_source=last_by_source)
    return report


def _select_sources(store: DigestSourceStore, source_ids: list[str] | None) -> list[DigestSource]:
    if not source_ids:
        return [source for source in store.list() if source.enabled]
    selected: list[DigestSource] = []
    for source_id in source_ids:
        source = store.get(source_id)
        if source is not None:
            selected.append(source)
    return selected


def _pull_one_source(
    source: DigestSource,
    vault: Vault,
    llm: LLMClient,
    store: RawInfoStore,
    report: DigestPullReport,
    *,
    max_items: int | None,
) -> None:
    seen = _load_seen(vault, source.id)
    created_or_seen: list[str] = []
    if source.kind == "rss":
        raw_items = fetch_source(SourceSpec(type="rss", url=source.url or ""))
        report.fetched += len(raw_items)
        for raw_item in raw_items:
            if max_items is not None and report.created >= max_items:
                break
            item_key = _rss_item_key(source.id, raw_item)
            if item_key in seen or store.has_item_key(item_key):
                continue
            report.new_items += 1
            normalized = _normalize_rss_item(source, raw_item, item_key, llm)
            if normalized is None:
                report.skipped += 1
                continue
            store.save(normalized)
            created_or_seen.append(item_key)
            report.created += 1
    else:
        payload = _run_prompt_source(source, llm)
        items = payload.get("items") or []
        if not isinstance(items, list):
            raise ValueError("prompt source JSON must contain items: []")
        warnings = _prompt_source_warnings(payload)
        if warnings and not items:
            raise ValueError("; ".join(warnings))
        report.fetched += len(items)
        for raw in items:
            if max_items is not None and report.created >= max_items:
                break
            if not isinstance(raw, dict):
                report.skipped += 1
                continue
            item_key = _prompt_item_key(source.id, raw)
            if not raw.get("url"):
                report.skipped += 1
                continue
            if item_key in seen or store.has_item_key(item_key):
                continue
            info = _raw_info_from_payload(
                source=source,
                payload=raw,
                item_key=item_key,
                fallback_title=str(raw.get("title") or ""),
                fallback_url=str(raw.get("url") or ""),
                content_excerpt="",
            )
            if info is None:
                report.skipped += 1
                continue
            store.save(info)
            created_or_seen.append(item_key)
            report.created += 1
            report.new_items += 1
    if created_or_seen:
        _save_seen(vault, source.id, [*seen, *created_or_seen])


def _normalize_rss_item(
    source: DigestSource,
    item: SourceItem,
    item_key: str,
    llm: LLMClient,
) -> RawInfo | None:
    payload = _run_rss_normalizer(source, item, llm)
    return _raw_info_from_payload(
        source=source,
        payload=payload,
        item_key=item_key,
        fallback_title=item.title,
        fallback_url=item.url,
        fallback_published_at=item.published,
        content_excerpt=item.content[:MAX_CONTENT_CHARS],
    )


def _run_rss_normalizer(source: DigestSource, item: SourceItem, llm: LLMClient) -> dict[str, Any]:
    prompt = f"""\
Knowlet digest source editor

Role:
You turn one RSS/Atom feed entry into one structured Raw Info item for a
user's review inbox. The original feed entry may be thin or noisy.

Input:
- Source name: {source.name}
- Feed URL: {source.url}
- Entry title: {item.title}
- Entry URL: {item.url}
- Published: {item.published or "null"}
- Entry content:
{item.content[:MAX_CONTENT_CHARS]}

Output only strict JSON with:
{{
  "title": "string",
  "summary": "string",
  "key_points": ["string"],
  "why_it_matters": "string",
  "suggested_tags": ["string"],
  "confidence": "high | medium | low"
}}

Do not output Markdown fences or commentary.
"""
    response = llm.chat(
        messages=[{"role": "user", "content": prompt}],
        tools=None,
        temperature=0.2,
    )
    return _parse_json_object(response.content)


def _run_prompt_source(source: DigestSource, llm: LLMClient) -> dict[str, Any]:
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    prompt = f"""\
Knowlet digest source editor

Role:
You are Knowlet's information-intake editor. You produce candidates for a
review inbox, not final notes and not chat answers.

Input:
The user-provided source prompt may be short, rough, or underspecified.
Insert it as the user's intent and turn it into reviewable information
items with original links.

User source prompt:
{source.prompt or ""}

Current date: {today}
Quantity: return up to 10 high-signal items.

Output only strict JSON:
{{
  "items": [
    {{
      "title": "string",
      "url": "https://...",
      "source_name": "string",
      "published_at": "YYYY-MM-DD or null",
      "summary": "string",
      "key_points": ["string"],
      "why_it_matters": "string",
      "suggested_tags": ["string"],
      "confidence": "high | medium | low"
    }}
  ],
  "warnings": ["string"]
}}

Rules:
- Every saved item needs a real original URL.
- Do not output Markdown fences, prose, or commentary outside JSON.
"""
    last_error: Exception | None = None
    tool_variants: list[list[dict[str, Any]]] = [
        [{"type": "web_search", "external_web_access": True}],
        [{"type": "web_search"}],
        [{"type": "web_search_preview"}],
        [],
    ]
    for tools in tool_variants:
        try:
            response = llm.responses(
                prompt,
                tools=tools or None,
                max_output_tokens=4000,
                temperature=0.2,
                role="digest_prompt_source",
            )
            if tools and not response_has_output_type(response.raw, "web_search_call"):
                raise ValueError("Responses returned no web_search_call")
            return _parse_json_object(response.content)
        except Exception as exc:
            last_error = exc
    assert last_error is not None
    raise last_error


def _prompt_source_warnings(payload: dict[str, Any]) -> list[str]:
    warnings = payload.get("warnings")
    if not isinstance(warnings, list):
        return []
    out = [str(item).strip() for item in warnings if str(item).strip()]
    return out


def _raw_info_from_payload(
    *,
    source: DigestSource,
    payload: dict[str, Any],
    item_key: str,
    fallback_title: str,
    fallback_url: str,
    fallback_published_at: str | None = None,
    content_excerpt: str = "",
) -> RawInfo | None:
    title = str(payload.get("title") or fallback_title).strip()
    url = str(payload.get("url") or fallback_url).strip()
    summary = str(payload.get("summary") or "").strip()
    if not title or not url or not summary:
        return None
    confidence = str(payload.get("confidence") or "medium").strip().lower()
    if confidence not in ("high", "medium", "low"):
        confidence = "medium"
    return RawInfo(
        source_id=source.id,
        source_name=source.name,
        source_kind=source.kind,
        item_key=item_key,
        title=title,
        url=url,
        published_at=(
            str(payload.get("published_at") or fallback_published_at)
            if (payload.get("published_at") or fallback_published_at)
            else None
        ),
        summary=summary,
        key_points=_string_list(payload.get("key_points")),
        why_it_matters=str(payload.get("why_it_matters") or "").strip(),
        suggested_tags=_string_list(payload.get("suggested_tags")),
        confidence=confidence,  # type: ignore[arg-type]
        content_excerpt=content_excerpt,
    )


def _string_list(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def _parse_json_object(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = raw.removeprefix("```json").removeprefix("```").strip()
        if raw.endswith("```"):
            raw = raw[:-3].strip()
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("expected JSON object")
    return payload


def _mark_source(
    source: DigestSource,
    store: DigestSourceStore,
    *,
    status: str,
    error: str | None,
) -> None:
    source.last_pull_at = now_iso()
    source.pull_status = status  # type: ignore[assignment]
    source.last_error = error
    if status == "ok":
        source.last_success_at = source.last_pull_at
    store.save(source)


def _seen_path(vault: Vault, source_id: str) -> Path:
    return vault.state_dir / "digest" / "seen" / f"{source_id}.json"


def _load_seen(vault: Vault, source_id: str) -> list[str]:
    path = _seen_path(vault, source_id)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    seen = data.get("seen", [])
    return [str(item) for item in seen] if isinstance(seen, list) else []


def _save_seen(vault: Vault, source_id: str, seen: list[str]) -> None:
    path = _seen_path(vault, source_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps({"seen": sorted(set(seen))}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def _auto_pull_state_path(vault: Vault) -> Path:
    return vault.state_dir / "digest" / AUTO_PULL_STATE_FILE


def _source_succeeded_on_day(source: DigestSource, day: str) -> bool:
    return bool(source.last_success_at and source.last_success_at.startswith(f"{day}T"))


def _read_auto_pull_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def _write_auto_pull_state(path: Path, *, last_by_source: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(
            {"last_by_source": last_by_source, "updated_at": now_iso()},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def _rss_item_key(source_id: str, item: SourceItem) -> str:
    stable = item.item_id or item.url or f"{item.title}|{item.published or ''}"
    return f"rss:{source_id}:{_short_hash(stable)}"


def _prompt_item_key(source_id: str, raw: dict[str, Any]) -> str:
    stable = str(raw.get("url") or "") or f"{raw.get('title') or ''}|{raw.get('summary') or ''}"
    return f"prompt:{source_id}:{_short_hash(stable)}"


def _short_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
