# Knowlet

> [English](./README.en.md) | **中文**

> **会自己整理的个人知识库。**
> *A personal knowledge base that organizes itself.*

Knowlet 是一个先自用、后开源的 AI 长期记忆层 + 减负型 PKM。AI 替你承担总结、分类、沉淀、检索这些低 ROI 的整理工作,你保留意图、思考、判断;同时,任何 AI 工具(Claude / Cursor / 其他)在跟你对话时,都可以从这个知识库主动检索你的私人累积知识 —— 不仅在 knowlet 内可见,也在你所有的 AI 工作流中可见。

> Knowlet 已完成 MVP(M0 端到端 CLI / M1 用户上下文层 / M2 极简 web UI),处于"先自用"阶段,真实使用反馈会驱动后续路线。详见 [ADR-0007](./docs/decisions/0007-mvp-slice.md) 与 [`docs/design/mvp-slice.md`](./docs/design/mvp-slice.md)。

## 快速上手

```bash
# 一次性安装(需要 Python 3.11+;可选 [embed] 拉本地 embedding 模型)
git clone https://github.com/FreeJolan/knowlet.git && cd knowlet
uv venv --python 3.12
uv pip install -e '.[embed]'

# 准备一个 vault(任意目录,推荐放进 iCloud / Syncthing 同步管道)
mkdir ~/my-vault && cd ~/my-vault
knowlet vault init .
knowlet config init       # 引导配置 OpenAI 兼容服务的 base_url / api_key / model
knowlet doctor            # 自检后端 + LLM 工具调用兼容性
knowlet user edit         # (可选)写一份你自己的 profile

# 开始用
knowlet                   # 不带子命令直接进 chat REPL
# 或者浏览器界面
knowlet web               # 默认 http://127.0.0.1:8765
```

LLM 服务可以是任何兼容 OpenAI Chat Completions 协议的端点 —— 官方 OpenAI、OpenRouter、Ollama,或用社区开源 wrapper 把 Claude Code / Codex / Cursor 等工具暴露成 OpenAI 协议。详见 [ADR-0005](./docs/decisions/0005-llm-integration-strategy.md)。

## 升级流程(数据安全)

knowlet 仍在快速迭代(0.0.x)。每次 `git pull` 拉新代码前,**强烈建议先打一份 vault 快照**,出问题随时能恢复:

```bash
cd ~/my-vault
knowlet vault snapshot --label pre-upgrade   # 在 .knowlet/snapshots/ 下生成完整副本

cd ~/path/to/knowlet/source
git pull && uv sync --extra embed             # 拉新代码 + 同步依赖

cd ~/my-vault
knowlet doctor                                # 检查:embedding / index / vault 数据完整性

# 一切正常 → 用一段时间确认稳定 → 删快照
ls .knowlet/snapshots/                        # knowlet vault list-snapshots 也行
rm -rf .knowlet/snapshots/<ts>-pre-upgrade

# 如果出问题 → 一键恢复(会先把当前坏状态再快照一份,所以 reverse 也安全)
knowlet vault restore-snapshot pre-upgrade
knowlet reindex                               # 重建 FTS / 向量索引
```

**保障**:

- Vault 是普通文件夹 — 你随时能 `cp -R` / git commit / Syncthing 备份
- 笔记是 Markdown + YAML frontmatter — 任何编辑器都能读 / 修复
- 写入是原子的(`.tmp` → `rename`),断电不会留半文件
- 删除是软删除(`notes/.trash/`),CLI `knowlet notes restore <id>` 找回
- Note frontmatter 有 `schema_version`(v1 默认),未来 schema 变更不会让旧笔记打不开
- `knowlet doctor` 走一遍每个 Note / Card / Draft / 任务文件,验证 parse 干净

## 核心理念

- **AI 是可选增强,不是必需品** —— 无 AI 时仍是可用的笔记库
- **数据主权在用户** —— 本地优先,Markdown / JSON,可随时打包带走
- **能力插件化 + AI 编排 + 原子执行** —— 代码只暴露原子能力,LLM 编排工作流

详见 [ADR-0002 — 三条核心原则](./docs/decisions/0002-core-principles.md) 与 [ADR-0004 — AI 编排 + 原子执行](./docs/decisions/0004-ai-compose-code-execute.md)。

## 阶段一服务的真实场景

详见 [ADR-0003](./docs/decisions/0003-wedge-pivot-ai-memory-layer.md):

- **A. 研究 / 论文阅读** — 嵌入式 chat 讨论 → AI 草稿 → 用户审查 → 沉淀;后续 AI 对话自动召回
- **B. 信息流订阅与整理** — 用户配置知识挖掘任务 → 定时抓取 + LLM 整理 → 用户审查 → 入库
- **C. 结构化重复记忆 + AI 增强** — 外语词汇 / 专业概念辨析 / 写作批改;SRS 子模块 + AI 按用户上下文调整反馈

三个场景共享同一份用户上下文(目标 / 偏好 / 错误模式 / 词汇掌握),AI 在跨场景间累积理解。

## 文档索引

- [`docs/`](./docs/) — 设计文档总入口
  - [`decisions/`](./docs/decisions/) — 架构决策记录(ADR)
  - [`design/`](./docs/design/) — 活文档:架构 / 用户 / 组织策略 / 技术栈 / 语音
  - [`roadmap/`](./docs/roadmap/) — 阶段路线图

## License

[MIT](./LICENSE)
