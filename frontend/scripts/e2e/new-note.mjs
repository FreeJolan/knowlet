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
    await page.click('button[aria-label="New note"]');
    const input = page.locator('input[data-rename-input="true"]');
    await input.waitFor({ state: "visible", timeout: 3000 });
    await input.fill("toolbar-note");
    await input.press("Enter");
    await page.waitForTimeout(800);
    assert(await hasRow(page, "toolbar-note"), "row appears in tree");
    const heading = (await page.locator("article header h1").textContent()) ?? "";
    assert(heading.includes("toolbar-note"), `right pane shows note — got "${heading}"`);
  });

  await runTest("Esc on inline new-note cancels (no row created)", async () => {
    await page.click('button[aria-label="New note"]');
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

  await runTest("right-click 'New note inside' inline-creates under folder", async () => {
    const lab = page.locator(".group").filter({ hasText: "lab" }).first();
    await lab.click({ button: "right" });
    await page.getByRole("menuitem", { name: "New note inside" }).click();
    const input = page.locator('input[data-rename-input="true"]');
    await input.waitFor({ state: "visible", timeout: 3000 });
    await input.fill("inside-lab");
    await input.press("Enter");
    await page.waitForTimeout(800);
    assert(await hasRow(page, "inside-lab"), "child note appears");
    const treeRes = await page.request.get(`${baseURL}/api/tree`);
    const tree = await treeRes.json();
    const labNode = tree.folders.find((f) => f.name === "lab");
    const found = labNode?.notes.some((n) => n.title === "inside-lab");
    assert(found, `note placed under lab; got ${JSON.stringify(labNode?.notes)}`);
  });

  await runTest(".md suffix is stripped on commit", async () => {
    await page.click('button[aria-label="New note"]');
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
