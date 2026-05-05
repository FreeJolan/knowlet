// E2E: file ops — create folder, rename, delete, restore.

import { assert, exitAfter, expectRow, hasRow, runTest, setupTestEnv } from "./_fixture.mjs";

const env = await setupTestEnv({
  notes: [
    { title: "alpha", body: "first" },
    { title: "beta", body: "second", folder: "lab" },
  ],
  folders: ["lab", "lab/inner"],
  language: "en",
});
const { page, baseURL, teardown } = env;

try {
  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);

  await runTest("seeded notes + folders render", async () => {
    await expectRow(page, "alpha");
    await expectRow(page, "beta");
    await expectRow(page, "lab");
    await expectRow(page, "inner");
  });

  await runTest("new folder via toolbar +", async () => {
    page.once("dialog", (d) => d.accept("scratch"));
    await page.click('button[aria-label="New folder"]');
    await page.waitForTimeout(400);
    assert(await hasRow(page, "scratch"), "scratch folder appears in tree");
  });

  await runTest("new note via toolbar", async () => {
    page.once("dialog", (d) => d.accept("zeta"));
    await page.click('button[aria-label="New note"]');
    await page.waitForTimeout(500);
    assert(await hasRow(page, "zeta"), "zeta note appears in tree");
  });

  await runTest("rename via right-click menu (Enter to commit)", async () => {
    const row = await expectRow(page, "alpha");
    await row.click({ button: "right" });
    await page.getByRole("menuitem", { name: "Rename" }).click();
    const input = page.locator('input[data-rename-input="true"]');
    await input.waitFor({ state: "visible", timeout: 3000 });
    await input.fill("alpha-renamed");
    await input.press("Enter");
    await page.waitForTimeout(500);
    assert(await hasRow(page, "alpha-renamed"), "renamed row appears");
  });

  await runTest("delete via right-click → trash → restore", async () => {
    const row = await expectRow(page, "beta");
    await row.click({ button: "right" });
    page.once("dialog", (d) => d.accept());
    await page.locator('[role="menuitem"]', { hasText: "Delete" }).click();
    await page.waitForTimeout(500);
    assert(!(await hasRow(page, "beta")), "beta gone from tree");

    // Open trash dialog
    await page.click('button[aria-label="Trash"]');
    await page.waitForTimeout(400);
    const restoreBtn = page.locator("button", { hasText: "Restore" }).first();
    await restoreBtn.click();
    await page.waitForTimeout(500);
    // Close trash; tree should now contain beta again.
    await page.keyboard.press("Escape");
    await page.waitForTimeout(300);
    assert(await hasRow(page, "beta"), "beta restored");
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
