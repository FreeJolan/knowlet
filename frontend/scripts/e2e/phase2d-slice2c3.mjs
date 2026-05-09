/**
 * Phase 2 D Slice 2c.3 — Command palette prefix mode (VS Code style).
 *
 * Verifies:
 *   - ⌘P opens palette in files mode (notes only).
 *   - ⌘⇧P opens palette in commands mode (built-ins + quick actions).
 *   - Typing ">" in files mode switches to commands mode + strips the
 *     leading ">".
 *   - Backspace at empty input in commands mode returns to files.
 *   - A built-in command runs (toggle theme flips data-theme on <html>).
 *   - A quick action runs from commands mode (creates today-note).
 */

import { assert, exitAfter, runTest, setupTestEnv } from "./_fixture.mjs";

const env = await setupTestEnv({
  notes: [
    { title: "alpha", body: "x" },
    { title: "beta", body: "y" },
  ],
  language: "en",
});
const { page, baseURL, teardown } = env;

try {
  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);

  await runTest("⌘P opens palette in files mode (no commands group)", async () => {
    await page.keyboard.press("Meta+P");
    await page
      .locator('[data-testid="palette-input"]')
      .waitFor({ state: "visible", timeout: 3000 });
    // Mode pill should NOT exist in files mode.
    const pill = await page
      .locator('[data-testid="palette-mode-pill"]')
      .count();
    assert(pill === 0, `files mode must not show pill — got ${pill}`);
    // Notes group should render at least our seeded "alpha".
    const items = await page
      .locator('[cmdk-item], [role="option"]')
      .allInnerTexts();
    assert(
      items.some((t) => /alpha/i.test(t)),
      "alpha note row visible in files mode",
    );
    // Built-in commands must NOT leak into files mode.
    assert(
      !items.some((t) => /Toggle theme/i.test(t)),
      "files mode must not list built-in commands",
    );
    await page.keyboard.press("Escape");
    await page.waitForTimeout(200);
  });

  await runTest("⌘⇧P opens palette in commands mode", async () => {
    await page.keyboard.press("Meta+Shift+P");
    await page
      .locator('[data-testid="palette-mode-pill"]')
      .waitFor({ state: "visible", timeout: 2000 });
    // Wait for the seeded today-note quick action to appear — its
    // visibility is the proof that the actions query resolved.
    await page
      .locator('[data-testid="palette-action-item"]')
      .first()
      .waitFor({ state: "visible", timeout: 3000 });
    const items = await page
      .locator('[cmdk-item], [role="option"]')
      .allInnerTexts();
    assert(
      items.some((t) => /Toggle theme/i.test(t)),
      "commands mode lists built-in commands (Toggle theme)",
    );
    assert(
      items.some((t) => /今日笔记/.test(t)),
      "commands mode lists seeded quick action 今日笔记",
    );
    await page.keyboard.press("Escape");
    await page.waitForTimeout(200);
  });

  await runTest('Typing ">" in files mode switches to commands mode', async () => {
    await page.keyboard.press("Meta+P");
    await page
      .locator('[data-testid="palette-input"]')
      .waitFor({ state: "visible", timeout: 2000 });
    // Type ">"
    const input = page.locator('[data-testid="palette-input"]');
    await input.fill(">");
    await page.waitForTimeout(150);
    // Pill should appear (we're in commands mode now).
    await page
      .locator('[data-testid="palette-mode-pill"]')
      .waitFor({ state: "visible", timeout: 1000 });
    // Input should be empty (we stripped the ">").
    const val = await input.inputValue();
    assert(val === "", `leading > must be stripped, got "${val}"`);
    await page.keyboard.press("Escape");
    await page.waitForTimeout(200);
  });

  await runTest("Backspace at empty input returns to files mode", async () => {
    await page.keyboard.press("Meta+Shift+P");
    await page
      .locator('[data-testid="palette-mode-pill"]')
      .waitFor({ state: "visible", timeout: 2000 });
    // Make sure the input is focused before the Backspace; cmdk auto-
    // focuses on open but explicitly clicking removes any race.
    await page.locator('[data-testid="palette-input"]').click();
    await page.keyboard.press("Backspace");
    await page.waitForTimeout(250);
    const pill = await page
      .locator('[data-testid="palette-mode-pill"]')
      .count();
    assert(pill === 0, "after backspace, must be back in files mode");
    await page.keyboard.press("Escape");
    await page.waitForTimeout(200);
  });

  await runTest("Built-in 'Toggle theme' runs + persists preference", async () => {
    // The PREFERENCE (localStorage) is the deterministic signal. The
    // RESOLVED theme on <html> may or may not change visually — e.g.
    // cycling "system" → "light" looks identical when the OS pref
    // is already light. Preference always changes; assert on that.
    const before = await page.evaluate(
      () => window.localStorage.getItem("knowlet.theme.v1") ?? "system",
    );
    await page.keyboard.press("Meta+Shift+P");
    await page
      .locator('[data-testid="palette-input"]')
      .waitFor({ state: "visible", timeout: 2000 });
    const item = page.locator(
      '[data-testid="palette-command-item"][data-command-id="builtin.toggle-theme"]',
    );
    await item.waitFor({ state: "visible", timeout: 2000 });
    await item.click();
    await page.waitForTimeout(200);
    const after = await page.evaluate(
      () => window.localStorage.getItem("knowlet.theme.v1") ?? "system",
    );
    assert(
      before !== after,
      `theme preference should advance — was "${before}", now "${after}"`,
    );
  });

  await runTest("Quick action runs from commands mode (creates today's note)", async () => {
    await page.keyboard.press("Meta+Shift+P");
    await page
      .locator('[data-testid="palette-input"]')
      .waitFor({ state: "visible", timeout: 2000 });
    await page.locator('[data-testid="palette-input"]').fill("今日");
    await page.waitForTimeout(200);
    await page.keyboard.press("Enter");
    await page.waitForTimeout(700);
    // Tree should now contain a daily/ folder with today's note.
    const tree = await page.evaluate(async () =>
      (await fetch("/api/tree")).json(),
    );
    const daily = tree.folders.find((f) => f.name === "daily");
    assert(daily && (daily.notes ?? []).length >= 1, "daily/ note created");
  });

  await teardown();
  exitAfter(0);
} catch (e) {
  console.error("phase2d-slice2c3 e2e failed:", e);
  await teardown();
  exitAfter(1);
}
