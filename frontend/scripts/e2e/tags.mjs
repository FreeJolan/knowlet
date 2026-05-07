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

  // ------------------------------------------------ Polish B: Tag chip strip

  async function clickFileTreeNote(title) {
    await page.locator('[data-testid="left-tab-files"]').click();
    await page.waitForTimeout(150);
    const escaped = title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const row = page
      .locator(".group")
      .filter({ hasText: new RegExp(`^${escaped}$`) })
      .first();
    await row.click();
    await page.waitForTimeout(300);
  }

  await runTest("Tag chip strip renders existing tags below title", async () => {
    await clickFileTreeNote("Note A");
    const strip = page.locator('[data-testid="tag-strip"]');
    await strip.waitFor({ state: "visible", timeout: 2000 });
    const chipCount = await strip.locator('[data-testid="tag-chip"]').count();
    assert(chipCount === 2, `Note A has 2 tags — got ${chipCount} chips`);
    // + tag button is also present.
    await strip.locator('[data-testid="tag-add-button"]').waitFor({
      state: "visible",
      timeout: 1000,
    });
  });

  await runTest("Adding a tag via chip strip updates frontmatter + tag list", async () => {
    await clickFileTreeNote("Note D");
    // Note D has no tags.
    const strip = page.locator('[data-testid="tag-strip"]');
    await strip.waitFor({ state: "visible", timeout: 2000 });
    const before = await strip.locator('[data-testid="tag-chip"]').count();
    assert(before === 0, `Note D should start with 0 tags — got ${before}`);
    await strip.locator('[data-testid="tag-add-button"]').click();
    await page.waitForTimeout(150);
    await page.locator('[data-testid="tag-add-input"]').fill("freshly-added");
    await page.keyboard.press("Enter");
    await page.waitForTimeout(900); // backend save + reindex
    const after = await strip.locator('[data-testid="tag-chip"]').count();
    assert(after === 1, `tag should be added — strip has ${after} chips`);
    // Switch to Tags tab — the new tag should appear in the global list.
    await page.locator('[data-testid="left-tab-tags"]').click();
    await page.waitForTimeout(400);
    const newRow = page.locator('[data-testid="tag-row"][data-tag="freshly-added"]');
    await newRow.waitFor({ state: "visible", timeout: 3000 });
  });

  await runTest("Removing a tag via × disappears from strip + tag list", async () => {
    await clickFileTreeNote("Note A");
    const strip = page.locator('[data-testid="tag-strip"]');
    await strip.waitFor({ state: "visible" });
    const remove = strip
      .locator('[data-testid="tag-chip-remove"][data-tag="shared"]')
      .first();
    await remove.click();
    await page.waitForTimeout(700);
    const stillThere = await strip
      .locator('[data-testid="tag-chip"][data-tag="shared"]')
      .count();
    assert(stillThere === 0, "shared chip should be removed from strip");
    // Note A had two tags (topic-x, shared). After removal it should still
    // have topic-x and lose shared. Note C has shared too, so the global
    // tag list should still contain shared (count drops from 2 to 1).
    await page.locator('[data-testid="left-tab-tags"]').click();
    await page.waitForTimeout(400);
    const sharedRow = page.locator('[data-testid="tag-row"][data-tag="shared"]');
    const sharedCount = await sharedRow.count();
    assert(sharedCount === 1, `shared still has Note C; expected 1 row got ${sharedCount}`);
  });

  // ------------------------------------------------ Polish C: inline #tag

  await runTest("inline #tag in body extracts to frontmatter on save", async () => {
    await clickFileTreeNote("Note D");
    // Type into the editor: navigate to body and add `#mood-test-tag`.
    // Easier: use the API directly to simulate body-with-tag save.
    const noteId = await page.evaluate(async () => {
      const r = await fetch("/api/tree");
      const tree = await r.json();
      const findD = (f) => {
        for (const n of f.notes) if (n.title === "Note D") return n.id;
        for (const sub of f.folders) {
          const id = findD(sub);
          if (id) return id;
        }
        return null;
      };
      return findD(tree);
    });
    const ok = await page.evaluate(
      async ([id]) => {
        const r = await fetch(`/api/notes/${id}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            title: "Note D",
            tags: [],
            body: "writing about #mood-test-tag here",
          }),
        });
        return r.ok;
      },
      [noteId],
    );
    assert(ok, "PUT with inline #tag should succeed");
    const apiTags = await page.evaluate(async () => {
      const r = await fetch("/api/tags");
      return r.json();
    });
    const has = apiTags.some((t) => t.tag === "mood-test-tag");
    assert(has, `inline tag should appear in /api/tags — got ${JSON.stringify(apiTags)}`);
  });

  await runTest("inline #tag renders as chip in preview", async () => {
    // Reload to get the body change picked up by the preview.
    await page.reload();
    await page.waitForTimeout(500);
    await clickFileTreeNote("Note D");
    await page.waitForTimeout(300);
    // Switch to preview mode where remarkInlineTag renders.
    await page.locator('button[data-mode="preview"]').click();
    await page.waitForTimeout(400);
    const chip = page
      .locator('[data-testid="markdown-preview"] a.kn-inline-tag')
      .first();
    await chip.waitFor({ state: "visible", timeout: 3000 });
    const text = (await chip.textContent()) ?? "";
    assert(text === "#mood-test-tag", `chip text should be "#mood-test-tag" — got "${text}"`);
  });

  await runTest("clicking inline #tag opens Tags tab and drills in", async () => {
    await clickFileTreeNote("Note D");
    await page.locator('button[data-mode="preview"]').click();
    await page.waitForTimeout(400);
    const chip = page
      .locator('[data-testid="markdown-preview"] a.kn-inline-tag')
      .first();
    await chip.click();
    await page.waitForTimeout(500);
    // Should now be on the Tags tab + drilled into mood-test-tag detail.
    const detailHeader = page.locator('[data-testid="tag-detail-back"]');
    await detailHeader.waitFor({ state: "visible", timeout: 3000 });
    const list = page.locator('[data-testid="tag-notes-list"]');
    await list.waitFor({ state: "visible", timeout: 2000 });
    const noteCount = await list.locator('[data-testid="tag-note-row"]').count();
    assert(noteCount >= 1, `expected ≥1 note for mood-test-tag — got ${noteCount}`);
  });

  await runTest("Autocomplete suggests existing tags", async () => {
    await clickFileTreeNote("Note D");
    await page
      .locator('[data-testid="tag-strip"] [data-testid="tag-add-button"]')
      .click();
    await page.waitForTimeout(150);
    const input = page.locator('[data-testid="tag-add-input"]');
    await input.fill("topic");
    await page.waitForTimeout(300);
    const suggestions = page.locator('[data-testid="tag-suggestion"]');
    const count = await suggestions.count();
    assert(count >= 1, `expected ≥1 'topic*' suggestion — got ${count}`);
    // Click the first → commits + closes input.
    await suggestions.first().click();
    await page.waitForTimeout(700);
    const chip = page
      .locator('[data-testid="tag-strip"] [data-testid="tag-chip"]')
      .first();
    await chip.waitFor({ state: "visible", timeout: 2000 });
  });

  await teardown();
  exitAfter(0);
} catch (e) {
  console.error("tags e2e failed:", e);
  await teardown();
  exitAfter(1);
}
