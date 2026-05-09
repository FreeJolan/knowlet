/**
 * Phase 2 D Slice 2a — NewDocDialog (Cmd+N + 顶栏「+ 新建文档」按钮).
 *
 * Verifies:
 *   - Cmd+N opens the dialog with seedFolder = currently-active note's folder
 *   - 顶栏 "+ 新建文档" button opens the same
 *   - 灵感 chip click fills folder + title fields
 *   - Esc closes the dialog
 *   - 创建 button creates note at the chosen folder + opens it in a tab
 *   - Title with {{date}} placeholder is rendered live to today's date
 *   - Footer "模板管理" link opens the existing TemplatesDialog (manager)
 */

import { assert, exitAfter, runTest, setupTestEnv } from "./_fixture.mjs";

function todayLocal() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

const env = await setupTestEnv({
  folders: ["projects", "projects/ai", "personal"],
  notes: [
    { title: "alpha", folder: "projects/ai", body: "alpha body" },
    { title: "loose", body: "root note" },
  ],
  language: "en",
});
const { page, baseURL, teardown } = env;

try {
  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);

  await runTest("Cmd+N opens dialog", async () => {
    await page.keyboard.press("Meta+N");
    await page
      .locator('[data-testid="new-document-dialog"]')
      .waitFor({ state: "visible", timeout: 2000 });
    await page.keyboard.press("Escape");
    await page.waitForTimeout(200);
  });

  await runTest("Tree [+ Note] button (click) opens dialog", async () => {
    // Header [+ 新建文档] button removed in 2026-05-09 dogfood iter —
    // tree's existing "+ Note" toolbar button now opens the dialog;
    // Shift+click keeps the legacy inline path.
    await page.locator('button[aria-label="New note"]').click();
    await page
      .locator('[data-testid="new-document-dialog"]')
      .waitFor({ state: "visible", timeout: 2000 });
  });

  await runTest("Right-click folder → New note inside opens dialog with seed", async () => {
    // Close any open dialog first.
    await page.keyboard.press("Escape").catch(() => {});
    await page.waitForTimeout(500);
    // Right-click projects/ai folder.
    await page
      .locator('[role="treeitem"]', { hasText: /^ai$/ })
      .first()
      .click({ button: "right" });
    await page.getByRole("menuitem", { name: /New note inside/ }).click();
    await page
      .locator('[data-testid="new-document-dialog"]')
      .waitFor({ state: "visible", timeout: 2000 });
    // Folder picker should show projects/ai pre-selected.
    const folder = await page
      .locator('[data-testid="dialog-folder-picker"]')
      .innerText();
    assert(
      /projects/.test(folder) && /ai/.test(folder),
      `seedFolder should be projects/ai, got "${folder}"`,
    );
  });

  await runTest("Tree [+ Note] Shift+click keeps legacy inline path", async () => {
    await page.keyboard.press("Escape").catch(() => {});
    await page.waitForTimeout(500);
    // Modifier-click via Playwright.
    await page.locator('button[aria-label="New note"]').click({
      modifiers: ["Shift"],
    });
    // Inline create stages a tree-row input, NOT the dialog.
    const dialogShown = await page
      .locator('[data-testid="new-document-dialog"]')
      .isVisible()
      .catch(() => false);
    assert(!dialogShown, "Shift+click must NOT open the dialog");
    await page
      .locator('input[data-rename-input="true"]')
      .waitFor({ state: "visible", timeout: 2000 });
    // Cancel the inline edit so the test environment is clean for the
    // next case.
    await page.keyboard.press("Escape");
    await page.waitForTimeout(200);
  });

  await runTest("Inspiration chip 周报 fills folder + title", async () => {
    // Re-open dialog (previous test closed it via Escape).
    await page.keyboard.press("Meta+N");
    await page
      .locator('[data-testid="new-document-dialog"]')
      .waitFor({ state: "visible", timeout: 2000 });
    await page.locator('[data-testid="inspiration-weekly"]').click();
    await page.waitForTimeout(500);
    const folder = await page
      .locator('[data-testid="dialog-folder-picker"]')
      .innerText();
    assert(/weekly/.test(folder), `folder should be weekly, got "${folder}"`);
    const titleVal = await page
      .locator('[data-testid="new-document-title"]')
      .inputValue();
    assert(
      titleVal.includes("周报") && titleVal.includes("{{week}}"),
      `title should include 周报 + {{week}}, got "${titleVal}"`,
    );
  });

  await runTest("Esc closes the dialog", async () => {
    await page.keyboard.press("Escape");
    await page.waitForTimeout(200);
    const stillOpen = await page
      .locator('[data-testid="new-document-dialog"]')
      .isVisible()
      .catch(() => false);
    assert(!stillOpen, "dialog should close on Esc");
  });

  await runTest("Cmd+N seeds folder = active note's folder", async () => {
    // Wait extra for any lingering Radix dialog overlay animation
    // before interacting with the tree.
    await page.waitForTimeout(400);
    // Open alpha (lives in projects/ai).
    await page
      .locator('[role="treeitem"]', { hasText: "alpha" })
      .first()
      .click();
    await page.waitForTimeout(300);
    await page.keyboard.press("Meta+N");
    await page
      .locator('[data-testid="new-document-dialog"]')
      .waitFor({ state: "visible", timeout: 2000 });
    const folder = await page
      .locator('[data-testid="dialog-folder-picker"]')
      .innerText();
    assert(
      /projects/.test(folder) && /ai/.test(folder),
      `seed folder should be projects/ai, got "${folder}"`,
    );
    await page.keyboard.press("Escape");
    await page.waitForTimeout(200);
  });

  await runTest(
    "Create with {{date}} placeholder renders today's date in title",
    async () => {
      await page.keyboard.press("Meta+N");
      await page
        .locator('[data-testid="new-document-dialog"]')
        .waitFor({ state: "visible", timeout: 2000 });
      // Pick personal folder via menu.
      await page.locator('[data-testid="dialog-folder-picker"]').click();
      await page
        .locator(
          '[data-testid="dialog-folder-option"][data-folder="personal"]',
        )
        .click();
      await page.waitForTimeout(500);
      // Type title with placeholder.
      const titleInput = page.locator('[data-testid="new-document-title"]');
      await titleInput.click();
      await titleInput.fill("journal {{date}}");
      // Submit.
      await page.locator('[data-testid="new-document-submit"]').click();
      await page.waitForTimeout(700);
      // Dialog closes; new tab open with rendered title.
      const today = todayLocal();
      const expectedTitle = `journal ${today}`;
      await page
        .locator('[data-testid="note-title"]')
        .filter({ hasText: today })
        .first()
        .waitFor({ state: "visible", timeout: 3000 });
      // Disk verification.
      const tree = await page.evaluate(async () =>
        (await fetch("/api/tree")).json(),
      );
      const personal = tree.folders.find((f) => f.name === "personal");
      const hit = (personal?.notes ?? []).find(
        (n) => n.title === expectedTitle,
      );
      assert(
        hit,
        `expected ${expectedTitle} in personal/, got ${JSON.stringify((personal?.notes ?? []).map((n) => n.title))}`,
      );
    },
  );

  await runTest(
    "Footer 'Templates → Settings/Templates' link opens manager",
    async () => {
      await page.keyboard.press("Meta+N");
      await page
        .locator('[data-testid="new-document-dialog"]')
        .waitFor({ state: "visible", timeout: 2000 });
      await page.locator('[data-testid="open-templates-manager"]').click();
      await page.waitForTimeout(400);
      // Existing TemplatesDialog should be visible (text "Templates").
      const tplDialog = await page
        .locator("text=Templates")
        .filter({ hasNotText: "Quick" })
        .first()
        .isVisible()
        .catch(() => false);
      assert(
        tplDialog,
        "Templates manager should open after clicking footer link",
      );
      await page.keyboard.press("Escape");
      await page.waitForTimeout(200);
    },
  );

  await teardown();
  exitAfter(0);
} catch (e) {
  console.error("phase2d-slice2a e2e failed:", e);
  await teardown();
  exitAfter(1);
}
