// Capture current state for the "+ 新建文档 dialog + DnD redesign" Claude
// Design handoff. Saves PNGs into /tmp/knowlet-newdoc/.
//
// Frames:
//   01-header-icons-light.png  current header with LayoutTemplate icon
//                              jammed among graph/trash/settings
//   02-templates-dialog-light  current "Templates" modal (the place users
//                              currently pick a template from)
//   03-after-create-light      after picking a template — new note has
//                              jumped into root; user must move it
//   04-tree-deep-light         a deep tree (depth ≥ 4) so designer can
//                              see indent ambiguity
//   05-drag-indicator-light    current drag-over visual (hopefully) — at
//                              minimum the static "selected" state for
//                              reference
//   01-05 dark variants
//
// Uses the e2e fixture for an isolated, predictable vault state.

import { mkdirSync } from "node:fs";
import { setupTestEnv } from "./e2e/_fixture.mjs";

const OUT = "/tmp/knowlet-newdoc";
mkdirSync(OUT, { recursive: true });

const env = await setupTestEnv({
  // Deep nesting so the depth ambiguity is visually obvious.
  folders: [
    "projects",
    "projects/ai",
    "projects/ai/papers",
    "projects/ai/papers/2026",
    "projects/web",
    "personal",
    "personal/journal",
  ],
  notes: [
    { title: "Attention Mechanism", folder: "projects/ai/papers/2026", body: "Self-attention notes." },
    { title: "RAG basics", folder: "projects/ai/papers", body: "RAG paper notes." },
    { title: "ai overview", folder: "projects/ai", body: "ai field overview" },
    { title: "site refactor", folder: "projects/web", body: "web project plan" },
    { title: "morning thoughts", folder: "personal/journal", body: "journal" },
    { title: "root note", body: "free-floating note" },
  ],
  language: "en",
});
const { page, baseURL, teardown } = env;

// Seed a sample template via the API so the templates dialog has something
// to show.
async function seedTemplate() {
  await page.evaluate(async () => {
    // Templates are notes in _templates/. Create one via the regular
    // create-note endpoint with folder=_templates won't work (forbidden),
    // so use POST /api/notes which respects a `folder=_templates` arg.
    await fetch("/api/notes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: "meeting-notes",
        folder: "_templates",
        body:
          "# {{date}} 会议\n\n## 与会人\n\n## 议题\n\n## 决议\n\n## TODO\n",
        tags: [],
      }),
    });
  });
  await page.waitForTimeout(300);
  await page.evaluate(async () => {
    const r = await fetch("/api/tree");
    return r.json();
  });
}

try {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.waitForTimeout(800);

  await seedTemplate();
  await page.reload({ waitUntil: "networkidle" });
  await page.waitForTimeout(500);

  // Expand the deep folder chain so we can see depth.
  for (const folderText of ["projects", "projects/ai", "papers"]) {
    const row = page.locator('[role="treeitem"]', { hasText: folderText }).first();
    if (await row.count()) await row.click().catch(() => {});
    await page.waitForTimeout(150);
  }

  async function setTheme(theme) {
    await page.evaluate((t) => {
      document.documentElement.setAttribute("data-theme", t);
      try {
        window.localStorage.setItem("knowlet.theme.v1", t);
      } catch {}
    }, theme);
    await page.waitForTimeout(200);
  }

  for (const theme of ["light", "dark"]) {
    await setTheme(theme);

    // 01 — header icons (focus on the right cluster).
    await page.screenshot({
      path: `${OUT}/${theme}-01-header-icons.png`,
      clip: { x: 0, y: 0, width: 1440, height: 70 },
    });

    // Force-close any dialog from prior iteration.
    await page.keyboard.press("Escape").catch(() => {});

    // 04 — deep tree, no dialog open. Capture sidebar full height.
    await page.screenshot({
      path: `${OUT}/${theme}-04-tree-depth.png`,
      clip: { x: 0, y: 0, width: 320, height: 700 },
    });

    // 02 — open templates dialog and capture.
    const templatesBtn = page.locator('[data-testid="templates-button"]');
    if (await templatesBtn.count()) {
      await templatesBtn.click();
      await page.waitForTimeout(450);
      await page.screenshot({ path: `${OUT}/${theme}-02-templates-dialog.png` });

      // 03 — pick template → new note appears at root.
      const tmplItem = page.locator("button").filter({ hasText: "meeting-notes" }).first();
      if (await tmplItem.count()) {
        await tmplItem.click();
        await page.waitForTimeout(800);
        await page.screenshot({ path: `${OUT}/${theme}-03-after-create.png` });
      } else {
        // dialog might be different layout — capture as-is for context
        await page.screenshot({ path: `${OUT}/${theme}-03-after-create.png` });
      }
    }

    // 05 — start a DnD: try to capture mid-drag. Playwright's DnD via
    // mouse events; we hover with button held to keep the indicator on.
    await page.keyboard.press("Escape").catch(() => {});
    await page.waitForTimeout(200);
    const sourceRow = page
      .locator('[role="treeitem"]', { hasText: "ai overview" })
      .first();
    const targetRow = page
      .locator('[role="treeitem"]', { hasText: "personal" })
      .first();
    if ((await sourceRow.count()) && (await targetRow.count())) {
      const src = await sourceRow.boundingBox();
      const dst = await targetRow.boundingBox();
      if (src && dst) {
        await page.mouse.move(src.x + 60, src.y + 10);
        await page.mouse.down();
        await page.mouse.move(src.x + 60, src.y + 30, { steps: 6 });
        await page.mouse.move(dst.x + 80, dst.y + 12, { steps: 12 });
        await page.waitForTimeout(120);
        await page.screenshot({
          path: `${OUT}/${theme}-05-drag-indicator.png`,
          clip: { x: 0, y: 0, width: 320, height: 700 },
        });
        await page.mouse.up().catch(() => {});
      }
    }
  }

  console.log("done — see " + OUT);
} finally {
  await teardown();
}
