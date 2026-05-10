# 0018 — 数据耐久性契约

> **中文**(English to follow if needed)

- Status: Accepted
- Date: 2026-05-10

## Context

knowlet 的核心承诺是 [ADR-0013](./0013-knowledge-management-contract.md) §"用户拥有":vault 是用户的,knowlet 只是窗口。这条承诺要在**版本升级、schema 演进、磁盘故障、误删**等所有场景下都成立 —— 否则窗口越好看,用户越不敢往里面投入。

到 2026-05-10 为止 knowlet 已经 ship 的耐久性安全垫:

- **`schema_version` 已在 commit `40cfcd0` ship**:Note frontmatter v1、QuickActions toml v1、SQLite `index.meta` v1。
- **`knowlet vault snapshot` / `restore-snapshot` / `list-snapshots`**:全 vault 一次性快照(`.knowlet/snapshots/<ts>[-label]/`),用于"我准备做高风险操作 / 升级前留个保险"。
- **`knowlet doctor`**:vault 完整性检查。
- **原子写入**(per [ADR-0006 §写入约束 1](./0006-storage-and-sync.md)):`.tmp` + rename,断电不产生半文件。

但**契约还没钉死**。具体的:

- Schema 怎么演进?能不能删字段?重命名怎么办?
- vault 升级时,旧 vault(M0/M3/M7 期写的)在新代码下能不能正常打开?
- "保留 N 次备份"(ADR-0006 §3)从未实现 —— `.knowlet/backups/` 目录至今为空。
- knowlet 自己的版本号(`v0.1.0` 等)和 schema_version 的关系是什么?灰度入口版是哪个?
- Card / Draft / MiningTask 还没有 schema_version 字段。

ADR-0022 §"灰度期入口条件" 直接把 ADR-0018 列为前置 —— 没这份契约,我们没法对自己说"vault 已经稳到可以让外部 alpha 用户进来"。

## 用户故事(三角色)

**小张(power user · 偶尔上游补丁)**
他改了 Note schema 加了一个 `aliases` 字段。他需要在 30 秒内回答两个问题:"我要 bump 版本吗?"、"我要写迁移代码吗?"。如果 ADR 说得清楚("加字段:不用 bump,只要新代码能读旧文件"),他直接动手;说不清楚就拖。规则越清楚,贡献成本越低。

**小红(casual · 半年才升级一次)**
她半年前装的 knowlet 写过 30 篇 Note。今天一升级,打开应用看到的全是 "(missing)" 或 parse error 怎么办?她会立刻关掉,也再也不会信。**1 major backward compat 强制**这条规则是她敢点 update 的隐性合同 —— 即使 ADR 她不会读。

**完全新用户(刚装 latest)**
他从 GitHub 装 latest,vault 全是 latest schema,看不见这层契约。但他半年后会变成"小红" —— 现在写下的契约就是届时的保险。本 ADR 帮他拉回到"敢长期写"的轨道。

三个故事都通,做。

## Decision

### 1. Schema 演进规则

knowlet vault 内每个有 `schema_version` 的实体(Note、QuickActions toml、SQLite tables、未来的 Card/Draft/MiningTask)按以下规则演进:

| 改动 | 是否 bump version | 是否需要迁移代码 |
|---|---|---|
| **加字段(可选,有 default)** | ❌ 不 bump | ❌ 不需要 |
| **加字段(必填)** | ✅ bump | ✅ 需要(为旧记录补 default) |
| **删字段** | ✅ bump | ✅ 需要(显式 drop / 归档) |
| **重命名字段** | ✅ bump | ✅ 需要(treat as remove+add) |
| **改字段语义 / 类型** | ✅ bump | ✅ 需要 |
| **改文件名 / 路径布局** | ✅ bump(全局) | ✅ 需要(物理迁移) |

**1 major backward compat 强制**:写代码到 schema_version = N 时,**必须** 仍能读 N-1。读到 N-1 的实体时:

- 如果是只读路径:就地降级渲染,不写回(避免格式漂移)。
- 如果是写路径:先做 in-memory 升级到 N,然后整体写回(原子)。

迁移函数命名规范:`knowlet/core/migrations/note_v1_to_v2.py`,只允许 read N-1 + write N,不允许跨 N-2 → N。跨多版必须串联多个迁移函数。

**version skip 禁止**:不允许 schema_version 跳号(如 v1 → v3)。每一步必须有迁移函数 + 对应 fixture。

### 2. Schema 覆盖范围

到 ADR-0018 落地时,以下实体**必须**带 schema_version:

| 实体 | 当前状态 | 目标 |
|---|---|---|
| Note(frontmatter `schema_version`) | ✅ v1 | 保持;Slice 4.C 进 v2(加 `status`) |
| QuickActions(toml `schema_version`) | ✅ v1 | 保持 |
| SQLite `index.meta`(table `meta`) | ✅ v1 | 保持 |
| Card | ❌ 没有 | Slice 4.D 加 v1 |
| Draft | ❌ 没有 | Slice 4.D 加 v1 |
| MiningTask | ❌ 没有 | Slice 4.D 加 v1 |
| Conversation(chat history) | ❌ 没有 | Phase 3 加(随 AI 重做) |
| Quiz | ❌ 没有 | Phase 3 加 |

**Slice 4.D 一并 ship 的契约**:任何**新增**的持久化实体类型,**首次**落盘前 schema_version 字段必须就位 —— 把"我先 ship 然后再加 version"这条路堵死。

### 3. Vault fixtures 测试套件

`tests/fixtures/vaults/` 维护若干**冷冻的真实 vault 快照**作为回归测试的 oracle:

```
tests/fixtures/vaults/
├── v1-minimal/         # Note v1, QuickActions v1, no Card/Draft
├── v1-with-trash/      # 含 .trash 的 v1 vault
├── v2-mixed/           # Note v2(status 字段)+ Card v1
└── ...
```

**测试约束**:

- 每个 fixture 配一段 `metadata.json`(写明产出版本、覆盖的特性、预期可读性)。
- 任何 schema_version bump **必须**:
  1. 新增对应 fixture(写入新版本数据)。
  2. 跑 `pytest tests/test_vault_fixtures.py` 验证当前代码能读所有历史 fixture(N-1 backward,older 可被显式弃用)。
  3. 在 events log(ADR-0023 §3)中能 replay 该 fixture(下游 audit 完整)。

**正向 + 反向断言**:fixtures 测试既验证"新代码读旧 vault"(forward compat),也验证"老代码读不了未来 vault 时,优雅 degrade 而非 crash"(graceful)。

### 4. `.knowlet/backups/` 契约

区别于 `.knowlet/snapshots/`(全 vault 用户主动快照),`backups/` 是**自动、入侵性更小、文件粒度**的安全垫,专为"覆盖前我留一手"场景:

```
.knowlet/backups/
├── note/
│   └── 01ABCD1234.2026-05-10T14-23-15.md
├── quick-actions/
│   └── quick-actions.2026-05-10T14-22-00.toml
└── ...
```

**契约**:

- **触发时机**:任何**写覆盖**敏感文件时,先把当前文件以 `.<entity>/<id>.<iso-ts>.<ext>` 拷贝到 backups/。**新建** 不触发(没东西可覆盖)。
- **保留策略**:每实体 `id` 最多保留**最近 5 个**版本,超过 LRU 删除。可被 `knowlet vault config` 调整(后续切片)。
- **覆盖范围**:
  - ✅ Note(每次写入)
  - ✅ QuickActions toml(每次写入)
  - ✅ frontmatter-driven 资产(将来的 Card / Draft 等)
  - ❌ SQLite `index.sqlite`(快照走 snapshot,不在 backups 里)
  - ❌ Trash(已经是软删除,不重复备份)
- **可见性**:UI 不暴露 backups 列表(用户视角看不到);供 `knowlet doctor --restore-from-backup` 等运维工具读。
- **权限**:用户可手动从 backups/ 拷文件出来恢复 —— 是 vault 的一部分,跟随 iCloud / Syncthing 一起同步。

**这不是 SCM**:backups/ 不能替代 git。用户严肃版本管理仍走自己的 git 仓库。backups/ 只兜底"误覆盖"场景。

### 5. 半显式版本号 + 灰度入口版

knowlet 的版本号采用 **SemVer**(`MAJOR.MINOR.PATCH`):

| 版本 | 含义 |
|---|---|
| `v0.x.y` | 内部 alpha;无 backward-compat 承诺;schema 可任意 bump |
| `v1.0.0` | **灰度入口版**(per [ADR-0022](./0022-product-lifecycle-phases.md))。从此 schema_version backward 1 major 强制 |
| `v1.x.y` | 灰度期 / 正式期;按 §1 规则演进 |
| `v2.0.0` | 重大架构变更(罕见);允许放弃 v0.x 全部兼容 |

**关系**:knowlet 版本号和单个实体的 schema_version **不耦合**。一个 v1.4.0 release 可以同时含 Note v3 + Card v1 + Draft v2;一个 v1.5.0 也可以完全不动 schema。每个实体独立演进。

**Pre-1.0 现状**:目前 knowlet 还在 v0.x。本 ADR 就是 **v1.0.0 灰度入口的前置文档** —— 一旦 ADR-0018 完整 ship(本切片 + 4.B-4.E 全部完成),knowlet 才能把版本号 bump 到 v1.0.0。

### 6. 与其他 ADR 的关系

- **[ADR-0006](./0006-storage-and-sync.md)**:本 ADR 把 §写入约束 §3 的 `.knowlet/backups/` 描述具体化为契约(本文档 §4)。
- **[ADR-0023 §3](./0023-llm-wiki-comparison-and-takeaways.md)**(events log):是本 ADR 的 oracle —— schema migration / fixture 测试都在 events log 里能溯源。Slice 4.B 落地。
- **[ADR-0023 §7](./0023-llm-wiki-comparison-and-takeaways.md)**(Note `status`):是本 ADR §1 规则的第一个使用案例(Note v1 → v2,新增可选字段,**不 bump**也行,但因为在 schema 里加了新枚举字段还是 bump)。Slice 4.C 落地。
- **[ADR-0024 §5 B](./0024-ai-assist-envelope.md)**(linter 不改正文):规约了"AI 不能擅自迁移用户内容",和本 ADR §1 "迁移代码只能加字段不能改正文" 同源。
- **[ADR-0022](./0022-product-lifecycle-phases.md)** §灰度期入口条件:本 ADR 是入口前置之一。

### 7. 不做的事(明确划清)

- ❌ **多 major 跨版迁移**:N → N+2 不允许直跨。串两个迁移函数即可。
- ❌ **运行时迁移用户内容**:迁移函数只能补 default / 删字段 / 改结构,**绝不修改用户写入的正文 / title / body**。Linter 报告"待补完"路径用 ADR-0023 §7 status 字段,**不动正文**。
- ❌ **schema_version 字段串(`"v1.2"`)**:用整数,简单稳定。
- ❌ **同步 / 远端 vault 兼容**:本 ADR 只覆盖 local-first 单 vault,跨设备同步是 ADR-0006 §同步策略 的责任(目前 = 用户自行选择 iCloud / Syncthing)。
- ❌ **加密 vault**:不在本 ADR 范围;独立 ADR(如有需要)。

## Consequences

**Positive**

- v1.0.0 灰度期入口契约钉死。外部 alpha 用户进来时我们能拍胸脯:1 major backward compat、原子写、自动 backups、全 vault snapshot、event log 可溯。
- Schema 演进决策从"靠记忆 / 当下灵感"变成 30 秒查表(§1)。降低未来贡献门槛(自己 / 别人 / agent)。
- Fixtures 测试给后续每次 schema 改动加上自动化护栏。漏改一个 backward read path → CI 红。
- backups/ 终于落地,covering 单个文件粒度的"误覆盖"。

**Negative / Risks**

- Fixtures 维护成本:每次 schema bump 要新增一个 fixture vault;fixture 多了体积可观(虽然每个 vault 几 KB)。**对策**:fixture 命名 + metadata 必须覆盖"为啥存在 / 测哪条",老 fixture 可被显式 deprecate。
- backups/ 占空间:5 份 × N 个文件 × 平均文件大小。N=1000 个 Note 时大致几十 MB。**对策**:只覆盖"被覆写"的文件、保留 5 份上限、用户可改、可显式清空(`knowlet vault prune-backups`,后续切片)。
- 半显式 versioning 的歧义:用户可能误以为"我装了 v1.2 → 我所有 Note 都是 Note v1.2"。文档要把"knowlet release version" vs "实体 schema_version" 解释清楚(README + 本 ADR 已写;UI 也可在 Settings → About 区分展示)。

## Alternatives considered

- **方案 A:不写 ADR,凭 commit-message 约定演进 schema**
  这是 v0.x 时期的现状。问题:贡献者(包括 agent)需要在每次 schema 改动时自己 reverse-engineer 历史 commit 才能判断"我能不能加这个字段"。Phase 2 收尾时已经感受到摩擦。被否。

- **方案 B:每次 schema 变化全 vault auto-migrate(强制写回)**
  类似 Postgres `ALTER TABLE`。问题:违反"用户拥有"——用户的 Note 文件被自动改写一遍(即使语义不变),iCloud sync 全文件 churn,git diff 噪音爆炸。被否。

- **方案 C:把 schema_version 编进文件名(如 `note.v1.<id>.md`)**
  让降级路径"显式可见"。问题:用户视角文件名变奇怪;移到外部编辑器(VS Code / Obsidian)又得脱掉。frontmatter 字段足以承担同样信息,不暴露给用户。被否。

- **方案 D:跳过 backups/,只靠 snapshot**
  `vault snapshot` 已经能全量备份,够不够?不够 —— snapshot 是用户主动行为,平均触发一次 / 周;backups 是**写覆盖前自动触发**,粒度细十倍。一个保大,一个保小,互补。被否(同时保留)。

## 实施清单

本 ADR 落地不是单一切片:

- **Slice 4.A**(本切片):本 ADR 文档。
- **Slice 4.B**:SQLite events log + `log.md` 渲染(ADR-0023 §3)。
- **Slice 4.C**:Note `status` v2(ADR-0023 §7,本 ADR §1 第一个 case)。
- **Slice 4.D**:Card / Draft / MiningTask 加 schema_version v1。
- **Slice 4.E**:`.knowlet/backups/` 契约实现(写覆盖前自动备份 + LRU 5)。
- **Slice 4.F**(可选):`tests/fixtures/vaults/` 初始 fixture + `test_vault_fixtures.py`。
- **Slice 4.G**(灰度准备):knowlet 版本号 bump 到 `v1.0.0-rc.1`,README 写明灰度入口要求。
