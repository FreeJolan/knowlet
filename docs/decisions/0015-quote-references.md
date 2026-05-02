# 0015 — 笔记选区 → 聊天引用胶囊

> [English](./0015-quote-references.en.md) | **中文**

- Status: Proposed
- Date: 2026-05-02

## Context

knowlet 当前最大的体验空缺之一:**"我正在读笔记,想就这一段问 AI"**。

现状只有两条通路:

1. **right-rail AI dock 的 scope toggle**(当前笔记 / 所有笔记 / 不参考)—— 喂的是**整条 Note**,粗粒度
2. **手动 copy-paste** 选段进对话框 —— 失去引用回溯,粗暴

这两条都没法精确表达"就这一段"。本 ADR 引入第三条通路:**选区 → 引用胶囊**,让用户在 Note 中圈选一段文字,以一颗"小胶囊"挂到聊天输入框上,作为下一轮对话的细粒度 context。

跟 [ADR-0011](./0011-web-ui-redesign.md) 右栏 AI dock + scope toggle 是**正交补充**:
- scope toggle = 当前笔记/全 vault 的**粗粒度**入口
- 引用胶囊 = 用户精挑一段(可跨 Note)的**细粒度**入口

跟 [ADR-0012](./0012-notes-first-ai-optional.md) "AI 是可选能力" 一致 —— 用户主动选段,主动发问,AI 永远是被请求的一方。

## Decision

### 1. 触发器(双轨)

**自动 popover + 手动快捷键并行**:

- 在编辑器(edit / split / preview 任一模式)中选中文字 ≥ 2 字符 → 选区右上方浮出一颗小按钮(`+ 引用至聊天`)
- 同时在键盘上按 `Cmd+Shift+A`(`A` for **A**dd)直接 attach 当前选区,跳过 popover

理由:鼠标用户阅读时鼠标已在动,popover 不打扰;键盘党有快捷键。两者最终走同一个 attach 函数。

popover 在以下情况自动消失:
- 选区被取消(其他地方点了一下)
- Esc
- 已 attach(成功后 popover 收起,选区高亮 ≤ 600ms 作为视觉确认)

### 2. 多引用 + 软上限

一条 message 最多挂 **5 颗胶囊**。理由:

- 单颗太死板(用户经常要 cross-Note 比较)
- 无上限会堆爆,且 LLM context 也吃不消
- 5 颗 × ~1500 字符 ≈ 7500 字符 ≈ 2000 token —— Claude 上下文层面完全 OK

超出 5 颗 → toast 提示"最多挂 5 颗,请先取掉一颗",不强行入队。

### 3. AI 回答的引用回标(citation back-reference)— **本阶段不做**

回答里出现 `[1] [2]` 跳回原段的能力,涉及:
- 改 chat system prompt 让 LLM 输出结构化 citation IDs
- 前端解析 + 跳转 + 重新定位段落
- 跳转失败的 graceful fallback

这是非平凡工程量(prompt 工程 + 解析 + UI),会拖累主功能。**先 ship 不带 citation 回标的版本**,如果 dogfood 显示需要,后续开 ADR-0015b 单独立。

### 4. 胶囊存储 + 上下文构造

#### 4.1 胶囊存储字段

```python
@dataclass
class QuoteRef:
    note_id: str            # 来源 Note 的 ULID
    note_title: str         # 显示用(发送时不重新查,胶囊在前端就有)
    quote_text: str         # 用户选中的原文(归一化:trim + collapse \n\n+)
    paragraph_anchor: str   # 段首前 64 字符的 normalized prefix(用于编辑后的 fuzzy 跳转)
```

故意**不存** offset / line number / character range —— 这些在编辑后必然失效。

#### 4.2 LLM 上下文构造(发送时计算,不入存储)

每颗胶囊在发送给 LLM 时,**不光给 quote,还要附带"包裹 quote 的标题段落"**作为 ambient context。

构造算法:

```
1. 用 quote_text 在最新 Note body 里 find()
   ├─ 命中 → 拿到 quote 的字符 offset
   └─ 未命中(笔记已编辑,quote 已不存在)
       → 用 paragraph_anchor 做 fuzzy 重定位
       → 都失败:degrade,只发 quote_text + "(原文已变更)" 提示
2. 从 quote offset 往前找最近的 markdown 标题(# / ## / ###)
   └─ 找到该标题后,从标题首字符往后扫,直到下一个同级或更高级标题
       即得 enclosing section 的字符范围
3. 截断 enclosing section 到 1500 字符上限
   ├─ 超出:截选区前 750 + 选区 + 选区后 750 字符,前后加 …
   └─ 选区在无标题区(笔记没有任何标题)→ 取整篇 Note,同样 1500 cap
```

**LLM 看到的最终格式**(每颗胶囊一个 block,multi-quote 拼接):

```
我想就这段问你:
> {quote_text}

(为给你上下文,这段所在的标题节是:)
> {enclosing_section}
———————————————

(用户 message 本体接在这里)
```

这样 LLM 既知道用户的精确兴趣点,也知道这段的结构性背景,能产出有针对性又不突兀的回答。

#### 4.3 跳转(点胶囊回 Note)

胶囊本身可点击 → 打开来源 Note,滚动到段落 anchor 命中处。命中失败 → 仅打开 Note + toast"原文似乎已变更"。

### 5. 胶囊持久化

**一次性 + 灰化保留**:

- 发送 message 后,胶囊**保留显示**但灰化(opacity ↓,加 "再用一次" 按钮)
- 灰化胶囊不参与下一轮发送,需用户点 "再用一次" 重新激活
- 切换 chat session 时清空(灰化的也清)

理由:一次性符合 "attach" 字面意义;追问场景靠 "再用一次" 一键复用,不用重选。

### 6. 快捷键 — `Cmd+Shift+A`

理由:零 macOS 系统冲突,语义贴 ("**A**dd reference"),跟现有 `Cmd+K` (palette) / `Cmd+N` (new note) / `Cmd+Shift+{C,D,R}` (focus modes) 不冲突。

**显式拒绝过的候选**:

- `Cmd+Q` / `Cmd+Shift+Q` —— macOS 退出 App / 注销用户,系统级冲突
- `Cmd+'` / `Cmd+;` —— 中文 IME 下死键,不可靠
- `Cmd+L` —— 浏览器 address bar
- `Cmd+J` —— Chrome Downloads

### 7. 范围接入

#### 7.1 web 三种界面都触达

- Right-rail AI dock(默认)
- Chat focus mode(`Cmd+Shift+C`)—— popover + 快捷键照常工作,胶囊带进 focus chat 输入框
- Cmd+K palette ask-once(`>` 前缀)—— **本阶段不接**;palette 是 ephemeral one-shot,胶囊语义跟 "持续对话" 绑得更紧

#### 7.2 CLI parity 不强求

CLI 模式 `knowlet chat` 没有"选区"概念,CLI 用户继续 paste 引文(沿用现状)。

[ADR-0008](./0008-cli-parity-discipline.md) 管的是 "feature 跨 interface 不缺失",而本 case 是 "interface 自身的输入能力差异"(GUI 有选区,terminal 没有)—— 不破 ADR-0008 的 spirit。

**未来若有需求**:CLI 可加 `:quote <note_id> <line_range>` 的 REPL 子命令,但优先级低,不在 M7.1 范围内。

### 8. 实施 phase plan

```
M7.1.0  ADR-0015 起草 + 用户拍板         (本 commit)
M7.1.1  Backend  references payload + extract_enclosing_section
M7.1.2  Frontend popover (选区监听 + anchor 跟随)
M7.1.3  Frontend 胶囊组件 (attach / 灰化 / 跳转)
M7.1.4  快捷键 Cmd+Shift+A + chat focus 覆盖
M7.1.5  i18n + 文档 + 视频 demo
                                          tag → m7.1
```

每个 phase 单独 commit + push;m7.1 tag 在 §8 全部 ✅ 后打。

## Consequences

### Positive

- 笔记 ↔ AI 终于有了**细粒度** bridge —— 当前最大体验空缺被填上
- 胶囊不入存储(只活在前端 state)—— 不增加 vault schema
- enclosing section ambient context 解决"丢上下文"风险,token 预算可控
- 双轨触发(popover + 快捷键)兼顾鼠标 / 键盘用户

### Negative

- popover 在某些选区位置可能跟编辑器 UI 重叠(如 footer / mode switcher)—— 实现时需 anchor 智能避让
- citation 回标推迟到 ADR-0015b,意味着 dogfood 时用户**只能向前问**,不能追溯 AI 引用过哪段
- enclosing section 的"找最近标题"在无标题笔记中退化为整篇,token 用量比预期高 —— 1500 cap 兜底但语义不如有标题时清晰

### Mitigations

- popover 智能 anchor:优先选区右上方,触底时翻到右下方
- citation 回标作为 follow-up,dogfood 体感好就立即起 ADR-0015b
- 鼓励用户养成"用 #/##/### 切结构"的写作习惯(纸感 UI 已经把 serif 标题做得吸睛)

### Out of scope

- citation 回标(→ 未来 ADR-0015b)
- 胶囊跨 session 的"草稿夹"持久化(用户只说"持续到下条 message",没说要跨 session 存)
- CLI 的选区模拟(REPL `:quote` 子命令)—— 优先级低
- AI 回答里的 "deep-link" 编辑器协议(`knowlet://note/<id>?line=42`)—— 未来 desktop / mobile 才需要

## References

- [ADR-0008](./0008-cli-parity-discipline.md) — CLI parity discipline (本 ADR §7.2 解释为何不破)
- [ADR-0011](./0011-web-ui-redesign.md) — web UI redesign (右栏 AI dock + scope toggle 是粗粒度入口)
- [ADR-0012](./0012-notes-first-ai-optional.md) — Notes-first / AI is optional (用户主动召唤的设计基础)
- [ADR-0013](./0013-knowledge-management-contract.md) §1 — AI 不自动改 IA(本 ADR 不触 IA,胶囊不入存储)
