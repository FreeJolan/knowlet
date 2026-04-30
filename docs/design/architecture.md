# 架构设计

> 活文档:本文描述 Knowlet 当前的架构意图,会随实现演进持续更新。决策原文见 [`../decisions/`](../decisions/)。

## 一、四层架构

Knowlet 在结构上分为四层,自底向上:

| 层级 | 职责 | 备注 |
|---|---|---|
| **存储层** | 纯文本 / Markdown / Frontmatter,Git 可版本化 | 本地文件系统 + SQLite 索引 |
| **领域层** | 笔记、卡片、错题、信息源四种核心实体 | 借鉴 Zettelkasten / SRS 模型 |
| **能力层** | Ingest(采集)、Distill(提炼)、Recall(召回)、Quiz(考核) | 插件化,每个能力独立可替换 |
| **交互层** | CLI / Web / 移动端(OCR) / MCP Server | 核心能力开放 API |

四层之间单向依赖:上层依赖下层接口,下层不感知上层。能力层之间互不直接依赖,通过领域层暴露的实体协作。

## 二、四类领域实体

```
Note(笔记)        ← Markdown 主体,Frontmatter 带元数据
Card(卡片)        ← 从 Note 派生 / OCR 直接生成,带 SRS 状态
Mistake(错题)     ← 一等公民,独立实体,带错因、频次、诊断
Source(信息源)    ← 订阅源 / RSS / API,带 TTL 与过期校验
```

四者之间的关系:

- Note 是知识的归宿,卡片复习/错题诊断/情报沉淀最终都流向 Note
- Card 由 Note 或外部输入派生,有独立的复习状态机
- Mistake 由 Card 复习失败产生,反向加权 Card 与标记 Note
- Source 是外部输入,产物先成为候选 Note/Card,经筛选后入库

## 三、生产-消费闭环

四条核心 Path 构成完整闭环:

```
                ┌──────────────────────────────────┐
                │           知识库 (Notes)          │
                │      MD + Frontmatter + Git       │
                └──────────────────────────────────┘
                  ▲          ▲          ▲          │
                  │          │          │          ▼
        Path 1    │   Path 2 │  Path 3  │      Path 0
   主动写入       │  OCR/导入 │ 定时拉取 │   突发查询(RAG)
                  │          │          │          │
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

- **Path 0 — 突发查询(消费驱动生产)**:任何提问都先用 RAG 检索本地库,若需补外网信息,**回答完毕后该问答自动沉淀回知识库**
- **Path 1 — 主动写入**:用户直接在 Note 里记
- **Path 2 — OCR / 导入**:扫书/截图/剪藏,生成 Card 与 Note
- **Path 3 — 定时拉取**:订阅源拉取信息,生成候选 Note/Card,带 TTL
- **Path 4 — 错题反哺**:错题不仅驱动 SRS,还反向标记 Note 待优化

详见图示原始草稿(飞书初稿白板,后续会迁移为 Mermaid):
- 整体闭环图(原 token: A3fTwVRbJhBZdhb9Qpacfj7Rntc)
- Path 0 子图(原 token: MirtwvITahu1qMbK7cWco3xdnvg)

> TODO:把上述两张白板转为本仓库内的 Mermaid 图。

## 四、对原始设计的三处加强

### 1. 错题作为一等公民

错题不应只是简单的复习日志,而是独立实体:

```yaml
# Mistake 实体字段
linked_note: notes/algo/binary-search.md    # 错在哪个知识点
linked_card: cards/abc123.md                 # 哪张卡片错的
error_type: factual | conceptual | confusion | forgotten
frequency: 7                                  # 历史错误次数
last_failed_at: 2026-04-29T10:23:00Z
ai_diagnosis: |
  用户混淆了开闭区间边界条件,
  历史上这是第 3 次在边界类问题出错
```

由此衍生三件事:

1. **加权出题** —— SRS 算法叠加错题权重(类似 Anki 的 ease factor 但更智能)
2. **盲区图谱** —— 可视化"最薄弱的领域",自动生成补强学习计划
3. **反哺知识库** —— 某个 Card 被反复答错 → 笔记写得不够好 → 自动标记 Note 待优化

### 2. 消费驱动生产(Path 0)

> 用过的知识才是你的知识。

原始设计中"突发查询某个问题"只是 RAG 外挂 Web,答完就丢。改进:每一次提问都应沉淀。

```
用户提问
   │
   ▼
RAG 检索本地库
   │
   ├─ 命中 → 用本地内容回答 → (可选)生成卡片巩固
   │
   └─ 未命中 → 联网查询 → 回答 → 沉淀为候选 Note + 候选 Card
                                    │
                                    ▼
                              用户筛选/编辑后入库
```

这是"第二大脑" vs "AI 搜索引擎"的本质区别。

### 3. 知识老化机制

Path 3 拉取的内容会过期(尤其技术文档/版本相关)。需要 **TTL + 重新校验**:

- 信息源类 Note 在 Frontmatter 标注 `expires_at` / `revalidate_after`
- 到期自动触发重新拉取并 diff
- 矛盾或过期内容在 UI 上高亮提醒,避免"僵尸知识"

## 五、双循环自我进化

- **小循环(高频)**:复习 → 错题 → SRS 加权 → 笔记标记待优化
- **大循环(低频)**:周期性扫描全库,识别矛盾/过期/孤立笔记,推送给用户处理

## 六、关键扩展点(为后续阶段预留)

虽然阶段一聚焦学习型(见 [ADR-0001](../decisions/0001-wedge-learning-first.md)),但架构必须为后续阶段留扩展点:

- **MD 底座** → 阶段二的双链/图谱可直接基于 Frontmatter 与正文链接构建
- **能力插件化** → 阶段三的订阅/拉取作为独立 Ingest 插件接入
- **领域实体一等公民** → Note/Card/Mistake/Source 边界清晰,新增能力不会"挤占"现有实体
