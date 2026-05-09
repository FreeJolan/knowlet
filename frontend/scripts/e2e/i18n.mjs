// E2E: backend language drives the UI strings.

import { exitAfter, runTest, setupTestEnv } from "./_fixture.mjs";

async function checkLanguage(language, expectedHeading, expectedMenuItem) {
  const env = await setupTestEnv({
    notes: [{ title: "x" }],
    folders: ["lab"],
    language,
  });
  const { page, baseURL, teardown } = env;
  try {
    await page.goto(baseURL, { waitUntil: "networkidle" });
    await page.waitForTimeout(800);

    await runTest(`heading reads ${JSON.stringify(expectedHeading)} for ${language}`, async () => {
      const heading = (
        await page.locator('[data-testid="file-tree-heading"]').first().textContent()
      )?.trim();
      if (heading !== expectedHeading) {
        throw new Error(`expected ${expectedHeading}, got ${heading}`);
      }
    });

    await runTest(`right-click menu reads ${JSON.stringify(expectedMenuItem)} for ${language}`, async () => {
      // Right-click any row → check Rename label
      const row = page.locator(".group").filter({ hasText: "x" }).first();
      await row.click({ button: "right" });
      await page.waitForTimeout(200);
      const items = await page.locator('[role="menuitem"]').allInnerTexts();
      if (!items.some((t) => t.trim() === expectedMenuItem)) {
        throw new Error(
          `expected menu item ${expectedMenuItem}; got ${JSON.stringify(items)}`,
        );
      }
      await page.keyboard.press("Escape");
    });

    if (env.errors.length > 0) {
      console.log(`✗ no console errors (${language})`);
      for (const e of env.errors) console.log("  ", e.type, e.text);
      process.exitCode = 1;
    }
  } finally {
    await teardown();
  }
}

await checkLanguage("en", "Vault", "Rename");
await checkLanguage("zh", "笔记库", "重命名");
exitAfter();
