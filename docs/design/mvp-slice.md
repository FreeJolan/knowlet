# MVP 切片实现规划

> [English](./mvp-slice.en.md) | **中文**

> 活文档。本文是 [ADR-0007](../decisions/0007-mvp-slice.md) 在工程层面的展开,会随 MVP 实现进度持续更新。

## 范围速览

只做**场景 A(研究 / 论文阅读)**的端到端最小可用版。详见 [ADR-0007 — MVP 范围](../decisions/0007-mvp-slice.md#mvp-范围)。

## 关键库选型

复用成熟库 + 自写架构层逻辑(见"不造轮子"判断标准):

| 用途 | 库 | 自造 / 复用 | 理由 |
|---|---|---|---|
| LLM 调用 | `openai` 官方 SDK | 复用 | OpenAI 兼容协议,直接打 Anthropic / OpenRouter / Ollama |
| Embedding(本地) | `sentence-transformers` 或 `fastembed` | 复用 | 本地推理,零额外配置 |
| 向量库 | `sqlite-vec` Python 绑定 | 复用 | 与 ADR-0006 一致,零外部依赖 |
| 全文索引 | SQLite 内置 FTS5 | 复用 | 零依赖,RAG hybrid retrieval 必备 |
| Markdown 解析 | `mistune` | 复用 | 高性能,API 简洁 |
| Frontmatter | `python-frontmatter` | 复用 | 标准实现 |
| 文件监听 | `watchdog` | 复用 | 行业标准 |
| Schema 校验 | `pydantic` v2 | 复用 | LLM tool schema + entity schema 都用 |
| ULID | `python-ulid` | 复用 | 简单,跨设备无冲突 |
| CLI 框架 | `typer` + `rich` | 复用 | 声明式 + 漂亮输出 |
| 配置 | `pydantic-settings` + TOML | 复用 | 类型安全 |
| HTTP 客户端 | `httpx` | 复用 | 现代,async 原生 |
| MCP | 官方 `mcp` Python SDK | 复用 | 为后续 MCP server 形态预留 |
| **Text splitter** | 自写(~30 行 sliding window + overlap) | **自造** | 比拉 LangChain 干净 |
| **RAG 主流程** | 自写(~80 行) | **自造** | 跟原子能力 + LLM 编排哲学高度耦合,无现成框架 |
| **原子能力 tool 实现** | 自写,按 MCP schema | **自造** | knowlet 架构核心,无现成 |
| **AI 草稿 + 人工审查流程** | 自写 | **自造** | 业务逻辑,无现成 |

## 模块划分(初步)

```
knowlet/                    Python package
├── core/
│   ├── vault.py            vault 读写、file watcher
│   ├── note.py             Note 实体 + frontmatter 处理
│   ├── embedding.py        Embedding 接口(默认 sentence-transformers)
│   ├── retrieval.py        全文 + 向量混合检索
│   ├── splitter.py         自写文本切分
│   ├── llm.py              OpenAI 兼容客户端封装
│   └── tools/              原子能力(MCP-style schema)
│       ├── _registry.py    tool 注册与分发
│       ├── search_notes.py
│       ├── get_note.py
│       ├── create_note.py
│       └── ...
├── chat/
│   ├── session.py          chat session 状态机 + tool 调度
│   └── sediment.py         AI 草稿 + 用户审查流程
├── cli/
│   └── main.py             typer entry
├── config.py               配置加载(pydantic-settings)
└── __main__.py             python -m knowlet 入口
```

## 数据布局(MVP 范围内)

```
<vault>/                          用户选定目录,放在 iCloud / Syncthing 之下
├── notes/<id>-<slug>.md          MVP 唯一的实体类型
└── .knowlet/
    ├── index.sqlite              FTS5 + sqlite-vec 共用一个 DB
    ├── conversations/            对话原始 payload(30 天保留,见 ADR-0006)
    ├── backups/                  关键文件备份
    └── config.toml               LLM endpoint / vault path / embedding 模型选择
```

MVP 不创建 `cards/` `mistakes/` `sources/` `users/` 这些目录;它们在阶段一其他切片才需要。

## 第一个里程碑(M0)

具体可验证的行为(从用户视角):

```
1. knowlet config init
   → 引导用户填 LLM endpoint URL + API key + 模型名,生成 .knowlet/config.toml

2. knowlet vault init <path>
   → 在指定目录创建 vault 结构(notes/ + .knowlet/)
   → 初始化 SQLite + sqlite-vec 表

3. knowlet chat
   → 启动 chat REPL(Rich-rendered)
   → 用户提问 → LLM 自动调用 search_notes tool
     - 命中:答案融合本地 Note + 通用知识
     - 未命中:答案基于通用知识,提示"未在本地找到相关内容"

4. chat 中输入 :save 命令
   → LLM 生成本次对话的 Note 草稿(标题 + 摘要 + 关键问答 + tags)
   → 显示 diff 给用户:y(接受) / n(丢弃) / e(打开 $EDITOR 编辑)
   → 接受后 Note 落入 notes/<ulid>-<slug>.md,触发增量索引

5. knowlet ls [--recent]
   → 列出 vault 中的 Note(默认按 created_at 倒序)

6. 退出 chat 后再次 knowlet chat,新 session
   → 用户问相关问题 → LLM 通过 search_notes 召回上次沉淀的 Note → 答案带历史结论

7. 自己用一周左右,主观判断"用着不烦躁"
```

打通这 7 步即 MVP 跑通(对应 ADR-0007 验证标准 1-5)。

## 关键 prompt(初稿)

LLM-driven retrieval 的 system prompt 设计原则:

- 明确告知 LLM 它有哪些 tools 可用
- 鼓励它**在回答前主动检索**(默认行为)
- 指导它**在何时不检索**(明显是闲聊或通用知识问题)
- 提示它在引用本地 Note 时**标注出处**(回应 ADR-0003 透明度承诺)

第一版具体 prompt 在实现阶段确定,可在原型期反复调整。

## 错误处理与日志策略

- LLM tool call 失败 → tool 返回结构化错误 + 建议修复方式(ADR-0004 第 4 条约束),让 LLM 自动恢复
- 文件 IO 失败 → 友好错误信息 + 建议(检查权限 / 磁盘空间)
- LLM API 失败(网络 / 认证 / 限速)→ 重试一次,失败则提示用户检查配置
- 日志级别:默认 INFO,可通过 `--verbose` 切到 DEBUG(显示所有 tool call)
- 透明度:UI 始终能看到"LLM 调了哪些 tool、参数、结果"(ADR-0009 透明度承诺的 CLI 实现)

## 还未敲定的细节(原型期决定)

- Embedding 模型具体选哪个(`all-MiniLM-L6-v2` vs `multilingual-e5-small` vs 其他)—— 中英混合场景需要测试
- 向量切块的具体策略(段落级 vs 固定 token 数 vs 语义切块)—— 影响 RAG 命中率
- chunk size 与 overlap 数值
- 检索的 hybrid 权重(BM25 与向量得分的融合比例)
- chat REPL 的命令清单(`:save` / `:undo` / `:show` 等)
- 第一版 system prompt 文本

这些都是细节,实现时迭代决定,不影响整体架构。

## 后续扩展锚点(M0 之后)

按需求自然出现顺序,不强求:

- M1: 加 `users/me.md` + LLM 注入用户上下文
- M2: 简单 web UI(FastAPI + 静态页),取代 CLI 主入口
- M3: Card 实体 + FSRS SRS 子模块(进入场景 C)
- M4: 知识挖掘任务(进入场景 B)
- M5: Tauri 桌面壳 + 移动 PWA

每一步进入路线图前,通过 [`../roadmap/`](../roadmap/) 的"特性优先级原则"4 问。
