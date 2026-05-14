# 0029 — knowlet 的认知契约

> **中文**(English to follow if needed)

- Status: Accepted
- Date: 2026-05-15

## Context

ADR-0013 锁定了 "**用户拥有,LLM 提案**" 的所有权根原则;ADR-0024 把它落到 7 个 AI role + 工作类别分类;ADR-0028 给每个 AI role 钉了 8 条机制约束。

但这些 ADR 都在回答 **"AI 该怎么做"**,没回答更上游的问题:**knowlet 为什么这样设计 AI?它服务的认知目标是什么?它的目标用户是怎样的人?它对人类学习与记忆的假设是什么?**

到 2026-05-15 为止,这些 deeper position 还散在头脑里和聊天历史里,没有被 codify。本 ADR 是 knowlet 所有 AI / IA 取舍的**根原则锚**,排在 ADR-0013 / 0024 / 0028 之前(它们的根原则都收敛到本 ADR)。

## §1 核心命题(knowlet 存在的理由)

**knowlet 服务于这样一类用户:对他们而言,知识本身就是成长 —— 构建知识库的*过程*就是目的,而不只是终态的 artifact。**

这条命题展开:
- 用户不是来"养肥一个 vault" 的;用户是来**通过沉淀知识让自己长大**的
- vault 是这个过程的副产品 + 长期记忆的延伸,不是 the goal itself
- 衡量 knowlet 价值的真正 metric 不是"vault 体积",是 **"用户认知能力的长期增长"** —— 即便后者不可直接测量

**这条不是产品偏好,有认知科学背书**:
- **Generation effect**(Slamecka & Graf, 1978):自己生成 > 被动读取,记忆留存差 30-50%
- **Desirable difficulties**(Robert Bjork):学习中适度费力是必需的,完全平滑的输入损害长期保留
- **Google effects on memory**(Sparrow et al., 2011):预期"信息能再找到"使大脑主动减少存储和加工
- **Deliberate practice**(Anders Ericsson):专家级直觉是大量主动加工的副产品,不是被动接触
- **Dreyfus skill acquisition** + **Kahneman dual-process**:System 1 直觉是 System 2 反复训练后的固化

knowlet 设计接受这些共识,让产品服务它们,而不是对抗它们(对抗即:让 AI 替代用户的认知加工)。

## §2 服务边界(诚实地说不服务谁)

knowlet **不是为这类用户设计**:
- 想"塞一堆 AI 整理好的内容,需要时让 AI 帮我查" 的人
- 把笔记软件当"增强版 ChatGPT" 的人
- 在意"laps notes 数翻倍" 而不在意"我自己理解了什么" 的人

对这类用户,**Notion AI / Mem.ai / Reflect / Glasp 等更合适**。knowlet 用清晰的边界换深度的服务,不试图同时讨好两类用户。

承认这缩小 TAM,but **honest scoping 是 strong positioning 的前提**;广谱产品在 AI 时代会陷入 identity crisis,小而深的产品才能活。

## §3 关于人类认知局限的现实假设

knowlet 设计**假设典型用户是**:
- **初衷正确**(想内化、想深度学习、想长期积累)
- **意志力有限**(per Baumeister 的 ego depletion 研究 —— 日常工作 / 家庭 / 情绪都在消耗 willpower,留给"主动深度处理"的余量极少)
- **长期会漂向懒**(per phenomenon §3.1)
- **会被可见 metric 引导**(per phenomenon §3.2)

**这个假设不是对用户的恶意 / 不信任,而是对人类客观规律的承认。** 极少数 self-driven 超人(具备极强的自我管理能力)不在此假设内 —— 他们不需要 knowlet 的支撑机制,但 knowlet 的设计基线**为常人服务,不为超人服务**。超人用 knowlet 会感受到轻微的支撑性 friction,但不会被困扰;常人则真正受益。

knowlet 的 voice 应当反映这个 framing:
- ❌ "我们假设你会偷懒,所以加这些限制"(disciplinary,冒犯)
- ✅ "我们承认意志力有限是科学事实,所以加这些支撑"(empathic,服务)

### §3.1 Behavioral drift(行为漂移 phenomenon)

即便用户初衷正确,**只要设计允许懒,长期一定会漂向懒**。 
不是因为用户不诚实,而是因为意志力是稀缺资源。

**设计含义:** 不能假设"用户初衷正确 → 长期保持正确行为"。 
**好设计 = 让正确行为是 default,错误行为需要 explicit effort 才能进入。**

### §3.2 False accumulation(虚假积累 phenomenon)

笔记数量上升 → 大脑奖励中枢被激活("我在积累知识")→ 但真实掌握度可能持平甚至下降。 
这是真实存在的认知偏差,类似 "藏书症"(拥有书 ≠ 读过书)。

vault 体积是 **highly visible** 的 metric;真实理解度是 **invisible** 的。如果只让前者可见,用户必然漂向养肥 vault 的虚假满足感。

**设计含义:** 必须让"深度"成可观察的 metric,否则用户没有 self-correct 的反馈环。

## §4 8 条设计原则

本 ADR 把上述命题翻译成 Phase 3 + 后续所有 AI / IA feature 设计**必须**满足的 8 条原则。任何提议过不了本 §4 checklist,直接拒。

### 原则 1: 用户是"最后一个字节"的强制通道

任何进入 vault 的内容必经用户的注意 + 决定。这是 ADR-0024 hybrid 路径的根 mechanism。

**模式**:
- AI 产物先进 `drafts/`,不直接写 `notes/`
- 没有 "AI auto-write to vault" toggle,任何 settings 下都没有
- approve 动作必须看到 final 形态;**不允许 chain-approve(批量秒批)**

### 原则 2: AI 是脚手架,不是支撑柱

脚手架特性 = 拆掉后用户依然能站着。 
**关掉 AI 后,knowlet 退化成纯笔记软件,所有 vault 内容仍可读、可搜、可改、可备份。**

**模式**:
- 本地零 LLM 模式始终可用(per ADR-0028 §5, ADR-0013)
- title / tags / folder / links 等结构性元数据若是 AI 提议,必须用户 explicit accept;不可由 AI 默写
- 不引入 "AI dependency" feature(如:auto-tag 后搜索全靠 AI 解释 —— 关 AI 即瘫)

### 原则 3: 降摩擦 ≠ 跳认知动作

AI 可以让用户**少做 mechanical work**(打字 / 找位置 / 抓 URL),**不可让用户少做 cognitive work**(理解 / 判断 / 决定 / 关联)。

**模式**:
- ✅ AI 抓 URL 元数据(title / favicon / 发布日期) —— mechanical 节省
- ✅ AI 推荐 folder —— mechanical 找位置,accept 是 cognitive 动作
- ❌ AI "理解一篇论文然后塞结论给你" —— 跳过学习过程
- 模糊场景:AI summarize 长内容 —— 允许做,但 summary 标 "AI-summarized" 状态,且 UI 鼓励用户看原文 + 自己改 summary

### 原则 4: AI 输出永远 traceable,引用比答案显眼

让用户养成"直接回 source 看" 的反射,而非"读 AI answer 当结论"。

**模式**:
- Chat 答案下方 "Sources" 卡片 —— 与答案同等 visual weight,可点击直跳笔记
- Editor advisor:**先**显示"基于这 5 篇 [titles]",**后**才是"建议放 X"
- Linter 每条问题都指向具体笔记片段,用户必须打开看才能 resolve
- 不做 "AI 总结今日笔记" 等让用户跳过原文的 feature

### 原则 5: AI 不主动浮出,需要用户召唤

User-pull,不是 AI-push。default 路径是"自己写",召 AI 是 explicit 选择。

**模式**:
- 编辑器无 typing-time autocomplete(per ADR-0028 §3 也已说不抄 Cursor Tab autocomplete)
- AI 提议在"建议中心"等用户主动来看,不弹通知 / banner / popup
- chat 必须用户主动打开,不会在写笔记时自动冒出
- 选中文本 + 快捷键召唤 AI 是允许的(Cursor 借鉴),**前提是用户主动 select**

### 原则 6: 不外部评判,但提供内部觉察

**外部压力** = "你 7 天没复习了!" / streak / badge / leaderboard —— 把学习变债务,**禁用**。 
**内部觉察** = on-demand dashboard / origin marker / 邀请性 banner —— 信息透明,用户自决,**鼓励**。

**模式**:
- 没有 streak counter / 没有 "你掉了" friction / 没有公开比较
- SRS / quiz 复习提醒以邀请性措辞("有 12 张卡片可以复习了"),不催促
- 任何子系统(SRS / quiz / lint)用户可完全关闭而不影响 knowlet 主功能
- **Vault Health Dashboard** 用户主动打开才看,不主动推送

### 原则 7: Anti-drift design(反漂移设计)

假设用户长期一定会漂向懒。设计让正确行为是 default,懒行为需 explicit cost。

**模式**:
- approve 单一动作必须看到 final 形态;不能从列表批量秒批
- 没有 "all-accept-default" 按钮
- chat 答案 source citation 比 answer 视觉权重更高(轻 nudge 用户回 source)
- AI drafts queue 有自然 cost(必须主动打开 + 主动 accept / reject),不会"忘记看"则自动入库

### 原则 8: Make depth visible(让深度成可观察 metric)

只让体积可见 → 用户必然漂向养肥 vault。必须让"实际掌握度"可见,用户才有 self-correct 反馈环。

**模式**:
- 笔记 frontmatter 加 `_origin: user | ai-drafted | ai-revised | imported`(隐藏,UI 选择性展示)
- 文件树中 ai-drafted 但用户从未 touch 过的笔记,subtle visual marker(浅色 ✨ icon)
- **Vault Health Dashboard**(on-demand):
  - "本月: 47 篇 / 12 篇你自己写 / 18 篇 AI 起草你重改过 / 17 篇 AI 起草直接 accept"
  - "AI 起草后从未回访的笔记: 23 篇"
  - "90 天未触碰的笔记: 156 篇"
  - **无 badge / 无通知 / 无 streak / 无 guilt 语气**
- 点开 ai-drafted note 顶部一次性 banner:"AI 起草,你 approve 后未再修改。Source: [link]。要现在过一遍吗?" —— **邀请**,不**催促**

## §5 与其他 ADR 的关系

本 ADR 在依赖图里**位于根**(其它 AI / IA 相关 ADR 都引用它的根原则):

- **ADR-0013**(知识管理契约 / "用户拥有"):本 ADR 是 ADR-0013 §"用户拥有"原则的展开 + 落地解释。ADR-0013 说**什么**(数据所有权),本 ADR 说**为什么**(认知成长目的)
- **ADR-0024**(AI assist envelope + 7 roles):本 ADR 是 ADR-0024 §1 工作类别分类(mech/hybrid/creative)和 §5 "AI 不做的事" 的**上游 reason**。每条"AI 不做的事"都能追溯到本 §4 某条原则
- **ADR-0028**(AI 质量机制契约):本 ADR 是 ADR-0028 §2 八条机制约束的**上游 reason**。ADR-0028 钉**机制怎么做**,本 ADR 钉**为什么要这些机制**
- **ADR-0009**(mining drafts review queue):本 ADR 的原则 1 + 7 的**第一个落地 mechanism**

引用关系总结:
```
ADR-0029(本 ADR,认知契约,根原则)
    ↓ 引用
ADR-0013(数据所有权 = 认知契约的物理表达)
ADR-0024(7 roles = 认知契约的 AI 落地)
ADR-0028(质量机制 = 认知契约的 AI 实施护栏)
ADR-0009(review queue = 认知契约第一个 mechanism)
```

## §6 不做的事(显式划清)

本 ADR 跟其它 ADR 的 anti-goal 联动:

- ❌ **AI 替用户做笔记正文最终决策**(per ADR-0024 §A;本 ADR 原则 1)
- ❌ **AI auto-write / auto-tag / auto-move / auto-merge**(per ADR-0024 §C/D;本 ADR 原则 1 + 7)
- ❌ **streak / guilt / leaderboard / 通知催复习**(本 ADR 原则 6)
- ❌ **typing-time AI autocomplete**(本 ADR 原则 5 + ADR-0028 §3)
- ❌ **"AI 总结今日笔记 / 周报" 让用户跳过原文**(本 ADR 原则 4)
- ❌ **"power user 关闭所有支撑机制" toggle**(本 ADR 原则 7 + §3 框架 —— opt-out 会成为 drift 渠道,大多数自认是 exception 的人统计上不是)
- ❌ **gamify 笔记数 / 引以为荣的体积感**(本 ADR 原则 8 —— vault 大小不是 metric,反而要让深度可见来抗虚假积累)

## §7 与现实世界产品的对照

本 ADR 隐含的反面案例(knowlet 不该长成这些):

| 产品 | 反面之处 | 违反本 ADR 哪条 |
|---|---|---|
| Notion AI | `/ai` 直接出文章自动入页 | 原则 1 |
| Mem.ai | 元数据全靠 AI 推断,关 AI 等于瘫 | 原则 2 |
| Glasp | AI 一键 highlight + 总结,用户不读原文 | 原则 3 + 4 |
| ChatGPT | 答案 confident 但无源,用户不知道凭什么 | 原则 4 |
| Cursor Tab autocomplete | 打字时持续 push 建议,用户被动接受 | 原则 5 |
| Duolingo / Anki streak | streak / 通知 / guilt,把学习变债务 | 原则 6 |
| 任何 "AI 自动整理"功能 | 用户无 cost 入库,长期漂向懒 | 原则 7 |
| 任何只显示 "你有 N 篇笔记!" 的 dashboard | 强化虚假积累 | 原则 8 |

## Consequences

**Positive**

- knowlet 有了一个 robust 的根原则锚 —— 5 年 / 10 年后 AI 能力大变,本 ADR 仍然适用(因为它的根是"用户自己成长"这件事的不变性,不是"AI 能不能"的可变性)
- Phase 3 + 后续每个 AI feature 提议在动手前有清晰的 8 条 checklist,过不了直接拒。设计成本下降
- 对外讲产品时有清晰的差异化锚("我们不是另一个 Notion AI / Mem.ai") —— 写进 README / landing page
- 隐含 honest user scoping —— 不试图讨好"AI 帮我搞定一切"的用户,专注服务"通过沉淀让自己长大"的用户

**Negative / Risks**

- **TAM 缩小**:honest scoping 排除了"AI 帮我囤积"的用户群,从市场规模看是损失。**Mitigation**:小而深 > 大而泛,广谱 AI 笔记产品在 identity crisis 中,knowlet 不抢那块
- **支撑机制可能被超人用户感知为多余 friction**:极少数 self-driven 用户不需要原则 7 / 8 的机制。**Mitigation**:friction 本身设计成 mild(不阻断,只提示),超人感觉到但不困扰
- **原则间偶有张力**(如原则 5 "AI 不主动浮" vs 原则 7 "anti-drift" —— 提醒用户回顾算不算主动浮?)。**Mitigation**:原则 6 把"邀请性 vs 催促性"边界画清,这类张力按那条裁决
- **认知契约对开发者 / 后来人的接受度**:外部贡献者 / 未来的 AI agent 可能不理解为什么 "AI 自动整理是好的 feature 但 knowlet 拒做"。**Mitigation**:本 ADR 写明 + memory 链接 + Phase 3 review 引用本 ADR,让拒绝有据可依

## Alternatives considered

- **方案 A:不写本 ADR,根原则散在 ADR-0013 / 0024 / 0028 里靠引用关系串起来**。问题:**每次 design review 都要重读 4 个 ADR 才能 grasp 根原则**。否。
- **方案 B:写得更短,只钉"用户拥有 + 用户最终决策"两条**。问题:**Anti-drift / Make-depth-visible 这两条原则没显式钉就丢了**,Phase 3 设计时容易回退。否。
- **方案 C:写得更长,把每条原则的具体实施细节都写到 ADR**。问题:细节属于实施层,ADR 写细节会随实现演变而过时。否,**ADR 钉原则,细节留给 design doc / code comment**。
- **方案 D:允许 "power user opt-out" 关掉原则 7/8 的支撑机制**。问题:**统计上大多数自认是 exception 的人不是 exception**;opt-out 会成 drift 主渠道,损害设计的整体效果。否。

## References

- **ADR-0013** — 知识管理契约("用户拥有")
- **ADR-0024** — AI assist envelope + 7 roles + creative 不碰契约
- **ADR-0028** — AI 输出质量机制契约
- **ADR-0009** — mining drafts review queue(认知契约第一个 mechanism)
- 项目 memory:
  - `project_knowlet_ai_value_is_curated_workflow.md` —— 差异化论点
  - `project_ai_design_borrow_from_claude_code.md` —— 借鉴策略
  - `feedback_knowlet_not_manual_authoring_centric.md` —— 用户场景定位
  - `project_ai_rework_gated_on_kb_complete.md` —— Phase 3 启动前置
- 外部 references(本 ADR §1 引用的认知科学):
  - Slamecka & Graf (1978) — Generation effect
  - Robert Bjork — Desirable difficulties
  - Sparrow et al. (2011) — Google effects on memory
  - Anders Ericsson — Deliberate practice
  - Hubert Dreyfus — Skill acquisition five-stage
  - Daniel Kahneman — Thinking Fast and Slow
  - Roy Baumeister — Ego depletion

## 实施位置

本 ADR 不是单一切片;是**所有后续 AI / IA 设计的 review gate**:

- Phase 3 每个 AI role slice 在 design review 时,必须证明本 §4 的 8 条原则都被满足
- Phase 4 灰度准备时,landing page / README / 文档 需引用本 ADR § 1 / §2 作为产品定位锚
- 后续任何 feature 提议(无论 AI / IA / 非 AI)如涉及"用户内容流向 vault",必须先过本 ADR 的 §4 checklist
- 后续如发现本 ADR 与新 ADR 冲突,默认本 ADR 优先 —— 想推翻本 ADR 必须 explicit amendment + 论证
