// Smoke test: open http://localhost:5173, verify tree renders + interaction
// works. Saves a screenshot for human review.

import { chromium } from "playwright";

const URL = process.env.URL ?? "http://localhost:5173";

const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 } });
const page = await ctx.newPage();

const errors = [];
page.on("console", (m) => {
  if (m.type() === "error" || m.type() === "warning") {
    errors.push({ type: m.type(), text: m.text() });
  }
});
page.on("pageerror", (e) => errors.push({ type: "pageerror", text: String(e) }));

const resp = await page.goto(URL, { waitUntil: "networkidle", timeout: 15000 });
console.log(`HTTP ${resp.status()} ${URL}`);
await page.waitForTimeout(800);

const initialRows = await page.locator(".group").count();
console.log("rows visible (default-open):", initialRows);

// Toggle by clicking the row body (the entire row should respond, not just
// the chevron icon). Pick any open folder row — its row text is the folder
// name; click it once and expect the visible row count to drop because the
// folder's children fold up.
const openFolderRow = page
  .locator(".group")
  .filter({ hasText: /^archive|^projects|^1$|^2025/ })
  .first();
if ((await openFolderRow.count()) > 0) {
  await openFolderRow.click();
  await page.waitForTimeout(180);
  const rowsAfterCollapse = await page.locator(".group").count();
  console.log("rows after one row-click:", rowsAfterCollapse);
  if (rowsAfterCollapse >= initialRows) {
    console.log("ERR: row click did not collapse the folder");
    process.exitCode = 1;
  }
  // Click again to re-expand
  await openFolderRow.click();
  await page.waitForTimeout(180);
  const rowsAfterReExpand = await page.locator(".group").count();
  console.log("rows after re-expand:", rowsAfterReExpand);
  if (rowsAfterReExpand !== initialRows) {
    console.log("ERR: re-expand did not restore row count");
    process.exitCode = 1;
  }
}

const sidebar = page.locator('[data-slot="resizable-panel"]').first();
const box = await sidebar.boundingBox();
const widthPct = box ? Math.round((box.width / 1400) * 100) : 0;
console.log(`sidebar width: ${box?.width}px (${widthPct}%)`);
// Px-anchored: ~280 px default at 1400-wide viewport, with a 160 px floor.
if (box && (box.width < 260 || box.width > 320)) {
  console.log(
    `WARN: sidebar width ${box.width}px outside 260..320 band for 1400px window`,
  );
}

// Pick a row, hover, take a screenshot for visual review.
const firstNote = page.locator(".group").filter({ hasText: /design|hello|idea/ }).first();
if ((await firstNote.count()) > 0) {
  await firstNote.click({ button: "right" });
  await page.waitForTimeout(200);
  const menuTexts = await page.locator('[role="menuitem"]').allInnerTexts();
  console.log("context menu items:", menuTexts.map((s) => s.trim()).join(" | "));
  if (menuTexts.some((s) => /Move to root|移到根/i.test(s))) {
    console.log("ERR: Move-to-root item still present");
    process.exitCode = 1;
  }
  await page.keyboard.press("Escape");
  await page.waitForTimeout(150);
}

await page.waitForTimeout(400);
const vaultHeading = (await page.locator("header + div span").first().textContent()) ?? "";
console.log("sidebar heading text:", vaultHeading.trim());

// Save a sidebar-only screenshot at 2x for the agent / human to compare.
const screenshotPath = process.env.SCREENSHOT_PATH ?? "/tmp/knowlet-sidebar.png";
await page.locator("header").first().screenshot({ path: "/tmp/knowlet-header.png" });
const sidebarPanel = page.locator('[data-slot="resizable-panel"]').first();
await sidebarPanel.screenshot({ path: screenshotPath });
console.log("sidebar screenshot:", screenshotPath);

console.log("---");
console.log("console errors / warnings:", errors.length);
for (const e of errors) console.log(" ", e.type, e.text);

await browser.close();
process.exit(
  initialRows === 0 || errors.some((e) => e.type === "pageerror") ? 1 : (process.exitCode ?? 0),
);
