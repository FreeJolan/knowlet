# 0006 — 数据存储与同步策略

> [English](./0006-storage-and-sync.en.md) | **中文**

- Status: Accepted
- Date: 2026-04-30

## Context

[ADR-0002](./0002-core-principles.md) 与 [ADR-0003](./0003-wedge-pivot-ai-memory-layer.md) 在原则层面承诺:

- 数据主权:用户随时可以打包带走全部数据
- 本地优先:无网仍可用
- 派生数据可重建,不与 ground truth 混淆
- 隐私边界明确

这些承诺需要落到具体的目录布局、文件格式、同步管道、隐私分级。本 ADR 把这些细节统一定下。

## Decision

### 三层存储模型

```
<vault>/                          ← 用户选定的目录
├── notes/                        Markdown 文档(用户笔记)
├── cards/                        JSON 记录(SRS 卡片)
├── mistakes/                     JSON 记录(错题)
├── sources/                      JSON 记录(信息源元数据)
├── users/
│   └── me.md                     Markdown 用户意图(目标 / 偏好 / 风格)
└── .knowlet/                     派生数据与私有缓存(默认不同步)
    ├── index.sqlite              SRS 调度 + 全文索引
    ├── vectors.sqlite            向量索引
    ├── profile/                  AI 派生分析(JSON)
    ├── conversations/            对话 raw payload(30 天保留)
    ├── quizzes/                  Quiz session 持久化(M7.4 / ADR-0014;90 天老化,有 Card 回流的留长)
    └── backups/                  关键 state 文件备份
```

| 层 | 内容 | 是否同步 | 是否可丢失 |
|---|---|---|---|
| **Vault 实体** | notes / cards / mistakes / sources / users | ✅ | ❌ ground truth |
| **AI 派生分析** | `.knowlet/profile/*.json`(错误模式统计、掌握度向量、学习行为画像) | ❌ | ✅ 可从 Vault 重建 |
| **系统索引** | `.knowlet/index.sqlite` / `vectors.sqlite` | ❌ | ✅ 可从 Vault 重建 |
| **对话缓存** | `.knowlet/conversations/` | ❌(永不同步) | ✅ 30 天自动过期 |
| **Quiz 历史** | `.knowlet/quizzes/<id>.json`(M7.4 / ADR-0014) | ❌ | ⚠️ 90 天后自动归档到 `.knowlet/quizzes/.archive/`;有 Card 回流的留长 |

判断规则:**"丢了这份数据是否丢了用户给我们的真实信息"** —— 是 → Vault 实体(必须同步);否(可从其他数据重建)→ `.knowlet/`(默认不同步)。

### 实体存储格式:按本质决定

| 实体 | 格式 | 文件名 | 主要编辑者 |
|---|---|---|---|
| Note | Markdown + YAML frontmatter | `notes/<id>-<slug>.md` | 用户(UI + 偶尔外部编辑器) |
| Card | JSON | `cards/<id>.json` | UI(用户极少打开原始文件) |
| Mistake | JSON | `mistakes/<id>.json` | 机器(用户不直接编辑) |
| Source | JSON | `sources/<id>.json` | 机器为主(用户偶尔编辑描述) |
| User profile | Markdown + YAML frontmatter | `users/me.md` | 用户(自由编辑) |

判断规则:**文档**(用户主导编辑、可能在外部编辑器查看)→ Markdown;**记录**(机器/UI 主导编辑、UI 是常态)→ JSON。

Card 的 `front` / `back` 等内容字段**允许 Markdown 字符串**,UI 按 Markdown 渲染。

ID 使用 [ULID](https://github.com/ulid/spec):26 字符,字典序即时间序,跨设备无冲突。

### 写入约束

适用于所有 vault 文件:

1. **原子写入**:写文件时先写到 `.tmp` 再 `rename`,防止断电 / 崩溃产生半文件
2. **严格 schema 校验 + 优雅回退**:parse 失败 → UI 显示"修复这个文件";字段缺失 / 类型错 → 用 default 补 + 记 warning
3. **关键 state 文件备份**:写到 `.knowlet/backups/<entity>/<id>.<ts>.json`,保留近 N 次,用户/工具可恢复
4. **UI 删除实体时清理对应文件**(避免孤儿文件)

### 同步策略

阶段一:**knowlet 不内置同步逻辑**。Vault 是普通文件夹,用户自行决定同步管道:

- iCloud Drive
- OneDrive / Dropbox / Google Drive
- Syncthing(开源,推荐)
- 其他任何文件级同步服务

knowlet 只做:

- 文件 IO + file watcher 监听外部变化 → 自动 reload
- 检测到冲突文件(如 `xxx (conflict).md`)时在 UI 提示用户处理

附带含义:**knowlet 不需要账户系统**。Vault = 一个目录,谁打开谁就是用户。这与 [ADR-0002](./0002-core-principles.md) 数据主权进一步对齐 —— 数据连"上传到 knowlet"这一步都没有。

阶段二 / 后续:knowlet 自建轻量同步服务(可能基于 CRDT 或加密同步)作为高级选项,与文件级同步共存。届时由新 ADR 决策。

### 重建机制

新设备从同步管道拉到 vault 后,首次启动:

```
1. 扫 notes/*.md
   切块 + 调用 embedding model
   → .knowlet/vectors.sqlite

2. 扫 cards/*.json
   读 srs 字段
   → .knowlet/index.sqlite(SRS 调度表)

3. 扫 mistakes/*.json
   聚合按 error_type / pattern
   → .knowlet/profile/<domain>_analytics.json

4. 扫 cards 的 review_history
   计算掌握度向量
   → .knowlet/profile/<domain>_analytics.json
```

时间预估(粗略,真实数字依实现):

- 几百 Notes / Cards → < 10 秒
- 几千 → 30 秒~1 分钟
- 几万 → 几分钟

UI 立即可用,向量索引在后台填充,期间 RAG 命中率渐进上升。

**Ground truth 永远是 Vault 实体,删 `.knowlet/` 只是触发重建,数据不会丢。**

### 加密策略

阶段一**默认不加密**,**提供加密为可选高级选项**(具体技术 git-crypt / age / 自研由后续 ADR 决定)。

理由:

- 大多数目标用户(程序员 / 知识工作者)选 iCloud / GitHub 私有仓 / Dropbox 时已做"信任决定"
- 高隐私需求用户(医疗 / 法律工作者)可一键开启加密
- 阶段一不实现加密路径,推到有真实需求时做

### 隐私边界声明(配合 [ADR-0005](./0005-llm-integration-strategy.md))

knowlet 文档需明确告知用户:

- **LLM provider 看得到用户的对话 + RAG 命中的 Note 片段**。这是直接连接,knowlet 不代理也不过滤。隐私由用户的 LLM 选择决定。想完全私密 → 用本地 Ollama;想联网但低风险 → 选 zero-retention API tier。
- **阶段一用 LLM provider 自带 web_search**:抓取由 provider 后端做,**用户 IP 不暴露给被抓站**。
- **阶段二启用 fallback 抓取后端**(若实现):从用户本机发起请求,**用户 IP 会暴露给被抓站**(与用浏览器访问相同)。UI 在启用时显式提示。
- **对话 raw payload 仅本地缓存,30 天后自动清理,永不同步**。

## Consequences

### 好处

- **用户随时可打包带走全部数据**:整个 vault 复制走即可,所有内容都是开放格式(Markdown / JSON)
- **knowlet 不参与同步 → 工程量低 + 跨平台天然**:macOS / Linux / Windows / 移动 PWA 共用同一套文件 IO
- **不需要账户系统**:简化产品边界,与终生不做多用户(ADR-0003)一致
- **Ground truth 概念简洁清晰**:Vault 实体是真相,`.knowlet/` 是缓存
- **重建机制保证派生数据丢失不致命**:用户清 `.knowlet/` 没顾虑

### 代价 / 约束

- **同步质量依赖用户选定的服务**:冲突处理、可靠性、跨平台一致性都不在 knowlet 控制之内
- **大型 vault 首次启动有可见延迟**:重建索引 / 向量需要时间(可接受,有进度提示)
- **JSON 实体不能用富文本编辑器编辑**:cards / mistakes / sources 的原文件查看体验不如 Markdown,但目标用户主要通过 UI 交互,可接受
- **加密路径推迟**:高隐私需求用户阶段一无完整解,只能靠选 zero-retention LLM + 私密同步管道
- **LLM provider 数据可见这一点不能由 knowlet 解决**:只能在文档中告知,由用户在选 LLM 时决策

### 后续扩展点(不在本 ADR 承诺时间表)

- knowlet 自建同步服务(CRDT 或加密同步)
- 完整加密路径(git-crypt / age 等)
- LLM provider 限制下的额外私密抓取后端

这些扩展由实际需求驱动,届时由新 ADR 决策。
