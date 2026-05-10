/**
 * Phase 2 E Slice S5 — conflict merge editor e2e.
 *
 * Mocks /api/sync/note-status (forces state=conflict on the test
 * note) and /api/sync/conflict-bundle (returns predefined local +
 * remote text with one shared prefix, one differing middle, and one
 * shared suffix). Drives the dialog: click badge → dialog opens →
 * pick Take Mine on the diff hunk → save → assert the resolveMerge
 * call carries the merged text + dialog closes.
 *
 * No real Drive setup required — fully self-driving.
 */

import { assert, exitAfter, expectRow, runTest, setupTestEnv } from "./_fixture.mjs";

const env = await setupTestEnv({
  notes: [{ title: "alpha", body: "alpha body" }],
  language: "en",
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

try {
  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);

  // Open the seeded note so NoteView mounts + the badge renders.
  const row = await expectRow(page, "alpha");
  await row.click();
  await page.waitForTimeout(500);

  await runTest("conflict badge is clickable", async () => {
    const badge = page
      .locator('[data-testid="sync-status-badge"][data-state="conflict"]')
      .first();
    await badge.waitFor({ state: "visible", timeout: 3000 });
    // It MUST render as a real button so keyboard / a11y works.
    const tag = await badge.evaluate((el) => el.tagName.toLowerCase());
    assert(tag === "button", `expected <button>, got <${tag}>`);
  });

  await runTest("clicking opens the merge dialog with both panes", async () => {
    await page
      .locator('[data-testid="sync-status-badge"][data-state="conflict"]')
      .first()
      .click();
    const dialog = page.locator('[data-testid="conflict-merge-dialog"]');
    await dialog.waitFor({ state: "visible", timeout: 3000 });
    await page
      .locator('[data-testid="merge-pane-mine"]')
      .waitFor({ state: "visible" });
    await page
      .locator('[data-testid="merge-pane-theirs"]')
      .waitFor({ state: "visible" });
    await page
      .locator('[data-testid="merge-pane-merged"]')
      .waitFor({ state: "visible" });
    // The diff hunk should be present on both sides exactly once.
    const mineHunks = await page
      .locator('[data-testid="merge-hunk-mine"]')
      .count();
    const theirsHunks = await page
      .locator('[data-testid="merge-hunk-theirs"]')
      .count();
    assert(mineHunks === 1, `expected 1 mine hunk, got ${mineHunks}`);
    assert(theirsHunks === 1, `expected 1 theirs hunk, got ${theirsHunks}`);
  });

  await runTest("save is disabled until a choice is made", async () => {
    const saveBtn = page.locator('[data-testid="merge-save"]');
    const disabledBefore = await saveBtn.getAttribute("disabled");
    assert(
      disabledBefore !== null,
      "save button must start disabled (no hunk choices yet)",
    );
  });

  await runTest(
    "Take Mine + Save sends merged text and closes dialog",
    async () => {
      // Click "Take mine" inside the mine hunk block.
      await page
        .locator('[data-testid="merge-hunk-mine"]')
        .getByRole("button", { name: /take mine/i })
        .click();
      // Save button should now be enabled.
      await page
        .locator('[data-testid="merge-save"]:not([disabled])')
        .waitFor({ state: "visible", timeout: 2000 });
      await page.locator('[data-testid="merge-save"]').click();

      // Dialog closes on success.
      await page
        .locator('[data-testid="conflict-merge-dialog"]')
        .waitFor({ state: "detached", timeout: 3000 });

      assert(resolveBody !== null, "resolveMerge POST never fired");
      assert(
        typeof resolveBody.merged_text === "string",
        "merged_text not in body",
      );
      // Take Mine on the only diff hunk → result should be local text.
      assert(
        resolveBody.merged_text === LOCAL_TEXT,
        `expected merged_text=${JSON.stringify(LOCAL_TEXT)}, got ${JSON.stringify(resolveBody.merged_text)}`,
      );
    },
  );

  await teardown();
  exitAfter(0);
} catch (e) {
  console.error("conflict-merge e2e failed:", e);
  await teardown();
  exitAfter(1);
}
