# 0027 — 多设备同步:Google Drive API as remote authority

> **中文**(English to follow if needed)

- Status: Accepted (设计 — 实现待 phase)
- Date: 2026-05-10

## Context

knowlet 的 [ADR-0013](./0013-knowledge-management-contract.md) 承诺"用户拥有 vault";[ADR-0006](./0006-storage-and-sync.md) 把多设备同步的责任**外包给用户自己选的工具**(iCloud / Syncthing / Dropbox)。这条路径有效解决了"知识库归用户",但留下了一个真实的冲突路径:

> 多台设备各自编辑 → 文件级同步工具按字节合并 → 用户在两份冲突文件之间手动 merge。

这个失败模式在 knowlet 的小用户量下不致命,但有几个问题:

- **Google Drive 客户端**(macOS / Windows 桌面端)可能**静默胜出**一份(不像 Dropbox / Syncthing 始终保留 `.sync-conflict-*`)。这对 knowlet 是不可接受的失败模式。
- 用户的真实场景多半是**顺序切换设备**(下班 → 关电脑 → 回家开另一台),而不是并发编辑。但**两台设备各自编辑了一会儿**(早上电脑 A,下午电脑 B,iCloud 还没全 sync)→ 切回 A 时仍可能踩到合并冲突。
- 离线场景更糟:在没网的电脑 B 编辑半小时,联网后才被告知"远端有新版本" —— 用户对此**毫不知情**就被埋伏了。

2026-05-10 用户 + agent 讨论后,共识是:

1. 文件级同步工具的"等权威 + auto-merge"模型不接受。
2. 项目方**不**跑 server 持用户数据(信任成本太重,时机不对)。
3. 用 Google Drive **API**(不是客户端)做"远端权威"模型 —— Google 替我们做 server,knowlet 只是 OAuth client。

详细共识见项目 memory `feedback_sync_remote_authoritative.md`,本 ADR 把它正式化。

## 用户故事(三角色 + 失败路径)

正常路径(必须为它们最优化):

**电脑 A → 电脑 B 下班切换**:在 A 上写笔记 → 关电脑 → 到家开 B → **看到 A 的最新成果**。
**电脑 A → 电脑 B 继续编辑**:同上,但在 B 上**接着**写,A 那边的状态自然存到了远端。

糟糕路径(必须排除):

**编辑后才发现冲突**:在 B 上编辑了 5 分钟,knowlet 才提示"远端有冲突"。
**离线沉默**:B 离线时编辑,联网后突然提示一堆冲突,用户毫不知情。
**Drive 客户端静默覆盖**:文件级同步把一台的修改静悄悄丢了。

三角色:
- **小张(power user, 多设备重度)**:每天笔记本 + 桌面机切换 5+ 次。期望切换无感、零冲突。愿意承担"打开笔记延迟 1 秒"换"绝不冲突"。
- **小红(casual, 一台主力 + Drive 备份)**:99% 时间在一台设备上,Drive 是备份网。期望本地秒开,不希望被 sync 状态机打扰。
- **完全新用户**:刚装 knowlet。可能根本不连 sync。期望默认 = 单设备本地 first;真要多设备时一键打开。

## Decision

### 1. 整体形态:opt-in,Google Drive API,远端权威

- **默认状态**:不开 sync。knowlet 本地优先(沿用 ADR-0006 现状)。
- **Opt-in**:Settings → Sync → Connect Google Drive。OAuth scope 限制为应用专属文件夹(`drive.appdata` 或 `drive.file` 限定文件)。
- **激活后**:knowlet 通过 Drive API 读写 vault 资源。本地依然有完整文件副本(offline-first),但 Drive 是 canonical 真理。
- **不路过 Drive 客户端**:不依赖、不期待用户启用 Drive 客户端。Drive 客户端如果开了也无所谓 —— 我们走 API 路径,自带 ETag 防冲突。

### 2. 核心机制:ETag-based OCC

每篇笔记 / 每个 quick-actions.toml 在 Drive 上对应一个 file resource,有 ETag(每次内容变化 ETag 变)。knowlet 本地维护一个 `sync_state.sqlite`(在 `.knowlet/sync_state.sqlite`),记录:

| 列 | 说明 |
|---|---|
| `entity_type` | "note" / "quick-actions" / future |
| `entity_id` | Note ULID 等 |
| `drive_file_id` | Drive 上对应资源 id |
| `last_known_etag` | 上次看到的 Drive ETag |
| `last_synced_at` | 上次成功同步时间(本机时钟,仅日志用) |
| `dirty` | 0/1 — 本地有未同步修改 |

写流程:

```
本地写笔记
  ↓
落本地 (atomic .tmp + rename, Vault.write_note 现有路径)
  ↓
backups/ 写覆盖前快照 (Slice 4.E,已 ship)
  ↓
audit log emit (Slice 4.B,已 ship)
  ↓
mark dirty=1 in sync_state
  ↓
sync agent (异步) 调 Drive API PUT (If-Match: <last_known_etag>)
  ↓
  ├─ 200 OK → 更新 last_known_etag, dirty=0
  └─ 412 Precondition Failed → 拉远端版本 → 弹冲突 UI
```

读流程:

```
打开应用 / 打开笔记
  ↓
调 Drive Changes API (GET /changes since <start_page_token>)
  ↓
  ├─ 远端有变化 + 本地 dirty=0 → 拉新版覆盖本地缓存,更新 ETag
  ├─ 远端有变化 + 本地 dirty=1 → 冲突 UI(双版本并存,用户挑)
  └─ 远端无变化 → 用本地缓存
```

### 3. UX 不变式(从用户故事推导)

- **保存即同步**:Save 必须等 Drive ACK 才算 done。不接受"乐观本地 + 后台 push"。
- **打开即拉最新**:打开应用 / 笔记 → 先 fetch Drive ETag → 完成后才允许编辑(默认 Strict / Auto-多设备)。
- **编辑期持续 poll**:每 15-30s 调 Changes API。远端有变 → **立即** banner 通知,不等 Save 时才告知。
- **关闭前必须同步完**:有 pending save → 关闭时强 modal "X 篇未同步,等完成或选离线保留"。
- **状态永久可见**:header 顶部 always-on 指示器:`synced 5s ago` / `syncing...` / `offline · N pending` / `error · retry`。
- **离线 / Drive 不可达**:
  - 多设备模式 + 冷启动离线 → 强 modal "你离线,且其它设备可能改过笔记。继续编辑可能产生冲突。"
  - 单设备模式 + 离线 → 静默(无冲突可能)。
  - 编辑期断线 → 状态指示器变 "offline · N pending",first poll 失败时 banner 一次。
  - Token 失效 → 红条 "Drive disconnected — reconnect"。

### 4. 三档 fetch 策略 + 智能默认

| 选项 | 行为 | 适用 |
|---|---|---|
| **Auto**(默认) | Drive 上 sync_state 里近 30 天有其它 device_id → 走 Strict;否则走 Lax | 不用想,跟着实际用法走 |
| **Strict** | 永远 block-on-open(打开前 fetch ETag,200-500ms 阻塞) | 多设备重度用户 |
| **Lax** | 永远 lazy(秒开 + 后台对账,远端有变就 banner) | 单设备 / Drive 纯备份 |

Auto 实现:每个 device 有唯一 `device_id`(本地生成 ULID,持久化在 `sync_state.sqlite`)。每次同步时把"我看到的活跃 device_id 列表 + 最后心跳"上报到 Drive 的 `sync_state` 索引。打开应用时读这个索引,30 天内见过 ≥2 个 device → Strict;否则 Lax。

### 5. 冲突处理

冲突 = "远端 ETag 变了 + 本地 dirty=1"。两种触发点:

- **Save 时 412**:用户点保存(或 autosave 触发),Drive 拒绝。
- **Poll 时检测**:用户编辑期间,后台 poll 发现远端变了 + 本地有未保存改动。

两种触发点 UX 一致:

```
┌─────────────────────────────────────────┐
│ 这篇笔记被另一台设备改了                  │
├─────────────────────────────────────────┤
│ 你的版本:                                │
│ ┌───────────────────────────────────┐    │
│ │ <你的本地内容预览>                  │    │
│ └───────────────────────────────────┘    │
│                                         │
│ 远端版本(2026-05-10 14:23 from MacBook):│
│ ┌───────────────────────────────────┐    │
│ │ <Drive 拉下的内容预览>              │    │
│ └───────────────────────────────────┘    │
│                                         │
│ [用我的 → 覆盖远端]  [用远端 → 丢我的]    │
│ [并存(都保留 → 拆两篇笔记)]              │
└─────────────────────────────────────────┘
```

**绝不静默选一份**。"并存"创建一篇副本笔记(标题加 ` (conflict from <device>)` 后缀),让用户后续慢慢合并。

### 6. 与既有 ADR / 基础设施的关系

- **[ADR-0006](./0006-storage-and-sync.md)**(数据存储与同步)— 本 ADR 不替代 0006,而是**增加一个 opt-in 的 sync 层**。0006 的"vault = 普通文件夹 + 用户自选同步工具"路径仍然是默认。
- **[ADR-0013](./0013-knowledge-management-contract.md)**(用户拥有)— 本 ADR 不违背:数据仍然在用户自己的 Drive 账号里,knowlet 不持任何用户数据。OAuth 撤销 → knowlet 立刻失去访问。
- **[ADR-0018](./0018-data-durability.md)** §4(backups)— `.knowlet/backups/` LRU 5 是本地兜底。即使 Drive sync 出问题(token 失效、API 限流、奇怪的客户端 bug),用户在本机仍有 5 份历史可恢复。
- **[ADR-0023 §3](./0023-llm-wiki-comparison-and-takeaways.md)**(events log)— `vault.events` 已经记录每次 note.created/updated/deleted。Sync 推 events 到 Drive 上的 `events.sqlite` mirror,作为多设备活动 oracle(也是 device_id 心跳的载体)。
- **[ADR-0022](./0022-product-lifecycle-phases.md)**(灰度入口)— ADR-0027 实现是灰度入口的**充分**条件之一(没它,多设备用户没法可靠用 knowlet)。但 v1.0.0-rc.1 不一定要等 0027 落地 —— 单设备用户可以先用上,sync 作为 v1.x post-rc 增量。

### 7. 不做的事(明确划清)

- ❌ **CRDT / Yjs 类异步合并**:用户已经否决(memory:Yjs 经验丢过数据)。
- ❌ **项目方维护 server 持用户数据**:用户已否决(信任成本)。
- ❌ **多 cloud 同时支持**:Slice 1 只支持 Google Drive。OneDrive / Dropbox 走类似 API,可后续做适配器(Drive API client 抽象成接口,implementation 替换)。但**Slice 1 不为它们设计**。
- ❌ **协同实时编辑**:knowlet 的笔记是个人工具,不是 Notion 团队空间。多用户 / 多 cursor 不在范围。
- ❌ **加密**:Drive 上的文件按 Google 默认 at-rest 加密;knowlet 不再加一层用户密钥。需求出现时另起 ADR。
- ❌ **byte-level 直接走 Drive 客户端**:per memory `feedback_sync_remote_authoritative`,Drive 客户端可能静默胜出,绝不接受。

### 8. 实施 phase(由你 sequence)

本 ADR 不立即实现。落地分多个 slice:

- **Slice 5.A**:OAuth 流程 + token 持久化 + Drive API client 模块(无 sync 行为,只验证连得通)。
- **Slice 5.B**:`sync_state.sqlite` schema + `device_id` + 启动期 Changes API 一次性拉取(read-only)。
- **Slice 5.C**:写路径 PUT-with-ETag + 412 冲突 UI(无 poll,只手动 save 时检测)。
- **Slice 5.D**:编辑期 poll Changes API + 远端变化 banner 通知。
- **Slice 5.E**:三档 Auto/Strict/Lax 设置 + 设备数自检测。
- **Slice 5.F**:离线 / token 失效全套 UX(冷启动 modal、状态指示器、关闭前阻拦)。
- **Slice 5.G**:CLI 平价(`knowlet sync status` / `knowlet sync force` / `knowlet sync conflicts`)。

每 slice 独立可 ship,失败/回滚的影响面被局限在该 slice 范围内。Slice 顺序遵循"读路径先于写路径,简单触发先于复杂触发"的安全梯度。

## Consequences

**Positive**

- 解决"我下班切设备看不到上午笔记"的核心痛点。
- ETag OCC 排除 byte-level sync 的静默丢失风险。
- 项目方零 ops:Google 替我们做 server,knowlet 只是 client。
- 用户**自己**拥有数据(在自己的 Drive 账号里),OAuth 可撤销 → 数据隔离权 100% 在用户。
- 复用已 ship 的基础设施:audit log(ADR-0023 §3)、backups(ADR-0018 §4)、schema_version(ADR-0018 §1)。
- Drive 自带版本历史(30 天)是第三层兜底。

**Negative / Risks**

- **Google 锁定**:第一波只支持 Google Drive。其它云的用户暂时只能走 ADR-0006 文件级同步。可接受 —— OneDrive / Dropbox 等都有类似 API,适配器模式留位。
- **API 限流**:Drive API 有 quota(默认每用户每 100s 1000 query)。重度用户多设备并发 + 高频 poll 可能撞上。设计 mitigation:poll 间隔自适应(空闲时 30s,活跃时 15s)、batch list-changes、HTTP 304 缓存。
- **OAuth 复杂度**:需要 Google Cloud project、API enable、OAuth consent screen 流程。对开发期 ok;灰度期需文档化。
- **网络依赖增强**:opt-in sync 后,所有 save 路径都依赖网络。autosave-error 路径(2026-05-10 fix `dc9f07b`)已经覆盖了基本"知情",但 sync 状态下需要额外的"等同步完成才能关闭"逻辑。
- **device_id 隐私**:sync_state 上传到用户自己的 Drive,只暴露给用户自己。但需在隐私文档里说明。

## Alternatives considered

- **方案 A:延续 ADR-0006(用户自己选同步工具)**
  当前路径。问题:Google Drive 客户端可能静默丢、用户 friction 高(要自己装 Syncthing 等)。**保留作为默认**,但不解决多设备核心痛点。
- **方案 B:项目方跑 server**
  最干净的远端权威。问题:用户已否决(信任成本太重,时机不对)。
- **方案 C:基于 events log 的 P2P 同步(无中心)**
  events 流推到一个 IPFS / 自托管 hub。问题:基础设施太重、IPFS 性能未经验证、自托管对普通用户太难。
- **方案 D:CRDT(Yjs)**
  用户已经在 TODO 软件里踩过坑(memory)。
- **方案 E:WebDAV 通用接入**
  支持所有 WebDAV-兼容服务(Nextcloud / OwnCloud)。问题:WebDAV 的 ETag 实现各家不一致,OCC 不可靠。可作为后续 nice-to-have,不是 Slice 1。

**最终选择 = Drive API 专用,因为它是 ETag OCC 最稳的免费路径,且 Google 用户基数最大。**

## 实施位置(待 Slice 5 起步时填充)

- `knowlet/core/sync/` 新模块树(client + state + conflict + UI 状态机)
- `knowlet/cli/sync.py` 平价 CLI
- `frontend/src/components/SyncStatus/`(header 状态指示器 + 冲突 modal)
- `frontend/src/api/sync.ts` (前端调 sync 控制 API)
- `docs/decisions/0027-sync-via-drive-api.md` ← 本文档
- 配置项加进 `KnowletConfig.sync.*`
