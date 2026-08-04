# External Links v0.0.26 Tracking

Date: 2026-08-04

## Scope

Open absolute HTTP and HTTPS links from the Knowlet desktop app in the
system default browser without replacing the current Tauri webview or losing
the user's note, Digest, Draft, or Discuss context. Keep the browser build's
safe new-tab behavior and leave internal links and downloads alone.

Out of scope: choosing a browser, an in-app browser, link previews, copying or
sharing links, local files, `mailto:`, `tel:`, custom protocols, and a persisted
trusted-domain registry.

## B.1 Prior Art

- VS Code keeps the editor open while handing outgoing links to the browser.
  It also has Trusted Domains and a confirmation prompt; those controls are a
  separate product surface and are not part of this patch release.
- Obsidian treats an embedded web viewer as an optional capability. The default
  browser remains the safer fit for normal Markdown sources and authenticated
  pages.
- Knowlet follows the shared part of both patterns: keep the workbench context,
  use the OS browser, and allow only explicit web URL schemes.

## B.2 Path Checklist

P1 Note and Digest Draft body links

    ☑ implemented   ☑ tested   □ dogfooded

- Entry state: a Note or Digest Draft is open in Preview or Split mode and an
  HTTP or HTTPS anchor is visible.
- Happy branch: click the link, or focus it and press Enter. Desktop hands the
  exact URL, including query and fragment, to the default browser; web opens a
  safe new tab.
- Second branch: the OS opener rejects the request. Knowlet stays in place,
  shows a compact failure notice, and lets the user retry without an unhandled
  promise.
- Final assertion: selected document, view mode, scroll position, unsaved text,
  and `window.location` stay unchanged; the backend receives no write.

P2 Discuss, Raw Info Chat, and Draft Chat links

    ☑ implemented   ☑ tested   □ dogfooded

- Entry state: a user or assistant Markdown message contains an HTTP or HTTPS
  anchor, including while an assistant turn is streaming.
- Happy branch: mouse or keyboard activation opens the browser exactly once.
- Second branch: activate a complete link during streaming or rapidly activate
  it twice. The stream continues, the transcript stays in place, and duplicate
  browser handoffs are suppressed.
- Final assertion: transcript, scroll position, selected object, and generation
  state stay unchanged; opening the link does not append a message.

P3 Note, Digest, and Draft source links

    ☑ implemented   ☑ tested   □ dogfooded

- Entry state: a Note source pill or Properties URL, Digest card/detail/review
  source, or Digest Draft source is visible.
- Happy branch: activating the link opens the exact stored source URL.
- Second branch: activating a link inside a Digest card does not bubble into
  card selection; rapid activation does not advance review or open duplicates.
- Final assertion: current Note, Raw Info item, Review stage, Draft, and backend
  status remain unchanged.

P4 Internal, download, empty, and unsafe link boundary

    ☑ implemented   ☑ tested   □ dogfooded

- Entry state: Preview contains a wikilink, heading target, inline tag, empty
  href, download, relative URL, or a non-HTTP(S) scheme.
- Happy branch: wikilinks and tags keep their existing in-app behavior, while
  downloads keep their existing download path.
- Second branch: missing internal targets and unsafe schemes neither call the
  native opener nor navigate the current webview.
- Final assertion: valid internal navigation reaches the expected DOM state;
  blocked targets produce zero opener calls and zero backend writes.

P1 directly exercises both the Tauri handoff and an ordinary browser popup.
The document-level browser fallback is tested once because the same handler
serves every anchor; it is not repeated for each P2 and P3 entry. P2 and P3
exercise the Tauri route from every reachable surface, and their renderers
retain safe `_blank` and `noopener noreferrer` attributes. No path is deferred.

## B.3 Persona Walkthrough

| Path | New user | Xiaohong | Xiaozhang |
| --- | --- | --- | --- |
| P1 | I click a familiar web link and expect my browser to open. I get stuck if nothing happens or Knowlet is replaced. | I open a source from an old note and return to the same reading position. I get stuck if the mode, scroll, or unsaved text resets. | I use Split mode and keyboard activation. I get stuck if Enter fails or the editor loses buffered text. |
| P2 | I click a citation in an AI answer without knowing which Markdown renderer produced it. I get stuck if the conversation is replaced. | I check a source and return to the same transcript. I get stuck if scrolling or generation resets. | I open references while a turn is streaming. I get stuck if one action opens duplicates or aborts the turn. |
| P3 | The source icon reads as "open the original". I get stuck if clicking it also changes the selected card. | I use source links from Properties, Digest, and Draft. I get stuck if those entry points behave differently. | I review several Raw Info items in sequence. I get stuck if opening a source advances or mutates the queue. |
| P4 | I follow visual link cues rather than URL schemes. I get stuck if an internal link leaves the app. | I rely on wikilinks and tags for daily navigation. I get stuck if a global handler breaks them. | I use `[[Note#Heading]]` from the keyboard. I get stuck if interception steals heading resolution. |

## B.4 Build Or Borrow

- Use `@tauri-apps/plugin-opener` `2.5.4` and `tauri-plugin-opener`
  `2.5.4`, both published 2026-05-02. Pin the JavaScript package as
  `"2.5.4"` and the Rust crate as `=2.5.4`.
- Grant `opener:allow-open-url` only for `http://*` and `https://*`.
  Do not grant the broader default permission, which also covers mail and
  telephone schemes plus file-reveal behavior.
- Reject `@tauri-apps/plugin-shell` / `tauri-plugin-shell` `2.3.5`
  (2026-02-03): starting processes is a wider capability than opening a URL.
- Reject Rust `open` `5.4.0` (2026-07-12): it would require a custom command,
  validation, and capability bridge already supplied by the official plugin.
- Reject npm `open` `11.0.0` (2025-11-15): it requires Node, which is not
  available in the Tauri webview.

## C.1 Similar Code Read

- Runtime branching and native calls: `frontend/src/components/DesktopVaultLauncher.tsx`
- Existing Tauri plugin wrapper: `frontend/src/components/DesktopUpdate/useDesktopUpdater.ts`
- Markdown anchor routing: `frontend/src/components/Editor/MarkdownPreview.tsx`
- Chat Markdown renderer: `frontend/src/components/Discuss/ChatMarkdown.tsx`
- Tauri IPC mock shape: `frontend/scripts/e2e/desktop-vault-launcher.mjs`
- Existing external-link assertion: `frontend/scripts/e2e/preview.mjs`
- Desktop plugin and capability registration: `frontend/src-tauri/src/lib.rs`
  and `frontend/src-tauri/capabilities/default.json`

## C.2 Exact Verification Commands

- Backend tests: `uv run pytest tests/`
- Frontend E2E: `cd frontend && npm run e2e`
- Frontend type check: `cd frontend && npx tsc --noEmit`
- Frontend lint: `cd frontend && npm run lint --silent`
- Frontend build: `cd frontend && npm run build --silent`
- Desktop tests: `cd frontend && npm run desktop:test`
- Focused E2E: `cd frontend && SKIP_BUILD=1 node scripts/e2e/preview.mjs`
- Focused E2E: `cd frontend && SKIP_BUILD=1 node scripts/e2e/discuss-pane.mjs`
- Focused E2E: `cd frontend && SKIP_BUILD=1 node scripts/e2e/phase1d-slice3.mjs`
- Focused E2E: `cd frontend && SKIP_BUILD=1 node scripts/e2e/digest-list.mjs`
- CI backend lint: `uv run ruff check`
- CI backend format: `uv run ruff format --check`
- CI backend typing: `uv run mypy knowlet`
- CI backend coverage: `uv run pytest --cov=knowlet --cov-report=xml --cov-report=term`

CI runs the backend lint, format, typing, and coverage gates, then installs the
frontend with Node 22, builds it, installs Chromium, and runs every E2E suite.

## C.3 Baseline

- `uv run pytest tests/`: 1086 passed on Python 3.12.13.
- `uv run ruff check`: passed.
- `uv run ruff format --check`: 212 files already formatted.
- `uv run mypy knowlet`: 129 source files passed.
- `cd frontend && npx tsc --noEmit`: passed.
- `cd frontend && npm run lint --silent`: passed.
- `cd frontend && npm run desktop:test`: 49 passed.
- `cd frontend && npm run e2e`: 54/55 suites passed after correcting the
  local Python environment. `discuss-composer.mjs` consistently exposes a
  pre-existing controlled-textarea caret race (`two` becomes `otw` immediately
  after Markdown list continuation). Its existing regression test will remain
  the gate while the root race is repaired before release.
- `npm run dev -- --host 127.0.0.1 --port 4175`: Vite started in 257 ms and
  returned HTTP 200.

## E.1 Path To Test Mapping

- P1 Note and Digest Draft body links:
  `frontend/scripts/e2e/preview.mjs:314`,
  `frontend/scripts/e2e/preview.mjs:337`,
  `frontend/scripts/e2e/preview.mjs:359`,
  `frontend/scripts/e2e/preview.mjs:425`,
  `frontend/scripts/e2e/preview.mjs:482`,
  `frontend/scripts/e2e/preview.mjs:507`,
  `frontend/scripts/e2e/preview.mjs:539`, and
  `frontend/scripts/e2e/digest-list.mjs:1123`. These cover mouse and keyboard
  entry, the real browser fallback, exact URLs, Split scroll and buffered text,
  zero backend writes, anchor remounts, stale request ordering, opener failure
  and retry, stable Draft state, and the Draft no-autosave assertion. ☑
- P2 Discuss, Raw Info Chat, and Draft Chat links:
  `frontend/scripts/e2e/discuss-pane.mjs:255`,
  `frontend/scripts/e2e/discuss-composer.mjs:370`, and
  `frontend/scripts/e2e/discuss-composer.mjs:436`. These activate user and
  assistant links in Discuss Note, Raw Info review, and the reachable Draft
  review stage. They also cover streaming, rapid mouse and Enter repeats,
  internal-link boundaries, transcript content and count, non-zero scroll,
  selected context, URL, and generation state. ☑
- P3 Note, Digest, and Draft source links:
  `frontend/scripts/e2e/phase1d-slice3.mjs:97`,
  `frontend/scripts/e2e/phase1d-slice3.mjs:167`,
  `frontend/scripts/e2e/phase1d-slice3.mjs:364`,
  `frontend/scripts/e2e/digest-list.mjs:412`,
  `frontend/scripts/e2e/digest-list.mjs:449`,
  `frontend/scripts/e2e/digest-list.mjs:491`,
  `frontend/scripts/e2e/digest-list.mjs:528`, and
  `frontend/scripts/e2e/digest-list.mjs:1152`. These cover every source entry,
  invalid input, mouse and keyboard card bubbling, rapid repeats, review state,
  backend status, and Draft autosave state. ☑
- P4 Internal, download, empty, and unsafe boundary:
  `frontend/scripts/e2e/preview.mjs:594`,
  `frontend/scripts/e2e/preview.mjs:653`,
  `frontend/scripts/e2e/preview.mjs:674`,
  `frontend/scripts/e2e/wikilinks.mjs:102`,
  `frontend/src-tauri/src/lib.rs:1000`, and
  `frontend/src-tauri/src/lib.rs:1010`. These cover wikilinks, tags, heading
  targets, missing targets, relative and empty links, unsafe schemes,
  a completed browser download, zero backend writes, plugin registration, and
  the HTTP(S)-only capability. ☑

## E.2 Final Automated Gates

- `uv run pytest tests/`: 1086 passed.
- `cd frontend && npm run e2e`: 55 of 55 suites passed in 126.5 seconds after
  repairing the controlled-textarea caret race and the Digest source cache
  update race.
- `cd frontend && npx tsc --noEmit`: passed.
- `cd frontend && npm run lint --silent`: passed.
- `cd frontend && npm run build --silent`: passed.
- `cd frontend && npm run desktop:test`: 51 passed.
- `uv run ruff check`: passed.
- `uv run ruff format --check`: 212 files formatted.
- `uv run mypy knowlet`: 129 source files passed.
- `uv run pytest --cov=knowlet --cov-report=xml --cov-report=term`: 1086
  passed, 73 percent total coverage.

## E.3 Dogfood

Change surface: global external-link handoff with a fixed failure status
notice.

Added probes beyond the floor:

- Resize from 1440 by 900 to 1000 by 720 before activation.
- Mouse, Tab, Shift+Tab, Enter, Escape, and rapid double-click activation.
- Empty, unsafe, invalid, and 4132-character HTTP URL inputs.
- Reload while the mocked opener promise is still pending.
- Open a chat link while response generation is still active.
- Replace an anchor during the rapid-click window and retry the same URL.
- Let an older opener request fail after a newer request succeeds.
- Preserve Split-mode buffered text and scroll without a backend write.
- Activate the non-Tauri browser fallback and confirm a hardened new tab.
- Complete the existing download path and verify its filename.
- Press Enter on a source link nested inside a keyboard-selectable Digest card.

Completed probes:

- The failure notice has opaque `rgb(237, 231, 217)` background and its center
  resolves to `[data-testid="external-link-error"]` through
  `document.elementFromPoint`.
- The activated anchor remains `document.activeElement`, and every changed CSS
  variable has a repository definition.
- Console errors and warnings: zero.
- No Vault write or schema changes are part of this release, so the real-Vault
  migration probe does not apply.
- No Vault scan, index, retrieval, or paint-on-keystroke hot path changed, so
  the performance probe does not apply.

Screenshots:

- P1: `/tmp/knowlet-v0.0.26-p1-note-link.png`
- P2: `/tmp/knowlet-v0.0.26-p2-chat-link.png`
- P3: `/tmp/knowlet-v0.0.26-p3-source-link.png`
- P4: `/tmp/knowlet-v0.0.26-p4-boundary.png`

The real Tauri app is running against a fresh temporary Vault. Final system
browser confirmation is waiting for the Mac to be unlocked.

## E.4 Cross-Interface Check

No backend Vault capability was added or changed. The new work is a UI-only
affordance that validates anchors and hands approved HTTP(S) URLs to the OS
browser, so CLI and MCP parity and the CLI experience exercise do not apply.

## E.5 Release Report

Pending implementation and verification.
