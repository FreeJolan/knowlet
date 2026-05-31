/**
 * Sync v2 freshness gate e2e.
 *
 * The first Drive check is intentionally lightweight and non-blocking.
 * Only after that probe reports remote work should the UI show a
 * blocking sync dialog and run the heavier preflight.
 */

import {
  assert,
  assertConsoleClean,
  exitAfter,
  runTest,
  setupTestEnv,
} from "./_fixture.mjs";

const env = await setupTestEnv({
  notes: [{ title: "alpha", body: "alpha body" }],
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

let freshnessCall = 0;
let preflightCall = 0;
let releaseFreshness;
let releasePreflight;

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
  if (route.request().method() === "PUT") {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        mode: "backup",
        effective_mode: "backup",
        device_count: 0,
      }),
    });
    return;
  }
  await route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      mode: "realtime",
      effective_mode: "realtime",
      device_count: 2,
    }),
  });
});

await page.route("**/api/sync/conflicts", async (route) => {
  await route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ ...emptyReport, ran_at: null }),
  });
});

await page.route("**/api/sync/unpushed-status", async (route) => {
  await route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ count: 0, authenticated: true }),
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
  freshnessCall += 1;
  if (freshnessCall === 1) {
    await new Promise((resolve) => {
      releaseFreshness = resolve;
    });
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        mode: "realtime",
        state: "needs_sync",
        checked_at: "2026-05-31T00:00:00Z",
        requires_sync: true,
        reason: "remote_changes",
        changed_count: 2,
        next_start_page_token: "tok-2",
        detail: null,
      }),
    });
    return;
  }
  await route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      mode: "realtime",
      state: "up_to_date",
      checked_at: "2026-05-31T00:00:02Z",
      requires_sync: false,
      reason: null,
      changed_count: 0,
      next_start_page_token: "tok-3",
      detail: null,
    }),
  });
});

await page.route("**/api/sync/preflight", async (route) => {
  preflightCall += 1;
  await new Promise((resolve) => {
    releasePreflight = resolve;
  });
  await route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(emptyReport),
  });
});

try {
  await page.goto(baseURL, { waitUntil: "domcontentloaded" });

  await runTest("lightweight freshness probe does not block while pending", async () => {
    await page.waitForTimeout(250);
    const blockingCount = await page
      .locator('[data-testid="sync-freshness-blocking-modal"]')
      .count();
    assert(blockingCount === 0, "freshness probe itself must not block");
    assert(preflightCall === 0, "preflight must wait for the freshness result");
  });

  await runTest("remote updates trigger blocking preflight then unlock", async () => {
    for (let i = 0; i < 30 && typeof releaseFreshness !== "function"; i += 1) {
      await page.waitForTimeout(50);
    }
    assert(
      typeof releaseFreshness === "function",
      "freshness request should be in flight before release",
    );
    releaseFreshness();
    const modal = page.locator('[data-testid="sync-freshness-blocking-modal"]');
    await modal.waitFor({ state: "visible", timeout: 3000 });
    assert(preflightCall === 1, "remote updates should start exactly one preflight");
    releasePreflight();
    await modal.waitFor({ state: "hidden", timeout: 3000 });
    assert(
      freshnessCall >= 2,
      "successful preflight should refetch freshness after syncing",
    );
  });

  assertConsoleClean(env);
  await teardown();
  exitAfter(0);
} catch (e) {
  console.error("sync-freshness-gate e2e failed:", e);
  await teardown();
  exitAfter(1);
}
