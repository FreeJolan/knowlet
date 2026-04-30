# 0007 — MVP 切片范围与技术栈

> [English](./0007-mvp-slice.en.md) | **中文**

- Status: Accepted
- Date: 2026-04-30

## Context

[ADR-0003](./0003-wedge-pivot-ai-memory-layer.md) 至 [ADR-0006](./0006-storage-and-sync.md) 完成了产品定位、架构哲学、LLM 接入、存储与同步的决策。后续主要的"未发现的未知"必须通过真实使用暴露,继续白纸讨论的边际收益已显著下降。

为兑现 ADR-0003 中"先自用后开源"调性的最直接方式,是尽快建立一个最小的端到端可用版本(MVP),用真实使用反馈驱动后续迭代。

但"阶段一全部上"的范围太大,会让首次实现拖延数月。本 ADR 决定 MVP 切片的最小范围与技术栈,作为开始写代码的依据。

## Decision

### MVP 范围

只做以下能力的端到端贯通:

| 维度 | MVP 包含 | MVP 不做 |
|---|---|---|
| **场景** | 场景 A:研究 / 论文阅读 | 场景 B 挖掘任务 / 场景 C SRS |
| **领域实体** | Note(Markdown + Frontmatter) | Card / Mistake / Source |
| **核心循环** | 嵌入式 chat → LLM-driven retrieval → AI 草稿 → 用户审查 → Note 入库 | 知识挖掘任务、SRS 复习、错题反哺 |
| **平台** | 桌面端 | 移动 PWA / 原生移动 |
| **接入形态** | CLI(后端 daemon 化设计,后续接 UI 复用) | Tauri 桌面壳、可视化 settings |
| **配置** | TOML 配置文件 | 可视化 LLM 配置 UI |
| **同步** | 用户已经把 vault 放进 iCloud / Syncthing 等;knowlet 只读取本地目录 | knowlet 内置同步 |

### 技术栈最终选型

- **语言**:Python 3.11+
- **架构形态**:本地后台服务(MVP 阶段以 CLI 为入口;后端按 daemon 模式设计,为后续 UI 复用)
- **核心库与判断**:见 [`../design/mvp-slice.md`](../design/mvp-slice.md)
- **不使用**:LangChain / LlamaIndex 这类架构层框架(理由:跟 [ADR-0004](./0004-ai-compose-code-execute.md) "原子能力 + LLM 编排"哲学冲突;API 不稳定;传递依赖膨胀)

选 Python 而非 Go 的核心理由:**knowlet 的工作负载是 IO + 底层库调用密集型**(LLM API、SQLite、embedding 模型、Markdown 解析),Python 在这类场景跟 Go 性能差异 < 1%。Python 在 LLM SDK / embedding / sqlite-vec / Markdown 等关键依赖上的生态成熟度显著领先,更契合"不造轮子"原则(见 [feedback_no_wheel_reinvention](../../)).

Python 启动慢(`import torch` 等几秒)的问题,通过**daemon 常驻**消化(MVP 阶段 CLI 接受单次启动开销,后续 UI 形态由 daemon 持续服务)。

### 验证标准(MVP 跑通的判定)

可量化的行为标准:

1. 通过 CLI 启动一次 chat session 不报错
2. chat 中 LLM 自动调用本地知识库检索 tool(可在日志看到 tool call)
3. 触发"沉淀本次对话"后,LLM 写出一份 Note 草稿,用户审查后落入 vault
4. 退出后再次启动新 session,LLM 能从之前沉淀的 Note 中召回相关内容

主观但关键的标准:

5. **自己用着不烦躁**(交互节奏、错误反馈、提示密度都在可接受范围)

四条客观标准 + 第五条主观标准全部满足 → MVP 跑通,可以进入下一阶段(逐步加场景 B / C / 移动端等)。

## Consequences

### 好处

- **快速进入真实使用**:估计 1-2 周可以跑通最小版本(零到一)
- **范围聚焦,实现风险可控**:不试图一次解决阶段一全部问题
- **真实反馈替代抽象讨论**:产品设计的盲点必须靠用上才能发现
- **Python 选择基于"不造轮子"原则**:LLM SDK / embedding / sqlite-vec / Markdown 等关键依赖在 Python 生态最成熟,实现成本最低

### 代价 / 约束

- **MVP 不能完整体现 ADR-0003 的破局点叙事**(尤其场景 B 挖掘任务、场景 C 学习增强);需诚实标记 MVP 之上的能力是后续迭代逐步加上的
- **Python 启动慢**(import 阶段 1-3 秒);CLI 形态接受,后续 daemon 化解决
- **CLI 没有视觉吸引力**:首次自用阶段 OK,开放外部用户前需补 UI(Tauri 或 web)
- **MVP 的临时实现可能被全量重写**:scratch-your-own-itch 模式接受这个代价
- **Python 单二进制分发的劣势**(PyInstaller / Nuitka 包大):MVP 自用阶段不重要,开放分发时再处理

### 与现有 ADR 的关系

完全从属于 [ADR-0002](./0002-core-principles.md) / [ADR-0003](./0003-wedge-pivot-ai-memory-layer.md) / [ADR-0004](./0004-ai-compose-code-execute.md) / [ADR-0005](./0005-llm-integration-strategy.md) / [ADR-0006](./0006-storage-and-sync.md);本 ADR 是这些原则在 MVP 阶段的工程展开。

未来某个时点本 ADR 会被新 ADR 取代(随着 MVP 扩展到完整阶段一,范围会变化,届时新写一份描述新切片)。
