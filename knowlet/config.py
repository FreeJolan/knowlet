"""Configuration: schema, discovery, load/save.

Vault discovery follows the git pattern — walk up from CWD looking for `.knowlet/`.
Config file lives at `<vault>/.knowlet/config.toml`.
"""

from __future__ import annotations

import os
from pathlib import Path

import tomlkit
from pydantic import BaseModel, Field

CONFIG_FILENAME = "config.toml"
VAULT_MARKER_DIR = ".knowlet"


class LLMConfig(BaseModel):
    provider: str = "openai"
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "claude-opus-4-7"
    max_tokens: int = 1024
    temperature: float = 0.3


class EmbeddingConfig(BaseModel):
    backend: str = "sentence_transformers"
    model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    dim: int = 384


class RetrievalConfig(BaseModel):
    chunk_size: int = 500
    chunk_overlap: int = 100
    top_k: int = 5
    rrf_k: int = 60


class KnowletConfig(BaseModel):
    llm: LLMConfig = Field(default_factory=LLMConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)


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
    with p.open("r", encoding="utf-8") as f:
        data = tomlkit.parse(f.read()).unwrap()
    return KnowletConfig.model_validate(data)


def save_config(vault: Path, cfg: KnowletConfig) -> None:
    p = config_path(vault)
    p.parent.mkdir(parents=True, exist_ok=True)
    doc = tomlkit.document()
    for section, payload in cfg.model_dump().items():
        table = tomlkit.table()
        for k, v in payload.items():
            table.add(k, v)
        doc.add(section, table)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(tomlkit.dumps(doc), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(p)
