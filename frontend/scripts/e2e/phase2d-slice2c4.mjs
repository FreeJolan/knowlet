/**
 * Phase 2 D Slice 2c.4 — Tab context menu + ⌘W + Close All/Others.
 *
 * Verifies:
 *   - Right-click on a tab opens a context menu with Close /
 *     Close Others / Close All.
 *   - "Close Others" leaves only the right-clicked tab.
 *   - "Close All" empties the strip.
 *   - ⌘W closes the active tab.
 *   - The palette in commands mode lists "Close all tabs" / "Close
 *     other tabs" / "Close tab" with no-op rows hidden when there's
 *     nothing to close.
 */

import {
  assert,
  exitAfter,
  expectRow,
  runTest,
  setupTestEnv,
} from "./_fixture.mjs";

const env = await setupTestEnv({
  notes: [
    { title: "alpha", body: "x" },
    { title: "beta", body: "y" },
    { title: "gamma", body: "z" },
  ],
  language: "en",
});
const { page, baseURL, teardown } = env;

async function openNoteByTitle(title) {
  const row = await expectRow(page, title);
  await row.click();
  await page.waitForTimeout(150);
}

try {
  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);
  // Open three tabs.
  await openNoteByTitle("alpha");
  await openNoteByTitle("beta");
  await openNoteByTitle("gamma");
  await page.waitForTimeout(200);

  await runTest("Right-click on a tab opens the context menu", async () => {
    const tabBeta = page.locator('[data-testid="tab"]', { hasText: "beta" }).first();
    await tabBeta.click({ button: "right" });
    await page
      .locator('[data-testid="tab-context-menu"]')
      .waitFor({ state: "visible", timeout: 2000 });
    // Close + Close Others + Close All visible.
    await page
      .locator('[data-testid="tab-context-close"]')
      .waitFor({ state: "visible" });
    await page
      .locator('[data-testid="tab-context-close-others"]')
      .waitFor({ state: "visible" });
    await page
      .locator('[data-testid="tab-context-close-all"]')
      .waitFor({ state: "visible" });
    await page.keyboard.press("Escape");
    await page.waitForTimeout(150);
  });

  await runTest("'Close Others' keeps only the right-clicked tab", async () => {
    const tabBeta = page.locator('[data-testid="tab"]', { hasText: "beta" }).first();
    await tabBeta.click({ button: "right" });
    await page
      .locator('[data-testid="tab-context-close-others"]')
      .click();
    await page.waitForTimeout(250);
    const remaining = await page.locator('[data-testid="tab"]').count();
    assert(remaining === 1, `expected 1 tab after Close Others, got ${remaining}`);
    const text = await page
      .locator('[data-testid="tab"]')
      .first()
      .textContent();
    assert(/beta/.test(text ?? ""), `surviving tab should be beta — "${text}"`);
  });

  await runTest("⌘W closes the active tab", async () => {
    // Open another tab so we have 2.
    await openNoteByTitle("alpha");
    let count = await page.locator('[data-testid="tab"]').count();
    assert(count === 2, `setup: expected 2 tabs, got ${count}`);
    await page.keyboard.press("Meta+W");
    await page.waitForTimeout(250);
    count = await page.locator('[data-testid="tab"]').count();
    assert(count === 1, `expected 1 tab after ⌘W, got ${count}`);
  });

  await runTest("Palette command 'Close all tabs' empties the strip", async () => {
    // Open one more tab so list is > 0; close all via palette.
    await openNoteByTitle("gamma");
    const before = await page.locator('[data-testid="tab"]').count();
    assert(before >= 1, "setup: at least one tab before Close All");
    await page.keyboard.press("Meta+Shift+P");
    await page
      .locator('[data-testid="palette-input"]')
      .waitFor({ state: "visible", timeout: 2000 });
    await page.locator('[data-testid="palette-input"]').fill("close all");
    await page.waitForTimeout(150);
    await page
      .locator(
        '[data-testid="palette-command-item"][data-command-id="builtin.tab-close-all"]',
      )
      .click();
    await page.waitForTimeout(300);
    const after = await page.locator('[data-testid="tab"]').count();
    assert(after === 0, `expected 0 tabs after Close All command, got ${after}`);
  });

  await runTest("'Close tab' command is hidden when no tab is active", async () => {
    // No tabs open from prior test. Open palette, search "close".
    await page.keyboard.press("Meta+Shift+P");
    await page
      .locator('[data-testid="palette-input"]')
      .waitFor({ state: "visible", timeout: 2000 });
    const items = await page
      .locator('[data-testid="palette-command-item"]')
      .allInnerTexts();
    assert(
      !items.some((t) => /Close tab/i.test(t)),
      `Close tab must be hidden with 0 tabs — got ${JSON.stringify(items)}`,
    );
    assert(
      !items.some((t) => /Close all tabs/i.test(t)),
      "Close all tabs must be hidden with 0 tabs",
    );
    await page.keyboard.press("Escape");
  });

  await teardown();
  exitAfter(0);
} catch (e) {
  console.error("phase2d-slice2c4 e2e failed:", e);
  await teardown();
  exitAfter(1);
}
