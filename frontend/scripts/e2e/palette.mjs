// E2E: Cmd+P palette opens, fuzzy-matches, jumps.

import { assert, exitAfter, runTest, setupTestEnv } from "./_fixture.mjs";

const env = await setupTestEnv({
  notes: [
    { title: "alpha note", body: "alpha body" },
    { title: "beta thing" },
    { title: "knowlet design", folder: "projects" },
  ],
  folders: ["projects"],
  language: "en",
});
const { page, baseURL, teardown } = env;

try {
  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);

  await runTest("Cmd+P opens palette and lists notes", async () => {
    await page.keyboard.press("Meta+P");
    await page.waitForTimeout(300);
    const input = page.locator('[cmdk-input], input[placeholder*="title" i]').first();
    await input.waitFor({ state: "visible", timeout: 3000 });
    // After typing "knowlet", only "knowlet design" should match.
    await input.fill("knowlet");
    await page.waitForTimeout(200);
    const items = await page
      .locator('[cmdk-item], [role="option"]')
      .allInnerTexts();
    assert(
      items.some((t) => /knowlet design/i.test(t)),
      "knowlet design row visible",
    );
    assert(
      !items.some((t) => /beta thing/i.test(t)),
      "beta thing filtered out",
    );
    // Press Enter to jump
    await page.keyboard.press("Enter");
    await page.waitForTimeout(500);
    // Right pane is now the CodeMirror editor — locate by the wrapping
    // testid added in Phase 1 B and read the editor content via .cm-content.
    const editor = page.locator('[data-testid="markdown-editor"] .cm-content');
    await editor.waitFor({ state: "visible", timeout: 3000 });
    const body = (await editor.textContent()) ?? "";
    assert(
      body.length > 0,
      `right pane shows editor with note content — got "${body.slice(0, 60)}"`,
    );
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
