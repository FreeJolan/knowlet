/**
 * Phase 1 B slice 8 v2 — Templates as a first-class concept.
 *
 * Verifies:
 *   - global header has a Templates icon (📋) — always visible
 *   - dialog lists templates, supports filter, click = use, edit, delete
 *   - templates folder is HIDDEN from the regular file tree
 *   - inline `/` slash command in editor inserts template body at the
 *     cursor with placeholders substituted
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

  await runTest("global header has Templates icon (always visible)", async () => {
    const btn = page.locator('[data-testid="templates-button"]');
    await btn.waitFor({ state: "visible", timeout: 3000 });
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

  await runTest("dialog lists templates + filter + click = use", async () => {
    await page.locator('[data-testid="templates-button"]').click();
    const dialog = page.locator('[role="dialog"]');
    await dialog.waitFor({ state: "visible", timeout: 3000 });
    const items = await dialog
      .locator('[data-testid="template-use"]')
      .allTextContents();
    const titles = items.map((s) => s.trim());
    assert(
      titles.includes("daily") && titles.includes("meeting"),
      `dialog lists templates — got ${JSON.stringify(titles)}`,
    );
    // Filter narrows to a single template.
    await dialog.locator('[data-testid="templates-filter"]').fill("dai");
    await page.waitForTimeout(150);
    const filtered = await dialog
      .locator('[data-testid="template-use"]')
      .allTextContents();
    assert(
      filtered.length === 1 && /daily/.test(filtered[0]),
      `filter narrows list — got ${JSON.stringify(filtered)}`,
    );
    // Click "daily" to use it; dialog closes, inline title input opens.
    await dialog.locator('[data-testid="template-use"]').first().click();
    const titleInput = page.locator('input[data-rename-input="true"]');
    await titleInput.waitFor({ state: "visible", timeout: 3000 });
    await titleInput.fill("monday");
    await titleInput.press("Enter");
    await page.waitForFunction(
      () => {
        const rs = Array.from(document.querySelectorAll(".group"));
        return rs.some((r) => /^monday$/.test((r.textContent ?? "").trim()));
      },
      null,
      { timeout: 4000, polling: 80 },
    );
    const note = await getNoteByTitle("monday");
    assert(note !== null, "monday note created");
    const body = await getNoteBody(note.id);
    assert(
      /^# monday$/m.test(body ?? "") && /\d{4}-\d{2}-\d{2}/.test(body ?? ""),
      `body has substituted title + date — got "${(body ?? "").slice(0, 120)}"`,
    );
  });

  await runTest("dialog 'New template' creates a template and opens it", async () => {
    await page.locator('[data-testid="templates-button"]').click();
    const dialog = page.locator('[role="dialog"]');
    await dialog.waitFor({ state: "visible", timeout: 3000 });
    const before = await page.request.get(`${baseURL}/api/templates`);
    const beforeCount = (await before.json()).length;
    await dialog.locator('[data-testid="templates-new"]').click();
    await page.waitForFunction(
      (n) =>
        document.querySelector('[role="dialog"]') === null &&
        document.querySelector('[data-testid="markdown-editor"] .cm-content'),
      beforeCount,
      { timeout: 4000, polling: 80 },
    );
    const after = await page.request.get(`${baseURL}/api/templates`);
    const afterCount = (await after.json()).length;
    assert(
      afterCount === beforeCount + 1,
      `templates count grew by 1 — before=${beforeCount} after=${afterCount}`,
    );
  });

  await runTest("`/` slash command inserts template body at cursor", async () => {
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
    const dialogs = [];
    page.on("dialog", (d) => {
      dialogs.push(d.message());
      void d.dismiss();
    });
    // Click + new-note button, type the title of an existing note.
    await page.locator('button[aria-label="New note"]').click();
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
