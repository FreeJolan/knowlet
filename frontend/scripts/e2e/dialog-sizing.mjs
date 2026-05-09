/**
 * Dogfood regression: shadcn's default DialogContent is `sm:max-w-sm`
 * (384 px). Our overrides without the `sm:` prefix were silently
 * losing to that responsive variant — every dialog stayed narrow on
 * a desktop window.
 *
 * Verifies all three browse-style dialogs render WIDE on a 1400 px
 * viewport (the e2e default). Width thresholds are conservative so
 * the test doesn't flake on a few px of padding shift.
 */

import { assert, exitAfter, runTest, setupTestEnv } from "./_fixture.mjs";

const env = await setupTestEnv({
  notes: [
    { title: "alpha", body: "x" },
    { title: "beta", body: "y", folder: "lab/inner" },
  ],
  folders: ["lab", "lab/inner"],
  language: "en",
});
const { page, baseURL, teardown } = env;

async function dialogWidth() {
  const box = await page
    .locator('[data-slot="dialog-content"]')
    .first()
    .boundingBox();
  return box?.width ?? 0;
}

try {
  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);

  await runTest("CommandPalette (Cmd+P) dialog ≥ 700px on 1400px viewport", async () => {
    await page.keyboard.press("Meta+P");
    await page
      .locator('[data-slot="dialog-content"]')
      .first()
      .waitFor({ state: "visible", timeout: 3000 });
    const w = await dialogWidth();
    assert(
      w >= 700 && w <= 1100,
      `palette dialog width in 700..1100 — got ${Math.round(w)}px`,
    );
    await page.keyboard.press("Escape");
    await page.waitForTimeout(150);
  });

  // 2026-05-10: Templates manage moved from a header dialog to the
  // left-rail "Templates" tab. The standalone dialog was removed in
  // Slice 2c.2-A'; no replacement size assertion needed (the tab
  // shares the file-tree's left-rail width which is exercised in
  // sidebar-width.mjs).

  await runTest("Trash dialog ≥ 900px on 1400px viewport", async () => {
    // Open via the global header icon. Trash is the widest dialog
    // because long folder paths + titles need room.
    await page.locator('button[aria-label="Trash"], button[aria-label="垃圾桶"]').first().click();
    await page
      .locator('[data-slot="dialog-content"]')
      .first()
      .waitFor({ state: "visible", timeout: 3000 });
    const w = await dialogWidth();
    assert(
      w >= 900 && w <= 1300,
      `trash dialog width in 900..1300 — got ${Math.round(w)}px`,
    );
    await page.keyboard.press("Escape");
    await page.waitForTimeout(150);
  });

  await runTest(
    "CommandPalette omits notes from `_templates/` (no storage leak)",
    async () => {
      // Seed a template via API, then verify it doesn't show in
      // the palette. The palette is for switching to NOTES; the
      // Templates dialog is for managing TEMPLATES.
      const r = await page.request.post(`${baseURL}/api/notes/new`, {
        data: { title: "secret tpl", folder: "_templates" },
      });
      assert(r.status() === 200, `template seeded — got ${r.status()}`);
      // Re-query the tree so the cached palette flatten() picks up
      // the new note.
      await page.evaluate(() => {
        const w = window;
        const qc = w.__qc;
        if (qc) qc.invalidateQueries({ queryKey: ["tree"] });
      });
      await page.keyboard.press("Meta+P");
      await page
        .locator('[data-slot="dialog-content"]')
        .first()
        .waitFor({ state: "visible", timeout: 3000 });
      await page.waitForTimeout(300);
      const items = await page
        .locator('[cmdk-item], [role="option"]')
        .allInnerTexts();
      const flat = items.join(" ");
      assert(
        !/secret tpl/i.test(flat),
        `_templates note hidden from palette — got "${flat.slice(0, 200)}"`,
      );
      await page.keyboard.press("Escape");
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
