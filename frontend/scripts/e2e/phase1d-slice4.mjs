/**
 * Phase 1 D slice 4 — multi-tab (basic version, D1).
 *
 * Verifies:
 *   - Tab strip is hidden when 0 notes are open (boot state).
 *   - Clicking a note in the tree opens a tab + activates it.
 *   - Clicking a second note adds a second tab; first tab persists.
 *   - Clicking the first tab activates it (NoteView swaps).
 *   - ✕ closes a tab; falls back to neighbor for active.
 *   - localStorage persistence: tabs survive a reload.
 *   - Deleting a note auto-closes its tab (tree-prune effect).
 */

import { assert, exitAfter, runTest, setupTestEnv } from "./_fixture.mjs";

const env = await setupTestEnv({
  notes: [
    { title: "Alpha", body: "alpha body" },
    { title: "Beta", body: "beta body" },
    { title: "Gamma", body: "gamma body" },
  ],
  language: "en",
});
const { page, baseURL, teardown } = env;

async function clickTreeRow(title) {
  await page
    .locator('[role="treeitem"]', { hasText: title })
    .first()
    .click();
  await page.waitForTimeout(250);
}

async function tabTitles() {
  return page.evaluate(() =>
    Array.from(document.querySelectorAll('[data-testid="tab"]')).map(
      (t) => (t.textContent ?? "").trim().replace(/×$/, "").trim(),
    ),
  );
}

async function activeTabTitle() {
  return page.evaluate(() => {
    const t = document.querySelector('[data-testid="tab"][data-active="true"]');
    return t ? (t.textContent ?? "").trim().replace(/×$/, "").trim() : null;
  });
}

try {
  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);

  await runTest("Tab strip hidden on boot (no tabs open)", async () => {
    const count = await page.locator('[data-testid="tab-strip"]').count();
    assert(count === 0, `tab strip should be hidden with 0 tabs, got ${count}`);
  });

  await runTest("Clicking Alpha opens a tab + activates it", async () => {
    await clickTreeRow("Alpha");
    await page
      .locator('[data-testid="tab-strip"]')
      .waitFor({ state: "visible", timeout: 2000 });
    const titles = await tabTitles();
    assert(
      titles.length === 1 && titles[0] === "Alpha",
      `expected 1 tab "Alpha", got ${JSON.stringify(titles)}`,
    );
    const active = await activeTabTitle();
    assert(active === "Alpha", `Alpha must be active, got ${active}`);
    // NoteView title h1 reflects active tab.
    const h1 = (await page.locator('[data-testid="note-title"]').first().textContent()) ?? "";
    assert(/Alpha/.test(h1), `note pane should show Alpha, got "${h1}"`);
  });

  await runTest("Clicking Beta appends a second tab", async () => {
    await clickTreeRow("Beta");
    const titles = await tabTitles();
    assert(
      titles.length === 2 && titles.includes("Alpha") && titles.includes("Beta"),
      `expected Alpha + Beta tabs, got ${JSON.stringify(titles)}`,
    );
    const active = await activeTabTitle();
    assert(active === "Beta", `Beta should be active after open, got ${active}`);
  });

  await runTest("Clicking the Alpha tab re-activates it without losing Beta", async () => {
    await page
      .locator('[data-testid="tab"]', { hasText: "Alpha" })
      .first()
      .click();
    await page.waitForTimeout(200);
    const active = await activeTabTitle();
    assert(active === "Alpha", `Alpha should be active after click, got ${active}`);
    const titles = await tabTitles();
    assert(titles.length === 2, `both tabs should remain, got ${JSON.stringify(titles)}`);
  });

  await runTest("Tabs survive a full reload (localStorage)", async () => {
    await page.reload({ waitUntil: "networkidle" });
    await page.waitForTimeout(500);
    const titles = await tabTitles();
    assert(
      titles.length === 2 && titles.includes("Alpha") && titles.includes("Beta"),
      `tabs lost across reload: ${JSON.stringify(titles)}`,
    );
    const active = await activeTabTitle();
    assert(active === "Alpha", `active state lost: ${active}`);
  });

  await runTest("✕ on Alpha closes it; Beta becomes active", async () => {
    await page
      .locator('[data-testid="tab-close"][data-note-id]')
      .first()
      .click(); // first tab in DOM = Alpha
    await page.waitForTimeout(200);
    const titles = await tabTitles();
    assert(
      titles.length === 1 && titles[0] === "Beta",
      `expected only Beta, got ${JSON.stringify(titles)}`,
    );
    const active = await activeTabTitle();
    assert(active === "Beta", `Beta should be active after close, got ${active}`);
  });

  await runTest("Closing the last tab hides the strip again", async () => {
    await page.locator('[data-testid="tab-close"]').first().click();
    await page.waitForTimeout(200);
    const count = await page.locator('[data-testid="tab-strip"]').count();
    assert(count === 0, `tab strip should be hidden after closing all, got ${count}`);
  });

  await runTest("Deleting a note auto-closes its tab", async () => {
    // Open Gamma in a tab.
    await clickTreeRow("Gamma");
    await page
      .locator('[data-testid="tab-strip"]')
      .waitFor({ state: "visible", timeout: 1500 });
    const before = await tabTitles();
    assert(before.includes("Gamma"), `Gamma should be open: ${JSON.stringify(before)}`);
    // Right-click → Delete via the context-menu path used elsewhere
    // in e2e is brittle; simpler: hit the API directly to delete the
    // note + invalidate the tree, mirroring what the FileTree
    // mutation does.
    const gammaId = await page.evaluate(async () => {
      const r = await fetch("/api/notes");
      const list = await r.json();
      return list.find((n) => n.title === "Gamma")?.id;
    });
    assert(gammaId, "couldn't resolve Gamma id");
    await page.evaluate(async (id) => {
      await fetch(`/api/notes/${id}`, { method: "DELETE" });
    }, gammaId);
    // Force a tree refetch so AppShell's prune effect runs.
    await page.evaluate(async () => {
      const qc = window.__queryClient ?? null;
      if (qc) await qc.invalidateQueries({ queryKey: ["tree"] });
      else {
        // Fallback: hard reload — same observable effect.
        location.reload();
      }
    });
    await page.waitForTimeout(800);
    const stripCount = await page.locator('[data-testid="tab-strip"]').count();
    assert(stripCount === 0, `tab strip should be hidden after delete, got ${stripCount}`);
  });

  await teardown();
  exitAfter(0);
} catch (e) {
  console.error("phase1d-slice4 e2e failed:", e);
  await teardown();
  exitAfter(1);
}
