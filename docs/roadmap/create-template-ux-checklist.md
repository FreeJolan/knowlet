# Create + Template UX Checklist

## Abstract

Creation in Knowlet should make the user's intent explicit: ordinary notes,
reference notes, knowledge notes, and templates are related but not the same
thing. The app should give first-time users obvious creation paths in empty
states and quick actions, while keeping template management separate from
"use a template to create a note"; note kind flows from the template when a
template is used, and defaults to knowledge when no template is used.

## Prior Art

- VS Code Explorer keeps file/folder creation in the tree header and shows
  obvious empty-workspace actions. Snippets/templates are managed as their own
  authoring surface, while using a snippet happens inside the editor.
- Obsidian separates note creation from the Templates plugin's insertion
  workflow: a template is authored as reusable source material, then inserted
  later from a command/hotkey.
- Notion separates "new page" from "template gallery / template buttons"; the
  template editor is framed as configuring a reusable starting point, not as a
  normal page with all normal page creation controls.

## Build / Borrow

- Dialogs/popovers/tooltips: keep existing shadcn/Radix wrappers.
  `@radix-ui/react-dialog` latest 1.1.15, modified 2026-06-01;
  `@radix-ui/react-tooltip` latest 1.2.8, modified 2026-06-01.
- Kind display: reuse local `KindChip` visual language. Quick Actions do not
  get a separate kind picker; they inherit kind from the selected template, or
  default to knowledge when no template is selected. Considered
  `@radix-ui/react-radio-group` latest 1.3.8, modified 2026-06-01, but the
  corrected product rule removes the need for a standalone selector.
- Folder/template tree surfaces: keep existing `react-arborist` usage for file
  tree behavior. Latest `react-arborist` is 3.8.0, modified 2026-05-25; project
  currently pins `^3.5.0`.
- Template body editing: reuse existing CodeMirror-backed editor pieces where
  possible. `@uiw/react-codemirror` latest 4.25.10, modified 2026-05-21;
  project currently pins `^4.25.9`.
- Forms: self-implement with local React state. Considered `react-hook-form`
  latest 7.77.0, modified 2026-05-31, but adding it for two small dialogs would
  increase dependency surface without reducing much complexity.

## Path Checklist

P1 Default today-note kind
    ☑ implemented   ☑ tested   ✓ dogfooded
    Entry state: fresh vault, first `/api/quick-actions`.
    Happy path: default "今日笔记" action appears; running it creates/opens
    today's note as `reference` because the default action is backed by a
    default reference-kind daily template.
    Branch: user deletes default action; it is not re-seeded.
    Final assertion: created note frontmatter has `kind: reference`; the
    quick-action TOML references the daily template instead of storing an
    independent note kind; tree/cache refreshes.

P2 Quick Action inherits template kind
    ☑ implemented   ☑ tested   ✓ dogfooded
    Entry state: Quick Actions manager open.
    Happy path: user creates/edits action, selects a template, saves, runs it;
    the created note uses the template's `kind`.
    Branch: user clears the template or creates an action without a template;
    running it creates a `knowledge` note. Existing quick actions without
    template continue to behave as knowledge actions.
    Final assertion: payload does not persist an independent `note_kind`; run
    creates note kind = selected template kind, or `knowledge` when no template
    is selected; row displays the inherited/default kind source clearly.

P3 Quick Action template creation entry
    ☑ implemented   ☑ tested   ✓ dogfooded
    Entry state: Quick Action editor open and template picker visible.
    Happy path: user opens "new template" from the picker/editor, creates a
    template, returns to the action editor with the new template selected.
    Branch: user cancels template creation; action editor keeps previous state.
    Final assertion: `/api/templates` contains the new template; action editor
    can save using it.

P4 Empty note vault creation affordances
    ☑ implemented   ☑ tested   ✓ dogfooded
    Entry state: notes tab with no visible notes/folders.
    Happy path: centered empty state offers create note and create folder.
    Branch: user creates a folder from empty state, then cancels note creation.
    Final assertion: folder appears without a note; canceled note leaves no
    file.

P5 Empty template library affordances
    ☑ implemented   ☑ tested   ✓ dogfooded
    Entry state: Templates tab with no templates.
    Happy path: centered empty state offers create template.
    Branch: user cancels template creation.
    Final assertion: canceled flow leaves `_templates/` unchanged; successful
    flow creates one template and opens it in the template editor.

P6 Dedicated template creation/editing
    ☑ implemented   ☑ tested   ✓ dogfooded
    Entry state: Templates tab.
    Happy path: user creates a template through a template-specific dialog or
    editor with title/body only; no "use template to create" controls appear.
    Branch: user cancels template creation before saving.
    Final assertion: saved template is listed by `/api/templates`; canceled
    creation does not write a template note.

P7 Existing template use remains intact
    ☑ implemented   ☑ tested   ✓ dogfooded
    Entry state: New Document dialog or `/` insertion in a normal note.
    Happy path: user selects an existing template to create/insert content.
    Branch: no templates exist; picker shows a clear empty state and entry to
    create one.
    Final assertion: normal notes are created from templates as before; template
    management remains reachable without leaking `_templates/` as a normal
    folder.

## Persona Walkthrough

- 新用户 / P4-P6: sees a centered action instead of a small line of helper
  text, so the first empty vault step is obvious. The Templates tab says
  "create template" rather than asking them to infer Shift-click behavior.
- 小红 / P2-P3: can update her weekly action by choosing the right template
  rather than remembering frontmatter or setting the same type twice. If she
  needs a new template while configuring the action, she does not have to leave
  the flow and hunt for the Templates tab.
- 小张 / P1-P7: keeps quick actions as the fast path, with kind/template
  configuration encoded in the preset. Existing slash-template insertion stays
  low-friction.

## Testing Surface

- Backend: `uv run pytest tests/test_quick_actions.py tests/test_templates.py`
- Backend full: `uv run pytest tests/`
- Frontend typecheck: `cd frontend && npx tsc --noEmit`
- Focused E2E: `cd frontend && SKIP_BUILD=1 node scripts/e2e/phase2d-slice2c2-b.mjs`
- Focused E2E: `cd frontend && SKIP_BUILD=1 node scripts/e2e/templates.mjs`
- Full E2E: `cd frontend && npm run e2e`

## Path/Test Reconciliation

- P1 Default today-note kind →
  `tests/test_quick_actions.py::test_endpoint_seeds_today_note_on_first_get`;
  `frontend/scripts/e2e/phase2d-slice2c3.mjs`
- P2 Quick Action inherits template kind →
  `tests/test_quick_actions.py::test_endpoint_run_inherits_selected_template_kind`;
  `frontend/scripts/e2e/phase2d-slice2c2-b.mjs`
- P3 Quick Action template creation entry →
  `tests/test_templates.py::test_create_template_endpoint_writes_template_note`;
  `frontend/scripts/e2e/phase2d-slice2c2-b.mjs`
- P4 Empty note vault creation affordances →
  `frontend/scripts/e2e/create-template-empty-states.mjs`
- P5 Empty template library affordances →
  `tests/test_templates.py::test_create_template_endpoint_writes_template_note`;
  `frontend/scripts/e2e/create-template-empty-states.mjs`
- P6 Dedicated template creation/editing →
  `tests/test_templates.py::test_create_template_endpoint_writes_template_note`;
  `frontend/scripts/e2e/templates.mjs`;
  `frontend/scripts/e2e/create-template-empty-states.mjs`
- P7 Existing template use remains intact →
  `tests/test_templates.py::test_new_note_with_template_inherits_template_kind`;
  `frontend/scripts/e2e/templates.mjs`;
  `frontend/scripts/e2e/create-template-empty-states.mjs`

## Verification Log

- `uv run pytest tests/test_quick_actions.py tests/test_templates.py -q` —
  28 passed.
- `uv run pytest tests/` — 1055 passed.
- `uv run ruff check knowlet/core/quick_actions.py knowlet/web/server.py tests/test_quick_actions.py tests/test_templates.py` —
  passed.
- `cd frontend && npx tsc --noEmit` — passed.
- `cd frontend && npm run lint` — passed.
- `cd frontend && npm run build` — passed.
- `cd frontend && SKIP_BUILD=1 node scripts/e2e/templates.mjs` — passed.
- `cd frontend && SKIP_BUILD=1 node scripts/e2e/phase2d-slice2c2-b.mjs` —
  passed.
- `cd frontend && SKIP_BUILD=1 node scripts/e2e/phase2d-slice2c3.mjs` —
  passed.
- `cd frontend && SKIP_BUILD=1 node scripts/e2e/create-template-empty-states.mjs` —
  passed.
- `cd frontend && npm run e2e` — 49/49 suites passed.
