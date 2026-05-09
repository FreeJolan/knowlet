# 0026 — Command palette: 一个对话框 × 两个前缀模式 (VS Code 风)

> **中文**(English to follow if needed)

- Status: Accepted
- Date: 2026-05-10

## Context

Phase 2 D Slice 2c.2 落地后,knowlet 已有四个独立"动作发起入口":

1. ⌘P — quick switcher(文件检索)
2. ⌘⇧A / ⚡ icon — quick actions manager(列表 + CRUD)
3. ⌘1/⌘2/⌘3 — 左栏 activity bar tab 切换
4. ⌘⇧G / ⌘⇧F / ⌘⇧D — 单点散热键(graph 聚焦 / 全局搜索 / 今日笔记)

入口越多 → 用户越难记。Quick actions 已经统一了"空间型用户操作"的执行层(ADR-0025),但**发现层**仍然分裂 —— 用户必须先知道"⚡ icon 在哪"或"⌘⇧A 这个键存在",才能用上。

VS Code 解过同一道题:

- `Cmd+P` = quick open(文件)
- `Cmd+Shift+P` = command palette(所有命令,文本检索)
- 同一个对话框,前缀字符 `>` 切换模式

我们的 ⌘P palette 已经是这个对话框的雏形,只差"command 模式"分支。

(参见 memory: `feedback_vscode_as_north_star.md` —— 借鉴 VS Code 模式时必须重新跑 knowlet 自己的用户故事。)

## 用户故事(三角色)

**小张(power user · 重度日记 + 开发笔记习惯)**
他每天开 knowlet 第一件事是 ⌘P 找文件。新工作流:他可以直接 ⌘⇧P 搜「toggle theme」「new note」「show graph」,不再需要记 ⌘⇧G/⌘⇧F/⌘⇧A 一堆散热键。习惯使用三个月后,他对**所有键盘快捷键的依赖度反而降低** —— 因为命令面板让"我要做 X" 变成纯文本检索。

**小红(casual · 偶尔写点东西)**
她从来不开 ⚡ manager。但今天她按 ⌘P 想找一篇笔记,误打了 `>` 字符,意外看到「今日笔记」「切到:模板」「打开设置…」一排命令 —— 这就是 discovery 表面。她发现"哦原来还能这样",日后逐渐用上更多功能。Palette 顺便成了**功能广告位**。

**完全新用户(刚装好 knowlet,vault 空)**
第一次按 ⌘⇧P,看到唯一一条预设 quick action「今日笔记」+ 一组内置命令(切换主题 / 打开设置 / 切换标签 tab / ...)。他不需要看文档,palette 就是 onboarding tour 的入口。

三个故事都通,做。

## Decision

### 一对话框,两模式

```
+---------------------------------------+
| [▶ COMMANDS  (⌫ 退出)]                |  ← 仅 commands 模式可见
| 🔍 Type a command…                    |
|---------------------------------------|
| ⚡ 今日笔记            ⌘⇧D            |
| ▶ Toggle theme        currently light |
| ▶ Show: Notes          ⌘1             |
| ...                                   |
|---------------------------------------|
| ⌫ 返回文件搜索 · Esc 关闭              |
+---------------------------------------+
```

- **files 模式(默认 / ⌘P)**:仅列文件。命令不混入,保持 quick switch 的极简体验。
- **commands 模式(⌘⇧P)**:列出所有 quick actions(⚡ icon)+ 所有内置 UI commands(▶ icon)。两者通过 cmdk 的 fuzzy filter 统一搜索,跨语言(name + description + keywords + 拼音/英文别名)。

### 模式切换路径

| From → To              | 触发                                  |
|------------------------|---------------------------------------|
| files → commands       | 输入 `>` (consume 该字符,清空 query) |
| files → commands       | ⌘⇧P (整体重开 + 切模式)              |
| commands → files       | 空 input 时按 Backspace               |
| commands → files       | 点击 commands 模式顶部的「▶ COMMANDS」pill |
| Esc                    | 关闭对话框(任意模式)                 |

VS Code 的 `>` 前缀语义在我们这里 1:1 复刻。

### 命令注册表(client-side)

`frontend/src/components/Palette/commands.ts` 导出 `buildBuiltinCommands(args)`,返回 `PaletteCommand[]`:

```ts
interface PaletteCommand {
  id: string;
  name: string;
  description?: string;
  shortcut?: string;
  keywords?: string[];      // 跨语言 alias,例如 ["theme", "dark", "主题"]
  run: () => void | Promise<void>;
}
```

AppShell 在 render 阶段构建命令(closure 拿到 setLeftTab / setQuickActionsOpen / openNewDocDialog 等),作为 `builtinCommands` prop 传给 palette。

Quick actions 不重复声明 —— palette 通过 `/api/quick-actions` 获取,在 commands 模式下 mapping 成 `PaletteCommand` 形状(`run = runQuickAction(id)`),与内置命令并列展示。区分仅在图标(⚡ vs ▶)。

### 为什么 client-side 命令注册,而不是 backend?

- 内置命令 ≠ 业务逻辑:它们是 **UI 状态切换**(打开 dialog / 切 tab / 切主题)。后端无概念。
- Quick actions / workflows 仍走后端(ADR-0025 已定):那是真正的业务操作,可被 CLI / MCP 复用。
- Palette 自身只承担"discovery + routing",不持有逻辑 —— 与 ADR-0025 的"thin shell over backend ActionRunner" 同构。

### 不做的事

- ❌ **基于 schema 的设置编辑**(VS Code 的 settings.json):knowlet 的 settings 极少,Settings dialog 已够用。
- ❌ **命令分组 / 分类**:总命令数 < 20 时分组反而碍事。等扩到 40+ 再考虑。
- ❌ **多前缀(`#tag`、`@symbol`、`:line`)**:有 ROI 时再加;`>` 一个先趟出模式切换的稳定模型。
- ❌ **历史 / Recently used**:未来 Slice 候选,先看真实使用反馈。

## Consequences

**Positive**
- 入口收敛:用户记一个 ⌘⇧P,代替 4-5 个散热键的认知负担。
- discovery 表面:新功能上线即在 palette 可被搜到,不再依赖发布说明 / tooltip。
- 跨语言 alias 让中英用户都能搜到(`keywords: ["theme", "主题"]`)。
- 与 ADR-0025 协同:quick actions 是用户私货,内置 commands 是产品默认值,palette 是统一发现表面。

**Negative**
- 多了一条前缀语义(`>`)需要用户学习。Footer hint + 模式 pill 缓解。
- 命令列表会随产品成长膨胀。设监控:总数 > 25 时再讨论分组 / sectioning。
- VS Code 习惯用户期望 `?` 显示帮助命令,目前未实现 —— 列入"未做的事",真有需求再加。

## Alternatives considered

- **方案 A:files 模式同时列 actions(轻方案)**
  Phase 2 D Slice 2c.1 实际就是这个做法。问题:files 模式被 actions 挤占,长 actions 列表把 "Quick switch a file" 体验 ruined。命令多了之后只会更糟。被否。

- **方案 C:两个独立对话框**
  ⌘P 走 quick switcher 组件,⌘⇧P 走 command palette 组件。问题:两份 UI 实现,样式飘移成本高,且用户在两者间切换无路径。被否。

- **后端命令注册中心**
  让 backend 暴露 commands manifest,frontend 拉取渲染。问题:对于纯 UI 切换无意义(后端没法 "切深色模式")。Quick actions 已经在后端,这块单独留 client-side 即可,不强行统一。被否。

## 实施位置

- `frontend/src/App.tsx` —— ⌘P / ⌘⇧P 全局键 → CustomEvent dispatch + `mode` detail
- `frontend/src/components/Palette/CommandPalette.tsx` —— 双模 UI、模式 pill、`>` 前缀消费、Backspace 回退
- `frontend/src/components/Palette/commands.ts` —— 内置命令注册表
- `frontend/src/components/AppShell/AppShell.tsx` —— `paletteInitialMode` 状态、`builtinCommands` 构造、CustomEvent listener `mode` 解析
- `frontend/src/i18n/{en,zh}.json` —— `palette.*` 扩展 + `commands.*` 命名空间
- `frontend/scripts/e2e/phase2d-slice2c3.mjs` —— 6 个测试覆盖打开 / 切换 / 回退 / 内置命令运行 / quick action 运行
