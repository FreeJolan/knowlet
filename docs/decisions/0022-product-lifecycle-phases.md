# 0022 — 产品上线阶段三期(开发期 / 灰度期 / 上线期)

> [English](./0022-product-lifecycle-phases.en.md) | **中文**

- Status: Accepted
- Date: 2026-05-05

## Context

knowlet 现在没有外部用户,但所有 ADR / 设计 / 修复决策的"风险评估"暗含一个用户基数假设。
这个假设没明文,导致两种失误:

1. **过度保守**:开发期我反复在"如果用户已经有数据怎么办" / "如果是 breaking change 怎么办"上花时间,
   而实际此刻**只有项目负责人一个 dogfooder**,激进的迭代代价为零。
2. **过度激进**:某些"凑合上线"的决策(M7.0 file ops 当 checklist)本来在没用户阶段没事,但**一旦走到外部用户**,
   "兼容/迁移"成本就指数级上来 — 那时再回头修就太迟。

本 ADR 把**用户基数 → 决策风险偏好**这个映射钉死,作为后续每个 ADR / 每条 PR 评审的隐性框架。

## Decision

### 三期定义

#### 1. 开发期(development)

- **用户**:仅项目负责人(本地 dogfood),**0 外部用户**
- **数据**:负责人自己的 vault(可丢)
- **决策偏好**:**激进迭代**
  - ❌ 不需要考虑旧版本兼容
  - ❌ 不需要 migration 脚本
  - ❌ 不需要 deprecation 周期
  - ✅ 可以删除整个文件 / 重做整个 surface / 改 schema 不写迁移
  - ✅ Breaking change 只需在 ADR / commit message 写明"开发期允许"即可
- **承诺底线**:**无**(负责人自己负责自己的数据)
- **当前所处阶段**: 是(2026-05-05)

#### 2. 灰度期(gray release)

- **用户**:负责人 + 数个早期用户
- **数据**:这些用户已经在**日常生活中**使用 knowlet 沉淀真实笔记
- **决策偏好**:**功能交互可激进改,数据必须保**
  - ✅ UI / UX 仍可大改(用户接受这是 early days)
  - ✅ 可以删除 feature(用 deprecation toast 提前一个版本告知)
  - ❌ **绝对不能破坏用户已有笔记**
  - ❌ schema 变化必须有 migration(自动跑 + 失败回滚 + snapshot 兜底)
  - ✅ Breaking API change 允许,但必须有版本号 / migration / 升级指南
- **承诺底线**:**用户的 vault 数据始终能打开**(即使 knowlet 当版本暴 bug,他们能 export / 复制走)
- **进入条件**(预估,可调):
  - Phase 1 知识库基线(per ADR-0021)完成
  - Phase 3 AI 能力补齐
  - 数据耐久 ADR-0018 落地(snapshot / restore / schema versioning / migration test suite 全套)
  - 至少 4 周开发期 dogfood 无重大 regression

#### 3. 上线期(production)

- **用户**:任何愿意装的人
- **数据**:用户多样化(个人 / 团队子集 / 学术 / 等)
- **决策偏好**:**保守 + 兼容优先**
  - ❌ 不能破坏 API / schema 兼容性,除非走 major version bump + 1 个版本周期 deprecation
  - ❌ 不能在不发版本说明的情况下改默认行为
  - ✅ 任何 breaking change 必须有 ADR + 用户文档 + 迁移路径
  - ✅ Bug fix / additive feature 仍然快速迭代
- **承诺底线**:
  - 数据耐久(同灰度期)
  - **API 兼容**(SemVer 严格):major bump 才允许 breaking
  - 安全 / 隐私(per ADR-0006:数据主权用户负责,但 knowlet 不能新增数据外泄面)
- **进入条件**:
  - 灰度期 ≥3 个月,有外部用户实际反馈
  - 0 已知 P0 / P1 bug
  - ADR-0019 (前端) + ADR-0020 (后端 hardening) + ADR-0018 (数据耐久) 全部 mature
  - 用户文档完整(install / use / troubleshoot / contribute)

### 阶段转换协议

- **进入新阶段必须由项目负责人主动声明**,不是 agent / 贡献者推测
- 转换时机会用 commit message 标注 + 在路线图 + memory 顶部更新
- 默认状态(未明示阶段切换 / 任何 agent 不确定时)= **当前阶段**(初始为开发期)

### 给 agent 的操作指南

每次评估"要不要做兼容 / migration / deprecation"时,先问:**当前是哪个阶段?**

| 问题 | 开发期 | 灰度期 | 上线期 |
|---|---|---|---|
| 改 Note schema(加字段)| 直接改 | 加 migration 脚本 + schema_version bump | 同左 + ADR + 文档 |
| 改 Note schema(改 / 删字段)| 直接改 | 必须 ADR + 自动 migration + snapshot | 同左 + major version bump |
| 改 API 端点路径 | 直接改 | deprecation 周期 + 旧路径保留 1 个版本 | 同左 + 用户公告 |
| 删除 UI feature | 直接删 | toast 告知 ≥1 版本 | 同左 + 文档 + ADR |
| 新增配置字段(可选)| 直接加 | 加 + 默认值文档化 | 同左 |
| 修 bug | 直接修 | 同 | 同 |
| Refactor | 直接 | 不破对外行为即可 | 同 |

### 跟其他 ADR 的关系

- **ADR-0006 数据主权**:本 ADR 灰度期 / 上线期的"承诺底线"以 ADR-0006 为基础再加严格度
- **[ADR-0018 数据耐久](./0018-data-durability.md)**(2026-05-10 起草):灰度期进入条件之一,本 ADR 引用而不重复
- **ADR-0019 / 0020 / 0021**:本 ADR 的"激进迭代"前提下,这三条得以快速 ship

## Consequences

### Positive

- **agent 决策框架明确**:再不会浪费时间评估"如果用户怎样"的假设场景(开发期没用户,直接改)
- **激进迭代有合法性**:开发期重做 file ops / 重写前端 / 改 schema 都是 ADR-0022 §"开发期"明确允许的
- **进入灰度期 / 上线期的检查清单具体**:不会"突然某天就上线了",有清晰的 gating

### Negative

- **某种激进迭代成习惯,转换到灰度期会有 culture shock**:agent 习惯了"直接改",突然要写 migration 会忘
  - 缓解:阶段切换时,我会在 memory 顶部 + 此 ADR 顶部强调,作为强提醒

### Out of scope

- 灰度期具体怎么发布(installer / 邮件邀请 / GitHub 公开)— 进入前再 ADR
- 上线期 SemVer 细节(major / minor / patch 各允许什么)— 进入前再 ADR

## References

- [ADR-0006 数据主权](./0006-storage-and-sync.md)
- [ADR-0018 数据耐久](./0018-data-durability.md) — 灰度期入口前置;Slice 4.A 起草完成,4.B-4.E 实施中
- [ADR-0019 前端栈](./0019-frontend-stack.md) — 开发期允许激进迭代 = 本 ADR 不需要 dual-render / feature flag
