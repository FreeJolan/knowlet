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

import contextvars
import os
from typing import Any

DEFAULT_LANGUAGE = "en"
SUPPORTED_LANGUAGES: tuple[str, ...] = ("en", "zh")

# Context-var instead of a module global so language doesn't leak across
# threads / async tasks. Each FastAPI request, scheduler thread, or worker
# task that wants its own language calls `set_language` and the change stays
# in that context. Default value applies to any context that hasn't set one.
_current_language: contextvars.ContextVar[str] = contextvars.ContextVar(
    "knowlet_current_language", default=DEFAULT_LANGUAGE
)


def set_language(lang: str | None) -> str:
    """Set the active language. Falls back to default if `lang` isn't supported.

    Returns the language that was actually set (so callers can observe a
    fallback without a try/except)."""
    if not lang:
        _current_language.set(DEFAULT_LANGUAGE)
        return DEFAULT_LANGUAGE
    norm = lang.strip().lower().split("-")[0]  # zh-CN → zh
    chosen = norm if norm in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE
    _current_language.set(chosen)
    return chosen


def current_language() -> str:
    return _current_language.get()


def init_from_env(default: str = DEFAULT_LANGUAGE) -> str:
    """Initialize from KNOWLET_LANG env var if present, else `default`."""
    env = os.environ.get("KNOWLET_LANG")
    return set_language(env or default)


def t(key: str, lang: str | None = None, /, **vars: Any) -> str:
    """Translate `key` into the active language (or `lang` if given).

    Missing key → falls back to English. Missing in English too → returns
    the key string itself, which makes gaps obvious during development.
    """
    target = (lang or _current_language.get()).split("-")[0]
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
    # ----- web UI -----
    # Header
    "header.palette.label": "Search · Run · Ask",
    "header.palette.title": "Command palette  (⌘K)",
    # Async bootstrap (B4)
    "health.indexing.label": "Indexing your notes…",
    "health.indexing.done": "Index ready — chat is warmed up.",
    "health.bootstrap.error": "Bootstrap failed",
    "header.save.title": "Save this chat as a note",
    "header.settings.title": "Profile & settings",
    # Cmd+K palette
    "palette.placeholder": "Jump to a note · run a command · `>` ask AI · `+` new note",
    "palette.section.notes": "Notes",
    "palette.section.commands": "Commands",
    "palette.section.askai": "Ask AI",
    "palette.section.newnote": "New note",
    "palette.kind.note": "NOTE",
    "palette.kind.cmd": "CMD",
    "palette.kind.ask": "AI",
    "palette.kind.newnote": "NEW",
    "palette.row.open": "↵",
    "palette.row.run": "↵",
    "palette.row.ask": "↵ ask",
    "palette.row.create": "↵",
    "palette.empty": "No matches.",
    "palette.askai.empty": "Type a question after `>`",
    "palette.askai.sub": "One-shot answer · stays out of chat history",
    "palette.askai.streaming": "claude · thinking…",
    "palette.askai.done": "claude · answer",
    "palette.newnote.empty": "Type a title after `+`",
    "palette.newnote.sub": "Create a new note in the vault",
    "palette.kbd.move": "select",
    "palette.kbd.open": "open",
    "palette.kbd.newtab": "new tab",
    "palette.parity": "parity: each command = a CLI · ADR-0008",
    # Palette commands (each maps to a CLI mirror per ADR-0008)
    "palette.cmd.mining": "Fetch all feeds now",
    "palette.cmd.mining.sub": "knowlet mining run-all",
    "palette.cmd.drafts": "Review inbox",
    "palette.cmd.drafts.sub": "knowlet drafts review",
    "palette.cmd.cards": "Review flashcards",
    "palette.cmd.cards.sub": "knowlet cards review",
    "palette.cmd.sediment": "Save chat as a note",
    "palette.cmd.sediment.sub": "knowlet chat sediment",
    "palette.cmd.clearchat": "Clear chat",
    "palette.cmd.clearchat.sub": "knowlet chat clear",
    "palette.cmd.profile": "Open profile",
    "palette.cmd.profile.sub": "knowlet profile edit",
    "palette.cmd.newnote": "New note",
    "palette.cmd.newnote.sub": "knowlet notes new",
    # Sidebar (vault tree)
    "sidebar.search.placeholder": "Search notes…",
    "sidebar.new.title": "New note",
    "sidebar.empty": "No notes yet — tap + to create one.",
    "sidebar.loading": "Loading…",
    # Tabs
    "tab.close": "Close",
    "tab.dirty": "Unsaved",
    # Editor
    "editor.mode.edit": "Edit",
    "editor.mode.split": "Split",
    "editor.mode.preview": "Preview",
    "editor.empty.before": "Pick a note on the left, or tap",
    "editor.empty.after": "to create one",
    "editor.placeholder": "Start writing… Markdown supported.",
    "editor.saving": "Saving…",
    "editor.chars": "{n} chars",
    "editor.savedmeta": "saved · UTF-8 · LF",
    # Right rail
    "rail.tab.outline": "Outline",
    "rail.tab.backlinks": "Linked notes",
    "rail.tab.ai": "AI",
    "rail.collapse.title": "Collapse",
    "rail.outline.empty": "No headings yet (#, ##, ### lines).",
    "rail.backlinks.placeholder": (
        "This panel will surface notes that reference the current one, "
        "with sentence-level previews. Coming in M6.2."
    ),
    "rail.ai.scope.label": "Context",
    "rail.ai.scope.note": "This note",
    "rail.ai.scope.vault": "All notes",
    "rail.ai.scope.none": "None",
    "rail.ai.clear.title": "Clear chat",
    "rail.ai.clear.label": "Clear",
    "rail.ai.placeholder": "Ask anything — Enter to send, Shift+Enter for newline",
    "rail.ai.empty": 'Ask anything about "{title}".',
    "rail.ai.empty.notitle": "(pick a note first)",
    "rail.ai.expand.title": "Open chat in focus mode",
    "rail.ai.label.you": "you",
    "rail.ai.label.ai": "claude",
    "rail.ai.composer.hint": "↵ send · ⇧↵ newline",
    # Footer
    "footer.inbox.label": "Inbox",
    "footer.inbox.title": "Items AI fetched for you, awaiting review",
    "footer.review.label": "Review",
    "footer.review.title": "Due flashcards",
    "footer.feed.label": "Feeds",
    "footer.feed.title": "Click to fetch new items now",
    "footer.feed.running": "Fetching…",
    "footer.feed.empty": "(none configured)",
    # Inbox / drafts focus mode
    "inbox.title": "Inbox",
    "inbox.empty": "Your inbox is empty.",
    "inbox.source": "Source",
    "inbox.tags": "Tags",
    "inbox.fetched": "fetched",
    "inbox.savepath": "Saved to",
    "inbox.action.discard": "Discard",
    "inbox.action.later": "Later",
    "inbox.action.keep": "Keep as note",
    "inbox.done": "Inbox cleared!",
    # Review / cards focus mode
    "review.title": "Review",
    "review.empty": "No cards due.",
    "review.front": "Front",
    "review.back": "Back",
    "review.reveal": "Reveal answer",
    "review.fsrs.hint": "FSRS · the next interval shows after you flip",
    "review.rate.again": "Again",
    "review.rate.hard": "Hard",
    "review.rate.good": "Good",
    "review.rate.easy": "Easy",
    "review.rate.again.title": "Forgot — restart from learning",
    "review.rate.hard.title": "Recalled with effort",
    "review.rate.good.title": "Recalled comfortably",
    "review.rate.easy.title": "Trivially easy — push interval out",
    "review.done": "Done for today!",
    # Focus mode shared chrome
    "focus.exit": "exit",
    "focus.prev": "prev",
    "focus.next": "next",
    # Chat focus mode
    "chat.focus.title": "Chat",
    "chat.focus.singlesession": "Single session · multi-session lands in M6.4",
    # Save chat as note (web flow)
    "sediment.web.title": "Save this chat as a note",
    "sediment.web.drafting": "Composing your note… (Opus takes ~25s)",
    "sediment.web.field.title": "Title",
    "sediment.web.field.tags": "Tags (comma-separated)",
    "sediment.web.field.body": "Body",
    "sediment.web.cancel": "Cancel",
    "sediment.web.commit": "Save",
    "sediment.web.required": "Both title and body are required.",
    "sediment.web.saved": "Saved as a note.",
    # Profile modal (web)
    "profile.web.title": "Profile",
    "profile.web.intro": (
        "AI reads this every time you chat — your interests, preferences, "
        "background. Edit freely."
    ),
    "profile.web.field.name": "Name (optional)",
    "profile.web.field.body": "Body (Markdown)",
    "profile.web.cancel": "Cancel",
    "profile.web.save": "Save",
    "profile.web.saved": "Profile saved.",
    # Prompts
    "prompt.new.title": "Title for the new note",
    # Mining run-all toasts (kept value-only, not action-only — "Feeds" word)
    "mining.toast.empty": "Fetched {n} · nothing new.",
    "mining.toast.no_drafts": "Fetched {n} · {m} new but AI extracted nothing usable.",
    "mining.toast.success": "Fetched {n} · {m} new items ready for review.",
    # Chat
    "chat.web.cleared": "Chat cleared.",
    # Common
    "modal.close": "Close",
    # Generic
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
    # ----- web UI(每条独立写,不直接翻译英文)-----
    # Header
    "header.palette.label": "搜索 / 命令 / 问 AI",
    "header.palette.title": "命令面板(⌘K)",
    # 异步启动状态(B4)
    "health.indexing.label": "正在为笔记建索引…",
    "health.indexing.done": "索引就绪,可以开始对话了。",
    "health.bootstrap.error": "启动失败",
    "header.save.title": "把这段对话存成笔记",
    "header.settings.title": "个人资料 · 设置",
    # ⌘K 命令面板
    "palette.placeholder": "跳转笔记 · 跑命令 · 用 > 直接问 AI · 用 + 新建笔记",
    "palette.section.notes": "笔记",
    "palette.section.commands": "命令",
    "palette.section.askai": "问 AI",
    "palette.section.newnote": "新建笔记",
    "palette.kind.note": "笔记",
    "palette.kind.cmd": "命令",
    "palette.kind.ask": "AI",
    "palette.kind.newnote": "新建",
    "palette.row.open": "⏎",
    "palette.row.run": "⏎",
    "palette.row.ask": "⏎ 问",
    "palette.row.create": "⏎",
    "palette.empty": "没有匹配项。",
    "palette.askai.empty": "在 > 后面输入问题",
    "palette.askai.sub": "单次回答 · 不会进对话记录",
    "palette.askai.streaming": "claude · 思考中…",
    "palette.askai.done": "claude · 回答",
    "palette.newnote.empty": "在 + 后面输入标题",
    "palette.newnote.sub": "在笔记库里创建一条新笔记",
    "palette.kbd.move": "选择",
    "palette.kbd.open": "打开",
    "palette.kbd.newtab": "新标签页",
    "palette.parity": "parity: 每条命令 = CLI · ADR-0008",
    # 命令面板里的命令(每条都对应一条 CLI · ADR-0008)
    "palette.cmd.mining": "立刻抓取所有订阅",
    "palette.cmd.mining.sub": "knowlet mining run-all",
    "palette.cmd.drafts": "审查收件箱",
    "palette.cmd.drafts.sub": "knowlet drafts review",
    "palette.cmd.cards": "复习记忆卡",
    "palette.cmd.cards.sub": "knowlet cards review",
    "palette.cmd.sediment": "把对话存成笔记",
    "palette.cmd.sediment.sub": "knowlet chat sediment",
    "palette.cmd.clearchat": "清空对话",
    "palette.cmd.clearchat.sub": "knowlet chat clear",
    "palette.cmd.profile": "编辑个人资料",
    "palette.cmd.profile.sub": "knowlet profile edit",
    "palette.cmd.newnote": "新建笔记",
    "palette.cmd.newnote.sub": "knowlet notes new",
    # Sidebar(笔记树)
    "sidebar.search.placeholder": "搜索笔记…",
    "sidebar.new.title": "新建笔记",
    "sidebar.empty": "还没有笔记。点 + 新建第一条。",
    "sidebar.loading": "加载中…",
    # Tabs
    "tab.close": "关闭",
    "tab.dirty": "未保存",
    # 编辑器
    "editor.mode.edit": "编辑",
    "editor.mode.split": "双栏",
    "editor.mode.preview": "预览",
    "editor.empty.before": "左栏选一条笔记,或点",
    "editor.empty.after": "新建",
    "editor.placeholder": "开始写… 支持 Markdown。",
    "editor.saving": "保存中…",
    "editor.chars": "{n} 字",
    "editor.savedmeta": "已保存 · UTF-8 · LF",
    # 右栏
    "rail.tab.outline": "大纲",
    "rail.tab.backlinks": "反链",
    "rail.tab.ai": "AI",
    "rail.collapse.title": "折叠",
    "rail.outline.empty": "这条笔记还没有章节标题(用 #、##、### 开头那种)。",
    "rail.backlinks.placeholder": (
        "这一栏会显示「引用了当前笔记的其它笔记」,带句子级预览。"
        "下一阶段(M6.2)实装。"
    ),
    "rail.ai.scope.label": "参考范围",
    "rail.ai.scope.note": "当前笔记",
    "rail.ai.scope.vault": "所有笔记",
    "rail.ai.scope.none": "不参考",
    "rail.ai.clear.title": "清空对话",
    "rail.ai.clear.label": "清空",
    "rail.ai.placeholder": "问点什么 — Enter 发送, Shift+Enter 换行",
    "rail.ai.empty": "问点关于「{title}」的内容。",
    "rail.ai.empty.notitle": "(先选一条笔记)",
    "rail.ai.expand.title": "进入全屏对话",
    "rail.ai.label.you": "你",
    "rail.ai.label.ai": "claude",
    "rail.ai.composer.hint": "⏎ 发送 · ⇧⏎ 换行",
    # 底栏
    "footer.inbox.label": "收件箱",
    "footer.inbox.title": "AI 帮你拣好的待审内容",
    "footer.review.label": "复习",
    "footer.review.title": "今天到期的记忆卡片",
    "footer.feed.label": "订阅",
    "footer.feed.title": "点击立刻抓取最新内容",
    "footer.feed.running": "抓取中…",
    "footer.feed.empty": "(暂无)",
    # 收件箱模态
    "inbox.title": "收件箱",
    "inbox.empty": "收件箱是空的。",
    "inbox.fetched": "抓取于",
    "inbox.savepath": "通过后保存到",
    "inbox.source": "来源",
    "inbox.tags": "标签",
    "inbox.action.discard": "不要",
    "inbox.action.later": "稍后再看",
    "inbox.action.keep": "收入笔记",
    "inbox.done": "收件箱审完了。",
    # 复习(卡片 focus mode)
    "review.title": "复习",
    "review.empty": "今天没有到期的卡片。",
    "review.front": "题面",
    "review.back": "答案",
    "review.reveal": "翻面查看答案",
    "review.fsrs.hint": "FSRS · 翻面后显示下次间隔",
    "review.rate.again": "不记得",
    "review.rate.hard": "勉强想起",
    "review.rate.good": "记起来了",
    "review.rate.easy": "太简单",
    "review.rate.again.title": "完全没记住,从头学一次",
    "review.rate.hard.title": "想了挺久才记起",
    "review.rate.good.title": "顺利记起",
    "review.rate.easy.title": "太简单了,下次推迟很多",
    "review.done": "今天的复习做完了。",
    # Focus mode 通用
    "focus.exit": "退出",
    "focus.prev": "上一条",
    "focus.next": "下一条",
    # Chat focus mode
    "chat.focus.title": "对话",
    "chat.focus.singlesession": "单会话 · 多会话归档下一阶段(M6.4)",
    # 把对话存成笔记(web flow)
    "sediment.web.title": "把这段对话存成笔记",
    "sediment.web.drafting": "AI 整理中…(Opus 大约 25 秒)",
    "sediment.web.field.title": "标题",
    "sediment.web.field.tags": "标签(逗号分隔)",
    "sediment.web.field.body": "正文",
    "sediment.web.cancel": "取消",
    "sediment.web.commit": "保存",
    "sediment.web.required": "标题和正文都得填一下。",
    "sediment.web.saved": "已存为笔记。",
    # 个人资料模态(web)
    "profile.web.title": "个人资料",
    "profile.web.intro": (
        "每次跟 AI 对话时,AI 会先读这份资料,知道你是谁、关心什么、希望它怎么回。随时改。"
    ),
    "profile.web.field.name": "姓名(可选)",
    "profile.web.field.body": "正文(Markdown)",
    "profile.web.cancel": "取消",
    "profile.web.save": "保存",
    "profile.web.saved": "个人资料已保存。",
    # 输入提示
    "prompt.new.title": "新笔记的标题",
    # 抓取(mining)的 toast
    "mining.toast.empty": "抓了 {n} 条 · 没有新内容。",
    "mining.toast.no_drafts": "抓了 {n} 条 · {m} 条新内容但 AI 没整理出有效条目。",
    "mining.toast.success": "抓了 {n} 条 · 整理出 {m} 条等你看。",
    # 对话清空
    "chat.web.cleared": "对话已清空。",
    # 通用
    "modal.close": "关闭",
    # 通用单字
    "ok": "好",
    "yes": "是",
    "no": "否",
}


_CATALOGS: dict[str, dict[str, str]] = {
    "en": _EN,
    "zh": _ZH,
}
