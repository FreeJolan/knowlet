// E2E: Phase 3 Stage 4 B1 — 今日反思 entry.
//
// One click on the header "今日反思" button should open (or create)
// today's daily note AND open the discussion pane on it — the
// daily reflect-and-talk habit in a single gesture. Reuses the
// existing today-note quick action (default-seeded by the backend).

import {
  assert,
  assertConsoleClean,
  exitAfter,
  runTest,
  setupTestEnv,
} from "./_fixture.mjs";

const env = await setupTestEnv({ notes: [], folders: [], language: "zh" });
const { page, baseURL, teardown } = env;

function countNotes(tree) {
  const root = (tree.notes ?? []).length;
  const inFolders = (tree.folders ?? []).reduce(
    (n, f) => n + (f.notes?.length ?? 0),
    0,
  );
  return root + inFolders;
}

try {
  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);

  await runTest("今日反思 opens today's note + discuss pane in one click", async () => {
    const before = countNotes(
      await (await page.request.get(`${baseURL}/api/tree`)).json(),
    );
    await page.locator('[data-testid="header-reflect-button"]').click();
    // The discussion pane opens, anchored to the freshly opened note.
    await page
      .locator('[data-testid="discuss-pane"]')
      .waitFor({ state: "visible", timeout: 5000 });
    // The title populates once the tree refetch lands (a beat after create).
    await page.waitForFunction(
      () => {
        const el = document.querySelector(
          '[data-testid="discuss-anchor-title"]',
        );
        const t = el && el.textContent ? el.textContent.trim() : "";
        return t.length > 0 && t !== "—";
      },
      { timeout: 5000 },
    );
    // A daily note was created.
    const after = countNotes(
      await (await page.request.get(`${baseURL}/api/tree`)).json(),
    );
    assert(after > before, `a daily note was created (before=${before}, after=${after})`);
  });

  await runTest("clicking 今日反思 again is idempotent (same day → one note)", async () => {
    const before = countNotes(
      await (await page.request.get(`${baseURL}/api/tree`)).json(),
    );
    // Close pane first so the click is unambiguous, then re-trigger.
    await page.locator('[data-testid="discuss-close"]').click().catch(() => {});
    await page.waitForTimeout(200);
    await page.locator('[data-testid="header-reflect-button"]').click();
    await page
      .locator('[data-testid="discuss-pane"]')
      .waitFor({ state: "visible", timeout: 5000 });
    const after = countNotes(
      await (await page.request.get(`${baseURL}/api/tree`)).json(),
    );
    assert(after === before, `same-day re-run must not pile up notes (before=${before}, after=${after})`);
  });

  await runTest("no console errors", () => assertConsoleClean(env));
} finally {
  await teardown();
}

exitAfter();
