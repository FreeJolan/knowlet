# 0009 — 知识挖掘任务 + 草稿审查队列

> [English](./0009-mining-tasks-and-drafts.en.md) | **中文**

- Status: Accepted
- Date: 2026-05-01

## Context

[ADR-0003](./0003-wedge-pivot-ai-memory-layer.md) 把"信息流订阅与整理"列为阶段一三个真实场景之一(场景 B):

> 用户配置"知识挖掘任务"(频率 + 来源约束 + Prompt) → 定时执行 → 抓取过程透明可追溯 → 生成多条原子 Note + 索引 Note → 用户审查后入库。

M0–M3 完成了场景 A(论文阅读)和场景 C(SRS),但场景 B 一直没有动。M4 把场景 B 的最小可用切片落地。

设计上有几个分叉一开始不明显,需要在 ADR 里钉死,以免后续 agent 重新争论:

- 调度后端选什么(自带 daemon 内调度 / 系统级 cron / 完全手动)
- 来源类型范围(RSS / URL / Web 抓取 / 邮件 / Webhook 各成本与价值)
- "AI 草稿 → 用户审查 → Note 入库"的物理表现(单独 drafts 目录 / inbox 标签 / 隐藏队列)
- 任务定义在哪里(vault 内 Markdown / vault 外 config / 数据库)
- 跨 run 的"已见"状态怎么持久化(避免重复抓同一篇)

## Decision

### 1. 调度后端:**APScheduler in-daemon + 手动 override 始终可用**

- `knowlet web` 启动时,FastAPI lifespan 拉起一个 `APScheduler.BackgroundScheduler`(`UTC` 时区)。
- 每个 task 的 `schedule.every` / `schedule.cron` 翻译成 `IntervalTrigger` / `CronTrigger`。
- `misfire_grace_time=300`,`coalesce=True`,`max_instances=1` —— daemon 重启 / 短暂离线后不会爆抓。
- **手动触发始终可用**:`knowlet mining run <id>` 与 `knowlet mining run-all` 不依赖 scheduler;用户可以用系统 cron 把 `knowlet mining run-all` 套一层做兜底。
- `knowlet chat`(非 daemon)模式不启动 scheduler。

**为什么不用系统级 launchd / cron:** macOS / Linux 实现不同、权限边界大、debug 困难;且违反"打包安装就能用"的承诺。

**为什么不只做手动触发:** 场景 B 字面要求"定时执行";否则跟把 RSS 链接收藏到收藏夹无差别,产品价值打折。

### 2. 来源类型范围(M4):**RSS / Atom + 单 URL fetch**

- **RSS / Atom**:`feedparser` 解析,每个 entry 是一个 `SourceItem`。
- **URL**:`httpx` GET → `trafilatura.extract` 抽正文,作为单 `SourceItem`。
- **明确不做**(M4 范围外):
  - 网页爬虫(多页 / 登录态 / JS 渲染) —— 每站要写适配器,M4 不值
  - 邮件 IMAP —— 认证复杂,价值面窄
  - Webhook —— 需要常驻 server 接收,跟当前的 daemon 模式正交但范围更大,留 M5+ 再说

来源约束设计:**统一返回 `SourceItem` 列表**,runner / extractor 不感知来源类型。新增类型时只增加 `sources.py` 内一个 `_fetch_<type>` 函数。

### 3. 草稿落点:**`<vault>/drafts/<id>-<slug>.md`**

每条草稿是一份独立的 Markdown(带 frontmatter,`status: draft`)。

- **优:** 跟 Note 同形态,用户编辑器(Obsidian / VS Code 等)直接可见可改;ADR-0002 数据主权字面成立;跟 ADR-0003 "AI 草稿 + 人工审查"逐字对齐。
- **审查动作:**
  - **approve** → 把 Draft 投影成 Note(`Draft.to_note()` 保留 id / title / body / tags / source),写入 `<vault>/notes/`,`Index.upsert_note` 索引,然后删除 drafts/ 里的源文件。
  - **reject** → 直接删除 drafts/ 文件;**已见的 source item id 仍留在 seen-set**,不会重新抓取。
- **不进入索引:** drafts 目录的内容**不**走 FTS5 / 向量索引;只有 approve 后的 Note 才进入 RAG 检索。理由:草稿是"待定"的,放进检索会污染答案;用户主动审查通过的内容才是知识库的一部分。

**为什么不用 `tags: [inbox]`:** 草稿与 Note 混在 `notes/` 里,检索时被一起拉出来污染答案;且"未审查"状态藏在 tag 里,用户编辑器很容易跟其它 tag 混,review 状态丢失风险高。

**为什么不用隐藏 JSON 队列(`.knowlet/pending/`):** 隐藏目录用户编辑器看不到,违反 ADR-0002 的"用户随时可以打包带走"承诺;且隐藏队列导致 review UX 必须靠 knowlet 工具实现,跟"零强制学习曲线"冲突。

### 4. 任务定义:**`<vault>/tasks/<id>-<slug>.md`,frontmatter 配置 + body 描述**

```yaml
---
id: 01HX...
name: AI papers daily
enabled: true
schedule:
  every: "1h"      # 或 cron: "0 9 * * *"
sources:
  - rss: "https://arxiv.org/rss/cs.AI"
  - url: "https://example.com/blog"
prompt: |
  Summarize each item in 2-3 sentences ...
created_at: ...
updated_at: ...
---
optional Markdown body — 这是为什么这个 task 存在的说明
```

- **跟 vault 走**:任务是用户的配置,放进 iCloud / Syncthing 后能跨设备使用同一组任务。
- **frontmatter + body**:用户编辑器友好;熟悉 YAML / 不熟悉 YAML 都能改。
- **不放进 `.knowlet/`**:那是 knowlet 的派生状态(索引、对话日志),不是用户拥有的内容。

### 5. 跨 run 的"已见"状态:**`<vault>/.knowlet/mining/<task_id>.json`**

```json
{ "seen": ["<item_id_1>", "<item_id_2>", ...] }
```

- 每个 task 一份;item_id 优先用 `entry.id`(RSS),其次 link,最后 URL。
- 失败的 item 也加入 seen-set,避免无限重试同一坏 item。
- 文件在 `.knowlet/`(派生状态),用户跨设备同步**不强制**:不同设备各自维护 seen-set 也能工作(代价是首次同步可能重复一批草稿,跑一次 reject 即可)。
- **不放进 vault 顶层**(用户内容),也不放进 SQLite(派生状态用 JSON 更易调试 + 可回填)。

### 6. LLM extraction 的 prompt 形态

跟 [ADR-0008](./0008-cli-parity-discipline.md)前后由 `chat/sediment.py` 总结的经验一致:**整段抽取 prompt 折进 user message**,不依赖 `role: "system"`(某些 OpenAI 兼容代理会忽略 system prompt 的角色指令)。

每个 source item 走一次 LLM 调用(不批量),换取:
- 错误隔离:一条 item 的 prompt 失败不影响其它
- token 边界稳定:不同 item 不抢 context 长度
- Provenance 清晰:每条 draft 对应一条 source

代价是 N 倍 LLM 调用;在 RSS feed 数十条入库的常态下可接受。后续如果要批量化,可在 extractor 层加一个 `batch_size` 参数(M5+ 再说)。

## Consequences

### 好处

- **场景 B 真正可用**。daemon 开着 → 用户晚上回来看到 inbox 里几条 draft → 审查 → 入库。这是产品级别的"AI 替我整理"承诺第一次具体实现。
- **跟 ADR-0008 纪律完全自洽**。6 个原子工具(`list_mining_tasks / run_mining_task / list_drafts / get_draft / approve_draft / reject_draft`)是后端函数的薄壳;CLI / slash / web 都直接 call 它们;LLM 通过 tool-call 自然编排"运行任务 → 列出草稿 → 列出 → 审查"的流程。
- **架构防腐**。Drafts 不进 RAG 索引,审查通过后才入库 —— 跟"AI 草稿 + 人工审查"的承诺字面一致,没有捷径。
- **手动 + 自动双轨**。daemon 不在线时,用户也能用 cron 套 `knowlet mining run-all`,不丢失场景 B 的能力。
- **测试覆盖好做**。Source 抓取被 monkeypatch 替换、LLM 用 stub —— `runner.run_task` 是纯函数式的(状态全在 vault 文件 + seen-set JSON),容易断言。

### 代价 / 约束

- **APScheduler 引入**(中量级 dep,~1MB,纯 Python)。比手动方案(0 dep)重,但比 launchd 集成的脏度低很多;可接受。
- **daemon 离线期间任务停摆**。`misfire_grace_time` 决定要不要补抓;我们选了"短暂离线 OK,长时间离线就让下个周期接手",这对 RSS / URL fetch 场景合理(下次跑会拉到所有新内容);对"必须不漏一次"的场景不适合。后续如果要"daemon 启动时检查上次跑过没,如果错过就立刻补",可以加 `misfire_grace_time=None` 或显式 catchup 逻辑。
- **每条 item 一次 LLM 调用**,RSS feed 大量更新时 token 成本可观。MVP 接受;批量化是 M5+ 优化点。
- **drafts 不进索引**。如果用户草稿堆积想"在草稿里搜索什么时候哪个 task 处理过 RAG",当前不支持。可加一个 `search_drafts(query)` 工具,但 M4 不做(草稿生命周期短,搜索价值低)。
- **Cron 表达式只支持标准 5 字段**。`@daily / @weekly` 这类宏不支持;APScheduler 的 `CronTrigger.from_crontab` 不接 macros。需要的话可以在 task 加载时做一次预处理,M4 不做。
- **任务编辑后必须 reload 调度器**(CLI / web 通过 `MiningScheduler.reload()`),否则 daemon 内仍跑老的 trigger。Web 端 PUT/POST 自动触发 reload;CLI 编辑(直接改 `<vault>/tasks/*.md`)不会自动 reload —— 用户需重启 daemon 或调一次 `:mining reload`(后续可加)。M4 文档里说明这个限制。

### 与现有 ADR 的关系

- **从属于** [ADR-0003](./0003-wedge-pivot-ai-memory-layer.md):场景 B 落地。
- **遵循** [ADR-0004](./0004-ai-compose-code-execute.md):runner / extractor / scheduler 是原子能力,LLM 通过 tool-call 编排。
- **遵循** [ADR-0008](./0008-cli-parity-discipline.md):6 个原子工具 + CLI 子命令 + slash + web endpoints + UI 面板,backend 函数共享;测试主要打 backend。
- **遵循** [ADR-0006](./0006-storage-and-sync.md):tasks / drafts 用户文件用 Markdown,seen-set 派生状态用 JSON。
- **不与** [ADR-0005](./0005-llm-integration-strategy.md) 冲突:LLM 通过同一个 OpenAI 兼容客户端调用,不引入新通道。
