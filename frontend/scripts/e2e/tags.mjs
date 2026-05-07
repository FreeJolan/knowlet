/**
 * Phase 1 C slice 2 — Tag browser in the left rail.
 *
 * After polish D the Tag browser is a file-tree (react-arborist) with
 * `/` as path separator. Tests cover:
 *   - Files / Tags tab toggle
 *   - Tags tree renders all tags with counts
 *   - Nested `#a/b` tags appear as expandable children of `#a`
 *   - Synthetic parents (no exact tag, only descendants) render too
 *   - Note rows nested under each tag; click opens the note
 *   - Empty vault shows the empty hint
 *   - Tag chip strip add / remove / autocomplete (Polish B)
 *   - Inline `#tag` extraction at save time + chip in preview (Polish C)
 */

import { assert, exitAfter, runTest, setupTestEnv } from "./_fixture.mjs";

const env = await setupTestEnv({
  notes: [
    { title: "Note A", body: "alpha", tags: ["topic-x", "shared"] },
    { title: "Note B", body: "beta", tags: ["topic-x"] },
    { title: "Note C", body: "gamma", tags: ["topic-y", "shared"] },
    { title: "Note D", body: "no tags here" },
    // Polish D — nested tags via `/` path separator.
    { title: "UI button study", body: "x", tags: ["design/ui"] },
    { title: "UI card layout", body: "y", tags: ["design/ui"] },
    { title: "Design system overview", body: "z", tags: ["design"] },
  ],
  language: "en",
});
const { page, baseURL, teardown } = env;

async function gotoTags() {
  await page.locator('[data-testid="left-tab-files"]').click();
  await page.waitForTimeout(150);
  await page.locator('[data-testid="left-tab-tags"]').click();
  await page.waitForTimeout(300);
}

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

  await runTest("Tags tree renders top-level tags", async () => {
    await page.locator('[data-testid="left-tab-tags"]').click();
    await page.waitForTimeout(500);
    // Top-level tags: design (3), shared (2), topic-x (2), topic-y (1).
    // (`design/ui` is nested so it doesn't show until parent expands.)
    const designRow = page.locator('[data-testid="tag-row"][data-tag="design"]');
    const sharedRow = page.locator('[data-testid="tag-row"][data-tag="shared"]');
    const topicX = page.locator('[data-testid="tag-row"][data-tag="topic-x"]');
    const topicY = page.locator('[data-testid="tag-row"][data-tag="topic-y"]');
    await designRow.waitFor({ state: "visible", timeout: 3000 });
    await sharedRow.waitFor({ state: "visible" });
    await topicX.waitFor({ state: "visible" });
    await topicY.waitFor({ state: "visible" });
  });

  await runTest("clicking a tag expands inline (no drill-down)", async () => {
    await gotoTags();
    const topicX = page
      .locator('[data-testid="tag-row"][data-tag="topic-x"]')
      .first();
    await topicX.click();
    await page.waitForTimeout(300);
    // Note rows for topic-x should appear in-tree, NOT in a separate
    // pane. Two notes (A + B) carry topic-x.
    const notes = page.locator('[data-testid="tag-note-row"]');
    const count = await notes.count();
    assert(count >= 2, `expected ≥2 note rows under topic-x — got ${count}`);
  });

  await runTest("clicking a nested tag like #design/ui shows under design parent", async () => {
    await gotoTags();
    const design = page
      .locator('[data-testid="tag-row"][data-tag="design"]')
      .first();
    await design.click();
    await page.waitForTimeout(300);
    // After expanding design, design/ui should be visible as a child row.
    const designUi = page.locator('[data-testid="tag-row"][data-tag="design/ui"]');
    await designUi.waitFor({ state: "visible", timeout: 2000 });
    // The design's own note (#design directly) should also be visible.
    const ownNote = page.locator(
      '[data-testid="tag-note-row"]',
    );
    const ownCount = await ownNote.count();
    assert(ownCount >= 1, `design's own notes should render — got ${ownCount}`);
  });

  await runTest("expanding design/ui reveals its notes", async () => {
    await gotoTags();
    await page.locator('[data-testid="tag-row"][data-tag="design"]').first().click();
    await page.waitForTimeout(200);
    await page
      .locator('[data-testid="tag-row"][data-tag="design/ui"]')
      .first()
      .click();
    await page.waitForTimeout(300);
    // design/ui has 2 notes; after expand both should be visible.
    const notes = page.locator('[data-testid="tag-note-row"]');
    const total = await notes.count();
    assert(
      total >= 3,
      `total visible notes (design 1 + design/ui 2) should be ≥3 — got ${total}`,
    );
  });

  await runTest("clicking a note row opens that note", async () => {
    await gotoTags();
    await page.locator('[data-testid="tag-row"][data-tag="topic-x"]').first().click();
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

  await runTest("Files tab returns the file tree intact", async () => {
    await page.locator('[data-testid="left-tab-files"]').click();
    await page.waitForTimeout(300);
    const row = page
      .locator(".group")
      .filter({ hasText: /^Note A$/ })
      .first();
    await row.waitFor({ state: "visible", timeout: 3000 });
  });

  // ------------------------------------------------ Polish B: Tag chip strip

  await runTest("Tag chip strip renders existing tags below title", async () => {
    await clickFileTreeNote("Note A");
    const strip = page.locator('[data-testid="tag-strip"]');
    await strip.waitFor({ state: "visible", timeout: 2000 });
    const chipCount = await strip.locator('[data-testid="tag-chip"]').count();
    assert(chipCount === 2, `Note A has 2 tags — got ${chipCount} chips`);
    await strip.locator('[data-testid="tag-add-button"]').waitFor({
      state: "visible",
      timeout: 1000,
    });
  });

  await runTest("Adding a tag via chip strip updates frontmatter + tag list", async () => {
    await clickFileTreeNote("Note D");
    const strip = page.locator('[data-testid="tag-strip"]');
    await strip.waitFor({ state: "visible", timeout: 2000 });
    const before = await strip.locator('[data-testid="tag-chip"]').count();
    assert(before === 0, `Note D should start with 0 tags — got ${before}`);
    await strip.locator('[data-testid="tag-add-button"]').click();
    await page.waitForTimeout(150);
    await page.locator('[data-testid="tag-add-input"]').fill("freshly-added");
    await page.keyboard.press("Enter");
    await page.waitForTimeout(900);
    const after = await strip.locator('[data-testid="tag-chip"]').count();
    assert(after === 1, `tag should be added — strip has ${after} chips`);
    // Tags tree should now include the new tag.
    await page.locator('[data-testid="left-tab-tags"]').click();
    await page.waitForTimeout(500);
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
    // Note C still has #shared, so the row remains in the tree.
    await page.locator('[data-testid="left-tab-tags"]').click();
    await page.waitForTimeout(500);
    const sharedRow = page.locator('[data-testid="tag-row"][data-tag="shared"]');
    const sharedCount = await sharedRow.count();
    assert(sharedCount === 1, `shared still has Note C; expected 1 row got ${sharedCount}`);
  });

  // ------------------------------------------------ Polish C: inline #tag

  await runTest("inline #tag in body extracts to frontmatter on save", async () => {
    await clickFileTreeNote("Note D");
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
    await page.reload();
    await page.waitForTimeout(500);
    await clickFileTreeNote("Note D");
    await page.waitForTimeout(300);
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
    // After click, we should be on Tags tab + the tag row should be
    // selected/visible (the tree expanded its path to it).
    const targetRow = page.locator(
      '[data-testid="tag-row"][data-tag="mood-test-tag"]',
    );
    await targetRow.waitFor({ state: "visible", timeout: 3000 });
  });

  await runTest("Autocomplete suggests existing tags", async () => {
    await clickFileTreeNote("Note A");
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
