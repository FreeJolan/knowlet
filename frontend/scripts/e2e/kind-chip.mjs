// E2E: Phase 3 Stage 2 — KindChip (knowledge / reference).
//
// Covers ADR-0029 §4.5 asymmetric upgrade contract:
//   - reference → knowledge: instant click, no confirm.
//   - knowledge → reference: popover requires confirm; cancel keeps it.
// Plus the ⌘⇧K global shortcut on each direction.

import {
  assert,
  assertConsoleClean,
  exitAfter,
  runTest,
  setupTestEnv,
} from "./_fixture.mjs";

const env = await setupTestEnv({
  notes: [{ title: "kind chip test note", body: "body" }],
  folders: [],
  language: "en",
});
const { page, baseURL, teardown } = env;

try {
  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);

  // Open the seeded note via the file tree.
  const row = page
    .locator(".group")
    .filter({ hasText: "kind chip test note" })
    .first();
  await row.waitFor({ state: "visible", timeout: 5000 });
  await row.click();
  await page.waitForTimeout(300);
  // NoteView mounted — wait for the chip.
  const knowledgeChip = page.locator(
    '[data-testid="kind-chip-knowledge"]',
  );
  const referenceChip = page.locator(
    '[data-testid="kind-chip-reference"]',
  );
  await knowledgeChip.waitFor({ state: "visible", timeout: 3000 });

  await runTest("Default kind on a manual-created note is knowledge", async () => {
    const visible = await knowledgeChip.isVisible();
    assert(visible, "knowledge chip visible on default note");
  });

  await runTest("Click knowledge chip opens demote popover (no instant change)", async () => {
    const btn = page.locator(
      '[data-testid="kind-chip-knowledge-button"]',
    );
    await btn.click();
    const popover = page.locator(
      '[data-testid="kind-chip-demote-popover"]',
    );
    await popover.waitFor({ state: "visible", timeout: 1500 });
    // Cancel — kind must stay knowledge.
    await page.locator('[data-testid="kind-chip-demote-cancel"]').click();
    await page.waitForTimeout(300);
    const stillKnowledge = await knowledgeChip.isVisible();
    assert(stillKnowledge, "knowledge chip still visible after Cancel");
  });

  await runTest("Demote popover Confirm changes kind to reference", async () => {
    await page
      .locator('[data-testid="kind-chip-knowledge-button"]')
      .click();
    await page
      .locator('[data-testid="kind-chip-demote-popover"]')
      .waitFor({ state: "visible", timeout: 1500 });
    await page
      .locator('[data-testid="kind-chip-demote-confirm"]')
      .click();
    // Wait for mutation + cache update.
    await referenceChip.waitFor({ state: "visible", timeout: 3000 });
  });

  await runTest("Reference → knowledge is instant (no popover)", async () => {
    // Wait for any in-flight popover state from the previous test to
    // settle before clicking the new chip.
    await page.waitForTimeout(300);
    const btn = page.locator(
      '[data-testid="kind-chip-reference-button"]',
    );
    await btn.click();
    // The chip should flip directly. No popover content should appear
    // during/after this click. Wait 400ms then check.
    await page.waitForTimeout(400);
    await knowledgeChip.waitFor({ state: "visible", timeout: 3000 });
    const popoverCount = await page
      .locator('[data-testid="kind-chip-demote-popover"]')
      .count();
    assert(
      popoverCount === 0,
      `no popover for upgrade — found ${popoverCount} popover(s)`,
    );
  });

  await runTest(
    "Cmd+Shift+K on knowledge focuses chip (preserves popover guard)",
    async () => {
      // Currently knowledge. ⌘⇧K should NOT instantly demote (anti-drift
      // guard is preserved — it dispatches click which opens popover).
      // Ensure focus is OUT of any input first so the global hotkey fires.
      await page.locator("body").click();
      await page.waitForTimeout(100);
      await page.keyboard.press("Meta+Shift+K");
      // Popover takes a moment to mount + animate in.
      const popover = page.locator(
        '[data-testid="kind-chip-demote-popover"]',
      );
      await popover.waitFor({ state: "visible", timeout: 2000 });
      await page
        .locator('[data-testid="kind-chip-demote-cancel"]')
        .click();
      await page.waitForTimeout(200);
    },
  );

  await runTest("Cmd+Shift+K on reference is instant upgrade", async () => {
    // Demote first via popover so we have a reference note.
    await page
      .locator('[data-testid="kind-chip-knowledge-button"]')
      .click();
    await page
      .locator('[data-testid="kind-chip-demote-popover"]')
      .waitFor({ state: "visible", timeout: 1500 });
    await page
      .locator('[data-testid="kind-chip-demote-confirm"]')
      .click();
    await referenceChip.waitFor({ state: "visible", timeout: 3000 });
    // Now ⌘⇧K should instantly upgrade.
    await page.keyboard.press("Meta+Shift+K");
    await knowledgeChip.waitFor({ state: "visible", timeout: 3000 });
  });

  await runTest("no console errors during the suite", () => {
    assertConsoleClean(env);
  });
} finally {
  await teardown();
}

exitAfter();
