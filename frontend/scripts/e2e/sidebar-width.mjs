// E2E: sidebar default width is px-anchored, not a flat percentage.
// 220 px target, 160 px floor, 40% cap.

import { assert, exitAfter, runTest, setupTestEnv } from "./_fixture.mjs";

async function checkAtViewport(width, expectedRange, label) {
  const env = await setupTestEnv({
    notes: [{ title: "n", folder: "f" }],
    folders: ["f"],
    language: "en",
  });
  const { page, browser, baseURL, teardown } = env;
  // Re-size the viewport AFTER setup (default fixture uses 1400×900).
  await page.setViewportSize({ width, height: 900 });
  try {
    await page.goto(baseURL, { waitUntil: "networkidle" });
    await page.waitForTimeout(400);
    const box = await page
      .locator('[data-slot="resizable-panel"]')
      .first()
      .boundingBox();
    const px = box?.width ?? 0;
    await runTest(`sidebar at ${width}px viewport — ${label}`, async () => {
      assert(
        px >= expectedRange[0] && px <= expectedRange[1],
        `expected ${expectedRange[0]}..${expectedRange[1]} px, got ${px} px`,
      );
    });
    if (env.errors.length > 0) {
      console.log(`✗ no console errors at ${width}`);
      for (const e of env.errors) console.log("  ", e.type, e.text);
      process.exitCode = 1;
    }
  } finally {
    await teardown();
    void browser;
  }
}

// 1400px: should land near 220px default.
await checkAtViewport(1400, [200, 240], "default ≈ 220 px");
// 800px: 220px would be 27.5% which is fine; should still get ~220px.
await checkAtViewport(800, [200, 240], "still ≈ 220 px on narrow viewport");
// 480px: 220 would be 45% (exceeds 40% cap); falls to 40% = 192px.
// But 192px > 160 floor so we accept somewhere in 160..220 band.
await checkAtViewport(480, [150, 220], "narrow window — capped at 40%");

exitAfter();
