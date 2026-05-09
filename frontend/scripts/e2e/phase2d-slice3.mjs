/**
 * Phase 2 D Slice 3 — Pinned tabs (VS Code parity).
 *
 * Verifies:
 *   - Right-click → Pin moves the tab to the leftmost pinned slot,
 *     shows the pin icon, hides the × close button.
 *   - Pinned tabs survive "Close All".
 *   - "Close Others" keeps pinned tabs in addition to the right-clicked.
 *   - Unpinning restores the × button + the tab leaves the pinned section.
 *   - Pinned ids persist across reload (localStorage round-trip).
 *   - Palette toggles "Pin tab" ↔ "Unpin tab" based on active tab state.
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
    { title: "ref-doc", body: "ref" },
    { title: "task-a", body: "a" },
    { title: "task-b", body: "b" },
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
  await openNoteByTitle("ref-doc");
  await openNoteByTitle("task-a");
  await openNoteByTitle("task-b");
  await page.waitForTimeout(200);

  await runTest("Right-click → Pin marks tab pinned + hides ×", async () => {
    const refTab = page.locator('[data-testid="tab"]', { hasText: "ref-doc" }).first();
    await refTab.click({ button: "right" });
    await page
      .locator('[data-testid="tab-context-pin"]')
      .waitFor({ state: "visible", timeout: 2000 });
    await page.locator('[data-testid="tab-context-pin"]').click();
    await page.waitForTimeout(250);
    // Tab now flagged data-pinned=true.
    const pinned = await page
      .locator('[data-testid="tab"][data-pinned="true"]')
      .count();
    assert(pinned === 1, `expected exactly 1 pinned tab, got ${pinned}`);
    // First tab in DOM order is the pinned one.
    const firstTabText = await page
      .locator('[data-testid="tab"]')
      .first()
      .textContent();
    assert(
      /ref-doc/.test(firstTabText ?? ""),
      `pinned tab should be leftmost — got "${firstTabText}"`,
    );
    // × close hidden inside the pinned tab.
    const closeBtns = await page
      .locator('[data-testid="tab"][data-pinned="true"] [data-testid="tab-close"]')
      .count();
    assert(closeBtns === 0, "pinned tab must NOT show × close button");
  });

  await runTest("'Close All' (Close Unpinned) keeps pinned tabs", async () => {
    const refTab = page.locator('[data-testid="tab"]', { hasText: "ref-doc" }).first();
    await refTab.click({ button: "right" });
    await page
      .locator('[data-testid="tab-context-close-all"]')
      .click();
    await page.waitForTimeout(250);
    const remaining = await page.locator('[data-testid="tab"]').count();
    assert(remaining === 1, `expected 1 pinned tab to survive, got ${remaining}`);
    const text = await page.locator('[data-testid="tab"]').first().textContent();
    assert(/ref-doc/.test(text ?? ""), `surviving tab should be ref-doc`);
  });

  await runTest("Pinned id persists across reload", async () => {
    // Open another tab so we have pinned + unpinned.
    await openNoteByTitle("task-a");
    await page.reload({ waitUntil: "networkidle" });
    await page.waitForTimeout(500);
    const pinned = await page
      .locator('[data-testid="tab"][data-pinned="true"]')
      .count();
    assert(pinned === 1, `pinned should survive reload, got ${pinned}`);
    const total = await page.locator('[data-testid="tab"]').count();
    assert(total === 2, `total tabs should be 2 after reload, got ${total}`);
  });

  await runTest("'Close Others' on unpinned tab keeps pinned + clicked", async () => {
    // Add a third tab.
    await openNoteByTitle("task-b");
    let total = await page.locator('[data-testid="tab"]').count();
    assert(total === 3, `setup: 3 tabs (1 pinned + 2 unpinned), got ${total}`);
    // Right-click task-a → Close Others.
    const taskA = page.locator('[data-testid="tab"]', { hasText: "task-a" }).first();
    await taskA.click({ button: "right" });
    await page.locator('[data-testid="tab-context-close-others"]').click();
    await page.waitForTimeout(250);
    total = await page.locator('[data-testid="tab"]').count();
    assert(
      total === 2,
      `after Close Others: pinned + clicked = 2, got ${total}`,
    );
    const texts = (await page.locator('[data-testid="tab"]').allInnerTexts()).join(" ");
    assert(/ref-doc/.test(texts), "ref-doc (pinned) survives");
    assert(/task-a/.test(texts), "task-a (right-clicked) survives");
    assert(!/task-b/.test(texts), "task-b is closed");
  });

  await runTest("Right-click → Unpin removes pin marker", async () => {
    const refTab = page.locator('[data-testid="tab"]', { hasText: "ref-doc" }).first();
    await refTab.click({ button: "right" });
    await page.locator('[data-testid="tab-context-pin"]').click();
    await page.waitForTimeout(250);
    const pinned = await page
      .locator('[data-testid="tab"][data-pinned="true"]')
      .count();
    assert(pinned === 0, `expected 0 pinned after unpin, got ${pinned}`);
    // × button visible again.
    const closeBtns = await page
      .locator('[data-testid="tab"]', { hasText: "ref-doc" })
      .first()
      .locator('[data-testid="tab-close"]')
      .count();
    assert(closeBtns === 1, "× button restored on unpin");
  });

  await runTest("Palette toggles 'Pin tab' ↔ 'Unpin tab' via active state", async () => {
    // ref-doc currently active (we just unpinned it). Palette should
    // show "Pin tab".
    await page.keyboard.press("Meta+Shift+P");
    await page
      .locator('[data-testid="palette-input"]')
      .waitFor({ state: "visible", timeout: 2000 });
    await page.locator('[data-testid="palette-input"]').fill("pin");
    await page.waitForTimeout(150);
    const itemsBefore = await page
      .locator('[data-testid="palette-command-item"]')
      .allInnerTexts();
    assert(
      itemsBefore.some((t) => /Pin tab/i.test(t)) &&
        !itemsBefore.some((t) => /^Unpin tab/i.test(t)),
      `expected 'Pin tab' (not Unpin) — got ${JSON.stringify(itemsBefore)}`,
    );
    // Run it.
    await page
      .locator('[data-testid="palette-command-item"][data-command-id="builtin.tab-pin"]')
      .click();
    await page.waitForTimeout(300);
    // Re-open palette, expect "Unpin tab" now.
    await page.keyboard.press("Meta+Shift+P");
    await page
      .locator('[data-testid="palette-input"]')
      .waitFor({ state: "visible", timeout: 2000 });
    await page.locator('[data-testid="palette-input"]').fill("pin");
    await page.waitForTimeout(150);
    const itemsAfter = await page
      .locator('[data-testid="palette-command-item"]')
      .allInnerTexts();
    assert(
      itemsAfter.some((t) => /Unpin tab/i.test(t)),
      `expected 'Unpin tab' after pin — got ${JSON.stringify(itemsAfter)}`,
    );
    await page.keyboard.press("Escape");
  });

  await teardown();
  exitAfter(0);
} catch (e) {
  console.error("phase2d-slice3 e2e failed:", e);
  await teardown();
  exitAfter(1);
}
