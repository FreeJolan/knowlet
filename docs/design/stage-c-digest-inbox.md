# Stage C v2 — 资讯审阅与入库

- Status: Implemented through C11 (Source config → Raw Info review → Draft diff → commit → workspace polish → note-like draft surface)
- Date: 2026-05-30
- Roadmap: [`../roadmap/ai-modes-roadmap.md`](../roadmap/ai-modes-roadmap.md)

## 定位

Stage C v2 不是 RSS 阅读器,也不是通用网页采集器。它是
**AI 辅助的信息批阅与入库系统**:外部资讯先以只读原始材料进入
inbox,用户围绕它和 AI 讨论,再决定舍弃或沉淀成可审核的笔记草稿,
最后由用户确认后入库。

核心原则:

- 资讯原文不可修改;它只是外部材料的只读输入。
- 笔记草稿可修改;自由改动发生在草稿阶段。
- 正式笔记必须由用户确认后落库。
- 每个关键动作同时有 UI 控件和 Tool 能力;按钮服务精确控制,对话服务高吞吐。
- AI 可以帮用户按按钮,但不能替用户猜测最终确认。

## 只支持两类来源

Stage C v2 只支持:

1. **RSS Source**
   - 用户提供 RSS / Atom feed URL。
   - 系统拉取 feed item,去重,再归一化为资讯条目。

2. **Prompt Source**
   - 用户提供一个资讯意图,例如"帮我找今天 AI agent 方向的重要更新"。
   - 系统不会直接把用户输入当 prompt 发给模型,而是嵌入 Knowlet
     自己的系统 prompt 模板。
   - 如果用户意图需要实时联网,则依赖当前 LLM capability profile 是否
     具备 hosted web search / fetch 能力;不具备时应显示来源不可可靠运行。

明确不做:

- 不支持"指定网站订阅"或站点爬取型 source。
- 不做 RSS-Bridge / crawler / paywall bypass。
- 不把普通网页 URL 当作长期订阅来源。

## Prompt Source 系统 Prompt

Prompt Source 的流程是:

```text
Knowlet digest system prompt
  + 用户 source prompt
  + 当前日期 / 语言 / 数量限制
  + 已见条目摘要或 URL hash
  -> LLM
  -> 结构化 JSON
  -> schema 校验
  -> 资讯条目
```

系统 prompt 必须包含:

- 角色定位:模型是 Knowlet 的资讯筛选编辑,不是开放式聊天助手。
- 输入说明:用户 prompt 可能很短、粗糙、含糊,甚至只是一个主题或目标。
- 任务说明:生成可供用户批阅的资讯候选。
- 输出约束:只能输出 JSON,不能输出 Markdown、解释文字或代码块。
- 结构化 schema:每条资讯必须能被机器解析。

建议 schema:

```json
{
  "items": [
    {
      "title": "string",
      "url": "https://...",
      "source_name": "string",
      "published_at": "YYYY-MM-DD or null",
      "summary": "string",
      "key_points": ["string"],
      "why_it_matters": "string",
      "suggested_tags": ["string"],
      "confidence": "high | medium | low"
    }
  ],
  "warnings": ["string"]
}
```

默认规则:

- `url` 缺失的条目不进入资讯 inbox,除非用户显式允许无链接灵感类条目。
- `confidence = low` 的条目可以进入 inbox,但 UI 应显示低置信提示。
- schema 校验失败时,记录 source error,不要把自由文本塞进 inbox。

## RSS 处理

RSS item 不能直接等同资讯条目。现实 feed 质量差异很大:

- Hacker News RSS 通常只有标题、链接、发布时间、评论链接;description
  基本只是评论入口。这类 item 不足以直接形成摘要。
- Ars Technica 等 feed 可能包含 description、category、content:encoded
  和 media,但内容通常是 HTML,并混有图片、评论链接、"read full article"
  等噪音,仍需要清洗和摘要。

RSS pipeline:

```text
RSS feed
  -> RawFeedItem(title/link/published/summary/content/categories/media)
  -> 去重(seen URL / guid / content hash)
  -> 内容清洗(HTML -> text,去评论/订阅/脚本噪音)
  -> 单条归一化
  -> InfoItem
```

归一化策略:

- feed item 已有足够正文:清洗后让 AI 生成摘要、关键点、为什么值得看。
- feed item 很薄:尝试 fetch 原链接抽取正文;失败则可入 inbox,但标记
  "摘要不足 / 仅标题来源"。
- 每条 RSS item 单独处理、单独失败、单独重试;不要把整个 feed 一次性
  丢给模型。

## 拉取机制与容量限制

自动拉取:

- 用户每天第一次打开 knowlet 时自动拉取。
- 如果用户一直在线,跨到新的一天后自动拉取一次。
- 每个 source 每天最多自动拉取一次。
- 用户手动"立即拉取"不受每天一次限制。

状态提示:

- App 右上角显示 digest 拉取状态。
- 拉取中:显示正在拉取资讯。
- 完成:短暂显示新增条数。
- 失败:显示失败来源数量,可进入 source 管理查看原因。
- 暂停:待处理资讯超过阈值时显示暂停原因。

容量限制:

- 未处理资讯超过 200 条时停止自动拉取。
- Digest inbox 顶部用一行小提示说明:"未处理资讯超过 200 条,已暂停自动拉取。处理或舍弃一些条目后会恢复。"

## 对象模型

Stage C v2 有三层对象:

1. **Raw Info**
   - 只读。
   - 来自 RSS 或 Prompt Source。
   - 包含原链接、来源、抓取时间、摘要、正文摘录、处理状态。
   - 可讨论、可跳过、可舍弃、可沉淀为草稿。

2. **Note Draft**
   - 可修改。
   - 由 AI 基于 Raw Info、讨论历史和库上下文生成。
   - 包含标题、正文、tags、笔记类型、建议目录、source。
   - 可继续讨论和修正,但尚未进入正式知识库。

3. **Note**
   - 正式笔记。
   - 用户确认落库后才进入 notes、目录、搜索、图谱等正式知识库 surface。

状态机:

```text
Raw Info
  ├─ discuss
  ├─ skip temporarily
  ├─ discard
  └─ create note draft
        ↓
Note Draft
  ├─ edit manually
  ├─ discuss draft
  ├─ propose diff
  ├─ accept/reject diff
  └─ commit
        ↓
Note
```

最终结果只有两类:

- 舍弃:discard 后离开待处理队列。
- 纳入:commit 后成为正式 Note。

`skip temporarily` 不是最终结果,只是在批阅模式里暂时跳过。

## Digest Inbox

取消 today/week tab。Digest 是待处理 inbox。

来源配置属于 Digest 工作流自身,不放在通用 Settings 里:

- Digest 顶部提供"配置来源"入口,打开 RSS / Prompt Source 管理区。
- 当 inbox 为空且没有任何 source 时,配置区可直接展开,帮助新用户完成第一步。
- 通用 Settings 不再出现 Digest Source tab,避免把必要工作流入口藏进全局偏好里。

分组选项:

- 按时间:今天、昨天、本周、更早。
- 按来源:RSS source / Prompt source 名称。

卡片应展示:

- 标题。
- source 名称与类型。
- 原链接。
- 内容总结。
- 抓取时间。
- 状态:未处理、已查看、已讨论、已生成草稿、已舍弃、已纳入。

## 审阅模式

入口:

- Digest 顶部"开始批阅"。
- 卡片上的"从此处开始批阅"。

审阅模式是全屏工作台,不是窗口化浮层。资讯内容和对话都可能很长,
全屏能减少遮挡和嵌套滚动。

- 左侧:阶段化阅读/编辑区。
  - 第一个阶段是 Raw Info。
  - 第二个阶段是 Note Draft。
  - 两个阶段用 Tab 呈现,并以 Raw Info → Note Draft 的顺序表达流程。
  - 生成草稿前,Note Draft Tab 禁用;生成后自动切换到 Note Draft。

- Raw Info 阶段:
  - 标题、来源、原链接。
  - 摘要、关键点、正文摘录。
  - 队列位置。
  - 操作:上一条、下一条、跳过、舍弃、沉淀为笔记。
  - 内容只读,不可直接编辑。

- Note Draft 阶段:
  - 展示 title、tags、kind、folder、source、rationale 和正文。
  - 草稿展示采用接近主笔记的 surface:标题是可内联编辑的大标题,
    tags 使用主笔记的 chip strip,kind 使用 `KindChip`,folder/source/rationale
    收进 properties 区。
  - 正文编辑体验复用主笔记 Markdown editor,并支持 edit / split / preview
    视图切换。
  - 草稿阶段可保存 metadata/body,可继续走 Diff Review,但仍不会写入正式 Note。

- 右侧:对话流。
  - 默认围绕当前 Raw Info 讨论。
  - 生成 Note Draft 后,上下文切换为 Raw Info + Draft + 讨论历史。
  - 工具调用 trace 可见。

Raw Info 本身不可直接修改。用户如果想改内容,必须先沉淀为 Note Draft。

## 沉淀为笔记草稿

提供按钮和 Tool: `create_note_draft_from_info`。

输入:

- Raw Info。
- 用户与 AI 的讨论历史。
- Library Context。
- 用户语言和风格偏好。

输出:

- title。
- body。
- tags。
- note kind: `reference` 或 `knowledge`。
- suggested folder。
- source URL。
- brief rationale。

生成后进入草稿 Review 状态。用户可以手动修改标题、正文、tags、目录、类型。

当前实现(2026-05-30):

- UI:审阅工作台的 Raw Info 阶段提供"沉淀为笔记草稿"按钮。
- API:`POST /api/digest/items/{info_id}/draft`。
- Tool:`create_note_draft_from_info`,可在 Raw Info review chat 中基于当前
  Raw Info 省略 `info_id` 调用。
- 生成 Draft 后更新 Raw Info 为 `drafted` 并写入 `note_draft_id`;不会写入
 正式 Note。
- 用户可在 Note Draft 阶段调整 title、tags、kind、folder 和正文,通过既有
  `PUT /api/drafts/{draft_id}` 保存草稿内容。
- Note Draft 阶段使用接近主笔记的交互:标题内联编辑、tags chip 增删、
  kind chip 升降级、properties 展开、Markdown edit/split/preview 切换。
- AI 输出 JSON schema 校验失败时返回错误,不写 Draft,不改变 Raw Info 状态。

## 隐藏知识: Library Context

为了让 AI 提出合适标题、tags 和目录,沉淀草稿时必须给它库上下文,但不能
塞完整 vault。

建议结构:

```json
{
  "top_tags": ["ai", "product", "sync"],
  "folder_tree": ["ai/tools", "product/knowlet", "reading/sources"],
  "similar_notes": [
    {
      "title": "AI tool routing",
      "path": "ai/tools",
      "tags": ["ai", "tools"],
      "summary": "short note summary"
    }
  ]
}
```

来源:

- 当前标签体系:常用 tags、相近 tags。
- 目录树:现有 folder path 和大致用途。
- 相似笔记:检索 3-5 篇相关 note。
- 用户偏好:语言、笔记风格、是否偏知识化或资料化。

## 知识 vs 资料判断

Prompt 需要明确引导:

- **资料(reference)**:用户主要想保留外部信息以便未来查找;讨论较少,
  用户没有明显形成自己的判断、框架或结论。
- **知识(knowledge)**:用户已经围绕这条资讯进行了较深入讨论,产生了
  自己的观点、推理、连接、反驳、行动结论或抽象原则。

补充规则:

- 用户明确说"先收藏/留作参考"时,即使内容很长,也偏 `reference`。
- 用户明确说"变成我的原则/经验/判断"时,即使讨论较少,也偏 `knowledge`。
- AI 可以建议类型,但用户在 Review 中可修改。

## 草稿修正与 Diff

生成 Note Draft 后,用户可以继续和 AI 讨论草稿。AI 在合适时调用工具
提出草稿修改。

已实现工具:

- `propose_current_draft_edit`:基于用户要求、当前 Draft、Raw Info 和对话历史提出草稿 diff。
- `accept_all_draft_diff`:全部接受当前 diff。
- `reject_all_draft_diff`:全部撤回当前 diff。
- `commit_note_draft`:将当前 Draft 明确落库为正式 Note。

Diff 规则:

- AI 不能静默覆盖草稿。
- 修改过程仍走 Diff Review。
- 用户可以手动编辑右侧草稿内容和 metadata。
- 接受前 diff 暂存在 Draft metadata 中;正式 Note 不会被写入。
- 用户明确说"接受所有修改"时,AI 可以调用 accept-all tool。
- 用户明确说"撤回/拒绝所有修改"时,AI 可以调用 reject-all tool。
- 如果用户手动保存 Draft 正文,未决 diff 会被清空,避免旧 diff 覆盖新正文。

API:

- `POST /api/drafts/{draft_id}/diff`:生成草稿 diff proposal。
- `POST /api/drafts/{draft_id}/diff/accept`:接受当前 diff。
- `POST /api/drafts/{draft_id}/diff/reject`:撤回当前 diff。

## 落库

提供按钮和 Tool: `commit_note_draft`。

落库前 Review 必须展示并允许修改:

- 标题。
- 正文。
- tags。
- 目标目录。
- note kind。
- source URL。

规则:

- 用户点击"落库"可以 commit。
- 用户明确说"帮我落库这份笔记 / 保存为正式笔记 / 放入知识库"时,
  AI 可以调用 `commit_note_draft`。
- 用户没有明确确认时,AI 不能主动落库。
- commit 前若仍有未处理 diff,系统会阻止落库并要求先接受或撤回。
- commit 后 Raw Info 标记为已纳入,Note Draft 从草稿列表移除,正式 Note 写入 vault 并刷新索引。

API:

- `POST /api/drafts/{draft_id}/commit`:落库 Draft 并返回正式 Note id/path。
- `POST /api/drafts/{draft_id}/approve`:兼容旧 approve 入口,内部复用同一 commit helper。

## 实现切片

- **C4 Source config**
  - 只支持 RSS Source / Prompt Source。
  - 管理启用状态、上次拉取、错误、手动立即拉取。

- **C5 Pull + normalize pipeline**
  - 自动拉取、跨日拉取、seen-set 去重。
  - RSS item 归一化。
  - Prompt Source structured JSON 解析。
  - 200 未处理条暂停机制。

- **C6 Digest inbox v2**
  - 取消 today/week。
  - 按时间 / 按来源分组。
  - 显示拉取状态和暂停提示。

- **C7 Review mode**
  - 全屏批阅工作台。
  - Raw Info 只读。
  - Raw Info → Note Draft 阶段 Tab + 右侧对话流。

- **C10 Digest workspace polish**
  - Source 配置移入 Digest 工作台。
  - Note Draft 阶段生成前禁用,生成后自动切换。
  - Draft 正文编辑复用主笔记编辑体验。

- **C11 Draft note surface**
  - Draft 阶段不再是表单堆叠,而是接近主笔记阅读/编辑的 surface。
  - title、tags、kind、folder、source、rationale 和 body 使用主笔记同源
    组件或同源交互。
  - Draft footer 保留保存、Diff Review、落库等草稿生命周期操作,明确
    仍处于入库前边界。

- **C8 Create draft + draft tools**
  - `create_note_draft_from_info`。
  - Library Context 构建。
  - 知识/资料判断。

- **C9 Draft diff + commit**
  - 草稿 diff 修正已接入 Review overlay 和 conversation tools。
  - accept/reject all tools 已接入 UI、API、CLI。
  - `commit_note_draft` 已接入 UI、API、CLI/tool registry。
  - 正式入库后的索引刷新和跳转已完成。
