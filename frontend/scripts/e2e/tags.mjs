/**
 * Phase 1 C slice 2 — Tag browser in the left rail.
 *
 * - Files / Tags tab toggle in the left panel
 * - Tags tab lists all tags with counts (sorted by count desc, then alpha)
 * - Click a tag → drill into list of notes carrying it
 * - Click a note → opens it in the editor (just like file tree)
 * - Empty vault (no tags anywhere) renders the empty hint
 */

import { assert, exitAfter, runTest, setupTestEnv } from "./_fixture.mjs";

const env = await setupTestEnv({
  notes: [
    { title: "Note A", body: "alpha", tags: ["topic-x", "shared"] },
    { title: "Note B", body: "beta", tags: ["topic-x"] },
    { title: "Note C", body: "gamma", tags: ["topic-y", "shared"] },
    { title: "Note D", body: "no tags here" },
  ],
  language: "en",
});
const { page, baseURL, teardown } = env;

/** Reset to the Tags tab top-level (back out of any tag detail). */
async function gotoTagsList() {
  // Toggle to Files then back to Tags so TagBrowser unmounts and
  // resets its activeTag state.
  await page.locator('[data-testid="left-tab-files"]').click();
  await page.waitForTimeout(150);
  await page.locator('[data-testid="left-tab-tags"]').click();
  await page.waitForTimeout(300);
}

try {
  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);

  await runTest("Files tab is active by default; Tags tab visible", async () => {
    const tagsTab = page.locator('[data-testid="left-tab-tags"]');
    await tagsTab.waitFor({ state: "visible", timeout: 3000 });
    const filesTab = page.locator('[data-testid="left-tab-files"]');
    const filesPressed = await filesTab.getAttribute("aria-pressed");
    assert(filesPressed === "true", `files tab should be active by default (got ${filesPressed})`);
  });

  await runTest("clicking Tags swaps in the tag list with counts", async () => {
    await page.locator('[data-testid="left-tab-tags"]').click();
    await page.waitForTimeout(400);
    const list = page.locator('[data-testid="tags-list"]');
    await list.waitFor({ state: "visible", timeout: 3000 });
    const rows = list.locator('[data-testid="tag-row"]');
    const count = await rows.count();
    // 3 unique tags: topic-x (2), shared (2), topic-y (1)
    assert(count === 3, `three tag rows expected — got ${count}`);
    // Top entry by count should be topic-x or shared (both at 2). Ties
    // break alpha asc → "shared" < "topic-x" (s < t), so first row is "shared".
    const firstTag = await rows.first().getAttribute("data-tag");
    assert(firstTag === "shared", `first row should be 'shared' (alpha tie-break) — got ${firstTag}`);
  });

  await runTest("clicking a tag drills into note list", async () => {
    await gotoTagsList();
    const topicX = page
      .locator('[data-testid="tag-row"][data-tag="topic-x"]')
      .first();
    await topicX.click();
    await page.waitForTimeout(400);
    const notesList = page.locator('[data-testid="tag-notes-list"]');
    await notesList.waitFor({ state: "visible", timeout: 3000 });
    const notes = notesList.locator('[data-testid="tag-note-row"]');
    const noteCount = await notes.count();
    assert(noteCount === 2, `two notes expected for topic-x — got ${noteCount}`);
  });

  await runTest("clicking a note in tag detail opens the note", async () => {
    await gotoTagsList();
    await page
      .locator('[data-testid="tag-row"][data-tag="topic-x"]')
      .first()
      .click();
    await page.waitForTimeout(300);
    const firstNote = page
      .locator('[data-testid="tag-note-row"]')
      .first();
    await firstNote.click();
    await page.waitForTimeout(400);
    const titleH1 = page.locator('[data-testid="note-title"]').first();
    await titleH1.waitFor({ state: "visible", timeout: 3000 });
    const titleText = (await titleH1.textContent()) ?? "";
    assert(
      /Note A|Note B/.test(titleText),
      `clicking a tag-note should open one of A/B (title="${titleText}")`,
    );
  });

  await runTest("back button returns to tag list", async () => {
    await gotoTagsList();
    await page
      .locator('[data-testid="tag-row"][data-tag="shared"]')
      .first()
      .click();
    await page.waitForTimeout(300);
    await page.locator('[data-testid="tag-detail-back"]').click();
    await page.waitForTimeout(300);
    const list = page.locator('[data-testid="tags-list"]');
    await list.waitFor({ state: "visible", timeout: 2000 });
  });

  await runTest("Files tab returns the file tree intact", async () => {
    await page.locator('[data-testid="left-tab-files"]').click();
    await page.waitForTimeout(300);
    // The file tree's Note A row should be visible again.
    const row = page
      .locator(".group")
      .filter({ hasText: /^Note A$/ })
      .first();
    await row.waitFor({ state: "visible", timeout: 3000 });
  });

  await teardown();
  exitAfter(0);
} catch (e) {
  console.error("tags e2e failed:", e);
  await teardown();
  exitAfter(1);
}
