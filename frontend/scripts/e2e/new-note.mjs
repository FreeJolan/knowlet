// E2E: new note creation via toolbar + via right-click on a folder.

import { assert, exitAfter, hasRow, runTest, setupTestEnv } from "./_fixture.mjs";

const env = await setupTestEnv({
  notes: [],
  folders: ["lab"],
  language: "en",
});
const { page, baseURL, teardown } = env;

try {
  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);

  await runTest("toolbar 'New note' opens inline input + Enter commits", async () => {
    await page.click('button[aria-label="New note"]', { modifiers: ['Shift'] });
    const input = page.locator('input[data-rename-input="true"]');
    await input.waitFor({ state: "visible", timeout: 3000 });
    await input.fill("toolbar-note");
    await input.press("Enter");
    await page.waitForTimeout(800);
    assert(await hasRow(page, "toolbar-note"), "row appears in tree");
    // Phase 1 B: right pane is the editor, no <article>. Title now lives
    // in the kn-paper header > h1.
    const heading = (await page.locator(".kn-paper header h1").textContent()) ?? "";
    assert(heading.includes("toolbar-note"), `right pane shows note — got "${heading}"`);
  });

  await runTest("Esc on inline new-note cancels (no row created)", async () => {
    await page.click('button[aria-label="New note"]', { modifiers: ['Shift'] });
    const input = page.locator('input[data-rename-input="true"]');
    await input.waitFor({ state: "visible", timeout: 3000 });
    await input.fill("ghost");
    await input.press("Escape");
    await page.waitForTimeout(400);
    assert(!(await hasRow(page, "ghost")), "ghost row not present");
  });

  await runTest("toolbar 'New folder' inline create works", async () => {
    await page.click('button[aria-label="New folder"]');
    const input = page.locator('input[data-rename-input="true"]');
    await input.waitFor({ state: "visible", timeout: 3000 });
    await input.fill("inbox");
    await input.press("Enter");
    await page.waitForTimeout(800);
    assert(await hasRow(page, "inbox"), "inbox folder appears");
  });

  // Phase 2 D Slice 2 (2026-05-09): right-click "New note inside"
  // now opens NewDocDialog instead of inline-creating. The new
  // coverage lives in phase2d-slice2a.mjs#"Right-click folder → New
  // note inside opens dialog with seed". Removed here.

  await runTest(".md suffix is stripped on commit", async () => {
    await page.click('button[aria-label="New note"]', { modifiers: ['Shift'] });
    const input = page.locator('input[data-rename-input="true"]');
    await input.waitFor({ state: "visible", timeout: 3000 });
    await input.fill("design.md");
    await input.press("Enter");
    await page.waitForTimeout(800);
    assert(await hasRow(page, "design"), "stored as 'design' not 'design.md'");
    assert(!(await hasRow(page, "design.md")), "no '.md' suffix in title");
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
