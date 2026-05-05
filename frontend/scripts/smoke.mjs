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

const firstFolderChevron = page.locator('button[aria-label="collapse"]').first();
const hasChevron = (await firstFolderChevron.count()) > 0;
console.log("collapse chevron present:", hasChevron);
if (hasChevron) {
  await firstFolderChevron.click();
  await page.waitForTimeout(150);
  const rowsAfterCollapse = await page.locator(".group").count();
  console.log("rows after one collapse:", rowsAfterCollapse);
  if (rowsAfterCollapse >= initialRows) console.log("WARN: collapse did not reduce row count");
  const expandBtn = page.locator('button[aria-label="expand"]').first();
  if ((await expandBtn.count()) > 0) {
    await expandBtn.click();
    await page.waitForTimeout(150);
  }
}

const sidebar = page.locator('[data-slot="resizable-panel"]').first();
const box = await sidebar.boundingBox();
const widthPct = box ? Math.round((box.width / 1400) * 100) : 0;
console.log(`sidebar width: ${box?.width}px (${widthPct}%)`);

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
