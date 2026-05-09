// Capture Slice 2b visuals — indent guides + ghost selection sync.
import { mkdirSync } from "node:fs";
import { setupTestEnv } from "./e2e/_fixture.mjs";

const OUT = "/tmp/knowlet-slice2b";
mkdirSync(OUT, { recursive: true });

const env = await setupTestEnv({
  folders: [
    "projects",
    "projects/ai",
    "projects/ai/papers",
    "projects/ai/papers/2026",
    "personal",
    "personal/journal",
  ],
  notes: [
    {
      title: "attention",
      folder: "projects/ai/papers/2026",
      body: "self-attention",
    },
    { title: "scaling", folder: "projects/ai/papers/2026", body: "scaling" },
    { title: "morning", folder: "personal/journal", body: "j" },
    { title: "loose", body: "root note" },
  ],
  language: "en",
});
const { page, baseURL, teardown } = env;

try {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.waitForTimeout(800);

  for (const theme of ["light", "dark"]) {
    await page.evaluate((t) => {
      document.documentElement.setAttribute("data-theme", t);
      try {
        window.localStorage.setItem("knowlet.theme.v1", t);
      } catch {}
    }, theme);
    await page.waitForTimeout(200);

    // 1 — passive (no dialog)
    await page.keyboard.press("Escape").catch(() => {});
    await page.waitForTimeout(200);
    await page.screenshot({
      path: `${OUT}/${theme}-1-passive-guides.png`,
      clip: { x: 0, y: 0, width: 320, height: 700 },
    });

    // 2 — dialog open, ghost target = projects/ai/papers/2026
    await page.keyboard.press("Meta+N");
    await page
      .locator('[data-testid="new-document-dialog"]')
      .waitFor({ state: "visible" });
    await page.locator('[data-testid="dialog-folder-picker"]').click();
    await page
      .locator(
        '[data-testid="dialog-folder-option"][data-folder="projects/ai/papers/2026"]',
      )
      .click();
    await page.waitForTimeout(300);
    await page.screenshot({
      path: `${OUT}/${theme}-2-ghost-deep.png`,
      // Capture both tree + dialog edge.
      clip: { x: 0, y: 0, width: 900, height: 800 },
    });

    // 3 — switch to personal
    await page.locator('[data-testid="dialog-folder-picker"]').click();
    await page
      .locator(
        '[data-testid="dialog-folder-option"][data-folder="personal"]',
      )
      .click();
    await page.waitForTimeout(300);
    await page.screenshot({
      path: `${OUT}/${theme}-3-ghost-shallow.png`,
      clip: { x: 0, y: 0, width: 900, height: 800 },
    });

    await page.keyboard.press("Escape");
    await page.waitForTimeout(200);
  }

  console.log("done — see " + OUT);
} finally {
  await teardown();
}
