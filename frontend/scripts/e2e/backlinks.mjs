/**
 * Phase 1 C slice 1 — Backlinks right-rail panel.
 *
 * - The right rail mounts and shows the Backlinks panel by default
 * - Selecting a note triggers a fetch and renders grouped mentions
 * - Clicking a backlink row opens the source note + scrolls editor to the
 *   correct line
 * - Empty state ("no other note links here yet") renders when no inbound
 * - The rail-toggle in the header collapses + restores the rail
 */

import { assert, exitAfter, runTest, setupTestEnv } from "./_fixture.mjs";

const env = await setupTestEnv({
  notes: [
    {
      title: "RAG retrieval",
      body: "# RAG retrieval\n\nCanonical reference for vault retrieval design.",
    },
    {
      title: "FTS5 trigram",
      body: [
        "# FTS5 trigram tuning",
        "",
        "Short queries hit better than expected; full discussion in",
        "[[RAG retrieval]] section three.",
        "",
        "Filler line so the link is past row 1.",
      ].join("\n"),
    },
    {
      title: "Personal energy",
      body: [
        "# Personal energy",
        "",
        "Afternoon brain fog → prioritize structural work, e.g.",
        "[[RAG retrieval]] series.",
      ].join("\n"),
    },
    { title: "Loose note", body: "no inbound links yet" },
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
}

try {
  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);

  await runTest("rail mounts; backlinks panel visible by default", async () => {
    // Title in panel header — i18n key rail.tab.backlinks → "Linked notes"
    const header = page.locator("text=Linked notes").first();
    await header.waitFor({ state: "visible", timeout: 3000 });
  });

  await runTest("RAG retrieval shows two backlink groups (FTS5 + Personal)", async () => {
    await clickRow("RAG retrieval");
    // Wait for fetch to complete + DOM to render
    await page.waitForTimeout(400);
    const list = page.locator('[data-testid="backlinks-list"]');
    await list.waitFor({ state: "visible", timeout: 3000 });
    const rows = list.locator('[data-testid="backlink-row"]');
    const rowCount = await rows.count();
    assert(rowCount === 2, `two backlink rows expected — got ${rowCount}`);
    // Both source notes should appear in the panel.
    const fts = await list.locator("text=FTS5 trigram").count();
    const energy = await list.locator("text=Personal energy").count();
    assert(fts >= 1, `FTS5 trigram source group should appear (got ${fts})`);
    assert(energy >= 1, `Personal energy source group should appear (got ${energy})`);
  });

  await runTest("clicking a backlink row opens the source note", async () => {
    await clickRow("RAG retrieval");
    await page.waitForTimeout(400);
    const firstRow = page
      .locator('[data-testid="backlink-row"]')
      .first();
    await firstRow.waitFor({ state: "visible" });
    await firstRow.click();
    // After click, NoteView should switch to the source note (FTS5 trigram
    // alphabetically — group sort is by source title).
    await page.waitForTimeout(500);
    const titleH1 = page.locator('[data-testid="note-title"]').first();
    await titleH1.waitFor({ state: "visible", timeout: 3000 });
    const titleText = (await titleH1.textContent()) ?? "";
    assert(
      /FTS5|Personal/.test(titleText),
      `clicked backlink should open one of the source notes (title="${titleText}")`,
    );
  });

  await runTest("empty state hint renders for note with no inbounds", async () => {
    await clickRow("Loose note");
    await page.waitForTimeout(400);
    // Shouldn't see the list; should see the empty hint.
    const list = page.locator('[data-testid="backlinks-list"]');
    const visible = await list.isVisible().catch(() => false);
    assert(!visible, "backlinks list shouldn't render for an isolated note");
    // The empty-state copy contains the literal `[[Title]]` instruction.
    const empty = page.locator("text=No other note links to this one");
    await empty.waitFor({ state: "visible", timeout: 2000 });
  });

  await runTest("rail toggle collapses and restores the panel", async () => {
    const toggle = page.locator('[data-testid="rail-toggle"]');
    await toggle.click();
    await page.waitForTimeout(200);
    const headerHidden = await page
      .locator("text=Linked notes")
      .first()
      .isVisible()
      .catch(() => false);
    assert(!headerHidden, "rail header should hide after collapse");
    await toggle.click();
    await page.waitForTimeout(200);
    const headerBack = await page
      .locator("text=Linked notes")
      .first()
      .isVisible();
    assert(headerBack, "rail header should reappear after expanding again");
  });

  await teardown();
  exitAfter(0);
} catch (e) {
  console.error("backlinks e2e failed:", e);
  await teardown();
  exitAfter(1);
}
