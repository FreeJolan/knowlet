# Phase 3 — AI 能力重做 切片计划

> **中文** | English to follow if needed
>
> Last update: 2026-05-16

## 背景

Phase 3 的根原则锚 = [ADR-0029](../decisions/0029-cognitive-contract.md)(认知契约)。 
机制护栏 = [ADR-0028](../decisions/0028-ai-quality-mechanism.md)(质量机制契约,包括 8 条机制约束)。 
Role 分类 = [ADR-0024](../decisions/0024-ai-assist-envelope.md)(envelope + 7 roles)。 
Hybrid 落地 = [ADR-0009](../decisions/0009-mining-tasks-and-drafts.md)(drafts queue,含 2026-05-16 amendment 重设计 capture-time inline review)。

每个 slice 在 design review 前必须证明:
1. 跟 ADR-0029 §1 核心命题对齐
2. 满足 ADR-0029 §4 八条原则
3. 满足 ADR-0028 §2 八条机制约束(envelope / audit / JSON schema / confidence / structured destination / first-class tool / why-citation / interruptible+undoable)
4. 在 ADR-0024 §4 七个 role 表里能定位

Phase 3 估时:**5-7 周**(原 3-4 周;新增 P3.0 / P3.8 / P3.9 + 每个 slice 多机制约束所致)。

---

## Slice 概览

```
P3.0  LLM Settings + 模型档位 UI + Privacy panel       3-4 天    无依赖
   ↓
P3.1  Envelope assembly framework + ai.call audit       3-4 天    依赖 P3.0
   ↓
   ├──→ P3.2  Chat companion 重做                       5-7 天    依赖 P3.1
   │
   ├──→ P3.8  知识/资料 type chip + 默认分类             3-4 天    依赖 P3.1
   │
   ├──→ P3.9  Drafts queue 重做(capture-time review)   5-6 天    依赖 P3.1 + P3.8
   │
   ├──→ P3.3  Capture extractor + Drafts UI 接入        4-5 天    依赖 P3.9
   │
   ├──→ P3.4  Editor advisor                            3-4 天    依赖 P3.1 + P3.8
   │
   ├──→ P3.5  Mining tasks UI                           4-5 天    依赖 P3.3 + P3.9
   │
   ├──→ P3.6  Linter(用户主动触发)                     4-5 天    依赖 P3.1
   │
   ├──→ P3.7  Vault Health Dashboard                    3-4 天    依赖 P3.8 + P3.6
   │
   └──→ P3.A  wiki_schema.md + user_profile.md 注入     2-3 天    依赖 P3.1
```

总工作量:~35-50 工作日,即 **5-7 周** 单人开发。

依赖关系决定: P3.0 + P3.1 是基础;之后 P3.2/3.4/3.6/3.A 大致并行;P3.8/3.9/3.3/3.5/3.7 是 drafts-queue + 资料分类 + dashboard 这一串。

---

## P3.0 — LLM Settings + 模型档位 UI + Privacy panel

**范围**: knowlet 自带 LLM 配置 UI(目前用 toml 配置,不友好),让普通用户能在 Settings 里完成 model / api key / 隐私偏好的所有设置。

### 用户故事

**小张(power user · 想用 Sonnet 4.6)**: 
打开 Settings → LLM → 选 "Claude" → 看到三档推荐("A: Opus 4.7 / Sonnet 4.6 - 完整体验"、"B: Haiku - 部分能力降级"、"C: 3.5/小模型 - 大多数高级 role 不可用") → 选 Sonnet 4.6 + 粘 API key → done。 
他切到 Haiku 测便宜版 → UI 立刻显示一行 "current mode: 降级,以下 role 已禁用: editor advisor / linter detail"。

**小红(casual · 不知道选什么)**: 
打开 Settings → LLM → 看到默认 = "本机 cliproxyapi"(我们 detect 到她有装就 default 选这个);看到一行说明 "knowlet 自动使用你已登录的 Claude 订阅";不用做任何事就能用。 
她忽略 Privacy panel(默认安全)。

**完全新用户**: 
首次打开 knowlet → chat 提示 "需要配 LLM 才能用 AI 能力" + 跳转 Settings。 
Settings 显示三步引导(Provider → Model → Test)。她跑完 Test 看到"OK,你可以在 chat 里用了"反馈。

### 满足 ADR 检测
- ADR-0029 原则 2(AI 是脚手架): ✅ 不配也能用,knowlet 退化纯笔记
- ADR-0029 原则 5(不主动浮): ✅ 配置入口靠用户主动开 Settings
- ADR-0028 §1(模型档位): ✅ 三档 explicit 显示 + degrade 提示

### 显式不做
- 内嵌 LLM(per ADR-0028 §3 商业模式选择)
- 帮用户付费(用户带凭证)
- 多 LLM 同时并发切换(后期 dogfood 撞到再加)

---

## P3.1 — Envelope assembly framework + ai.call audit

**范围**: 后端基础设施。所有 AI role 通过 `knowlet/core/ai/envelope.py` 组装 prompt;每次 LLM 调用写 `events.sqlite` 的 `ai.call` event;统一 LLM 客户端封装(同时支持直连 API + cliproxyapi)。

### 用户故事
**用户感知不到**(per memory `feedback_user_story_first` 的"纯 backend 基础设施例外条款")。但这是 Phase 3 的地基,所有后续 slice 共用。

需要 trace 出可观测性:用户在 Settings → Advanced → AI audit log 可看到最近 N 次 AI 调用的详细 trace(prompt 长度 / 模型 / token / 延迟 / 输出预览)。这条 trace 入口是给 power user 看的,普通用户不开。

### 满足 ADR 检测
- ADR-0028 §2 第 1 条(统一 envelope): ✅ 落地
- ADR-0028 §2 第 2 条(audit trail): ✅ 落地
- ADR-0028 §9(对话上下文 + cliproxyapi 路径): ✅ 客户端兼容两条路径

### 显式不做
- Per-role prompt 优化(本 slice 只搭框架,模板留给各 role slice)
- Eval 框架(per ADR-0028 §7 后置 Phase 4)

---

## P3.2 — Chat companion 重做

**范围**: 新前端 chat focus mode + Vercel AI SDK 化(替代当前自写 SSE);走 P3.1 的 envelope;接 `@-mention` 拉笔记进 context(per Cursor 借鉴);Sources 区永远比 answer 显眼。

### 用户故事

**小张(每天用 chat 讨论)**: 
⌘L 打开 chat,聊一个想法,AI retrieve 3 篇相关笔记,答案下方 "Sources" 区列出来 → 他点其中一篇直接跳到 noteview 验证。 
chat 里他打 `@RAG综述` → autocomplete 列出含 "RAG" 的笔记 → 选一个,这篇笔记的完整内容进 envelope 的 task 层,精准回答。 
他在 chat 里说 "把这个 idea 整成一篇 note" → AI 起草 → **在 chat 里当场显示**(per ADR-0009 amendment) → 他点 "进 review queue" → 落 drafts → 后续审。

**小红**: 
⌘L chat → "我之前是不是写过关于 X" → AI 答案 + Sources 给到具体笔记,她点过去看。 
失败路径: AI 没找到相关笔记时,chat 仍正常答(per ADR-0028 §4),但 Sources 区不显示 — 她从"有没有 Sources" 自己判断答案的来源。

**新用户**: 
chat 入口空状态 + 一句话:"问关于你 vault 的任何问题"。 
失败路径: 未配 LLM → 显式提示 + 跳转 Settings(per ADR-0028 §6 失败 UX)。

### 满足 ADR 检测
- ADR-0029 原则 1(用户最后字节): ✅ AI 起草的 note 进 drafts queue,不直接入 notes
- ADR-0029 原则 4(traceable + citation): ✅ Sources 区 visual weight > answer
- ADR-0029 原则 5(AI 不主动浮): ✅ chat 用户主动 ⌘L 打开
- ADR-0028 §2 (8 条): 全 ✅

### 显式不做
- Chat history 增强(多会话搜索 / 删除会话)— v2
- 多 chat 并发 / 多 LLM 切换 — v2
- 语音 input — Phase 5

---

## P3.8 — 知识/资料 type chip + 默认分类(必须先于 P3.9 / P3.3)

**范围**: 笔记 frontmatter 新增 `_type: knowledge | reference`(per ADR-0029 §4.5,开发期 schema 自由迭代);各创建路径默认分类按 source(详 §4.5 表);NoteView header 显示 type chip 可一键 toggle;不对称升级降级(资料 → 知识一键;知识 → 资料二次确认);文件树视觉区分(资料类 muted color)。

### 用户故事

**小张(常区分用)**: 
新建笔记 → header 自动显示 `[🧠 知识]` chip → 他写完。 
某次他粘了一个 cheat sheet → header chip 自动 = `[📚 资料]`(因 source = paste 检测到非 markdown / 短内容) → 直接保存。 
他后来翻到一篇曾标 "资料"但其实想认真理解的 → 一键 toggle 升级为知识 → 进入 review queue。

**小红**: 
她从来不点 chip,所有笔记保持默认 = 知识(她手写的)/ 资料(网页 capture)。OK 状态,不打扰。

**新用户**: 
第一次看到 chip 出现 → header 下一行小字解释 "knowlet 区分知识 / 资料两类... [了解更多] [知道了]" → dismiss 后不再出现。

### 满足 ADR 检测
- ADR-0029 §4.5: ✅ 整节物理实现
- ADR-0029 §4.5 Meta 原则(结构决策必须 visible): ✅ chip 在 NoteView header 而非 frontmatter / settings
- ADR-0029 原则 7(anti-drift): ✅ 不对称升降级

### 显式不做
- 强 mid-write 切换提示(用户自己看 chip 想改就改,不打扰)
- 自动 inference("AI 觉得这篇是知识"主动改 type)— 违反 §6 用户最终决策

---

## P3.9 — Drafts queue 重做(capture-time inline review + anti-drift 兜底)

**范围**: 新前端 drafts queue UI(老 Alpine 已删);**capture-time inline review 是 default**(per ADR-0009 amendment 2026-05-16);drafts queue 只装 explicit-defer 的内容;落 4 个 anti-drift 兜底(age tickling / soft limit / mining 节流 / 无 streak)。

### 用户故事

**小张(常审 drafts)**: 
chat 里说 "起草这篇" → AI 在 chat 当场显示草稿 → 他读完点 [🧠 知识 进 review] → drafts queue 多 1 条 → 他立即点开看 → edit 标题 → approve → 落 notes。**全程 < 30 秒**,没等"以后慢慢看"。 
偶尔他没空 → 点 [暂存 进 queue] → 然后忘了。30 天后再 capture 时 → drafts UI 顶部 banner "你有 1 条 30 天前的 deferred draft,要 review 还是归档?" 他 review 掉,清空 queue。

**小红**: 
她偶尔 paste URL → AI summarize → 她当场选 [📚 资料 直接存] → done,不进 queue。 
她从不主动 defer,所以 queue 永远空。

**新用户**: 
第一次见到 drafts queue 概念 → onboarding banner 解释"这里是你 explicit 暂存的待审稿"。 
他不主动暂存 → queue 永远空 → 不会困惑"哪些东西堆在这里"。

**Mining task 用户(也是小张)**: 
他配了一个 mining task 跑每天 6am。某次他出差 7 天没看,mining task 跑出 5 条 → **达 max 5 limit task 自动暂停** → 他回来开 knowlet,first thing 看到"上次 mining 出 5 篇,逐条 review?"(per A2.2 表) → 他逐条 5 篇 → unpause task。

### 满足 ADR 检测
- ADR-0029 §4 原则 1 用户最后字节: ✅ drafts queue 全部经用户决定
- ADR-0029 §4 原则 7 anti-drift: ✅ capture-time default + 4 个兜底
- ADR-0028 §2 第 5 条(structured destination): ✅ drafts/archive/<yyyy-mm>/
- ADR-0009 amendment 2026-05-16 全部条款: ✅

### 显式不做
- Mobile drafts review(per ADR-0029 §4.5 移动端 note,Phase 5)
- "Batch accept all" 按钮(违反原则 7)
- "AI auto-suggest 哪些 drafts 应该 prioritize"(过度智能 + 违反原则 5)

---

## P3.3 — Capture extractor + Drafts UI 接入

**范围**: 实现 `Capture extractor` AI role(per ADR-0024 §4) — URL paste / 拖拽 PDF / Capture box 全套;接 P3.9 的 drafts queue 流;支持知识 / 资料默认分类(per ADR-0029 §4.5);⌘⇧V 全局快捷键。

### 用户故事

**小张(用 ⌘⇧V 抓 blog)**: 
看到 blog 想留 → ⌘⇧V → Capture 模态 → 粘 URL → AI 自动 fetch + extract title/author/summary → 默认 chip = `[📚 资料]` → 他改成 `[🧠 知识]`(因这篇要细看)→ 点保存 → 落 drafts queue 等审。

**小红**: 
偶尔丢 URL 进 chat → AI inline 显示三按钮 → 她点 [📚 资料] → 一秒完成。 
失败路径: paste 一个 paywall URL → fetch 失败 → UI "抓取失败:网页要登录。要不要只保存 URL?" → 她 OK。

**新用户**: 
第一次 capture → onboarding "这是 knowlet 的捕获入口,把你看到的内容存进来,AI 会先帮你 extract 信息"。

### 满足 ADR 检测
- ADR-0028 §2 第 3 条(JSON schema 校验 AI extract 输出): ✅
- ADR-0024 §4 Capture extractor role: ✅
- ADR-0009 amendment A2.2 三入口(chat URL / drag / Capture box) 全套: ✅

### 显式不做
- YouTube transcript / 学术 PDF 引用 deep extract(等真实需求)
- 自动 ingest 全网 RSS(那是 mining task 的事,P3.5)

---

## P3.4 — Editor advisor

**范围**: 用户在 NoteView 写新笔记时,AI 根据 title + 前 N 字 + vault context 推荐 folder / tags / 相关笔记;气泡呈现,confidence < 0.5 不显示;用户 accept 才执行(knowlet 代码做,不是 LLM tool call)。

### 用户故事

**小张(常用)**: 
新建笔记,写完 title "Mintlify virtual filesystem" + 前两行内容 → header 气泡浮出"建议放 `concepts/mintlify/`,因为已有 3 篇 Mintlify 相关在那" → 他 accept → 笔记 move。

**小红**: 
她写完笔记不点气泡 → 笔记保持原位 → 没影响。 
失败路径: confidence 低时不显示气泡,她不感知 — 正确。

**新用户**: 
空 vault 时 → advisor 没数据可参考 → 不显示。等他写了几篇后"自然就出现"。

### 满足 ADR 检测
- ADR-0029 原则 1(用户最后字节): ✅ 气泡 = 建议,accept 才执行
- ADR-0029 原则 4(why citation): ✅ "基于这 3 篇"
- ADR-0029 原则 5(用户召唤): ✅ 用户主动写笔记时被动 nudge,不主动 push
- ADR-0028 §2 第 4 条(confidence threshold): ✅ < 0.5 不显示

### 显式不做
- AI 改正文(per ADR-0024 §B)
- 自动应用建议(per ADR-0024 §C)
- Auto-tag(per ADR-0024 §D)

---

## P3.5 — Mining tasks UI

**范围**: 实现 ADR-0009 描述的 mining task UI(后端 ship 已久,前端缺) — 任务列表 / 编辑器 / 运行历史 / event trace。接 P3.9 的 capture-time review 流(per A2.2:mining 跑完不主动通知,下次启动 first thing surface)+ A2.3 节流(max_pending_drafts)。

### 用户故事

**小张(用)**: 
Settings → Mining → 新建任务 "每天早上抓 LLM 论文" → 配 prompt + RSS source + cron → 任务每天跑。 
他出差 7 天回来 → 打开 knowlet → first thing 看到 "上次 mining 出 5 篇" → 逐条 review。

**小红 / 新用户**: 
不知道 mining 是什么,Settings 里看到入口但不点。OK。

### 满足 ADR 检测
- ADR-0009 主体 + amendment 2026-05-16: 全 ✅
- ADR-0029 §4 原则 7 (anti-drift 节流): ✅ max_pending + 自动 pause

### 显式不做
- AI 替用户改 task prompt(用户的创造,AI 不替写)
- 任务的自动 tune(用户调,not AI)

---

## P3.6 — Linter(用户主动触发)

**范围**: 实现 ADR-0024 §4 Linter role,扫跨页矛盾 / dangling wikilinks / missing entities / 过时内容;**仅用户主动触发**(per ADR-0029 §5b);结果落 dashboard + frontmatter status 标记 + NoteView 一次性 banner(per 3-test)。

### 用户故事

**小张(power user)**: 
⌘⇧L 跑 lint → progress bar(全 vault 扫 1000 篇 P95 ≤ 30s) → 报告: 8 条问题,4 矛盾、2 dangling、1 missing entity、1 过时。 
他点其中一条 → 跳 noteview → 自己改。改完 frontmatter `status: needs-update` 自动清除。

**小红 / 新用户**: 
不知道 lint 存在 → 在 Settings → Maintenance 下面有个 "Scan vault for issues" 按钮。他们不点也完全 OK,knowlet 不主动跑。

### 满足 ADR 检测
- ADR-0029 §5b Linter 触发约束: ✅
- ADR-0029 原则 5(不主动浮): ✅
- ADR-0024 §B(不替写正文): ✅ 只标 status

### 显式不做
- 自动修(per §B)
- 自动 merge 矛盾笔记
- 替写 missing entity 的笔记

---

## P3.7 — Vault Health Dashboard

**范围**: 实现 ADR-0029 §4 原则 8 描述的 dashboard。用户主动开,显示双 metric(知识维度 + 资料库存 + AI drafts breakdown + dangling 等 lint 信号汇总)。**绝无 streak / guilt / 红 badge**。

### 用户故事

**小张(每月看一次)**: 
打开 Settings → Vault Health → 看到 "本月: 47 篇 / 12 篇自己写 / 18 篇 AI 起草重改 / 17 篇 AI 起草直接 accept" + "AI 起草后从未回访: 23 篇" + "90 天未触碰: 156 篇" + "Lint 上次跑: 14 天前 / 待处理 8 条"。 
他看完决定 "我应该清理一下 untouched"。

**小红**: 
看一眼觉得太多数字 → 关掉 → 不再看 → OK,设计如此。

**新用户**: 
不会主动开,但用了一段时间后(假设设计上某天用户撞到它的入口)他打开看一眼 → 学到"哦原来 knowlet 区分知识 / 资料,以及 AI 起草和我手写"。

### 满足 ADR 检测
- ADR-0029 原则 8(make depth visible): ✅
- ADR-0029 原则 6(无外部评判,有内部觉察): ✅
- §4 3-test: ✅(完全 on-demand,无主动 push)

### 显式不做
- 通知(per 原则 5)
- streak / 比较(per 原则 6)
- 自动周报(等用户 opt-in,per §5b)

---

## P3.A — wiki_schema.md + user_profile.md 注入

**范围**: 落地 ADR-0024 §3 描述的两层静态 envelope source。`vault/.knowlet/wiki_schema.md`(per-vault 写作约定) + `vault/.knowlet/user_profile.md`(身份层);UI: Settings → Vault → 编辑这两个文件;每次 LLM 调用 envelope 自动注入对应层(per ADR-0024 §3.3 表)。

### 用户故事

**小张(写约定)**: 
打开 Settings → Vault → Wiki schema → 写"我所有概念笔记必须包含 §Why、§How、§See also"+ 保存。 
下次 AI 起草笔记 → 自动按这个约定。 
他写 user_profile → "我是后端工程师,Go 经验 10 年,React 是新接触" → chat 答案语气随之调整。

**小红 / 新用户**: 
不写也完全可以。AI 用默认行为。

### 满足 ADR 检测
- ADR-0024 §3 多层 envelope: ✅
- ADR-0029 §4.5 元原则(可见可改): ✅ 不藏 Settings 二级,有专门入口

### 显式不做
- 多层级 schema(`~/.knowlet/wiki_schema.md` 全局层)— 等用户撞到再加
- Schema syntax validator — 自由格式,不强约束

---

## Phase 3 完成定义

Phase 3 全部 slice ship + dogfood 至少 2 周(用户每天用 chat / capture / 起草)+ 无 P0 bug → 完成。

完成后下一站 = Phase 3.5 桌面端(per memory `project_desktop_client_after_ai_before_gray`),最后 Phase 4 灰度。
