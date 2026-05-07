/**
 * Phase 1 C slice 3 — Graph view (rail tab + focus mode).
 *
 * Verifies the React surface; force-directed layout itself is a
 * library concern (react-force-graph-2d). We assert structure +
 * interactions, not pixel positions.
 */

import { assert, exitAfter, runTest, setupTestEnv } from "./_fixture.mjs";

const env = await setupTestEnv({
  notes: [
    { title: "Alpha", body: "See [[Beta]] and [[Gamma]] for details." },
    { title: "Beta", body: "Refers back to [[Alpha]]." },
    { title: "Gamma", body: "Standalone reference page." },
    { title: "Orphan", body: "Nothing here." },
  ],
  language: "en",
});
const { page, baseURL, teardown } = env;

async function clickRow(title) {
  const escaped = title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const row = page
    .locator(".group")
    .filter({ hasText: new RegExp(`^${escaped}$`) })
    .first();
  await row.waitFor({ state: "visible", timeout: 3000 });
  await row.click();
  await page.waitForTimeout(300);
}

try {
  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);

  await runTest("right rail has Backlinks + Graph tabs", async () => {
    await page
      .locator('[data-testid="rail-tab-backlinks"]')
      .waitFor({ state: "visible", timeout: 3000 });
    await page
      .locator('[data-testid="rail-tab-graph"]')
      .waitFor({ state: "visible", timeout: 1500 });
  });

  await runTest("header Graph button opens focus mode without a selected note", async () => {
    // No note selected yet — global graph entry must work via the
    // header button so the user isn't forced to pick a note first.
    await page.locator('[data-testid="header-graph-button"]').click();
    await page.waitForTimeout(400);
    await page
      .locator('[data-testid="graph-focus-mode"]')
      .waitFor({ state: "visible", timeout: 2000 });
    await page.keyboard.press("Escape");
    await page.waitForTimeout(200);
  });

  await runTest("clicking Graph tab loads /api/graph + renders canvas", async () => {
    await clickRow("Alpha");
    await page.locator('[data-testid="rail-tab-graph"]').click();
    await page.waitForTimeout(800); // force layout settle
    // react-force-graph-2d renders a <canvas>. With the rail tab being
    // ~340px wide, exactly one canvas should be present in the rail.
    const canvas = page.locator("canvas").first();
    await canvas.waitFor({ state: "visible", timeout: 3000 });
  });

  await runTest("rail Graph panel shows out/in degrees in footer", async () => {
    await clickRow("Alpha");
    await page.locator('[data-testid="rail-tab-graph"]').click();
    await page.waitForTimeout(600);
    // Alpha has 2 outbound (Beta, Gamma) and 1 inbound (from Beta).
    // The footer text contains "outbound" and "inbound" labels.
    const out = await page.locator("text=outbound").first().isVisible();
    const inb = await page.locator("text=inbound").first().isVisible();
    assert(out, "outbound label should be visible");
    assert(inb, "inbound label should be visible");
  });

  /** Ensure focus mode is closed before a test starts. */
  async function ensureFocusClosed() {
    const open = await page
      .locator('[data-testid="graph-focus-mode"]')
      .isVisible()
      .catch(() => false);
    if (open) {
      await page.keyboard.press("Escape");
      await page.waitForTimeout(250);
    }
  }

  await runTest("Cmd+Shift+G opens Graph focus mode", async () => {
    await ensureFocusClosed();
    await clickRow("Alpha");
    await page.keyboard.press("Meta+Shift+G");
    await page.waitForTimeout(500);
    const focus = page.locator('[data-testid="graph-focus-mode"]');
    await focus.waitFor({ state: "visible", timeout: 3000 });
    // Degree-sorted right rail in focus mode renders.
    const list = page.locator('[data-testid="graph-degree-list"]');
    await list.waitFor({ state: "visible", timeout: 2000 });
    const rows = list.locator('[data-testid="graph-degree-row"]');
    const count = await rows.count();
    assert(count >= 3, `expected ≥3 connected nodes — got ${count}`);
    await ensureFocusClosed();
  });

  await runTest("Esc closes Graph focus mode", async () => {
    await ensureFocusClosed();
    await page.keyboard.press("Meta+Shift+G");
    await page.waitForTimeout(400);
    await page
      .locator('[data-testid="graph-focus-mode"]')
      .waitFor({ state: "visible", timeout: 2000 });
    await page.keyboard.press("Escape");
    await page.waitForTimeout(300);
    const stillOpen = await page
      .locator('[data-testid="graph-focus-mode"]')
      .isVisible()
      .catch(() => false);
    assert(!stillOpen, "focus mode should close on Esc");
  });

  await runTest("'Focus mode' link in rail footer also opens it", async () => {
    await ensureFocusClosed();
    await clickRow("Alpha");
    await page.locator('[data-testid="rail-tab-graph"]').click();
    await page.waitForTimeout(500);
    await page.locator('[data-testid="graph-enter-focus"]').click();
    await page.waitForTimeout(400);
    await page
      .locator('[data-testid="graph-focus-mode"]')
      .waitFor({ state: "visible", timeout: 2000 });
    // Close again for clean state.
    await page.locator('[data-testid="graph-focus-close"]').click();
  });

  await runTest("clicking a degree-row in focus mode opens that note", async () => {
    await ensureFocusClosed();
    await page.keyboard.press("Meta+Shift+G");
    await page.waitForTimeout(400);
    const firstRow = page
      .locator('[data-testid="graph-degree-row"]')
      .first();
    await firstRow.waitFor({ state: "visible" });
    await firstRow.click();
    await page.waitForTimeout(500);
    const titleH1 = page.locator('[data-testid="note-title"]').first();
    await titleH1.waitFor({ state: "visible", timeout: 3000 });
    const titleText = (await titleH1.textContent()) ?? "";
    assert(
      /Alpha|Beta|Gamma/.test(titleText),
      `clicking degree row should open one of the connected notes (got "${titleText}")`,
    );
  });

  await teardown();
  exitAfter(0);
} catch (e) {
  console.error("graph e2e failed:", e);
  await teardown();
  exitAfter(1);
}
