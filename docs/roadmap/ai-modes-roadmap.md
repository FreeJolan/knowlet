# AI 能力 Roadmap — need-driven 重定向（modes，非 envelope 全家桶）

- Status: Active
- Date: 2026-05-24
- **取代**: [`phase-3-stages.md`](./phase-3-stages.md) 的 7-Stage 计划 + [`phase-3-slicing.md`](./phase-3-slicing.md) 的 slice 切分。那套（envelope 7 层 / linter 全库扫 / reorg planner / tidy advisor / vault health dashboard / 知识·资料二分 / anti-drift 队列）大部分被判为**伪需求或早产**——它们建立在发明的 persona（小红/小张/新用户）上,而非用户的真实需求。
- **命名警告**:`AGENTS.md` 里的 Phase A/B/C/D/E 是 agent 工作流;本文件的 阶段 A/B/C/D/E 是产品 roadmap。问"下一阶段/Phase B"时,以本文件为准。
- **当前默认 LLM(2026-05-27)**:本机 `cliproxyapi` + Codex/GPT 5.5(`http://127.0.0.1:8317/v1`, `gpt-5.5`)。历史文档里 Claude/Claude Code 相关内容只作当时参考,不再作为默认接入或 dogfood 路径。
- **当前执行顺序(2026-05-30 五次重排)**:阶段 B 已由用户 dogfood 通过;随后插队的 **F0 — AI 底层能力重构** 已完成当前门槛。Stage C 的第一版 digest/drafts 已验证基础通路,用户 dogfood 后升级的 **Stage C v2 — 资讯审阅与入库** 已完成 C4-C15。**Phase 3.5 桌面端客户端** 已完成当前第一刀:合法 vault 选择、本地服务生命周期基础、self-contained universal DMG、Developer ID 签名、公证与 Gatekeeper 验证。下一步继续桌面端系统级入口与 Stage C 自动拉取承载。阶段 E/Quiz 暂缓到桌面端之后再评估。
- 根原则锚仍是 [ADR-0029](../decisions/0029-cognitive-contract.md):**用户是最后一个字节**（现由 diff-accept 兑现）、AI 是脚手架、输出可追溯。ADR-0029 衍生的**维护类机制**（anti-drift 队列 / dashboard / 知识资料二分）**推迟到有真实大 vault 信号再说**。

## 为什么重定向（2026-05-24 讨论）

用户（= 唯一目标/dogfood 用户）从自己的真实 AI 使用场景反推,而非自顶向下从 ADR。详见 memory `project_ai_real_needs_four_scenarios` / `feedback_user_story_first`（补充 3:n=1,不拆三角色）。

**4 个真实场景** = 同一个循环（产出文字 → 让外部脑子跟它较劲 → 较劲结果反哺文字）+ 4 种姿态:

| 场景 | AI 姿态 | 频次 |
|---|---|---|
| 读书讨论 | 批判者（推翻你） | 中 |
| 每日总结/情绪 | 镜子（托住你） | **最高** |
| 资讯内化 | 对谈者（双向） | 次高 |
| 学习测试 | 考官（判你对错） | 低 |

## 北极星

knowlet AI = **Cursor-for-notes**。唯一不可替代价值 = grounded 对谈 + 预调 stance + diff-accept 这套**界面/集成**,闭合 "Codex/agent 开在笔记文件夹里" 的两个痛点:
- (a) 每次重讲上下文 → AI 已读过本篇 + 你是谁,零交代
- (b) 交互掰不稳（出题只列题不给答案对比）→ 预先调好的可靠 mode

**razor**:任何 feature 先问 "相对 CC-in-a-folder 多给了什么?" 服务不了就砍。**排序按日常频次,不按结构复杂度。**

---

## 阶段 A — 对谈原子（最高频,是后面所有 mode 的引擎）

> 讨论 → AI 提议 → 审 diff。A1–A4 已完成并全绿（后端 note-chat 8 测 + e2e 9/9 + tsc 0,full backend 946 passed）。代码:`knowlet/chat/note_chat.py`、`POST /api/chat/note/{id}/stream` + `/propose-edit`、`frontend/src/components/Discuss/`。

- [x] A1 grounded 对谈 pane（⌘J,锚定本篇）
- [x] A2 口吻自适应（2026-05-25 改:**不让用户选、不固定枚举**;AI 按笔记性质自判口吻,指令在 user 消息。已自验:情绪→温和 / 论文→尖锐抓错）
- [x] A3 AI 提议 diff（最小局部改,不写盘）
- [x] A4 accept/reject + 原子写盘（走既有 `PUT /api/notes` + 备份,ADR-0018）
- [x] **A5 流式「停止」按钮**(P5) — 流式中 send 变「停止」,abort 在途请求(e2e 验)
- [x] **A6 对谈历史持久化 + 多轮记忆**(P6) — 关 pane 重开恢复(localStorage/per-note);并补上多轮记忆(之前每轮孤立,AI 不记得→现在带历史)。e2e 持久化 + CLI 真 LLM 多轮(AI 复述上一轮)双验
- [x] **A7 真 LLM dogfood + stance 口吻调校 + 截图** — 2026-05-27 已用 cliproxyapi + `gpt-5.5` 跑通 CLI `doctor`/`discuss` + UI Discuss/Diff/Reflect 截图;后续口吻微调并入 B2

## 阶段 B — 每日反思 / 情绪（need 2,最高频日用）

> 基本就是 A 原子（口吻已自动按情绪类材料变温和）+ 入口。依赖 A。

- [x] B1 今日反思入口（顶栏一键:开/建今日笔记 + 自动开对谈 pane;复用 today-note action。口吻由内容自动温和。e2e + 顺手修了新建笔记标题在 pane 头显示"—"的 lag bug）
- [x] B2 情绪类口吻打磨（温和、不纠错、不灌鸡汤）— 2026-05-27 收紧 TONE_GUIDANCE:先映照具体感受、不急着给建议、不要诊断、不灌鸡汤、最多一个轻问题;已用 `gpt-5.5` 真模型 CLI dogfood 通过
- _（need 1/3 的"讨论"直接复用 A,无需单独做）_

## 阶段 C — 资讯内化 triage（need 1,次高频）

> 目标形态见 [`../design/stage-c-digest-inbox.md`](../design/stage-c-digest-inbox.md):RSS / Prompt Source → 只读资讯 → 对话审阅 → 沉淀为笔记草稿 → 草稿 Diff 修正 → 用户选择目录并确认落库,或明确舍弃。依赖 A + F0 tool/capability layer。C14 后,Stage C v2 已达到当前实现门槛,下一步直接进入 Phase 3.5 桌面端。

**v1 已完成但不足(保留为基础能力):**

- [x] C1 源配置（RSS/URL）+ 定时抓取（复用 mining 后端）— 2026-05-27 新增 `knowlet digest add/list/run/remove`;底层仍是带 marker 的 MiningTask,复用现有 scheduler/runner/seen-set/drafts;已用本地 HTML 源 + `gpt-5.5` 真模型 dogfood 生成 draft
- [x] C2 digest 列表 UI（今日/本周新抓,逐条卡片）— 2026-05-27 新增 `/api/digest/drafts` + Digest focus mode;Today/This week 切换只显示 digest source 产出的 drafts,普通 mining drafts 不混入;E2E + 截图 `/tmp/knowlet-c2-digest.png`
- [x] C3 逐条:读 + 用 A 讨论 → 三选（跳过/存资料/内化为知识,内化可 AI 起草草稿走 diff 审）— 2026-05-27 新增 draft-anchored chat/propose-internalize;Digest detail 里可先对谈再 skip/save reference/internalize;internalize 走 DiffReview 后才写入;E2E + 真 `gpt-5.5` dogfood + 截图 `/tmp/knowlet-c3-digest.png`

**2026-05-30 v2 设计修正:**

- Stage C 不再支持"指定网站订阅";source 只允许 RSS Source 和 Prompt Source。
- Prompt Source 必须用 Knowlet 系统 prompt 包裹用户 prompt,并要求模型输出结构化 JSON;不能把用户自由文本直接发给模型后再猜解析。
- RSS item 不能直接变资讯;feed item 先进入 RawFeedItem,再逐条清洗、补全文、摘要和结构化为 InfoItem。
- 资讯是只读 Raw Info,不能直接修改;用户必须先"沉淀为笔记草稿",再在草稿阶段自由修改。
- 关键动作必须同时有 UI 和 Tool:沉淀草稿、修正草稿、接受/撤回 Diff、落库。
- 纳入前必须有 Review:AI 生成标题、正文、tags、资料/知识类型和建议目录;用户可修改后确认落库。
- 知识/资料判断依赖讨论深度:少讨论、只想留作参考 → 资料;经过深入讨论并形成用户自己的观点/原则/连接 → 知识。

**v2 待实现切片:**

- [x] C4 Source config v2:只支持 RSS / Prompt Source;提供 CLI + API + 初始 Settings 入口,支持启用/停用/删除,拒绝旧网站订阅 surface;focused E2E + 全量 pytest 已通过,截图 `/tmp/knowlet-c4-digest-sources.png`。C10 已将入口从 Settings 移到 Digest 工作台。
- [x] C5 Pull + normalize pipeline:每日首次在线/跨日在线自动拉取;RSS/Prompt Source 结构化处理;seen-set 去重;未处理资讯超过 200 条暂停拉取并记录 source pause 状态;新增 Raw Info 存储/API/CLI。focused pytest + ruff + tsc 已通过;本地一条 RSS + `gpt-5.5` 真模型 dogfood 创建 Raw Info,第二次运行去重为 `new=0`。
- [x] C6 Digest inbox v2:取消 today/week;改为 Raw Info inbox;支持按时间或来源分组;右上角显示拉取状态,超过 200 pending 显示暂停提示;保留只读详情,批阅/对话进入 C7。focused E2E + tsc/lint 已通过,截图 `/tmp/knowlet-c6-digest-inbox.png`。
- [x] C7 Review mode:初版批阅工作区;左侧只读 Raw Info,右侧对话流;支持从顶部开始或从指定卡片开始;新增 Raw Info 专属 chat stream,讨论后条目标记为 `discussed`。focused E2E/pytest 已通过,截图 `/tmp/knowlet-c7-review-mode.png`。C10 已收敛为全屏工作台 + 阶段 Tab。
- [x] C8 Create draft + draft tools:`create_note_draft_from_info`;接入目录树、标签体系、相似笔记等 Library Context;生成标题、正文、tags、类型、建议目录。2026-05-30:Raw Info review overlay 新增“沉淀为笔记草稿”;后端 `POST /api/digest/items/{id}/draft` + Tool 同源;失败不写 Draft;生成后可在入库前调整标题、tags、kind、folder。
- [x] C9 Draft diff + commit:草稿修正走 Diff;支持全部接受/全部撤回;对话可驱动 `propose_current_draft_edit` / `accept_all_draft_diff` / `reject_all_draft_diff` / `commit_note_draft`;用户确认后落库为正式 Note。2026-05-30:新增 Draft pending diff 持久化、UI DiffReview、API/CLI/tool parity、真 `gpt-5.5` dogfood 和生产构建浏览器 dogfood,截图 `/tmp/knowlet-c9-draft-commit-dogfood.png`。
- [x] C10 Digest workspace polish:Source 配置从通用 Settings 移到 Digest 工作台;批阅模式改为全屏工作台;左侧 Raw Info → Note Draft 阶段 Tab,草稿生成前禁用 Draft Tab,生成后自动切换并用主编辑器体验编辑草稿正文。focused E2E + tsc/build + focused pytest 已通过。
- [x] C11 Draft note surface:Note Draft 阶段从表单堆叠升级为接近主笔记的 surface:标题内联编辑、tags chip、KindChip、properties、source/rationale、Markdown edit/split/preview 和草稿生命周期 footer。focused E2E + lint/tsc/build + focused pytest 已通过,截图 `/tmp/knowlet-c11-draft-note-surface.png`。
- [x] C12 Directory-confirmed commit queue:草稿页不再裸落库;改为"选取目录并落库"→目录树确认→commit API 携带目标 folder。已有草稿不重复生成,进入该条默认 Draft 阶段;commit/舍弃自动推进队列,空队列显示跨栏空状态;Review 初始布局改 6:4。focused E2E + focused pytest + lint/tsc/build 已通过。
- [x] C13 Draft autosave / initial completion transition:草稿标题、tags、kind、folder、正文停止编辑后短间隔 autosave;footer 显示保存中/已保存/保存失败,失败时阻止落库并可重试;commit 后显示完成过渡再推进队列。focused E2E + 全量 E2E(45/45) + lint/tsc/build + 全量 pytest 已通过,截图 `/tmp/knowlet-c13-autosave-saved.png`, `/tmp/knowlet-c13-commit-transition.png`。
- [x] C14 Review action consolidation + destination animation:草稿页去掉"撤回本次改动"/"保存草稿"按钮,批阅页去掉"跳过";上一条/下一条只浏览不处理。新增"舍弃"终态(API/CLI/Tool),会标记 Raw Info 为 `discarded` 并删除关联 Draft;落库/舍弃均使用 2 秒去向动画,落库进入知识库标记并显示绿色完成,舍弃进入中性垃圾箱标记且不使用红色。
- [x] C15 Safer terminal actions + refined animation:批阅底部操作稳定为上一条 / 舍弃 / 选取目录并落库 / 下一条;落库保留 disabled 原位和 hover 原因;舍弃新增二次确认气泡;落库/舍弃动画改为快速缩小到固定尺寸后水平移动,目标收拢且更大,落库显示绿色完成,舍弃显示中性气泡破裂。

_死掉不做:网站订阅 / 通用爬站 / RSS-Bridge / anti-drift 队列 / 自动归档 / 知识资料强制二次确认。_

## 阶段 D — 笔记校准 check-note（need 4 上半,中频）

> 单篇、用户触发、对标准答案查对错/遗漏（窄版 linter,**不**全库自动扫）。依赖 A。

- [x] D1「查这篇」→ AI 报告错漏,指向具体段落（不改正文）— 2026-05-27 新增 `check_note` 核心 + `POST /api/chat/note/{id}/check` + `knowlet check-note`;单篇用户触发,报告-only,不改正文/不标 status
- [x] D2 报告里的修正一键接 A 的 diff 流 — 2026-05-27 Discuss pane 新增“查这篇”;报告 finding 的“修正”复用 `propose-edit` → DiffReview → 用户应用;E2E + 真 `gpt-5.5` CLI dogfood + 截图 `/tmp/knowlet-d-check-note.png`

**2026-05-28 UI 修正**:用户 dogfood 后,"查这篇/改这篇"不再作为短标签快捷操作直接露出。Discuss pane 的入口改成**推荐用户输入的问题**:点击后等同用户发送一条诚实展示在聊天记录里的自然语言问题,再进入普通流式对谈。`check_note` / `propose-edit` 后端能力保留,但后续若要重新把 D 报告 UI 接回来,必须先经过 F0 的 tool/capability/event 层,不能再以绕过对话流的按钮体验回归。

**2026-05-29 普通对话触发**:Stage D 的校准能力已接入普通 Discuss 工具循环。用户自然问"帮我检查这篇有没有错漏/事实错误/推理漏洞"时,模型可调用只读工具 `check_current_note`,UI 显示工具 trace,再由 AI 用 Markdown 解释结构化 findings。工具只在 note-anchored Discuss/CLI `discuss` 中有当前笔记上下文;全局 chat 调用会返回"no current note is active"。

**2026-05-29 Diff 接回普通对话**:用户自然问"帮我改写/修正/让这篇更清晰/把问题应用到正文"时,模型可调用 `propose_current_note_edit`。该工具复用既有 `propose_note_edit` 生成 `old_body/new_body`,只返回可审阅提案、不写盘;UI 收到工具结果后打开 `DiffReview`,用户逐块审/手动改/放弃/应用。推荐问题仍只是发送一条诚实的普通用户输入,不再绕过聊天流。真模型 dogfood 发现 GPT 会把"生成 diff 提案"当成普通文本 diff 输出,所以 web note stream 对明确的 edit/diff/reviewable proposal 意图做确定性路由,仍通过 `tool_call`/`tool_result` 事件显式展示过程。

## 插队阶段 F0 — AI 底层能力重构（当前门槛已完成）

> 目标:把"模型是谁"、"端点怎么包了一层"、"API surface 是 Chat Completions 还是 Responses"、"hosted tool 与 knowlet 本地 tool 谁执行"拆开。用户填好 AI 配置后,knowlet 应该自动建立能力画像,而不是要求用户手动声明"我是 cliproxyapi / OpenAI / 某某 provider"。

- [x] F0.1 `CapabilityProfile`:以 `base_url + api_key/account + model + API surface` 为运行时能力主体;`doctor`/设置页探测文本、流式、Chat Completions tools、Responses、hosted web search,并在进程内按端点+模型缓存结果
- [x] F0.2 Responses adapter(当前门槛):新增 `/v1/responses` 同步通路,能解析 output text / output item type,并识别 hosted `web_search_call`;Chat Completions 继续保留作基础文本/流式/本地工具循环路径。Responses streaming parser 先不接 UI,等有必须走 Responses 的对话模式时再补
- [x] F0.3 Tool routing(当前门槛):当前对话仍把 `web_search` 暴露为 knowlet-local tool,但 auto provider 会优先调用 endpoint 的 Responses hosted `web_search`;失败时落到 ADR-0017 的本地 provider/fetch fallback。provider-hosted 与 local fallback 的数据流在 payload/trace 中可见
- [x] F0.4 Prompt/事件统一:Discuss 与 Digest 共享 `ChatSession.user_turn_stream` + `ChatEvent` 事件;UI 用统一 `ChatTranscript` 渲染 tool trace、生成状态、Markdown、人类气泡/AI 左侧答案;CLI `discuss` 也消费同一事件流并显示工具 trace。note-anchored Discuss 已把 `check_current_note` / `propose_current_note_edit` 接入工具循环;底层 `check_note`/`propose_note_edit` 仍保持 one-shot 能力,由工具负责包装成流式事件
- [x] F0.5 联网文献/资料路径:优先走 capability profile 证实可用的 hosted web search;不可用时才落到 ADR-0017 的本地 `web_search`/`fetch_url` fallback。后续可在此之上加 `search_papers` 等领域工具
- [x] F0.6 设置与 doctor:用户只填 endpoint/key/model;`knowlet doctor` 与设置页显示"文本/流式/tool calling/Responses/hosted web_search"探测结果,失败时把问题限定到端点协议兼容而不是 prompt 猜测

**F0 完成门槛**:

- 本机 `cliproxyapi` + `gpt-5.5` 跑通 Chat Completions 与 Responses 两条最小路径
- Responses hosted `web_search` 能在真实模型上触发,且 tool trace 可见
- CLI 与 UI 至少各跑一条真实模型路径,不只靠 stub pytest
- 文档/doctor 明确说明:能力由端点实测 + 模型已知信息共同决定,不能只看模型名

**2026-05-28 F0 dogfood/验证记录**:

- `uv run knowlet doctor` against local `cliproxyapi` + `gpt-5.5`:LLM ping、tool calling、streaming、Responses、hosted web_search 均通过
- `knowlet discuss` 真实模型路径跑通过,CLI 现在会显示同源 tool trace
- UI Discuss / Digest 走统一 Markdown transcript;工具过程自动折叠,最终答案保持常显;截图:`/tmp/knowlet-codex-like-trace.png`
- 回归:`uv run pytest tests/`;`cd frontend && npx tsc --noEmit`;`cd frontend && npm run e2e`

## Phase 3.5 — 桌面端客户端（C v2 后下一站）

> 这不是 AI mode,但它是 Stage C v2 后的产品下一站。原因:在资讯审阅与入库形成高频闭环后,桌面端的本地文件夹打开、系统级入口、后台常驻与跨日自动拉取,会比继续补 Quiz 更直接支撑日常 dogfood。

- [x] Desktop 1 打开任意文件夹作为 vault + `.knowlet/` 合法性检测。2026-05-30: Tauri app 支持 `KNOWLET_VAULT` 与 native folder picker 两条启动路径。
- [ ] Desktop 2 本地服务生命周期:启动/停止/端口占用/日志/错误恢复。部分完成(2026-05-30):已完成随机 loopback 端口、`/api/health` readiness、bundled sidecar 启动、正常退出清理;日志、错误恢复和信号级强杀后的 orphan 防护仍待补。
- [ ] Desktop 3 系统级入口:菜单栏 / Dock / 快捷键 / 打开最近 vault。部分完成(2026-05-30):桌面端会在 app config 中维护最近 vault 列表,启动时自动重开最近仍有效的 vault;已提供 Vault → Open Vault... 与 Cmd/Ctrl+O 显式切库入口。Dock 行为和显式最近 vault 列表仍待补。
- [x] Desktop 4 Stage C 自动拉取承载:用户首次在线、跨日在线、后台状态提示。2026-05-30:桌面后端启动后沿用 WebState 的 Stage C auto-pull loop,首次在线立即检查,随后周期检查以覆盖跨日在线;主界面 Digest 图标轮询 `/api/digest/status` 并在拉取中显示动画;原生 Digest 菜单提供状态行、Open Digest 和 Pull Digest Now,并通过 Tauri event bridge 驱动 React 工作台。
- [x] Desktop 5 打包与本机 dogfood:Developer ID 签名、公证、真实 vault 验证。2026-05-30:Developer ID universal DMG 已签名、公证、staple、Gatekeeper accepted;包内自带 React frontend、universal backend launcher、arm64/x86_64 PyInstaller sidecars。用 `PATH=/usr/bin:/bin` dogfood 确认不依赖本机 repo 或 `uv`。升级路径/auto-update 另列为后续桌面分发切片。详见 `docs/development/macos-desktop.md`。

## 阶段 E — 出题考我 quiz（need 4 下半,最低频,桌面端后再评估）

> 结构化状态机:定知识点 → 生成题+答案 → 逐题问答 → rubric 评分 → 记分板。复用已 ship 的 quiz/SRS 后端(M7.4)。

- [ ] E1 quiz 会话状态机 UI（题卡/答题/记分板）接已有后端 — ~2–3d
- [ ] E2 评分 rubric + 逐点比对 + 标准答案渲染 — ~1d
- [ ] E3 错题接 SRS 复习（后端有,接 UI）— ~1d

## 横切 / 收尾

- [ ] 整体 dogfood（A–E 真用一遍）+ 修坑 — ~1d
- [ ] 文档:各 mode 怎么用 — ~0.5d

---

## 工期 & 排程

**近期粗估** ≈ **1.5–3 周**（桌面端剩余系统级入口/后台拉取 ≈ 1.5–2.5 周 · 收尾/dogfood ≈ 1.5d）。A/B/D、F0、Stage C v2 当前门槛和桌面 self-contained package 已完成;阶段 E/Quiz 不计入最近一轮,桌面端后再评估。

**建议顺序**:A/B/D 已完成 → F0 AI 底层能力重构当前门槛完成 → **C v2(资讯审阅与入库) 当前门槛完成(C15)** → **Phase 3.5 桌面端客户端继续做 Desktop 3/4/2 收尾** → 桌面端 dogfood 后再决定是否回到 **E/Quiz**。不要再根据旧 `phase-3-*` 文档、本文件 2026-05-28/2026-05-30 早些时候的旧结论或 ADR-0021 旧 Phase 3 envelope 计划推进。

## 明确不做（旧计划里、用户场景没点到的）

全库自动 linter · reorg planner · tidy advisor · vault health dashboard · 知识/资料二分 · envelope 7 层全家桶 · mode builder（类 Coze,推到阶段二有真实需求再说）· streak/gamification（ADR-0029 原则 6 仍禁）。
