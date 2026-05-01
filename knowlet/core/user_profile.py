"""User profile (`<vault>/users/me.md`) — the user's own description of who
they are, what they care about, how they want the assistant to respond.

This is the "分层用户上下文 / Markdown 意图层" layer from ADR-0003. The MVP
keeps it simple: a single Markdown file with frontmatter, owned by the user,
read on every chat session, surfaced to the LLM via two complementary paths:

1. The chat system prompt embeds the body so compliant backends see it
   without any tool call.
2. The `get_user_profile` atomic tool exposes the same content so backends
   that ignore role:'system' (e.g., Claude-Code-via-proxy) can still reach
   it via a function call.

See ADR-0008 for why these two paths share a single backend function.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import frontmatter

from knowlet.core.note import now_iso

PROFILE_FILENAME = "me.md"
PROFILE_BODY_CHAR_LIMIT = 8000  # ~2000 tokens; truncate beyond this for safety

DEFAULT_PROFILE_TEMPLATE = """\
# About me

写一段关于你自己的短描述,让 knowlet 在每次对话中知道你是谁。
建议覆盖:

## 当前关注
- 我目前在研究 / 学习 / 思考的事

## 偏好与风格
- 我喜欢什么样的回答(简洁 vs 详尽 / 中文 vs 英文 / 公式 vs 类比)
- 我不喜欢什么(不要寒暄、不要过度礼貌、不要凭空发明引用)

## 已有的背景
- 我已经熟悉的领域、可以省略基础解释的范围

## 这份文档
随手编辑就好,knowlet 每次启动会重新读取。可以放进 vault 的同步管道(iCloud / Syncthing)跨设备共用。
"""


@dataclass
class UserProfile:
    """In-memory representation of `<vault>/users/me.md`."""

    body: str
    name: str | None = None
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    path: Path | None = None

    @property
    def is_empty(self) -> bool:
        return not self.body.strip()

    def to_markdown(self) -> str:
        meta: dict[str, str | None] = {
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self.name:
            meta["name"] = self.name
        post = frontmatter.Post(self.body, **{k: v for k, v in meta.items() if v is not None})
        return frontmatter.dumps(post)

    def truncated_for_prompt(self, limit: int = PROFILE_BODY_CHAR_LIMIT) -> str:
        body = self.body.strip()
        if len(body) <= limit:
            return body
        return body[:limit].rstrip() + "\n\n…(profile truncated for prompt)"


def read_profile(profile_path: Path) -> UserProfile | None:
    """Load `<vault>/users/me.md` if present. Returns None when missing."""
    if not profile_path.exists():
        return None
    with profile_path.open("r", encoding="utf-8") as f:
        post = frontmatter.load(f)
    meta = post.metadata
    return UserProfile(
        body=post.content,
        name=str(meta["name"]) if meta.get("name") else None,
        created_at=str(meta.get("created_at") or now_iso()),
        updated_at=str(meta.get("updated_at") or now_iso()),
        path=profile_path,
    )


def write_profile(profile_path: Path, profile: UserProfile) -> Path:
    """Atomically write the profile to disk with 0600 perms.

    The profile typically contains personal information, so we keep it
    user-readable only by default — the user's data sovereignty is the
    project's first principle (see ADR-0002).
    """
    import os

    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile.updated_at = now_iso()
    profile.path = profile_path
    tmp = profile_path.with_suffix(profile_path.suffix + ".tmp")
    tmp.write_text(profile.to_markdown(), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(profile_path)
    return profile_path


def ensure_profile(profile_path: Path) -> UserProfile:
    """Return existing profile, or create a default one if missing."""
    existing = read_profile(profile_path)
    if existing is not None:
        return existing
    profile = UserProfile(body=DEFAULT_PROFILE_TEMPLATE.strip())
    write_profile(profile_path, profile)
    return profile


def edit_profile_in_editor(profile_path: Path) -> UserProfile:
    """Open `<vault>/users/me.md` in $EDITOR for direct editing.

    Creates the file with the default template if missing. Returns the
    profile after the editor exits. Raises subprocess.CalledProcessError on
    editor failure; FileNotFoundError if $EDITOR is not on PATH.

    The CLI subcommand `knowlet user edit` and the slash `:user edit` share
    this single backend function — see ADR-0008 (CLI parity discipline).
    """
    import os
    import subprocess

    ensure_profile(profile_path)
    editor = os.environ.get("EDITOR") or "vi"
    subprocess.run([editor, str(profile_path)], check=True)
    profile = read_profile(profile_path)
    assert profile is not None  # ensure_profile guaranteed it exists
    # Refresh updated_at since the user may have edited the body without touching frontmatter.
    write_profile(profile_path, profile)
    return profile
