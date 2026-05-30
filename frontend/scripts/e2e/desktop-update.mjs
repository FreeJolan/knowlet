// E2E: desktop update UX is visible in Settings but hidden from plain web.

import {
  assert,
  assertConsoleClean,
  exitAfter,
  runTest,
  setupTestEnv,
} from "./_fixture.mjs";

const env = await setupTestEnv({
  notes: [{ title: "Release note", body: "Desktop update smoke test." }],
  language: "zh",
});
const { page, baseURL, teardown } = env;

try {
  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);

  await runTest("web runtime does not show header update button", async () => {
    const count = await page
      .locator('[data-testid="header-desktop-update-button"]')
      .count();
    assert(count === 0, `header update button hidden in browser — got ${count}`);
  });

  await runTest("Settings exposes Desktop update panel", async () => {
    await page.locator('[data-testid="header-settings-button"]').click();
    await page
      .locator('[data-testid="settings-dialog"]')
      .waitFor({ state: "visible", timeout: 3000 });
    await page.locator('[data-testid="settings-tab-desktop"]').click();

    const panel = page.locator('[data-testid="settings-desktop-update-panel"]');
    await panel.waitFor({ state: "visible", timeout: 3000 });
    const text = await panel.textContent();
    assert(
      text?.includes("仅桌面端支持自动更新"),
      `unsupported runtime hint visible — got ${JSON.stringify(text)}`,
    );
  });

  await runTest("update dialog opens with disabled browser actions", async () => {
    await page.locator('[data-testid="settings-open-update-dialog"]').click();
    const dialog = page.locator('[data-testid="desktop-update-dialog"]');
    await dialog.waitFor({ state: "visible", timeout: 3000 });
    const text = await dialog.textContent();
    assert(
      text?.includes("仅桌面端支持自动更新"),
      `dialog explains unsupported runtime — got ${JSON.stringify(text)}`,
    );
    assert(
      !(await page.locator('[data-testid="desktop-update-check"]').isEnabled()),
      "manual check disabled outside desktop runtime",
    );
    assert(
      !(await page.locator('[data-testid="desktop-update-install"]').isEnabled()),
      "install disabled outside desktop runtime",
    );
  });

  assertConsoleClean(env);
  console.log("✓ no console errors");
} finally {
  await teardown();
  exitAfter();
}
