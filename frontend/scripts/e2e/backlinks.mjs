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
    {
      title: "With dangling",
      body: "Some pre-context here.\nThis note refers to [[Nonexistent Target]].",
    },
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

  await runTest("rail mounts; both sections appear when note is open", async () => {
    // Title in panel header — i18n key rail.tab.backlinks → "Linked notes"
    const header = page.locator("text=Linked notes").first();
    await header.waitFor({ state: "visible", timeout: 3000 });
    // Section headers only render when a note is selected (no-note state
    // is a single placeholder).
    await clickRow("RAG retrieval");
    await page.waitForTimeout(300);
    await page
      .locator('[data-testid="rail-inbound-header"]')
      .waitFor({ state: "visible", timeout: 1500 });
    await page
      .locator('[data-testid="rail-outbound-header"]')
      .waitFor({ state: "visible", timeout: 1500 });
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

  await runTest("empty inbound message renders for note with no inbounds", async () => {
    await clickRow("Loose note");
    await page.waitForTimeout(400);
    // The empty-state copy contains the literal `[[Title]]` instruction.
    const empty = page.locator("text=No other note links to this one");
    await empty.waitFor({ state: "visible", timeout: 2000 });
  });

  await runTest("Outbound section lists each [[Target]] in current note body", async () => {
    // FTS5 trigram references RAG retrieval once.
    await clickRow("FTS5 trigram");
    await page.waitForTimeout(400);
    const outList = page.locator('[data-testid="outbound-list"]');
    await outList.waitFor({ state: "visible", timeout: 3000 });
    const rows = outList.locator('[data-testid="outbound-row"]');
    const count = await rows.count();
    assert(count === 1, `expected 1 outbound row from FTS5 trigram — got ${count}`);
    const dangling = await rows.first().getAttribute("data-dangling");
    assert(dangling === "0", `RAG retrieval is a real note — should NOT be dangling (got ${dangling})`);
  });

  await runTest("clicking an outbound row opens the target note", async () => {
    await clickRow("FTS5 trigram");
    await page.waitForTimeout(400);
    const firstRow = page.locator('[data-testid="outbound-row"]').first();
    await firstRow.click();
    await page.waitForTimeout(500);
    const titleH1 = page.locator('[data-testid="note-title"]').first();
    const titleText = (await titleH1.textContent()) ?? "";
    assert(
      /RAG retrieval/.test(titleText),
      `outbound click should open the target note (title="${titleText}")`,
    );
  });

  await runTest("dangling [[Missing]] target renders broken state", async () => {
    // "With dangling" note links to [[Nonexistent Target]] which isn't
    // in the seed — we add a note inline below; for now, navigate to
    // the test note and check.
    await clickRow("With dangling");
    await page.waitForTimeout(400);
    const danglingRow = page
      .locator('[data-testid="outbound-row"][data-dangling="1"]')
      .first();
    await danglingRow.waitFor({ state: "visible", timeout: 3000 });
    // Click should be a no-op (button disabled).
    const tag = await danglingRow.evaluate((el) => el.tagName.toLowerCase());
    assert(tag === "button", "dangling row should be a <button>");
    const disabled = await danglingRow.isDisabled();
    assert(disabled, "dangling row should be disabled");
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
