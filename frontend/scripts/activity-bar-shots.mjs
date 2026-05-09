// Capture the new VS Code-style activity bar.
import { mkdirSync } from "node:fs";
import { setupTestEnv } from "./e2e/_fixture.mjs";

const OUT = "/tmp/knowlet-activity";
mkdirSync(OUT, { recursive: true });

const env = await setupTestEnv({
  folders: ["projects", "personal"],
  notes: [
    { title: "alpha", folder: "projects", body: "x" },
    { title: "diary 1", folder: "personal", body: "x" },
    { title: "daily", folder: "_templates", body: "## {{title}}" },
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

    // Notes view
    await page.locator('[data-testid="activity-bar-notes"]').click();
    await page.waitForTimeout(200);
    await page.screenshot({
      path: `${OUT}/${theme}-1-notes.png`,
      clip: { x: 0, y: 0, width: 360, height: 600 },
    });

    // Tags view
    await page.locator('[data-testid="activity-bar-tags"]').click();
    await page.waitForTimeout(200);
    await page.screenshot({
      path: `${OUT}/${theme}-2-tags.png`,
      clip: { x: 0, y: 0, width: 360, height: 600 },
    });

    // Templates view
    await page.locator('[data-testid="activity-bar-templates"]').click();
    await page.waitForTimeout(200);
    await page.screenshot({
      path: `${OUT}/${theme}-3-templates.png`,
      clip: { x: 0, y: 0, width: 360, height: 600 },
    });
  }

  console.log("done — see " + OUT);
} finally {
  await teardown();
}
