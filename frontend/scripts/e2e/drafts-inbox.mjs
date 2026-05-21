// E2E: Phase 3 Stage 3 — Drafts focus mode (⌘I).
//
// Pre-seeds drafts via /api/capture/decide (no network required —
// the capsule is supplied directly), opens ⌘I, exercises the row
// actions and the empty state.

import { assert, exitAfter, runTest, setupTestEnv } from "./_fixture.mjs";

const env = await setupTestEnv({
  notes: [],
  folders: [],
  language: "en",
});
const { page, baseURL, teardown } = env;

async function seedDraft({ title, body, kind = "reference" }) {
  const r = await page.request.post(`${baseURL}/api/capture/decide`, {
    data: {
      capsule: { title, body, source: null },
      decision: "defer",
      defer_kind: kind,
    },
  });
  if (!r.ok())
    throw new Error(
      `seedDraft failed: ${r.status()} ${await r.text()}`,
    );
  return await r.json();
}

try {
  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);

  await runTest("Cmd+I opens Drafts focus mode (empty state visible)", async () => {
    await page.locator("body").click();
    await page.waitForTimeout(100);
    await page.keyboard.press("Meta+I");
    await page.waitForTimeout(300);
    const panel = page.locator('[data-testid="drafts-focus-mode"]');
    await panel.waitFor({ state: "visible", timeout: 3000 });

    // Playwright's `state: "visible"` only checks DOM + size +
    // display/visibility — it accepts transparent panels and
    // panels covered by higher-z-index siblings. Verify the panel
    // is **actually opaque + on top** by:
    //   (a) elementFromPoint at center lands on the panel (z-stack OK)
    //   (b) computed background-color is non-transparent (so the
    //       main UI doesn't bleed through — the original 2026-05-22
    //       bug was `var(--bg-0)` which doesn't exist, silently
    //       resolving to transparent).
    const visualCheck = await page.evaluate(() => {
      const panel = document.querySelector('[data-testid="drafts-focus-mode"]');
      if (!panel) return { onTop: false, opaque: false, bg: null };
      const r = panel.getBoundingClientRect();
      const cx = Math.round(r.left + r.width / 2);
      const cy = Math.round(r.top + r.height / 2);
      const hit = document.elementFromPoint(cx, cy);
      const onTop = !!hit && (hit === panel || panel.contains(hit));
      const bg = getComputedStyle(panel).backgroundColor;
      const opaque =
        bg !== "" &&
        bg !== "transparent" &&
        !/rgba\([^)]+,\s*0\s*\)/.test(bg) &&
        bg !== "rgb(0, 0, 0)" /* defensive — JSDOM-style unset */;
      return { onTop, opaque, bg };
    });
    assert(
      visualCheck.onTop,
      "Drafts panel center is the topmost hit element (z-index OK)",
    );
    assert(
      visualCheck.opaque,
      `Drafts panel background must be opaque, got "${visualCheck.bg}"`,
    );

    const empty = page.locator('[data-testid="drafts-empty"]');
    await empty.waitFor({ state: "visible", timeout: 1500 });
    // Empty hint mentions the capture shortcut.
    const text = await empty.innerText();
    assert(
      text.includes("⌘⇧V"),
      `empty state teaches the capture shortcut: got "${text.slice(0, 80)}"`,
    );
  });

  await runTest("Escape closes Drafts focus mode", async () => {
    await page.keyboard.press("Escape");
    await page.waitForTimeout(300);
    const panel = page.locator('[data-testid="drafts-focus-mode"]');
    const visible = await panel.isVisible().catch(() => false);
    assert(!visible, "panel hidden after Escape");
  });

  await runTest("Seeded drafts render with KindChip + title + age", async () => {
    await seedDraft({
      title: "Test draft alpha",
      body: "Content A",
      kind: "reference",
    });
    await seedDraft({
      title: "Test draft beta",
      body: "Content B",
      kind: "knowledge",
    });
    // Reset focus to body so the global Cmd+I hotkey fires reliably
    // (after Escape from the previous test, focus may be elsewhere).
    await page.locator("body").click({ position: { x: 5, y: 5 } });
    await page.waitForTimeout(150);
    await page.keyboard.press("Meta+I");
    await page.waitForTimeout(600);
    // Verify panel opened. If it didn't, the rows won't be there.
    const panel = page.locator('[data-testid="drafts-focus-mode"]');
    await panel.waitFor({ state: "visible", timeout: 3000 });
    // Both rows visible.
    const alpha = page
      .locator('[data-testid^="draft-row-"]')
      .filter({ hasText: "Test draft alpha" });
    const beta = page
      .locator('[data-testid^="draft-row-"]')
      .filter({ hasText: "Test draft beta" });
    await alpha.waitFor({ state: "visible", timeout: 3000 });
    await beta.waitFor({ state: "visible", timeout: 3000 });
    // alpha is reference, beta is knowledge — check chip kind via data attr.
    const alphaChip = alpha.locator('[data-kind="reference"]');
    const betaChip = beta.locator('[data-kind="knowledge"]');
    await alphaChip.waitFor({ state: "visible", timeout: 1000 });
    await betaChip.waitFor({ state: "visible", timeout: 1000 });
  });

  await runTest("Approve row converts the draft to a Note", async () => {
    const alpha = page
      .locator('[data-testid^="draft-row-"]')
      .filter({ hasText: "Test draft alpha" })
      .first();
    // Approve button inside this row.
    await alpha
      .locator('[data-testid^="draft-approve-"]')
      .click();
    // Wait for the row to vanish (mutation + invalidate + refetch
    // + re-render can take ~1s in CI). Use waitFor instead of a
    // fixed sleep so we don't flake on slow runs.
    await page
      .locator('[data-testid^="draft-row-"]')
      .filter({ hasText: "Test draft alpha" })
      .waitFor({ state: "detached", timeout: 5000 });
    // Note should exist in /api/tree.
    const tree = await (
      await page.request.get(`${baseURL}/api/tree`)
    ).json();
    const titles = (tree.notes ?? []).map((n) => n.title);
    assert(
      titles.includes("Test draft alpha"),
      `Approve wrote a Note: tree=${JSON.stringify(titles)}`,
    );
  });

  await runTest("Archive row removes the draft from the list", async () => {
    const beta = page
      .locator('[data-testid^="draft-row-"]')
      .filter({ hasText: "Test draft beta" })
      .first();
    await beta
      .locator('[data-testid^="draft-reject-"]')
      .click();
    await page
      .locator('[data-testid^="draft-row-"]')
      .filter({ hasText: "Test draft beta" })
      .waitFor({ state: "detached", timeout: 5000 });
    // Should NOT be in /api/tree (archive only removes from active queue).
    const tree = await (
      await page.request.get(`${baseURL}/api/tree`)
    ).json();
    const titles = (tree.notes ?? []).map((n) => n.title);
    assert(
      !titles.includes("Test draft beta"),
      `archive should NOT promote to Note: tree=${JSON.stringify(titles)}`,
    );
  });
} finally {
  await teardown();
}

exitAfter();
