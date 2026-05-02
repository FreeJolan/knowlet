"""Configuration: schema, discovery, load/save.

Vault discovery follows the git pattern — walk up from CWD looking for `.knowlet/`.
Config file lives at `<vault>/.knowlet/config.toml`.
"""

from __future__ import annotations

import os
import tomllib  # stdlib (3.11+) — read only
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

CONFIG_FILENAME = "config.toml"
VAULT_MARKER_DIR = ".knowlet"


class LLMConfig(BaseModel):
    provider: str = "openai"
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "claude-opus-4-7"
    max_tokens: int = 1024
    # `None` means "let the provider pick its default." Claude 4.x models
    # reject `temperature` outright; setting any value here forces the
    # client into a 400-then-retry path on first call. Leave None unless
    # the user explicitly wants determinism on a non-Claude provider.
    temperature: float | None = None


class EmbeddingConfig(BaseModel):
    backend: str = "sentence_transformers"
    model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
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

    provider: str = ""              # "" | "brave" | "tavily" | "searx" | "ddg"
    brave_api_key: str = ""
    tavily_api_key: str = ""
    searx_url: str = ""             # e.g. "https://searx.example.com"
    max_per_turn: int = 3           # hard ceiling per turn; tool raises beyond


class KnowletConfig(BaseModel):
    general: GeneralConfig = Field(default_factory=GeneralConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    web_search: WebSearchConfig = Field(default_factory=WebSearchConfig)


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


def load_config(vault: Path) -> KnowletConfig:
    p = config_path(vault)
    if not p.exists():
        return KnowletConfig()
    with p.open("rb") as f:
        data = tomllib.load(f)
    return KnowletConfig.model_validate(data)


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


def save_config(vault: Path, cfg: KnowletConfig) -> None:
    p = config_path(vault)
    p.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for section, payload in cfg.model_dump().items():
        lines.append(f"[{section}]")
        for k, v in payload.items():
            if v is None:
                continue  # TOML has no null; absence is the canonical encoding
            lines.append(f"{k} = {_toml_value(v)}")
        lines.append("")
    text = "\n".join(lines).rstrip() + "\n"
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(p)
