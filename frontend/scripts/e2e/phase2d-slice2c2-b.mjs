/**
 * Phase 2 D Slice 2c.2-B' — Quick actions manager (header ⚡ icon).
 *
 * Verifies the CRUD loop is closed:
 *   - ⚡ header button opens manager
 *   - Cmd+Shift+A toggles manager
 *   - Empty state shows hint
 *   - "+ 新建" creates a standalone action (NOT tied to creating a doc)
 *   - The editor can create/select a template, and runs inherit template kind
 *   - Edit pre-fills + saves
 *   - Delete confirms + removes
 *   - Run from manager opens the resulting note + closes manager
 */

import { assert, exitAfter, runTest, setupTestEnv } from "./_fixture.mjs";

const env = await setupTestEnv({
  folders: ["weekly", "reading"],
  notes: [{ title: "filler", body: "x" }],
  language: "en",
});
const { page, baseURL, teardown } = env;

function countRegularNotes(folder) {
  let count = folder.notes?.length ?? 0;
  for (const sub of folder.folders ?? []) {
    if (sub.name === "_templates") continue;
    count += countRegularNotes(sub);
  }
  return count;
}

try {
  // Auto-accept any window.confirm() — used by delete buttons.
  page.on("dialog", (d) => void d.accept());
  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);
  // Slice 2c.2-C': first GET /api/quick-actions seeds a default
  // `today-note`. Wipe it so the rest of this suite's "empty",
  // "exactly 1 row" assertions hold from a known clean baseline.
  await page.evaluate(async () => {
    const list = await (await fetch("/api/quick-actions")).json();
    for (const a of list) {
      await fetch(`/api/quick-actions/${a.id}`, { method: "DELETE" });
    }
  });

  await runTest("Header ⚡ icon opens manager (empty state)", async () => {
    await page.locator('[data-testid="header-quick-actions-button"]').click();
    await page
      .locator('[data-testid="quick-actions-manager"]')
      .waitFor({ state: "visible", timeout: 2000 });
    await page
      .locator('[data-testid="quick-actions-empty"]')
      .waitFor({ state: "visible", timeout: 1000 });
    await page.keyboard.press("Escape");
    await page.waitForTimeout(300);
  });

  await runTest("Cmd+Shift+A toggles manager", async () => {
    await page.keyboard.press("Meta+Shift+A");
    await page
      .locator('[data-testid="quick-actions-manager"]')
      .waitFor({ state: "visible", timeout: 2000 });
    await page.keyboard.press("Escape");
    await page.waitForTimeout(300);
  });

  await runTest("Standalone create — NO document is created", async () => {
    // Snapshot tree note count before.
    const before = await page.evaluate(async () =>
      (await fetch("/api/tree")).json(),
    );
    const beforeCount = countRegularNotes(before);

    await page.locator('[data-testid="header-quick-actions-button"]').click();
    await page
      .locator('[data-testid="quick-actions-manager"]')
      .waitFor({ state: "visible" });
    await page.locator('[data-testid="quick-actions-new"]').click();
    await page
      .locator('[data-testid="quick-actions-editor"]')
      .waitFor({ state: "visible", timeout: 2000 });

    await page.locator('[data-testid="editor-name"]').fill("Read article");
    await page.locator('[data-testid="editor-folder"]').fill("reading");
    await page
      .locator('[data-testid="editor-title-template"]')
      .fill("{{date}} reading");
    await page.locator('[data-testid="editor-template-picker"]').click();
    await page.locator('[data-testid="editor-template-create"]').click();
    await page
      .locator('[data-testid="template-create-dialog"]')
      .waitFor({ state: "visible", timeout: 2000 });
    await page.locator('[data-testid="template-title"]').fill("Reference clipping");
    await page.locator('[data-testid="template-kind-reference"]').click();
    await page.locator('[data-testid="template-body"]').fill("# {{title}}\n\nsource:");
    await page.locator('[data-testid="template-create-submit"]').click();
    await page.waitForTimeout(500);
    await page.locator('[data-testid="editor-shortcut"]').fill("Cmd+Shift+R");
    await page.locator('[data-testid="editor-description"]').fill("After finishing a piece");
    await page.locator('[data-testid="editor-save"]').click();
    await page.waitForTimeout(700);

    // Action persisted.
    const actions = await page.evaluate(async () =>
      (await fetch("/api/quick-actions")).json(),
    );
    assert(
      actions.length === 1 &&
        actions[0].name === "Read article" &&
        actions[0].params.content_template_id,
      `expected 1 'Read article' action, got ${JSON.stringify(actions)}`,
    );

    // No regular document was created (template creation lives under
    // _templates/ and is intentionally excluded here) — that's the
    // standalone-action contract this slice fixes.
    const after = await page.evaluate(async () =>
      (await fetch("/api/tree")).json(),
    );
    const afterCount = countRegularNotes(after);
    assert(
      afterCount === beforeCount,
      `note count must NOT grow on standalone create — before ${beforeCount} after ${afterCount}`,
    );
  });

  await runTest("Manager lists the saved action with name + folder/title", async () => {
    // Manager dialog is still visible (editor closed but list now has 1 row).
    const rows = await page.locator('[data-testid="quick-actions-row"]').count();
    assert(rows === 1, `expected 1 action row, got ${rows}`);
    const rowText = await page
      .locator('[data-testid="quick-actions-row"]')
      .first()
      .textContent();
    assert(
      /Read article/.test(rowText ?? "") &&
        /reading/.test(rowText ?? "") &&
        /\{\{date\}\}/.test(rowText ?? "") &&
        /Reference clipping/.test(rowText ?? "") &&
        /Reference/.test(rowText ?? ""),
      `row should show name + folder + template + inherited kind — got "${rowText}"`,
    );
  });

  await runTest("Edit ✏️ pre-fills the form + saves changes", async () => {
    await page.locator('[data-testid="quick-actions-edit"]').first().click();
    await page
      .locator('[data-testid="quick-actions-editor"]')
      .waitFor({ state: "visible", timeout: 2000 });
    const nameVal = await page.locator('[data-testid="editor-name"]').inputValue();
    assert(nameVal === "Read article", `editor pre-filled name — got "${nameVal}"`);
    // Change shortcut.
    await page.locator('[data-testid="editor-shortcut"]').fill("Cmd+Shift+E");
    await page.locator('[data-testid="editor-save"]').click();
    await page.waitForTimeout(500);
    // List reflects the change.
    const actions = await page.evaluate(async () =>
      (await fetch("/api/quick-actions")).json(),
    );
    assert(
      actions[0].shortcut === "Cmd+Shift+E",
      `shortcut updated — got "${actions[0].shortcut}"`,
    );
  });

  await runTest("⚡ Run from manager creates a doc + opens it + closes manager", async () => {
    await page.locator('[data-testid="quick-actions-run"]').first().click();
    await page.waitForTimeout(800);
    // Manager closed.
    const stillOpen = await page
      .locator('[data-testid="quick-actions-manager"]')
      .isVisible()
      .catch(() => false);
    assert(!stillOpen, "manager should close after running");
    // A note was created in reading/ matching today's date pattern.
    const tree = await page.evaluate(async () =>
      (await fetch("/api/tree")).json(),
    );
    const reading = tree.folders.find((f) => f.name === "reading");
    assert(
      reading && reading.notes && reading.notes.length >= 1,
      `reading/ should contain ≥1 note — got ${JSON.stringify(reading?.notes ?? [])}`,
    );
    const created = reading.notes.find((n) => /reading/.test(n.title));
    const full = await (
      await page.request.get(`${baseURL}/api/notes/${encodeURIComponent(created.id)}`)
    ).json();
    assert(full.kind === "reference", `created note inherits template kind — got ${full.kind}`);
    // h1 reflects the created note title.
    const h1 = (await page.locator('[data-testid="note-title"]').first().textContent()) ?? "";
    assert(/reading/.test(h1), `h1 should show '... reading' — got "${h1}"`);
  });

  await runTest("Delete 🗑 removes the action after confirm", async () => {
    await page.locator('[data-testid="header-quick-actions-button"]').click();
    await page
      .locator('[data-testid="quick-actions-manager"]')
      .waitFor({ state: "visible" });
    await page.locator('[data-testid="quick-actions-delete"]').first().click();
    await page.waitForTimeout(500);
    const actions = await page.evaluate(async () =>
      (await fetch("/api/quick-actions")).json(),
    );
    assert(actions.length === 0, `action should be deleted — got ${JSON.stringify(actions)}`);
    await page.keyboard.press("Escape");
  });

  await teardown();
  exitAfter(0);
} catch (e) {
  console.error("phase2d-slice2c2-b e2e failed:", e);
  await teardown();
  exitAfter(1);
}
