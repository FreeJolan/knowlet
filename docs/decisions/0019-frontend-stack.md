# 0019 — 前端栈:React 19 + Vite + TypeScript + 现成组件库

> [English](./0019-frontend-stack.en.md) | **中文**

- Status: Accepted
- Date: 2026-05-05
- Supersedes: [ADR-0011](./0011-web-ui-redesign.md) §"Stack" 的 "no SPA framework" 约束

## Context

[ADR-0011](./0011-web-ui-redesign.md) §"Stack"(2026-04-29) 写过:**不引入 SPA 框架**,栈定为 Tailwind + Alpine.js + marked.js + Split.js。理由当时是"减少依赖 / 好审计 / 可被 LLM 维护"。

2026-05-04 项目负责人完成了第一次正式 dogfood([报告](../dogfood/M7-M8.1-report-2026-05-04.md)),结论:**前端基本不可用**。具体故障:

- AI 对话:空气泡 / 隐藏 prompt 暴露给用户 / 刷新后输入框消失(3 个互不相关的 bug)
- 输入框 IME(中文拼音)偶发吃字
- 文件操作完全不能跟齐 Obsidian / Bear 基线(× 当删除 / 恢复要 CLI / 文件夹要 Finder 创建)
- 选区胶囊溢出输入框
- Cmd+Shift+C 不能 toggle 退出焦点模式
- 一系列视觉 / 交互的小问题集合

**根因诊断**(详见 5/5 对话纪录):

1. **手写 chat UI**:SSE event 流 + Alpine 反应式 proxy 的边角组合,产生了多个我没预料到的 bug。Chat 是已解决品类,有现成开源组件(Vercel AI SDK + useChat / assistant-ui / deep-chat 等),不该自写。
2. **栈选 Alpine 偏门**:GitHub ~25k 星(对比 React ~225k)。**LLM agent 训练数据 React 远多于 Alpine**,我熟悉度也低,反复在 reactive proxy 边角踩坑。
3. **没有静态类型**:JS + Alpine,17k LOC 各种 typo / 遗忘字段 / 状态机 race 没有任何编译时拦截。
4. **没有 chat-specific 测试**:376 backend 测试全过,但 chat 全栈流(用户输入 → SSE → render → persist → refresh restore)一行 e2e 测试都没。

ADR-0011 §"Stack" 的三条理由今天**全部不再成立**:

| 当时论证 | 2026-05-05 事实 |
|---|---|
| 减少依赖 | 替代依赖的是 ~2000 行自写 app.js + ~1100 行 index.html 模板。**净增加** |
| 好审计 | Alpine 库本身小,但自写代码量是它的 ~100 倍。**净降** |
| 可被 LLM 维护 | **完全反了** — LLM 训练数据 React 密度高得多;Alpine reactive proxy 边角 LLM 经常猜错 |

加上项目负责人坦白"我连 Alpine 听都没听过" — 工具链选偏门到 owner 看不懂自己的项目,**已经突破了 ADR-0002 §"AI is optional, owner is autonomous" 的隐性边界**。

## Decision

### 前端栈完全替换

**新栈**(2026-05-05 起):

```
React 19           SPA 框架本体
Vite               build / dev server / HMR
TypeScript         静态类型
Tailwind CSS       工具类(留;现有 paper-light + dark token 直接复用)
shadcn/ui          通用组件(Modal / Popover / Select / Tooltip / Cmd+K palette / etc)
Vercel AI SDK      Chat 流(useChat hook + SSE / streaming / tool trace 全包)
CodeMirror 6       Markdown 编辑器(替换现有 textarea;ADR-0011 §"Schedule" 本来就要做)
react-arborist     文件树(虚拟化 + 拖拽 + 多选 + 重命名内联)
Tanstack Query     API 调用 + 缓存 + 重试 + 状态管理
Vitest             单元 / 组件测试
Playwright         e2e 测试(尤其 chat 全栈流)
```

### 弃用栈(完全删除)

- ❌ Alpine.js(包括所有 `x-data` / `x-show` / `x-text` / `x-model`)
- ❌ Split.js(用 React 原生或 react-resizable-panels 替代)
- ❌ marked.js(CodeMirror 6 内置 / 或 unified + remark)
- ❌ highlight.js(CodeMirror 6 内置语法高亮)
- ❌ marked-highlight(同上)
- ❌ 自写 SSE parser(`knowlet/web/static/lib/sse.js`)— 用 AI SDK 的 streaming
- ❌ 自写 palette parser(`knowlet/web/static/lib/palette.js`)— 用 cmdk / shadcn

### 保留(0 改动)

- ✅ Backend 整套 Python(per ADR-0020 单独硬化,不重写)
- ✅ Vault 数据格式 / Markdown + frontmatter / `.knowlet/` 状态目录
- ✅ Token 系统(纸感浅色 + dark token mirror)— 移植到 Tailwind config + CSS variables
- ✅ ADR / 设计 brief / dogfood 报告 — 历史记录,不动
- ✅ 363+ 后端测试

### 选择 React 不是 Vue / Svelte / Solid 的理由

直接给:**生态压倒性**。

- 我们要用的具体库(AI SDK / shadcn / CodeMirror React wrapper / react-arborist / Tanstack Query)**旗舰版本全是 React**
- Vue 也能用,但很多组件库 React 优先,Vue 移植版滞后 / 缺
- Svelte / Solid 更小 + 更现代,但**重蹈 Alpine 覆辙**(生态偏门 + agent 训练数据少)

### 不混合 Alpine + React 的理由

(2026-05-05 上一轮讨论中我提过混合方案,被否决):

- 两套 paradigm 共存:状态分裂 + 心智成本翻倍 + glue 是新 bug 温床
- 同一组件双重维护(capsule 在 Alpine 渲染 + 在 React chat 里渲染)
- 过渡期长,迁移期间任何 bug 都得在两边查

**当前是开发期**(per [ADR-0022](./0022-product-lifecycle-phases.md))— 没有兼容包袱,允许一刀切。

### 不引入后端 TypeScript / 全栈单语言的理由

详见 5/5 对话:LLM / ML 生态(sentence-transformers / trafilatura / OpenAI SDK / 各家 SDK 新 model 跟进速度)Python 仍然是头等公民。后端不重写。

## 实施切片

详见 [ADR-0021](./0021-knowledge-base-first-roadmap.md)。简要:

```
Phase 0  ADR + Vite/React 脚手架 + 后端 hardening 并行         (2-3 天)
Phase 1  知识库基线 A(file ops)+ B(编辑器)+ C(连接)        (4-5 周)
Phase 2  知识库 D(入口 + 模板 + Daily notes)+ E(版本 / 导入导出) (1-2 周,可推)
Phase 3  AI 能力在新 React 重做(chat / 胶囊 / quiz / mining / web search) (3-4 周)
Phase 4  整体 dogfood + ADR-0018 数据耐久 + 灰度期准备
```

### 文件布局

```
knowlet/
├── web/                  ← 旧 Alpine UI(将整个删除,用 git 历史可查)
│   └── static/           
└── frontend/             ← 新 React UI
    ├── package.json
    ├── vite.config.ts
    ├── tsconfig.json
    ├── tailwind.config.ts
    ├── src/
    │   ├── main.tsx
    │   ├── App.tsx
    │   ├── components/   shadcn-derived + 自定义
    │   ├── routes/       react-router 或 tanstack-router
    │   ├── lib/          API client / utils
    │   ├── stores/       少量全局状态(Zustand / Tanstack Query 为主)
    │   └── styles/       Tailwind + CSS variables(纸感 + dark)
    └── tests/            Vitest + Playwright
```

后端继续从 `knowlet/web/server.py` 起 FastAPI;Vite dev server 反向代理 `/api/*`;构建产出从 `frontend/dist/` 通过 FastAPI 静态托管。

### 旧 Alpine UI 删除策略

**当前是开发期**:不需要 dual-render / feature flag。Phase 1 第一个 slice ship 时,直接删 `knowlet/web/static/` 整个目录(留 git 历史)。

期间(Phase 0 → Phase 1 的 1 周内)如果有人需要 dogfood 旧 UI,checkout 之前的 commit 即可。

## Consequences

### Positive

- **现成组件**:chat UI 的所有 bug 借用 AI SDK 一笔勾销;file tree 借 react-arborist 跟齐 Obsidian;palette 借 cmdk
- **TypeScript 静态类型**:重构安全(改字段名 → 17 处编译错误),消灭一大类 runtime 错误
- **agent 友好**:LLM 训练数据 React + TS 密度最高,后续 agent 维护好得多
- **owner 看得懂**:项目负责人作为 React 受众内行,可以阅读 / 评审代码
- **e2e 测试有路径**:Playwright + chat e2e 测试是 Phase 1 必备,陈年的"chat 全栈无测试"问题被堵
- **设计 token 复用**:paper-light + dark CSS variables 是纯 CSS,不绑 Alpine,移植 0 成本

### Negative

- **重写代价大**:~2000 行 app.js + 1100 行 index.html 全部丢,加上多个 ADR / memory 引用 Alpine 部分需 amend
- **学习曲线**(我作为 agent):shadcn / AI SDK / cmdk / Tanstack Query / CodeMirror 6 每个都有上手成本
- **新依赖**:从"几个 CDN script" 变成"npm 工具链"(node + bun / npm + lockfile + build step)
- **Bundle size**:从 vanilla ~200KB 变成 React + 组件库 ~500KB-1MB(production gzip)— 单用户 desktop 无所谓,但需要诚实记录

### Mitigations

- 重写代价:开发期没用户,完全可控
- 学习曲线:先 Phase 0 起脚手架(不实际写功能),让我熟悉栈;Phase 1 才写 production code
- 新依赖:lockfile 进 git;`uv sync` 等价物用 `bun install --frozen-lockfile`
- Bundle size:Vite tree-shake + lazy-load(focus modes 按需加载)+ shadcn 是 copy-paste 不是预编译库

### Out of scope

- React Native / mobile native(per ADR-0003 阶段二)
- SSR / Next.js — knowlet 是 single-user localhost,SPA 已足
- State management 重型方案(Redux Toolkit / Zustand 全局)— Tanstack Query 处理 server state,组件本地 state 用 React useState 即可

## References

- [ADR-0011](./0011-web-ui-redesign.md) §"Stack" — 本 ADR supersede
- [ADR-0020](./0020-backend-python-discipline.md) — 后端硬化(并行,不重写)
- [ADR-0021](./0021-knowledge-base-first-roadmap.md) — 实施顺序
- [ADR-0022](./0022-product-lifecycle-phases.md) — 开发期允许激进迭代,本 ADR 不需要兼容包袱
- [Dogfood 报告 2026-05-04](../dogfood/M7-M8.1-report-2026-05-04.md) — 触发本次重写决策的原始信号
- [Claude Design 2nd pass bundle](../design/bundle-2026-05-04/) — 视觉 / 交互参考(将在 React 实施时映射)
