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
  });

  // -------- inline expand + Edit dialog (added 2026-05-22) --------

  await runTest("Click row title toggles inline body expansion", async () => {
    // Close panel first so re-open triggers refetch with the new
    // seeded draft.
    await page.keyboard.press("Escape");
    await page.waitForTimeout(200);
    await seedDraft({
      title: "Editable draft",
      body: "Original body text from capture.",
      kind: "reference",
    });
    await page.locator("body").click({ position: { x: 5, y: 5 } });
    await page.waitForTimeout(150);
    await page.keyboard.press("Meta+I");
    await page.waitForTimeout(500);
    const row = page
      .locator('[data-testid^="draft-row-"]')
      .filter({ hasText: "Editable draft" })
      .first();
    await row.waitFor({ state: "visible", timeout: 3000 });
    // Body should NOT be visible until expanded.
    const bodyLocator = row.locator('[data-testid^="draft-body-"]');
    let bodyCount = await bodyLocator.count();
    assert(bodyCount === 0, "body hidden initially");
    // Click title → expand.
    await row.locator('[data-testid^="draft-title-"]').click();
    await bodyLocator.waitFor({ state: "visible", timeout: 2000 });
    const bodyText = await bodyLocator.innerText();
    assert(
      bodyText.includes("Original body"),
      `body content shown: got "${bodyText.slice(0, 80)}"`,
    );
    // Click again → collapse.
    await row.locator('[data-testid^="draft-title-"]').click();
    await page.waitForTimeout(200);
    bodyCount = await bodyLocator.count();
    assert(bodyCount === 0, "body hidden after second click");
  });

  await runTest("Edit dialog updates draft title + body in place", async () => {
    const row = page
      .locator('[data-testid^="draft-row-"]')
      .filter({ hasText: "Editable draft" })
      .first();
    await row.locator('[data-testid^="draft-edit-"]').click();
    const dialog = page.locator('[data-testid="draft-edit-dialog"]');
    await dialog.waitFor({ state: "visible", timeout: 3000 });
    // Edit both fields.
    const titleInput = page.locator('[data-testid="draft-edit-title"]');
    await titleInput.fill("Edited title");
    const bodyInput = page.locator('[data-testid="draft-edit-body"]');
    await bodyInput.fill("Refined body content.");
    // Save (NOT approve).
    await page.locator('[data-testid="draft-edit-save"]').click();
    // Wait for the row to re-render with the new title.
    await page
      .locator('[data-testid^="draft-row-"]')
      .filter({ hasText: "Edited title" })
      .waitFor({ state: "visible", timeout: 3000 });
    // Original title should be gone.
    const oldCount = await page
      .locator('[data-testid^="draft-row-"]')
      .filter({ hasText: "Editable draft" })
      .count();
    assert(oldCount === 0, "original title gone after rename");
  });

  await runTest("Save & Approve writes the (edited) draft as a Note", async () => {
    const row = page
      .locator('[data-testid^="draft-row-"]')
      .filter({ hasText: "Edited title" })
      .first();
    await row.locator('[data-testid^="draft-edit-"]').click();
    await page
      .locator('[data-testid="draft-edit-dialog"]')
      .waitFor({ state: "visible", timeout: 3000 });
    // Tweak once more then Save & Approve.
    const bodyInput = page.locator('[data-testid="draft-edit-body"]');
    await bodyInput.fill("Final body, ready to approve.");
    await page
      .locator('[data-testid="draft-edit-save-approve"]')
      .click();
    // Dialog closes, row vanishes.
    await page
      .locator('[data-testid^="draft-row-"]')
      .filter({ hasText: "Edited title" })
      .waitFor({ state: "detached", timeout: 5000 });
    // Note exists in /api/tree.
    const tree = await (
      await page.request.get(`${baseURL}/api/tree`)
    ).json();
    const titles = (tree.notes ?? []).map((n) => n.title);
    assert(
      titles.includes("Edited title"),
      `Save & Approve wrote a Note: got ${JSON.stringify(titles)}`,
    );
    // beta from the earlier archive test should still not be a Note.
    assert(
      !titles.includes("Test draft beta"),
      `archived draft must not have leaked into notes: ${JSON.stringify(titles)}`,
    );
  });
} finally {
  await teardown();
}

exitAfter();
