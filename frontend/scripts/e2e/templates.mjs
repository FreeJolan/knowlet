/**
 * Phase 2 D Slice 2c.2-A' — Templates as a left-rail tab.
 *
 * Replaces the old global header dialog (Phase 1 B slice 8 v2) with a
 * dedicated tab in the left rail (Files / Tags / Templates). Reasons
 * tracked in feedback_user_story_first.md — the dialog conflated
 * "manage templates" with "use a template" and the icon's intent
 * wasn't readable.
 *
 * Verifies:
 *   - Templates tab exists in left rail (next to Files / Tags)
 *   - Templates folder is HIDDEN from the regular Files tab
 *   - Tab shows _templates/ contents as the visible tree root
 *   - "+ Note" button creates a template inline under _templates/
 *   - inline `/` slash command in editor inserts template body at the
 *     cursor with placeholders substituted (unchanged)
 */

import { assert, exitAfter, runTest, setupTestEnv } from "./_fixture.mjs";

const env = await setupTestEnv({
  notes: [
    {
      title: "daily",
      body: "# {{title}}\n\n_started {{date}}_\n",
      folder: "_templates",
    },
    {
      title: "meeting",
      body: "# Meeting — {{title}}\nDate: {{date}}\n",
      folder: "_templates",
    },
    { title: "reading", body: "regular note" },
  ],
  folders: [],
  language: "en",
});
const { page, baseURL, teardown } = env;

async function getNoteByTitle(title) {
  const r = await page.request.get(`${baseURL}/api/tree`);
  const tree = await r.json();
  const flat = [];
  const walk = (node) => {
    for (const n of node.notes ?? []) flat.push(n);
    for (const f of node.folders ?? []) walk(f);
  };
  walk(tree);
  return flat.find((n) => n.title === title) ?? null;
}

async function getNoteBody(id) {
  const r = await page.request.get(
    `${baseURL}/api/notes/${encodeURIComponent(id)}`,
  );
  return r.ok() ? (await r.json()).body : null;
}

try {
  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);

  await runTest("Templates tab exists in left rail next to Files / Tags", async () => {
    await page
      .locator('[data-testid="left-tab-templates"]')
      .waitFor({ state: "visible", timeout: 3000 });
  });

  await runTest("templates folder is HIDDEN from the regular tree", async () => {
    // The vault has a `_templates/` folder seeded — but the file tree
    // must not surface it as a node. Users only meet "Templates" via
    // the global dialog; the on-disk name (with leading underscore)
    // stays opaque unless they peek in Finder.
    const rows = await page
      .locator(".group")
      .evaluateAll((els) => els.map((el) => (el.textContent ?? "").trim()));
    assert(
      !rows.includes("_templates") && !rows.includes("templates"),
      `templates folder not visible in tree — got rows ${JSON.stringify(rows)}`,
    );
    // The regular note "reading" still shows up.
    assert(rows.includes("reading"), "regular note still visible");
  });

  await runTest("Templates tab shows _templates/ contents as the visible tree", async () => {
    await page.locator('[data-testid="left-tab-templates"]').click();
    await page.waitForTimeout(300);
    // Seeded vault has 2 templates: daily + meeting. Both should be
    // visible at the top level of the templates view.
    const rows = await page
      .locator(".group")
      .evaluateAll((els) => els.map((el) => (el.textContent ?? "").trim()));
    assert(
      rows.includes("daily") && rows.includes("meeting"),
      `templates tab should list 'daily' + 'meeting' — got ${JSON.stringify(rows)}`,
    );
    // Regular note "reading" must NOT appear in templates tab.
    assert(
      !rows.includes("reading"),
      `templates tab should NOT show non-template notes — got ${JSON.stringify(rows)}`,
    );
  });

  await runTest("Click a template in tab opens it for editing in NoteView", async () => {
    const dailyRow = page
      .locator(".group")
      .filter({ hasText: /^daily$/ })
      .first();
    await dailyRow.click();
    await page.waitForTimeout(300);
    // Note title in main pane should reflect the template.
    const h1 = (await page.locator('[data-testid="note-title"]').first().textContent()) ?? "";
    assert(/daily/.test(h1), `NoteView should show daily template — got "${h1}"`);
  });

  await runTest("'+ Note' in Templates tab creates a template under _templates/", async () => {
    await page.locator('[data-testid="left-tab-templates"]').click();
    await page.waitForTimeout(200);
    // Use Shift+click to enter inline create (per Slice 2 — plain
    // click opens NewDocDialog, which doesn't apply for templates
    // creation flow).
    await page.click('button[aria-label="New note"]', { modifiers: ["Shift"] });
    const input = page.locator('input[data-rename-input="true"]');
    await input.waitFor({ state: "visible", timeout: 3000 });
    await input.fill("weekly");
    await input.press("Enter");
    await page.waitForTimeout(800);
    // The new template lands under _templates/.
    const r = await page.request.get(`${baseURL}/api/templates`);
    const titles = (await r.json()).map((t) => t.title);
    assert(
      titles.includes("weekly"),
      `'weekly' template created — got ${JSON.stringify(titles)}`,
    );
  });

  await runTest("`/` slash command inserts template body at cursor", async () => {
    // Switch back to Files tab — previous tests left us on Templates.
    await page.locator('[data-testid="left-tab-files"]').click();
    await page.waitForTimeout(200);
    // Open a regular note ("reading"), put cursor at end, type `/`,
    // pick "daily" — body should land in the editor with placeholders
    // substituted (note's own title goes into {{title}}).
    const reading = page
      .locator(".group")
      .filter({ hasText: /^reading$/ })
      .first();
    await reading.click();
    const cm = page.locator('[data-testid="markdown-editor"] .cm-content');
    await cm.click();
    await page.keyboard.press("Meta+End");
    await page.keyboard.press("Enter");
    await page.keyboard.type("/", { delay: 30 });
    const popup = page.locator(".cm-tooltip-autocomplete").first();
    await popup.waitFor({ state: "visible", timeout: 3000 });
    // Type to filter, then accept first suggestion.
    await page.keyboard.type("daily", { delay: 30 });
    await page.waitForTimeout(400);
    await page.keyboard.press("Enter");
    // Wait for the placeholder to be replaced with the real body.
    await page.waitForFunction(
      () => {
        const cmContent = document.querySelector(
          '[data-testid="markdown-editor"] .cm-content',
        );
        const text = cmContent?.textContent ?? "";
        return /# reading/.test(text) && /\d{4}-\d{2}-\d{2}/.test(text);
      },
      null,
      { timeout: 4000, polling: 80 },
    );
    // Wait for auto-save then read the persisted body.
    await page.waitForTimeout(1500);
    const note = await getNoteByTitle("reading");
    const body = await getNoteBody(note.id);
    assert(
      /# reading/.test(body ?? "") && /\d{4}-\d{2}-\d{2}/.test(body ?? ""),
      `slash insertion saved with substitution — got "${(body ?? "").slice(0, 200)}"`,
    );
  });

  await runTest(
    "creating folder named '_templates' from the UI is rejected",
    async () => {
      // Backend reserves `_templates/` as a system folder. The "+ folder"
      // button must surface that as a 400 — not silently create a
      // colliding regular folder that the tree then can't see (since
      // the tree hides anything called `_templates`).
      const r = await page.request.post(`${baseURL}/api/folders`, {
        data: { path: "_templates" },
      });
      assert(
        r.status() === 400,
        `POST /api/folders {path:_templates} returns 400 — got ${r.status()}`,
      );
      const body = await r.json();
      assert(
        /reserved|system/i.test(body.detail ?? ""),
        `error detail mentions reservation — got "${body.detail}"`,
      );
    },
  );

  await runTest("duplicate note title triggers a friendly alert", async () => {
    // Frontend pre-flights against the cached tree before calling the
    // backend, so the user gets feedback even when the backend would
    // happily accept (notes are ULID-keyed → would create a confusing
    // duplicate row in the tree).
    // Make sure we're in Files tab — duplicate-check is per-folder; we
    // want to collide with "reading" which lives at vault root.
    await page.locator('[data-testid="left-tab-files"]').click();
    await page.waitForTimeout(200);
    const dialogs = [];
    page.on("dialog", (d) => {
      dialogs.push(d.message());
      void d.dismiss();
    });
    // Click + new-note button, type the title of an existing note.
    await page.locator('button[aria-label="New note"]').click({ modifiers: ['Shift'] });
    const input = page.locator('input[data-rename-input="true"]');
    await input.waitFor({ state: "visible", timeout: 3000 });
    await input.fill("reading"); // already exists in seeded vault
    await input.press("Enter");
    await page.waitForTimeout(400);
    assert(
      dialogs.some((m) => /reading/.test(m) && /already/i.test(m)),
      `alert mentions duplicate — got ${JSON.stringify(dialogs)}`,
    );
    // Cancel the still-open inline create.
    await page.keyboard.press("Escape");
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
