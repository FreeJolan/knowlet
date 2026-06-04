"""Configuration: schema, discovery, load/save.

Vault discovery follows the git pattern — walk up from CWD looking for `.knowlet/`.
Config file lives at `<vault>/.knowlet/config.toml`.
"""

from __future__ import annotations

import os
import tempfile
import tomllib  # stdlib (3.11+) — read only
from contextlib import suppress
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

CONFIG_FILENAME = "config.toml"
VAULT_MARKER_DIR = ".knowlet"
SYNC_CONFIG_DIR = "sync"
SYNC_CONFIG_SNAPSHOT_FILENAME = "config-public.toml"
DEFAULT_LLM_BASE_URL = "http://127.0.0.1:8317/v1"
DEFAULT_LLM_MODEL = "gpt-5.5"


class LLMConfig(BaseModel):
    provider: str = "openai"
    base_url: str = DEFAULT_LLM_BASE_URL
    api_key: str = ""
    model: str = DEFAULT_LLM_MODEL
    max_tokens: int = 1024
    # `None` means "let the provider pick its default." Some OpenAI-compatible
    # backends reject `temperature` for specific models; setting any value here
    # can force a 400-then-retry path on first call. Leave None unless the user
    # explicitly wants determinism on a known-compatible provider.
    temperature: float | None = None
    # Optional independent model for LLM rerank (Phase 3 Stage 1).
    # Empty string = "use ``model``"; otherwise the rerank path uses this
    # one (typically a cheaper / faster model). Same base_url + api_key are used.
    rerank_model: str = ""


class EmbeddingConfig(BaseModel):
    backend: str = "dummy"
    model: str = "dummy"
    dim: int = 384


class RetrievalConfig(BaseModel):
    chunk_size: int = 500
    chunk_overlap: int = 100
    top_k: int = 5
    rrf_k: int = 60


class GeneralConfig(BaseModel):
    """Top-level / cross-cutting settings.

    `language` is the UI / CLI / template language (ADR-0010). It does not
    affect chat reply language — the assistant still mirrors whatever
    language the user types in.
    """

    language: str = "en"  # "en" | "zh" (extend in core/i18n.py)


class WebSearchConfig(BaseModel):
    """ADR-0017: tunes the LLM web-search tool.

    `provider = ""` triggers auto-pick: brave > tavily > searx > ddg.
    Explicitly set to one of those names to force. API keys + searx URL
    are checked at provider construction time so a missing key surfaces
    immediately, not at first chat call.
    """

    provider: str = ""  # "" | "brave" | "tavily" | "searx" | "ddg"
    brave_api_key: str = ""
    tavily_api_key: str = ""
    searx_url: str = ""  # e.g. "https://searx.example.com"
    max_per_turn: int = 3  # hard ceiling per turn; tool raises beyond


class SyncConfig(BaseModel):
    """Phase 2 E Slice 5.A — opt-in Drive sync (ADR-0027).

    Empty by default. ``client_secrets_path`` is the user-provided
    Google OAuth client (downloaded from their own GCP project's
    Credentials page). knowlet does NOT bundle a shared client —
    requiring users to bring their own keeps trust local and avoids
    a single point of compromise for the whole user base.
    """

    # Path to the user's OAuth client_secret.json. May be absolute
    # or relative to the vault root. Empty = sync not configured.
    client_secrets_path: str = ""
    # Where the per-user tokens live. Default = inside .knowlet/ so
    # they ride along with the vault and stay private to the
    # local machine if .knowlet/ is excluded from cloud sync (per
    # ADR-0006 §40 default).
    token_path: str = ".knowlet/sync_credentials.json"  # noqa: S105 - path, not a secret


class KnowletConfig(BaseModel):
    general: GeneralConfig = Field(default_factory=GeneralConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    web_search: WebSearchConfig = Field(default_factory=WebSearchConfig)
    sync: SyncConfig = Field(default_factory=SyncConfig)


class VaultNotFoundError(RuntimeError):
    pass


def find_vault(start: Path | None = None) -> Path:
    """Walk up from start (or CWD) looking for a `.knowlet/` directory.

    Honors KNOWLET_VAULT env var if set.
    """
    env = os.environ.get("KNOWLET_VAULT")
    if env:
        p = Path(env).expanduser().resolve()
        if (p / VAULT_MARKER_DIR).is_dir():
            return p
        raise VaultNotFoundError(
            f"KNOWLET_VAULT={env} does not contain a {VAULT_MARKER_DIR}/ directory"
        )

    cur = (start or Path.cwd()).resolve()
    for candidate in [cur, *cur.parents]:
        if (candidate / VAULT_MARKER_DIR).is_dir():
            return candidate
    raise VaultNotFoundError(
        f"No {VAULT_MARKER_DIR}/ found in {cur} or any parent. "
        f"Run `knowlet vault init <path>` first, or set KNOWLET_VAULT."
    )


def config_path(vault: Path) -> Path:
    return vault / VAULT_MARKER_DIR / CONFIG_FILENAME


def synced_config_snapshot_path(vault: Path) -> Path:
    return vault / VAULT_MARKER_DIR / SYNC_CONFIG_DIR / SYNC_CONFIG_SNAPSHOT_FILENAME


def load_config(vault: Path) -> KnowletConfig:
    p = config_path(vault)
    if not p.exists():
        snapshot = synced_config_snapshot_path(vault)
        if snapshot.exists():
            return _load_config_file(snapshot)
        return KnowletConfig()
    return _load_config_file(p)


def _load_config_file(path: Path) -> KnowletConfig:
    with path.open("rb") as f:
        data = tomllib.load(f)
    return KnowletConfig.model_validate(data)


def _scrub_config_for_sync(cfg: KnowletConfig) -> dict[str, Any]:
    """Return config fields safe to sync across devices.

    Secrets and device-local paths stay out:
    - LLM/Web-search API keys.
    - sync OAuth client/token paths.
    """
    data = cfg.model_dump()
    data.get("llm", {}).pop("api_key", None)
    web_search = data.get("web_search", {})
    web_search.pop("brave_api_key", None)
    web_search.pop("tavily_api_key", None)
    web_search.pop("searx_url", None)
    data.pop("sync", None)
    return data


def _toml_from_payload(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    for section, values in payload.items():
        if not isinstance(values, dict):
            continue
        lines.append(f"[{section}]")
        for k, v in values.items():
            if v is None:
                continue  # TOML has no null; absence is the canonical encoding
            lines.append(f"{k} = {_toml_value(v)}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_synced_config_snapshot(vault: Path, cfg: KnowletConfig) -> Path:
    p = synced_config_snapshot_path(vault)
    p.parent.mkdir(parents=True, exist_ok=True)
    text = _toml_from_payload(_scrub_config_for_sync(cfg))
    fd, tmp_name = tempfile.mkstemp(prefix=f"{p.name}.", suffix=".tmp", dir=p.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(tmp, 0o600)
        tmp.replace(p)
    except Exception:
        with suppress(OSError):
            tmp.unlink()
        raise
    from knowlet.core.sync.tracked_files import queue_syncable_vault_file_if_authenticated

    queue_syncable_vault_file_if_authenticated(vault_root=vault, path=p)
    return p


def _toml_value(v: Any) -> str:
    """Serialize a single primitive value as TOML.

    Sufficient for knowlet's config schema (str / int / float / bool only —
    no nested tables, no arrays, no datetimes). When that changes, switch
    to a real writer.
    """
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        # Use double-quoted strings; escape backslash and double quote.
        escaped = v.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    raise TypeError(f"unsupported config value type: {type(v).__name__}")


def save_config(
    vault: Path,
    cfg: KnowletConfig,
    *,
    sync_snapshot: bool = True,
) -> None:
    p = config_path(vault)
    p.parent.mkdir(parents=True, exist_ok=True)
    text = _toml_from_payload(cfg.model_dump())
    fd, tmp_name = tempfile.mkstemp(prefix=f"{p.name}.", suffix=".tmp", dir=p.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(tmp, 0o600)
        tmp.replace(p)
    except Exception:
        with suppress(OSError):
            tmp.unlink()
        raise
    if sync_snapshot:
        write_synced_config_snapshot(vault, cfg)


def apply_synced_config_snapshot(vault: Path) -> KnowletConfig | None:
    snapshot = synced_config_snapshot_path(vault)
    if not snapshot.exists():
        return None
    incoming = _load_config_file(snapshot)
    raw = config_path(vault)
    local = _load_config_file(raw) if raw.exists() else KnowletConfig()
    incoming.llm.api_key = local.llm.api_key
    incoming.web_search.brave_api_key = local.web_search.brave_api_key
    incoming.web_search.tavily_api_key = local.web_search.tavily_api_key
    incoming.web_search.searx_url = local.web_search.searx_url
    incoming.sync = local.sync
    save_config(vault, incoming, sync_snapshot=False)
    return incoming
