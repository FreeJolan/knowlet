# knowlet — Collaboration principles for AI agents

This file is the canonical source for how Claude Code (and other AI agents) should approach work on knowlet. Read it at the start of each session.

Per-user, per-machine preferences (English-learning corrections, local cliproxyapi endpoint, memory hygiene for the agent's own memory store, etc.) live in the user's global `~/.claude/CLAUDE.md` and are NOT committed. This file stacks on top of that.

Project-specific architectural decisions live in `docs/decisions/` (ADRs) — those are authoritative for "what we decided"; this file is authoritative for "how we work."

---

## Personas — for user-story walkthroughs

When walking through any UI / interaction work (see §4 below), use these three personas. Each gets 2 sentences: "what do I see / do / get stuck on?"

- **小张** — power user with heavy journaling + dev-notes habits. Tolerates complexity for power. Asks: "does this shave steps off my daily flow?"
- **小红** — casual user, writes occasionally. Asks: "can I remember this? can I discover this?"
- **新用户** — first-time opener. Asks: "what is this? what's my first move? can I leave without committing?"

If a design only works for 小张 and traps 小红 / 新用户, the design is incomplete — not "ship anyway for power users."

---

## 1. No hidden technical debt

The project is ~99% written by AI agents; writing cost is near-zero. Debugging, root-causing, and refactoring cost dominate. So default to *good* technical taste, not *fast*:

- "Should this be its own module / class / function?" → **yes**, unless trivially 1-2 lines used in exactly one place.
- "Should I add a test?" → **yes** for parsing, state machines, error paths, anything stateful or async.
- "Is this a quick-fix workaround?" → **no.** Find the root cause; bypasses become traps for future agents.
- "Am I crossing layers / using globals / inlining what should be encapsulated?" → **no.**

When in doubt, ask: *"if a different agent reads this in three months, how many files and how many lines until they understand it?"* If the answer is large, the structure is wrong — refactor before adding logic.

---

## 2. Work autonomously with good technical taste

Apply judgment; don't ask the project owner about small calls. The escalation bar is **product- or maintenance-scale** issues, **not** code-shape issues.

- ❌ **Don't ask** about: module/file names, parameter order, error-message wording, whether to extract a helper, internal library selection within already-established constraints, default values, formatting/style.
- ✅ **Do ask** about: product experience and information architecture, decisions whose impact is months long (sync vs async stack, single-tenant vs multi-tenant, persistence model), changes to target users / scope / milestones, anything that contradicts an existing ADR or memory.

The project owner welcomes interruptions for the second category and considers them well-spent. The first category wastes attention.

---

## 3. Single source of truth, thin shells per interface

knowlet has multiple interfaces (CLI, web UI, future desktop app, possibly MCP server). The discipline:

- All business logic lives in one backend module set (`knowlet/core/...`); each interface is a **thin adapter** over backend functions.
- Streaming responses (LLM tokens, progress, tool-call traces) are exposed as **structured-event generators** that any adapter consumes — never reimplemented per interface.
- Tests primarily target the backend modules. Per-interface tests are **integration smoke** only (e.g., CLI runs a known command and asserts the right backend function was hit). UI tests cover only what's UI-specific (rendering, events, websocket/SSE plumbing).
- A feature isn't "done" until **every existing interface** can reach it. If you've added a UI button without a CLI / slash mirror, the design is incomplete.

This pattern (Stripe / GitHub / Vercel CLI use it) makes the CLI double as a QA harness, replacing most manual UI-clicking regression testing with cheap automated tests.

---

## 4. UI / 交互设计工作 — 强制 2-step 工作流

**触发**: 任何设计、修改、重排 UI / 交互流程的工作 —— 包括新加 panel、改字段顺序、设计 picker / form / onboarding、声明 "X 应该是 Y" 这类 IA 断言、刚实现完准备说 "done" 的 UI 改动。**不允许跳步**,包括 "看起来很显然" 的小改动(显然是错觉的常见来源)。

**Step 1 — 先看竞品**: VS Code(北极星)+ 至少 1 个其他主流(Obsidian / macOS Settings / Chrome / Cursor / Slack…)。把它们怎么做的**明确说出来**。找不到对照 → 明示 "未找到先例,以下为首次设计",**不能用 "懒得查" 伪装成 "全新发明"**。

**Step 2 — 再走用户故事**: 用本文件顶部定义的三角色(小张 / 小红 / 新用户),每人 2 句 "看到什么 / 做什么 / 卡在哪"。卡住的点 = 要修的点。

**产出时明示**: 对照了谁、哪个角色卡在哪。不能只给结论不给依据。

**Why**: 反复观察到的失败模式 —— 从随手编的理论(如 "按重要性排 tabs")直接给自信结论;或实现完一个 UI 后只查技术信号(类型 / 测试通过)就宣布 done,不模拟用户走一遍。这两个缺陷加起来会让明显的体验问题(chicken-and-egg / 顺序反 / 静默坏配置)漏到用户面前才被发现。

---

## 5. 不造轮子,优先复用成熟方案

**触发**: 任何要写 "自己实现 X" 的时刻 —— 包括算法、数据结构、协议解析、UI 组件、状态管理、流处理、文件 watch、diff、并发原语、序列化、文本搜索…

**Step 1 — 先查**: 现有依赖里有没有?生态里有没有 battle-tested 的库?该领域的标准做法是什么?**明确说出查到了什么、为什么不用**。哪怕只是一句 "我搜了 X、Y,X 不维护了,Y 体积太大"。

**Step 2 — 再造**: 只在以下情况自己实现:
- (a) 现有方案严重不匹配需求,且 adapter 成本高于自实现;
- (b) 引入依赖的安全 / 体积 / 维护成本超过自实现;
- (c) 这就是项目的核心创新(领域特殊部分,不是通用机械)。

**Step 3 — 说出来**: 决定自实现时,在对话 / PR 里**明示**对照了哪些现成方案、为什么不选,而不是默默重写。沉默地造轮子是常见的隐藏债。

**Why**: 自己造的代码 "看起来简单" 是错觉 —— 边界条件、罕见 bug、未来维护、跨平台差异都是隐藏成本;成熟库已经被大量用户暴露过这些问题。除非有清晰的 "不复用" 理由,否则默认复用。与 §4 的 "先看竞品" 是同一精神:**自信结论之前先看世界上的现成答案**。

---

## See also

- `docs/decisions/` — Architecture Decision Records. Treat as authoritative for the "why" behind major choices.
- `docs/roadmap/` — current milestone slicing.
- ADR-0029 (`docs/decisions/0029-cognitive-contract.md`) — the root principle anchor for all AI / IA design decisions in this project. Read it before proposing any AI-touching feature.
