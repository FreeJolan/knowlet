---
created_at: '2026-05-29T16:10:52Z'
id: 01KST81D0BY4TMW0T6B9GFTVHY
kind: reference
schema_version: 1
source: https://example.com/local-first-note-conflict
status: draft
tags:
- digest
- stage-c-dogfood
task_id: 01KST81D0AN4XWQ0BX8K3QJMS4
title: Stage C 样例 - 本地优先笔记的同步冲突
updated_at: '2026-05-29T16:10:52Z'
---

一篇产品设计笔记比较了本地优先笔记应用里的三类冲突：正文冲突、frontmatter 冲突、文件移动冲突。

要点：
- 正文冲突最适合用双栏 diff 让用户决定。
- metadata 冲突如果直接混入正文 diff，会制造噪音。
- 自动合并只适合低风险字段，高风险内容应保持用户确认。

为什么值得看：它和 knowlet “用户是最后一个字节”的原则高度相关，可以作为资料保存，也可能内化成同步设计准则。