// E2E: drag-and-drop moves a note into a folder.

import { assert, exitAfter, hasRow, runTest, setupTestEnv } from "./_fixture.mjs";

const env = await setupTestEnv({
  notes: [{ title: "draggable" }],
  folders: ["target"],
  language: "en",
});
const { page, baseURL, teardown } = env;

try {
  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);

  await runTest("drag note into folder", async () => {
    const note = page.locator(".group").filter({ hasText: "draggable" }).first();
    const folder = page.locator(".group").filter({ hasText: "target" }).first();
    await note.dragTo(folder);
    await page.waitForTimeout(800);
    // Note should now be a child of `target` — verify via API for the
    // strongest signal (DOM may also still show it just rearranged).
    const treeRes = await page.request.get(`${baseURL}/api/tree`);
    const tree = await treeRes.json();
    const target = tree.folders.find((f) => f.name === "target");
    assert(target, "target folder still exists");
    const found = target.notes.some((n) => n.title === "draggable");
    assert(found, `note moved into target; got ${JSON.stringify(target.notes)}`);
    // Sanity in DOM too.
    assert(await hasRow(page, "draggable"), "row still rendered");
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
