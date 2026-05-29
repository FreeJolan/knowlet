---
created_at: '2026-05-29T16:10:52Z'
id: 01KST81D0BY4TMW0T6B9GFTVHX
kind: reference
schema_version: 1
source: https://example.com/ai-tool-protocol-boundary
status: draft
tags:
- digest
- stage-c-dogfood
task_id: 01KST81D0AN4XWQ0BX8K3QJMS4
title: Stage C 样例 - AI 工具调用协议边界
updated_at: '2026-05-29T16:10:52Z'
---

一篇技术文章讨论 Chat Completions、Responses API、本地 tools 与 hosted web_search 的边界。

要点：
- 模型本身可能具备工具推理能力，但真正能调用什么，取决于 provider/API surface 是否暴露。
- 应用侧仍需要负责执行本地工具、保存结果、把 trace 展示给用户。
- 对 knowlet 这类本地知识库，能力画像应该基于 endpoint + model 的实测结果，而不是只看模型名。

为什么值得看：这条可以帮助判断 knowlet 的 F0 能力层是否抽象得足够清楚。