// E2E: Stage 3 P3 — URL fetch failure + Retry recovery.
//
// Intercepts /api/capture/url at the network layer (no real outbound
// HTTP needed) and serves a 502 → frontend should render the error
// UI with a Retry button; clicking Retry re-attempts and succeeds
// once the route is unblocked.

import { assert, exitAfter, runTest, setupTestEnv } from "./_fixture.mjs";

const env = await setupTestEnv({ notes: [], language: "en" });
const { page, baseURL, teardown } = env;

let failNextCapture = true;

try {
  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);

  // Intercept the capture endpoint. First call fails 502; once
  // ``failNextCapture`` flips false, requests pass through so the
  // Retry path can succeed on a synthetic body.
  await page.route("**/api/capture/url", async (route) => {
    if (failNextCapture) {
      await route.fulfill({
        status: 502,
        contentType: "application/json",
        body: JSON.stringify({ detail: "simulated upstream failure" }),
      });
    } else {
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
    failNextCapture = false;
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
} finally {
  await teardown();
}

exitAfter();
