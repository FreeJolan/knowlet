"""i18n primitives — minimal hand-rolled catalog.

Per ADR-0010, knowlet is multilingual with **English as the default**.
Currently bundled languages: `en`, `zh`. Adding a new language = adding a
new key to `_CATALOGS` and translating the values.

Per the no-wheel-reinvention memory, gettext / babel are overkill for our
~200-string scale. A flat dict-of-dicts is debuggable, agent-friendly, and
zero-dependency.

API:
    from knowlet.core.i18n import t, set_language, current_language

    set_language("zh")
    t("vault.init.success", root="/some/path")  # → "vault 已在 /some/path 初始化"

`t()` falls back to English if a key is missing in the active language, and
returns the key itself if absent in English too — making gaps loud rather
than silent. UI tests should detect "key wasn't translated" by asserting
the rendered string differs from the key.
"""

from __future__ import annotations

import os
from typing import Any

DEFAULT_LANGUAGE = "en"
SUPPORTED_LANGUAGES: tuple[str, ...] = ("en", "zh")

_current_language: str = DEFAULT_LANGUAGE


def set_language(lang: str | None) -> str:
    """Set the active language. Falls back to default if `lang` isn't supported.

    Returns the language that was actually set (so callers can observe a
    fallback without a try/except)."""
    global _current_language
    if not lang:
        _current_language = DEFAULT_LANGUAGE
        return _current_language
    norm = lang.strip().lower().split("-")[0]  # zh-CN → zh
    if norm in SUPPORTED_LANGUAGES:
        _current_language = norm
    else:
        _current_language = DEFAULT_LANGUAGE
    return _current_language


def current_language() -> str:
    return _current_language


def init_from_env(default: str = DEFAULT_LANGUAGE) -> str:
    """Initialize from KNOWLET_LANG env var if present, else `default`."""
    env = os.environ.get("KNOWLET_LANG")
    return set_language(env or default)


def t(key: str, lang: str | None = None, /, **vars: Any) -> str:
    """Translate `key` into the active language (or `lang` if given).

    Missing key → falls back to English. Missing in English too → returns
    the key string itself, which makes gaps obvious during development.
    """
    target = (lang or _current_language).split("-")[0]
    catalog = _CATALOGS.get(target) or _CATALOGS[DEFAULT_LANGUAGE]
    template = catalog.get(key) or _CATALOGS[DEFAULT_LANGUAGE].get(key) or key
    if vars:
        try:
            return template.format(**vars)
        except (KeyError, IndexError):
            return template
    return template


def all_keys(lang: str = DEFAULT_LANGUAGE) -> dict[str, str]:
    """Return the full catalog for one language. Useful for the web UI to
    fetch via `/api/i18n/{lang}.json`."""
    return dict(_CATALOGS.get(lang) or _CATALOGS[DEFAULT_LANGUAGE])


# ----------------------------------------------------- catalogs


_EN: dict[str, str] = {
    # vault
    "vault.init.banner": (
        "vault initialized at {root}\n"
        "  notes/                ← put or sediment Notes here\n"
        "  .knowlet/index.sqlite ← FTS5 + sqlite-vec index\n"
        "  .knowlet/config.toml  ← run `knowlet config init` to set the LLM"
    ),
    "vault.init.title": "vault init",
    "vault.notfound": (
        "No vault found in {cwd} or any parent.\n"
        "Initialize one here so you can start chatting?"
    ),
    "vault.welcome.title": "welcome",
    "vault.init.prompt": "initialize vault here?",
    "vault.dir.prompt": "vault directory",
    "vault.created": "vault initialized at {root}",
    # config
    "config.llm.title": "LLM backend",
    "config.llm.intro": (
        "Point knowlet at any OpenAI-compatible HTTP service.\n"
        "Examples: OpenAI, Anthropic-via-OpenAI shim, OpenRouter, Ollama, "
        "or a local wrapper that fronts your AI tool of choice.\n"
        "knowlet does not proxy or store credentials beyond this file."
    ),
    "config.base_url.prompt": "base URL",
    "config.model.prompt": "model name",
    "config.api_key.prompt": "API key",
    "config.embed.title": "Embedding (local)",
    "config.embed.backend.prompt": "backend (sentence_transformers/dummy)",
    "config.embed.model.prompt": "model",
    "config.lang.title": "Interface language",
    "config.lang.prompt": "language (en/zh)",
    "config.saved": "config saved → {path}",
    "config.next": (
        "Next: run [bold]knowlet doctor[/bold] to verify the backend is reachable\n"
        "and tool-calling works, then [bold]knowlet chat[/bold] to start a session."
    ),
    "config.llm_setup.title": "LLM setup",
    "config.llm_setup.intro": (
        "LLM is not configured yet — let's do that now.\n"
        "knowlet talks to any OpenAI-compatible HTTP service."
    ),
    # chat REPL
    "chat.banner.title": "knowlet {version}",
    "chat.banner.body": (
        "[bold]knowlet[/bold]  vault={vault}  model={model}\n"
        ":save :ls :reindex :doctor :config :user :cards :mining :drafts :clear :help :quit"
    ),
    "chat.prompt": "[bold cyan]you[/bold cyan]",
    "chat.history.cleared": "history cleared",
    "chat.error": "LLM error: {err}",
    # slash
    "slash.help.title": "slash commands",
    "slash.help.body": (
        ":save              draft a Note from this chat and review it\n"
        ":ls [-r]           list Notes (created_at; -r for updated_at)\n"
        ":reindex           re-scan vault notes from disk\n"
        ":doctor            run diagnostics on backend + embedding\n"
        ":config show       print the current config (key masked)\n"
        ":user [edit]       show or edit your profile (users/me.md)\n"
        ":cards due         list cards due now\n"
        ":cards review      run an interactive review session\n"
        ":mining list       show configured mining tasks\n"
        ":mining run-all    run every enabled mining task now\n"
        ":drafts list       drafts pending review\n"
        ":drafts approve <id> / reject <id>   review a draft\n"
        ":tools             list LLM-callable tools\n"
        ":clear             reset chat history (keeps system prompt)\n"
        ":help              this help (also  ?)\n"
        ":quit              exit  (also  :q  :exit  Ctrl-D)"
    ),
    # sediment / draft review
    "sediment.drafting": "drafting Note from conversation…",
    "sediment.draft.title": "draft",
    "sediment.draft.choices": "save? [y]es / [n]o / [e]dit",
    "sediment.discarded": "discarded",
    "sediment.saved": "saved → {path}",
    "sediment.editor.failed": "editor failed: {err}",
    "sediment.empty": "nothing to sediment yet",
    # web UI labels (also served via /api/i18n/{lang}.json)
    "web.send": "send",
    "web.profile": "profile",
    "web.clear": "clear",
    "web.save": "save",
    "web.cancel": "cancel",
    "web.composer.placeholder": "Ask, discuss, or paste — Cmd+Enter to send.",
    "web.recent_notes": "recent notes",
    "web.notes.empty": "no notes yet — save a chat to create the first one.",
    "web.cards.due": "cards due",
    "web.cards.start_review": "start review",
    "web.cards.empty": "nothing due — make some cards in chat",
    "web.drafts.inbox": "drafts inbox",
    "web.drafts.empty": "inbox empty — run mining or wait for the schedule",
    "web.drafts.review": "review drafts",
    "web.drafts.run_mining": "run mining now",
    "web.drafts.title": "drafts review",
    "web.drafts.reject": "reject",
    "web.drafts.skip": "skip",
    "web.drafts.approve": "approve",
    "web.drafts.quit": "quit",
    "web.review.modal.title": "review",
    "web.review.reveal": "reveal",
    "web.review.again": "again",
    "web.review.hard": "hard",
    "web.review.good": "good",
    "web.review.easy": "easy",
    "web.draft.modal.title": "save this chat as a Note",
    "web.draft.field.title": "title",
    "web.draft.field.tags": "tags (comma-separated)",
    "web.draft.field.body": "body",
    "web.profile.modal.title": "your profile",
    "web.profile.intro": "knowlet reads this on every chat session. edit freely.",
    "web.profile.field.name": "name (optional)",
    "web.profile.field.body": "body (Markdown)",
    "web.note.close": "close",
    "web.toast.cleared": "history cleared",
    "web.toast.note_saved": "note saved",
    "web.toast.profile_saved": "profile saved",
    "web.toast.review_done": "review done",
    "web.toast.empty_inbox": "inbox empty",
    "web.toast.required_fields": "title and body are required",
    # generic
    "ok": "ok",
    "yes": "yes",
    "no": "no",
}


_ZH: dict[str, str] = {
    "vault.init.banner": (
        "vault 已在 {root} 初始化\n"
        "  notes/                ← 放或沉淀 Note 在此\n"
        "  .knowlet/index.sqlite ← FTS5 + sqlite-vec 索引\n"
        "  .knowlet/config.toml  ← 运行 `knowlet config init` 来配置 LLM"
    ),
    "vault.init.title": "vault 初始化",
    "vault.notfound": (
        "在 {cwd} 及其父目录都没找到 vault。\n"
        "在这里初始化一个,马上开始用?"
    ),
    "vault.welcome.title": "欢迎",
    "vault.init.prompt": "在这里初始化 vault?",
    "vault.dir.prompt": "vault 目录",
    "vault.created": "vault 已在 {root} 初始化",
    "config.llm.title": "LLM 后端",
    "config.llm.intro": (
        "把 knowlet 接到任意兼容 OpenAI 协议的 HTTP 服务。\n"
        "示例:OpenAI、Anthropic-via-OpenAI 转接层、OpenRouter、Ollama、"
        "或者把你常用 AI 工具暴露成 OpenAI 端点的本地 wrapper。\n"
        "knowlet 不代理也不离开本地存储凭据。"
    ),
    "config.base_url.prompt": "base URL",
    "config.model.prompt": "模型名",
    "config.api_key.prompt": "API key",
    "config.embed.title": "Embedding(本地)",
    "config.embed.backend.prompt": "backend(sentence_transformers/dummy)",
    "config.embed.model.prompt": "模型",
    "config.lang.title": "界面语言",
    "config.lang.prompt": "语言 (en/zh)",
    "config.saved": "config 已保存 → {path}",
    "config.next": (
        "下一步:运行 [bold]knowlet doctor[/bold] 验证后端可达 + tool-calling 工作\n"
        "然后 [bold]knowlet chat[/bold] 开始对话。"
    ),
    "config.llm_setup.title": "LLM 配置",
    "config.llm_setup.intro": (
        "LLM 还没配置 —— 现在就配。\n"
        "knowlet 跟任何兼容 OpenAI 协议的 HTTP 服务对话。"
    ),
    "chat.banner.title": "knowlet {version}",
    "chat.banner.body": (
        "[bold]knowlet[/bold]  vault={vault}  model={model}\n"
        ":save :ls :reindex :doctor :config :user :cards :mining :drafts :clear :help :quit"
    ),
    "chat.prompt": "[bold cyan]你[/bold cyan]",
    "chat.history.cleared": "历史已清空",
    "chat.error": "LLM 错误:{err}",
    "slash.help.title": "slash 命令",
    "slash.help.body": (
        ":save              把这段对话沉淀成 Note 并审查\n"
        ":ls [-r]           列出 Note(默认按创建时间;-r 按更新时间)\n"
        ":reindex           从磁盘重扫 Note 重建索引\n"
        ":doctor            诊断 backend + embedding\n"
        ":config show       打印当前配置(key 已掩码)\n"
        ":user [edit]       查看或编辑 profile (users/me.md)\n"
        ":cards due         列出当前到期的卡\n"
        ":cards review      进入交互式复习会话\n"
        ":mining list       查看配置的挖掘任务\n"
        ":mining run-all    立刻跑所有启用的挖掘任务\n"
        ":drafts list       待审查的草稿\n"
        ":drafts approve <id> / reject <id>   审查单条草稿\n"
        ":tools             列出 LLM 可调用的工具\n"
        ":clear             清空对话历史(保留 system prompt)\n"
        ":help              本帮助(也可用  ?)\n"
        ":quit              退出  (也可用  :q  :exit  Ctrl-D)"
    ),
    "sediment.drafting": "正在从对话生成 Note 草稿…",
    "sediment.draft.title": "草稿",
    "sediment.draft.choices": "保存?[y]是 / [n]否 / [e]编辑",
    "sediment.discarded": "已丢弃",
    "sediment.saved": "已保存 → {path}",
    "sediment.editor.failed": "编辑器执行失败:{err}",
    "sediment.empty": "对话还没什么内容可沉淀",
    "web.send": "发送",
    "web.profile": "档案",
    "web.clear": "清空",
    "web.save": "保存",
    "web.cancel": "取消",
    "web.composer.placeholder": "提问、讨论、粘贴 —— Cmd+Enter 发送。",
    "web.recent_notes": "最近的 Note",
    "web.notes.empty": "还没有 Note —— 保存一段 chat 试试。",
    "web.cards.due": "到期卡片",
    "web.cards.start_review": "开始复习",
    "web.cards.empty": "目前没有到期的 —— 在 chat 里加点卡片吧",
    "web.drafts.inbox": "草稿待审",
    "web.drafts.empty": "收件箱为空 —— 运行挖掘或等定时器",
    "web.drafts.review": "审查草稿",
    "web.drafts.run_mining": "立刻跑挖掘",
    "web.drafts.title": "草稿审查",
    "web.drafts.reject": "拒绝",
    "web.drafts.skip": "跳过",
    "web.drafts.approve": "通过",
    "web.drafts.quit": "退出",
    "web.review.modal.title": "复习",
    "web.review.reveal": "翻面",
    "web.review.again": "重来",
    "web.review.hard": "困难",
    "web.review.good": "良好",
    "web.review.easy": "简单",
    "web.draft.modal.title": "把这段 chat 保存为 Note",
    "web.draft.field.title": "标题",
    "web.draft.field.tags": "tag(逗号分隔)",
    "web.draft.field.body": "正文",
    "web.profile.modal.title": "你的档案",
    "web.profile.intro": "knowlet 在每次 chat 启动都会读取它。随时改。",
    "web.profile.field.name": "姓名(可选)",
    "web.profile.field.body": "正文(Markdown)",
    "web.note.close": "关闭",
    "web.toast.cleared": "历史已清空",
    "web.toast.note_saved": "已保存 Note",
    "web.toast.profile_saved": "已保存档案",
    "web.toast.review_done": "复习完成",
    "web.toast.empty_inbox": "收件箱为空",
    "web.toast.required_fields": "标题和正文都是必填的",
    "ok": "好",
    "yes": "是",
    "no": "否",
}


_CATALOGS: dict[str, dict[str, str]] = {
    "en": _EN,
    "zh": _ZH,
}
