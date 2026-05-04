# 路线图

> [English](./README.en.md) | **中文**

Knowlet 按 Wedge 战略分阶段演进。能力同源、相互增强;叙事按阶段聚焦。详见 [ADR-0003](../decisions/0003-wedge-pivot-ai-memory-layer.md)。

## 阶段总览

```
阶段一 (MVP / V1):    AI 长期记忆层 + 减负型 PKM
阶段二 (V1 → V2):     用户需求驱动的扩展
阶段三 (V2 → V3):     跨 AI 工具的记忆层(MCP server)
阶段四:               全能形态
```

## 阶段一 — MVP / V1

**Slogan:** 会自己整理的个人知识库 / *A personal knowledge base that organizes itself.*

### 服务的真实场景

详见 [ADR-0003](../decisions/0003-wedge-pivot-ai-memory-layer.md) 场景 A / B / C。简要:

- **场景 A — 研究 / 论文阅读**:在 knowlet chat 讨论 → AI 草稿 → 用户审查 → 沉淀;后续 AI 对话自动召回历史结论
- **场景 B — 信息流订阅与整理**:配置知识挖掘任务 → 定时抓取 + LLM 整理 → 用户审查 → 入库
- **场景 C — 结构化重复记忆 + AI 增强**:外语词汇 / 专业概念辨析 / 写作批改类场景,SRS 子模块调度 + AI 在交互中按用户上下文调整反馈

### 核心特性

- **嵌入式 chat**:LLM 由用户自带([ADR-0005](../decisions/0005-llm-integration-strategy.md))
- **LLM-driven retrieval**:LLM 在每次对话中按需从知识库检索
- **知识挖掘任务**:定时 + Prompt + 来源约束 + 抓取过程透明
- **AI 草稿 + 人工审查**:默认沉淀模式
- **SRS 子模块(FSRS)**:作为知识库的"主动复习视图"
- **分层用户上下文**:Markdown 意图 + JSON 派生分析 + SQLite 派生状态
- **桌面端 + 移动 PWA**:碎片场景兜底

### 显式不做

详见 [ADR-0003](../decisions/0003-wedge-pivot-ai-memory-layer.md) "阶段一明确不做"小节。摘要:

- 团队协作 / 多用户(终生不做)
- 内容推荐 / 信息发现 / 社交
- 任务 / 日历 / Todo 管理
- AI Chat 产品的功能复刻
- knowlet chat 不抢 Claude / Cursor 的位置

> **2026-05-04 修订**:原"传统 PKM 双链 / 图谱专门 UI(由 LLM agent + tools 间接达成)" 这条**已撤销**。双链 + 图谱是知识软件核心能力,不是装饰。Wikilinks 已在 M7.0.4 落地;graph view 进 M8(详见 ADR-0003 / 0011 / 0013 各自的 2026-05-04 amendment)。

### 衡量是否可进入阶段二

- 三个真实场景的 happy path 能稳定跑通
- AI 草稿 + 人工审查的沉淀循环在用户实际使用中不令人烦躁
- LLM-driven retrieval 命中率达可用阈值(具体数值在原型阶段定)
- 跨场景上下文累积有可观察的效果(写作批改用上历史错误模式 / 阅读促进词汇队列等)

## 阶段一进度(2026-05-04 当前快照)

### ✅ 已 ship

```
M6.0–M6.5  Obsidian-style UI shell + 多会话 chat + 收尾打磨
Phase B    并发 / 异步启动 / SSE 抽 module 等 8 项硬骨头
M7.0       笔记基线 5 项(软删除 / 嵌套 / 图片 / wikilinks / 代码高亮)
M7.1       选区 → 聊天引用胶囊(ADR-0015)
M7.2       URL 录入 + sediment ambient(ADR-0016)
M7.3       草稿质量增强(critical take + hover quote)
M7.4       笔记考试模式(ADR-0014:CLI + Web + 历史 tab + Cards 回流)
M7.5       LLM web_search + fetch_url(ADR-0017,backend-agnostic)
M8.1       Structure signals 后端(near-dup / clusters / orphan / aging)
ADR-0004 amendment 后修复:web_search palette / 新建 Card UI
```

### ⏳ 在执行 / 待落地

- **Claude Design 第二轮**(brief 在 [`../design/m7-m8-redesign-brief.md`](../design/m7-m8-redesign-brief.md)):
  覆盖 8 个 M7 surface audit + M8.2 知识地图侧栏 / M8.2b 图谱 view / M8.3 周报 / M8.4 暗色 token
- **集中 dogfood**(模版在 [`../dogfood/M7-M8.1-report-template.md`](../dogfood/M7-M8.1-report-template.md)),反馈回流到设计 + bug 修

### 🔧 ADR-0004 修订 backlog(每个 AI 功能必须有 UI 替代)

- ✅ `web_search` — palette 命令(commit `ee0998a`)
- ✅ `create_card` — Cards focus + palette + 新建 modal(commit `483ed4c`)
- ⏳ `list_mining_tasks` — 需 Web mining-config 面板(等 design)
- ⏳ `fetch_url` — 跟 M7.2 url-capture 流统一(等 design)

### 📋 设计回件后(M8 第二轮 + dogfood polish)

```
M8.2  知识地图侧栏(消费 M8.1 信号)+ graph view(用户认可的双链)
M8.3  周报(Sunday-newspaper,ADR-0013 Layer C)
M8.4  暗色 toggle(localStorage + 跟随系统)
M7.4.3-cluster  cluster scope quiz(目前路由 501,wire-compatible 等 Layer B)
```

## 知识软件核心能力盘点(2026-05-04)

knowlet 是知识软件,不是 AI Chat 套壳(per [ADR-0012](../decisions/0012-notes-first-ai-optional.md))。这一节横切**知识软件作为品类的核心能力**,看 knowlet 的覆盖度:

### A. 笔记内容(authoring)

| 能力 | 状态 |
|---|---|
| Markdown 编辑 + preview | ✅ M6 |
| 图片粘贴 | ✅ M7.0.3 |
| 代码语法高亮 | ✅ M7.0.5 |
| 双链 wikilinks `[[Title]]` | ✅ M7.0.4 |
| **块引用 `[[Note#Heading]]` / block-id** | ❌ **未规划 — Tier 1 缺口** |
| **数学公式渲染(KaTeX)** | ❌ **未规划 — Tier 1 缺口**(STEM 笔记必需)|
| **Mermaid / PlantUML 图表** | ❌ **未规划 — Tier 1 缺口**(技术笔记常需)|
| **模板系统**(读书笔记 / 会议纪要 等)| ❌ **未规划 — Tier 1 缺口** |
| 大纲模式(Logseq-style block hierarchy) | ❌ Tier 2 — 是否做需新 ADR(改 IA 范式)|
| 一般附件(PDF / 音频 / 视频)| ❌ 当前只有图片 |
| CodeMirror 升级编辑器 | ⏳ ADR-0011 §M7+ defer |

### B. 组织 & 检索(organization)

| 能力 | 状态 |
|---|---|
| 文件夹层级 | ✅ M7.0.2(递归)|
| Tags(frontmatter)| ✅ M0 |
| 全文搜索(FTS5)| ✅ M0 |
| 向量搜索 + RRF hybrid | ✅ M0 |
| 反链面板 | ✅ M7.0.4 |
| 笔记跳转 palette(Cmd+P) | ✅ M6.2 |
| Graph view | ⏳ M8(刚 amend 进来)|
| 知识地图侧栏(LLM 信号)| ⏳ M8.2 |
| **Daily notes / 日记**(date-based 自动创建)| ❌ **未规划 — Tier 1 缺口**(Roam 入口模式)|
| **批量操作**(多选 → tag / move / delete)| ❌ **未规划 — Tier 1 缺口** |
| 标签树 explorer | ❌ Tier 2 |
| 保存的搜索 / smart folders | ❌ Tier 2 |
| typed properties(Obsidian properties)| ❌ Tier 2 |

### C. 录入(capture)

| 能力 | 状态 |
|---|---|
| 手动新建 + sediment 对话存笔记 | ✅ M0 / M6 |
| URL → 摘要 → 胶囊 | ✅ M7.2 |
| 图片粘贴 | ✅ M7.0.3 |
| RSS / URL mining → drafts | ✅ M3 |
| Web mining-config 面板 | ⏳ ADR-0004 backlog |
| **选区 → Card 一键**(highlight-to-card)| ❌ **未规划 — Tier 1 缺口**(跟 ADR-0014 同源)|
| Watch folder(放入自动入库)| ❌ Tier 3 |
| 音频录制 + 转写 | ❌ Tier 3 |
| OCR 图片 → 文字 | ❌ Tier 3 |
| 浏览器扩展 / web clipper | ❌ M9+(per ADR-0016 §"Out of scope")|

### D. 主动复习(active recall)

| 能力 | 状态 |
|---|---|
| Cards / FSRS | ✅ M0 |
| Quiz 模式(scope-driven recall)| ✅ M7.4 |
| 错题 → Card 回流 | ✅ M7.4.2 |
| **Cloze deletions(`{{c1::}}`)** | ❌ **未规划 — Tier 2 缺口** |
| Anki .apkg 导入 | ❌ Tier 3 |

### E. AI 集成

| 能力 | 状态 |
|---|---|
| Chat with vault(RAG)| ✅ M0 |
| 选区 → 聊天胶囊 | ✅ M7.1 |
| URL → 摘要 → 胶囊 | ✅ M7.2 |
| Quiz 出题 + 评分 | ✅ M7.4 |
| Web search tool | ✅ M7.5 |
| 多会话 chat history | ✅ M6.4 |
| **编辑器内联 AI**(Cmd+K → continue / refine / shorten)| ❌ **未规划 — Tier 2 缺口**(Notion AI 风格)|
| **智能链接建议**(typing 时 AI 建议 `[[...]]` 候选,基于向量)| ❌ Tier 2 |
| 图片理解(paste 图 → 问 AI)| ❌ Tier 3 |
| 语音 / TTS / STT | ❌ Tier 3 |

### F. 生命周期(lifecycle / hygiene)

| 能力 | 状态 |
|---|---|
| Soft-delete + trash | ✅ M7.0.1 |
| Layer A ambient(sediment 时显示相似)| ✅ M7.2 |
| Layer B 结构信号(near-dup / cluster / orphan / aging)| ⏳ Backend ✅ M8.1 / UI 等 design |
| Layer C 周报 | ⏳ M8.3 |
| 显式 archive(跟 trash 区分)| ❌ Tier 2 |
| 笔记 freeze / pin | ❌ Tier 3 |
| 笔记历史 / diff | ❌ Tier 3(用户用 git 兜底)|

### G. 同步 & 导出

| 能力 | 状态 |
|---|---|
| Vault = 普通文件夹(用户自接 Syncthing/iCloud)| ✅ M0(per ADR-0006)|
| 导出(PDF / HTML / Anki)| ❌ Tier 2 |
| Vault 导入(Obsidian / Notion / Roam)| ❌ Tier 2 |
| 自建同步(CRDT / 加密)| ⏳ 阶段二 |

### H. 扩展性

| 能力 | 状态 |
|---|---|
| Plugin 系统 | ⏳ 阶段二 |
| MCP server | ⏳ 阶段三 |

### I. 视觉

| 能力 | 状态 |
|---|---|
| 纸感浅色 | ✅ M6.1.5 |
| 暗色 toggle | ⏳ M8.4 |

### Tier 1 缺口汇总(对"知识软件"身份最 load-bearing,建议进 M9 候选)

**M9 候选**(等 M8 dogfood 反馈定优先级):

1. **块引用 + block-id 锚点** — 双链当前到 note 级,Roam/Obsidian/Logseq 都到 block 级。M7.0.4 wikilinks 是基础,M9 加 `[[Note#Heading]]` 跟 `[[Note^block-id]]` 锚点。
2. **Daily notes / 日记** — Roam-style date-based 自动创建。要跟 ADR-0013 Layer C 周报澄清边界(daily 是录入入口,周报是回顾入口,不冲突)。
3. **数学(KaTeX)+ Mermaid 渲染** — STEM / 工程笔记必需。marked 有现成插件,接入成本低,只是没排上。
4. **模板系统** — `templates/` 目录 + new-note 时 template picker。
5. **选区 → Card 一键** — 跟 M7.4 Cards 回流同源:笔记中 highlight → 浮窗"做成 Card" → 跳进 New Card modal 预填。补强 active recall 录入端。
6. **批量操作** — 多选 → 改 tag / 移文件夹 / 删除。dogfood 后期 vault 大了必爆这个需求。

### Tier 2(夹在中间)

7. 大纲模式(Logseq block hierarchy)— 改 IA 范式,需 ADR
8. Cloze deletions(`{{c1::}}`)— Anki-style 卡面
9. **编辑器内联 AI**(Cmd+K continue / refine / shorten)— Notion AI 风格;跟 M7.1 capsule 是不同入口
10. 智能链接建议(打字时向量 retrieval 推 `[[...]]` 候选)
11. 显式 archive(跟 trash 区分)
12. 标签树 explorer / saved searches / typed properties
13. 导出 / 导入(Obsidian / Notion / Roam → knowlet)

### Tier 3(后续阶段 / 低优先)

附件(PDF/audio/video)/ watch folder / 音频录制 + 转写 / OCR / 图片理解 / 语音 / 浏览器扩展 / 移动原生 / Plugin 系统(已在阶段二)/ Anki .apkg 导入

---

## 阶段二 — V1 → V2:用户需求驱动的扩展

阶段一稳定后,用户自然会浮出新需求。可能演进的方向(按预期优先级):

- **plugin 生态**:开放接口让用户/社区写自定义 tool,扩展原子能力层
- **移动端原生**:PWA 不够,音频 / OCR / 通知等场景需要原生能力
- **knowlet 自建同步**:文件级同步的冲突体验不佳时,补 CRDT 或加密同步路径
- **完整加密路径**:高隐私需求出现时(参见 [ADR-0006](../decisions/0006-storage-and-sync.md))
- **fallback 抓取后端**:支持不带原生 web_search 的 LLM(SearXNG / Brave / 自托管)

> **2026-05-04 修订**:原"图谱 / 双链可视化"列在阶段二 — **已移到阶段一 M8**(per ADR-0003 / 0011 / 0013 amendment)。双链是知识软件核心,不是 V2 扩展。

阶段二是**被用户需求推着走**,而不是先做出来再找需求。具体特性进入路线图前需通过特性优先级原则(下方)。

## 阶段三 — V2 → V3:跨 AI 工具的记忆层

knowlet 阶段一的原子能力按 MCP 标准设计([ADR-0004](../decisions/0004-ai-compose-code-execute.md))。阶段三正式开放 MCP server 形态:

- Claude Desktop / Cursor / 其他 MCP-compatible 工具直接调 knowlet 的能力
- knowlet 不再只是"打开就用的应用",而是"用户所有 AI 工具的私人记忆层"
- 这与 ADR-0003 的破局点叙事完全自洽

## 阶段四 — 长远全能形态

当三条主能力(消费沉淀 / 信息挖掘 / 学习增强)在 MCP 形态下相互强化:

```
信息挖掘 → AI 整理候选 → 用户审查入库
              ↓
       LLM-driven retrieval 在所有 AI 工具中召回
              ↓
       使用过的知识形成卡片 → SRS 复习
              ↓
       错题反哺笔记与挖掘任务的 prompt 调整
```

阶段四不再是"叠加新能力",而是把已有能力的反馈环路打满。

## 特性优先级原则

每条新特性进入路线图前,先过四个问题:

1. **服务于当前阶段的破局点吗?** 否 → backlog
2. **会损害三条核心原则吗?**(AI 可选 / 数据主权 / 插件化) 是 → 拒绝
3. **能用现有领域实体表达吗?** 否 → 思考是否需要新增实体,而不是塞进现有实体里
4. **拒绝它的代价是什么?** 如果代价是"失去某类用户但他们不在当前阶段画像里",可以接受

这套原则避免"什么都想做"的早期陷阱,具体每条候选特性的判断结果会在 ADR 或 design 文档里记录。
