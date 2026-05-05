// E2E: inline edit paths that the earlier "happy-path fill+Enter" suites
// missed. The user's pinyin-input test session caught:
//   - input visually visible but not actually focused
//   - Enter during IME composition committing the half-typed name AND
//     bubbling to arborist's tree handler, which then enters edit mode
//     on a sibling row.
// We assert focus explicitly and use real keyboard events + composition
// events instead of `input.fill()`.

import {
  assert,
  exitAfter,
  expectFocused,
  hasRow,
  runTest,
  setupTestEnv,
  simulateIMEComposition,
  typeInto,
} from "./_fixture.mjs";

const env = await setupTestEnv({
  notes: [{ title: "alpha", folder: "lab" }],
  folders: ["lab", "other"],
  language: "en",
});
const { page, baseURL, teardown } = env;

try {
  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);

  await runTest("toolbar 'New note' input gets focus immediately", async () => {
    await page.click('button[aria-label="New note"]');
    const input = page.locator('input[data-rename-input="true"]');
    await input.waitFor({ state: "visible", timeout: 3000 });
    await expectFocused(page, input, "new-note input is focused");
    // Cancel for cleanup.
    await page.keyboard.press("Escape");
    await page.waitForTimeout(200);
  });

  await runTest("right-click Rename input gets focus immediately", async () => {
    const row = page.locator(".group").filter({ hasText: "alpha" }).first();
    await row.click({ button: "right" });
    await page.getByRole("menuitem", { name: "Rename" }).click();
    const input = page.locator('input[data-rename-input="true"]');
    await input.waitFor({ state: "visible", timeout: 3000 });
    await expectFocused(page, input, "rename input is focused");
    await page.keyboard.press("Escape");
    await page.waitForTimeout(200);
  });

  await runTest(
    "real keystrokes type into new-note input + Enter commits exactly that text",
    async () => {
      await page.click('button[aria-label="New note"]');
      const input = page.locator('input[data-rename-input="true"]');
      await input.waitFor({ state: "visible", timeout: 3000 });
      await typeInto(page, input, "design");
      await page.keyboard.press("Enter");
      await page.waitForTimeout(800);
      assert(await hasRow(page, "design"), "row exists with the typed name");
      // Critical: NO other row should have been pulled into edit mode.
      const inputCount = await page.locator('input[data-rename-input="true"]').count();
      assert(inputCount === 0, `no rogue rename input survived (got ${inputCount})`);
    },
  );

  await runTest(
    "IME composition: Enter during candidate confirm does NOT submit",
    async () => {
      await page.click('button[aria-label="New note"]');
      const input = page.locator('input[data-rename-input="true"]');
      await input.waitFor({ state: "visible", timeout: 3000 });
      // Simulate user typing pinyin for 设计 — composition starts,
      // Enter confirms the candidate. Our input must treat that Enter
      // as IME-only and stay in edit mode.
      await simulateIMEComposition(page, input, "设计");
      // After composition end, user presses Enter for real.
      await page.waitForTimeout(150);
      // The input should still be in edit mode after the IME Enter —
      // verify by checking the input is still in the DOM AND focused.
      const stillEditing = await page
        .locator('input[data-rename-input="true"]')
        .count();
      assert(stillEditing === 1, "input still mounted after IME Enter");
      await expectFocused(page, input, "input still focused after IME Enter");
      // Now press Enter for real (no composition) to commit.
      await page.keyboard.press("Enter");
      await page.waitForTimeout(800);
      assert(await hasRow(page, "设计"), "Chinese title committed correctly");
    },
  );

  await runTest(
    "Enter inside input does NOT bubble to tree (no rogue edit elsewhere)",
    async () => {
      // Pre-condition: select a different row so arborist has a focused
      // node that, if it received an Enter, would enter edit mode.
      const labRow = page.locator(".group").filter({ hasText: "lab" }).first();
      await labRow.click();
      await page.waitForTimeout(100);

      await page.click('button[aria-label="New note"]');
      const input = page.locator('input[data-rename-input="true"]');
      await input.waitFor({ state: "visible", timeout: 3000 });
      await typeInto(page, input, "isolated");
      await page.keyboard.press("Enter");
      await page.waitForTimeout(800);
      assert(await hasRow(page, "isolated"), "new note created");
      const remainingInputs = await page
        .locator('input[data-rename-input="true"]')
        .count();
      assert(
        remainingInputs === 0,
        `Enter must not have bubbled to a sibling row (got ${remainingInputs} stray inputs)`,
      );
    },
  );

  await runTest("Esc cancels without committing", async () => {
    await page.click('button[aria-label="New note"]');
    const input = page.locator('input[data-rename-input="true"]');
    await input.waitFor({ state: "visible", timeout: 3000 });
    await typeInto(page, input, "phantom");
    await page.keyboard.press("Escape");
    await page.waitForTimeout(400);
    assert(!(await hasRow(page, "phantom")), "phantom row not in tree");
    const inputs = await page.locator('input[data-rename-input="true"]').count();
    assert(inputs === 0, "input dismissed");
  });

  if (env.errors.length > 0) {
    console.log("✗ no console errors");
    for (const e of env.errors) console.log("  ", e.type, e.text);
    process.exitCode = 1;
  } else {
    console.log("✓ no console errors");
  }
} finally {
  await teardown();
  exitAfter();
}
