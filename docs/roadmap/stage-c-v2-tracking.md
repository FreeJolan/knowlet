# Stage C v2 Tracking — 资讯审阅与入库

- Status: Active implementation
- Started: 2026-05-30
- Design: [`../design/stage-c-digest-inbox.md`](../design/stage-c-digest-inbox.md)

## A.1 Abstract

Knowlet should turn outside information into a reviewable inbox: raw items stay read-only, users discuss them with AI, then explicitly discard them or settle them into editable note drafts before final library entry.

## B.1 Prior Art

- **VS Code**: Settings uses a searchable, left-nav configuration surface, and source-control review separates raw file state from explicit accept/reject actions. The load-bearing pattern is: configuration and review are persistent work surfaces, not one-off popovers.
- **Readwise Reader**: feeds land in an inbox, can be triaged item by item, and keep original links/provenance visible while the user decides what deserves deeper attention. The load-bearing pattern is: intake is not the same as permanent knowledge storage.
- **Obsidian**: source material becomes durable only when it is written as markdown in the vault; plugins may ingest feeds, but vault files remain the user-auditable boundary. The load-bearing pattern is: local files are the final knowledge substrate.

## B.2 Path Checklist

P1 Source config v2
    ☑ implemented   ☑ tested   ✓ dogfooded
    Entry state: Settings is open, Digest tab selected.
    Happy path: user adds an RSS Source or Prompt Source, sees it in the source list, toggles enabled state, and can remove it.
    Branch: invalid URL / empty prompt is rejected without writing a source.
    Final assertion: source file is persisted under the vault and API/CLI return the same shape.

P2 Pull + normalize pipeline
    □ implemented   □ tested   □ dogfooded
    Entry state: at least one enabled source exists.
    Happy path: daily auto-pull or manual pull creates raw info items with original links, summaries, source ids, and seen-set dedupe.
    Branch: source fails or pending raw info exceeds 200; pull records failure or pause state without losing existing items.
    Final assertion: raw items are queryable and source status shows success/failure/pause.

P3 Digest inbox v2
    □ implemented   □ tested   □ dogfooded
    Entry state: Digest is opened from the header.
    Happy path: user sees unprocessed raw info grouped by time or source and can switch grouping.
    Branch: empty inbox and >200 pending pause banner render correctly.
    Final assertion: no today/week tabs remain; raw info items display source, original link, summary, and status.

P4 Review mode
    □ implemented   □ tested   □ dogfooded
    Entry state: user clicks Start review or starts from one card.
    Happy path: large review overlay opens with read-only raw info on the left and conversation stream on the right.
    Branch: user skips, closes, or changes item while a conversation exists; state remains consistent.
    Final assertion: raw info is not directly editable and conversation remains anchored to the selected item.

P5 Create note draft from info
    □ implemented   □ tested   □ dogfooded
    Entry state: user is reviewing a raw info item.
    Happy path: user clicks Settle as note draft or asks AI to do it; AI receives raw info, discussion history, and library context, then returns title/body/tags/kind/folder/source.
    Branch: LLM or schema validation fails; no draft is written and the user sees a retryable error.
    Final assertion: a Note Draft exists, raw info remains read-only, and user can edit draft metadata before commit.

P6 Draft diff tools
    □ implemented   □ tested   □ dogfooded
    Entry state: review mode has a generated note draft.
    Happy path: user asks AI to revise draft; AI proposes a diff and user accepts or rejects all.
    Branch: user says reject/撤回 all or closes the diff mid-review; draft body does not silently change.
    Final assertion: accepted diff mutates only the draft; rejected diff leaves it unchanged.

P7 Commit note draft
    □ implemented   □ tested   □ dogfooded
    Entry state: note draft is ready in review mode.
    Happy path: user clicks Commit or asks AI to commit; note is written to the selected folder, indexed, and opened.
    Branch: missing title/body/folder or write failure blocks commit without deleting the draft.
    Final assertion: raw info is marked included, draft is committed, and formal Note appears in the vault.

## B.3 Persona Walkthrough

- **新用户 / P1**: I open Settings because source setup feels like configuration. I need the UI to make RSS vs Prompt obvious and reject website subscription wording.
- **小红 / P1**: I add a couple of weekly feeds and expect to see whether they are enabled. I get stuck if the only route is CLI.
- **小张 / P1**: I want to toggle and remove sources quickly while testing. I get stuck if source errors are hidden from the list.

- **新用户 / P2-P4**: I click Digest and expect a queue, not a mining-task dashboard. I get stuck if raw information looks editable before it becomes a draft.
- **小红 / P2-P4**: I come back after a few days and need grouping plus pause status to explain the queue. I get stuck if today/week hides older pending items.
- **小张 / P2-P4**: I want to review many items with keyboard and quick actions. I get stuck if conversations reset or source grouping is slow.

- **新用户 / P5-P7**: I need the app to show that the AI draft is only a proposal. I get stuck if "commit" happens without a clear review boundary.
- **小红 / P5-P7**: I want to adjust title/tags/folder before saving. I get stuck if AI picks a folder but I cannot change it.
- **小张 / P5-P7**: I want to drive settle/revise/accept/commit by conversation. I get stuck if the tool trace says something happened but the draft state does not match.

## B.4 Build Or Borrow

- RSS parsing: keep existing Python `feedparser 6.0.12` (locked; PyPI upload 2025-09-10). It already exists in the project and is enough for C5 normalization.
- Article extraction: keep existing `trafilatura 2.0.0` (locked; PyPI upload 2024-12-03). Use it only for content cleanup/fetch, not for website subscriptions.
- Structured validation: keep existing `pydantic 2.13.3` (locked; PyPI upload 2026-04-20). It fits Prompt Source JSON validation and avoids adding another schema layer.
- Settings/source form UI: considered `react-hook-form 7.76.1` (npm modified 2026-05-23) and `zod 4.4.3` (npm modified 2026-05-04), but rejected for C4 because the form has few fields and the app already uses local React state for settings panels.

## C.1 Similar Code Read

- Backend store pattern: `knowlet/core/mining/task_store.py`
- Existing digest wrapper: `knowlet/core/digest.py`
- CLI adapter pattern: `knowlet/cli/digest.py`
- Web endpoint pattern: `knowlet/web/server.py` mining/digest endpoints
- Frontend settings pattern: `frontend/src/components/Settings/SettingsDialog.tsx`
- Existing E2E shape: `frontend/scripts/e2e/digest-list.mjs`

## C.2 Exact Verification Commands

- Backend focused: `uv run pytest tests/test_digest_sources.py tests/test_digest.py tests/test_cli.py`
- Backend related: `uv run pytest tests/test_web_note_chat.py tests/test_drafts_stage3.py tests/test_web_capture_flow.py`
- Frontend type: `cd frontend && npx tsc --noEmit`
- E2E focused: `cd frontend && SKIP_BUILD=1 node scripts/e2e/digest-sources.mjs`
- Full backend: `uv run pytest tests/`
- Full E2E baseline: `cd frontend && npm run e2e`

## C.3 Baseline

- Current baseline after commits `55e186d` and `f324845`:
  - `uv run pytest tests/test_web_note_chat.py tests/test_quick_actions.py tests/test_drafts_stage3.py tests/test_web_capture_flow.py tests/test_ai_envelope.py tests/test_sync_state.py tests/test_sync_oauth.py` → 98 passed.
  - `cd frontend && npx tsc --noEmit` → passed.
  - `git status --short` → clean.

## E.1 Path × Test Reconciliation

- P1 Source config v2 → `tests/test_digest_sources.py`, `tests/test_digest.py`, `tests/test_cli.py`, `frontend/scripts/e2e/digest-sources.mjs` ☑

## E.3 Dogfood Log

- P1 Source config v2:
  - Production-build browser path: Settings → Digest → source list renders RSS / Prompt rows.
  - Adversarial branch: invalid RSS URL returns 400 and does not persist.
  - UI probes: panel background opaque (`rgb(239, 233, 221)`), add button hit target resolves at center, no unfiltered browser errors/warnings.
  - Screenshot: `/tmp/knowlet-c4-digest-sources.png`
