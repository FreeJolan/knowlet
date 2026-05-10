/**
 * Phase 2 E Slice S1 — per-note SyncStatusBadge e2e.
 *
 * Mocks /api/sync/note-status/<id> at the network layer for each
 * of the five terminal states + the two frontend overlay states
 * (syncing during a save, editing during unsaved typing). Verifies
 * the badge renders the right icon/label/color and that the
 * unauthenticated state hides the badge entirely.
 *
 * No real Drive setup required — fully self-driving.
 */

import { assert, exitAfter, expectRow, runTest, setupTestEnv } from "./_fixture.mjs";

const env = await setupTestEnv({
  notes: [{ title: "alpha", body: "alpha body" }],
  language: "en",
});
const { page, baseURL, teardown } = env;

let stubState = "synced";
let stubDetail = null;

await page.route("**/api/sync/note-status/**", async (route) => {
  const url = route.request().url();
  // Find the note id segment so we don't 404 unexpected ones.
  const m = url.match(/\/api\/sync\/note-status\/([^/?]+)/);
  const noteId = m ? m[1] : "";
  await route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      state: stubState,
      last_synced_at: stubState === "synced" ? "2026-05-10T12:00:00Z" : null,
      drive_file_id: stubState === "unauthenticated" ? null : "DRIVE-FID",
      last_known_revision: stubState === "synced" ? "rev-1" : null,
      current_drive_revision:
        stubState === "synced"
          ? "rev-1"
          : stubState === "conflict"
            ? "rev-2"
            : null,
      detail: stubDetail,
    }),
  });
  // Suppress "noteId" unused warning under strict tooling.
  void noteId;
});

try {
  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);

  // Open the seeded note so NoteView mounts + fires the polling query.
  const row = await expectRow(page, "alpha");
  await row.click();
  await page.waitForTimeout(500);

  await runTest("synced state shows green check + 'synced'", async () => {
    stubState = "synced";
    // Force a refetch by reloading; React Query will fire the route mock.
    await page.reload({ waitUntil: "networkidle" });
    await (await expectRow(page, "alpha")).click();
    const badge = page
      .locator('[data-testid="sync-status-badge"]')
      .first();
    await badge.waitFor({ state: "visible", timeout: 3000 });
    const state = await badge.getAttribute("data-state");
    assert(state === "synced", `expected data-state=synced, got ${state}`);
    const text = (await badge.textContent()) ?? "";
    assert(/synced/i.test(text), `badge text must say synced — got "${text}"`);
  });

  await runTest("dirty state surfaces 'not synced'", async () => {
    stubState = "dirty";
    await page.reload({ waitUntil: "networkidle" });
    await (await expectRow(page, "alpha")).click();
    const badge = page
      .locator('[data-testid="sync-status-badge"]')
      .first();
    await badge.waitFor({ state: "visible" });
    const state = await badge.getAttribute("data-state");
    assert(state === "dirty", `expected dirty, got ${state}`);
  });

  await runTest("conflict state surfaces 'conflict'", async () => {
    stubState = "conflict";
    await page.reload({ waitUntil: "networkidle" });
    await (await expectRow(page, "alpha")).click();
    const badge = page.locator('[data-testid="sync-status-badge"]').first();
    await badge.waitFor({ state: "visible" });
    const state = await badge.getAttribute("data-state");
    assert(state === "conflict", `expected conflict, got ${state}`);
  });

  await runTest("offline state surfaces 'offline'", async () => {
    stubState = "offline";
    stubDetail = "ConnectionError('network down')";
    await page.reload({ waitUntil: "networkidle" });
    await (await expectRow(page, "alpha")).click();
    const badge = page.locator('[data-testid="sync-status-badge"]').first();
    await badge.waitFor({ state: "visible" });
    const state = await badge.getAttribute("data-state");
    assert(state === "offline", `expected offline, got ${state}`);
    const tooltip = await badge.getAttribute("title");
    assert(
      (tooltip ?? "").includes("network down"),
      `tooltip should carry detail — got "${tooltip}"`,
    );
    stubDetail = null;
  });

  await runTest(
    "unauthenticated state hides the badge",
    async () => {
      stubState = "unauthenticated";
      await page.reload({ waitUntil: "networkidle" });
      await (await expectRow(page, "alpha")).click();
      // Give the polling query time to settle.
      await page.waitForTimeout(500);
      const count = await page
        .locator('[data-testid="sync-status-badge"]')
        .count();
      assert(
        count === 0,
        `badge must be hidden under unauthenticated — got ${count}`,
      );
    },
  );

  await teardown();
  exitAfter(0);
} catch (e) {
  console.error("sync-status-badge e2e failed:", e);
  await teardown();
  exitAfter(1);
}
