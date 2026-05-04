# 0013 — 知识管理契约 / 碎片化治理三层框架

> [English](./0013-knowledge-management-contract.en.md) | **中文**

- Status: Proposed
- Date: 2026-05-02

## Context

[ADR-0003](./0003-wedge-pivot-ai-memory-layer.md) 把 wedge 定为"AI 长期记忆层";[ADR-0012](./0012-notes-first-ai-optional.md) 把身份钉死为"个人知识库 / 笔记软件 + AI 可选增强"。但**两条都没回答一个 6 个月内必然爆出来的问题**:

> 用户每天 chat 沉淀 + 每条 mining draft 通过 = +1 Note。M2-M6 累计 dogfood 已经在 `/tmp/knowlet-real` 里堆出 37+ Note,真实使用半年后注定到 1000+。**没有任何机制让用户能在不焦虑的前提下管理这堆笔记**。

用户在 dogfood 反馈里把这个问题原话表述为"碎片地狱",并强调:
> 大模型不具备真正意义上的判断力,如果知识最终是为人服务,那么人要为知识的准确性负责。

这条原则得从 ADR-0012 的"AI 是可选"延伸到一个更具体的契约:**结构性变更必须由人触发,AI 只能指出可能性**。本 ADR 把这条契约 + 配套的三层应对框架钉死,作为后续 M7+ 所有"管理类"功能的硬约束。

## Decision

### 1. 核心契约:AI 不自动改 IA

**任何会改变 vault 结构(`notes/` 目录、Note 内容、tag 集、文件名)的动作,必须有用户的 explicit click,不能靠默认值或后台任务完成。**

具体含义:

| 类型 | 允许 | 禁止 |
|---|---|---|
| AI 算 cluster / 近重复 / 衰老候选 | ✅(后台计算) | — |
| AI 提议合并 / 拆分 / archive | ✅(显示为信息,默认动作不变) | ❌ 默认按下"合并"按钮 |
| AI 自动 archive 衰老 Note | — | ❌(包括"30 天没碰自动归档"这种) |
| 用户在 UI 里点"合并这两条" | ✅ | — |
| 周报里点"归档这 5 条" | ✅(每条单独点) | ❌ 一键全归档(批量必须是用户主动选中) |

这把 [ADR-0012](./0012-notes-first-ai-optional.md) 的"AI 是可选增强"从语义层落到行为层。**ADR-0012 答的是"AI 在不在",本 ADR 答的是"AI 在的时候,能干什么不能干什么"。**

### 2. 碎片化的 4 条独立产生机制

以下机制是讨论时拆出来的,**为了让"该用哪一招打哪一招"清楚**。三层框架对应解决其中三条;一条是结构性悖论(见后述)。

| # | 机制 | 当前状态 | 三层中谁解决 |
|---|---|---|---|
| ① | 录入端无回压 | chat 沉淀 + draft 通过 = +1 Note,无任何反作用力 | **Layer A — 录入端 ambient** |
| ② | 相似度信号不可见 | knowlet 已经有 FTS5 + 向量索引知道哪些 Note 在讲同一件事,**但只用于检索,从未引导组织** | **Layer B — 被动结构化** |
| ③ | 没有衰老层 | 每条 Note 都 live 到永远;真实人类知识 ~80% 写完只看一次 | **Layer B — 被动结构化** |
| ④ | 没有跨语料 review 契机 | 用户永远只看当前 Note 局部状态,不看横切 | **Layer C — 周报** |

### 3. 三层框架

#### Layer A — 录入端 ambient 信息(M7 candidate)

每次用户即将创建新 Note(sediment / draft 通过 / 手动 new note),**ambient 显示 top-3 相似 Note**(向量近邻),不带"建议合并"动词,不预选任何动作。

- **默认动作永远是"新建"**,合并必须用户 explicit click
- 显示形态像引用预览,而非"建议"提示
- **拒绝"AI 觉得这条该合并到 X"** 的弹窗 / 通知

落实 §1 契约:AI 给信息,人做决定。

#### Layer B — 被动结构化(M8 candidate)

后台持续算结构信号,**不主动 push**,用户想看时进"知识地图"侧栏:

- 近重复对(cosine > threshold)
- Note clusters(over embeddings,k-means / HDBSCAN)
- 孤儿 Note(无入链 + 检索频率低 + 多月未触)
- 衰老候选

**只算,不动。** 看到"3 篇高度相似"用户自己去合并;看到"5 条 6 个月没碰"自己去 archive。系统从不替用户按按钮。

显式不做:
- ❌ Graph view(ADR-0011 已定不做)
- ❌ Tag taxonomy(top-down 强制分类是 Notion fail 模式)
- ❌ 自动归档 / 自动合并(违反 §1 契约)

#### Layer C — 定期摘要(M8 candidate)

**周期由用户配置**(开始日 + 每隔 N 天)—— 默认 7 天(周报),用户可改成 14 天 / 30 天 / 自定义起始点。**不强制周报**,但默认值是周报,因为日报必触发 backlog guilt loop(Roam / Obsidian 的标志失败模式)。

调性 = **Sunday newspaper**:
- 信息密度 ✓,催促 ✗
- **不留 unread badge** — 必须可"关掉就走"
- 内容形态(候选,实施期校准):
  - 这周期新增 N 条 + 3 条最长的 Note 题目
  - 1-2 条 Layer B 的 cluster-collapse 提议(但仍需用户单条点选)
  - 5 条衰老候选(同上)

**显式不用 FSRS / 遗忘曲线。** FSRS 在 Cards 上跑得很好,Note 层面"你今天该重读《X》吗"用户答"我没忘只是没空"指标无法解释。两条独立 review 通路 > 一条共用。

### 4. 跟现有系统的边界

#### 跟 Cards / FSRS 的关系

- **Cards = 原子事实级**(front/back,二值自评 1-4,FSRS 调度,持久化)
- **Note 层 review 不走 SRS**,因为它不是"记得 / 忘了"二值;它是"还相关吗 / 该归档吗"的**跨语料判断**
- 周报里**不会**对 Note 启动 FSRS 复习。如果用户想把某条 Note 的关键点变成 Card,走"从 Note 生成 Card"路径(已有 tool)

#### 跟笔记考试模式(`project_knowlet_note_quiz_idea` memory)的关系

笔记考试模式(scope-driven AI 出题 + advisory 评分)是**第三种 review 模态**,跟本 ADR 的 Layer C 周报正交:

- **Layer C 周报**:被动接收"这周看了什么、哪些该收拾"
- **笔记考试**:用户主动召唤"考我这一簇笔记"

考试模式的**评分**部分必然 AI 做判断,跟 §1 契约边界相关。处理方式:**评分必须是 advisory(给理由 + 分数,用户最终拍板),不是权威**。考试模式留给独立 ADR(M7+ 时起草)详细处理。本 ADR 不展开。

### 5. 实施边界

- 本 ADR **只钉框架与契约**,不指定具体 UI / 阈值 / 算法
- 实施切片(Layer A / B / C)各自需要独立的 design pass(原型 + 阈值校准 + dogfood)
- 三层都要做(2026-05-02 用户拍板),但**不强求顺序**;Layer A 是最小单元,可以单独 ship 验证录入端体感
- 衰老阈值 / cosine threshold / 周报频率 等具体数字,留给实施时跟用户共同 dogfood 校准
- Layer B "知识地图"的 UI 位置(AI dock sub-tab vs 独立 focus mode)留给实施期决定
- 笔记考试模式见 [ADR-0014](./0014-note-quiz-mode.md)(本 ADR 落地后立刻起草)

### 6. 相似性模型(技术 load-bearing 部分)

> 用户提示(2026-05-02):"相似性判断决定功能效果,其它都是体验问题"。本节钉死相似性的设计原则,具体阈值留给实施期校准。

#### 6.1 操作定义先于准确性

不同 Layer 想找的"相似"是**不同的关系**,绝不能用同一指标统一衡量:

| 用在 | 想找的关系 | 失败模式 |
|---|---|---|
| Layer A 录入端 ambient | 同主题但还没合并的近邻 | **高精度优先**:误报一次,用户学会忽略整个 ambient 区域 |
| Layer B 近重复对 | 几乎在讲同一件事(高 cosine + 高 keyword overlap 双高) | 假阳性 → 用户误合并不该合并的两条 |
| Layer B 聚类 | 同领域簇(粒度可调) | 过粗 → 全归一类没用;过细 → 每条 Note 自己一簇 |
| Layer B + C 衰老 / 孤儿 | 跟最近活动有没有连接(入链 + 检索频率 + 最近触摸) | 误判孤儿让用户错过其实还有用的 Note |

#### 6.2 精度优于召回(尤其 Layer A)

**Layer A 的 hard target:`P@3 ≥ 0.67`**(top-3 至少 2/3 在用户主观评估下"确实相关")。

理由:用户每天看到 ambient,**只要 30% 是误报,剩下 70% 也会被一起忽略**(Notion AI / Roam Copilot 的死刑)。Recall 不重要 —— 漏报某条相关 Note 没关系,用户能照样新建。

Layer B 近重复:`cosine > 0.85 且 keyword Jaccard > 0.4`(双门槛交叉),宁缺毋滥。

Layer B 聚类:无 ground truth,**dogfood 调粒度**(用户主观判断"这簇看起来对吗")。

#### 6.3 性能预算

| 路径 | 预算 | 当前能力 |
|---|---|---|
| Layer A 录入端 top-K(<200ms) | < 200ms | sqlite-vec 5000-Note 量级 ≈ 50ms ✓ |
| Layer B cluster 批处理 | < 5s | 5000 × 384 dim 余弦全对 ≈ 200ms ✓ |
| Embedding 重算(per-Note edit) | 已走 `content_hash` skip-if-unchanged ✓ | — |
| 录入流量大场景(连续 sediment 5 个)| 异步 / 批量,不阻塞主流 | **实施时需要确认** |

#### 6.4 可解释性 — evidence 列必须有

cosine 0.87 说不出"为什么近"。任何 ambient / 近重复显示**必须带 evidence**:
- 共享关键词(top 3-5 个,从 BM25 高分句对中提)
- 共享 tag
- (可选,有 wikilink 后)co-citation

**没有 evidence 的相似性显示不上线**。这把"AI 觉得近"变成"AI 给你看证据,你自己判断" —— 跟 §1 契约同源。

#### 6.5 混合信号优于纯 embedding

纯 cosine 已知失败模式:短 Note vs 长 Note 假相似;抽象 vs 具体不该归一类但 cosine 高;同义不同词跨语言相似度低。

knowlet 已经有的多路信号都该用:
- **向量 cosine**(主信号)
- **BM25 / FTS5**(已就位):捕捉同名实体 / 函数名 / 引用
- **tag overlap**(用户手标的最便宜信号)
- **co-citation**(将来有 wikilink 后)

公式骨架(weights 实施期校准,不写死):
```
score = w1·cosine + w2·bm25_score + w3·tag_jaccard  (+ w4·co_citation)
```

各层 weights 不同:Layer A 重 cosine;Layer B 近重复要求 cosine + BM25 双高;Layer B 聚类用 cosine 主导(配合聚类算法的距离度量)。

#### 6.6 校准 — threshold 不能硬编码

threshold 数据集相关:学术论文 vault vs 日常 journal vault 的 similarity 分布完全不同。

实施期必做:
1. **dogfood 期人工标 ~50 对**(每对标"近重复 / 同主题但独立 / 无关")
2. 算 ROC,选使 `P@3 ≥ 0.67` 的 threshold
3. 给用户 **per-vault 手动 dial**(`config set similarity.threshold 0.85` 或 UI slider)
4. embedding model 切换 = 全量重 embed + 重新校准(已知代价)

## Consequences

### 落地后的硬约束

- **每个新 feature 落地前必须答两道题**(ADR-0012 的"AI 没配置时这是什么"+ 本 ADR 的"会改变 IA 吗"):
  - 改 IA → 必须有 explicit click,不能默认动作
  - 不改 IA(纯计算 / 显示) → 自由
- 任何 PR 引入"AI 自动 archive / 合并 / 拆分"路径,review 时直接 reject

### 跟现有 ADR / memory 的关系

- 延伸 [ADR-0012](./0012-notes-first-ai-optional.md):AI-optional 是宏观契约,本 ADR 是"AI 在的时候"的子契约
- 落地 `project_knowlet_fragmentation_thinking` memory 提的全部内容(4 机制 + 三层 + IA 契约)
- 与 `project_knowlet_note_quiz_idea` memory **正交**:本 ADR 处理"被动 review",考试是"主动 review",留给 ADR-0014
- 跟 [ADR-0011](./0011-web-ui-redesign.md) 的"显式不做 graph view"一致;Layer B 知识地图≠graph view(graph 是 Note→Note 链接可视化;Map 是 cluster / 重复 / 孤儿信号汇总)
- 触发 [`feedback_no_hidden_debt`](memory) §6:本 ADR 钉死后,M7+ 任何 feature 都不能"先快速做了再补 IA 契约"

### 风险 / 代价

- **Layer A 的"显示 top-3 相似"对录入流加了一步认知负担**。用户每次新建 Note 都看一眼。如果实施做得不好(显得吵 / 像"AI 在催"),反而劝退。需要 dogfood 校准。
- **Layer B 后台 cluster 计算的成本**(几千条 Note 时):k-means/HDBSCAN 在向量索引上不重,但首次跑可能 O(秒级)。需要在数据规模上调优。
- **Layer C 周报内容质量**取决于 Layer B 信号质量。如果 cluster 信号假阳性多(把不同主题的 Note 误归一簇),周报会噪。需要先验证 B 再 ship C。
- **不引入 graph view / tag taxonomy** 是显式承诺;后续看到这两类需求,以本 ADR 为准 push back。

### 决策溯源

- 用户原话(2026-05-02 dogfood 反馈):
  > 在一般的使用场景中,用户会不断通过日常对话以及订阅推送积累大量知识笔记,如果不加管理,用户就会面临碎片"地狱"... 大模型不具备真正意义上的判断力,如果知识最终是为人服务,那么人要为知识的准确性负责。
- 用户当时给的两个粗略想法(录入前整合、日报/周报+遗忘曲线)被批判性 review 后融合进本 ADR
- 触发于 2026-05-02 dogfood + 第二轮独立 critique #6(产品定位内在矛盾,经 ADR-0012 解决后,自然引出本 ADR 关心的"那 AI 在的时候到底能干啥")

## Amendment(2026-05-04 协同 ADR-0003 修订)

§3 Layer B 的"显式不做"清单中第一条:

> ❌ Graph view(ADR-0011 已定不做)

**撤销。** [ADR-0003 amendment(2026-05-04)](./0003-wedge-pivot-ai-memory-layer.md#amendment2026-05-04-用户拨乱反正)
明确双链 + 图谱是知识软件核心能力,ADR-0011 也已撤回"虚荣功能"判断。
本 ADR 的对应修订:

- **graph view ≠ Layer B"知识地图侧栏"**,但两者**共存于 M8**,不是 either/or:
  - **Graph view** = 用户主动写的 `[[Title]]` 链接关系可视化(ground truth,
    用户认可的关系)
  - **Layer B 知识地图侧栏** = LLM 推断的结构信号(cluster / 近重复 / 孤儿 /
    衰老,**辅助信号**,不是用户认可的关系)
  - 两层 UI 互补,不替代

§3 Layer B 的"显式不做"清单中其他两项**不变**:
- ❌ Tag taxonomy(top-down 强制分类仍然是 fail mode)
- ❌ 自动归档 / 自动合并(违反 §1 契约)

§7 边界表(`vs ADR-0011 的"显式不做 graph view"`)对应行也无效;
ADR-0011 amendment 已同步处理。
