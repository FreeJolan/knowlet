/**
 * Phase 1 B slice 7 dogfood follow-up — click-to-edit the right-pane
 * note title (Notion / Bear / Typora convention).
 *
 * Verifies:
 *   - clicking the h1 swaps in an inline input pre-filled with the title
 *   - Enter commits via PUT /api/notes/{id} (file on disk + tree query)
 *   - Esc cancels with no rename
 *   - the file tree row reflects the new title (optimistic update)
 *   - empty / unchanged input is a no-op
 */

import { assert, exitAfter, runTest, setupTestEnv } from "./_fixture.mjs";

const env = await setupTestEnv({
  notes: [
    { title: "alpha", body: "alpha body" },
    { title: "beta", body: "beta body" },
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

try {
  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);

  await runTest("click on title swaps in an inline input", async () => {
    await clickRow("alpha");
    await page.locator('[data-testid="note-title"]').click();
    const input = page.locator('[data-testid="title-edit-input"]');
    await input.waitFor({ state: "visible", timeout: 2500 });
    // Input should be focused with the current title selected.
    const isFocused = await input.evaluate((el) => el === document.activeElement);
    assert(isFocused, "title input has focus");
    const value = await input.inputValue();
    assert(value === "alpha", `input pre-filled with current title — got "${value}"`);
  });

  await runTest(
    "title-edit blocks renaming to a sibling's existing title",
    async () => {
      // Pre-flight dup-check: renaming beta → alpha must alert and
      // leave the rename uncommitted, mirroring the create-time
      // dup-check. Runs BEFORE the next test which renames alpha
      // away — so both seeded notes are still around to collide.
      const alerts = [];
      const handler = (d) => {
        alerts.push(d.message());
        void d.dismiss();
      };
      page.on("dialog", handler);
      try {
        await clickRow("beta");
        await page.locator('[data-testid="note-title"]').click();
        const input = page.locator('[data-testid="title-edit-input"]');
        await input.waitFor({ state: "visible" });
        await input.fill("alpha");
        await input.press("Enter");
        await page.waitForTimeout(400);
        assert(
          alerts.some((m) => /alpha/.test(m)),
          `alert mentions duplicate — got ${JSON.stringify(alerts)}`,
        );
        // Tree still has both alpha + beta; no rename happened.
        assert(
          (await getNoteByTitle("alpha")) !== null,
          "alpha intact",
        );
        assert(
          (await getNoteByTitle("beta")) !== null,
          "beta intact",
        );
        // Dialog auto-exits edit mode on dup so the user doesn't
        // strand on a stale input — input should already be gone.
        const stillEditing = await page
          .locator('[data-testid="title-edit-input"]')
          .count();
        assert(
          stillEditing === 0,
          `input closed after dup-block — got ${stillEditing}`,
        );
      } finally {
        page.off("dialog", handler);
      }
    },
  );

  await runTest("Enter commits the new title to disk + tree", async () => {
    await clickRow("alpha");
    await page.locator('[data-testid="note-title"]').click();
    const input = page.locator('[data-testid="title-edit-input"]');
    await input.waitFor({ state: "visible" });
    // Replace the entire value, then commit.
    await input.fill("alpha-renamed");
    await input.press("Enter");
    // h1 reflects the new title.
    await page.waitForFunction(
      () => {
        const h1 = document.querySelector('[data-testid="note-title"]');
        return h1 && /alpha-renamed/.test(h1.textContent ?? "");
      },
      null,
      { timeout: 2500, polling: 50 },
    );
    // Tree row reflects new title.
    await page.waitForFunction(
      () => {
        const rows = Array.from(document.querySelectorAll(".group"));
        return rows.some((r) => /^alpha-renamed$/.test((r.textContent ?? "").trim()));
      },
      null,
      { timeout: 2500, polling: 80 },
    );
    // Backend persisted.
    const note = await getNoteByTitle("alpha-renamed");
    assert(note !== null, "backend tree contains note with the new title");
  });

  await runTest("Esc cancels without renaming", async () => {
    await clickRow("beta");
    await page.locator('[data-testid="note-title"]').click();
    const input = page.locator('[data-testid="title-edit-input"]');
    await input.waitFor({ state: "visible" });
    await input.fill("beta-aborted");
    await input.press("Escape");
    await page.waitForTimeout(400);
    const h1Text = await page
      .locator('[data-testid="note-title"]')
      .textContent();
    assert(/beta/.test(h1Text ?? "") && !/aborted/.test(h1Text ?? ""), `title unchanged — got "${h1Text}"`);
    const aborted = await getNoteByTitle("beta-aborted");
    assert(aborted === null, "backend NOT renamed on Esc");
  });

  await runTest("empty input is a no-op", async () => {
    await clickRow("beta");
    await page.locator('[data-testid="note-title"]').click();
    const input = page.locator('[data-testid="title-edit-input"]');
    await input.waitFor({ state: "visible" });
    await input.fill("");
    await input.press("Enter");
    await page.waitForTimeout(400);
    const note = await getNoteByTitle("beta");
    assert(note !== null, "beta still exists with original title");
  });

  await runTest("unchanged input is a no-op (no spurious save)", async () => {
    await clickRow("beta");
    await page.locator('[data-testid="note-title"]').click();
    const input = page.locator('[data-testid="title-edit-input"]');
    await input.waitFor({ state: "visible" });
    // Submit unchanged value — should just close the input, no PUT.
    await input.press("Enter");
    await page.waitForTimeout(400);
    const stillEditing = await page
      .locator('[data-testid="title-edit-input"]')
      .count();
    assert(stillEditing === 0, "input closed without committing");
    const note = await getNoteByTitle("beta");
    assert(note !== null, "beta still exists");
  });

  await runTest("F2 / Enter on focused title also enters edit mode", async () => {
    await clickRow("beta");
    const h1 = page.locator('[data-testid="note-title"]');
    await h1.focus();
    await page.keyboard.press("F2");
    const input = page.locator('[data-testid="title-edit-input"]');
    await input.waitFor({ state: "visible", timeout: 2000 });
    await input.press("Escape");
  });

  await runTest(
    "title-edit strips trailing .md (no `foo` vs `foo.md` confusion)",
    async () => {
      // Dogfood scenario: user types `whatever.md` into the title
      // input — it should land as `whatever`, matching the create
      // path's strip rule. Without this, `foo` and `foo.md` look
      // near-identical in the tree but are different notes.
      await clickRow("beta");
      await page.locator('[data-testid="note-title"]').click();
      const input = page.locator('[data-testid="title-edit-input"]');
      await input.waitFor({ state: "visible" });
      await input.fill("beta-renamed.md");
      await input.press("Enter");
      await page.waitForFunction(
        () => {
          const h1 = document.querySelector('[data-testid="note-title"]');
          return h1 && /beta-renamed/.test(h1.textContent ?? "");
        },
        null,
        { timeout: 2500, polling: 60 },
      );
      const h1text = await page
        .locator('[data-testid="note-title"]')
        .textContent();
      assert(
        /^beta-renamed$/.test((h1text ?? "").trim()),
        `title stripped of .md — got "${h1text}"`,
      );
      // Backend persisted the cleaned title.
      const note = await getNoteByTitle("beta-renamed");
      assert(note !== null, "backend has note titled 'beta-renamed'");
      const stale = await getNoteByTitle("beta-renamed.md");
      assert(stale === null, "no note titled with the .md suffix");
    },
  );

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
