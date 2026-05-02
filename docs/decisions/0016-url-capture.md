# 0016 — URL → 笔记录入流 + Layer A 录入端 ambient

> [English](./0016-url-capture.en.md) | **中文**

- Status: Proposed
- Date: 2026-05-02

## Context

[M7.1 / ADR-0015](./0015-quote-references.md) 把 **"已有笔记 → AI 对话"** 的细粒度通路打通了。但还有一条对偶通路缺位:

> **外部内容(URL / 文章) → 我想读完之后做点笔记**

dogfood 反馈原话(2026-05-01):

> 有时候我看到有意思的内容,我会跳转到网页链接去看,看完之后也许我很有收获,想要记录一下,此时没有合适的入口;延伸一下,我甚至可能跟 AI 头脑风暴,然后就此主题做一下总结和记录。

knowlet 当前的状况:

- 用户读完 URL → 想记录 → **得手动复制内容到 chat 输入框**(粗暴,失去引用回溯)
- 或者完全离开 knowlet,自己写 → **离开了"AI 在场"的协作语境**

[ADR-0013](./0013-knowledge-management-contract.md) §3 也指出**Layer A — 录入端 ambient 信息**是 M7 候选:每次用户即将创建新 Note,显示 top-3 相似 Note,**不预设动作,不弹"建议合并"**,信息呈现交给用户判断。

本 ADR **同时落两件事**(它们的实现路径高度重合,分两个 ADR 反而割裂):

1. **URL 录入流**:粘贴 URL → 摘要 → 胶囊 → AI 讨论 → sediment 成 Note
2. **Layer A ambient**:sediment 模态打开时显示 top-3 相似 Note(纯信息,无预设动作)

## Decision

### 1. URL 录入主入口 — 粘贴检测 + Cmd+K 双轨

**主入口:chat 输入框粘贴检测**

- 用户在右栏 AI dock 或 chat focus 模式的输入框粘贴一段文本
- 前端检测粘贴内容是否符合"单一 URL"模式(`^https?://\S+$` after trim)
- 若是 → 拦截默认 paste,在输入框下方浮一个小提示:`[抓取并讨论这个网页]`
- 用户点击 → 进入抓取流程
- 用户继续打字(忽略提示)→ 提示自动消失

**次入口:Cmd+K 命令面板**

- 新命令 `url-capture` —— 在 palette 里输入 / 粘贴 URL → 命令"抓取并讨论"
- 键盘党的备选;粘贴检测兜不住的场景(用户已经在写其他东西不想触发提示)

**显式不做**:

- ❌ Header "+ from URL" 按钮 —— 入口冗余,已经有粘贴检测
- ❌ Drafts 模态里的"讨论再保存"按钮 —— drafts 流自己有 source URL,后续单独考虑
- ❌ 浏览器扩展 / share-target —— 工程量大,defer 到 M9+ Tauri 阶段

### 2. 抓取后内容如何进入对话 — 沿用 M7.1 capsule 机制

**新增一种 capsule 来源:`source = "url"`**(M7.1 默认 `source = "note"`)

- 数据模型扩展:`QuoteRef` 加 `source: str = "note"` + `source_url: str = ""` 字段
- 对外 API:`QuoteRefPayload` 同步加这两个字段
- 渲染分化:
  - `source = "note"` 胶囊 → `《Note title》quote_text…`(M7.1 现状)
  - `source = "url"` 胶囊 → `[网页] {title} · {hostname}`,点击打开 URL
- LLM 上下文构造分化:
  - `source = "note"`:走 `extract_enclosing_section` 找标题段(M7.1 现状)
  - `source = "url"`:**直接用 quote_text(=摘要),不去 vault 找 enclosing section**

最大化复用 M7.1 已建好的发送通路 + capsule strip 渲染 + Cmd+Shift+A 快捷键(在 URL 胶囊上一样能加;但 URL 胶囊创建路径是粘贴 / palette,不是选区)。

### 3. 内容粒度 — 独立 LLM 摘要 + URL 链接

**抓取链路**:

```
1. 用户粘 URL → trafilatura.extract 拿正文(已有 mining/sources.py 复用)
2. 独立 LLM 调用 出 ~300-400 字中立摘要
3. 胶囊呈现 = [网页] {title} · {hostname} + 摘要正文 + 可点击 URL
4. 发送到 chat 时,LLM 看到:
   "我想就这篇文章问你(来自《{title}》· {url}):
    > {summary}
    ———————————————
    {用户的问题}"
```

**关键决定**:

- **全文不进 chat 上下文**,只摘要进。Token 预算从 M7.1 的 1500 字符进一步收紧到摘要的 ~500 字符
- 摘要 prompt 是**独立的、固定的、中性的**:
  ```
  对以下网页正文做 300 字左右的中立摘要,提取主旨 + 关键论点 + 结论。
  不要带个人评论,不要扩展超出原文的信息。
  ```
- 摘要 LLM 调用**复用现有 LLMClient**(走用户配置的 OpenAI-compat 后端),不走 chat session(避免污染对话历史)
- 摘要前后端均走 sync,不流式(摘要短;3-6 秒等待加 streaming hint 即可)

**失败 fallback**:

- trafilatura 抽不出正文(JS 重度页面 / 付费墙)→ 抓取失败 toast,不进胶囊路径
- LLM 摘要调用失败 → 胶囊用 "(摘要失败,原文 {N} 字)"占位,用户可仍然把 capsule 发出去;LLM 收到的 quote_text 留空,用 url + title 作 reference

### 4. 录入端 Layer A ambient — sediment 模态时显示 top-3 相似

**触发点(M7.2 范围)**:**只在 sediment 模态**打开时触发。

**显式不在 M7.2 做**:

- 手动 "+ 新建空 Note" 时不触发(blank 没内容,搜不出近邻)
- Drafts approve 时不触发(M7.x 后续考虑;drafts 是 mining 自动产出,跟用户主动行为不同语境)

**实现**:

- 新 endpoint `GET /api/notes/similar?q=<text>&top_k=3`
- 复用 `core/index.py` 的 `search(query, top_k)` —— 现有 RRF hybrid retrieval(FTS + vec)
- 前端 sediment 模态打开时,以草稿正文作 query,fetch top-3
- UI 呈现:在 sediment 模态的"标题"行**上方**或**右侧**多一个折叠面板:"可能相关的笔记"
  - 默认折叠 / 折叠态显示数字提示("3 条相关")
  - 展开后:每条 = title + 第一段 ≤80 字预览 + click → 在新 tab 打开该 Note
  - **不带任何动词按钮**(没有"合并到这条" / "merge 到现有 Note")
- 严格遵循 [ADR-0013 §1](./0013-knowledge-management-contract.md):AI 给信息,人做决定;**默认动作永远是"新建"**

**评分阈值**:不卡阈值,top_k=3 取就完了。即使相关性低,3 条也是合理的"周边视野"。

### 5. 保存 = 直接成 Note(沿用 sediment 流)

URL 录入流的最后一步 = **跟现有 sediment 完全同路径**:

- 用户讨论完 → 在右栏 AI dock 或 chat focus 点 sediment 按钮
- sediment 模态打开 → 同时触发 §4 的 ambient 拉取
- 用户编辑 title / tags / body → commit → `notes/<ulid>.md`

**显式不做**:

- ❌ URL 录入有"自动落 draft"路径 —— drafts 队列是 mining 的;用户主动行为直接 sediment
- ❌ sediment 模态多一个 "存为 Note / 存为 draft" toggle —— 增加决策负担,M6.5 的"sediment 直接成 Note"约定已 ship 用户接受

### 6. CLI parity 不强求

CLI 模式 `knowlet chat` 没有"粘贴检测"概念;CLI 用户通过 `:capture <url>` REPL 子命令(可后续加,本 M7.2 不实施)或继续手动 paste 全文。

[ADR-0008](./0008-cli-parity-discipline.md) 管的是 "feature 跨 interface 不缺失",而本 case 跟 ADR-0015 §7.2 同理 —— "interface 自身的输入能力差异"(GUI 有粘贴拦截 ↔ terminal 没有)。

### 7. Web search 不在本 ADR 范围

dogfood 期间用户 side-asked:OpenAI-compat 后端是否有原生 web search 能力。

**答**:OpenAI Chat Completions 协议本身**没有**;Claude 经 OpenAI-compat 代理通常也**没接**(因为 server tools 没有协议映射)。

**对 knowlet**:

- M7.2 的 URL 录入是**用户主动给链接**,不是 LLM 主动搜
- 如果未来要做"LLM 主动搜索网页",路径是**写本地 `web_search` tool**(类似已有 vault tools),走 LLM function calling,跟 OpenAI-compat 后端解耦,符合 [feedback_backend_agnostic](memory)
- 这是独立 feature,起单独 ADR-0017,不进 M7.2

### 8. Phase plan

```
M7.2.0  ADR-0016 起草 + 用户拍板               (本 commit)
M7.2.1  Backend  /api/url/capture + QuoteRef.source = "url" + Layer A search endpoint
M7.2.2  Frontend 粘贴检测 + URL 胶囊渲染分化
M7.2.3  Frontend sediment 模态 ambient 面板
M7.2.4  Cmd+K palette `url-capture` 命令
M7.2.5  i18n + 文档
                                                 tag → m7.2
```

每个 phase 单独 commit + push;m7.2 tag 在 §8 全部 ✅ 后打。

## Consequences

### Positive

- 笔记软件 ↔ 外部内容的 dogfood gap 终于补上
- URL 摘要走独立 LLM 调用,**不污染 chat session 历史**;chat 看到的是干净的 quote+context
- Layer A ambient 在 sediment 一处接入,自然渗透到所有用户主动创建 Note 的路径
- capsule 渲染分化(note vs url)沿用 M7.1 同一通路,代码无平行二套
- 严守 ADR-0013 §1 契约:Layer A 纯信息,无预设动作

### Negative

- 双跳延迟(抓取 → 摘要 → 胶囊出现)~3-6 秒,用户体感"等"
- 摘要 LLM 调用消耗 token / API 配额,频繁粘 URL 的成本可见
- trafilatura 抓不到 JS-heavy / paywall 页面,这部分 URL 走 fallback("抓取失败,可手动 paste 正文")
- Layer A 在 sediment 一处不覆盖"手动 + 新建空 Note"路径(空 Note 无内容可搜),这是 M7.2 的设计裁剪,不是缺陷

### Mitigations

- 双跳延迟:加 streaming hint("抓取中…摘要中…"),不让用户瞎等
- 摘要 token 成本:摘要 prompt 控制在 ~300 字输出 + 5000 字符截断 input,单次 ~2k token
- trafilatura 失败:toast 给清晰原因 + 引导手动 paste 正文,流程不卡死
- 空 Note 不接 Layer A:用户用 "+ 新建" 写到一定篇幅后,触发 ambient(后续 follow-up;M7.2 先不做)

### Out of scope

- LLM 主动 web search(→ 独立 ADR-0017)
- Drafts approve 时显示 ambient(→ M7.x 后续)
- 浏览器扩展 / share-target(→ M9+ Tauri 阶段)
- 抓取后的 image / video / PDF 内容(只处理文字)
- multi-URL 一次粘贴(只处理单一 URL,多个的话提示"一次只能贴一个")

## References

- [ADR-0008](./0008-cli-parity-discipline.md) — CLI parity discipline (本 ADR §6 解释为何不破)
- [ADR-0011](./0011-web-ui-redesign.md) — web UI redesign (sediment 模态结构 + 右栏 AI dock)
- [ADR-0012](./0012-notes-first-ai-optional.md) — Notes-first / AI is optional (URL 录入是用户主动行为,AI 是工具)
- [ADR-0013](./0013-knowledge-management-contract.md) §1 + §3 — AI 不自动改 IA + Layer A 录入端 ambient(本 ADR §4 落地)
- [ADR-0015](./0015-quote-references.md) — 笔记选区 → 聊天引用胶囊(本 ADR 沿用 capsule 机制)
