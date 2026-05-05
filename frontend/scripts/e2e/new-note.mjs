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

  await runTest("toolbar 'New note' creates a root note + auto-selects", async () => {
    page.once("dialog", (d) => d.accept("toolbar-note"));
    await page.click('button[aria-label="New note"]');
    await page.waitForTimeout(800);
    assert(await hasRow(page, "toolbar-note"), "row appears in tree");
    // Auto-select means the right pane shows its title.
    const heading = (await page.locator("article header h1").textContent()) ?? "";
    assert(heading.includes("toolbar-note"), `right pane shows note — got "${heading}"`);
  });

  await runTest("right-click on folder → 'New note inside' creates child note", async () => {
    const lab = page.locator(".group").filter({ hasText: "lab" }).first();
    await lab.click({ button: "right" });
    page.once("dialog", (d) => d.accept("inside-lab"));
    await page.getByRole("menuitem", { name: "New note inside" }).click();
    await page.waitForTimeout(800);
    assert(await hasRow(page, "inside-lab"), "child note appears");
    // Verify it's truly under lab via API.
    const treeRes = await page.request.get(`${baseURL}/api/tree`);
    const tree = await treeRes.json();
    const labNode = tree.folders.find((f) => f.name === "lab");
    const found = labNode?.notes.some((n) => n.title === "inside-lab");
    assert(found, `note placed under lab; got ${JSON.stringify(labNode?.notes)}`);
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
