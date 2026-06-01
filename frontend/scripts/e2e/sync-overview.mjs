/**
 * Header sync overview: visible "is everything pushed?" text plus a
 * manual sync-now entry.
 */

import {
  assert,
  assertConsoleClean,
  exitAfter,
  runTest,
  setupTestEnv,
} from "./_fixture.mjs";

const env = await setupTestEnv({
  notes: [{ title: "Sync overview note", body: "local body" }],
  language: "en",
});
const { page, baseURL, teardown } = env;

const emptyReport = {
  ran_at: Date.now() / 1000,
  scanned: 0,
  conflicts: [],
  offline: [],
  auto_pulled_ids: [],
  synced_count: 0,
  dirty_count: 0,
  unauthenticated: false,
  alive_devices: [],
  cloned_from_drive_ids: [],
  trashed_for_drive_delete_ids: [],
};

let pushedAll = 0;
let drained = 0;
let synced = false;

await page.route("**/api/sync/auth-status", async (route) => {
  await route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      connected: true,
      user_email: "alice@example.com",
      user_display_name: "Alice",
      connecting: false,
      last_error: null,
    }),
  });
});

await page.route("**/api/sync/mode", async (route) => {
  await route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      mode: "realtime",
      effective_mode: "realtime",
      device_count: 1,
    }),
  });
});

await page.route("**/api/sync/conflicts", async (route) => {
  await route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(emptyReport),
  });
});

await page.route("**/api/sync/unpushed-status", async (route) => {
  await route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ count: synced ? 0 : 1, authenticated: true }),
  });
});

await page.route("**/api/sync/push-errors", async (route) => {
  await route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ errors: [] }),
  });
});

await page.route("**/api/sync/freshness", async (route) => {
  await route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      mode: "realtime",
      state: "up_to_date",
      checked_at: "2026-06-02T00:00:00Z",
      requires_sync: false,
      reason: null,
      changed_count: 0,
      next_start_page_token: "tok",
      detail: null,
    }),
  });
});

await page.route("**/api/sync/overview", async (route) => {
  await route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(
      synced
        ? {
            authenticated: true,
            state: "synced",
            pending_count: 0,
            dirty_count: 0,
            deletion_pending_count: 0,
            unpushed_count: 0,
            failure_count: 0,
            last_synced_at: "2026-06-02T00:00:03Z",
            detail: null,
          }
        : {
            authenticated: true,
            state: "pending",
            pending_count: 2,
            dirty_count: 1,
            deletion_pending_count: 0,
            unpushed_count: 1,
            failure_count: 0,
            last_synced_at: "2026-06-02T00:00:00Z",
            detail: "2 pending local change(s)",
          },
    ),
  });
});

await page.route("**/api/sync/push-all-unpushed", async (route) => {
  pushedAll += 1;
  await route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ queued: 1 }),
  });
});

await page.route("**/api/sync/drain-now", async (route) => {
  drained += 1;
  synced = true;
  await route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ ran: true }),
  });
});

try {
  await page.goto(baseURL, { waitUntil: "domcontentloaded" });

  await runTest("header shows pending sync status and sync-now action", async () => {
    const chip = page.locator('[data-testid="sync-chip"]');
    await chip.waitFor({ state: "visible", timeout: 5000 });
    assert((await chip.innerText()).includes("2 to sync"), "chip should show pending count");
    assert((await chip.getAttribute("data-pending")) === "2", "chip should expose pending count");

    await chip.click();
    const panel = page.locator('[data-testid="sync-inbox"]');
    await panel.waitFor({ state: "visible", timeout: 3000 });
    assert(
      (await page.locator('[data-testid="sync-inbox-overview"]').innerText()).includes(
        "2 local changes",
      ),
      "panel should explain that local changes have not reached Drive",
    );

    await page.locator('[data-testid="sync-inbox-sync-now"]').click();
    await page.waitForFunction(() => {
      const el = document.querySelector('[data-testid="sync-chip"]');
      return el?.textContent?.includes("Synced");
    });
    assert(pushedAll === 1, "sync now should queue first-push rows");
    assert(drained === 1, "sync now should kick the drainer immediately");
  });

  await runTest("sync chip panel has opaque background", async () => {
    await page.locator('[data-testid="sync-chip"]').click();
    const bg = await page
      .locator('[data-testid="sync-inbox"]')
      .evaluate((el) => getComputedStyle(el).backgroundColor);
    assert(bg !== "rgba(0, 0, 0, 0)", `sync panel background must be opaque, got ${bg}`);
  });

  await assertConsoleClean(env);
} finally {
  await teardown();
}

exitAfter();
