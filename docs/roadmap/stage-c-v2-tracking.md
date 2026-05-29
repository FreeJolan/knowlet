# Stage C v2 Tracking — 资讯审阅与入库

- Status: C4-C10 implemented and verified
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
    Entry state: Digest workbench is open and the source configuration panel is expanded.
    Happy path: user adds an RSS Source or Prompt Source, sees it in the source list, toggles enabled state, and can remove it.
    Branch: invalid URL / empty prompt is rejected without writing a source; general Settings no longer contains a Digest source tab.
    Final assertion: source file is persisted under the vault and API/CLI return the same shape.

P2 Pull + normalize pipeline
    ☑ implemented   ☑ tested   ✓ dogfooded
    Entry state: at least one enabled source exists.
    Happy path: daily auto-pull or manual pull creates raw info items with original links, summaries, source ids, and seen-set dedupe.
    Branch: source fails or pending raw info exceeds 200; pull records failure or pause state without losing existing items.
    Final assertion: raw items are queryable and source status shows success/failure/pause.

P3 Digest inbox v2
    ☑ implemented   ☑ tested   ✓ dogfooded
    Entry state: Digest is opened from the header.
    Happy path: user sees unprocessed raw info grouped by time or source and can switch grouping.
    Branch: empty inbox and >200 pending pause banner render correctly.
    Final assertion: no today/week tabs remain; raw info items display source, original link, summary, and status.

P4 Review mode
    ☑ implemented   ☑ tested   ✓ dogfooded
    Entry state: user clicks Start review or starts from one card.
    Happy path: large review overlay opens with read-only raw info on the left and conversation stream on the right.
    Branch: user skips, closes, or changes item while a conversation exists; state remains consistent.
    Final assertion: raw info is not directly editable and conversation remains anchored to the selected item.

P5 Create note draft from info
    ☑ implemented   ☑ tested   ✓ dogfooded
    Entry state: user is reviewing a raw info item.
    Happy path: user clicks Settle as note draft or asks AI to do it; AI receives raw info, discussion history, and library context, then returns title/body/tags/kind/folder/source.
    Branch: LLM or schema validation fails; no draft is written and the user sees a retryable error.
    Final assertion: a Note Draft exists, raw info remains read-only, and user can edit draft metadata before commit.

P6 Draft diff tools
    ☑ implemented   ☑ tested   ✓ dogfooded
    Entry state: review mode has a generated note draft.
    Happy path: user asks AI to revise draft; AI proposes a diff and user accepts or rejects all.
    Branch: user says reject/撤回 all or closes the diff mid-review; draft body does not silently change.
    Final assertion: accepted diff mutates only the draft; rejected diff leaves it unchanged.

P7 Commit note draft
    ☑ implemented   ☑ tested   ✓ dogfooded
    Entry state: note draft is ready in review mode.
    Happy path: user clicks Commit or asks AI to commit; note is written to the selected folder, indexed, and opened.
    Branch: missing title/body/folder or write failure blocks commit without deleting the draft.
    Final assertion: raw info is marked included, draft is committed, and formal Note appears in the vault.

P8 Digest workspace polish
    ☑ implemented   ☑ tested   ✓ dogfooded
    Entry state: user is in Digest inbox or opens review mode from a card.
    Happy path: source configuration lives in Digest, review opens as a full-screen workspace, Raw Info is selected first, Draft is disabled before generation, and generation switches into an editable Draft stage.
    Branch: empty-source state exposes configuration; closing review returns to inbox without a window backdrop.
    Final assertion: Digest-specific configuration is discoverable in the workbench and the Raw Info → Note Draft stage boundary is visible in DOM state.

## B.3 Persona Walkthrough

- **新用户 / P1**: I open Digest and need the source setup to be right there because it is required for the workflow. I need the UI to make RSS vs Prompt obvious and reject website subscription wording.
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
- Review workspace split: reuse existing `react-resizable-panels 2.1.9` (npm publish 2025-04-27) through the local `ResizablePanelGroup` wrapper. It matches AppShell's pane pattern and avoids new layout state.
- Stage tabs: considered `@radix-ui/react-tabs 1.1.13` (npm modified 2025-12-24), but rejected for C10 because this surface needs only two stable buttons with explicit ARIA state and no new dependency.
- Draft body editing: reuse existing `@uiw/react-codemirror 4.25.9` (npm publish 2026-03-25) indirectly through `MarkdownEditor`, the same primitive used by `NoteView`, so draft editing stays close to the main note experience.

## C.1 Similar Code Read

- Backend store pattern: `knowlet/core/mining/task_store.py`
- Existing digest wrapper: `knowlet/core/digest.py`
- CLI adapter pattern: `knowlet/cli/digest.py`
- Web endpoint pattern: `knowlet/web/server.py` mining/digest endpoints
- Frontend settings pattern: `frontend/src/components/Settings/SettingsDialog.tsx`
- Existing E2E shape: `frontend/scripts/e2e/digest-list.mjs`
- Digest-source workbench E2E shape: `frontend/scripts/e2e/digest-sources.mjs`

## C.2 Exact Verification Commands

- Backend focused: `uv run pytest tests/test_digest_pull.py tests/test_digest_sources.py tests/test_digest.py tests/test_cli.py`
- Backend related: `uv run pytest tests/test_web_note_chat.py tests/test_drafts_stage3.py tests/test_web_capture_flow.py`
- Frontend type: `cd frontend && npx tsc --noEmit`
- E2E focused: `cd frontend && node scripts/e2e/digest-list.mjs`; `cd frontend && node scripts/e2e/digest-sources.mjs`
- Full backend: `uv run pytest tests/`
- Full E2E baseline: `cd frontend && npm run e2e`

## C.3 Baseline

- Current baseline after commits `55e186d` and `f324845`:
  - `uv run pytest tests/test_web_note_chat.py tests/test_quick_actions.py tests/test_drafts_stage3.py tests/test_web_capture_flow.py tests/test_ai_envelope.py tests/test_sync_state.py tests/test_sync_oauth.py` → 98 passed.
  - `cd frontend && npx tsc --noEmit` → passed.
  - `git status --short` → clean.

## E.1 Path × Test Reconciliation

- P1 Source config v2 → `tests/test_digest_sources.py`, `tests/test_digest.py`, `tests/test_cli.py`, `frontend/scripts/e2e/digest-sources.mjs:21` Settings no longer owns Digest sources + `frontend/scripts/e2e/digest-sources.mjs:38` workbench add/toggle/remove ☑
- P2 Pull + normalize pipeline → `tests/test_digest_pull.py:59` RSS normalize + seen-set, `tests/test_digest_pull.py:136` Prompt Source JSON wrapper, `tests/test_digest_pull.py:187` 200 pending pause, `tests/test_digest_pull.py:226` API pull/list, `tests/test_digest_pull.py:330` CLI pull, `tests/test_digest_pull.py:375` CLI limit regression, `tests/test_digest_pull.py:432` daily auto-pull ☑
- P3 Digest inbox v2 → `tests/test_digest_pull.py:269` status API, `frontend/scripts/e2e/digest-list.mjs:123` Raw Info list/group/detail/empty/overflow paths ☑
- P4 Review mode → `tests/test_digest_pull.py:299` Raw Info chat stream + discussed state, `frontend/scripts/e2e/digest-list.mjs:191` review from header/chat/next/close, `frontend/scripts/e2e/digest-list.mjs:228` review from specific card ☑
- P5 Create note draft from info → `tests/test_digest_pull.py:332` API creates Draft with library context + metadata update, `tests/test_digest_pull.py:423` invalid LLM payload writes nothing, `tests/test_digest_pull.py:450` `create_note_draft_from_info` tool uses current Raw Info, `frontend/scripts/e2e/digest-list.mjs:239` review overlay creates a Draft and edits metadata ☑
- P6 Draft diff tools → `tests/test_digest_pull.py:531` draft diff API proposes without writing Note, `tests/test_digest_pull.py:549` reject keeps Draft body unchanged, `tests/test_digest_pull.py:564` accept mutates only Draft, `tests/test_digest_pull.py:607` conversation tool proposes/rejects/accepts current Draft, `frontend/scripts/e2e/digest-list.mjs:469` review chat opens DiffReview and can reject/accept all ☑
- P7 Commit note draft → `tests/test_digest_pull.py:632` `commit_note_draft` tool writes Note, indexes it, deletes Draft, and marks Raw Info included, `tests/test_digest_pull.py:650` empty-body commit blocks without deleting Draft, `frontend/scripts/e2e/digest-list.mjs:499` review overlay commit writes and opens the Note, `tests/test_cli.py` exposes `drafts commit`, `drafts accept-diff`, and `drafts reject-diff` commands ☑
- P8 Digest workspace polish → `frontend/scripts/e2e/digest-sources.mjs:21` general Settings lacks Digest tab, `frontend/scripts/e2e/digest-sources.mjs:38` source config is in Digest, `frontend/scripts/e2e/digest-list.mjs:191` review is full-screen with Raw Info/Draft stages, `frontend/scripts/e2e/digest-list.mjs:470` Draft stage enables and auto-selects after generation ☑

## E.3 Dogfood Log

- P1 Source config v2:
  - Historical production-build browser path at C4: Settings → Digest → source list rendered RSS / Prompt rows; C10 moved this surface into Digest workbench.
  - Adversarial branch: invalid RSS URL returns 400 and does not persist.
  - UI probes: panel background opaque (`rgb(239, 233, 221)`), add button hit target resolves at center, no unfiltered browser errors/warnings.
  - Screenshot: `/tmp/knowlet-c4-digest-sources.png`
- P2 Pull + normalize pipeline:
  - Red test: `tests/test_digest_pull.py::test_auto_pull_runs_once_per_day_and_rechecks_next_day` initially failed on missing `maybe_auto_pull_digest_sources`.
  - Focused green: `uv run pytest tests/test_digest_pull.py tests/test_digest_sources.py tests/test_digest.py tests/test_cli.py` → 34 passed; `cd frontend && node scripts/e2e/digest-sources.mjs` → passed.
  - Lint/type/full backend: `uv run ruff check knowlet/core/digest_items.py knowlet/core/digest_pull.py knowlet/core/digest_sources.py knowlet/core/vault.py knowlet/cli/digest.py knowlet/web/server.py tests/test_digest_pull.py` → passed; `cd frontend && npx tsc --noEmit` → passed; `cd frontend && npm run lint --silent` → passed; `uv run pytest tests/` → 986 passed.
  - Real model dogfood: temp vault `/tmp/knowlet-c5-dogfood-local.zCz5lQ`, local one-item RSS, `NO_PROXY=127.0.0.1,localhost KNOWLET_VAULT=<vault> uv run knowlet digest run --limit 1` via `gpt-5.5` → `fetched=1 new=1 created=1 skipped=0 pending=1`.
  - Dedupe dogfood: second run on the same feed → `fetched=1 new=0 created=0 skipped=0 pending=1`.
  - API smoke: `GET /api/health` on the temp vault returned `ready=true`; `GET /api/digest/items` returned the created read-only Raw Info item.
  - Screenshot: not applicable; P2 is backend/API/CLI infrastructure. Visual inbox verification starts at P3.
- P3 Digest inbox v2:
  - Red test: `cd frontend && node scripts/e2e/digest-list.mjs` initially failed because the old today/week draft tabs were still present.
  - Focused green: `cd frontend && node scripts/e2e/digest-list.mjs` → passed; `cd frontend && node scripts/e2e/digest-sources.mjs` → passed; `uv run pytest tests/test_digest_pull.py tests/test_digest_sources.py tests/test_digest.py tests/test_cli.py` → 35 passed.
  - Lint/type/full backend: `cd frontend && npx tsc --noEmit` → passed; `cd frontend && npm run lint --silent` → passed; `uv run pytest tests/` → 987 passed.
  - UI probes: detail panel background is opaque; card center resolves through `document.elementFromPoint`; console clean in populated / overflow / empty inbox suites.
  - Screenshot: `/tmp/knowlet-c6-digest-inbox.png`
- P4 Review mode:
  - Red test: `tests/test_digest_pull.py::test_raw_info_chat_stream_marks_item_discussed` initially failed with `405 Method Not Allowed`; the old UI also had no review overlay entry points.
  - Focused green: `uv run pytest tests/test_digest_pull.py tests/test_digest_sources.py tests/test_digest.py tests/test_cli.py` → 36 passed; `cd frontend && node scripts/e2e/digest-list.mjs` → passed.
  - Lint/type/full backend: `uv run ruff check knowlet/chat/raw_info_chat.py knowlet/web/server.py tests/test_digest_pull.py` → passed; `cd frontend && npx tsc --noEmit` → passed; `cd frontend && npm run lint --silent` → passed; `uv run pytest tests/` → 989 passed.
  - UX check: header "Start review" opens the overlay, card "Review from here" starts at that card, right-side chat uses `/api/chat/raw-info/{id}/stream`, and Next/Close preserve a consistent selected item.
  - Screenshot: `/tmp/knowlet-c7-review-mode.png`
- P5 Create note draft from info:
  - Red test: `tests/test_digest_pull.py::test_raw_info_draft_api_creates_review_draft_with_library_context` initially failed with `405 Method Not Allowed`; `frontend/scripts/e2e/digest-list.mjs` initially failed because `digest-settle-draft` did not exist.
  - Focused green: `uv run pytest tests/test_digest_pull.py::test_raw_info_draft_api_creates_review_draft_with_library_context tests/test_digest_pull.py::test_raw_info_draft_api_rejects_invalid_llm_payload_without_writing tests/test_digest_pull.py::test_create_note_draft_from_info_tool_uses_current_raw_info` → 3 passed; `cd frontend && SKIP_BUILD=1 node scripts/e2e/digest-list.mjs` → passed.
  - Related green: `uv run pytest tests/test_digest_pull.py tests/test_digest_sources.py tests/test_digest.py tests/test_cli.py` → 39 passed; `uv run pytest tests/test_web_note_chat.py tests/test_drafts_stage3.py tests/test_web_capture_flow.py` → 36 passed; `uv run pytest tests/` → 994 passed; `cd frontend && npx tsc --noEmit` → passed; `cd frontend && npm run lint --silent` → passed; `cd frontend && npm run build --silent` → passed.
  - E2E green: `cd frontend && node scripts/e2e/digest-list.mjs` → passed; `cd frontend && SKIP_BUILD=1 node scripts/e2e/digest-sources.mjs` → passed.
  - Real model dogfood: temp vault `/var/folders/5x/snmbmx3s5h372_xpld7c2mlh0000gn/T/knowlet-c8-dogfood-dr6njlmy`, `cliproxyapi` + `gpt-5.5` generated Draft `01KSTFXYB119KF3XHSGNSQ01AT`, selected folder `ai/agents`, marked Raw Info `drafted`.
  - Browser dogfood: production build served from temp vault `/var/folders/5x/snmbmx3s5h372_xpld7c2mlh0000gn/T/knowlet-c8-ui-dogfood-ttre8wdj`; Digest → Start review → Settle as note draft created visible draft metadata. Probes: result panel background `rgb(244, 240, 232)`, center hit target resolved to `digest-settle-draft`, active element `BODY`, browser logs had no errors/warnings.
  - Screenshot: `/tmp/knowlet-c8-draft-dogfood.png`
  - UX check: review overlay now has "Settle as note draft"; generated drafts show title/tags/kind/folder metadata and can save metadata changes before commit. `create_note_draft_from_info` is also registered as a tool, so conversation-driven settlement can use the same backend path.
- P6 Draft diff tools:
  - Red tests: `tests/test_digest_pull.py::test_raw_info_draft_diff_api_accepts_or_rejects_without_note_write` initially failed with `405 Method Not Allowed`; `tests/test_digest_pull.py::test_current_draft_tools_propose_accept_reject_and_commit` initially failed because `propose_current_draft_edit` was not registered; `frontend/scripts/e2e/digest-list.mjs` initially timed out waiting for `[data-testid="diff-review"]`.
  - Focused green: `uv run pytest tests/test_digest_pull.py::test_raw_info_draft_diff_api_accepts_or_rejects_without_note_write tests/test_digest_pull.py::test_current_draft_tools_propose_accept_reject_and_commit tests/test_digest_pull.py::test_commit_note_draft_rejects_empty_body_without_deleting_draft` → 3 passed; `cd frontend && SKIP_BUILD=1 node scripts/e2e/digest-list.mjs` → passed.
  - Related green: `uv run pytest tests/test_digest_pull.py tests/test_digest_sources.py tests/test_digest.py tests/test_cli.py` → 42 passed; `uv run pytest tests/test_web_note_chat.py tests/test_drafts_stage3.py tests/test_web_capture_flow.py` → 36 passed; `uv run pytest tests/test_architecture.py tests/test_bootstrap_and_slash.py` → 130 passed.
  - Full backend/frontend: `uv run pytest tests/` → 999 passed; `cd frontend && npm run lint --silent` → passed; `cd frontend && npx tsc --noEmit` → passed; `cd frontend && npm run build --silent` → passed.
  - Real model dogfood: temp vault `/var/folders/5x/snmbmx3s5h372_xpld7c2mlh0000gn/T/knowlet-c9-dogfood-k5hilqng`, `cliproxyapi` + `gpt-5.5`; `propose_current_draft_edit` returned `changed=True`, `accept_all_draft_diff` returned `accepted=True`, and the accepted Draft body was updated before any Note write.
  - Browser dogfood: production build served from temp vault `/var/folders/5x/snmbmx3s5h372_xpld7c2mlh0000gn/T/knowlet-c9-ui-dogfood-XXXXXX.uguV4aDKI8`; Digest → Start review → Settle as note draft worked. Browser plugin text input was blocked by its virtual clipboard limitation, so the interactive typed diff branch was covered by Playwright E2E and real-model tool dogfood instead.
- P7 Commit note draft:
  - Red test: `tests/test_digest_pull.py::test_commit_note_draft_rejects_empty_body_without_deleting_draft` initially failed with `405 Method Not Allowed`.
  - CLI parity: `uv run pytest tests/test_cli.py tests/test_digest_pull.py::test_current_draft_tools_propose_accept_reject_and_commit` → 19 passed; `drafts commit` is an alias for approve and shares the same commit helper, while `accept-diff` / `reject-diff` expose draft diff lifecycle controls.
  - Real model dogfood: after accepting the GPT-5.5 draft diff, `commit_note_draft` wrote `/private/var/folders/5x/snmbmx3s5h372_xpld7c2mlh0000gn/T/knowlet-c9-dogfood-k5hilqng/notes/ai/agents/01KSTHDEPJQ4D773D6Q62SQZAW.md`, indexed title `Agent Trace Review`, deleted the Draft, and marked Raw Info `included`.
  - Browser dogfood: production build path Digest → Start review → Settle as note draft → Commit note showed `Committed "Agent trace review patterns"`; API confirmed Raw Info status `included` with `note_id=01KSTHGTEZHWZ0QEPADMNRDABJ`.
  - UI probes: review overlay background `rgb(244, 240, 232)`, `document.elementFromPoint(center)` resolved to `digest-settle-draft`, active element `BODY`, and browser console had no new errors/warnings.
  - Screenshot: `/tmp/knowlet-c9-draft-commit-dogfood.png`
  - UX check: AI/tool-driven draft lifecycle now has the same boundary as the UI: propose diff → review → accept/reject all → explicit commit. Commit is blocked if a pending diff exists or title/body are missing, so Raw Info cannot silently enter the vault.
- P8 Digest workspace polish:
  - Red tests: `frontend/scripts/e2e/digest-sources.mjs` initially failed because general Settings still exposed `settings-tab-digest`; `frontend/scripts/e2e/digest-list.mjs` initially failed waiting for `digest-review-workspace` while the old windowed review overlay was still present.
  - Focused green: `cd frontend && SKIP_BUILD=1 node scripts/e2e/digest-sources.mjs` → passed; `cd frontend && SKIP_BUILD=1 node scripts/e2e/digest-list.mjs` → passed.
  - Related green: `uv run pytest tests/test_digest_pull.py tests/test_digest_sources.py tests/test_digest.py tests/test_cli.py` → 42 passed; `cd frontend && npx tsc --noEmit` → passed; `cd frontend && npm run build --silent` → passed.
  - Browser dogfood: production build served from `/tmp/knowlet-stage-c-demo-vault`; Digest → Configure sources showed the source panel in-workbench with opaque background `rgb(244, 240, 232)` and no Settings Digest tab.
  - Browser dogfood: Digest → Start review opened full-screen `digest-review-workspace` with no backdrop, Raw Info selected, Draft disabled, and center hit target on `digest-settle-draft`; clicking settle reused/generated a Draft, enabled Draft, auto-selected it, and showed `digest-draft-editor`.
  - UI probes: source panel background `rgb(244, 240, 232)`, review workspace background `rgb(244, 240, 232)`, `document.elementFromPoint(center)` resolved to `digest-config-toggle` / `digest-settle-draft`, active element `BUTTON`, and browser console had no errors/warnings.
  - Screenshots: `/tmp/knowlet-c10-digest-config.png`, `/tmp/knowlet-c10-review-workspace.png`, `/tmp/knowlet-c10-draft-stage.png`
  - UX check: Digest now owns source configuration; review mode is a full-screen workspace without a backdrop; Raw Info is the first selected stage; Note Draft is disabled until generation, then auto-selected and editable with the same Markdown editor primitive as the main note view.
