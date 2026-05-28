# AI 能力 Roadmap — need-driven 重定向（modes，非 envelope 全家桶）

- Status: Active
- Date: 2026-05-24
- **取代**: [`phase-3-stages.md`](./phase-3-stages.md) 的 7-Stage 计划 + [`phase-3-slicing.md`](./phase-3-slicing.md) 的 slice 切分。那套（envelope 7 层 / linter 全库扫 / reorg planner / tidy advisor / vault health dashboard / 知识·资料二分 / anti-drift 队列）大部分被判为**伪需求或早产**——它们建立在发明的 persona（小红/小张/新用户）上,而非用户的真实需求。
- **命名警告**:`AGENTS.md` 里的 Phase A/B/C/D/E 是 agent 工作流;本文件的 阶段 A/B/C/D/E 是产品 roadmap。问"下一阶段/Phase B"时,以本文件为准。
- **当前默认 LLM(2026-05-27)**:本机 `cliproxyapi` + Codex/GPT 5.5(`http://127.0.0.1:8317/v1`, `gpt-5.5`)。历史文档里 Claude/Claude Code 相关内容只作当时参考,不再作为默认接入或 dogfood 路径。
- **当前执行顺序(2026-05-28 重排)**:阶段 B 已由用户 dogfood 通过;随后插队的 **F0 — AI 底层能力重构** 已完成当前门槛。下一步恢复阶段 E/Quiz。原因:cliproxyapi/Codex 暴露了 Chat Completions 与 Responses、hosted tools、本地 tools、模型/端点能力探测之间的边界;F0 已先把 capability layer 钉到可继续做 mode 的程度。
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

> 定时抓 → digest → 逐条讨论 → 选择性积累。复用刚做完的 Stage 3 采集/drafts 后端,前端从"被动队列"改"主动 digest"。依赖 A。

- [x] C1 源配置（RSS/URL）+ 定时抓取（复用 mining 后端）— 2026-05-27 新增 `knowlet digest add/list/run/remove`;底层仍是带 marker 的 MiningTask,复用现有 scheduler/runner/seen-set/drafts;已用本地 HTML 源 + `gpt-5.5` 真模型 dogfood 生成 draft
- [x] C2 digest 列表 UI（今日/本周新抓,逐条卡片）— 2026-05-27 新增 `/api/digest/drafts` + Digest focus mode;Today/This week 切换只显示 digest source 产出的 drafts,普通 mining drafts 不混入;E2E + 截图 `/tmp/knowlet-c2-digest.png`
- [x] C3 逐条:读 + 用 A 讨论 → 三选（跳过/存资料/内化为知识,内化可 AI 起草草稿走 diff 审）— 2026-05-27 新增 draft-anchored chat/propose-internalize;Digest detail 里可先对谈再 skip/save reference/internalize;internalize 走 DiffReview 后才写入;E2E + 真 `gpt-5.5` dogfood + 截图 `/tmp/knowlet-c3-digest.png`
- _死掉不做:anti-drift 队列 / 自动归档 / 知识资料强制二次确认（逐条亲自过,无垃圾场）_

## 阶段 D — 笔记校准 check-note（need 4 上半,中频）

> 单篇、用户触发、对标准答案查对错/遗漏（窄版 linter,**不**全库自动扫）。依赖 A。

- [x] D1「查这篇」→ AI 报告错漏,指向具体段落（不改正文）— 2026-05-27 新增 `check_note` 核心 + `POST /api/chat/note/{id}/check` + `knowlet check-note`;单篇用户触发,报告-only,不改正文/不标 status
- [x] D2 报告里的修正一键接 A 的 diff 流 — 2026-05-27 Discuss pane 新增“查这篇”;报告 finding 的“修正”复用 `propose-edit` → DiffReview → 用户应用;E2E + 真 `gpt-5.5` CLI dogfood + 截图 `/tmp/knowlet-d-check-note.png`

**2026-05-28 UI 修正**:用户 dogfood 后,"查这篇/改这篇"不再作为短标签快捷操作直接露出。Discuss pane 的入口改成**推荐用户输入的问题**:点击后等同用户发送一条诚实展示在聊天记录里的自然语言问题,再进入普通流式对谈。`check_note` / `propose-edit` 后端能力保留,但后续若要重新把 D 报告 UI 接回来,必须先经过 F0 的 tool/capability/event 层,不能再以绕过对话流的按钮体验回归。

## 插队阶段 F0 — AI 底层能力重构（当前门槛已完成）

> 目标:把"模型是谁"、"端点怎么包了一层"、"API surface 是 Chat Completions 还是 Responses"、"hosted tool 与 knowlet 本地 tool 谁执行"拆开。用户填好 AI 配置后,knowlet 应该自动建立能力画像,而不是要求用户手动声明"我是 cliproxyapi / OpenAI / 某某 provider"。

- [x] F0.1 `CapabilityProfile`:以 `base_url + api_key/account + model + API surface` 为运行时能力主体;`doctor`/设置页探测文本、流式、Chat Completions tools、Responses、hosted web search,并在进程内按端点+模型缓存结果
- [x] F0.2 Responses adapter(当前门槛):新增 `/v1/responses` 同步通路,能解析 output text / output item type,并识别 hosted `web_search_call`;Chat Completions 继续保留作基础文本/流式/本地工具循环路径。Responses streaming parser 先不接 UI,等有必须走 Responses 的对话模式时再补
- [x] F0.3 Tool routing(当前门槛):当前对话仍把 `web_search` 暴露为 knowlet-local tool,但 auto provider 会优先调用 endpoint 的 Responses hosted `web_search`;失败时落到 ADR-0017 的本地 provider/fetch fallback。provider-hosted 与 local fallback 的数据流在 payload/trace 中可见
- [x] F0.4 Prompt/事件统一:Discuss 与 Digest 共享 `ChatSession.user_turn_stream` + `ChatEvent` 事件;UI 用统一 `ChatTranscript` 渲染 tool trace、生成状态、Markdown、人类气泡/AI 左侧答案;CLI `discuss` 也消费同一事件流并显示工具 trace。`check_note`/`propose-edit` 仍是非流式 one-shot,但复用同一 LLM wiring,不另起 provider 分支
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

## 阶段 E — 出题考我 quiz（need 4 下半,最低频,垫底;下一步）

> 结构化状态机:定知识点 → 生成题+答案 → 逐题问答 → rubric 评分 → 记分板。复用已 ship 的 quiz/SRS 后端(M7.4)。

- [ ] E1 quiz 会话状态机 UI（题卡/答题/记分板）接已有后端 — ~2–3d
- [ ] E2 评分 rubric + 逐点比对 + 标准答案渲染 — ~1d
- [ ] E3 错题接 SRS 复习（后端有,接 UI）— ~1d

## 横切 / 收尾

- [ ] 整体 dogfood（A–E 真用一遍）+ 修坑 — ~1d
- [ ] 文档:各 mode 怎么用 — ~0.5d

---

## 工期 & 排程

**剩余粗估** ≈ **4.5–6.5 单人天**（E ≈ 3–5d · 收尾 ≈ 1.5d）。B/C/D 与 F0 当前门槛已完成。

**建议顺序**:A/B/C/D 已完成 → F0 AI 底层能力重构当前门槛完成 → **E/Quiz**。不要再根据旧 `phase-3-*` 文档或本文件旧版结论回到 envelope 计划。

## 明确不做（旧计划里、用户场景没点到的）

全库自动 linter · reorg planner · tidy advisor · vault health dashboard · 知识/资料二分 · envelope 7 层全家桶 · mode builder（类 Coze,推到阶段二有真实需求再说）· streak/gamification（ADR-0029 原则 6 仍禁）。
