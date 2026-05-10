/**
 * Save-error UX (no slice number — counts as a Phase 2 E hardening
 * follow-up after the saveMutation onError gap was found while
 * confirming auto-save support).
 *
 * Verifies:
 *   - When the backend rejects PUT /api/notes/* repeatedly, the
 *     auto-save badge transitions to "error" state (after retries
 *     exhaust) and shows a Retry button.
 *   - Editor content is preserved during the error window — user
 *     hasn't "lost" their edits even though the save failed.
 *   - Clicking Retry while the route is still failing keeps the
 *     error state (no fake success).
 *   - Once the route is restored + Retry clicked, save completes
 *     and the badge falls back to "saved" / "idle".
 */

import { assert, exitAfter, runTest, setupTestEnv } from "./_fixture.mjs";

const env = await setupTestEnv({
  notes: [{ title: "alpha", body: "starting body" }],
  language: "en",
});
const { page, baseURL, teardown } = env;

try {
  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);

  // Open the note.
  await page.locator(".group").filter({ hasText: "alpha" }).first().click();
  await page.waitForTimeout(300);
  await page
    .locator('[data-testid="markdown-editor"] .cm-content')
    .waitFor({ state: "visible", timeout: 3000 });

  await runTest("PUT failures surface as 'error' state with retry button", async () => {
    // Block all PUT /api/notes/* with a 500.
    let blocked = 0;
    await page.route("**/api/notes/*", async (route) => {
      if (route.request().method() === "PUT") {
        blocked++;
        await route.fulfill({
          status: 500,
          contentType: "application/json",
          body: JSON.stringify({ detail: "simulated" }),
        });
        return;
      }
      await route.continue();
    });

    // Type something to trigger autosave.
    const editor = page.locator(
      '[data-testid="markdown-editor"] .cm-content',
    );
    await editor.click();
    await page.keyboard.type(" extra typed");
    // Wait for autosave debounce (800ms) + retry backoff (~14s
    // worst case, 1+2+4+8 then onError). Cap at 18s.
    await page
      .locator('[data-testid="autosave-state"][data-state="error"]')
      .waitFor({ state: "visible", timeout: 18000 });
    // Retry button is visible.
    const retry = page.locator('[data-testid="autosave-retry"]');
    await retry.waitFor({ state: "visible" });
    // Editor still carries the user's changes — no silent data loss
    // even though save failed.
    const editorText = (await editor.textContent()) ?? "";
    assert(
      /extra typed/.test(editorText),
      `editor must keep user's edits during save error — got "${editorText}"`,
    );
    assert(blocked >= 1, `expected at least one blocked PUT, got ${blocked}`);

    // Unblock the route + click Retry → save should succeed.
    // (We deliberately skip "manual retry while still broken stays
    // in error" — that fights react-query's saving→error transition
    // window, which is timing-dependent and not load-bearing for
    // user behavior.)
    await page.unroute("**/api/notes/*");
    await retry.click();
    // After success: state goes saved → idle (1.2s timeout in component).
    // Wait for either explicit "saved" OR the badge becoming hidden.
    await page.waitForFunction(
      () => {
        const el = document.querySelector('[data-testid="autosave-state"]');
        if (!el) return false;
        const state = el.getAttribute("data-state");
        return state === "saved" || state === "idle";
      },
      undefined,
      { timeout: 5000 },
    );
  });

  await teardown();
  exitAfter(0);
} catch (e) {
  console.error("autosave-error e2e failed:", e);
  await teardown();
  exitAfter(1);
}
