// E2E: Stage 3 P3 — URL fetch failure + Retry recovery.
//
// Intercepts /api/capture/url at the network layer (no real outbound
// HTTP needed) and serves a 502 → frontend should render the error
// UI with a Retry button; clicking Retry re-attempts and succeeds
// once the route is unblocked.

import {
  assert,
  assertConsoleClean,
  exitAfter,
  runTest,
  setupTestEnv,
} from "./_fixture.mjs";

const env = await setupTestEnv({ notes: [], language: "en" });
const { page, baseURL, teardown } = env;

/**
 * Route mode controls how the mocked /api/capture/url responds:
 *   "502"          — return 502 (P3.a, P3.retry-error path)
 *   "200-ok"       — return clean capsule (P3.b retry success)
 *   "200-degraded" — return 200 + summary_failed=true + summary_error
 *                    (regression for 2026-05-22 dogfood: LLM down
 *                    but page extraction worked)
 */
let routeMode = "502";

try {
  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);

  await page.route("**/api/capture/url", async (route) => {
    if (routeMode === "502") {
      await route.fulfill({
        status: 502,
        contentType: "application/json",
        body: JSON.stringify({ detail: "simulated upstream failure" }),
      });
    } else if (routeMode === "200-ok") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          title: "Recovered fetch",
          body: "summary after retry",
          source: "https://example.com/after-retry",
          hostname: "example.com",
          summary_failed: false,
        }),
      });
    } else {
      // "200-degraded"
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          title: "example.com",
          body: "raw extracted body content",
          source: "https://example.com/will-degrade",
          hostname: "example.com",
          summary_failed: true,
          summary_error:
            "InternalServerError('Error code: 503 - auth_unavailable')",
        }),
      });
    }
  });

  await runTest("P3.a: 502 from /capture/url surfaces error + Retry button", async () => {
    await page.keyboard.press("Meta+Shift+V");
    await page.waitForTimeout(300);
    const urlInput = page.locator('[data-testid="capture-url-input"]');
    await urlInput.fill("https://example.com/will-fail");
    await page.locator('[data-testid="capture-fetch"]').click();
    const err = page.locator('[data-testid="capture-error"]');
    await err.waitFor({ state: "visible", timeout: 5000 });
    const text = await err.innerText();
    assert(text.length > 0, `error message should be visible: "${text}"`);
    // No capsule.
    const capCount = await page
      .locator('[data-testid="capture-capsule"]')
      .count();
    assert(capCount === 0, "no capsule when fetch failed");
  });

  await runTest("P3.b: Retry returns to empty state; second fetch succeeds", async () => {
    // Look for any visible "retry" button (button text or aria-label).
    // The retry path in CaptureBox resets to the empty state, then
    // user re-enters URL and re-clicks fetch.
    const retryBtn = page.getByRole("button").filter({
      hasText: /retry|重试/i,
    });
    await retryBtn.first().click();
    await page.waitForTimeout(300);
    // Now flip route to succeed for the second call.
    routeMode = "200-ok";
    const urlInput = page.locator('[data-testid="capture-url-input"]');
    await urlInput.fill("https://example.com/will-succeed");
    await page.locator('[data-testid="capture-fetch"]').click();
    const capsule = page.locator('[data-testid="capture-capsule"]');
    await capsule.waitFor({ state: "visible", timeout: 5000 });
    const capText = await capsule.innerText();
    assert(
      capText.includes("Recovered fetch"),
      `recovered capsule rendered: got "${capText.slice(0, 80)}"`,
    );
  });

  // Track how many times the route has been hit (for the retry
  // test below — first call = degraded, second call = recovered).
  let degradedCallCount = 0;
  await page.unroute("**/api/capture/url");
  await page.route("**/api/capture/url", async (route) => {
    if (routeMode === "502") {
      await route.fulfill({
        status: 502,
        contentType: "application/json",
        body: JSON.stringify({ detail: "simulated upstream failure" }),
      });
    } else if (routeMode === "200-ok") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          title: "Recovered fetch",
          body: "summary after retry",
          source: "https://example.com/after-retry",
          hostname: "example.com",
          summary_failed: false,
        }),
      });
    } else if (routeMode === "200-degraded-then-ok") {
      degradedCallCount += 1;
      if (degradedCallCount === 1) {
        // First call: summary failed.
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            title: "Article",
            body: "raw page text",
            source: "https://example.com/will-recover",
            hostname: "example.com",
            summary_failed: true,
            summary_error: "InternalServerError('503 auth_unavailable')",
          }),
        });
      } else {
        // Second call (retry): success.
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            title: "Article",
            body: "AI summary: this article is about ...",
            source: "https://example.com/will-recover",
            hostname: "example.com",
            summary_failed: false,
          }),
        });
      }
    } else {
      // "200-degraded"
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          title: "example.com",
          body: "raw extracted body content",
          source: "https://example.com/will-degrade",
          hostname: "example.com",
          summary_failed: true,
          summary_error:
            "InternalServerError('Error code: 503 - auth_unavailable')",
        }),
      });
    }
  });

  // Regression for 2026-05-22 dogfood: when /capture/url returns
  // summary_failed=true with summary_error set, the UI must show
  // BOTH the generic "summary failed" line AND the underlying
  // error message. The original UI only showed the generic line,
  // leaving the user unable to diagnose root cause.
  await runTest(
    "P3.d: Retry summary recovers from summary_failed → clean capsule",
    async () => {
      await page.keyboard.press("Escape");
      await page.waitForTimeout(300);
      routeMode = "200-degraded-then-ok";
      degradedCallCount = 0;
      await page.keyboard.press("Meta+Shift+V");
      await page.waitForTimeout(300);
      const urlInput = page.locator('[data-testid="capture-url-input"]');
      await urlInput.fill("https://example.com/will-recover");
      await page.locator('[data-testid="capture-fetch"]').click();
      // First response: degraded (summary_failed=true).
      await page
        .locator('[data-testid="capture-summary-failed"]')
        .waitFor({ state: "visible", timeout: 5000 });
      const retryBtn = page.locator(
        '[data-testid="capture-retry-summary"]',
      );
      await retryBtn.waitFor({ state: "visible", timeout: 1000 });
      // Click retry → second response: clean.
      await retryBtn.click();
      // summary_failed warning must DISAPPEAR after retry.
      const warnGoneCount = await page
        .locator('[data-testid="capture-summary-failed"]')
        .count();
      // It could take a tick for the new capsule to render.
      await page.waitForTimeout(800);
      const warnAfter = await page
        .locator('[data-testid="capture-summary-failed"]')
        .count();
      assert(
        warnAfter === 0,
        `summary_failed warning gone after retry succeeds, got ${warnAfter}`,
      );
      // New capsule body present.
      const capsule = page.locator('[data-testid="capture-capsule"]');
      const capText = await capsule.innerText();
      assert(
        capText.includes("AI summary"),
        `recovered summary visible: got "${capText.slice(0, 100)}"`,
      );
    },
  );

  await runTest(
    "P3.c: degraded capsule surfaces summary_error root cause",
    async () => {
      // Close the existing modal first.
      await page.keyboard.press("Escape");
      await page.waitForTimeout(300);
      routeMode = "200-degraded";
      await page.keyboard.press("Meta+Shift+V");
      await page.waitForTimeout(300);
      const urlInput = page.locator('[data-testid="capture-url-input"]');
      await urlInput.fill("https://example.com/will-degrade");
      await page.locator('[data-testid="capture-fetch"]').click();
      // Capsule appears with the "summary failed" warning.
      const warn = page.locator(
        '[data-testid="capture-summary-failed"]',
      );
      await warn.waitFor({ state: "visible", timeout: 5000 });
      const errRow = page.locator(
        '[data-testid="capture-summary-error"]',
      );
      await errRow.waitFor({ state: "visible", timeout: 1000 });
      const errText = await errRow.innerText();
      assert(
        errText.includes("auth_unavailable") ||
          errText.includes("503"),
        `summary_error surfaces root cause: got "${errText.slice(0, 120)}"`,
      );
      // Capsule body still renders (graceful degrade).
      const capsule = page.locator('[data-testid="capture-capsule"]');
      const capText = await capsule.innerText();
      assert(
        capText.includes("raw extracted body content"),
        `raw body still shown for triage: got "${capText.slice(0, 80)}"`,
      );
    },
  );

  await runTest("no unexpected console errors during the suite", () => {
    // P3.a deliberately triggers a 502 → client logs the fetch
    // failure. That's expected; filter it.
    assertConsoleClean(env, {
      allowMessages: [/502/, /Failed to load resource/i],
    });
  });
} finally {
  await teardown();
}

exitAfter();
