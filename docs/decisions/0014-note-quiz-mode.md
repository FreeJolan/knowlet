# 0014 — 笔记考试模式 / Scope-driven 主动召回

> [English](./0014-note-quiz-mode.en.md) | **中文**

- Status: Proposed
- Date: 2026-05-02

## Context

[ADR-0012](./0012-notes-first-ai-optional.md) 把身份钉为"笔记软件 + AI 是可选增强";[ADR-0013](./0013-knowledge-management-contract.md) 处理**碎片化**(被动 review 通路:录入端 ambient / 被动结构化 / 定期摘要)。

但 ADR-0013 §4 也指出一个被动 review 不能解决的失血点:

> 用户跟 AI 合作构建笔记时,AI 替用户做了大量"提取关键点 / 总结概念"的工作。Note 存在了,但**学习未必发生**。Active recall(主动召回 / 自我测试)是这类失血的标准止血方式。

[ADR-0001(已归档)](./archive/0001-wedge-learning-first.md) 的原始 wedge 就有 `AI 出题 + 错题回流`,但**框架是 SRS 应试工具**(Form A);[ADR-0003](./0003-wedge-pivot-ai-memory-layer.md) pivot 到 Form B 时把它整条砍了。

本 ADR **以 Form B 框架重生**这个 idea,不再是 SRS 应试,而是:**用户主动召唤的 scope-driven active recall,AI 出题 + advisory 评分,跟 Cards 互补不互替**。

## Decision

### 1. 三条核心决定

#### (a) 用户主动召唤,scope 显式

**永远不自动弹出"考你一下"。** 用户必须主动触发,且必须显式选 scope:
- 单条 Note(在 Note 上点"考我")
- 多条 Note(file tree 多选 → 考我)
- 一个 tag / cluster(待 Layer B 知识地图实施后)

**反面**:Anki / Duolingo 那种"今天 N 张到期,推送给你"的被动通路 —— 那是 Cards 的领域。本模态是"我现在想检验一下我对 RAG 这一簇笔记的理解"。

#### (b) AI 出题,题型多样

避免"水题"(如"这条笔记的三个要点是什么" — 那是 extraction,不是 active recall)。强制题型多样化:

| 题型 | 例子 | 检验什么 |
|---|---|---|
| Concept explanation | "用你自己的话解释 RRF 中 k 的作用" | 概念内化 |
| Application | "如果一个 vault 有 1 万条 Note,RRF 的 k=60 是否还合适?为什么?" | 迁移应用 |
| Contrast | "BM25 和 cosine 在哪些 query 类型上失败模式不同?" | 区分理解 |
| Inference | "如果向量召回完全失败,RRF 还能给出有意义结果吗?" | 推理能力 |
| Recall | "什么是 cross-encoder re-ranking?何时该用?" | 回忆 + 应用 |

生成 prompt 强制要求 N 道题中 ≥ 3 种题型。

**显式拒绝**的题:
- 答案能从源 Note 文本里直接 ctrl-F 找到的 → 太浅
- "请总结这条 Note 的要点" → extraction 不是 recall
- 无 ground truth 的"开放讨论题" → 评分不可靠

#### (c) AI 评分是 advisory,不是权威

**评分必须给理由 + 用户可一键 override。** 跟 ADR-0013 §1 契约同源 —— AI 给信息,人做决定。

每题展示:
```
题目:[question]
你的回答:[user answer]
AI 参考答案:[reference]
AI 评分:[score] · [理由]
[ ✓ 我同意 ] [ ✗ 我不同意 ]  ← 不同意会展开理由输入框
```

session 结束的统计**必须**显示 disagree count:"5/7 答对(其中 1 题你不同意 AI 评分)"。**永不替用户决定他答对没答对。**

### 2. Quiz session 生命周期

```
[user] 触发 → [scope picker] → [generation] → [N 道题 loop] → [summary + 回流入口]
   │           │                  │              │                      │
   palette     Note / Notes /     LLM 调用       answer + grade         Cards 回流(可选)
   Cmd+K       tag / cluster      生成 N 题      + 用户确认             past-quiz 归档
   或 Note     (P2 才有)
   右键
```

**触发位置**:
- Cmd+K palette 命令:`考我`
- 单条 Note 的右键 / icon:`考我这条`
- 多选 Note 后 file tree action:`考我这几条`
- (P2)tag 或 cluster 视图里的 `考我这一簇`

**Generation 后:**用户先看到"出了 N 题,基于 [scope 概要]",可点 `开始` / `换一组` / `取消`。

**Loop 中:**每题独立显示;答题时长无强制(active recall 不是计时考试);随时可 `pause` / `quit`(已答的部分入归档)。

**Summary:**展示分数(含 disagree 标注)+ 错题列表 + 每题"做成 Card"1 键。

### 3. 题目质量(技术 load-bearing 部分)

跟 ADR-0013 §6 类似,这一节是工程上最难的部分。

#### 3.1 Generation prompt 骨架

```
You are creating an active-recall quiz for a knowledge worker who wrote
the following notes. Generate {n} questions across at least 3 of these
types: concept-explanation, application, contrast, inference, recall.

Requirements:
- Each question must NOT be answerable by ctrl-F over the source notes
  (no "what are the 3 key points" style; no quote-then-fill).
- Each question must have a defensible reference answer using only the
  source notes (don't invent facts not in the notes).
- Mix question types — a quiz of 5 must use at least 3 different types.
- Use the same language the notes are in.

Source notes:
[source ...]

Output strict JSON: {questions: [{type, question, reference_answer, source_note_ids}]}.
```

#### 3.2 Rejection / regeneration

如果 LLM 生成的题不符合上述 requirements(用户主观判断 / heuristic 检测如"题面 50% 字符与 Note 文本重合"),给"换一组"按钮,**不收费第二次生成**(免费的 Q&A 重生不应让用户犹豫)。

#### 3.3 Session 长度默认

**默认 5 题 / session,用户可在 scope picker 的「高级设置」入口调整**(临时该次 session,或勾选 `记住此设置` 持久化到 vault config)。理由:
- 太少(1-2)出错率方差大
- 太多(15+)疲劳,active recall 收益递减
- 5 题 ≈ 5-10 分钟,跟 Cards 单次 review 时长接近

跟 [`feedback_default_plus_advanced_override`](memory) 一致 —— 给默认值,通过 UI 高级设置允许临时 / 持久化覆盖。

### 4. 评分模型

#### 4.1 Score 标度

**单题 1-5(整数)** —— 跟 FSRS 的 1-4 借鉴但加一档(允许"非常好,超出预期"):
- 1 完全没答出 / 错误
- 2 答出方向但缺关键
- 3 答出关键但有遗漏 / 偏差
- 4 答得完整且准确
- 5 答得完整准确且补充了源 Note 没明说的合理推论

理由:LLM 在百分制上评分**不稳定**(95 vs 88 在 LLM 内部分布上没本质差异),5 档区分度足够稳定。

**Session 最终分数 = 0-100 整数**(2026-05-02 用户拍板)。

聚合公式:
```
session_score = round( (sum_of_per_question_scores / (n_questions * 5)) * 100 )
```

理由:用户对 0-100 有直觉(及格线 60、优秀 90),便于纵向对比"我半年前考 RAG 那簇得 70,这次 85"。但**单题层面仍只展示 1-5**,因为单题没有可对比的纵向数据,百分制反而会让用户纠结 95 vs 88 的伪精度。

#### 4.2 评分 prompt 骨架

```
Grade the user's answer to the quiz question. Output strict JSON:
{score: 1..5, reason: "...", missing: ["...", ...]}.

Be charitable — if the user uses different wording but covers the same
concept, full credit. Don't penalize formatting / brevity.

Question: [...]
Reference answer: [...]
User's answer: [...]
```

#### 4.3 用户 override

`不同意` 弹文本框(可空),记录在 session 里。session summary 永远显示 `ok / disagreement` 计数,而不是单一总分。

### 5. Storage 模型

#### 5.1 Trade-off

- **Ephemeral**(关掉就消失):跟 ADR-0013 反碎片化对齐,简单
- **Persistent**(留盘):支持"看我的错题历史"、Cards 回流需要题面+答案保留、可做长期 active-recall 进步追踪

#### 5.2 决定

**Persistent,但藏在主 UI 之外。**

- 路径:`<vault>/.knowlet/quizzes/<id>.json`
- **不进** `notes/` 文件树
- **不进** 主 UI 列表(Notes / Drafts / Cards)
- 访问入口:专用的 "Past quizzes" focus mode(M7.4 Phase 3 才做)
- 老化策略:**默认 90 天后归档到 `.knowlet/quizzes/.archive/`**,除非该 session 有 Card 回流(说明用户从中学到东西,值得长留)
- 周期可配(沿用 ADR-0013 Layer C 的 user-configurable pattern)

session schema 草案:
```json
{
  "id": "<ulid>",
  "started_at": "...",
  "finished_at": "...",
  "model": "claude-opus-4-7",
  "scope": {
    "type": "notes" | "tag" | "cluster",
    "note_ids": ["..."],   // for type=notes
    "tag": "...",          // for type=tag
    "cluster_id": "..."    // for type=cluster (P2)
  },
  "questions": [
    {
      "type": "concept-explanation",
      "question": "...",
      "reference_answer": "...",
      "source_note_ids": ["..."],
      "user_answer": "...",
      "ai_score": 4,
      "ai_reason": "...",
      "user_disagrees": false,
      "user_disagree_reason": null,
      "card_id_after_reflux": null
    }
  ],
  "summary": {
    "n_questions": 5,
    "n_correct": 4,        // by AI score >= 3
    "n_disagreement": 1,
    "cards_created": 2
  }
}
```

### 6. Cards 回流

session 结束的 summary 页面列出**所有错题**(AI score < 3 或 user marked unsure),每条带勾选框 + "批量做成 Card"按钮(2026-05-02 用户拍板):

- **错题列表默认全部勾选**,用户可减勾不想要的
- 每条 Card 草稿可单独 inline 编辑(front / back / tags)
- back 默认填 reference_answer,但用户可改写为自己修正的版本
- tags 默认 = 源 Note 的 tag 集合 ∪ `{quiz}`
- source_note_id 已知则填

**只有错题进入回流候选**(答对的题不强推 Card,避免冗余 Card 库)。

这条**呼应 ADR-0001 砍掉的"错题回流"概念,但在 Form B 框架下完全不同**:不再是"应试系统的错题本",而是"主动召回时发现的认知缺口的针对性 spaced retrieval"。

### 7. 边界

| vs | 区别 |
|---|---|
| Cards / FSRS | Cards = 原子事实级,定时到期 SRS 调度,被动通路;Quiz = 跨 Note 主动召回,用户驱动,scope-explicit |
| ADR-0013 Layer C 周报 | 周报是被动接收"这周新增 / 衰老候选";Quiz 是主动召唤"考我这一簇" |
| ADR-0013 §6 Similarity | Quiz scope picker 在选 "这一簇" 时**会**用 similarity 做"基于这条 Note 找相关的来一起考"的 add-on,**但这是 UX 增强,不是 Quiz 核心** |
| ADR-0001 砍掉的"AI 出题" | 旧框架是 OCR + SRS Card + AI 出题(Form A 应试);本 ADR 是 Form B 知识工作者主动召回,Cards 仍是被动 SRS,Quiz 是新模态 |

### 8. 实施切片(M7.4)

| Phase | 范围 | 验收 |
|---|---|---|
| **M7.4.0** | 设计 prompt + 在 CLI 跑通 generation + grading(无 UI) | 命令行能跑出可读题面 + advisory 评分 |
| **M7.4.1** | UI MVP:scope = 单 Note / 多 Note 手动选;题型 = concept + recall;advisory 评分**无** disagreement loop | 用户能从 palette / Note 触发,跑完 5 题流 |
| **M7.4.2** | + 4 种题型 + disagreement loop + Cards 回流 | summary 页可单题转 Card,不同意可输理由 |
| **M7.4.3** | + tag / cluster scope(依赖 ADR-0013 Layer B 落地) + past-quizzes focus mode + 90 天老化 | 历史 quiz 可回看,scope picker 支持 tag |

每 phase 独立 commit + 不打 tag(M7.4 整体用一个 tag `m7.4`)。

## Decisions locked(2026-05-02 用户拍板)

1. **Score 标度** — 单题 1-5 整数 / session 最终 0-100(见 §4.1 公式)
2. **默认 session 长度** — 5 题,用户可在 scope picker 的「高级设置」入口临时 / 持久化覆盖(见 §3.3)
3. **Quiz UI 形态** — 独立 focus mode `Cmd+Shift+Q`,跟 chat / drafts / cards focus 同组
4. **Cards 回流默认行为** — 仅错题进入候选列表;**列表内默认全勾选**,用户可减勾不想要的;支持单条 inline 编辑(见 §6)
5. **生成不满意时** — `换一组` 无限重生(active recall 价值 ≫ token 成本,不该卡这一步)

## Consequences

### 落地后

- **每个新 ADR-0013 Layer A/B/C feature 落地时,本 ADR 的 active-recall 通路成为对照**:碎片化治理是被动一边,Quiz 是主动一边,产品故事完整
- **Cards 回流路径成为 Quiz → Cards 的主要新建路径之一**(目前 Cards 主要从 chat 由 LLM 主动生成 / CLI 手写)
- **`.knowlet/quizzes/` 是 vault 内第三种 LLM 生成的持久化数据**(after `notes/` 和 `drafts/`),需要在 ADR-0006 §"重建机制"补一笔(M7.4.1 commit 时顺手)

### 风险 / 代价

- **题目质量是非确定性 LLM 输出的产物**;P@质量 可能 < 0.7,需要 dogfood 校准 prompt
- **AI 评分跟 ADR-0013 §1 契约的距离**:评分本身就是判断,但因为 advisory + 永远显示 disagreement,**用户最终拍板**这一条契约不被违反
- **storage 长期 ≠ 主 vault**:有用户可能想找"我半年前考过的题",90 天老化的设计需要在 dogfood 期校准
- **scope = tag / cluster 依赖 Layer B 落地**;P3 必须等 ADR-0013 Layer B 完成,不能并行

### 跟现有 ADR / memory 的关系

- 兑现 [ADR-0013](./0013-knowledge-management-contract.md) §4 承诺的"ADR-0014 是另一条 review 通路"
- 落地 `project_knowlet_note_quiz_idea` memory 的全部内容(5 个 待考虑点 + 跟 Cards 的对照表 + 历史回溯)
- 反向 inform [ADR-0001(已归档)](./archive/0001-wedge-learning-first.md):那条砍掉的"错题回流"概念在 Form B 重生,本 ADR §6 落地;ADR-0001 archive 注释可加一句指向本 ADR
- 触发 [ADR-0006](./0006-storage-and-sync.md) 微改:`.knowlet/quizzes/` 进重建机制清单(M7.4.1 实施时改)

### 决策溯源

- 用户原话(2026-05-02):
  > 当用户和 AI 合作构建一篇笔记时,用户可以圈选(多篇)笔记,甚至圈选 topic/label(tag),然后由 AI 出题甚至评分,从而实现用户"主动吸收"的诉求,毕竟 AI 参与会分担走大量积累过程中的收获点。
- 5 个具体待考虑点来自 `project_knowlet_note_quiz_idea` memory(2026-05-02 整理)
- 跟 ADR-0013 同期决定:用户在 ADR-0013 拍板时(2026-05-02)确认"ADR-0014 立刻起草"
- 历史回溯:ADR-0001(2026-04-30,已归档)的 SRS-应试 wedge 砍掉后,"AI 出题"这个 idea 在 Form B 框架下重新焕发价值;两条 ADR 在概念上呼应,但产品故事完全不同
