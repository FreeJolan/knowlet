# 架构设计

> [English](./architecture.en.md) | **中文**

> 活文档。本文描述 Knowlet 当前的架构意图,会随实现演进持续更新。决策原文见 [`../decisions/`](../decisions/);本文是它们在架构层的展开。

## 一、四层结构

Knowlet 自底向上分四层,单向依赖:

| 层级 | 职责 | 备注 |
|---|---|---|
| **存储层** | Vault 实体(Markdown / JSON)+ `.knowlet/` 派生数据 | 详见 [ADR-0006](../decisions/0006-storage-and-sync.md) |
| **领域层** | Note / Card / Mistake / Source 四类核心实体 | 详见下文 |
| **能力层** | Ingest(采集)/ Distill(提炼)/ Recall(召回)/ Quiz(考核) | 全部以原子能力 + LLM 编排实现,详见 [ADR-0004](../decisions/0004-ai-compose-code-execute.md) |
| **交互层** | 嵌入式 chat / 设置 UI / 移动 PWA / 未来 MCP server | 详见 [ADR-0003](../decisions/0003-wedge-pivot-ai-memory-layer.md)、[ADR-0005](../decisions/0005-llm-integration-strategy.md) |

能力层之间互不直接依赖,通过领域层暴露的实体协作。

## 二、四类领域实体

```
Note(笔记)        Markdown 文档       用户主导编辑
Card(卡片)        JSON 记录          UI 主导编辑,SRS 状态在 frontmatter 之外的字段中
Mistake(错题)     JSON 记录          机器维护
Source(信息源)    JSON 记录          机器为主,可选用户描述
```

四者关系:

- Note 是知识的归宿,卡片复习 / 错题诊断 / 情报沉淀最终都流向 Note
- Card 由 Note 派生或独立创建,有独立的 SRS 状态
- Mistake 由 Card 复习失败产生,反向加权 Card 与标记 Note
- Source 是外部输入,产物先成为候选 Note / Card,经审查后入库

存储格式与目录布局见 [ADR-0006](../decisions/0006-storage-and-sync.md) "实体存储格式"小节。

## 三、生产-消费闭环

四条核心 Path,**Path 0 是主线**(对应 ADR-0003 破局点):

```
                ┌──────────────────────────────────┐
                │           知识库 (Vault)          │
                │   notes / cards / mistakes /     │
                │   sources / users                │
                └──────────────────────────────────┘
                  ▲          ▲          ▲          │
        Path 1    │  Path 2  │  Path 3  │      Path 0 (主线)
   主动写入       │ OCR/导入 │ 知识挖掘 │   消费驱动生产
                  │          │  任务    │
                  │          │          │          ▼
                  │          │          │   ┌──────────────┐
                  │          │          │   │   Cards 卡片  │
                  │          │          │   └──────────────┘
                  │          │          │          │
                  │          │          │          ▼
                  │          │          │      复习考核
                  │          │          │          │
                  │          │          │          ▼
                  │          │          │   ┌──────────────┐
                  └──────────┴──────────┴───│ Mistakes 错题 │
                              Path 4 反哺   └──────────────┘
```

### Path 0 — 消费驱动生产(主线)

任何提问 / 阅读 / 讨论的内容都自动沉淀。子流程:

```
用户在 knowlet chat 提问
   │
   ▼
LLM-driven retrieval(LLM 自动从 Vault 检索相关内容)
   │
   ├─ 命中 → 基于本地内容 + 通用知识回答
   │           └─ AI 草稿沉淀候选(可选)→ 用户审查 → Note 入库
   │
   └─ 未命中且需外部信息 → LLM provider 自带 web_search
                            ↓
                          基于外部信息 + 本地知识回答
                            └─ AI 草稿沉淀候选 → 用户审查 → Note 入库
```

**关键点**:LLM 在每次回答前**自动**调用知识库检索 tool,而非等用户主动搜。这是 [ADR-0004](../decisions/0004-ai-compose-code-execute.md) "原子能力 + LLM 编排"的具体体现 —— retrieval 是一个 tool,LLM 决定何时调用。

### Path 1 — 主动写入

用户直接在 knowlet 写 Note 或 Card。最朴素的输入路径,不依赖 AI。

### Path 2 — OCR / 导入

扫书 / 截图 / 剪藏 / Markdown 批量导入,生成 Note 或 Card 候选,AI 草稿处理后入库。

### Path 3 — 知识挖掘任务

用户配置定时任务(频率 + Prompt + 来源约束),knowlet 在指定时间执行:

```
触发(定时 / 手动)
   ▼
LLM 通过 tool-call 执行:
   - LLM provider 原生 web_search
   - 抓取过程透明可追溯(去了哪些站、用了什么搜索词)
   ▼
LLM 整理 → 多条原子 Note + 索引 Note
   ▼
进入"待审查"区
   ▼
用户审查(扫一眼,删减,接受)→ 入库
```

详见 [ADR-0003](../decisions/0003-wedge-pivot-ai-memory-layer.md) 场景 B 与 [ADR-0005](../decisions/0005-llm-integration-strategy.md)。

### Path 4 — 错题反哺

错题作为一等公民:

```yaml
# Mistake 实体核心字段
linked_card: cards/01HYYY.json
linked_note: notes/01HXXX-...md
error_type: factual | conceptual | confusion | forgotten
frequency: 7
last_failed_at: 2026-04-29T10:23:00Z
ai_diagnosis: |
  用户在闭区间循环条件上反复出错...
```

Mistake 驱动三件事:

1. **加权出题**:SRS 算法叠加错题权重(FSRS 的 difficulty / stability 字段微调)
2. **盲区图谱**:可视化"最薄弱的领域",数据从 `.knowlet/profile/<domain>_analytics.json` 聚合
3. **反哺知识库**:某个 Card 被反复答错 → 笔记写得不够好 → 自动标记 Note 待优化

## 四、跨场景上下文累积

ADR-0003 的差异化点之一:多个使用场景**共享同一份用户上下文**,AI 在跨场景之间累积理解。

```
                ┌──────────────────────────────────────┐
                │  用户上下文 (users/me.md + .knowlet/)  │
                │  目标 / 偏好 / 错误模式 / 词汇掌握     │
                └──────────────────────────────────────┘
                 ▲          ▲          ▲          │
                 │          │          │          ▼
        场景 A        场景 B        场景 C     注入到所有
        论文阅读      信息流挖掘    学习场景     AI 交互
        (SRS 不用)    (SRS 不用)    (SRS 主导)
```

跨场景信号流(阶段一实现的最小集):

| 信号源 | 流向 | 效果 |
|---|---|---|
| 反复答错某类卡片 | 上下文"常犯错误"区 | 写作批改时主动检查 |
| 阅读 / 讨论遇到生词 | promote 到词汇 SRS | 进入复习队列 |
| 写作发现表达薄弱 | 推荐相关词汇 / 句型 | 加入学习目标 |

更复杂的累积(掌握度反过来影响批评判断)推到阶段二。

## 五、AI 编排 + 原子执行

[ADR-0004](../decisions/0004-ai-compose-code-execute.md) 是本架构的工程根基。所有跨特性的工作流都让 LLM 通过 tool-call 编排,代码只暴露原子能力。

阶段一预计的核心原子能力(非穷尽):

```
search_notes(query, top_k)         检索 Vault
get_note(id)                       读单条 Note
create_note(content, metadata)     创建 Note
update_note(id, patch)             修改 Note
link_notes(a, b, relation)         建立链接
delete_note(id)                    删除(走二次门)
create_card(front, back, ...)      新建卡片
review_card(id, rating)            提交复习评分
get_user_profile()                 读取用户上下文
update_user_profile(patch)         更新上下文
run_mining_task(task_id)           执行知识挖掘任务
fetch_url(url)                     抓取网页(走 LLM provider 原生 search)
...
```

每个 tool 满足 ADR-0004 的四条约束:可逆 / 二次门 / 一句话颗粒度 / 结构化返回。

## 六、知识老化机制

Path 3 拉取的内容会过期(尤其技术文档 / 框架文章)。需要 **TTL + 重新校验**机制:

- Source 实体在 `revalidate_after` 字段标注过期时间
- 到期触发重新拉取并 diff
- 矛盾 / 过期内容在 UI 上高亮提醒,避免"僵尸知识"

## 七、双循环自我进化

- **小循环(高频)**:复习 → 错题 → SRS 加权 → 笔记标记待优化
- **大循环(低频)**:周期性扫描全库,识别矛盾 / 过期 / 孤立笔记,推送给用户处理(由用户主动触发或 AI 编排)

## 八、关键扩展点

- **MD / JSON 底座** → 阶段二的图谱可视化基于 Frontmatter / link 字段构建
- **原子能力 = MCP tool schema** → 阶段二天然成为 MCP server,跨 AI 工具暴露
- **领域实体边界清晰** → 新增能力(如新 Source 类型)不挤占现有实体
- **`.knowlet/` 完全派生** → 重建机制保证用户对派生数据无心智负担

## 待办

- 把图示从 ASCII 升级为 Mermaid 图(便于在不同渲染环境中展示)
- 飞书初稿中的两张白板(整体闭环、Path 0 子图)的可视化迁移到本仓库
