# 0029 — knowlet 的认知契约

> **中文**(English to follow if needed)

- Status: Accepted
- Date: 2026-05-15
- Last update: 2026-05-16(§4 加 3-test、§4 原则 7 加 capture-time default 与 4 个 anti-drift 兜底、§4.5 命名 confirmed、Lint 触发约束 §5b)

**重要 status(2026-05-16)**:knowlet 处于 v0.x 开发期(per ADR-0022),**无外部用户**。本 ADR 的所有 schema 字段、frontmatter 标记(如 `_origin` / `_type`)、目录约定(如 `drafts/archive/`)在开发期**可自由迭代**,不需要写 migration 路径。一旦 bump 到 v1.0.0-rc.1 进入灰度期,本 ADR 引入的所有数据结构必须按 ADR-0018 §1 演进规则处理(届时再 ADR amendment)。

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

## §2 服务边界(核心 / 支持 / 不优化)

**核心服务**:把知识沉淀当**自我成长过程**的人。 
**同样支持**:这类用户日常会用到的资料 / 参考 / 备查内容(通过资料类型,详 §4.5)。**混合使用(主要内化 + 少量资料)是目标场景**,不是 fallback。

**不优化**:把笔记软件当"增强版 ChatGPT"、**primary mode 是 AI 帮我囤积 + 查询而非自我成长** 的用户。这类用户技术上能用 knowlet(资料类型对他们可用),但 knowlet 的 design choices(深度可见 / anti-drift / 无 gamification / Vault Health Dashboard 反虚假积累)在反向工作,实际体验**不如 Notion AI / Mem.ai / Glasp**。

如果你是这类用户:**为了你自己好,建议选更合适的工具**。

**关键区分**: 我们不是排斥"想存资料"的需求(几乎所有用户都会有),我们不优化的是"**把笔记软件当 AI 个人助理来囤积而非用来成长**"这个 primary mode。两者是 dominant intent 的区别,不是 feature 支持的有无。

承认 honest scoping 缩小 TAM,但**广谱 AI 笔记产品**(同时讨好深度学习者 + 囤积者)在 AI 时代必然陷入 identity crisis;**小而深的定位才能活**。同时承认:产品挑用户 / 用户也挑产品是**双向**过程,本 ADR 的 honest scoping 是为了让 self-selection 更准,减少 mismatch churn,不是单方面拒绝。

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

#### §4 原则 5 ↔ 原则 6 边界检测(3-test)

原则 5 "AI 不主动浮" 跟原则 6 "提供内部觉察 banner" 表面有矛盾,实际是同一原则的两面。具体边界用 3-test 判定:

某条提示是 **push(违反原则 5)** 还是 **invite(满足原则 6)**?三个问题:
1. 用户 dismiss 后**永久消失**吗?(还是再次出现?)
2. 不 dismiss 也能**继续工作**吗?(还是阻断主流程?)
3. 措辞是**邀请性**吗?(还是 demanding / urgent?)

3 个 yes → 允许 invite。任何一个 no → 违反原则 5,改设计。

**例子对照**:

| UI 表现 | dismiss 后永久消失? | 不 dismiss 也能工作? | 措辞邀请性? | 判定 |
|---|---|---|---|---|
| ai-drafted note 顶部一次性 banner "要现在过一遍?" | ✅ | ✅ | ✅ | OK invite |
| Dashboard 显示 "本月 17 篇直接 accept" | ✅(用户开才看) | ✅ | ✅ | OK invite |
| 启动时 modal "你欠 12 条 review!" | ❌(每次启动) | ❌(阻断) | ❌(demanding) | ❌ push |
| 红色 badge 显示 drafts 数 | ❌(常显) | ✅ | ❌(暗示 urgent) | ❌ push |

### 原则 7: Anti-drift design(反漂移设计)

假设用户长期一定会漂向懒。设计让正确行为是 default,懒行为需 explicit cost。

**模式**:
- approve 单一动作必须看到 final 形态;不能从列表批量秒批
- 没有 "all-accept-default" 按钮
- chat 答案 source citation 比 answer 视觉权重更高(轻 nudge 用户回 source)

**Capture-time inline review 是 default,drafts queue 是 explicit-defer exception**:

这条 invariant 防止 drafts queue 变成"AI 输出垃圾场" → 破窗效应 → 永远的"明天 review"。具体:

1. **任何 AI 生成内容,UI 必然给用户一次"看到 + 决定"的机会**,不允许默默落 drafts queue
2. **drafts queue 仅装"用户 explicit 选 save-for-later"的内容**,不是"AI 默认落点"
3. **入口分四类**(详 ADR-0009 amendment):
   - chat 粘 URL → 当场 inline review(三按钮:资料 / 知识 / 暂存)
   - 拖拽 / Capture box → 模态半屏,必须 confirm
   - Mining task 后台跑完 → 下次 knowlet 启动 first thing 看到 + 主动跳过 3 次才进 queue + 上限自动暂停
   - chat 里"帮我起草" → 当场显示,当场决定

**Drafts queue 的 anti-drift 兜底**(防止 deferred 部分长期堆积):
- **age tickling**: 7 天灰显;30 天 banner "要 review 还是归档?";90 天自动归档到 `drafts/archive/`(不删,可恢复)
- **soft limit**: active queue > 20 → 创建新 draft 时透明提示"已有 23 条 deferred,先 review?"(不 block)
- **Mining task 节流**: 每 task 默认 max 5 pending,达上限 task 自动暂停
- **无 streak / guilt / 红 badge**(per 原则 6 + §4 3-test)

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

**Dashboard discovery 机制**(2026-05-16 加 — self-review 发现 dashboard 如果没人主动开,等于原则 8 形同虚设):
- **Threshold invite(一次性)**: vault 达到关键 milestone(50 篇 / 200 篇 / 500 篇)时 invite 一次"想看 Health Dashboard 吗?"。过 §4 3-test(dismissible 永久、非阻断、邀请措辞)。每个 milestone 只触发一次,不重复
- **常驻信息行**: 在自然 surface(Settings 首页 / Capture 面板顶部)放一行 muted 小字 "Vault Health: 8 drafts pending · 5 stale notes" → 点击跳 dashboard。信息常驻但视觉权重低,不打扰
- 这两条都过 §4 3-test,属 invite 不属 push

## §4.5 知识 vs 资料(两类内容的并行路径)

并非所有进 vault 的内容都需要同等深度的认知处理。强制全部走"严格 engagement gate"会逼用户去用别的工具存参考资料,违反 knowlet 帮用户省摸索时间的差异化(per memory `project_knowlet_ai_value_is_curated_workflow`)。

knowlet 因此区分两类笔记:

| | **知识** | **资料** |
|---|---|---|
| 含义 | 你**理解 + 拥有 + 能用**的东西 | 你**收藏 + 可查 + 不用时记得**的东西 |
| 例子 | "RAG 怎么工作 / 我对 X 的判断 / 这个 bug 的根因" | API 文档 / 配方 / 历史时间线 / 网页 clip |
| 价值度量 | 用户认知能力 | vault 的查得到率 |
| 处理路径 | 必须 engagement | 只要 findable |

**8 条原则在两类内容上的应用强度**:

| 原则 | 知识 | 资料 |
|---|---|---|
| 1 用户是最后字节通道 | **强制 review queue**(per ADR-0024 hybrid 路径) | **轻量确认**(单击保存即可) |
| 2 AI 是脚手架 | 同样 | 同样 |
| 3 降摩擦 ≠ 跳认知 | 严格(cognitive 工作禁止 AI 替做) | 放宽(AI 自动 extract + 落入资料库 OK) |
| 4 traceable | 同样 | 同样(资料更要 traceable,将来要 cite) |
| 5 AI 不主动浮 | 严格 | 同样 |
| 6 不外部评判, 提供内部觉察 | dashboard 重点关注**深度** | dashboard 关注**库存量 + 查询命中率** |
| 7 Anti-drift | 强制(approve 不批量秒批) | **不需要**(资料就是 stockpile) |
| 8 Make depth visible | 重点 metric:"engage 了多少知识" | 单独 metric:"存了多少、最近用了哪些" |

**默认分类(按 source)**,用户可改:

| 创建路径 | 默认 | 理由 |
|---|---|---|
| 手动 ⌘N 新建 | 知识 | 主动写 = 主动思考 |
| 从 chat 沉淀为草稿 | 知识 | 主动思想产出 |
| 网页 URL 粘贴 → Capture extractor | 资料 | 绝大多数是参考用 |
| 拖拽 PDF / 文件 | 资料 | 同上 |
| Mining task 抓回 | 资料 | 自动收集本就为 stockpile |
| 模板新建("今日笔记") | 知识 | 日记 / 反思类 = 主动思考 |

**Chat 里粘 URL** 这个特殊入口(模糊场景):**两等权按钮**让用户选,没有默认 — 因为用户当下意图常常分裂(可能想讨论 / 可能想沉淀 / 可能想存档),逼用户做一次有意义的判断。

**升级 vs 降级 不对称**(per 原则 7 anti-drift):
- 资料 → 知识 = 升级,直接生效
- 知识 → 资料 = 降级,需二次确认(防 escape hatch)

**Dashboard 双 metric 显式区分**:
- "知识维度: N 篇 / X 篇自己写 / Y 篇 AI 起草重改 / Z 篇 AI 起草直接 accept"
- "资料库存: M 条 / 最近 30 天访问 K 条"
- **vault 对外可见的"总笔记数"不在主界面突出展示**,避免虚假积累奖励通路对资料类生效

**Meta 原则: 结构决策必须 visible**:笔记类型(知识 / 资料)必须在**用户做保存决定的同一屏内**显示 + 可改;**绝不藏在 frontmatter / settings / 二级菜单**。用户应当 NEVER 需要琢磨"这条笔记现在是哪类",knowlet UI 永远直接告诉他。

**Permanent learnability(2026-05-16 加 — self-review 发现 dismiss-once onboarding 假设过强)**:
- 任意 chip 鼠标 hover → tooltip 永久可用,显示一句话解释("知识 = 你要内化的内容,会进 review queue / 资料 = 备查内容,直接存")
- 任意 chip 旁边可选 `(?)` 一级 affordance,点开展开更长解释
- 这条对 dismiss-once onboarding 是补强:onboarding 解释一次给意识到的人,hover tooltip 给所有人随时复习

**命名 confirmed**(2026-05-16):
- 中文: **知识 / 资料**
- 英文: **Knowledge / Reference**
- 不使用"笔记 / 素材"(素材过于原料感)、"沉淀 / 收藏"(收藏跟 Favorites 撞名)

**Mobile 端处理**(forward-looking,Phase 5 落地时按此原则):
- **不支持 drafts review on mobile**(per 用户 2026-05-16 决定:review 不带 edit 是半成品)
- 移动端可**read-only 显示 deferred drafts 数 + age**(信息,不操作),提示用户回桌面处理
- 知识类笔记的深度审 / 编辑 → 桌面端
- 资料类笔记的快速浏览 + 复习 → 移动端 first-class
- 这条跟 ADR-0029 §1 移动端定位"读 / 复习"一致

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

## §5b Linter 触发约束(amendment to ADR-0024 §4 Linter role)

Linter 跑得起 ≠ 应该主动跑。具体触发规则:

- ✅ **允许触发**:`knowlet lint` 命令 / Settings 里 "扫描笔记" 按钮 / 用户 opt-in 配置的 scheduled run(默认关) / 用户 opt-in 周报(默认关)
- ❌ **禁止**:knowlet 启动时自动跑 / 笔记保存时自动 lint / 任何不经用户 explicit 触发的 lint

**Lint 输出渲染**:
- 报告 = 列表式(用户主动开 Lint 面板才看)
- frontmatter 标记 = `status: needs-update` 写到对应笔记(per ADR-0024 §B 不动正文,只动 status field)
- 进 Vault Health Dashboard 分类汇总(用户主动开)
- **NoteView 一次性 banner**:仅在用户打开 `status: needs-update` 笔记时显示,过 §4 3-test(dismissible + non-blocking + 邀请措辞)
- **绝不**主动弹结果 modal / 红点 / 通知

**Why 这条 amendment**:Lint 跨 vault 扫一次,可能输出几十条问题。如果完成后主动弹,违反原则 5 + 制造类似 drafts queue 的 backlog 焦虑;如果不约束触发,后台自动跑会变成低质量噪音源。**用户主动触发 + 结果信息化呈现 = Lint 该有的姿态**。

**Lint 自身的 backlog anti-drift(2026-05-16 加 — self-review 发现:lint 报告 50 条同样会 backlog)**:

跟 drafts queue 平等处理 — 适用原则 7 anti-drift:
- **信息分级显示**:Lint 报告按 severity 排序;默认只显示前 10 条,其余折叠 "...还有 N 条"。**避免一打开就被 backlog 压垮 → 关掉 → 永远不处理**
- **`status: needs-update` 标记的 age tickling**:
  - 14 天未处理 → 笔记 list / dashboard 上 muted 颜色显示
  - 30 天未处理 → Vault Health Dashboard 出现一行 "未处理 lint: 8 条,要看看吗?"
  - 90 天未处理 → 标记不删但 hidden 出 active lint view(per drafts queue 相同的 archive 模式)
- **无 streak / guilt / 红 badge**(同 drafts queue)

## §6 不做的事(显式划清)

本 ADR 跟其它 ADR 的 anti-goal 联动:

- ❌ **AI 替用户做笔记入库的最终决策**(per ADR-0024 §A;本 ADR 原则 1)。**注意**:AI **允许写大量正文**,只要用户**显式调用** AND **走 review 流让用户做最终入库决策**。差异是触发模型 + 决策权,不是 AI 写多少字数
- ❌ **AI auto-tag / auto-move / auto-merge / auto-import-to-vault 等任何不经用户显式触发就改 vault 状态的行为**(per ADR-0024 §C/D;本 ADR 原则 1 + 7)
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
  - 成熟 agent prompt 工程借鉴策略
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
