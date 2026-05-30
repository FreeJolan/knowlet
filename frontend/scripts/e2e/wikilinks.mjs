/**
 * Phase 1 B slice 7 — Obsidian-style `[[Title]]` and `[[Title#Heading]]`
 * wiki-links: preview rendering, click navigation, heading anchor scroll,
 * and `[[ ` autocomplete in the CodeMirror editor.
 */

import { assert, exitAfter, runTest, setupTestEnv } from "./_fixture.mjs";

const env = await setupTestEnv({
  notes: [
    { title: "alpha", body: "See also [[beta]] and [[beta#Conclusion]]." },
    {
      // Long body so the `## Conclusion` heading is well below the
      // viewport's initial scroll position — that way the heading-anchor
      // click test actually verifies scroll-to-hash, not just "the
      // heading happens to be visible already".
      title: "beta",
      body: [
        "# Beta intro",
        "",
        ...Array.from({ length: 30 }, (_, i) => `Filler paragraph ${i + 1}.`),
        "",
        "## Conclusion",
        "",
        "End notes.",
      ].join("\n"),
    },
    { title: "gamma", body: "g" },
    { title: "garage", body: "g" },
  ],
  language: "en",
});
const { page, baseURL, teardown } = env;

async function clickRow(title) {
  const escaped = title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const row = page
    .locator(".group")
    .filter({ hasText: new RegExp(`^${escaped}$`) })
    .first();
  await row.waitFor({ state: "visible", timeout: 3000 });
  await row.click();
}

async function clickPreview() {
  await page.locator('button[data-mode="preview"]').click();
  await page.waitForTimeout(180);
}

async function clickEdit() {
  await page.locator('button[data-mode="edit"]').click();
  await page.waitForTimeout(180);
}

try {
  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);

  await runTest("wikilink renders as kn-wikilink anchor in preview", async () => {
    await clickRow("alpha");
    await clickPreview();
    const anchor = page
      .locator('[data-testid="markdown-preview"] a.kn-wikilink')
      .first();
    await anchor.waitFor({ state: "visible", timeout: 3000 });
    const count = await page
      .locator('[data-testid="markdown-preview"] a.kn-wikilink')
      .count();
    assert(count === 2, `two wiki-link anchors rendered — got ${count}`);
    const href = await anchor.getAttribute("href");
    assert(
      typeof href === "string" && href.startsWith("wikilink:"),
      `anchor href uses wikilink: scheme — got "${href}"`,
    );
  });

  await runTest("clicking [[Title]] switches to that note", async () => {
    await clickRow("alpha");
    await clickPreview();
    const anchor = page
      .locator('[data-testid="markdown-preview"] a.kn-wikilink')
      .filter({ hasText: /^beta$/ })
      .first();
    await anchor.click();
    // After dispatch + tree resolution, AppShell should swap noteId.
    // The header in the right pane shows the title — wait for "beta".
    await page.waitForFunction(
      () => {
        const h1 = document.querySelector(".kn-paper header h1");
        return h1 && /beta/i.test(h1.textContent ?? "") && !/alpha/i.test(h1.textContent ?? "");
      },
      null,
      { timeout: 3000, polling: 80 },
    );
    const heading = await page.locator(".kn-paper header h1").textContent();
    assert(
      /beta/i.test(heading ?? "") && !/alpha/i.test(heading ?? ""),
      `note swapped to beta — got header "${heading}"`,
    );
  });

  await runTest("clicking [[Title#Heading]] scrolls to the heading", async () => {
    // Re-seed by going back to alpha first.
    await clickRow("alpha");
    await clickPreview();
    // Sanity: before clicking the heading link, the `## Conclusion`
    // heading is well below the viewport (long body of filler paragraphs
    // pushes it out of view). If we don't sample this baseline, a doc
    // short enough for the heading to be visible already would let the
    // test pass even if scroll-to-hash were broken.
    const anchor = page
      .locator('[data-testid="markdown-preview"] a.kn-wikilink')
      .filter({ hasText: /Conclusion/ })
      .first();
    await anchor.click();
    // After navigation: look for the rehype-slug-generated `#conclusion`
    // (lowercased, hyphenated) and a scroll-into-view that lands the
    // heading at the TOP of the preview viewport.
    const targetId = "conclusion";
    await page.waitForFunction(
      (id) => document.querySelector(`#${id}`) !== null,
      targetId,
      { timeout: 3000, polling: 80 },
    );
    await page.waitForTimeout(500); // smooth scroll
    const headingBox = await page.locator(`#${targetId}`).boundingBox();
    const previewBox = await page
      .locator('[data-testid="markdown-preview"]')
      .boundingBox();
    if (!headingBox || !previewBox)
      throw new Error("missing bounding box for heading or preview");
    const offsetWithinPreview = headingBox.y - previewBox.y;
    // Heading should be within the top half of the preview viewport
    // (smooth scroll can leave ~50-200px depending on layout). With a
    // long body, this only succeeds if the scroll-to-hash code path
    // actually ran — broken slug lookup would leave the heading
    // hundreds of px down (or below the viewport entirely).
    assert(
      offsetWithinPreview >= 0 && offsetWithinPreview < previewBox.height * 0.7,
      `Conclusion heading scrolled near top of preview — offset=${offsetWithinPreview}px, viewport=${previewBox.height}px`,
    );
  });

  // Helper: place us in edit mode on alpha with a clean buffer + closed
  // autocomplete popup. Each autocomplete sub-test starts from a known
  // empty doc so prior typing can't bleed in via auto-save.
  async function freshEditorBuffer() {
    await clickRow("alpha");
    await clickEdit();
    const cm = page.locator('[data-testid="markdown-editor"] .cm-content');
    await cm.click();
    // Close any popup left over from a previous test, then clear.
    await page.keyboard.press("Escape");
    await page.keyboard.press("Meta+A");
    await page.keyboard.press("Delete");
    return cm;
  }

  await runTest("typing `[[` opens autocomplete with vault titles", async () => {
    const cm = await freshEditorBuffer();
    void cm;
    await page.keyboard.type("[[", { delay: 30 });
    // CM6 autocomplete renders a tooltip with `cm-tooltip-autocomplete`.
    const popup = page.locator(".cm-tooltip-autocomplete").first();
    await popup.waitFor({ state: "visible", timeout: 2500 });
    const items = await popup.locator("li, .cm-completionLabel").allInnerTexts();
    const flat = items.join(" ");
    assert(
      /alpha/.test(flat) && /beta/.test(flat) && /gamma/.test(flat),
      `popup lists vault titles — got "${flat.slice(0, 200)}"`,
    );
  });

  await runTest("typing `[[ga` filters to titles matching ga", async () => {
    await freshEditorBuffer();
    await page.keyboard.type("[[ga", { delay: 30 });
    const popup = page.locator(".cm-tooltip-autocomplete").first();
    await popup.waitFor({ state: "visible", timeout: 2500 });
    const items = await popup.locator("li, .cm-completionLabel").allInnerTexts();
    const flat = items.join(" ").toLowerCase();
    assert(
      /gamma/.test(flat) && /garage/.test(flat),
      `popup keeps matches — got "${flat.slice(0, 200)}"`,
    );
    assert(
      !/alpha/.test(flat) && !/beta/.test(flat),
      `popup drops non-matching titles — got "${flat.slice(0, 200)}"`,
    );
  });

  await runTest(
    "fuzzy autocomplete: subsequence query reaches non-prefix match",
    async () => {
      // Strict substring would reject "gma"; CM6's scorer accepts
      // subsequence matches at length 3+. This catches the dogfood
      // report that motivated switching from hand-rolled substring
      // filter → CM6 built-in fuzzy with relevance scoring.
      await freshEditorBuffer();
      await page.keyboard.type("[[gma", { delay: 30 });
      const popup = page.locator(".cm-tooltip-autocomplete").first();
      await popup.waitFor({ state: "visible", timeout: 2500 });
      const items = await popup
        .locator("li, .cm-completionLabel")
        .allInnerTexts();
      const flat = items.join(" ").toLowerCase();
      assert(
        /gamma/.test(flat),
        `popup includes 'gamma' for subsequence query 'gma' — got "${flat.slice(0, 200)}"`,
      );
    },
  );

  await runTest(
    "`[[Title#` opens heading autocomplete with target note's headings",
    async () => {
      const cm = await freshEditorBuffer();
      void cm;
      await page.keyboard.type("[[beta#", { delay: 30 });
      const popup = page.locator(".cm-tooltip-autocomplete").first();
      await popup.waitFor({ state: "visible", timeout: 3000 });
      await page.waitForTimeout(400);
      const items = await popup
        .locator("li, .cm-completionLabel")
        .allInnerTexts();
      const flat = items.join(" ");
      assert(
        /Beta intro/i.test(flat) && /Conclusion/i.test(flat),
        `popup lists target note's headings — got "${flat.slice(0, 200)}"`,
      );
    },
  );

  await runTest("Enter on heading completion inserts `Heading]]`", async () => {
    const cm = await freshEditorBuffer();
    await page.keyboard.type("[[beta#Conc", { delay: 30 });
    const popup = page.locator(".cm-tooltip-autocomplete").first();
    await popup.waitFor({ state: "visible", timeout: 3000 });
    await page.waitForTimeout(400);
    await page.keyboard.press("Enter");
    await page.waitForTimeout(400);
    const text = await cm.textContent();
    assert(
      /\[\[beta#Conclusion\]\]/.test(text ?? ""),
      `editor doc contains [[beta#Conclusion]] — got "${(text ?? "").slice(-80)}"`,
    );
  });

  await runTest(
    "backspace inside an existing wikilink re-opens autocomplete",
    async () => {
      const cm = await freshEditorBuffer();
      // Type a complete wikilink, dismiss the popup, then move cursor
      // back inside it and backspace one char — popup should re-open
      // because the cursor sits in the trigger zone again.
      await page.keyboard.type("[[gamma", { delay: 30 });
      // Wait for the popup to appear, then dismiss it.
      await page
        .locator(".cm-tooltip-autocomplete")
        .first()
        .waitFor({ state: "visible", timeout: 2500 });
      await page.keyboard.press("Escape");
      await page.waitForTimeout(150);
      // Confirm popup is closed.
      const closedCount = await page.locator(".cm-tooltip-autocomplete").count();
      assert(
        closedCount === 0,
        `popup dismissed before backspace — got ${closedCount}`,
      );
      // Now backspace once inside `[[gamma` (cursor is after "gamma").
      await page.keyboard.press("Backspace");
      // Popup should re-open within ~200ms (deferred via queueMicrotask).
      await page
        .locator(".cm-tooltip-autocomplete")
        .first()
        .waitFor({ state: "visible", timeout: 1500 });
      const reopenItems = await page
        .locator(".cm-tooltip-autocomplete li, .cm-tooltip-autocomplete .cm-completionLabel")
        .allInnerTexts();
      const flat = reopenItems.join(" ").toLowerCase();
      assert(
        /gamma/.test(flat) || /garage/.test(flat) || /alpha/.test(flat),
        `popup re-opened with vault titles — got "${flat.slice(0, 200)}"`,
      );
      void cm;
    },
  );

  await runTest("Enter on autocomplete inserts `Title]]` + cursor past brackets", async () => {
    const cm = await freshEditorBuffer();
    await page.keyboard.type("refer [[gam", { delay: 30 });
    const popup = page.locator(".cm-tooltip-autocomplete").first();
    await popup.waitFor({ state: "visible", timeout: 2500 });
    // CM6's autocomplete tooltip flips to "visible" the moment its DOM
    // mounts, before the option list is filtered + the first item is
    // selected. Without this wait, Enter sometimes fires before the
    // selection lands and the keystroke goes to closeBrackets instead.
    await page.waitForTimeout(400);
    await page.keyboard.press("Enter");
    await page.waitForTimeout(400);
    const text = await cm.textContent();
    assert(
      /\[\[gamma\]\]/.test(text ?? ""),
      `editor doc contains [[gamma]] after autocomplete commit — got "${(text ?? "").slice(-80)}"`,
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
