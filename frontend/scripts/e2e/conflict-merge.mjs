/**
 * Phase 2 E Slice S5 v2 — conflict merge editor e2e.
 *
 * Mocks /api/sync/note-status (force conflict on the active note)
 * and /api/sync/conflict-bundle (predefined local + remote with one
 * shared prefix, one differing middle hunk, one shared tail). Drives
 * the dialog: open → click "→" gutter button → assert preview row
 * updated → save → assert resolveMerge POST body carries the
 * merged text and dialog closes.
 *
 * Also covers the global "Use mine for everything" toolbar shortcut
 * — important because that's the small-red persona's escape hatch.
 *
 * HEADLESS=0 keeps Chromium visible for the dogfood pass.
 */

import { assert, exitAfter, expectRow, runTest, setupTestEnv } from "./_fixture.mjs";

const HEADLESS = process.env.HEADLESS !== "0";

const env = await setupTestEnv({
  notes: [{ title: "alpha", body: "alpha body" }],
  language: "en",
  headless: HEADLESS,
});
const { page, baseURL, teardown } = env;

const LOCAL_TEXT = ["shared prefix line", "MINE only line", "shared tail"].join(
  "\n",
);
const REMOTE_TEXT = [
  "shared prefix line",
  "THEIRS only line",
  "shared tail",
].join("\n");

let resolveBody = null;

await page.route("**/api/sync/note-status/**", async (route) => {
  await route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      state: "conflict",
      last_synced_at: "2026-05-10T12:00:00Z",
      drive_file_id: "DRIVE-FID",
      last_known_revision: "rev-OLD",
      current_drive_revision: "rev-NEW",
      detail: null,
    }),
  });
});

await page.route("**/api/sync/conflict-bundle/**", async (route) => {
  await route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      note_id: "test-note",
      drive_file_id: "DRIVE-FID",
      local_text: LOCAL_TEXT,
      remote_text: REMOTE_TEXT,
      current_drive_revision: "rev-NEW",
      last_known_revision: "rev-OLD",
      local_modified_at: "2026-05-10T14:32:00Z",
      remote_modified_at: "2026-05-10T17:08:00Z",
      remote_modified_by: "alice@example.com",
    }),
  });
});

await page.route("**/api/sync/resolve-merge/**", async (route) => {
  resolveBody = route.request().postDataJSON();
  await route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      drive_file_id: "DRIVE-FID",
      new_revision: "rev-MERGED",
    }),
  });
});

const PAUSE = HEADLESS ? 0 : 1200;
const breath = () => page.waitForTimeout(PAUSE);

try {
  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);
  await breath();

  const row = await expectRow(page, "alpha");
  await row.click();
  await page.waitForTimeout(500);

  await runTest("conflict badge renders as a clickable button", async () => {
    const badge = page
      .locator('[data-testid="sync-status-badge"][data-state="conflict"]')
      .first();
    await badge.waitFor({ state: "visible", timeout: 3000 });
    const tag = await badge.evaluate((el) => el.tagName.toLowerCase());
    assert(tag === "button", `expected <button>, got <${tag}>`);
  });

  await runTest("clicking opens the dialog with column headers", async () => {
    await breath();
    await page
      .locator('[data-testid="sync-status-badge"][data-state="conflict"]')
      .first()
      .click();
    await page
      .locator('[data-testid="conflict-merge-dialog"]')
      .waitFor({ state: "visible", timeout: 3000 });

    // Headers should display human-friendly identifiers, not raw rev ids.
    const mineHeader = page.locator(
      '[data-testid="merge-pane-mine-header"]',
    );
    const theirsHeader = page.locator(
      '[data-testid="merge-pane-theirs-header"]',
    );
    await mineHeader.waitFor({ state: "visible" });
    const mineHeaderText = (await mineHeader.textContent()) ?? "";
    const theirsHeaderText = (await theirsHeader.textContent()) ?? "";
    assert(
      /you/i.test(mineHeaderText),
      `mine header must say "you", got "${mineHeaderText}"`,
    );
    assert(
      /alice@example\.com/.test(theirsHeaderText),
      `theirs header must show the editor's identity, got "${theirsHeaderText}"`,
    );

    // The 5-column grid with one diff hunk → 1 mine and 1 theirs cell.
    await page
      .locator('[data-testid="merge-grid"]')
      .waitFor({ state: "visible" });
    const mineCount = await page
      .locator('[data-testid="merge-hunk-mine-0"]')
      .count();
    const theirsCount = await page
      .locator('[data-testid="merge-hunk-theirs-0"]')
      .count();
    assert(
      mineCount === 1 && theirsCount === 1,
      `expected one diff per side, got mine=${mineCount} theirs=${theirsCount}`,
    );
    await breath();
  });

  await runTest("save is disabled until each hunk has a choice", async () => {
    const saveBtn = page.locator('[data-testid="merge-save"]');
    const disabledBefore = await saveBtn.getAttribute("disabled");
    assert(
      disabledBefore !== null,
      "save must start disabled (no hunk choices yet)",
    );
    // Pending count surfaces the "still need a choice" hint.
    await page
      .locator('[data-testid="merge-pending-count"]')
      .waitFor({ state: "visible" });
  });

  await runTest("→ gutter button toggles mine into merged", async () => {
    await page
      .locator('[data-testid="merge-push-mine-0"]')
      .click();
    await breath();
    // Save now enabled.
    await page
      .locator('[data-testid="merge-save"]:not([disabled])')
      .waitFor({ state: "visible", timeout: 2000 });
    // Pressed state on the gutter button.
    const pressed = await page
      .locator('[data-testid="merge-push-mine-0"]')
      .getAttribute("aria-pressed");
    assert(pressed === "true", `expected aria-pressed=true, got ${pressed}`);
    // Merged row text = mine text for this hunk.
    const mergedRow = page.locator('[data-testid="merge-merged-row-0"]');
    const mergedText = (await mergedRow.textContent()) ?? "";
    assert(
      mergedText.includes("MINE only line"),
      `merged row should show MINE content, got "${mergedText}"`,
    );
  });

  await runTest("← also toggled in → ← state = both, mine then theirs", async () => {
    await page.locator('[data-testid="merge-push-theirs-0"]').click();
    await breath();
    const mergedRow = page.locator('[data-testid="merge-merged-row-0"]');
    const mergedText = (await mergedRow.textContent()) ?? "";
    assert(
      mergedText.includes("MINE only line") &&
        mergedText.includes("THEIRS only line") &&
        mergedText.indexOf("MINE") < mergedText.indexOf("THEIRS"),
      `both choice must concat mine→theirs, got "${mergedText}"`,
    );
  });

  await runTest("Use-mine-for-everything global shortcut", async () => {
    // Reset to all-mine via the global toolbar.
    await page.locator('[data-testid="merge-all-mine"]').click();
    await breath();
    const minePressed = await page
      .locator('[data-testid="merge-push-mine-0"]')
      .getAttribute("aria-pressed");
    const theirsPressed = await page
      .locator('[data-testid="merge-push-theirs-0"]')
      .getAttribute("aria-pressed");
    assert(
      minePressed === "true" && theirsPressed === "false",
      `all-mine should leave mine pressed and theirs unpressed; got mine=${minePressed} theirs=${theirsPressed}`,
    );
  });

  await runTest("Save sends merged text and closes dialog", async () => {
    await breath();
    await page.locator('[data-testid="merge-save"]').click();
    await page
      .locator('[data-testid="conflict-merge-dialog"]')
      .waitFor({ state: "detached", timeout: 3000 });
    assert(resolveBody !== null, "resolveMerge POST never fired");
    assert(
      typeof resolveBody.merged_text === "string",
      "merged_text not in body",
    );
    // After "all mine" → result equals the local text exactly.
    assert(
      resolveBody.merged_text === LOCAL_TEXT,
      `expected merged_text=${JSON.stringify(LOCAL_TEXT)}, got ${JSON.stringify(resolveBody.merged_text)}`,
    );
    // CRITICAL: no git-style markers should ever leak to disk.
    assert(
      !/^<<<<<<<\s|^>>>>>>>\s|^=======$/m.test(resolveBody.merged_text),
      `saved text must not contain git conflict markers — got ${JSON.stringify(resolveBody.merged_text)}`,
    );
  });

  if (!HEADLESS) await page.waitForTimeout(2500);
  await teardown();
  exitAfter(0);
} catch (e) {
  console.error("conflict-merge e2e failed:", e);
  await teardown();
  exitAfter(1);
}
