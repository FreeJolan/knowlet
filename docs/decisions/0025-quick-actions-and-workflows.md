# 0025 — 快捷操作 vs 工作流:两种叙事 + 共享 runner

> [English](./0025-quick-actions-and-workflows.en.md) | **中文**

- Status: Proposed
- Date: 2026-05-09

## Context

Phase 2 D 探索"daily notes" 时,从 Obsidian 风的 magic-named template (`_templates/daily.md`) 一路抽象上来:

```
magic-named template (隐性约定)
  → quick action (显式声明 = "在文件夹 X 用模板 Y 创建文档")
  → workflow (再加上 "时间触发 / 多步链 / 后台 / LLM-aware")
```

最后一层抽象引出新问题:**快捷操作和工作流是同一种东西吗?**

有 3 个力量在拉这个边界:

1. **认知负担**:简单用户配"今日笔记"快捷键时,不应该被迫看到 `schedule / next-fire-time / dry-run / dead-letter` 等字段
2. **触发模型**:快捷操作 = **空间型**(键盘 / 按钮 / palette,显式可达);工作流 = **时间+事件型**(后台运行,定时触发,产出结果用户事后审查)
3. **运维责任**:快捷操作失败 = 用户立刻看到 toast,自己修;工作流失败 = 后台静默,需要 dashboard / dead-letter / pause / log

本 ADR 锁定:**两个独立产品概念,共享同一个 action runner**。让 Phase 2 D 的快捷操作和 Phase 3 的工作流能各自演进而不相互拖累,但在底层共享一套执行 / 模板渲染 / idempotency 逻辑。

## Decision

### 1. 概念边界

| | 快捷操作(Quick Action)| 工作流(Workflow)|
|---|---|---|
| **触发模型** | 用户主动:键盘 / 按钮 / Cmd+P palette | 时间(cron-like) / 启动 catch-up / 未来:vault 事件 |
| **执行特性** | 单步、立即、用户在场 | 多步可链、后台跑、LLM 可调 |
| **失败模式** | toast + 立即看到 | dashboard / dead-letter / pause |
| **审批模型** | 用户主动按 = 默许执行 | 第一次跑必须 dry-run(per [ADR-0024 §3](./0024-ai-assist-envelope.md) hybrid 类)|
| **认知负担** | "我把常用动作快捷化了" | "knowlet 帮我后台干活" |
| **配置位置** | Settings → "我的快捷操作" | Settings → "工作流"(默认折叠,小白用户隐形)|
| **存储** | `.knowlet/quick-actions.toml`(vault 同步) | `.knowlet/workflows.toml`(vault 同步,跟 mining task 同位)|
| **快捷键绑定** | `~/.knowlet/keybindings.json`(本地,跨设备不冲突) | 通常不绑(由 schedule 触发) |
| **Phase 归属** | **Phase 2 D ship** | **Phase 3** 跟 mining 重做合并 ship |

**判别问题**(用户层):"这是我点一下就立刻能看到结果的事?还是 knowlet 静默帮我做、我事后看结果的事?" 第一类 = 快捷操作,第二类 = 工作流。

### 2. 共享底层 — Action Runner

两者都映射到同一个抽象接口:

```python
# knowlet/core/actions/runner.py(Phase 2 D 落地最小集)
class ActionRunner:
    def run(self, kind: str, params: dict, *, dry_run: bool = False) -> ActionResult:
        ...
```

`kind` 列表(共享):

- `create_note(folder, title_template, content_template_id?)` — 渲染占位符 → 检查 idempotency(同 folder 同 title 已存在则返回现有)→ 创建
- `move_note(note_id, target_folder)` — 简单文件 op 也归入 runner,以便未来工作流复用
- `apply_template(note_id, template_id)` — 模板套到现有 note(用户点 / 工作流跑都用)
- `ingest_url(url, target_folder, template_id?)` —(Phase 3 工作流用,M7.2 url-capture 重构)
- `summarize_with_llm(note_id, target_folder?)`(Phase 3 工作流用)

**v1(Phase 2 D)只 ship `create_note`**;其他 kind 是 Phase 3 跟 workflow / mining 重做时再加,但接口形状已锁定。

`ActionResult`:

```python
@dataclass
class ActionResult:
    ok: bool
    note_id: str | None        # 如果产生 / 操作了 note
    message: str               # toast / log 文案
    side_effects: list[str]    # human-readable 步骤("created daily/2026-05-09.md")
```

**dry_run 语义**:不产生副作用,只返回 `side_effects` 描述。`create_note` dry-run = "Would create: daily/2026-05-09.md, applying template 'diary-default'"。

### 3. 模板占位符

共享一组占位符语法,所有渲染 title / content 的地方都用同一个解析器:

```
{{date}}              # 2026-05-09(local)
{{date:yyyy-MM-dd}}   # 2026-05-09
{{date:yyyy/MM}}      # 2026/05
{{week}}              # 2026-W19(ISO 周编号)
{{month}}             # 2026-05
{{year}}              # 2026
{{time}}              # 14:23
{{datetime}}          # 2026-05-09 14:23
{{title}}             # 当前 note 标题(如 apply_template 在已有 note 上)
{{cursor}}            # 光标落点(只 apply_template 用)
```

复用现有 `apply_template_placeholders`(已在 Phase 1 B 模板系统 ship),扩展时间型占位符。

### 4. Phase 2 D 范围(快捷操作)

**v1 ship**:

- `.knowlet/quick-actions.toml` schema:

  ```toml
  [[actions]]
  id = "today-note"           # 稳定 id,跨重命名
  name = "今日笔记"             # UI 显示名
  description = "创建或打开今日笔记"  # Cmd+P 二级文案 + 未来 marketplace
  kind = "create_note"
  
  [actions.params]
  folder = "daily"
  title_template = "{{date}}"
  content_template_id = ""    # 可选;空 = 空白笔记

  # 可选(本地 binding 不进文件,在 ~/.knowlet/keybindings.json):
  # shortcut = "Cmd+Shift+D"
  ```

- 默认 ship 的 5 个预设(写进 `~/.knowlet/data/seed-actions.toml`,新 vault 启动时复制):
  1. **今日笔记** — `create_note(folder=daily, title={{date}})`,绑 ⌘⇧D
  2. **本周周报** — `create_note(folder=weekly, title=周报 {{week}})`
  3. **本月月报** — `create_note(folder=monthly, title=月报 {{month}})`
  4. **抓 URL 成笔记** —(占位,Phase 3 用 ingest_url 替)
  5. **1:1 会议笔记** — `create_note(folder=meetings, title=1on1 {{date}})`
  6. **读完一篇文章** — `create_note(folder=reading, title={{date}} reading log)`

  ship 这些是为了让用户**通过 fork-and-edit 学会这套机制**(per [feedback_roadmap_decision_heuristic](../../memory/feedback_roadmap_decision_heuristic.md) 风格)。

- UI 暴露面:
  - **Settings → "我的快捷操作"**(默认折叠) —— 列表 / 新建(从 6 个 pattern 起手,不是空白表单) / 编辑 / 删除 / 绑键
  - **Cmd+P palette** —— 笔记列表之上加 "动作" 段,模糊匹配 `name + description`
  - **header CalendarDays 按钮** —— 现 ⌘⇧D 入口保留,运行 id="today-note" 那个 action(就算用户改了它 ship 的预设,header 按钮跟着这个 action 走)
  - **新建 action 时**:必填 `name + folder + title_template`;可选 `content_template_id + shortcut + description`。**不出现 schedule 字段**

- 后端 endpoints:
  - `GET /api/quick-actions` — 列表
  - `POST /api/quick-actions` — 新建
  - `PUT /api/quick-actions/{id}` — 编辑
  - `DELETE /api/quick-actions/{id}` — 删除
  - `POST /api/quick-actions/{id}/run` — 触发执行,返回 ActionResult

- 文案规则:
  - 不使用 "automation" / "workflow" / "trigger" / "schedule" 这些词
  - 使用 "我的快捷操作" / "常用动作" / "运行" / "新建" / "绑定快捷键"
  - 失败 toast 用具体语言:"创建 daily/2026-05-09.md 失败 — 文件夹已被删除,请重新配置"

**v1 不 ship**:

- ❌ 多步链(`create_note → apply_tag → ping_llm → ...`)
- ❌ 定时触发 / 启动 catch-up
- ❌ Event-trigger(避免循环)
- ❌ Dry-run UI(快捷操作单步,不需要)
- ❌ LLM 调用作为 action kind
- ❌ Cost / quota 显示
- ❌ Marketplace / 导入导出
- ❌ Per-folder default template(quick action 已覆盖大部分场景)

### 5. Phase 3 范围(工作流)— 留 ADR 起草占位

Phase 3 跟 mining task 重做时一并设计,本 ADR 仅锁定**接口契约**:

- 现有 `MiningTask`(M7.5)归约为 `Workflow(kind=ingest, ...)`
- `MiningTaskScheduler` → `WorkflowScheduler`,新增对 `kind=create_note(schedule=...)` 等"非 mining" 工作流的支持
- Lazy catch-up 模型:启动时 + 周期 tick 跑 `for each scheduled action: if last_fired_at < schedule: fire`,记录 `last_fired_at`,弹静默 toast
- Schedule UI 不暴露 cron 语法,给 4-5 个预设(daily / weekly Mon / monthly 1st / weekday-only / custom-cron)
- Dry-run 必选:第一次激活 schedule 时强制 dry-run 一次,展示"这是它将创建的内容",用户审批
- Dead-letter:连续 3 次失败 → 自动暂停 + 在 Settings 标红
- Cost 透明:LLM-call 类工作流的 quota / 月估算单独区显示(per ADR-0004 amendment)
- 工作流 ≠ 自动改 vault 文件 —— 任何"修改正文 / 自动 tag"都按 [ADR-0024 §5](./0024-ai-assist-envelope.md) 拒绝

### 6. 与现有 ADR 的关系

- **ADR-0004**(AI 可选)—— 工作流引入 LLM 调用时,继承"所有 AI 入口必须有 UI 替代路径";手动版的 quick action 是 LLM-工作流的 UI 替代
- **ADR-0008**(CLI parity)—— quick action 的 `run` 必须有 CLI 镜像:`knowlet action run <id>`,工作流同理:`knowlet workflow run <id> --dry-run`
- **ADR-0009**(mining tasks)—— Phase 3 mining task 归约为工作流,review queue 接住所有 hybrid 类工作流的产物
- **ADR-0013 §1**(用户拥有,LLM 提案)—— 工作流如果改 vault 内容,**只能创建新 note / 标记 needs-update**,不能改正文(参考 [ADR-0023 §7](./0023-llm-wiki-comparison-and-takeaways.md) status 字段)
- **ADR-0023 §3**(events log)—— 每次 quick action / workflow 跑产生 `vault.events` 记录,作为 audit trail + 未来活跃度 heatmap 数据源
- **ADR-0024**(AI 协助边界)—— 工作流的 LLM-call 步骤必须在 §4 七个 AI role 表里有位置;不在表里的 role 不能引入

### 7. 命名 / 文案规则

| 概念 | 用户层叫法(中文) | 用户层叫法(英文) |
|---|---|---|
| Quick Action | 快捷操作 / 我的快捷操作 / 常用动作 | Quick action / My shortcuts |
| Workflow | 工作流 | Workflow |
| Action Runner | (内部概念,用户不见) | (internal) |
| Schedule | (Phase 3 才出现) | (Phase 3 only) |
| Trigger | "触发" / "运行" | "Run" / "Trigger" |
| Template placeholder | "占位符" | "Placeholder" |
| Default action | 默认快捷操作 | Default shortcut |

**禁词清单**(不进任何用户层文案):

- ❌ Automation / 自动化
- ❌ Cron / Scheduler / Job(用户不需要知道)
- ❌ Hook / Webhook
- ❌ Macro / 宏

## Out of scope(本 ADR 不规定)

- **per-folder default template** — quick action 已覆盖大部分场景。dogfood 撞到再加(roadmap 🟢 区已记录)
- **快捷操作的多步链** — Phase 3 工作流的特性,不下放到 Phase 2 D
- **快捷操作的 LLM 调用** — 同上
- **GitHub-style 活跃度 heatmap** — 跟 events log 共生的 UI 概念,roadmap 🟢 区
- **Marketplace / 社区分享** — schema 留 `description` 字段为之留路,但 v1/v2 不实现
- **跨 vault 共享快捷操作** — 单 vault 内的工具,不联邦

## Why split, why now

**Why split(为什么不合并叙事)**:

如果合并,Settings UI 必须同时承载"按一下做某事" + "配 cron 跑某事" + "审批 dry-run" 等等。简单用户配"今日笔记"这种 1 步动作时被迫看到不需要的字段,**配置成本**高出 5 倍,**完成率**会断崖。两种概念的认知负担曲线不在同一个量级,合并即灾难。

**Why now(Phase 2 D 而不是 Phase 3 一起做)**:

- Phase 2 D 已经做了 daily notes(Slice 1),用户已经撞到"_templates/daily.md 太隐晦"的痛点 —— 现在动手解决最有契机
- 快捷操作的 schema / runner / template renderer 在 Phase 3 工作流中**直接复用**,提前做不浪费
- ship 一个能教育用户"knowlet 是有自动化能力的"的预设组,为 Phase 3 工作流上线做心智铺路
- Phase 3 跟 mining 重做合并设计工作流,接口已经在 ADR-0024 envelope 里有位置,本 ADR 只是给它加一个共享 runner 锚点

## Acceptance(本 ADR 落地标志)

Phase 2 D Slice 2 完成 + tag `m2.D2` 时:

- [ ] `.knowlet/quick-actions.toml` schema + 后端 GET/PUT/DELETE/run endpoints
- [ ] 默认 ship 的 6 个预设可被新 vault 装载
- [ ] Settings → "我的快捷操作" UI(列表 / 新建从 pattern 起手 / 编辑 / 绑键 / 删除)
- [ ] Cmd+P palette "动作" 段落
- [ ] 现有 ⌘⇧D 行为 = 运行 id="today-note" 这个预设
- [ ] CLI parity:`knowlet action list` / `knowlet action run <id>`
- [ ] 文案审计:无 "automation / workflow / cron" 等禁词出现在用户层 UI / i18n
- [ ] e2e:create / edit / 触发 / 带模板 / palette 走通

Phase 3 工作流 ADR(待起草,编号待定)落地时:

- [ ] `MiningTask` 归约 + `WorkflowScheduler`
- [ ] cron-less schedule UI(预设 + custom)
- [ ] Dry-run 强制 / dead-letter / cost 透明
- [ ] 死循环检测(event-trigger 启用时)

## 一句话总结

**快捷操作 = 用户的常用动作,我手动按一下做完;工作流 = knowlet 后台帮我做事,事后看结果**。两个产品概念分开叙事降低认知负担,底层共享一个 action runner 避免重复造轮子,Phase 2 D 先做快捷操作,Phase 3 跟 mining 一起做工作流。
