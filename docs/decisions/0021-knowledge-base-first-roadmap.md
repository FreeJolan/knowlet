# 0021 — 知识库优先实施顺序(Phase 0-4)

> [English](./0021-knowledge-base-first-roadmap.en.md) | **中文**

- Status: Accepted (amended 2026-05-08)
- Date: 2026-05-05

> **2026-05-08 amendment**:Phase 1 D 追加(Obsidian-baseline UX 6 项缺口),原 8-12 周 → 10-14 周。详见 [`docs/roadmap/README.md` §"重写后的 Phase 计划"](../roadmap/README.md#重写后的-phase-计划)。触发原因:Phase 1 ABC 完成 + GATE 2 dogfood 通过后实测对比 Obsidian 仍有 6 个用户每天会撞到的 baseline 缺口(多 tab / 全文搜索面板 / Properties UI / 暗色 toggle / Outline 面板 / hover preview)。

## Context

[ADR-0012](./0012-notes-first-ai-optional.md) 把身份钉为"笔记软件 + AI 是可选增强";
[ADR-0003 amendment(2026-05-04)](./0003-wedge-pivot-ai-memory-layer.md#amendment2026-05-04-用户拨乱反正) 把双链 + 图谱归位为知识软件核心。

但**实施顺序上**我之前严重跑偏:

```
M6.0–M6.5  Obsidian-style UI shell + 多会话 chat              (~3 周)
M7.0       笔记基线 5 项(checklist 跑完,UX 没磨)             (1 周)
M7.1       选区 → 聊天胶囊                                    (3 天)
M7.2       URL → 摘要 → 胶囊                                  (3 天)
M7.3       Mining critical take + hover quote                (1 天)
M7.4       Quiz 模式                                         (1 周)
M7.5       LLM web_search                                   (3 天)
M8.1       Structure signals 后端                             (1 天)
```

M7.0 之后 6 个 phase 都是 AI 集成。**M7.0 笔记基线是当 checklist 跑完,没当成"knowlet 的招牌门面"做精**。

2026-05-04 dogfood 验证:用户对 file ops / chat / 视觉 / 交互全打 F=1,total verdict "完全不愿意用第二次"。
[报告全文](../dogfood/M7-M8.1-report-2026-05-04.md)。

本 ADR 把**重做的实施顺序**钉死,确保 knowlet 先**作为知识软件可用**,再补 AI 增强。

## Decision

### 五个 phase

```
🟢 Phase 0  决策锁定 + 脚手架 + 后端 hardening(并行)         2-3 天
🟢 Phase 1  知识库基线 A + B + C(必备)                       4-5 周
🟢 Phase 2  知识库 D + E(该有,可推)                         1-2 周
🟢 Phase 3  AI 能力在新栈下重做                                3-4 周
🟢 Phase 4  整体 dogfood + 数据耐久 + 灰度期准备
```

默认产品阶段 = **开发期**(per [ADR-0022](./0022-product-lifecycle-phases.md)),全过程允许激进迭代,无需考虑兼容。

### Phase 0 — 决策锁定 + 脚手架 + 后端 hardening

**目标**:把所有"再不锁就漂"的决策定死,把脚手架搭好,后端硬化跑起来。**不写 production code**,只搭基建。

清单:
- [ ] ADR-0019 前端栈写完(本批次包含)
- [ ] ADR-0020 后端 hardening 写完(本批次包含)
- [ ] ADR-0021 本 ADR 写完(本批次包含)
- [ ] ADR-0022 产品阶段写完(本批次包含)
- [ ] ADR-0011 §"Stack" amendment 完成(本批次包含)
- [ ] 路线图 + memory 更新(本批次包含)
- [ ] **Phase 0 实施**(下次 agent 启动后):
  - [ ] `frontend/` 目录建,Vite + React + TS + Tailwind 起步;`bun install` + `bun dev` 跑通,显示 hello world
  - [ ] shadcn/ui 装好,Tailwind config 接上现有 paper-light + dark token
  - [ ] FastAPI 反代 `/api/*` → `localhost:8000`(后端);`frontend/dist/` 静态托管落点想清楚
  - [ ] 后端:`mypy --strict` 配置 + 跑 + 修暴露的类型漏(预估 50-100 处)
  - [ ] 后端:`ruff` 严配置 + 修 lint
  - [ ] 后端:pre-commit hooks + 文档
  - [ ] 后端:GitHub Actions CI

**Phase 0 完成定义**:
- 新 React 页能起来,显示一个空白带 paper-light 背景 + 应用 token 的 placeholder
- 后端 `mypy --strict` + `ruff check` + `pytest` 全过
- pre-commit + CI 跑起来,任何 fail 拦截 commit / push

**Phase 0 ❌ 不做**:任何实际 feature。

### Phase 1 — 知识库基线 A + B + C(必备)

**目标**:knowlet 作为知识软件**有资格被采纳**(没装过的 Obsidian / Bear 用户首次打开,5 分钟内完成新建/重命名/移动/删除/恢复/搜索/创建文件夹,**不用碰 CLI**)。

#### A. File ops 跟齐 Obsidian / Bear / VS Code 基线(1-1.5 周)

- [ ] 文件树:react-arborist + 虚拟化 + 多选(Cmd / Shift)
- [ ] 右键菜单:新建笔记 / 新建子目录 / 重命名 / 移动 / 复制 / 删除 / 在新 tab 打开 / 复制路径
- [ ] 拖拽移动(笔记 / 文件夹)
- [ ] F2 / 双击 重命名(inline edit)
- [ ] 批量操作(多选 → 批量移 / 删 / tag)
- [ ] **Trash UI**(focus mode 一栏 / 模态)— 替代 CLI restore
- [ ] Vault 内全文搜索(palette `Cmd+P` 强化版,跟 Obsidian quick switcher 对齐)
- [ ] **新建文件夹 UI**(替代 Finder)
- [ ] Sidebar 收藏 / 最近编辑(可推到 Phase 2 D)

**验收**:负责人能在 React UI 里完成所有 file ops,不打开 Finder / 不开 terminal。

#### B. 编辑器跟齐 Bear / iA Writer 基线(2 周)

- [ ] CodeMirror 6 替代 textarea
- [ ] Markdown 实时预览 / split view / preview-only 三态
- [ ] 图片粘贴(已有后端,UI 重做)
- [ ] **数学公式渲染**(KaTeX)
- [ ] **Mermaid 图表渲染**
- [ ] **模板系统**:`templates/` 目录 + 新笔记弹 picker
- [ ] **块引用 `[[Note#Heading]]`** + `[[Note^block-id]]` 锚点
- [ ] 代码语法高亮(CodeMirror 内置;不再用 highlight.js)
- [ ] 编辑器内部快捷键(Cmd+B/I/K 等基础;不要 over-engineer)

**验收**:负责人能用 knowlet 写一篇带数学公式 / 代码块 / Mermaid 图 / 块引用的中文笔记,**比在 Obsidian 写体验不差**。

#### C. 知识连接基线(1 周)

- [ ] Wikilinks `[[Title]]`(已有,React 重做 + 加 typing-time autocomplete)
- [ ] Backlinks 面板(已有,React 重做 + 句子级预览 + filter)
- [ ] **Graph view**(per ADR-0003 amendment;node = note,edge = `[[…]]`,可放大缩小拖拽)
- [ ] **Tag 浏览器**(标签树 / 点 tag 看所有持有该 tag 的笔记)
- [ ] Tag autocomplete(typing 时建议 vault 已有 tag)

**验收**:负责人在 graph view 里能看到 vault 全貌,点任意 node 跳转;tag 浏览器能像 Obsidian 那样一目了然。

#### Phase 1 完成定义

- A + B + C 全清单 ✅
- 负责人 dogfood 一周后,**愿意继续用 knowlet 作为日常笔记软件**(主观判断)
- 0 P0 / P1 bug

### Phase 2 — 知识库 D + E(该有,可推)

#### D. 入口体验(0.5-1 周)

- [ ] **Daily notes**(date-based 自动创建 + 跳转;Roam 入口模式)
- [ ] Quick switcher 强化(palette,模糊匹配 + 最近)
- [ ] 收藏 / 置顶 笔记(top of left rail)

#### E. 数据耐久 + 同步(1 周,跟 ADR-0018 一起)

- [ ] **ADR-0018 起草 + 实施**:schema_version 推到 Card / Draft / MiningTask;migration 脚本 + fixture-based 回归测试套件
- [ ] Vault snapshot / restore UI(已有 CLI;React 加按钮)
- [ ] Note version history(轻量,基于 git 或 `.knowlet/backups/`)
- [ ] (可选)Import:Obsidian / Notion / Roam → knowlet
- [ ] (可选)Export:PDF / HTML / Anki

**Phase 2 是"该有但可推"** — 如果 dogfood Phase 1 后负责人想直接进 Phase 3 AI,Phase 2 的 D / E 可以拖到 Phase 4 整合时再做。

### Phase 3 — AI 能力在新栈下重做(3-4 周)

**重点**:AI 后端**已存在**(376 测试覆盖),Phase 3 是在新 React UI 下**重新表现**这些能力,顺手:
- 修协议层(把 user-facing message 跟 LLM-facing prompt 拆开,杜绝"隐藏 prompt 暴露给用户")
- 吸收 dogfood 暴露的设计问题(quiz scope picker / 胶囊去重 / URL ghost capsule / sediment ambient inline 等 — 详见 [Claude Design 2nd pass bundle](../design/bundle-2026-05-04/))

清单:
- [ ] **Chat dock + chat focus mode**:Vercel AI SDK + useChat hook(SSE / streaming / persist / refresh restore 全包)
- [ ] **选区 → 胶囊** 重做(去重 / wrap 不溢出 input / popover 智能避让 / Cmd+Shift+A)
- [ ] **URL ghost capsule**(per Claude Design §3 — 替代 banner)
- [ ] **Sediment + Layer A inline ambient**
- [ ] **Quiz focus mode**(per Claude Design §8 — 2 步 scope picker / search-not-list / inline disagree)
- [ ] **Mining drafts UI**:重做 critical take + hover quote,List + 翻页 + 接受 / 拒绝
- [ ] **Web search trace 显示**:tool call 在 chat history 里清晰可见
- [ ] **Cards 整套**:Cards focus mode + 新建 Card UI(已有)
- [ ] (回流)**create_card / web_search / fetch_url / list_mining_tasks 的 UI peer**(per ADR-0004 amendment)

**验收**:dogfood 报告所有 frustration 全部清掉,Top frustration 从"Chat 完全不能用"变成"我希望 X feature 更好"。

### Phase 4 — 整体 dogfood + 灰度期准备

- [ ] 全栈 e2e 测试(Playwright)— chat 全栈 / file ops / quiz 流 等
- [ ] 数据耐久 ADR-0018 完整落地(if not done in Phase 2)
- [ ] 文档完整(README / install / use guide / contribute)
- [ ] 灰度期 entry criteria 评估(per ADR-0022)
- [ ] 灰度期发布机制(brew formula / installer / 邀请流程)

### Phase 4 之后 = 进入灰度期(per ADR-0022)

## Consequences

### Positive

- **顺序对了**:知识软件先,AI 后,跟 ADR-0012 身份契约一致
- **每个 Phase 有可量化验收标准**:不会"以为做完了"
- **dogfood 反馈循环紧**:Phase 1 完一次 dogfood,Phase 3 完一次 dogfood,有节奏
- **进入灰度期路径清楚**:Phase 4 entry criteria 锁定

### Negative

- **8-10 周看不到任何新 AI feature**(项目负责人已表示能保持耐心)
- **某些已有 AI feature(quiz / mining / web_search)在 Phase 3 之前以"裸 API + curl 调用"形态存在**:勉强可用,但没 UI
  - 缓解:Phase 3 不算延后,只要顺序对就好

### Out of scope

- 灰度期之后的事(per ADR-0022 进入时再 ADR)
- M9 阶段(本 ADR 把以前的 M9 候选(块引用 / Daily / Math / 模板等)全部并入 Phase 1 B/D)

## References

- [ADR-0012](./0012-notes-first-ai-optional.md) — 笔记软件 + AI 可选(本 ADR 实施层兑现)
- [ADR-0003 amendment(2026-05-04)](./0003-wedge-pivot-ai-memory-layer.md#amendment2026-05-04-用户拨乱反正) — 双链 + 图谱是核心(Phase 1 C)
- [ADR-0004 amendment(2026-05-04)](./0004-ai-compose-code-execute.md#amendment2026-05-04-用户澄清ai--唯一入口) — 每个 AI 功能必须有 UI 替代(Phase 3 兑现)
- [ADR-0019 前端栈](./0019-frontend-stack.md) / [ADR-0020 后端 hardening](./0020-backend-python-discipline.md) — 工程基础
- [ADR-0022 产品阶段](./0022-product-lifecycle-phases.md) — 当前是开发期,允许激进迭代
- [Dogfood 报告 2026-05-04](../dogfood/M7-M8.1-report-2026-05-04.md) — 触发本 ADR 的原始信号
- [Claude Design 2nd pass bundle](../design/bundle-2026-05-04/) — Phase 1/3 视觉 + 交互参考
