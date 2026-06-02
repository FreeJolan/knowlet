// E2E: AI chat composer sizing, long-form mode, and Markdown-friendly input.

import { assert, assertConsoleClean, exitAfter, runTest, setupTestEnv } from "./_fixture.mjs";

const env = await setupTestEnv({
  notes: [
    {
      title: "Composer Note",
      body: "A note used to exercise the discussion composer.",
    },
  ],
  folders: [],
  language: "en",
});
const { page, teardown } = env;

async function openDiscussPane() {
  await page.goto(env.baseURL, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);
  await page
    .locator(".group")
    .filter({ hasText: "Composer Note" })
    .first()
    .click();
  await page.locator('[data-testid="header-discuss-button"]').click();
  await page
    .locator('[data-testid="discuss-pane"]')
    .waitFor({ state: "visible", timeout: 3000 });
}

try {
  await openDiscussPane();

  await runTest("composer defaults to a roomier height", async () => {
    const height = await page
      .locator('[data-testid="discuss-input"]')
      .evaluate((el) => el.getBoundingClientRect().height);
    assert(height >= 92, `composer input should default to a roomier height, got ${height}`);
  });

  await runTest("normal composer continues ordered Markdown lists on Enter", async () => {
    const input = page.locator('[data-testid="discuss-input"]');
    await input.fill("1. first\n2. second\n3. third");
    await input.click();
    await page.keyboard.press("Enter");
    const value = await input.inputValue();
    assert(
      value === "1. first\n2. second\n3. third\n4. ",
      `Enter at the end of an ordered list should continue numbering, got ${JSON.stringify(value)}`,
    );
  });

  await runTest("composer height can be increased by dragging the resize handle", async () => {
    const shell = page.locator('[data-testid="discuss-composer-shell"]');
    const handle = page.locator('[data-testid="discuss-composer-resize-handle"]');
    const before = await shell.evaluate((el) => el.getBoundingClientRect().height);
    const box = await handle.boundingBox();
    assert(box, "resize handle should have a bounding box");
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width / 2, box.y - 80, { steps: 6 });
    await page.mouse.up();
    const after = await shell.evaluate((el) => el.getBoundingClientRect().height);
    assert(after >= before + 50, `dragging up should increase composer height: ${before} -> ${after}`);
  });

  await runTest("long-form popout preserves text and treats Enter as newline", async () => {
    const input = page.locator('[data-testid="discuss-input"]');
    await input.fill("1. one");
    await page.locator('[data-testid="discuss-longform-open"]').click();
    const dialog = page.locator('[data-testid="discuss-longform-dialog"]');
    await dialog.waitFor({ state: "visible", timeout: 3000 });
    const longInput = page.locator('[data-testid="discuss-longform-input"]');
    await longInput.click();
    await page.keyboard.press("Enter");
    let value = await longInput.inputValue();
    assert(value === "1. one\n2. ", `long-form Enter should continue the list, got ${JSON.stringify(value)}`);
    await page.keyboard.type("two");
    await page.keyboard.press("Enter");
    value = await longInput.inputValue();
    assert(
      value === "1. one\n2. two\n3. ",
      `long-form should keep Markdown continuation without sending, got ${JSON.stringify(value)}`,
    );
    assert(
      (await page.locator('[data-testid="discuss-message-user"]').count()) === 0,
      "pressing Enter in long-form mode should not send a message",
    );
    await page.keyboard.press("Escape");
    await dialog.waitFor({ state: "hidden", timeout: 3000 });
    const smallValue = await input.inputValue();
    assert(
      smallValue === "1. one\n2. two\n3. ",
      `closing long-form should copy text back to the compact input, got ${JSON.stringify(smallValue)}`,
    );
  });

  await runTest("clicking outside the long-form popout closes and keeps edits", async () => {
    await page.locator('[data-testid="discuss-longform-open"]').click();
    await page
      .locator('[data-testid="discuss-longform-input"]')
      .fill("outside close\nkeeps content");
    await page.mouse.click(20, 20);
    await page
      .locator('[data-testid="discuss-longform-dialog"]')
      .waitFor({ state: "hidden", timeout: 3000 });
    const value = await page.locator('[data-testid="discuss-input"]').inputValue();
    assert(
      value === "outside close\nkeeps content",
      `outside click should preserve long-form edits, got ${JSON.stringify(value)}`,
    );
  });

  await runTest("no unexpected console errors", () => {
    assertConsoleClean(env);
  });
} finally {
  await teardown();
}

exitAfter();
