# Archived ADRs

ADRs that no longer represent the current product direction. Kept for git-blame and historical context, **not** as binding constraints.

If you're looking for what knowlet currently is, read `../README.md` and the ADRs at the parent level.

## Why each was archived

- **`0001-wedge-learning-first.md`** — Superseded by [ADR-0003](../0003-wedge-pivot-ai-memory-layer.md) on 2026-04-30, the same day it was originally accepted. The "exam / SRS / OCR cards" wedge was abandoned in favor of "AI long-term memory layer + lower-burden PKM." Archived 2026-05-02 to remove the false impression that exam-prep is still on the roadmap.

- **`0007-mvp-slice.md`** — The MVP slice it described (CLI-only chat REPL, no web UI, M0-only) is now historical. M6 has shipped a three-column web UI with command palette and three focus modes; M0/M1 work it sequenced is done. Archived 2026-05-02 to remove milestone-driven scaffolding from the active decision set. Current milestone state lives in the project memory snapshot, not in an ADR.

## Decision-set hygiene principle (also see [ADR-0008 §"Update 2026-05-02"](../0008-cli-parity-discipline.md) and [`feedback_no_hidden_debt`](../../../) if you have memory access)

ADRs should bind, not narrate. Anything that becomes obsolete the moment a milestone ships should not be an ADR — it should be a memo, a memory entry, or a roadmap item.
