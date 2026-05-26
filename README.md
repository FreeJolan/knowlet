# Knowlet

> [English](./README.en.md) | **中文**

> **会自己整理的个人知识库。**
> *A personal knowledge base that organizes itself.*

Knowlet 是一个先自用、后开源的 AI 长期记忆层 + 减负型 PKM。AI 替你承担总结、分类、沉淀、检索这些低 ROI 的整理工作,你保留意图、思考、判断;同时,任何 AI 工具(Codex / Cursor / 其他)在跟你对话时,都可以从这个知识库主动检索你的私人累积知识 —— 不仅在 knowlet 内可见,也在你所有的 AI 工作流中可见。

> Knowlet 已完成 MVP(M0 端到端 CLI / M1 用户上下文层 / M2 极简 web UI),处于"先自用"阶段,真实使用反馈会驱动后续路线。详见 [ADR-0007](./docs/decisions/0007-mvp-slice.md) 与 [`docs/design/mvp-slice.md`](./docs/design/mvp-slice.md)。

## 快速上手

```bash
# 安装(需要 Python 3.11+;可选 [embed] 拉本地 embedding 模型)
git clone https://github.com/FreeJolan/knowlet.git && cd knowlet
uv sync --extra embed                  # 同步依赖到 project venv
uv tool install -e .                   # 把 `knowlet` 装到 PATH(推荐,任何目录可用)

# 准备一个 vault(任意目录,推荐放进 iCloud / Syncthing 同步管道)
mkdir ~/my-vault && cd ~/my-vault
knowlet vault init .
knowlet config init       # 引导配置 OpenAI 兼容服务的 base_url / api_key / model
knowlet doctor            # 自检后端 + LLM 工具调用兼容性
knowlet user edit         # (可选)写一份你自己的 profile

# 开始用
knowlet                   # 不带子命令直接进 chat REPL
knowlet web               # 浏览器界面 — http://127.0.0.1:8765
```

> **不想全局装?** `uv tool install` 那行可以省。从源码目录用 `uv run` 前缀替代:
> ```bash
> cd /path/to/knowlet
> KNOWLET_VAULT=~/my-vault uv run knowlet web --port 8765
> KNOWLET_VAULT=~/my-vault uv run knowlet vault snapshot --label pre-upgrade
> ```
> 或者一次性 `source .venv/bin/activate` 在当前 shell 用裸 `knowlet` 命令(`deactivate` 退出)。
>
> **升级方法**(所有路径通用):`cd /path/to/knowlet && git pull && uv sync --extra embed && uv tool install -e . --force`(末尾这条只 `uv tool install` 路径需要)。

默认 LLM 路径是本机 `cliproxyapi` + Codex/GPT 5.5:`http://127.0.0.1:8317/v1` + `gpt-5.5`。LLM 服务仍可以是任何兼容 OpenAI Chat Completions 协议的端点 —— 官方 OpenAI、OpenRouter、Ollama,或用社区 wrapper 把 Codex / Cursor 类工具暴露成 OpenAI 协议。详见 [ADR-0005](./docs/decisions/0005-llm-integration-strategy.md)。

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

## 定位:用户拥有,LLM 提案

> **任何进入 vault 的内容都过审批管线 —— LLM 永远不自动落库。**

knowlet 的 chat 沉淀、mining draft、URL 捕获、source ingest 都走同一条 review queue:LLM 生产**候选**(草稿 / 摘要 / 链接建议 / IA 提案),用户审批后才进 vault。LLM 不会自动合并同义概念、自动归档老笔记、或在你不知情时改写已有内容。

**用 Tiago Forte 的 CODE 框架对比 "让 LLM 替你管 wiki" 的模式**(如 [Karpathy LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)):

| 阶段 | "LLM 替你管 wiki" 模式 | knowlet |
|---|---|---|
| Capture(收集)| 用户 + AI 抓取 | 用户 + AI 抓取 |
| **Organize**(组织)| **LLM 自动决定 IA** | **用户拥有**;AI 仅在用户主动触发时给候选 |
| **Distill**(提炼)| **LLM 自动写笔记主体** | **AI 只产候选 → review queue → 用户审批** |
| Express(表达)| 用户(查询 / 生成 slides)| 用户(写 / 用 Quiz / Sediment)|

knowlet 的差异本质是 **不自动化 Organize、Distill 永远走审批**。在跨多年 / 多场景 / 多 LLM 后端的长期使用下,可解释性 / 可控性比维护成本节省更重要。

详见 [ADR-0013](./docs/decisions/0013-knowledge-management-contract.md)(契约)+ [ADR-0023](./docs/decisions/0023-llm-wiki-comparison-and-takeaways.md)(对比与吸纳)+ [ADR-0024](./docs/decisions/0024-ai-assist-envelope.md)(AI 协助边界)。

## 阶段一服务的真实场景

详见 [ADR-0003](./docs/decisions/0003-wedge-pivot-ai-memory-layer.md):

- **A. 研究 / 论文阅读** — 嵌入式 chat 讨论 → AI 草稿 → 用户审查 → 沉淀;后续 AI 对话自动召回
- **B. 信息流订阅与整理** — 用户配置知识挖掘任务 → 定时抓取 + LLM 整理 → 用户审查 → 入库
- **C. 结构化重复记忆 + AI 增强** — 外语词汇 / 专业概念辨析 / 写作批改;SRS 子模块 + AI 按用户上下文调整反馈

三个场景共享同一份用户上下文(目标 / 偏好 / 错误模式 / 词汇掌握),AI 在跨场景间累积理解。

## 文档索引

- [`AGENTS.md`](./AGENTS.md) — **AI agent 协作准则**(Codex / Cursor / 其他 agent 进项目第一件事就是读这个)。包含工程纪律、UI 设计强制工作流、roadmap 读取顺序、不造轮子原则等。`CLAUDE.md` 仅保留作旧工具兼容入口。
- [`docs/`](./docs/) — 设计文档总入口
  - [`decisions/`](./docs/decisions/) — 架构决策记录(ADR)
  - [`design/`](./docs/design/) — 活文档:架构 / 用户 / 组织策略 / 技术栈 / 语音
  - [`roadmap/`](./docs/roadmap/) — 阶段路线图

## License

[MIT](./LICENSE)
