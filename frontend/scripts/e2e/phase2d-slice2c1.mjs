/**
 * Phase 2 D Slice 2c.1 — Quick actions persistence (ADR-0025).
 *
 * Verifies the end-to-end flow:
 *   - "保存为快捷操作" checkbox in NewDocDialog reveals sub-fields
 *   - On submit, both the note AND the quick action are persisted
 *   - Cmd+P palette shows the saved action under "快捷操作" / "Quick actions"
 *   - Triggering it from palette runs the backend's create_note flow
 *     (idempotent: same-day re-run reuses the existing note)
 */

import { assert, exitAfter, runTest, setupTestEnv } from "./_fixture.mjs";

const env = await setupTestEnv({
  folders: ["weekly"],
  notes: [{ title: "filler", body: "x" }],
  language: "en",
});
const { page, baseURL, teardown } = env;

try {
  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);

  await runTest("Save-as-quick-action checkbox toggles + reveals sub-fields", async () => {
    await page.keyboard.press("Meta+N");
    await page
      .locator('[data-testid="new-document-dialog"]')
      .waitFor({ state: "visible", timeout: 2000 });
    // Sub-fields hidden by default.
    let count = await page
      .locator('[data-testid="save-as-quick-action-fields"]')
      .count();
    assert(count === 0, `sub-fields hidden initially, got ${count}`);
    // Click checkbox.
    await page.locator('[data-testid="save-as-quick-action"]').click();
    await page.waitForTimeout(150);
    count = await page
      .locator('[data-testid="save-as-quick-action-fields"]')
      .count();
    assert(count === 1, `sub-fields should appear after toggle, got ${count}`);
  });

  await runTest("Submit creates both the note AND the quick action", async () => {
    // Fill folder + title + action name + shortcut.
    await page.locator('[data-testid="dialog-folder-picker"]').click();
    await page
      .locator('[data-testid="dialog-folder-option"][data-folder="weekly"]')
      .click();
    await page.waitForTimeout(150);
    await page.locator('[data-testid="new-document-title"]').fill("周报 {{week}}");
    await page.locator('[data-testid="action-name"]').fill("Weekly review");
    await page.locator('[data-testid="action-shortcut"]').fill("Cmd+Shift+W");
    await page.locator('[data-testid="action-description"]').fill("Sunday wrap-up");
    await page.locator('[data-testid="new-document-submit"]').click();
    await page.waitForTimeout(800);
    // Quick action should now exist.
    const actions = await page.evaluate(async () =>
      (await fetch("/api/quick-actions")).json(),
    );
    assert(
      actions.length === 1 && actions[0].name === "Weekly review",
      `expected 1 'Weekly review' action, got ${JSON.stringify(actions)}`,
    );
    assert(
      actions[0].params.kind === "create_note" &&
        actions[0].params.folder === "weekly" &&
        actions[0].params.title_template === "周报 {{week}}",
      `params not persisted correctly: ${JSON.stringify(actions[0].params)}`,
    );
    // Note also created (with rendered week placeholder in title).
    const tree = await page.evaluate(async () =>
      (await fetch("/api/tree")).json(),
    );
    const weekly = tree.folders.find((f) => f.name === "weekly");
    assert(
      weekly && weekly.notes.length >= 1,
      `expected note in weekly/, got ${JSON.stringify(weekly?.notes ?? [])}`,
    );
  });

  // 2026-05-10 — Slice 2c.3 split palette into files (⌘P) / commands
  // (⌘⇧P) modes; quick actions only appear in commands mode now. The
  // following tests use ⌘⇧P; the seeded today-note + the test's own
  // "Weekly review" action both live there.
  await runTest("⌘⇧P commands palette lists the saved action", async () => {
    await page.keyboard.press("Meta+Shift+P");
    await page.waitForTimeout(400);
    const allActions = await page
      .locator('[data-testid="palette-action-item"]')
      .allInnerTexts();
    assert(
      allActions.some((t) => /Weekly review/.test(t)),
      `commands mode should list Weekly review — got ${JSON.stringify(allActions)}`,
    );
    await page.keyboard.press("Escape");
    await page.waitForTimeout(200);
  });

  await runTest("Running action from commands mode opens the existing note (idempotent)", async () => {
    const tree = await page.evaluate(async () =>
      (await fetch("/api/tree")).json(),
    );
    const weekly = tree.folders.find((f) => f.name === "weekly");
    const initialNote = weekly?.notes?.[0];
    assert(initialNote, "must have created a weekly note in previous test");
    await page.keyboard.press("Meta+Shift+P");
    await page.waitForTimeout(300);
    // Filter to just our action so click hits the right row even if
    // today-note is also present.
    await page.locator('[data-testid="palette-input"]').fill("Weekly");
    await page.waitForTimeout(200);
    await page.locator('[data-testid="palette-action-item"]').first().click();
    await page.waitForTimeout(800);
    // Now check that the active tab title matches the existing note's title
    // (idempotency means we did NOT create a duplicate).
    const tree2 = await page.evaluate(async () =>
      (await fetch("/api/tree")).json(),
    );
    const weekly2 = tree2.folders.find((f) => f.name === "weekly");
    assert(
      weekly2.notes.length === 1,
      `must NOT duplicate — expected 1 note, got ${weekly2.notes.length}`,
    );
    assert(
      weekly2.notes[0].id === initialNote.id,
      "running action again must reuse the same note id",
    );
    // The h1 should show the rendered title.
    const h1 = (await page.locator('[data-testid="note-title"]').first().textContent()) ?? "";
    assert(
      /周报/.test(h1),
      `note pane should show 周报 ... — got "${h1}"`,
    );
  });

  await runTest("Delete action via API removes it from commands palette", async () => {
    // Find Weekly review's id (today-note is also seeded; we want the
    // user-created one).
    const actions = await page.evaluate(async () =>
      (await fetch("/api/quick-actions")).json(),
    );
    const weekly = actions.find((a) => /Weekly review/.test(a.name));
    assert(weekly, "Weekly review action must exist");
    await page.evaluate(
      async (id) => fetch(`/api/quick-actions/${id}`, { method: "DELETE" }),
      weekly.id,
    );
    await page.waitForTimeout(200);
    await page.keyboard.press("Meta+Shift+P");
    await page.waitForTimeout(400);
    const allActions = await page
      .locator('[data-testid="palette-action-item"]')
      .allInnerTexts();
    assert(
      !allActions.some((t) => /Weekly review/.test(t)),
      `palette must not list deleted Weekly review — got ${JSON.stringify(allActions)}`,
    );
    await page.keyboard.press("Escape");
  });

  await teardown();
  exitAfter(0);
} catch (e) {
  console.error("phase2d-slice2c1 e2e failed:", e);
  await teardown();
  exitAfter(1);
}
