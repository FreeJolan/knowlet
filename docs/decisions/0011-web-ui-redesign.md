# 0011 — Web UI 重设计:笔记软件本位 + Focus Modes

> [English](./0011-web-ui-redesign.en.md) | **中文**

- Status: Proposed
- Date: 2026-05-01

## Context

ADR-0003 把 knowlet 字面定位为 "**个人知识库 + AI 长期记忆层**" —— **笔记是主体,AI 是组织手段**。

但 M0–M4 累积出来的 web UI 是 chat-first 形态:chat 占 70% 屏幕、Notes / Cards / Drafts 是 30% 右侧栏 widget。这跟 ChatGPT / Claude.ai 等"agent + context sidebar" 完全同形,**违反 ADR-0003 的字面承诺**。

用户在 2026-05-01 dogfood 实验 2 后明确指出:

> 我对整体 UI 设计和交互设计都比较不满,难道这套设计只是 MVP 阶段凑合用,后续会直接全部丢弃吗?如果你打算只是小修小补或者只是往上边堆积功能,我会十分不满。
> 我们已经多次确认 knowlet 本质是一款笔记软件,但是现在呢?看界面感觉是个 agent 套壳。
> 也许我们应该先对整体 UI 设计有个基本的思路和认知,定下一些基础的基调或选型。

需要在动代码之前**先用 ADR 把信息架构和设计基调钉死**。本 ADR 就是这件事。

为了避免"开发者一个人决定产品级 UI 形态"的风险,本 ADR 的方向选定基于:

1. 用户在 2026-05-01 选定的方向 = **Obsidian-style + Focus Modes**(笔记本位,工作流时全屏聚焦)
2. 三次独立 Claude 咨询(`Agent` 工具,fresh-eyes 不带本项目上下文),分别从 ① 直接设计、② pitfall 警示、③ 跨产品 IA 比较 三个角度给意见 —— 三方在四个核心点上高度一致
3. 项目原则:ADR-0008 CLI parity discipline、ADR-0002 数据主权、no-hidden-debt memory

## Decision

### 1. 三栏布局(Obsidian-style)

```
┌──────────────────────────────────────────────────────────────────┐
│ knowlet  vault·model·lang             [icons]  [Cmd+K palette]  │  ← header (32px)
├──────────────┬───────────────────────────────┬──────────────────┤
│              │                               │                  │
│   vault tree │       Note editor / view      │   Right rail     │
│   (notes/    │       (tab bar + content)     │   (collapsible   │
│    only)     │                               │    to 32px rail) │
│   18%        │       54%                     │   28% / 32px     │
│              │                               │                  │
├──────────────┴───────────────────────────────┴──────────────────┤
│ [Drafts ●12] [Cards ●3] [Mining ●HF blog]   [v0.0.1 · zh]      │  ← footer (28px)
└──────────────────────────────────────────────────────────────────┘
```

- **左栏(18%)**:vault file tree;**只显示 `<vault>/notes/`**(树形,跟 Obsidian 一样)。顶上一个 fuzzy-search box / new note 按钮。
- **中栏(54%)**:Note 编辑/查看区域。tab bar 支持多 Note 同时打开;面包屑 + 状态栏(字数 / 修改时间 / 语言)。
- **右栏(28%,默认折叠到 32px rail)**:三块叠放可折叠区:**Outline** / **Backlinks** / **AI**。AI 是 dock 形态的小 chat 条,scope toggle("这条 Note" / "整个 vault" / "无 context"),默认 scope = 当前 Note。
- **底部状态栏(28px)**:`drafts` / `cards` / `mining` 三个图标,分别带计数。点击 → 进对应 focus mode。
- **顶部 header(32px)**:logo + vault meta + Cmd+K 命令面板入口 + 几个 icon 按钮(profile / 全屏 / 主题 等)。
- 所有面板可拖动 resize,布局 preference 持久化在 localStorage。

### 2. File tree 只显示 `notes/`

**不暴露 `cards/` `drafts/` `tasks/` `users/`。** 这些是用户拥有的文件没错(数据主权),但**它们不是用户用 file tree 浏览/编辑的对象**:

- `cards/` 是 SRS 调度数据,JSON,看了也没用
- `drafts/` 是 AI 草稿队列,review 完就消失,放在 tree 里显得永久
- `tasks/` 是配置而不是内容
- `users/me.md` 是用户档案,跟工具栏 "profile" 按钮重复

**进入这些区域的入口**:
- 底部状态栏图标(快速查看 + 入 focus mode)
- 命令面板(Cmd+K → 输入 "drafts" / "cards" / "task" 即出条目)
- CLI 始终可达(`knowlet drafts list` 等)

ADR-0002 数据主权字面成立 —— 文件还在用户 vault 里,他们用 Finder / Obsidian 看得到;但**knowlet 自己的 web UI 不喧宾夺主地把它们当 first-class 文件夹**。

### 3. AI 在右栏默认折叠

AI 不是中央广场,是**按需召唤的合作者**。表现:

- 右栏 AI 区域**默认折叠到 32px 竖向 rail**。rail 上是 AI logo + 当前 chat 状态(idle / thinking / 几条消息)。
- 点击展开 → 一个 dock 形态的小 chat,**scope 默认绑定当前 Note**(每条用户 message 自动 prepend "context: this note title + body excerpt")。
- scope toggle 在 dock 顶部:**这条 Note** / **整个 vault** / **无 context**(默认顺序,可切换)。
- 长对话进 chat focus mode(Cmd+Shift+C),里头才是完整的 chat history + multi-session sidebar。

### 4. 命令面板(Cmd+K)是主导航

**Cmd+K 统一所有动作入口**,替代当前 chat-first UI 顶部那一排杂乱按钮:

- **快速跳转 Note**:输入名称 → fuzzy match → 回车打开
- **运行命令**:`reindex` / `run mining` / `cards review` / `doctor` / `clear chat` 等(每个对应一个 CLI 命令,符合 ADR-0008 parity)
- **问 AI(prefix `>`)**:`> 这周我读过什么关于 RAG?` → 直接发到 AI 一次性回答(不进 chat history;就地 popup)
- **创建新 Note**:`+ <title>` 或 `new note <title>`

**Cmd+P** 是单纯的 note quick-switcher(纯 fuzzy 搜文件名,不混杂命令)—— 高频使用所以保留独立快捷键。

### 5. Focus Modes

**三个**(用户 2026-05-01 明确要求):

| 模式 | 触发 | 出 | 状态保留 |
|---|---|---|---|
| Chat focus | `Cmd+Shift+C` / 点 AI rail "expand" 图标 | `Esc` | 外层 layout / 打开的 Notes / 滚动位置 |
| Drafts review | `Cmd+Shift+D` / 点底栏 drafts 图标 | `Esc` | 同上 |
| Cards review | `Cmd+Shift+R` / 点底栏 cards 图标 | `Esc` | 同上 |

每个 focus mode 是**全屏 overlay**(不导航);Esc 出 → 完全回到原来的位置(光标 / 选区 / 滚动条都恢复)。

### 6. Drafts 计数:不要做成收件箱地狱

A2 pitfall #3 的具体应对:

- 底部状态栏的 `drafts` 图标:**计数 ≤ 9 显示数字;> 9 显示 `9+`;> 50 红色 "inbox 满了" 提示而非计数**
- drafts focus mode 顶部:展示当前 batch 大小(默认按 task / source / created_at 切片,不全部一次给)
- mining task 加 `max_keep` 字段(默认 30):新草稿超出阈值,**最旧的自动 archive 而不是排队**(archive 是软删,可恢复;不会污染主 list)

### 7. Backlinks 句子级预览(M6 phase 2)

**当前 phase 1 不做** —— backlinks 实现复杂,先空着不渲染。

未来形态(M6 phase 2):右栏 Backlinks 区,每条 backlink 显示**包含 `[[link]]` 的那段话**(段级预览),不是单纯 note 标题列表。点击 → 跳转;Cmd+点击 → 在新 tab 打开。

### 8. 空 vault 第一启动

- 中栏:打开 `users/me.md` 模板,编辑模式,template 提示"你是谁?想记什么?"
- 左栏:空 file tree,提示"Cmd+N 创建第一条 Note"
- 右栏:折叠
- 底栏:零计数
- **不弹模态向导**;不强迫先 setup

### 9. 不做 / 显式 defer

- ❌ Graph view —— A2 / A3 一致认为是"漂亮但每月用一次"的虚荣特性,本 ADR 显式不做
- ⏳ CodeMirror 编辑器 —— defer 到 M7+;M6 继续用 `<textarea>` + marked.js preview(全屏编辑器已经做过了)
- ⏳ 内联 slash 菜单 / 选区 AI 操作("summarize this", "make a card from this") —— defer 到 M7+;先保证 chat dock 形态稳定
- ⏳ 拖拽重排 / 多选批量操作 —— defer

### 10. 实施分阶段(M6 切片)

| Phase | 范围 | 目标 |
|---|---|---|
| **M6.0** | wireframe(HTML mock + 文字描述) | 用户 review 后才动代码 |
| **M6.1** | 三栏布局 + file tree(只 notes/)+ Markdown viewer/editor 中栏 + 右栏折叠 rail | 笔记本位的 default view 立起来,chat 暂时去到 focus mode |
| **M6.2** | Cmd+K 命令面板(open note / 命令 / `>` ask AI) | 主导航替换当前顶部按钮排 |
| **M6.3** | 三个 Focus Modes(chat / drafts / cards) | 工作流体验完整 |
| **M6.4** | 多会话 chat history(从 `project_knowlet_multi_session_chat` memory)+ chat focus 内的 session sidebar | scenario A 长期可用 |
| **M6.5** | drafts 计数 cap + max_keep + 底栏样式打磨 | 防"未读 247"地狱 |

每个 phase 独立 commit + 独立 tag(`m6.0` … `m6.5`),phase 之间用户都能完整使用前一阶段功能。

## Consequences

### 好处

- **产品定位字面成立**:打开 knowlet 看到 vault tree + Note 中央 = "这是个笔记软件",不再像 agent 套壳
- **AI 不喧宾夺主**:右栏默认折叠,Cmd+K 入口、focus mode 入口、底栏入口随时可达,但用户写笔记时不被打扰
- **Cmd+K 是单一权威入口**:符合 ADR-0008 CLI parity discipline,每条 palette 条目一一对应一条 CLI 命令
- **Focus mode 解决"工作流期间需要全屏"的真实需求**:不必跟"日常笔记本位"互相牺牲
- **drafts 焦虑被设计层面预防**:不会重蹈"未读 247"的产品 fail
- **graph 等虚荣功能显式不做**:开发资源集中,不被截图驱动

### 代价 / 约束

- **当前 `knowlet/web/static/*` 几乎完全重写**:`index.html` / `app.js` / `app.css` 都得改;但 backend API 全部保留(ADR-0008 的红利)
- **新增 backend endpoints**:Note 全文 fuzzy search(给 Cmd+K)、Notes/CRUD endpoints(目前只读)、Backlinks API(M6.2+)
- **多会话 chat history** 是 ADR-0003 字面承诺却一直没做的事,M6.4 必须做 —— 牵涉 conversation log + storage schema + UI session sidebar
- **vanilla JS + DOM 写三栏 + drag resize + tab bar + 命令面板**比想象中工程量大;不引入 SPA 框架的承诺不变(per `feedback_no_wheel_reinvention`),但部分组件(命令面板)考虑用 ~30 行的极简自写,不拉 fzf-for-js 这种库
- **CodeMirror defer**:textarea + preview 的体验不如 CodeMirror,但够 M6 用,M7 再升级

### 与现有 ADR / memory 的关系

- 落实 [ADR-0003](./0003-wedge-pivot-ai-memory-layer.md) 字面承诺(笔记主体,AI 长期记忆层)
- 遵循 [ADR-0008](./0008-cli-parity-discipline.md):Cmd+K 每条命令 = 一条 CLI 命令的薄壳;backend API 不动
- 遵循 [ADR-0002](./0002-core-principles.md):用户文件仍可见(file tree + 系统底栏 + CLI),数据主权不损失
- 触发 [project_knowlet_multi_session_chat](memory) 必须在 M6.4 实现,不能再 defer
- 解决 [project_knowlet_ui_redesign_pending](memory) 提出的所有具体不满

## Open questions — 用户已确认按推荐走(2026-05-01)

1. ✅ 命令面板里 `>` prefix ask-AI:**就地 popup 一次性回答**
2. ✅ 多会话 chat 标题:**首条 user message 后台延迟 LLM 摘要,自动起**
3. ✅ 主题(2026-05-02 翻案):**纸感浅色为默认骨干,暗色保留为可选 toggle**。原因:knowlet 字面定位是"笔记软件",纸感浅色是阅读 / 写作长时间停留的天然底子(Bear / Ulysses / Notion / Apple Notes 的默认形态);暗色作为"夜间 / 高对比偏好"的可选项保留,但不是基线。具体 token 值(`--bg` 接近书页米白而非纯白、`--surface` 略深做层级、`--text` 用近黑而非纯黑、`--accent` 在浅底上重新校准)等 Claude Design mock 回来后再敲定;wireframe.html 当前的暗色 token 仅作历史参考,M6.x 实施时一次性换掉。
4. ✏️ 字体(看完 wireframe v1 后用户翻案,2026-05-01):**正文 sans-serif(Inter / 系统中文)+ 代码 / 路径 / ID / 快捷键 monospace**。原因:全 monospace 渲染出来"太 geek",像 VS Code 而非笔记软件。同步把 ASCII 几何 icon(▸ ↩ ✦)换成 inline SVG(heroicons 风格,~12 个);accent 色具体值随主题翻案一并在浅底上重新校准(原暗底版本 #92b3dc 不再适用)。

## 11. Tech stack(2026-05-01 用户确认按推荐走)

### 选定

**Tailwind CSS + Alpine.js + Split.js + 自写薄组件层。**

不引入 React / Vue / 任何 SPA framework;不引入 Daisy UI / Naive UI / shadcn 等 pre-styled component lib(原因下面)。

### 否决方案的简短理由

不引入的:**React / Vue / SPA framework**(50+ MB node_modules + 构建管道,违反 ADR-0002 精简 / 可分发);**DaisyUI / Naive UI / shadcn 等 pre-styled component lib**(调性都是"现代 SaaS 风",跟 knowlet"终端 + 信息密集"冲突,override 70% 反而比自写累);**htmx + server-rendered**(拖拽 resize / 命令面板 / 实时多面板编辑这类 client-heavy 交互不够)。详细对比见 git history。

### 为什么是 Tailwind + Alpine + Split

**1. Tailwind = 颜色 / 间距 / 排版的"封装库"(token 层而非组件层)**

- 一份 `tailwind.config.js` + 一份 CSS custom properties 决定**全部** token:颜色(`--bg`/`--surface`/`--text`/`--accent` …)、字号(`text-sm` / `text-base` …)、间距(`p-2` / `gap-3` …)、圆角(`rounded` / `rounded-lg` …)
- 主题骨干已定为纸感浅色(2026-05-02 翻案);暗色作为可选 toggle = 改 config / 改 CSS variables → 整个 app 自动重 theme
- 不引入 lib 的组件外观 —— 自己用 utility class 组装的组件天然维持 knowlet 终端 monospace 调性
- AI assistants(包括未来 Claude session)对 Tailwind 极熟,改起来快

**2. Alpine.js(15 kb)= 声明式状态,不是 SPA framework**

- 用于:命令面板下拉、模态开关、tab 切换、focus mode 进出、resize 状态、theme toggle
- 写法:HTML 属性内联 `x-data="{ open: false }"` / `x-show="open"` / `@click="open = !open"`
- **不需要 build step,不需要 virtual DOM,不需要 component model**
- 读起来跟 HTML 一样直观;调试在浏览器 devtools 里就够

**3. Split.js(3 kb)= 拖拽 resize**

- 三栏布局必须的拖拽 handle
- API 简单:`Split([leftEl, midEl, rightEl], { sizes: [18, 54, 28] })`
- 状态可以序列化到 localStorage 保留用户布局偏好

**4. 自写 8-10 个薄组件层(~200 行 HTML 模板 + Tailwind classes)**

每个组件就是一个 HTML partial + 一组 Tailwind utility class 约定:

| 组件 | 用在 |
|---|---|
| `button` | 各处。primary / ghost / icon-only / danger 4 种变体 |
| `input` / `textarea` | composer / palette / 编辑器中央 / profile 模态 |
| `modal-card` | drafts focus / cards focus / chat focus / profile editor / draft commit |
| `tab-bar` | 中栏多个 Note tab / 命令面板分类切换 |
| `panel-section` | 右栏 Outline / Backlinks / AI 三块 |
| `file-tree-node` | 左栏递归节点(展开 / 折叠 / 选中状态) |
| `palette-item` | Cmd+K 命令面板每行 |
| `status-icon` | 底部状态栏的 drafts / cards / mining 入口(带计数) |
| `tooltip` | hover 显示原文 / 解释 / 快捷键提示 |
| `toast` | 已有 |

每个 ≤ 30 行。共享同一 token base 所以一致性自动成立。

### bundle 预算(release 时)

- Tailwind purged CSS: ~10 kb gzipped
- Alpine.js: ~15 kb
- Split.js: ~3 kb
- marked.js(已有,不动): ~30 kb
- 自写 app.js: 估 ~15 kb(目前有 ~12 kb)
- **总:~75 kb gzipped**

参考:React + shadcn 全套 ~250 kb;Vue 3 + Naive UI ~500 kb。我们这个数量级差异。

### Build pipeline 取舍

- **Dev**:Tailwind 用 CDN play script(`https://cdn.tailwindcss.com`),JIT 实时编译,改 HTML 立刻生效。Alpine / marked / Split 全部 CDN ESM。**完全 build-step-free**,跟当前现状一样
- **Release**(commit 进 main 时跑一次):`npx @tailwindcss/cli -i input.css -o static/dist/tailwind.css --minify` 把 utility class purge + 压缩到 ~10 kb 静态文件,FastAPI serve 出去
- **CI**:加一条 `tailwind --check` 验证没有用 undefined 的 class
- **不引入 PostCSS / Vite / esbuild / webpack 等更复杂的构建工具**

### 与现有 ADR / memory 的关系

- 遵循 [ADR-0008](./0008-cli-parity-discipline.md):backend 函数 + API 完全不动,Alpine 只是 wire HTML ↔ fetch 的薄胶
- 遵循 `feedback_no_wheel_reinvention` memory:**这条 memory 反对的是 "framework abstractions over LLM workflows"(LangChain / LlamaIndex)和"API 不稳定的依赖"**;Tailwind / Alpine / Split 都是 6+ 年成熟、API 稳定、社区大、AI assistant 熟练度高的工具。**自写薄组件**完全契合 memory 里"实现简单的小工具可以自造"那条
- 遵循 [ADR-0002](./0002-core-principles.md):没有引入构建期间联网拉远端服务的依赖;CDN 是开发期可选,release 后是 self-contained 静态文件
- 解决用户提出的"颜色 / 组件等的封装库"问题:**封装在 token 层而非组件层**

### 演化路径

- M6 全程用本栈
- M7 视情况:CodeMirror 6(替代 textarea)→ 一个 ~150 kb 的真编辑器,但 tree-shake 后 ~50 kb;独立成自己的"Editor 区域",不污染其他组件
- M8 视情况:加**暗色可选 toggle**(浅色已是默认骨干;暗色 token 一次性补齐,加 header / 设置里的切换控件 + localStorage 持久化 + 跟随系统选项)
- M5 / M9 Tauri 桌面壳:同套 `knowlet/web/static/` 直接打包进 Tauri,不需要重写

## Amendment(2026-05-04 协同 ADR-0003 修订)

§"## Consequences" 写道:

> graph 等虚荣功能显式不做 —— 开发资源集中,不被截图驱动

**这条撤销。** 跟 [ADR-0003 amendment(2026-05-04)](./0003-wedge-pivot-ai-memory-layer.md#amendment2026-05-04-用户拨乱反正)
一致 —— 双链 + 图谱是知识软件的核心能力,不是"虚荣 / 截图驱动"的可有可无装饰。

修正后的姿态:

- **图谱 view 重新进入路线图**(目标:M8 阶段;具体落点视 Claude Design 第二轮回件而定)
- 但保留原 ADR 的另一意图:**graph view 不该成为产品卖点叙事的主轴**(那才是"截图驱动")。
  图谱是用户已经写好的链接关系的可视化,跟 cluster / 近重复 / 孤儿 等 LLM 推断信号
  (ADR-0013 §3 Layer B)是**互补**的两层。
- M7.0.4 已 ship 的 wikilinks `[[Title]]` + 反链面板是双链的"列表形态"(commit
  62b4d6e);M8 加图谱形态作为同一组数据的另一种 view,不是另起炉灶。

§"显式不做"清单中的其他几项(团队协作 / 移动原生 / etc)**不变**。
