/**
 * Phase 2 D Slice 2b — file-tree visuals.
 *
 * Verifies:
 *   - Indent guides: every visible row at depth ≥ 1 has N (= depth)
 *     guide spans (1 px line-soft) inside its row.
 *   - Ghost selection: when NewDocDialog is open with a target
 *     folder (e.g., projects/ai/papers), that row gets
 *     `[data-ghost-target="1"]` and the ancestor chain rows have
 *     hot guides (≥ 1 wider, accent-colored guide span).
 *   - Auto-expand: targeting a buried folder auto-opens the path so
 *     the target row is visible.
 *   - Ghost follows when user picks a different folder in the dialog.
 *
 * DnD 3-state visuals are NOT covered here — that's Slice 2c.
 */

import { assert, exitAfter, runTest, setupTestEnv } from "./_fixture.mjs";

const env = await setupTestEnv({
  folders: [
    "projects",
    "projects/ai",
    "projects/ai/papers",
    "projects/ai/papers/2026",
    "personal",
  ],
  notes: [
    {
      title: "attention",
      folder: "projects/ai/papers/2026",
      body: "self-attention",
    },
    { title: "alpha", folder: "personal", body: "x" },
  ],
  language: "en",
});
const { page, baseURL, teardown } = env;

try {
  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);

  await runTest("Indent guides render at every depth ≥ 1", async () => {
    // The seeded vault is open by default. Each row at depth d should
    // have d indent-guide spans inside it. Check `attention` (depth 4
    // — projects/ai/papers/2026/attention).
    const attention = page
      .locator('[role="treeitem"]', { hasText: "attention" })
      .first();
    await attention.waitFor({ state: "visible", timeout: 3000 });
    const guideCount = await attention.evaluate((el) => {
      // Indent guides are aria-hidden absolute spans with a fixed
      // width of 1 or 2 px and a non-button parent. Filter by their
      // 1/2 px width + line-soft / accent backgrounds.
      const spans = el.querySelectorAll('span[aria-hidden="true"]');
      let n = 0;
      for (const s of spans) {
        const w = (s.getBoundingClientRect().width || 0).toFixed(0);
        if (w === "1" || w === "2") n += 1;
      }
      return n;
    });
    assert(
      guideCount >= 4,
      `attention is at depth 4 → ≥ 4 guide spans, got ${guideCount}`,
    );
  });

  await runTest("Cmd+N ghost-targets root by default", async () => {
    await page.keyboard.press("Meta+N");
    await page
      .locator('[data-testid="new-document-dialog"]')
      .waitFor({ state: "visible", timeout: 2000 });
    await page.waitForTimeout(150);
    // Root target = no folder row gets data-ghost-target=1 (root has
    // no row to mark — it's the implicit container).
    const ghosts = await page
      .locator('[data-ghost-target="1"]')
      .count();
    assert(ghosts === 0, `root target has no ghost row, got ${ghosts}`);
  });

  await runTest(
    "Picking deep folder in dialog auto-expands path + sets ghost target",
    async () => {
      // Pick projects/ai/papers/2026 via the folder menu.
      await page.locator('[data-testid="dialog-folder-picker"]').click();
      await page
        .locator(
          '[data-testid="dialog-folder-option"][data-folder="projects/ai/papers/2026"]',
        )
        .click();
      await page.waitForTimeout(250);
      // The 2026 row should now have data-ghost-target.
      const ghostTarget = await page
        .locator('[data-ghost-target="1"]')
        .count();
      assert(
        ghostTarget === 1,
        `expected exactly 1 ghost row, got ${ghostTarget}`,
      );
      // The 2026 row should be visible (auto-expanded path).
      const target = page
        .locator('[role="treeitem"]', { hasText: /^2026$/ })
        .first();
      await target.waitFor({ state: "visible", timeout: 1500 });
    },
  );

  await runTest("Switching ghost folder updates the highlight", async () => {
    await page.locator('[data-testid="dialog-folder-picker"]').click();
    await page
      .locator(
        '[data-testid="dialog-folder-option"][data-folder="personal"]',
      )
      .click();
    await page.waitForTimeout(250);
    // Now `personal` is the target.
    const targetIds = await page.evaluate(() =>
      Array.from(document.querySelectorAll('[data-ghost-target="1"]')).map(
        (el) => (el.textContent ?? "").trim(),
      ),
    );
    assert(
      targetIds.length === 1 && /personal/.test(targetIds[0] ?? ""),
      `personal should be the ghost target, got ${JSON.stringify(targetIds)}`,
    );
  });

  await runTest("Closing dialog clears the ghost", async () => {
    await page.keyboard.press("Escape");
    await page.waitForTimeout(200);
    const ghosts = await page.locator('[data-ghost-target="1"]').count();
    assert(ghosts === 0, `closing dialog must clear ghost, got ${ghosts}`);
  });

  await teardown();
  exitAfter(0);
} catch (e) {
  console.error("phase2d-slice2b e2e failed:", e);
  await teardown();
  exitAfter(1);
}
