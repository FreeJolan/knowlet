# 架构图

> [English](./architecture-diagrams.en.md) | **中文**

> 活文档。两张图反映 2026-05-02 当下形态(M6 + ADR-0013/0014)。技术架构图描述代码 / 模块 / 数据流;产品架构图描述用户视角的 lane / 概念 / 触达面。两者搭配看。

---

## 一、技术架构图

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                                  USER INTERFACES                                  │
│  ┌─────────────────────┐    ┌─────────────────────┐    ┌─────────────────────┐  │
│  │  CLI (terminal)     │    │  Web SPA            │    │  Future: Tauri      │  │
│  │  Typer · Rich       │    │  Alpine · Tailwind  │    │  desktop shell      │  │
│  │  REPL chat (`:`)    │    │  Split.js · marked  │    │  (M9+,同 web/static) │  │
│  └──────────┬──────────┘    └──────────┬──────────┘    └─────────────────────┘  │
└─────────────┼──────────────────────────┼──────────────────────────────────────────┘
              │ direct import             │ HTTP / SSE
              ▼                           ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│              ADAPTERS (thin shells · ADR-0008 parity)                              │
│                                                                                    │
│  ┌──────────────────────────┐    ┌──────────────────────────────────────────┐    │
│  │  knowlet/cli/             │    │  knowlet/web/server.py (FastAPI)         │    │
│  │  · main.py (302 lines)    │    │  /api/health · /notes · /chat/turn       │    │
│  │  · vault, config, user,   │    │  /chat/stream · /chat/sessions/* (M6.4)  │    │
│  │    cards, mining, drafts  │    │  /chat/ask-once · /system/reindex        │    │
│  │  · chat_repl              │    │  /system/doctor · /drafts · /cards       │    │
│  │  · _common · _doctor      │    │  /mining · /profile                      │    │
│  └────────────┬──────────────┘    └────────────┬─────────────────────────────┘    │
└───────────────┼─────────────────────────────────┼────────────────────────────────┘
                │                                 │
                └──────────────┬──────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│              ORCHESTRATION  (knowlet/chat/)                                        │
│                                                                                    │
│   bootstrap.py  →  ChatRuntime                                                     │
│                    ├─ vault, config, backend, index                                │
│                    ├─ llm, registry, ctx                                           │
│                    ├─ session: ChatSession (history, user_turn_stream)             │
│                    ├─ conversations: ConversationStore   (M6.4)                    │
│                    └─ active_conversation: Conversation                            │
│                                                                                    │
│   session.py        ChatSession.user_turn / user_turn_stream → tool loop           │
│   prompts.py        CHAT_SYSTEM_PROMPT / SEDIMENT_PROMPT                           │
│   sediment.py       conversation history → Note draft (JSON)                       │
│   conversation_     CRUD over <vault>/.knowlet/conversations/                      │
│     store.py                                                                       │
└──────────────────────────────────┬─────────────────────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│              CORE  (knowlet/core/  ·  single source of truth · no UI code)         │
│                                                                                    │
│   ┌───────────────────────┐  ┌────────────────────────┐  ┌────────────────────┐  │
│   │  ENTITIES             │  │  STORAGE / PERSISTENCE │  │  EXTERNAL          │  │
│   │  note.py              │  │  vault.py              │  │  llm.py            │  │
│   │  card.py              │  │   atomic write +       │  │   OpenAI-compat    │  │
│   │  drafts.py (Draft)    │  │   backups              │  │   client           │  │
│   │  user_profile.py      │  │  card_store.py         │  │  embedding.py      │  │
│   │  mining/task.py       │  │  drafts.py (Store +    │  │   sentence-trans   │  │
│   │   (MiningTask,        │  │    archive)            │  │   formers / dummy  │  │
│   │    SourceSpec)        │  │  mining/task_store.py  │  │                    │  │
│   │                       │  │  index.py              │  │                    │  │
│   │                       │  │   SQLite + FTS5 +      │  │                    │  │
│   │                       │  │   sqlite-vec           │  │                    │  │
│   │                       │  │   (per-thread conn)    │  │                    │  │
│   └───────────────────────┘  └────────────────────────┘  └────────────────────┘  │
│                                                                                    │
│   ┌──────────────────────────────────────────────────────────────────────────┐    │
│   │  TOOLS  (LLM tool-calling, OpenAI shape; ADR-0004 future MCP adapter)    │    │
│   │  _registry.py  +                                                         │    │
│   │  search_notes · get_note · list_recent_notes · create_card ·             │    │
│   │  list_due_cards · get_card · review_card · list_mining_tasks ·           │    │
│   │  run_mining_task · list_drafts · get_draft · approve_draft ·             │    │
│   │  reject_draft · get_user_profile                                         │    │
│   └──────────────────────────────────────────────────────────────────────────┘    │
│                                                                                    │
│   ┌──────────────────────────────────────────────────────────────────────────┐    │
│   │  MINING PIPELINE                                                          │    │
│   │  scheduler (APScheduler) → fetch (RSS / URL) → extractor (LLM) →         │    │
│   │  drafts/ → user reviews → notes/ + index                                  │    │
│   │  + max_items_per_run (B2) + max_keep archive (M6.5)                      │    │
│   └──────────────────────────────────────────────────────────────────────────┘    │
│                                                                                    │
│   ┌──────────────────────────────────────────────────────────────────────────┐    │
│   │  CROSS-CUTTING                                                            │    │
│   │  i18n (contextvars · EN/ZH catalogs) · _logging (rotating file handler) ·│    │
│   │  events · splitter · fsrs_wrap                                           │    │
│   └──────────────────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────┬─────────────────────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│              ON-DISK VAULT  (user-owned files · ADR-0006)                          │
│                                                                                    │
│   <vault>/                                                                         │
│     ├── notes/<ulid>.md           ← B3:ULID-only filename · iCloud-safe           │
│     ├── drafts/<id>-<slug>.md     ← AI-extracted, pending review                  │
│     │     └── .archive/            ← M6.5 max_keep soft-archive                   │
│     ├── cards/<ulid>.md            ← FSRS state in frontmatter                    │
│     ├── tasks/<id>-<slug>.md       ← mining task config                           │
│     ├── users/me.md                ← user profile                                 │
│     └── .knowlet/                                                                  │
│         ├── config.toml            ← LLM endpoint, embedding, language            │
│         ├── index.sqlite           ← FTS5 + sqlite-vec, derived (重建机制)         │
│         ├── conversations/         ← M6.4 multi-session chat                      │
│         ├── quizzes/               ← ADR-0014 future, M7.4                        │
│         ├── mining/                ← seen-set per task                            │
│         ├── backups/               ← pre-overwrite copies                         │
│         └── knowlet.log            ← rotating log                                 │
└──────────────────────────────────────────────────────────────────────────────────┘
```

### 关键约束

| 维度 | 约束 |
|---|---|
| 单源真理 | core/ 是唯一业务逻辑;cli / web / 未来 desktop 都是薄壳(ADR-0008) |
| 流式接口 | `ChatSession.user_turn_stream` 是单一 streaming 来源;web SSE / CLI REPL 都消费同一事件流(ADR-0008) |
| 工具形态 | OpenAI function-calling shape;未来 MCP 走独立 adapter(ADR-0004 修订) |
| 数据主权 | 用户所有内容是文件系统上的 Markdown / JSON;`.knowlet/` 派生数据可重建(ADR-0006) |
| 并发 | per-thread SQLite connection · WAL · busy_timeout 5s(B1) |
| AI 可选 | api_key 为空时,backend 启动正常 / Note CRUD 工作 / chat-类入口隐藏(ADR-0012) |

---

## 二、产品架构图

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                                    USER                                           │
└──────────────────────────────────┬─────────────────────────────────────────────────┘
                                   │
        ┌──────────────────────────┼──────────────────────────────┐
        │                          │                              │
        ▼                          ▼                              ▼
   ┌────────────┐            ┌────────────┐                ┌────────────┐
   │  Lane A    │            │  Lane B    │                │  Lane C    │
   │  KNOWLEDGE │            │  AI CHAT   │                │  INGEST    │
   └────────────┘            └────────────┘                └────────────┘

┌──────────────────────────────────────────────────────────────────────────────────┐
│  Lane A — KNOWLEDGE  (notes-app 身份 · ADR-0012)                                   │
│  ────────────────────────────────────────────                                      │
│  概念   Note · Tag · Folder(M7.0)· Backlink(M7.0)                                │
│  能力   create / read / edit / delete(M7.0)/ search / tabs / outline / preview   │
│  触达   左栏文件树 · 中栏编辑器 · 右栏 Outline · Cmd+P 快速跳转                     │
│  存储   <vault>/notes/<ulid>.md(frontmatter + Markdown,B3 ULID-only)              │
│                                                                                    │
│  Lane B — AI CONVERSATION  (wedge 差异化 · ADR-0003 / 0012)                        │
│  ─────────────────────────────────────────────                                     │
│  概念   Conversation · Session · Tool call · Reference · Sediment draft           │
│  能力   多轮 chat 调用 vault tools · scope toggle(note/vault/none)·              │
│         multi-session(M6.4)· auto-title · sediment 对话 → Note ·                  │
│         一次性 ask-AI(palette `>`)                                                │
│  触达   右栏 AI dock · Chat focus(`Cmd+Shift+C`)· Cmd+K palette                   │
│  存储   <vault>/.knowlet/conversations/<ulid>.json                                 │
│                                                                                    │
│  Lane C — AI INGESTION  (订阅 / mining)                                            │
│  ─────────────────────────────────────                                             │
│  概念   Mining task · Source · Item · Draft · Inbox                               │
│  能力   定时 RSS / URL 抓取 · LLM 抽取 · max_items_per_run(B2)·                  │
│         max_keep 软归档(M6.5)· 用户审查(approve/reject/skip)                    │
│  触达   底栏 Drafts icon · Drafts focus(`Cmd+Shift+D`)·                          │
│         CLI `mining add/list/run/reset` · palette `立刻抓取所有订阅`               │
│  存储   <vault>/drafts/, tasks/, .knowlet/mining/seen                             │
└──────────────────────────────────────────────────────────────────────────────────┘

      ┌──────────────────────────────────────┐
      │  Lane D                               │
      │  ACTIVE RECALL                        │
      └──────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────────────┐
│  Lane D — ACTIVE RECALL  (Cards / Quiz · ADR-0014)                                 │
│  ────────────────────────────────────────────                                      │
│  概念   Card · Due/Review · Quiz session(M7.4)· Reflux                           │
│  能力   FSRS 调度 · 自评(1-4)· scope-driven quiz(M7.4)· quiz 错题回流 Card     │
│  触达   底栏 Cards icon · Cards focus(`Cmd+Shift+R`)·                            │
│         Quiz focus(`Cmd+Shift+Q`,M7.4)· palette `复习记忆卡` / `考我`            │
│  存储   <vault>/cards/<ulid>.md(FSRS state)·                                     │
│         <vault>/.knowlet/quizzes/<ulid>.json(M7.4)                                │
└──────────────────────────────────────────────────────────────────────────────────┘

           ┌───────────────────────────────────────────────────────┐
           │  Cross-lane                                            │
           │  KNOWLEDGE GOVERNANCE                                  │
           └───────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────────────┐
│  Cross-lane — KNOWLEDGE GOVERNANCE  (碎片化治理 · ADR-0013 · M7-M8)                │
│  ─────────────────────────────────────────────────────────                         │
│  概念   Similarity · Cluster · Near-duplicate · Aging · Digest                    │
│  Layer A 录入端 ambient(M7)— 新建 Note 时显示 top-3 相似 Note,默认动作仍是新建    │
│  Layer B 被动结构化(M8)— 后台算 cluster / 近重复 / 孤儿 / 衰老,只算不动        │
│  Layer C 定期摘要(M8)— Sunday newspaper 调性,周期用户可配,无 unread badge      │
│                                                                                    │
│  契约   AI 不自动改 IA — 任何变更 vault 结构(目录 / 内容 / tag)的动作            │
│         必须有用户的 explicit click,不能靠默认值或后台任务完成(ADR-0013 §1)       │
└──────────────────────────────────────────────────────────────────────────────────┘
```

### Lane × Surface 矩阵

|  | 左栏 | 中栏 | 右栏 | 底栏 | Cmd+K | Focus | 模态 |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| Lane A 知识 | ✓ tree | ✓ editor | ✓ Outline / Backlinks(M7.0) | — | ✓ jump | — | — |
| Lane B AI 对话 | — | — | ✓ AI dock | — | ✓ `>` ask-once | ✓ chat | ✓ sediment |
| Lane C 采集 | — | — | — | ✓ Drafts icon | ✓ feed cmd | ✓ drafts | — |
| Lane D 复习 | — | — | — | ✓ Cards icon | ✓ cards cmd | ✓ cards / quiz(M7.4) | — |
| Cross-lane 治理 | — | (Layer A 入口) | (Layer B Map) | — | — | (待 M8 决定) | — |

### ADR 映射

| 约束 / 设计 | ADR |
|---|---|
| 三条核心原则(数据主权 / AI 可选 / 插件化) | [ADR-0002](../decisions/0002-core-principles.md) |
| Wedge:AI 长期记忆层 | [ADR-0003](../decisions/0003-wedge-pivot-ai-memory-layer.md) |
| AI 编排 + 原子执行 + future MCP adapter | [ADR-0004](../decisions/0004-ai-compose-code-execute.md) |
| LLM 接入策略(OpenAI-compat) | [ADR-0005](../decisions/0005-llm-integration-strategy.md) |
| 存储 / 同步 / 重建机制 | [ADR-0006](../decisions/0006-storage-and-sync.md) |
| CLI / UI 平价开发纪律 + UI 单测扩展 | [ADR-0008](../decisions/0008-cli-parity-discipline.md) |
| Mining tasks + drafts + 调度 | [ADR-0009](../decisions/0009-mining-tasks-and-drafts.md) |
| i18n(英文默认,EN+ZH) | [ADR-0010](../decisions/0010-i18n.md) |
| Web UI 重设计:三栏 + Focus modes + Cmd+K | [ADR-0011](../decisions/0011-web-ui-redesign.md) |
| 笔记本位 / AI 是可选增强 | [ADR-0012](../decisions/0012-notes-first-ai-optional.md) |
| 知识管理契约 / 碎片化治理三层 | [ADR-0013](../decisions/0013-knowledge-management-contract.md) |
| 笔记考试模式 / scope-driven 主动召回 | [ADR-0014](../decisions/0014-note-quiz-mode.md) |
