// E2E: Stage 3 P9 (age signals) + P10 (soft-limit warning).
//
// Both require seeding drafts with controlled created_at — done by
// writing the draft markdown directly into the test vault's drafts/
// dir. The capture-decide API doesn't accept a custom timestamp.

import fs from "node:fs";
import path from "node:path";

import { assert, exitAfter, runTest, setupTestEnv } from "./_fixture.mjs";

const env = await setupTestEnv({ notes: [], language: "en" });
const { page, baseURL, vaultDir, teardown } = env;

function writeDraftFile({ id, title, body, kind = "reference", daysAgo = 0 }) {
  const draftsDir = path.join(vaultDir, "drafts");
  fs.mkdirSync(draftsDir, { recursive: true });
  const created = new Date(Date.now() - daysAgo * 86400_000).toISOString();
  const slug = title.toLowerCase().replace(/[^a-z0-9]+/g, "-").slice(0, 40);
  const fname = `${id}-${slug}.md`;
  const front = [
    "---",
    "schema_version: 1",
    `id: ${id}`,
    `title: ${title}`,
    "tags: []",
    `kind: ${kind}`,
    `created_at: ${created}`,
    `updated_at: ${created}`,
    "status: draft",
    "---",
  ].join("\n");
  fs.writeFileSync(path.join(draftsDir, fname), `${front}\n${body}\n`);
}

async function openPanelFresh() {
  // Hard-reset panel + caches so the new seeded files are read.
  await page.keyboard.press("Escape");
  await page.waitForTimeout(200);
  await page.locator("body").click({ position: { x: 5, y: 5 } });
  await page.waitForTimeout(150);
  await page.keyboard.press("Meta+I");
  await page.waitForTimeout(600);
}

try {
  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);

  // ---------------------- P9 — stale row muted

  await runTest(
    "P9: stale draft (≥7 days) muted; fresh draft full opacity",
    async () => {
      writeDraftFile({
        id: "01STALE0001",
        title: "Stale ten days",
        body: "old",
        daysAgo: 10,
      });
      writeDraftFile({
        id: "01FRESH0001",
        title: "Fresh today",
        body: "new",
        daysAgo: 0,
      });
      await openPanelFresh();

      const staleOpacity = await page
        .locator('[data-testid="draft-row-01STALE0001"]')
        .evaluate((el) => getComputedStyle(el).opacity);
      const freshOpacity = await page
        .locator('[data-testid="draft-row-01FRESH0001"]')
        .evaluate((el) => getComputedStyle(el).opacity);

      assert(
        parseFloat(staleOpacity) < 0.7,
        `stale row should be muted, got opacity ${staleOpacity}`,
      );
      assert(
        parseFloat(freshOpacity) > 0.95,
        `fresh row should be full opacity, got ${freshOpacity}`,
      );

      // ALSO assert the data-stale attribute is correct (a probe
      // separate from opacity, in case the CSS variable changes).
      const staleAttr = await page
        .locator('[data-testid="draft-row-01STALE0001"]')
        .getAttribute("data-stale");
      assert(
        staleAttr === "true",
        `data-stale=true expected, got ${staleAttr}`,
      );
    },
  );

  // ---------------------- P9 — warn-age banner

  await runTest("P9: warn-age draft (≥30 days) shows banner", async () => {
    writeDraftFile({
      id: "01WARN0001",
      title: "Aging thirty five days",
      body: "...",
      daysAgo: 35,
    });
    await openPanelFresh();
    const banner = page.locator(
      '[data-testid="draft-warn-age-01WARN0001"]',
    );
    await banner.waitFor({ state: "visible", timeout: 3000 });
  });

  // ---------------------- P10 — soft limit at >20

  await runTest(
    "P10: >20 active drafts → soft limit banner visible at top",
    async () => {
      // Already have a few from prior tests; seed enough to push >20.
      for (let i = 0; i < 21; i++) {
        writeDraftFile({
          id: `01SOFT0${String(i).padStart(4, "0")}`,
          title: `Soft limit fixture ${i}`,
          body: "x",
        });
      }
      await openPanelFresh();
      const warn = page.locator('[data-testid="drafts-soft-limit"]');
      await warn.waitFor({ state: "visible", timeout: 3000 });
      const text = await warn.innerText();
      // Must mention the live count so the user knows the threshold
      // is informational, not arbitrary.
      assert(
        /\d+/.test(text),
        `soft-limit text should mention live count, got "${text}"`,
      );
    },
  );
} finally {
  await teardown();
}

exitAfter();
