/**
 * Phase 2 D slice 1 — Daily notes (Cmd+Shift+D).
 *
 * Verifies:
 *   - Cmd+Shift+D creates today's note in `daily/` folder, opens
 *     in a tab with title = local YYYY-MM-DD.
 *   - Pressing again on the same day re-activates the existing tab,
 *     does NOT create a duplicate.
 *   - The header "Today's note" button does the same.
 *   - daily/ folder is auto-created on first call.
 */

import { assert, exitAfter, runTest, setupTestEnv } from "./_fixture.mjs";

function todayLocal() {
  const d = new Date();
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

const env = await setupTestEnv({
  notes: [{ title: "filler", body: "non-daily" }],
  language: "en",
});
const { page, baseURL, teardown } = env;

try {
  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);

  const today = todayLocal();

  await runTest("Cmd+Shift+D creates today's daily note + opens tab", async () => {
    await page.keyboard.press("Meta+Shift+D");
    // Wait for tab strip to show the new note.
    await page
      .locator(`[data-testid="tab"]`, { hasText: today })
      .first()
      .waitFor({ state: "visible", timeout: 4000 });
    // NoteView title h1 reflects the new note.
    const h1 = (await page.locator('[data-testid="note-title"]').first().textContent()) ?? "";
    assert(h1.includes(today), `note title should be ${today}, got "${h1}"`);
    // Tree got a `daily/` folder (visible if expanded; check API).
    const tree = await page.evaluate(async () => (await fetch("/api/tree")).json());
    const daily = tree.folders.find((f) => f.name === "daily");
    assert(daily, "daily/ folder should exist after first daily-create");
    const todayNote = (daily?.notes ?? []).find((n) => n.title === today);
    assert(todayNote, `daily/ should contain note titled ${today}`);
  });

  await runTest("Pressing Cmd+Shift+D again re-activates the same tab (idempotent)", async () => {
    const tabsBefore = await page.locator('[data-testid="tab"]').count();
    await page.keyboard.press("Meta+Shift+D");
    await page.waitForTimeout(500);
    const tabsAfter = await page.locator('[data-testid="tab"]').count();
    assert(
      tabsBefore === tabsAfter,
      `tab count must not grow (was ${tabsBefore}, now ${tabsAfter})`,
    );
    // Backend has only one daily note for today.
    const tree = await page.evaluate(async () => (await fetch("/api/tree")).json());
    const daily = tree.folders.find((f) => f.name === "daily");
    const todayCount = (daily?.notes ?? []).filter((n) => n.title === today).length;
    assert(
      todayCount === 1,
      `expected exactly 1 daily note for ${today}, got ${todayCount}`,
    );
  });

  await runTest("Header 'Today's note' button does the same", async () => {
    // Open a non-daily note first to make sure the button activates the daily tab.
    await page
      .locator('[role="treeitem"]', { hasText: "filler" })
      .first()
      .click();
    await page.waitForTimeout(300);
    await page.locator('[data-testid="header-daily-button"]').click();
    await page.waitForTimeout(500);
    const activeTitle = await page.evaluate(() => {
      const t = document.querySelector('[data-testid="tab"][data-active="true"]');
      return t ? (t.textContent ?? "").trim().replace(/×$/, "").trim() : null;
    });
    assert(
      activeTitle === today,
      `daily button should activate today's tab, got "${activeTitle}"`,
    );
    // Still no duplicates.
    const tree = await page.evaluate(async () => (await fetch("/api/tree")).json());
    const daily = tree.folders.find((f) => f.name === "daily");
    const todayCount = (daily?.notes ?? []).filter((n) => n.title === today).length;
    assert(todayCount === 1, `still exactly 1 daily note, got ${todayCount}`);
  });

  await runTest("After reload, Cmd+Shift+D still finds existing note (no dup)", async () => {
    await page.reload({ waitUntil: "networkidle" });
    await page.waitForTimeout(600);
    await page.keyboard.press("Meta+Shift+D");
    await page.waitForTimeout(500);
    const tree = await page.evaluate(async () => (await fetch("/api/tree")).json());
    const daily = tree.folders.find((f) => f.name === "daily");
    const todayCount = (daily?.notes ?? []).filter((n) => n.title === today).length;
    assert(
      todayCount === 1,
      `post-reload Cmd+Shift+D must not duplicate, got ${todayCount}`,
    );
  });

  await teardown();
  exitAfter(0);
} catch (e) {
  console.error("phase2d-slice1 e2e failed:", e);
  await teardown();
  exitAfter(1);
}
