# 仓库UI重设计

_Started 2026-05-01 16:30 UTC_

---

## User



## Assistant

I'll design Knowlet as an original concept — a warm dark, paper-leather note-taking app. The user gave a very strong, specific brief, so I'll commit to a single opinionated direction rather than asking questions.

Let me check the napkin sketch first, then plan.

_[tool: list_files]_

_[tool: list_files]_

No thumbnail available, so I'll work from the brief. Here's my plan:

**Design direction (committing):**
- **Accent**: muted plum (~#a48bb0) — warmer than slate-blue, less expected than sand, suits "calm study at dusk"
- **Background**: paper-leather #1c1d22, with #232428 panels and #2b2c31 cards
- **Type**: Inter (body/UI), Source Serif Pro (headings, sparingly), JetBrains Mono (code/paths/timestamps only)
- **Layout**: design_canvas with 4 artboards — Home (1440×900, primary), Inbox (1200×800), Card Review (1200×800), ⌘K Palette (1200×800)

Let me set up the project.

_[tool: update_todos]_

_[tool: copy_starter_component]_

Now let me build the screens. I'll create them as separate component files to keep things modular.

_[tool: write_file]_

Now the icons + shared components file:

_[tool: write_file]_

Now Screen 1 — the Home view (the most important one):

_[tool: write_file]_

_[tool: snip]_

_[tool: write_file]_

_[tool: write_file]_

_[tool: write_file]_

Now the main HTML file that pulls everything together:

_[tool: write_file]_

_[tool: show_html]_

_[tool: snip]_

_[tool: done]_

_[tool: fork_verifier_agent]_

Built **Knowlet** — 4 artboards on a design canvas:

1. **Home** (1440×900) — three-column with sidebar tree, markdown editor showing CJK + English RAG notes with code, and the AI panel docked right (context selector → "This note", a 2-turn conversation with cited sources, composer at the bottom).
2. **Inbox focus** (1200×800) — single AI-summarized item, max-width ~720px, source link + tags + key points, three actions with "Keep as note" as the primary.
3. **Card review** (1200×800) — large CJK front side ("RRF 中 k 的典型值是多少？为什么？"), Reveal-answer button, four rating buttons with Good highlighted, FSRS interval hint.
4. **⌘K palette** (1200×800) — floating 640px panel near top, Notes / Commands / Ask AI sections, kbd footer.

**Direction committed:** muted plum accent (#a48bb0), paper-leather background (#1c1d22 / #232428 / #2c2d32), warm off-white text (#e7e3d9). Inter for UI, Source Serif 4 for headings (and the front of flashcards for warmth), JetBrains Mono restricted to code, file paths, timestamps, and kbd hints. Soft accent-tinted highlight for the active item and AI assistant bubbles — no neon, no gradients, no terminal vibes.

Drag artboards to reorder, click any label to focus fullscreen.

## User

GitHub connected

## Assistant

Hi! GitHub's connected — feel free to paste a repo URL if you'd like me to pull design context (theme files, components, brand assets) from a codebase. I can explore the structure and import specific files to ground the next iteration of Knowlet in real source material.

_[tool: snip]_

_[tool: snip]_

Ready when you are — paste a GitHub URL, give me feedback on the screens, or point me at the next thing to build.

## User

仓库地址是 ：https://github.com/FreeJolan/knowlet
我必须提一下，我现在对仓库里当前的 UI 设计并不满意。

## Assistant

_[tool: github_get_tree]_

明白 — 我来探索仓库，重点关注现有的 UI/前端代码、配置和功能定义。我不打算复制现有 UI，而是确认实际的功能、数据模型、约束，然后基于此重做。

_[tool: github_get_tree]_

_[tool: github_read_file]_

_[tool: github_get_tree]_

_[tool: snip]_

_[tool: github_read_file]_

_[tool: github_get_tree]_

_[tool: snip]_

_[tool: github_read_file]_

_[tool: github_read_file]_

_[tool: snip]_

我对你的现状做了完整调研。三件关键事实:

1. **ADR-0011 已经把方向钉死**:Obsidian-style 三栏 + Focus Modes、AI 默认折叠到右栏 rail、Cmd+K 是主导航、不做 graph view、不做 inbox 地狱。我的第一版完全没读到这份 ADR,导致 AI panel 给得太大、底栏没有 drafts/cards/mining 三个状态入口、tab 栏过厚 —— 跟你字面承诺的"笔记软件本位"还是有距离。
2. **wireframe.html 已经定好了 token 与 stack**:`#191b1f / #212329 / #92b3dc`(柔化的暗蓝)、Tailwind + Alpine + Split.js,正文 sans + monospace 仅限路径/快捷键/代码。
3. **你说"对仓库当前 UI 不满"** —— 看了 `wireframe.html`,我的判断是:它 IA 对了(三栏 + Cmd+K + focus modes 都按 ADR 做了),但**视觉气质**还是太"工具感":灰度过于均匀、accent 只是高光、没有"纸-皮革"的暖度、阶层不清晰、focus mode 跟主界面气质割裂。

所以接下来我会做的不是"再画一组好看的图",而是:

**带着 ADR-0011 的字面 IA 约束 + 你 wireframe 的 token,给出一份气质拉满的视觉重做**,落点是 4 张可直接对照 wireframe 的高保真画面。具体几个动作:

- **抛掉**当前 `Knowlet.html` 里那个 Obsidian + Bear 自由发挥版,因为它违反了 ADR-0011(AI 占了 380px 而不是默认折叠;状态栏没有 drafts/cards/mining 计数;tab 栏过重)。
- **新版本以 wireframe.html 的 IA 为骨架,但视觉上彻底重做**:
  - 暖化背景 `#191b1f → #1c1d22`(纸皮革),保留你定的 `#92b3dc` accent,但把它降一档明度变成更温柔的 dusk 蓝 `#8aa9c9`(你 brief 里也写了这个候选)。
  - **AI 右栏默认折叠到 32px rail**(不是我之前给的 380px panel)。
  - **底栏 drafts ●12 / cards ●3 / mining HF blog** 三个 status icon,完全按 ADR-0011 §6 计数策略。
  - **三个 focus mode 视觉统一**:同一个浅渐隐底色、同样的"Esc 退出"右上角、同样的 max-width 720 阅读列。

我会做的 4 张画面正好对应你 brief 的 4 个,但每一张都跟 wireframe 的 IA 一一对应、互相能 review:Home(三栏 + AI 折叠)、Drafts focus、Cards focus、Cmd+K palette。

要我现在直接动手重做吗?或者你想先就两件事拍板:

- **AI rail 默认折叠还是默认展开**?(ADR-0011 写的是默认折叠到 32px;但 dogfood 中你可能其实希望默认展开。我倾向严格执行 ADR-0011。)
- **accent 走哪个色**?(`#92b3dc` 已落库的 dusk 蓝、还是我这版的 `#a48bb0` 低饱和 plum。两个都不"现代 SaaS 风",我倾向 dusk 蓝因为它已写在 ADR 里了,但 plum 更暖、更"夜晚书房"。)

你拍一下,我就动手。

## User

按照你的倾向走

## Assistant

_[tool: snip]_

按倾向定:**AI rail 默认折叠**(严格走 ADR-0011),**accent = dusk 蓝 `#8aa9c9`**(已落库 `#92b3dc` 的下一档,更柔)。开始重做。

_[tool: write_file]_

_[tool: snip]_

_[tool: write_file]_

[Snipping completed earlier work to free context.]

_[tool: snip]_

_[tool: write_file]_

_[tool: write_file]_

_[tool: write_file]_

_[tool: write_file]_

[Snipping resolved phases.]

_[tool: snip]_

_[tool: write_file]_

_[tool: snip]_

_[tool: done]_

_[tool: snip]_

_[tool: fork_verifier_agent]_

v2 已经按 ADR-0011 重做完毕,4 张画面对应 wireframe 的 IA:

1. **Home(1440×900)** — 三栏:左 240px vault tree(只显示 `notes/`)、中是 Note + tab 栏 + 编辑/双栏/预览模式切换,右栏默认折叠到 40px rail(大纲 / 反链 / AI 三个图标)。底部状态栏 drafts `9+` / cards `3` / mining `HF blog daily` 三个入口,严格走 ADR-0011 §6 的计数策略。
2. **草稿审查(1280×820)** — Cmd+Shift+D。720 阅读列、source + task meta、AI 总结正文、key points、保存路径预览;底部「拒绝 / 跳过 / 通过 → notes/」三键 + JK 翻页提示。
3. **卡片复习(1280×820)** — Cmd+Shift+R。FSRS,大字 serif 中文卡面、虚线 ⏎ 翻面按钮、四个评级按钮在翻面前以 0.4 透明度预占位。
4. **⌘K 命令面板(1280×820)** — 640px 浮窗、三段式 Notes / Commands / Ask AI、底栏写明 `parity: 每条命令 = CLI · ADR-0008`。

视觉系统按你已落库的 token:`#1c1d22 / #212329 / #33363f` + `#8aa9c9` dusk 蓝 accent;正文 sans,monospace 仅限路径 / 时间戳 / 快捷键 / 代码;heroicons 风格 14px 1.6 stroke。

## User

奇怪，我们为什么要坚持黑色为主色调呢

## Assistant

好问题 —— 其实**并不需要**坚持。回头看 ADR-0011 写的是"先暗色一种"作为 M6 的范围限制(只是不分散精力做 light/dark toggle),而不是"暗色才是 knowlet 的本色"。

我之前一路走暗色,是被三个东西带着跑:

1. 你的 brief 第一段就给了"warm dark mode · paper-leather"的明确指示
2. 仓库 `wireframe.html` 也是暗色,`#191b1f`
3. ADR-0011 §"主题"那条:**先暗色一种**

但这三个都只是**当前默认**,不是产品定位。"个人知识库 / 长时间阅读写作"的主流参考(iA Writer / Bear / Reflect / Things 3 — 你 brief 自己列的)其实**默认浅色**,长时间阅读/写作 light theme 普遍更舒服;dark 只是夜间模式。

我的建议是把视觉骨干切到**纸感浅色为默认**,暗色保留为可选。具体:

- **Light(默认)**:背景 `#f6f3ec`(纸,不是纯白)、面板 `#ede8de`、墨色 `#2a2823`、accent 还是 dusk 蓝 `#5b7a9c`(浅底下要降明度)。气质:iA Writer / Bear 浅色那种"灯下纸面"。
- **Dark(可选,即现在的版本)**:`#1c1d22 / #212329 / #8aa9c9`,留作夜间。
- 让 4 张画面都出 light 版,dark 版作为 Tweak 切换。

要我直接动手切到 light 默认吗?或者你想看 light 的一张样张再定?

## User

直接切换吧

## Assistant

_[tool: snip]_

_[tool: str_replace_edit]_

[Quietly snipping resolved phases.]

_[tool: snip]_

_[tool: read_file]_

_[tool: snip]_

_[tool: str_replace_edit]_

_[tool: read_file]_

_[tool: snip]_

The remaining styles read fine for light mode — `--panel-2` is now warm off-white so code blocks, hover states, and tree backgrounds will all sit naturally on the paper. Let me verify visually.

_[tool: done]_

_[tool: fork_verifier_agent]_

切换完成 —— 4 张画面现在都是纸感浅色:`#f4f0e8` 纸底,`#ede7d9` 面板,`#2a2823` 暖墨色文字,accent 降到 `#5b7a9c` 让它在浅底上不刺眼。dark 版本的 token 已经被替换,稍后我可以加回 Tweak 切换让 dark 作为可选夜间模式。等 verifier 回报具体看哪里需要再调。

## User

Verifier agent check completed

## Assistant

Good catch on both. Fixing the palette scrim now and tightening the active tab.

_[tool: grep]_

[Snipping resolved diagnostic.]

_[tool: snip]_

_[tool: str_replace_edit]_

_[tool: str_replace_edit]_

_[tool: done]_

两处都修了:

- **⌘K 面板的暗背**:`rgba(15,16,20,0.55)` → `rgba(90,78,55,0.18)`,改成偏暖的纸色压暗,不再像"灯下纸面里嵌了个暗房"。
- **活动 tab**:加了 2px dusk-blue 顶边 + 用 `--card`(更浅的 `#fbf8f1`)做底色,跟正文背景拉开层级。

## User

给多一张主界面全部展开的图

## Assistant

好 —— 我会加一张 Home 但右栏 AI 完全展开的画面,放在第一张 Home 的旁边作为对照。让我先看一下现有的 Home 结构,然后做一张展开版。

_[tool: list_files]_

_[tool: read_file]_

让我看一下 HomeScreen 是怎么处理 AI 折叠状态的:

_[tool: read_file]_

现在做一个展开版 —— 同样的三栏,但右栏从 40px rail 变成 ~360px AI panel,展示一段对话。

_[tool: write_file]_

[Checking icons used and wiring up.]

_[tool: snip]_

_[tool: grep]_

[Need to add missing icons: Copy, NewNote, Refresh, At, Slash. Then wire it up.]

_[tool: snip]_

_[tool: read_file]_

_[tool: snip]_

_[tool: str_replace_edit]_

_[tool: str_replace_edit]_

_[tool: str_replace_edit]_

_[tool: snip]_

_[tool: done]_

_[tool: snip]_

_[tool: fork_verifier_agent]_

加好了 —— Home 旁边多了一张 **01b · Home — AI 右栏展开**(1440×900),展示 AI 完全展开 (~360px) 的状态:子 tab(大纲 / 反链 / AI)、上下文选择器(当前 Note · +2 已选)、两轮对话 + 引用 [1][2] + 消息 actions(复制 / 作为新 Note / 重新生成)、tool-call placeholder(`generate_card`)、底部 composer (@ 附加 · / 工具 · ⏎ 发送)。

## User

Verifier agent check completed

## Assistant

全过。Home 展开版已就位,5 张画面齐了。

## User

我的 Claude Code 提出了诉求：

## Assistant

[Cleaning context — most prior phases are done.]

_[tool: update_todos]_

_[tool: snip]_

这是个非常扎实的 brief —— 11 个 surface,分两类(8 audit + 3 net-new),底色已经定好,要的是细节精修和新 surface 设计。让我先消化一下 ADR、读一下现有几个 ADR(0011/0013)确认硬约束,然后规划。

_[tool: github_get_tree]_

[Aggressive snip — most older phases are resolved iterations.]

_[tool: snip]_

_[tool: github_read_file]_

_[tool: github_read_file]_

_[tool: github_read_file]_

_[tool: github_read_file]_

_[tool: snip]_

_[tool: snip]_

我读完了 ADR-0011/0013/0014/0015/0016。约束已经吃透,以下是我的处理方案,然后开干。

## 我的整体方案

把 11 个 surface 拆成 **3 个 design 文档**(不是 3 个 HTML —— 那样太散),每个文档对应一个工作流,每个 surface 都是其中的一帧或一个 component spec:

- **Knowlet — Audit.html** —— A 类 8 个,放进现有 Home 三栏 + 全屏 focus 的真实语境里。Quiz focus mode 占独立 section 因为它是 4 阶段长流。
- **Knowlet — New.html** —— B 类 3 个 (knowledge map / digest / dark toggle)。
- **Knowlet — Tokens.html** —— dark token 系统的真实 swatch + 前后对照,1 个文档说清整套。

外加保留你现在看到的 `Knowlet.html` 不动 —— 它是 baseline,新 surface 的"放进真实语境"指的就是这个。

## A 类的关键设计判断(逐个,不啰嗦)

1. **Selection popover** — anchor 只两态:`above`(默认,选区顶 -32px)/ `below`(选区距 viewport top < 80px 时翻);**死活不进 footer / palette / 模式切换器的占用区**,用 collision detection 而不是位置算法。视觉是 `var(--card)` 浮起 + 1px line + 6px radius,不带阴影避免"惊吓"。
2. **Capsule strip** — 5 颗在 340px 内用**水平 wrap 到第二行**,而非压缩单颗。NOTE 和 URL 用**色块差异**而不是图标差异:NOTE = `var(--accent-soft)` 左色条,URL = `var(--bg-1)` 中性灰。Active = 实色边 + ×;sent = 50% 透明 + "再用"hover 变实。
3. **URL banner** — 不要"banner",改为**胶囊 ghost preview**:粘贴后输入框下方直接显示一颗"半透明、虚线边、loading spinner"的 capsule placeholder,跟最终 capsule 同位同形。这样**没有 layout shift**,只是一颗 capsule 从 ghost → solid。
4. **Sediment ambient panel** — 改 ADR-0013 §1 不容许的"建议感"。改为**默认折叠到一行 inline 文字**:`"3 条相关 ↗ Personal energy · Books 2026 reading · Balcony garden"`(纯文字,可点跳转,不带"建议"动词)。展开 = 完整段落预览。这比折叠 details 更轻。
5. **Hover quote tooltip** — 360px max-width 不够,改 **min(420px, 80vw)**;边缘碰撞 → 用 CSS `anchor-name` (新规范) 做 fallback,旧浏览器降级到 `position: absolute` + JS 一行 reposition。CJK 走 1.7 行高 + Source Serif 4 西文 / Noto Serif SC 中文 stack。
6. **Recursive folder tree** — 240px 在 depth ≥ 3 确实会卡。设计上**指南线 + 根行 sticky**:每级用 1px `var(--line-soft)` 竖向 guide(像 GitHub web),depth × 12px(从 14 缩到 12),root 折叠态 sticky 到 tree 顶部。
7. **Backlinks panel** — 列表按 source note group,**句子用前后省略号 + line 号**:`…如 [[RAG 检索策略]] 中描述的 RRF 融合… L24`。`<mark>` 改为 **2px 底色横条**(不是矩形 highlight),accent-soft 上读不清的问题靠"不用块,用线"绕过。
8. **Quiz focus mode** —— **这是大头**,我会做完整 4 阶段:
   - **Scope picker** 重做:不是 100+ 列表,是**两步**——先选 source 类型(单 Note / 多 Note / tag(灰,M7.4.3)/ cluster(灰)),再用 **search-then-pick** 而不是 list-with-checkbox;高级设置走 "≥5 题 / 默认 5" 一行 inline,不开 collapsible。
   - **Loop**:每页一题,左侧题 + 右侧"参考来源 Note(可点开 split)"。
   - **Summary**:per-question 评分卡片;**disagree 不再是两步 confirm**——直接一个 `× 不同意` 按钮,点击 inline 展开理由 textarea(可空),理由 ≠ 必填。Cards 回流"列表内默认全勾"按 ADR-0014 §6 拍板的样式。
   - **History tab** 顶部:列表 + 每条进入查看(只读)。

## B 类的关键设计判断

9. **Knowledge map** —— 不是右栏 sub-tab(挤),开成 **focus mode**(`Cmd+Shift+M`),4 个 signal 横向 4 列(near-dup pairs / clusters / orphans / aging),每列各自独立滚动。**没有动作按钮**,每条只是"点击 → 在新 tab 打开 Note A,split-view 显示 Note B"(对 near-dup pairs)。这把 ADR-0013 §1 落得最干净。
10. **Weekly digest** —— 真做成"周日报"。**全屏阅读体验**(像 Stratechery / NYT digest),Source Serif 4 标题 + 大段 prose 串信号,而不是 dashboard 卡片堆。底部 cadence 配置一行(`下次发布 周日 · 改为 14天 / 30天 / 自定义`)。**没有 read/unread state**,每次打开就是"这一期"。
11. **Dark toggle** + dark token 系统 —— toggle 放**设置**(主入口)+ **Cmd+K 命令**(`dark / light / system`),不进 top bar(占地)。Dark token 严格镜像 light 七色。

我现在动手,先做 Audit 文档(8 个 surface),然后 New 文档,最后 tokens。每个文档完成会单独 done + 你 review。

## User

很好，继续

## Assistant

开干。先建 todo,然后从 Audit 文档开始。

_[tool: update_todos]_

_[tool: list_files]_

先看现有 styles.css 和 home 的结构作为基底,然后建 Audit.html。

_[tool: read_file]_

_[tool: read_file]_

好,我把 home 的视觉语言吃透了。看一下现有的 Knowlet.html 和 icons,确认 import 模式。

_[tool: read_file]_

_[tool: read_file]_

视觉语言我已经吃透了。我需要补几个图标(Quote / BarChart / TreeIndent / Mark / Lightning / Quiz 等)然后开始写 Audit.html。

先把 icons 扩一下,然后建 Audit.html 主文件 + 第一批 surface 文件。

_[tool: str_replace_edit]_

现在写第一批 surface。我把 8 个 audit surface 分成 4 个文件,每文件 ~2 个 surface,主 HTML 放进 design canvas。

先做 surface 1+2+3+4:**selection popover + capsule strip + URL ghost + sediment inline** —— 全部在 Home 三栏的真实语境里展示。

_[tool: write_file]_

_[tool: write_file]_

接下来 surface 3 (URL ghost) + 4 (sediment inline) — 都在 AI 右栏语境。

_[tool: write_file]_

_[tool: write_file]_

现在 surface 5 (hover quote tooltip) + 6 (recursive tree) + 7 (backlinks)。

_[tool: write_file]_

_[tool: write_file]_

_[tool: write_file]_

现在做大头 —— surface 8 (Quiz 4 阶段 focus mode)。这个会比较长,分成 4 个分镜在一个 surface 里水平流动展示,这样用户能看到完整流程。

_[tool: write_file]_

_[tool: snip]_

Now build the Audit.html main file that pulls all 8 surfaces into a design canvas.

_[tool: write_file]_

[Calling snip on completed file-creation phases]

_[tool: snip]_

_[tool: done]_

Empty root — let me check the logs.

_[tool: get_webview_logs]_

直引号嵌套坏掉了。把 `"两路分数"` 用 fancy quotes 修一下。

_[tool: str_replace_edit]_

还有几处也是同样的问题:`"不同意"` 在 button、`"信息检索"` 在 trigram 解释里。我搜一下找全。

_[tool: grep]_

[Calling snip on completed phases]

_[tool: snip]_

_[tool: grep]_

_[tool: snip]_

_[tool: str_replace_edit]_

现在还要检查其他几个 audit 文件,特别是 audit-2-capsules 里的 sent capsule 和别的地方有 nested quotes 的情况。

_[tool: grep]_

干净。再 done 验证一遍。

_[tool: done]_

现在做 New.html 的 3 个 surface — knowledge map / weekly digest / dark toggle。

_[tool: write_file]_

_[tool: write_file]_

_[tool: write_file]_

_[tool: snip]_

_[tool: read_file]_

需要看 Audit.html 的结构,然后照着创建 New.html。

_[tool: list_files]_

_[tool: read_file]_

现在我来创建 New.html 沿用 Audit 的格式:

_[tool: write_file]_

现在检查 icons.jsx 看哪些图标已有,我用了一些可能不存在的:Map, NearDup, Cluster, Orphan, Aging, Refresh, Calendar, Cog, Sun, Moon, Monitor, Search, Dot

_[tool: grep]_

所有 icon 都已存在。Done 验证。

_[tool: done]_

_[tool: update_todos]_

_[tool: fork_verifier_agent]_

New.html 完成 — 3 个全新表面在 design canvas 里:

**09 · 知识图 · 信号面板**(focus mode,⌘⇧M) — 4 列 signal:近重复对 / 语义聚类 / 孤立 note / 老旧未访问。不画图,只列结构问题,每条点击进 split-view。

**10 · 周报 · 阅读视图** — Source Serif 4 长读体,signal 串成 narrative(不是 dashboard 卡片堆),底部 cadence 一行 inline 设置(7/14/30 天)。

**11 · 主题切换** — 设置主入口 (3-way: Light / Dark / 跟随系统 + 3 个子选项) + ⌘K 次入口 + 完整七色 token 镜像表(light → dark 一一对应,不发明 dark 专属色)。原则:top bar 不放 toggle,因为不是高频操作。

剩下 9 项 todo(8 个 audit 表面 + 1 个 Tokens.html)等你确认要不要继续往哪个方向做。

## User

你继续做完

## Assistant

好,继续做剩下的。先做 Tokens.html — 七色 token + dark 镜像 + before/after。然后 Audit.html 我已完整做好,把那 8 项 todo 清掉。

_[tool: update_todos]_

_[tool: grep]_

Token system 完整。现在做 Tokens.html — 设计 token 文档,展示七色系统 + dark 镜像 + before/after 应用。

_[tool: write_file]_

_[tool: write_file]_

把所有 todo 清掉,验证。

_[tool: update_todos]_

_[tool: done]_

#root 空 — Babel 脚本静默失败了。

_[tool: get_webview_logs]_

嵌套引号问题。

_[tool: str_replace_edit]_

_[tool: done]_

还是空 — 可能是缓存或别的问题。

_[tool: get_webview_logs]_

还有一处。

_[tool: str_replace_edit]_

_[tool: grep]_

这些都是合法的(JS 表达式 + ternary/string)。done 验证。

_[tool: done]_

_[tool: fork_verifier_agent]_

全做完了。三个 canvas 文件:

- **Audit.html** — 8 个已存在但需要重做的 surface(selection / capsules / URL ghost / sediment / tooltip / tree / backlinks / quiz 4-phase)
- **New.html** — 3 个全新 surface(知识图 focus / 周报阅读视图 / 主题切换)
- **Tokens.html** — 七色 token 完整 spec + dark 一一镜像 + light/dark 同组件 before/after + type/spacing/radius/shadow

七色 token 系统(`--bg / --ink / --accent / --line / --good / --warn / --danger`)在三份文件之间贯通,dark 严格镜像不发明专属色。

